"""Immutable, local-only source bytes and offline replay. No publication capability."""
import csv
import hashlib
import io
import json
import platform
import re
import subprocess
from importlib.metadata import version
from pathlib import Path
from urllib.request import Request, urlopen
from email.utils import parsedate_to_datetime

from publication_policy import REPOSITORY, is_live_path
from weekly_schedule import utc, utc_now

CODE_FILES = (
    'weekly_capture.py', 'weekly_data.py', 'weekly_sources.py', 'weekly_generation.py',
    'weekly_pipeline.py', 'weekly_schedule.py', 'weekly_storage.py', 'roster_eligibility.py', 'publication_policy.py',
    'td_predictor_v5.py', 'game_breakdown.py', 'export_json.py', 'data_schema.py',
    'game_projection.py', 'game_projection_artifact.py', 'matchup_intelligence.py',
    'matchup_schema.py', 'matchup_publication.py', 'artifact_schema.py', 'matchup_cli.py',
    'game_projection_cli.py', 'evaluation_utils.py', 'outcome_semantics.py',
    'requirements-automation.txt', 'requirements-validation.txt',
)
PACKAGES = ('nflreadpy', 'pandas', 'numpy', 'pyarrow', 'tzdata', 'jsonschema')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def local_root(path):
    path = Path(path).resolve()
    if is_live_path(path) or any(path.is_relative_to(REPOSITORY / p) for p in ('public', 'td-predictor-web/public')):
        raise ValueError('Capture/replay output must not be in served paths')
    return path


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def write_new(path, data):
    with Path(path).open('xb') as stream:
        stream.write(data)


def code_identity():
    return {name: sha((REPOSITORY / name).read_bytes()) for name in CODE_FILES}


def validate_revision(revision, repo=REPOSITORY):
    """A data-only descendant is valid; changed generator source requires fresh capture."""
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Invalid captured Git revision')
    ancestry = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', revision, 'HEAD'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if ancestry.returncode or subprocess.check_output(['git', '-C', str(repo), 'diff', revision, 'HEAD', '--', *CODE_FILES]):
        raise ValueError('Captured revision is not an unchanged-code ancestor; regenerate')


def dependencies():
    return {'python': platform.python_version(), **{name: version(name) for name in PACKAGES}}


def source_url(name, season):
    paths = {'stats': f'stats_player/stats_player_week_{season}', 'pbp': f'pbp/play_by_play_{season}',
             'weekly_rosters': f'weekly_rosters/roster_weekly_{season}', 'rosters': f'rosters/roster_{season}',
             'players': 'players/players', 'injuries': f'injuries/injuries_{season}'}
    return 'https://github.com/nflverse/nflverse-data/releases/download/' + paths[name] + '.parquet'


class Capture:
    def __init__(self, root, clock=utc_now, opener=urlopen):
        self.root = local_root(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.clock, self.opener, self.records = clock, opener, {}
        self.started = utc(clock())

    def fetch(self, key, url, optional=False):
        if key in self.records or not key.replace('_', '').isalnum():
            raise ValueError('Duplicate or unsafe capture key')
        started = utc(self.clock())
        try:
            with self.opener(Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'NFL-PM-capture/1'}), timeout=90) as response:
                if response.status != 200:
                    raise ValueError('Non-200 source response')
                data = response.read(300_000_001)
                headers = response.headers
            ended = utc(self.clock())
            if not data or len(data) > 300_000_000 or ended < started:
                raise ValueError('Invalid source response or clock regression')
            modified = parsedate_to_datetime(headers['Last-Modified']).astimezone(ended.tzinfo) if headers.get('Last-Modified') else None
            if modified and modified > ended:
                raise ValueError('Provider modification time is in the future')
            name = key + ('.csv' if key == 'schedule' else '.parquet')
            write_new(self.root / name, data)
            self.records[key] = {'path': name, 'url': url, 'sha256': sha(data), 'bytes': len(data),
                                 'started_at_utc': started.isoformat(), 'retrieved_at_utc': ended.isoformat(),
                                 'provider_modified_utc': modified.isoformat() if modified else None,
                                 'etag': headers.get('ETag'), 'optional': optional, 'available': True}
            return data
        except Exception as exc:
            # Retain evidence of failure, never a pretend empty required source.
            self.records[key] = {'url': url, 'available': False, 'optional': optional,
                                 'retrieved_at_utc': utc(self.clock()).isoformat(), 'reason': type(exc).__name__}
            if not optional:
                raise RuntimeError('Required capture failed: ' + key) from exc
            return None

    def freeze(self):
        cutoff = utc(self.clock())
        if not self.records or any(not r['available'] and not r['optional'] for r in self.records.values()):
            raise ValueError('Incomplete required input capture')
        if any(not self.started <= utc(r['retrieved_at_utc']) <= cutoff for r in self.records.values()):
            raise ValueError('Capture timestamps do not precede common cutoff')
        manifest = {'version': 1, 'kind': 'live_capture', 'started_at_utc': self.started.isoformat(),
                    'source_cutoff_utc': cutoff.isoformat(), 'sources': self.records,
                    'git_revision': subprocess.check_output(['git', '-C', str(REPOSITORY), 'rev-parse', 'HEAD'], text=True).strip(),
                    'code_sha256': code_identity(), 'dependencies': dependencies(),
                    'limitations': ['Capture time is not provider modification time',
                                    'Local clock and trusted capture execution are part of the provenance trust boundary']}
        write_new(self.root / 'capture.json', encode(manifest))
        return load_capture(self.root)


def load_capture(root, check_runtime=True):
    root = local_root(root)
    path = root / 'capture.json'
    if path.is_symlink():
        raise ValueError('Symlink capture manifest')
    manifest = json.loads(path.read_bytes())
    if manifest.get('version') != 1 or manifest.get('kind') != 'live_capture':
        raise ValueError('Unsupported or reconstructed input capture')
    if check_runtime and (manifest['code_sha256'] != code_identity() or manifest['dependencies'] != dependencies()):
        raise ValueError('Replay code or dependency versions differ from capture')
    cutoff, started = utc(manifest['source_cutoff_utc']), utc(manifest['started_at_utc'])
    if cutoff < started or cutoff > utc_now():
        raise ValueError('Invalid capture cutoff')
    expected = {'capture.json', 'run.json', 'failure.json'}
    for key, record in manifest['sources'].items():
        if not started <= utc(record['retrieved_at_utc']) <= cutoff:
            raise ValueError('Invalid captured source timestamp')
        if not record['available']:
            if not record['optional']:
                raise ValueError('Missing required source')
            continue
        expected.add(record['path'])
        file = root / record['path']
        if file.parent != root or file.is_symlink() or not file.is_file():
            raise ValueError('Unsafe captured source path')
        data = file.read_bytes()
        if len(data) != record['bytes'] or sha(data) != record['sha256']:
            raise ValueError('Captured source hash mismatch: ' + key)
        if record.get('provider_modified_utc') and utc(record['provider_modified_utc']) > utc(record['retrieved_at_utc']):
            raise ValueError('Provider timestamp exceeds retrieval')
    if any(p.name not in expected or p.is_symlink() or not p.is_file() for p in root.iterdir()):
        raise ValueError('Unexpected capture files')
    return manifest


def schedule_rows(data):
    return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))


def verified_schedule(records, pbps, cutoff):
    """Final scores require a captured END GAME event with matching terminal totals."""
    import copy
    import pandas as pd
    from weekly_schedule import kickoff, present
    out = copy.deepcopy(records)
    ends = {}
    for year, frame in pbps.items():
        if not {'game_id', 'play_id', 'desc', 'total_home_score', 'total_away_score'}.issubset(frame):
            raise ValueError('Missing terminal game-state evidence')
        terminal = frame[frame.desc.fillna('').str.strip().str.upper().eq('END GAME')]
        for gid, group in terminal.groupby('game_id'):
            group = group.sort_values('play_id')
            totals = {(float(r.total_home_score), float(r.total_away_score)) for r in group.itertuples()}
            if len(totals) != 1:
                raise ValueError('Conflicting terminal game scores')
            ends[gid] = totals.pop()
    for game in out:
        game.pop('game_status', None)
        game.pop('completion_evidence', None)
        if game['game_id'] in ends:
            home, away = ends[game['game_id']]
            if not (present(game.get('home_score')) and present(game.get('away_score'))
                    and home == float(game['home_score']) and away == float(game['away_score'])
                    and pd.notna(home) and pd.notna(away) and kickoff(game) < utc(cutoff)):
                raise ValueError('Schedule/terminal game result conflicts')
            game['completion_evidence'] = {'kind': 'pbp_end_game', 'home_score': home, 'away_score': away}
    return out


def validate_envelope(board, receipt, now):
    """Verify the portable capture receipt without needing private raw files in a data PR."""
    from datetime import timedelta
    from weekly_schedule import kickoff
    envelope = receipt['input_capture']
    manifest = envelope['manifest']
    if envelope['manifest_sha256'] != sha(encode(manifest)) or manifest.get('kind') != 'live_capture':
        raise ValueError('Input capture manifest hash/classification mismatch')
    pins = dict(line.strip().split('==') for line in (REPOSITORY / 'requirements-automation.txt').read_text().splitlines() if '==' in line)
    recorded = manifest.get('dependencies', {})
    # Validators do not need the network loader/Arrow installed just to inspect its recorded version.
    # Exact replay still requires every original dependency and the full Python patch version.
    compatible = (set(recorded) == {'python', *PACKAGES}
                  and recorded['python'].split('.')[:2] == platform.python_version().split('.')[:2]
                  and all(recorded.get(name) == pins.get(name) for name in PACKAGES)
                  and all(version(name) == pins[name] for name in ('pandas', 'numpy', 'tzdata', 'jsonschema')))
    if manifest.get('code_sha256') != code_identity() or not compatible:
        raise ValueError('Captured code/runtime differs; regenerate under reviewed source')
    validate_revision(manifest.get('git_revision'))
    cutoff = utc(receipt['source_cutoff_utc'])
    generated = utc(board['meta']['generated_at'])
    if cutoff != utc(manifest['source_cutoff_utc']) or not utc(manifest['started_at_utc']) <= cutoff <= generated <= utc(now):
        raise ValueError('Captured cutoff/generation timestamp mismatch')
    remaining = min(kickoff(g) for g in board['meta']['games']) - utc(now)
    limit = timedelta(minutes=30) if remaining <= timedelta(hours=6) else timedelta(hours=6) if remaining <= timedelta(hours=48) else timedelta(hours=24)
    season = board['meta']['season']
    required = {'schedule', f'players_{season}'} | {f'{kind}_{year}' for year in range(season-3, season+1) for kind in ('pbp', 'stats')}
    if not required.issubset(manifest['sources']) or any(not manifest['sources'][k]['available'] for k in required):
        raise ValueError('Required capture inventory is incomplete')
    if not any(manifest['sources'].get(f'{name}_{season}', {}).get('available') for name in ('weekly_rosters', 'rosters')):
        raise ValueError('Captured roster evidence missing')
    from weekly_schedule import SCHEDULE_URL
    for key, record in manifest['sources'].items():
        if key == 'schedule':
            expected_url = SCHEDULE_URL
        else:
            kind, year = key.rsplit('_', 1)
            expected_url = source_url(kind, int(year))
        if record['url'] != expected_url:
            raise ValueError('Unapproved captured source origin')
        captured = utc(record['retrieved_at_utc'])
        if not utc(manifest['started_at_utc']) <= captured <= cutoff or not timedelta(0) <= utc(now) - captured < limit:
            raise ValueError('Stale input capture or retrieval after common cutoff')
        if not record['available'] and not record['optional']:
            raise ValueError('Missing required captured source')
        if record['available'] and (not isinstance(record['sha256'], str) or len(record['sha256']) != 64):
            raise ValueError('Invalid raw source fingerprint')
        if record['available'] and not utc(manifest['started_at_utc']) <= utc(record['started_at_utc']) <= captured:
            raise ValueError('Invalid source retrieval interval')
        if record.get('provider_modified_utc') and utc(record['provider_modified_utc']) > captured:
            raise ValueError('Provider timestamp exceeds capture time')
