"""Read-only content health. Warnings never authorize a release or replace its checks."""
import argparse
import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from data_schema import validate_board, validate_breakdowns
from reviewed_publication import PREFIX, revision, tree
from verify_publication import NoRedirect, PRODUCTION, wait_ready
from weekly_schedule import forecast_deadline, kickoff, utc, utc_now


class MissingFile(RuntimeError):
    pass


def read_public(url):
    """No credentials, redirects, writes or unbounded responses."""
    if not url.startswith(PRODUCTION + '/'):
        raise ValueError('Only the fixed production origin is permitted')
    try:
        with build_opener(NoRedirect).open(Request(url, headers={
                'User-Agent': 'NFL-PM-read-only-health', 'Cache-Control': 'no-cache'}), timeout=20) as response:
            if response.status != 200:
                raise RuntimeError('Non-200 public response')
            raw = response.read(20_000_001)
            if len(raw) > 20_000_000:
                raise RuntimeError('Oversized public response')
            return raw
    except HTTPError as exc:
        if exc.code == 404:
            raise MissingFile('Expected public file is missing') from None
        raise RuntimeError('Public HTTP/access/redirect error') from None
    except Exception:
        raise RuntimeError('Public network/response error') from None


def health(expected, commit, now=None, fetch=read_public, deployment_check=None, season=None, week=None):
    """Expected bytes must come from the exact reviewed production Git revision.

    Integrity checks cover every committed archive. Freshness warnings concern the
    selected snapshot only; missing optional pointers in legacy weeks are normal.
    """
    revision(commit)
    now = utc(now or utc_now())
    report = {'checked_at_utc': now.isoformat(), 'expected_commit': commit,
              'deployment': {'status': 'unverified'}, 'checks': [], 'snapshots': []}

    def note(kind, status, **details):
        report['checks'].append({'kind': kind, 'status': status, **details})

    if deployment_check:
        try:
            report['deployment'] = {'status': 'verified', **deployment_check(commit)}
        except Exception:
            note('deployment_error', 'error')
            report['deployment'] = {'status': 'failed'}
    else:
        note('deployment_access_not_supplied', 'unverified')
    try:
        shell = fetch(PRODUCTION + '/')
        if b'NFL PM' not in shell or b'/_next/' not in shell:
            note('website_unavailable_or_unexpected_page', 'error')
        else:
            note('website_http_shell', 'ok', message='HTTP shell only; not a browser runtime check')
    except Exception:
        note('website_http_error', 'error')
    verified = {}
    for name, raw in sorted(expected.items()):
        relative = name.removeprefix(PREFIX)
        if (not name.startswith(PREFIX) or PurePosixPath(relative).is_absolute()
                or '..' in PurePosixPath(relative).parts):
            raise ValueError('Unsafe expected data reference')
        try:
            served = fetch(PRODUCTION + '/data/' + relative)
        except MissingFile:
            note('missing_file', 'error', file=relative)
            continue
        except Exception:
            note('http_error', 'error', file=relative)
            continue
        if served != raw:
            note('hash_mismatch', 'error', file=relative)
            continue
        verified[name] = served
        note('content_hash', 'ok', file=relative, sha256=hashlib.sha256(served).hexdigest())
    try:
        if fetch(PRODUCTION + '/data/manifest.json') != expected[PREFIX + 'manifest.json']:
            note('manifest_changed_during_check', 'error')
    except Exception:
        note('manifest_recheck_failed', 'error')
    try:
        document = json.loads(expected[PREFIX + 'manifest.json'])
        if (season is None) != (week is None):
            raise ValueError('Both season and week required')
        if season is None:
            season = max(document['seasons'], key=int)
            weeks = document['seasons'][season]['weeks']
            week = max(weeks, key=lambda w: (utc(weeks[w]['generated_at']), int(w)))
        files = document['seasons'].get(str(season), {}).get('weeks', {}).get(str(week))
        if files is None:
            report['snapshots'].append({'season': season, 'week': week, 'state': 'expected_unavailable'})
        else:
            def read(reference):
                name = PREFIX + reference
                if name not in verified:
                    raise ValueError('Unverified manifest reference')
                return json.loads(verified[name])

            board, breakdowns = read(files['board']), read(files['breakdowns'])
            meta = board['meta']
            validate_board(board, int(season), int(week))
            validate_breakdowns(breakdowns, int(season), int(week), meta['games'])
            if not (meta['generated_at'] == files['generated_at'] == breakdowns['meta']['generated_at']):
                raise ValueError('Snapshot timestamp mismatch')
            stamps = [utc(meta['generated_at'])]
            receipt_ref = str(PurePosixPath(files['board']).with_name('receipt.json'))
            receipt = read(receipt_ref) if PREFIX + receipt_ref in expected else None
            if receipt:
                for name, key in [('board', 'board_sha256'), ('breakdowns', 'breakdowns_sha256')]:
                    if hashlib.sha256(verified[PREFIX + files[name]]).hexdigest() != receipt[key]:
                        raise ValueError('Receipt content mismatch')
                cutoff = utc(receipt['source_cutoff_utc'])
                if cutoff > stamps[0] or any(cutoff >= kickoff(g) for g in meta['games']):
                    raise ValueError('Invalid pregame cutoff')
                stamps.append(cutoff)
                envelope = receipt.get('input_capture')
                if envelope:
                    capture = envelope['manifest']
                    encoded = json.dumps(capture, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                    if (hashlib.sha256(encoded).hexdigest() != envelope['manifest_sha256']
                            or capture['source_cutoff_utc'] != receipt['source_cutoff_utc']
                            or capture.get('kind') != 'live_capture'):
                        raise ValueError('Invalid capture receipt')
                    for source in capture['sources'].values():
                        retrieved = utc(source['retrieved_at_utc'])
                        if not utc(capture['started_at_utc']) <= utc(source['started_at_utc']) <= retrieved <= cutoff:
                            raise ValueError('Source retrieved after cutoff or invalid interval')
                        if not source['available'] and not source['optional']:
                            raise ValueError('Missing required source')
                        stamps.append(retrieved)
                else:
                    note('legacy_capture_unavailable', 'warning')
            else:
                note('legacy_provenance_unavailable', 'warning')
            sidecars = {}
            for key, schema, receipt_key in [
                    ('game_predictor', 'game-predictor', 'game_predictor_sha256'),
                    ('matchup_intelligence', 'matchup-intelligence', 'matchup_intelligence_sha256')]:
                reference, pin = files.get(key), files.get(key + '_sha256')
                if reference is None and pin is None:
                    sidecars[key] = 'expected_unavailable'
                    continue
                if not reference or not pin or PREFIX + reference not in verified:
                    raise ValueError('Missing pinned sidecar')
                if hashlib.sha256(verified[PREFIX + reference]).hexdigest() != pin:
                    raise ValueError('Sidecar manifest hash mismatch')
                if receipt is None or receipt.get(receipt_key) != pin:
                    raise ValueError('Sidecar receipt binding mismatch')
                artifact = read(reference)
                from artifact_schema import validate_sidecar_schema
                validate_sidecar_schema(artifact, schema)
                if (artifact['meta']['season'] != int(season) or artifact['meta']['week'] != int(week)
                        or artifact['meta']['generated_at'] != meta['generated_at']):
                    raise ValueError('Sidecar snapshot mismatch')
                if key == 'game_predictor':
                    from game_projection_artifact import validate_artifact
                    validate_artifact(artifact, meta['games'], int(season), int(week), now=now)
                    if artifact['meta']['data_cutoff'] != receipt['source_cutoff_utc']:
                        raise ValueError('Game cutoff mismatch')
                    stamps.extend(utc(s['as_of']) for s in artifact['meta']['sources'].values())
                else:
                    from matchup_schema import validate_intelligence
                    validate_intelligence(artifact, board)
                    if artifact['meta']['data_as_of'] != receipt['source_cutoff_utc']:
                        raise ValueError('Intelligence cutoff mismatch')
                    stamps.extend(utc(s) for s in artifact['meta']['source_as_of'].values())
                sidecars[key] = 'present_verified'
            if any(stamp > now for stamp in stamps):
                raise ValueError('Future snapshot/cutoff')
            upcoming = [g for g in meta['games'] if kickoff(g) > now]
            if meta.get('snapshot_classification') == 'historical_backfill':
                state = 'historical_unavailable'
            elif not upcoming:
                state = 'archived'
            else:
                start = min(kickoff(g) for g in upcoming)
                deadline = min(forecast_deadline(stamp, start) for stamp in stamps)
                state = ('kickoff_margin' if start - now <= timedelta(minutes=10)
                         else 'stale' if now >= deadline else 'current')
                if state != 'current':
                    note(state, 'warning', message='Expected unavailable projections; no publication authorized')
            report['snapshots'].append({'season': int(season), 'week': int(week), 'state': state,
                                        'players': len(board['rows']), 'games': len(meta['games']),
                                        'generated_at': meta['generated_at'], 'sidecars': sidecars,
                                        'source_cutoff_utc': receipt['source_cutoff_utc'] if receipt else None})
    except Exception:
        note('invalid_snapshot_contract', 'error')
    # Detect deployment/alias movement just as the strict release verifier does.
    if deployment_check and report['deployment']['status'] == 'verified':
        try:
            if deployment_check(commit) != {k: v for k, v in report['deployment'].items() if k != 'status'}:
                note('deployment_changed_during_check', 'error')
        except Exception:
            note('deployment_recheck_failed', 'error')
    statuses = {item['status'] for item in report['checks']}
    report['status'] = ('ERROR' if 'error' in statuses else 'DEGRADED' if 'warning' in statuses
                        else 'UNKNOWN' if 'unverified' in statuses else 'HEALTHY')
    report['release_authorized'] = False
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--season', type=int)
    parser.add_argument('--week', type=int)
    parser.add_argument('--verify-deployment', action='store_true', help='Existing read-only Vercel access required')
    args = parser.parse_args()
    check = None
    if args.verify_deployment:
        token = os.environ.get('VERCEL_READ_TOKEN')
        if not token:
            raise SystemExit('Read-only deployment token unavailable; no action taken')
        check = lambda sha: wait_ready(sha, token, attempts=1)
    result = health(tree(Path.cwd(), args.expected_commit), args.expected_commit,
                    deployment_check=check, season=args.season, week=args.week)
    print(json.dumps(result, indent=2))
    return 1 if result['status'] == 'ERROR' else 0


if __name__ == '__main__':
    raise SystemExit(main())
