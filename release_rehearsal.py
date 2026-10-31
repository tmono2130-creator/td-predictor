"""Rehearse a real captured release and rollback in a new isolated local Git repo.

Never pushes, creates a PR, touches served data, deploys or changes settings.
The only network operation retrieves the current public NFL schedule read-only.
"""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from automation_publish import validate_requested_bundle
from publication_policy import fresh
from reviewed_publication import MANIFEST, PREFIX, tree, validate_change
from verify_publication import PRODUCTION, verify_json
from weekly_capture import local_root
from weekly_pipeline import verify_current_schedule
from weekly_schedule import retrieve_schedule, utc_now
from weekly_storage import DEFAULT_DATA, publish_candidate, validate_candidate, validate_manifest


def digest(data):
    return hashlib.sha256(data).hexdigest()


def files(root):
    root = Path(root).resolve()
    result = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Rehearsal input contains a symlink')
        if path.is_file():
            if path.suffix != '.json':
                raise ValueError('Rehearsal inputs must contain JSON files only')
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def git(repo, *args):
    # Inherited local Git routing must never redirect a fixture command to real Git.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    return subprocess.check_output(['git', '-C', str(repo), *args], env=env,
                                   stderr=subprocess.PIPE, text=True).strip()


def commit(repo, label):
    git(repo, 'add', '--', PREFIX)
    git(repo, 'commit', '-qm', 'TEST REHEARSAL ONLY: ' + label)
    return git(repo, 'rev-parse', 'HEAD')


def rehearse(candidate, data, output):
    candidate, data = Path(candidate).resolve(), Path(data).resolve()
    output = local_root(output)
    if any(output.is_relative_to(source) or source.is_relative_to(output) for source in (candidate, data)):
        raise ValueError('Rehearsal output must be separate from input trees')
    if output.exists():
        raise FileExistsError('Rehearsal output must be a new directory')
    # Actual runtime, code, revision, cutoff and source guards stay enabled.
    board, _, receipt = validate_candidate(candidate)
    validate_requested_bundle(receipt, 'all')
    fresh(board, receipt, utc_now())
    baseline_files, candidate_files = files(data), files(candidate)
    validate_manifest(data)
    if digest(baseline_files['manifest.json']) != receipt['base_manifest_sha256']:
        raise ValueError('Current data manifest differs from captured baseline')
    records = retrieve_schedule()
    verify_current_schedule(board, records)
    output.mkdir(parents=True, exist_ok=False)
    repo = output / 'isolated-repository'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'rehearsal-fixture')
    for key, value in [('user.name', 'TEST REHEARSAL ONLY'),
                       ('user.email', 'rehearsal@example.invalid'),
                       ('core.autocrlf', 'false'), ('commit.gpgsign', 'false')]:
        git(repo, 'config', key, value)
    hooks = output / 'empty-hooks'; hooks.mkdir()
    git(repo, 'config', 'core.hooksPath', str(hooks))
    if git(repo, 'remote'):
        raise ValueError('Isolated rehearsal must have no Git remotes')
    target = repo / PREFIX
    for name, raw in baseline_files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
    baseline = commit(repo, 'baseline data')
    baseline_tree = tree(repo, baseline)
    relative = publish_candidate(candidate, target)
    proposed = commit(repo, 'isolated complete three-feature data proposal')
    checked = validate_change(repo, baseline, proposed, 'nfl-pm/publication/0-1', records)
    proposed_tree = tree(repo, proposed)
    added = set(proposed_tree) - set(baseline_tree)
    expected_added = {PREFIX + relative + '/' + name for name in candidate_files}
    if added != expected_added or len(added) != 5:
        raise ValueError('Rehearsal did not add exactly one complete five-file snapshot')
    for name, raw in candidate_files.items():
        if proposed_tree[PREFIX + relative + '/' + name] != raw:
            raise ValueError('Staged artifact differs from captured candidate: ' + name)
    # Simulated served HTTP bytes, not a claim of a real deployment or Vercel Ready.
    def fetch(url):
        if not url.startswith(PRODUCTION + '/data/'):
            raise ValueError('Unexpected rehearsal verification URL')
        return proposed_tree[PREFIX + url.removeprefix(PRODUCTION + '/data/')]
    verified = verify_json(proposed_tree, fetch)
    (target / 'manifest.json').write_bytes(baseline_files['manifest.json'])
    restored = commit(repo, 'manifest-only rollback retaining every archive')
    rollback = validate_change(repo, proposed, restored, 'nfl-pm/rollback/rehearsal', records)
    restored_tree = tree(repo, restored)
    if restored_tree[MANIFEST] != baseline_tree[MANIFEST] or (
            {n: v for n, v in restored_tree.items() if n != MANIFEST}
            != {n: v for n, v in proposed_tree.items() if n != MANIFEST}):
        raise ValueError('Rollback did not restore only the prior manifest')
    if files(data) != baseline_files or files(candidate) != candidate_files:
        raise ValueError('Read-only source inputs changed during rehearsal')
    result = {'kind': 'isolated_unpublished_rehearsal', 'production_modified': False,
              'network_operation': 'read-only public schedule retrieval',
              'season': board['meta']['season'], 'week': board['meta']['week'],
              'checked_at_utc': utc_now().isoformat(), 'source_cutoff_utc': receipt['source_cutoff_utc'],
              'baseline_fixture_commit': baseline, 'proposal_fixture_commit': proposed,
              'rollback_fixture_commit': restored, 'snapshot_directory': relative,
              'publication_validation': checked, 'rollback_validation': rollback,
              'baseline_manifest_sha256': digest(baseline_tree[MANIFEST]),
              'proposal_manifest_sha256': digest(proposed_tree[MANIFEST]),
              'restored_manifest_sha256': digest(restored_tree[MANIFEST]),
              'artifact_sha256': {n: digest(v) for n, v in candidate_files.items()},
              'simulated_served_json_sha256': verified,
              'original_json_files_preserved': len(baseline_files),
              'all_snapshot_files_after_rollback': len(restored_tree) - 1,
              'remote_git_write_or_production_deployment_performed': False}
    with (output / 'rehearsal-result.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--data', default=DEFAULT_DATA, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(rehearse(args.candidate, args.data, args.output), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
