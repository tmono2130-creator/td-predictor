"""CI-only creation of a reviewed data PR. Never push to main or deploy."""
import base64
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.request import Request, build_opener
from verify_publication import NoRedirect
from reviewed_publication import MANIFEST, PREFIX, fresh, revision, validate_change
from weekly_pipeline import verify_current_schedule
from weekly_schedule import retrieve_schedule, utc_now
from weekly_storage import DEFAULT_DATA, publish_candidate, validate_candidate


def git(*args):
    env = os.environ.copy()
    token = env.pop('GH_PUSH_TOKEN', None)
    if token:
        env['GIT_CONFIG_COUNT'] = '1'
        env['GIT_CONFIG_KEY_0'] = 'http.https://github.com/.extraheader'
        env['GIT_CONFIG_VALUE_0'] = 'AUTHORIZATION: basic ' + base64.b64encode(('x-access-token:' + token).encode()).decode()
    return subprocess.check_output(['git', *args], text=True, env=env).strip()


def publication_allowed(event, ref, enabled, requested):
    return event == 'workflow_dispatch' and ref == 'refs/heads/main' and enabled == 'true' and requested == 'true'


def github(path, payload=None):
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid GitHub repository')
    request = Request('https://api.github.com/repos/' + repo + path,
                      data=None if payload is None else json.dumps(payload).encode(),
                      headers={'Authorization': 'Bearer ' + os.environ['GH_PUSH_TOKEN'],
                               'Accept': 'application/vnd.github+json', 'User-Agent': 'NFL-PM-reviewed-publication'})
    try:
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            return json.load(response)
    except Exception:
        raise RuntimeError('GitHub publication request failed; inspect PRs/branches before retrying') from None


def assert_no_pending():
    for page in range(1, 11):
        pulls = github(f'/pulls?state=open&base=main&per_page=100&page={page}')
        if any(p['head']['ref'].startswith(('nfl-pm/publication/', 'nfl-pm/rollback/')) for p in pulls):
            raise ValueError('Concurrent publication/rollback PR exists')
        if len(pulls) < 100:
            return
    raise ValueError('Cannot safely establish publication exclusivity')


def assert_main(expected):
    if git('ls-remote', 'origin', 'refs/heads/main').split()[0] != expected:
        raise ValueError('Main moved during generation; regenerate, never rebase automatically')


def create_data_pr(candidate, expected_head, run_id, attempt, root=DEFAULT_DATA):
    revision(expected_head)
    if not re.fullmatch(r'[0-9]+', run_id) or not re.fullmatch(r'[0-9]+', attempt):
        raise ValueError('Numeric GitHub run and attempt identifiers required')
    branch = f'nfl-pm/publication/{run_id}-{attempt}'
    if git('rev-parse', 'HEAD') != expected_head or git('status', '--porcelain'):
        raise ValueError('Checkout is not the clean reviewed main revision')
    repo = Path(git('rev-parse', '--show-toplevel')).resolve()
    if Path(root).resolve() != repo / PREFIX.rstrip('/'):
        raise ValueError('Publication root must be frontend JSON directory')
    assert_main(expected_head); assert_no_pending()
    if git('ls-remote', 'origin', 'refs/heads/nfl-pm/publication/*'):
        raise ValueError('Publication branch exists; inspect its PR outcome before cleanup')
    board, _, receipt = validate_candidate(candidate)
    fresh(board, receipt, utc_now())
    records = retrieve_schedule()
    verify_current_schedule(board, records)
    git('switch', '-c', branch)
    directory = publish_candidate(candidate, root)
    allowed = {MANIFEST} | {PREFIX + directory + '/' + n for n in ('board.json', 'breakdowns.json', 'receipt.json')}
    changed = set(git('diff', '--name-only').splitlines()) | set(git('ls-files', '--others', '--exclude-standard').splitlines())
    if changed != allowed:
        raise ValueError('Unexpected working-tree changes; no review branch push permitted')
    git('add', '--', *sorted(allowed))
    if set(git('diff', '--cached', '--name-only').splitlines()) != allowed:
        raise ValueError('Staged changes do not match data-only allowlist')
    git('diff', '--cached', '--check')
    git('-c', 'user.name=NFL PM data bot', '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
        'commit', '-m', f"Propose NFL PM {board['meta']['season']} week {board['meta']['week']} forecasts")
    proposed = git('rev-parse', 'HEAD')
    if git('status', '--porcelain'):
        raise ValueError('Unexpected changes remain after data commit')
    summary = validate_change(repo, expected_head, proposed, branch)
    assert_main(expected_head); assert_no_pending()
    # Normal push to a unique review branch only. Never main or a forced update.
    git('push', 'origin', f'HEAD:refs/heads/{branch}')
    assert_main(expected_head)
    pull = github('/pulls', {'base': 'main', 'head': branch, 'draft': True,
        'title': f"Review NFL PM {summary['season']} week {summary['week']} predictions",
        'body': f"Data-only candidate. Base: {expected_head}; head: {proposed}.\n\n"
                f"Players: {summary['players']}; games: {summary['games']}. "
                f"Manifest SHA256: {summary['manifest_sha256']}.\n\n"
                'No automatic merge. Approve required workflows if GitHub requests it. Rerun all checks '
                'immediately before merge; reject stale candidates. Record the current deployment and '
                'manifest for rollback. A human-approved merge uses existing Git-to-Vercel integration; '
                'verify the exact deployed commit, JSON hashes, and website afterward.'})
    return pull['html_url']


def main():
    if not publication_allowed(os.environ.get('GITHUB_EVENT_NAME'), os.environ.get('GITHUB_REF'),
                               os.environ.get('NFL_PM_PUBLISHING_ENABLED'), os.environ.get('PUBLISH_REQUESTED')):
        raise SystemExit('Reviewed PR creation is disabled or this run is not approved main')
    url = create_data_pr(Path(os.environ['CANDIDATE_DIR']), os.environ['GITHUB_SHA'],
                         os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT'])
    print('Created draft data PR: ' + url)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
        stream.write('Draft data PR: ' + url + '\nNo merge or deployment was requested.\n')


if __name__ == '__main__':
    main()
