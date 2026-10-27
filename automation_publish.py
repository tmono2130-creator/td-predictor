"""CI-only allowlisted data commit/push, with a race check and no history rewriting.

Do not invoke locally during implementation. workflow_dispatch's publish flag,
repository variable, protected branch, and production environment all gate this.
"""
import os
import base64
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from weekly_pipeline import verify_current_schedule
from weekly_schedule import retrieve_schedule
from weekly_storage import DEFAULT_DATA, publish_candidate, validate_candidate


def git(*args):
    env = os.environ.copy()
    token = env.pop("GH_PUSH_TOKEN", None)
    if token:
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = "AUTHORIZATION: basic " + base64.b64encode(("x-access-token:" + token).encode()).decode()
    return subprocess.check_output(["git", *args], text=True, env=env).strip()


def publication_allowed(event, ref, enabled, requested):
    return ref == "refs/heads/main" and enabled == "true" and (event == "schedule" or event == "workflow_dispatch" and requested == "true")


def commit_data(candidate, expected_head, root=DEFAULT_DATA):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise ValueError("Expected source revision is required")
    if git("rev-parse", "HEAD") != expected_head or git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Checkout is not the clean reviewed source revision")
    remote_head = git("ls-remote", "origin", "refs/heads/main").split()[0]
    if remote_head != expected_head:
        raise ValueError("Main moved during generation; do not merge/rebase automatically")
    repo = Path(git("rev-parse", "--show-toplevel")).resolve()
    if Path(root).resolve() != repo / "td-predictor-web" / "public" / "data":
        raise ValueError("Publication root must be the frontend JSON directory")
    board, _, _ = validate_candidate(candidate)
    verify_current_schedule(board, retrieve_schedule())
    directory = publish_candidate(candidate, root)
    prefix = "td-predictor-web/public/data/"
    allowed = {prefix + "manifest.json"} | {prefix + directory + "/" + name for name in ("board.json", "breakdowns.json", "receipt.json")}
    git("add", "--", *sorted(allowed))
    if set(git("diff", "--cached", "--name-only").splitlines()) != allowed:
        raise ValueError("Staged changes do not match the data-only allowlist")
    git("diff", "--cached", "--check")
    git("-c", "user.name=NFL PM data bot", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "-m", f"Refresh NFL PM {board['meta']['season']} week {board['meta']['week']} forecasts")
    # Normal push fails on a concurrent remote update; never force, pull, or rebase.
    git("push", "origin", "HEAD:refs/heads/main")
    return git("rev-parse", "HEAD")


def validate_hook_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "api.vercel.com" or not parsed.path.startswith("/v1/integrations/deploy/"):
        raise ValueError("Expected a Vercel deploy hook URL")
    return url


def trigger_deploy_hook(url):
    validate_hook_url(url)
    # Treat the entire URL as a secret: no printing, shell expansion, or HTTP error URLs.
    try:
        with urlopen(Request(url, data=b"", method="POST"), timeout=45) as response:
            if response.status not in (200, 201, 202):
                raise RuntimeError("Deploy hook rejected")
    except Exception:
        raise RuntimeError("Vercel deploy hook failed; data commit remains available for a manual deployment") from None


def main():
    if not publication_allowed(os.environ.get("GITHUB_EVENT_NAME"), os.environ.get("GITHUB_REF"),
                               os.environ.get("NFL_PM_PUBLISHING_ENABLED"), os.environ.get("PUBLISH_REQUESTED")):
        raise SystemExit("Publication is disabled or this run is not approved main")
    sha = commit_data(Path("work/candidate"), os.environ.get("GITHUB_SHA", ""))
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write("published_sha=" + sha + "\n")
    print("Published validated data commit " + sha)


if __name__ == "__main__":
    main()
