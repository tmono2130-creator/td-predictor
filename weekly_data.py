"""Captured weekly generation and exact offline replay. Never publishes or deploys."""
import argparse
import json
import traceback
from pathlib import Path
import pandas as pd

from weekly_capture import Capture, load_capture, local_root, encode, sha, write_new, source_url, schedule_rows, verified_schedule
from weekly_schedule import SCHEDULE_URL, plan_week, regular_games, kickoff, utc, utc_now
from weekly_sources import FreshSources
from weekly_generation import generate_candidate
from weekly_storage import digest, validate_candidate
from publication_policy import fresh
from roster_eligibility import select_weekly


class CapturedSources(FreshSources):
    """Existing source policies, backed exclusively by pinned files; no network fallback."""
    def __init__(self, root):
        super().__init__(fetchers={'offline': None})
        self.root = local_root(root)
        self.capture = load_capture(root)
        self.cutoff = utc(self.capture['source_cutoff_utc'])

    def get(self, name, season, optional=False):
        key = f'{name}_{season}'
        record = self.capture['sources'].get(key)
        if record is None or not record['available']:
            if not optional:
                raise ValueError('Required captured source missing: ' + key)
            self.metadata[f'{name}:{season}'] = {'available': False, 'reason': 'source unavailable in immutable capture'}
            return pd.DataFrame()
        if key not in self.cache:
            path = self.root / record['path']
            if digest(path) != record['sha256']:
                raise ValueError('Captured source changed during replay')
            if name == 'pbp':
                import pyarrow.parquet as parquet
                from weekly_sources import PBP_REQUIRED
                from game_projection import PBP_COLUMNS
                wanted = PBP_REQUIRED | PBP_COLUMNS | {'total_home_score', 'total_away_score', 'epa'}
                columns = set(parquet.ParquetFile(path).schema.names)
                self.cache[key] = pd.read_parquet(path, columns=sorted(columns & wanted))
            else:
                self.cache[key] = pd.read_parquet(path)
            self.metadata[f'{name}:{season}'] = {**record, 'rows': len(self.cache[key])}
        return self.cache[key].copy(deep=True)

    def schedule(self):
        record = self.capture['sources']['schedule']
        records = schedule_rows((self.root / record['path']).read_bytes())
        years = sorted({int(k.split('_')[1]) for k in self.capture['sources'] if k.startswith('pbp_')})
        return verified_schedule(records, {y: self.get('pbp', y) for y in years}, self.cutoff)


def capture_inputs(root, season=None, week=None):
    capture = Capture(root)
    raw = capture.fetch('schedule', SCHEDULE_URL)
    plan = plan_week(schedule_rows(raw), season=season, week=week)
    if plan['status'] != 'ready':
        raise ValueError('No eligible upcoming week to capture')
    year = plan['season']
    # All three prior seasons need verified final evidence, not merely populated scores.
    for y in range(year - 3, year + 1):
        capture.fetch(f'stats_{y}', source_url('stats', y))
        capture.fetch(f'pbp_{y}', source_url('pbp', y))
    weekly = capture.fetch(f'weekly_rosters_{year}', source_url('weekly_rosters', year), optional=True)
    target_available = weekly is not None and not select_weekly(pd.read_parquet(__import__('io').BytesIO(weekly)), year, plan['week']).empty
    if not target_available:
        capture.fetch(f'rosters_{year}', source_url('rosters', year))
    capture.fetch(f'players_{year}', source_url('players', year))
    capture.fetch(f'injuries_{year}', source_url('injuries', year), optional=True)
    capture.freeze()
    return plan['season'], plan['week']


def hashes(folder):
    return {p.name: digest(p) for p in sorted(Path(folder).iterdir()) if p.is_file()}


def build_from_capture(capture_root, destination, data_root, season, week, features=('matchup', 'game'), replay=False):
    from artifact_schema import validate_sidecar_schema
    from game_projection import prepare_team_games
    from game_projection_artifact import build_artifact, validate_artifact
    from game_projection_cli import attach
    from matchup_intelligence import build_intelligence
    from matchup_publication import validate_sidecar
    from matchup_cli import attach_artifact

    source = CapturedSources(capture_root)
    if not set(features).issubset({'game', 'matchup'}) or len(set(features)) != len(features):
        raise ValueError('Unsupported or duplicate requested feature')
    destination = local_root(destination)
    baseline = None
    if replay:
        baseline = json.loads((source.root / 'run.json').read_bytes())
        if baseline['season'] != season or baseline['week'] != week or baseline['features'] != list(features):
            raise ValueError('Replay configuration differs from original run')
        if baseline['base_manifest_sha256'] != digest(Path(data_root) / 'manifest.json'):
            raise ValueError('Replay base manifest differs')
        generated = utc(baseline['generated_at'])
    else:
        generated = None
    records = source.schedule()
    plan = plan_week(records, now=source.cutoff, season=season, week=week)
    if plan['status'] != 'ready' or any(kickoff(g) <= source.cutoff for g in plan['games']):
        raise ValueError('No remaining pregame targets at frozen cutoff')
    from weekly_capture import validate_envelope
    checked_at = generated if replay else utc_now()
    validate_envelope({'meta': {'season': season, 'games': plan['games'], 'generated_at': checked_at.isoformat()}},
                      {'source_cutoff_utc': source.cutoff.isoformat(),
                       'input_capture': {'manifest': source.capture, 'manifest_sha256': sha(encode(source.capture))}}, checked_at)
    # Fail on missing prior finals rather than silently shortening the training history.
    for g in regular_games(records, min_season=season - 3, max_season=season):
        if ((g['season'] < season or g['week'] < week) and kickoff(g) < source.cutoff and not g['complete']):
            raise ValueError('Unverified prior final game: ' + g['game_id'])
    # Retrieval finished before cutoff. Metadata now records original bytes and real capture times.
    generate_candidate(plan, records, source, destination, data_root, clock=(lambda: generated) if replay else utc_now)
    board, _, receipt = validate_candidate(destination, now=generated or utc_now())
    generated = utc(board['meta']['generated_at'])
    fresh(board, receipt, generated)
    target_ids = [g['game_id'] for g in plan['games']]
    status, unavailable = {'core': 'complete'}, {}
    histories, pbp = source.history(records, season, week, source.cutoff)
    if 'game' in features:
        try:
            past = [g for g in records if season - 1 <= int(g['season']) <= season
                    and (int(g['season']) < season or int(g['week']) < week)]
            table = prepare_team_games(past, pbp)
            parents = {k: v for k, v in source.capture['sources'].items() if k.startswith('pbp_') and int(k.split('_')[1]) >= season - 1}
            as_of = max(v['retrieved_at_utc'] for v in parents.values())
            provenance = {'schedule': {'as_of': source.capture['sources']['schedule']['retrieved_at_utc'],
                                      'sha256': source.capture['sources']['schedule']['sha256'], 'origin': SCHEDULE_URL},
                          'team_games': {'as_of': as_of, 'sha256': sha(table.to_csv(index=False).encode()),
                                         'origin': source_url('pbp', season)}}
            value = build_artifact(table, records, season, week, source.cutoff, provenance,
                                   generated_at=generated, target_ids=target_ids)
            validate_sidecar_schema(value, 'game-predictor')
            validate_artifact(value, board['meta']['games'], season, week, generated, publishing=True)
        except (ValueError, KeyError) as exc:
            unavailable['game'] = str(exc)
        else:
            path = destination.parent / (destination.name + '-game-input.json')
            write_new(path, encode(value))
            attach(destination, path, generated)
            status['game'] = 'complete'
    if 'matchup' in features:
        try:
            weekly = source.get('weekly_rosters', season, optional=True)
            if select_weekly(weekly, season, week).empty:
                raise ValueError('Target-week roster capture unavailable; season fallback cannot prove weekly membership')
            stamps = {name: source.capture['sources'][key]['retrieved_at_utc'] for name, key in
                      [('schedule', 'schedule'), ('pbp', f'pbp_{season}'), ('player_games', f'stats_{season}'),
                       ('weekly_rosters', f'weekly_rosters_{season}'), ('players', f'players_{season}')]}
            value = build_intelligence(board, records, source.get('pbp', season), histories[season], weekly,
                                       source.get('players', season), source.cutoff, generated_at=generated,
                                       source_as_of=stamps, target_ids=target_ids)
            validate_sidecar_schema(value, 'matchup-intelligence')
            path = destination.parent / (destination.name + '-matchup-input.json')
            raw = encode(value)
            # Validate completely before changing the candidate receipt or file set.
            write_new(path, raw)
            validate_sidecar(path, board, {'matchup_intelligence_sha256': sha(raw)}, generated)
        except (ValueError, KeyError) as exc:
            unavailable['matchup'] = str(exc)
        else:
            attach_artifact(destination, path, generated)
            status['matchup'] = 'complete'
    # Raw inputs stay outside the publishable bundle. Receipt carries the immutable capture envelope.
    receipt_path = destination / 'receipt.json'
    receipt = json.loads(receipt_path.read_bytes())
    receipt['input_capture'] = {'manifest': source.capture, 'manifest_sha256': sha(encode(source.capture))}
    receipt['bundle_status'] = {'core': 'complete', 'three_features': all(status.get(k) == 'complete' for k in ('game', 'matchup')),
                                'requested': list(features), 'available': sorted(status), 'unavailable': unavailable}
    # This is still an unpublished local candidate; never edit any archived receipt.
    temporary = destination / '.receipt-captured'
    write_new(temporary, encode(receipt))
    temporary.replace(receipt_path)
    validate_candidate(destination, now=generated if replay else utc_now())
    fresh(board, receipt, generated if replay else utc_now())
    result = {'season': season, 'week': week, 'generated_at': generated.isoformat(), 'features': list(features),
              'games_expected': len(plan['games']), 'games_generated': len(board['meta']['games']),
              'players_expected': len(receipt['eligible_players']), 'players_generated': len(board['rows']),
              'source_cutoff_utc': source.cutoff.isoformat(), 'base_manifest_sha256': receipt['base_manifest_sha256'],
              'capture_manifest_sha256': sha(encode(source.capture)), 'bundle_status': receipt['bundle_status'],
              'artifact_hashes': hashes(destination), 'published': False}
    if replay:
        if result != baseline:
            raise ValueError('Deterministic replay mismatch')
    else:
        write_new(source.root / 'run.json', encode(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('capture-generate', 'replay'))
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--data', type=Path, default=Path(__file__).parent / 'td-predictor-web/public/data')
    parser.add_argument('--season', type=int)
    parser.add_argument('--week', type=int)
    parser.add_argument('--features', choices=('core', 'game', 'matchup', 'all'), default='core')
    args = parser.parse_args(argv)
    features = () if args.features == 'core' else ('matchup', 'game') if args.features == 'all' else (args.features,)
    try:
        if args.command == 'capture-generate':
            season, week = capture_inputs(args.capture, args.season, args.week)
        else:
            prior = json.loads((local_root(args.capture) / 'run.json').read_bytes())
            season, week = args.season or prior['season'], args.week or prior['week']
        result = build_from_capture(args.capture, args.candidate, args.data, season, week, features, args.command == 'replay')
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        failure = {'published': False, 'error': type(exc).__name__, 'reason': str(exc)}
        audit = getattr(exc, 'audit', None)
        if audit:
            failure['roster_counts'] = audit['counts']
            failure['pending'] = [r for r in audit['decisions'] if r['decision'] == 'pending']
        print(json.dumps(failure, indent=2))
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
