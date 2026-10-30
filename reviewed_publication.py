"""Trusted-base checks for data-only PRs; never executes proposed PR source."""
import argparse
import copy
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from weekly_pipeline import verify_current_schedule
from weekly_schedule import retrieve_schedule, utc, utc_now
from weekly_storage import validate_candidate, validate_manifest
from publication_policy import fresh as fresh
from matchup_publication import CORE_FILES, SIDECAR, bundle_files, manifest_fields

PREFIX = 'td-predictor-web/public/data/'
MANIFEST = PREFIX + 'manifest.json'
BUNDLE = CORE_FILES


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def revision(value):
    if not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('An exact commit SHA is required')
    return value


def tree(repo, sha):
    result = {}
    for entry in git(repo, 'ls-tree', '-rz', revision(sha), '--', PREFIX).split(b'\0'):
        if not entry:
            continue
        details, name = entry.split(b'\t', 1)
        mode, kind, oid = details.decode().split()
        name = name.decode('utf-8')
        relative = name.removeprefix(PREFIX)
        if (mode != '100644' or kind != 'blob' or not name.startswith(PREFIX)
                or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.json', relative)
                or any(p in {'.', '..'} for p in relative.split('/'))):
            raise ValueError('Unsafe data tree entry')
        if int(git(repo, 'cat-file', '-s', oid)) > 20_000_000:
            raise ValueError('Oversized JSON data file')
        result[name] = git(repo, 'cat-file', 'blob', oid)
    return result


def materialize(files, root):
    for name, data in files.items():
        target = Path(root) / name.removeprefix(PREFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def validate_change(repo, base, head, branch, records=None, now=None):
    revision(base); revision(head)
    if subprocess.call(['git', '-C', str(repo), 'merge-base', '--is-ancestor', base, head],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
        raise ValueError('Branch is behind current main; regenerate')
    changes = git(repo, 'diff', '--no-renames', '--name-only', '-z', base, head).decode().strip('\0').split('\0')
    if changes == ['']:
        raise ValueError('Empty publication diff')
    data_changes = [p for p in changes if p.startswith(PREFIX)]
    if not data_changes:
        if branch.startswith(('nfl-pm/publication/', 'nfl-pm/rollback/')):
            raise ValueError('Publication PR contains no data')
        return {'kind': 'source', 'changed_files': len(changes)}
    if len(changes) != len(data_changes):
        raise ValueError('Data PR cannot modify source or unrelated files')
    before, after = tree(repo, base), tree(repo, head)
    if MANIFEST not in before or MANIFEST not in after:
        raise ValueError('Existing and proposed manifests required')
    for name, data in before.items():
        if name != MANIFEST and after.get(name) != data:
            raise ValueError('Immutable snapshot modified or deleted')
    added = set(after) - set(before)
    # Use the caller's writable workspace rather than a host-specific temp ACL.
    with tempfile.TemporaryDirectory(dir=repo) as temporary:
        old_root, new_root = Path(temporary) / 'base', Path(temporary) / 'head'
        materialize(before, old_root); materialize(after, new_root)
        old_manifest = validate_manifest(old_root)
        manifest = validate_manifest(new_root)
        if re.fullmatch(r'nfl-pm/rollback/[A-Za-z0-9-]+', branch):
            if set(changes) != {MANIFEST} or added:
                raise ValueError('Rollback must change only manifest and retain archives')
            history = git(repo, 'rev-list', '--max-count=1000', base, '--', MANIFEST).decode().splitlines()
            if not any(git(repo, 'show', f'{sha}:{MANIFEST}') == after[MANIFEST] for sha in history):
                raise ValueError('Rollback manifest must match a previous main manifest exactly')
            return {'kind': 'rollback', 'manifest_sha256': hashlib.sha256(after[MANIFEST]).hexdigest()}
        if not re.fullmatch(r'nfl-pm/publication/[0-9]+-[0-9]+', branch):
            raise ValueError('Data updates require a publication or rollback branch')
        if len(added) not in (3, 4) or set(changes) != added | {MANIFEST}:
            raise ValueError('Publication must add one approved immutable bundle and change manifest')
        folders = {str(Path(p).parent).replace('\\', '/') for p in added}
        if len(folders) != 1 or {Path(p).name for p in added} not in (BUNDLE, BUNDLE | {SIDECAR}):
            raise ValueError('Unexpected publication bundle')
        folder = folders.pop().removeprefix(PREFIX)
        if not re.fullmatch(r'\d{4}/week-\d{1,2}/\d{8}T\d{6}Z-[0-9a-f]{12}', folder):
            raise ValueError('Invalid immutable snapshot path')
        now = utc(now or utc_now())
        board, _, receipt = validate_candidate(new_root / folder, now=now)
        if {Path(p).name for p in added} != bundle_files(receipt):
            raise ValueError('Receipt and publication file allowlist differ')
        if receipt.get('base_manifest_sha256') != hashlib.sha256(before[MANIFEST]).hexdigest():
            raise ValueError('Concurrent manifest change; regenerate')
        fresh(board, receipt, now)
        verify_current_schedule(board, retrieve_schedule() if records is None else records, now=now)
        meta = board['meta']
        if not folder.startswith(f"{meta['season']}/week-{meta['week']}/"):
            raise ValueError('Snapshot path differs from season/week')
        expected = copy.deepcopy(old_manifest)
        expected['seasons'].setdefault(str(meta['season']), {'weeks': {}})['weeks'][str(meta['week'])] = {
            'board': folder + '/board.json', 'breakdowns': folder + '/breakdowns.json',
            'generated_at': meta['generated_at'], 'model': meta['model'], **manifest_fields(folder, receipt)}
        if manifest != expected:
            raise ValueError('Manifest changes exceed single approved week pointer')
        return {'kind': 'publication', 'season': meta['season'], 'week': meta['week'],
                'players': len(board['rows']), 'games': len(meta['games']),
                'manifest_sha256': hashlib.sha256(after[MANIFEST]).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True); parser.add_argument('--head', required=True)
    parser.add_argument('--branch', required=True)
    args = parser.parse_args()
    print(json.dumps(validate_change(Path.cwd(), args.base, args.head, args.branch)))
