"""Local/CI test fixtures and protected-file audit. No prediction publication."""
import argparse
import subprocess
from pathlib import Path
from weekly_capture import local_root, write_new, encode


def fixtures(output):
    from test_matchup_intelligence import fixture, candidate
    output = local_root(output)
    output.mkdir(parents=True, exist_ok=True)
    value = candidate()
    value['meta']['limitations'].append('TEST FIXTURE — synthetic browser regression only')
    write_new(output / 'm7-fixture-artifact.json', encode(value))
    write_new(output / 'm7-fixture-board.json', encode(fixture()[0]))


def integrity(base):
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', base, 'td-predictor-web/public/data'], text=True).splitlines()
    if len(paths) != 13:
        raise ValueError('Original production baseline must contain exactly 13 files')
    protected = ['td_predictor_v5.py', 'game_projection.py', 'td-predictor-web/lib/parlay.ts']
    for name in paths:
        if Path(name).read_bytes() != subprocess.check_output(['git', 'show', base + ':' + name]):
            raise ValueError('Protected production/calculation file changed: ' + name)
    for name in protected:
        # Git stores LF; Windows checkout may use CRLF. Do not rewrite protected source files.
        current = Path(name).read_bytes().replace(b'\r\n', b'\n')
        original = subprocess.check_output(['git', 'show', base + ':' + name]).replace(b'\r\n', b'\n')
        if current != original:
            raise ValueError('Protected calculation source changed: ' + name)
    print('PASS 13 original production JSON files and protected V5/PPP/parlay source bytes')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--base', default='origin/main')
    args = parser.parse_args()
    if args.fixtures:
        fixtures(args.fixtures)
    else:
        integrity(args.base)
