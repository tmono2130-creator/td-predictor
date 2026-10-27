"""Read-only exact-commit Vercel verification; no deployment or promotion API."""
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from reviewed_publication import PREFIX, git, revision, tree
from weekly_storage import validate_manifest

PROJECT = 'prj_BMbAPCEIR8gvJBa4eSLRuPvhAWir'
TEAM = 'team_Eb1qaCcmH0YMrhfjywQr9mON'
PRODUCTION = 'https://td-predictor.vercel.app'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Neither API credentials nor protected/login responses may silently redirect.
        return None


def read_url(url, token=None):
    headers = {'User-Agent': 'NFL-PM-publication-verification', 'Cache-Control': 'no-cache'}
    if token:
        if not url.startswith('https://api.vercel.com/'):
            raise ValueError('Vercel credentials may only be sent to its API')
        headers['Authorization'] = 'Bearer ' + token
    try:
        with build_opener(NoRedirect).open(Request(url, headers=headers), timeout=30) as response:
            if response.status != 200:
                raise RuntimeError('Non-200 verification response')
            data = response.read(20_000_001)
            if len(data) > 20_000_000:
                raise ValueError('Oversized verification response')
            return data
    except Exception:
        raise RuntimeError('Verification HTTP request failed (access, redirect, network or response limit); no release action taken') from None


def api(path, token):
    if not token:
        raise ValueError('Protected read-access Vercel token required')
    return json.loads(read_url('https://api.vercel.com' + path, token))


def wait_ready(sha, token, fetch=api, sleep=time.sleep, attempts=40):
    revision(sha)
    if not 1 <= attempts <= 40:
        raise ValueError('Bounded verification attempts required')
    for number in range(attempts):
        query = urlencode({'projectId': PROJECT, 'teamId': TEAM, 'target': 'production',
                           'limit': 100, 'meta-githubCommitSha': sha})
        deployments = fetch('/v6/deployments?' + query, token)['deployments']
        matches = [d for d in deployments if d.get('meta', {}).get('githubCommitSha') == sha
                   and d.get('meta', {}).get('githubCommitRef') == 'main' and d.get('target') == 'production']
        if matches:
            deployment = max(matches, key=lambda d: d.get('created', 0))
            if deployment.get('state') in {'ERROR', 'CANCELED', 'BLOCKED'}:
                raise ValueError('Exact-commit production deployment failed or was blocked')
            if deployment.get('state') == 'READY':
                detail = fetch('/v13/deployments/' + deployment['uid'] + '?' + urlencode({'teamId': TEAM}), token)
                if (detail.get('readyState') != 'READY' or detail.get('target') != 'production'
                        or detail.get('meta', {}).get('githubCommitSha') != sha
                        or detail.get('projectId') != PROJECT
                        or 'td-predictor.vercel.app' not in detail.get('alias', [])):
                    raise ValueError('Ready deployment is not the exact production alias target')
                alias = fetch('/v4/aliases/td-predictor.vercel.app?' + urlencode({'teamId': TEAM, 'projectId': PROJECT}), token)
                if alias.get('deploymentId') != deployment['uid'] or alias.get('projectId') != PROJECT:
                    raise ValueError('Production alias currently points to another deployment')
                return {'deployment_id': deployment['uid'], 'commit': sha, 'state': 'READY'}
        if number + 1 < attempts:
            sleep(15)
    raise TimeoutError('No Ready exact-commit production deployment within verification window')


def verify_json(expected, fetch=read_url):
    """Compare ALL committed JSON bytes, including inactive immutable archives."""
    hashes = {}
    for name, value in sorted(expected.items()):
        relative = name.removeprefix(PREFIX)
        actual = fetch(PRODUCTION + '/data/' + relative)
        expected_hash = hashlib.sha256(value).hexdigest()
        if hashlib.sha256(actual).hexdigest() != expected_hash:
            raise ValueError('Production JSON hash mismatch: ' + relative)
        hashes[relative] = expected_hash
    # Catch an alias/manifest switch during the multi-file fetch.
    manifest = expected[PREFIX + 'manifest.json']
    if fetch(PRODUCTION + '/data/manifest.json') != manifest:
        raise ValueError('Production manifest moved during verification')
    return hashes


def assert_current_main(repo, sha):
    current = git(repo, 'ls-remote', 'origin', 'refs/heads/main').decode().split()[0]
    if current != sha:
        raise ValueError('Main advanced during verification; verify its exact new deployment separately')


def main():
    sha = revision(os.environ['GITHUB_SHA'])
    if os.environ.get('GITHUB_REF') != 'refs/heads/main' or os.environ.get('NFL_PM_VERIFY_DEPLOYMENTS') != 'true':
        raise SystemExit('Read-only deployment verification is disabled or not on main')
    repo = Path.cwd()
    if git(repo, 'rev-parse', 'HEAD').decode().strip() != sha:
        raise ValueError('Verification checkout differs from merged commit')
    validate_manifest(repo / PREFIX)
    assert_current_main(repo, sha)
    result = wait_ready(sha, os.environ['VERCEL_READ_TOKEN'])
    result['hashes'] = verify_json(tree(repo, sha))
    assert_current_main(repo, sha)
    # Check alias assignment again after HTTP verification; no secret in report.
    if wait_ready(sha, os.environ['VERCEL_READ_TOKEN'], attempts=1)['deployment_id'] != result['deployment_id']:
        raise ValueError('Deployment changed during verification')
    output = Path(os.environ['RUNNER_TEMP']) / 'nfl-pm-deployment-verification.json'
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'commit': sha, 'deployment_id': result['deployment_id'], 'json_files_verified': len(result['hashes'])}))


if __name__ == '__main__':
    main()
