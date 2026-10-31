"""Local/CI test fixtures and protected-file audit. No prediction publication."""
import argparse
import subprocess
from pathlib import Path
from weekly_capture import local_root, write_new, encode
from reviewed_publication import MANIFEST, PREFIX, tree, validate_change


def fixtures(output):
    from test_matchup_intelligence import fixture, candidate
    output = local_root(output)
    output.mkdir(parents=True, exist_ok=True)
    value = candidate()
    value['meta']['limitations'].append('TEST FIXTURE — synthetic browser regression only')
    write_new(output / 'm7-fixture-artifact.json', encode(value))
    write_new(output / 'm7-fixture-board.json', encode(fixture()[0]))


def integrity(base, branch=None, repo=None):
    """Protect every archive while admitting only separately reviewed data changes.

    Source PRs may not introduce any served file. Manifest changes additionally
    require the unchanged reviewed data-only/rollback validator and explicit branch.
    """
    repo = Path(repo or Path.cwd()).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    base = git('rev-parse', '--verify', base + '^{commit}')
    head = git('rev-parse', 'HEAD')
    baseline = tree(repo, base)
    if len(baseline) < 13 or MANIFEST not in baseline:
        raise ValueError('Production baseline must preserve at least the original 13 JSON files')
    current = {}
    for path in (repo / PREFIX).rglob('*'):
        if path.is_symlink():
            raise ValueError('Unexpected symlink in production data')
        if path.is_file():
            if path.suffix != '.json':
                raise ValueError('Unexpected non-JSON production data file')
            current[path.relative_to(repo).as_posix()] = path.read_bytes()
    protected = ['td_predictor_v5.py', 'game_projection.py', 'td-predictor-web/lib/parlay.ts']
    for name, raw in baseline.items():
        if name != MANIFEST and current.get(name) != raw:
            raise ValueError('Protected production snapshot changed or deleted: ' + name)
    for name in protected:
        # Git stores LF; Windows checkout may use CRLF. Do not rewrite protected source files.
        actual = (repo / name).read_bytes().replace(b'\r\n', b'\n')
        original = subprocess.check_output(['git', '-C', str(repo), 'show', base + ':' + name]).replace(b'\r\n', b'\n')
        committed = subprocess.check_output(['git', '-C', str(repo), 'show', head + ':' + name]).replace(b'\r\n', b'\n')
        if actual != original or committed != original:
            raise ValueError('Protected calculation source changed: ' + name)
    if current.get(MANIFEST) != baseline[MANIFEST]:
        if not branch:
            raise ValueError('Manifest change requires an explicit reviewed publication/rollback branch')
        result = validate_change(repo, base, head, branch)
        if current != tree(repo, head):
            raise ValueError('Uncommitted or untracked data differs from reviewed commit')
    else:
        if current != baseline:
            raise ValueError('Source-only audit forbids new, deleted or modified production data')
        if tree(repo, head) != baseline:
            raise ValueError('Committed data changes cannot be hidden by working-tree edits')
        result = {'kind': 'source', 'protected_json_files': len(baseline)}
    print(f'PASS {len(baseline)} baseline JSON files protected; reviewed {result["kind"]}; V5/PPP/parlay unchanged')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--base', default='origin/main')
    parser.add_argument('--branch', help='Explicit PR head branch; required for reviewed manifest changes')
    args = parser.parse_args()
    if args.fixtures:
        fixtures(args.fixtures)
    else:
        integrity(args.base, args.branch)
