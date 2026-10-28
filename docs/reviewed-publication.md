# Milestone 5B — reviewed prediction publication

Development only. No production activation, schedule, generated week, credential,
push, or deployment is part of this implementation. The UI and model are unchanged.

## Workflow and trust boundaries

`weekly-predictions.yml` remains manual-only. `publish=false` generates an
unpublished temporary candidate. Its gated `publish` job now means **create a
draft data PR**, never merge or push to main. It requires a manual main run,
`publish=true`, repository variable `NFL_PM_PUBLISHING_ENABLED=true`, and approval
of `nfl-pm-production`. No deploy hooks or Vercel credentials are used by it.

The writer uses a fresh checkout of the exact reviewed main SHA and creates
`nfl-pm/publication/<run-id>-<attempt>`. Only one outstanding publication/rollback
PR is allowed. Any existing publication branch also blocks a new proposal until
an operator inspects its outcome and removes the obsolete branch. Workflow
concurrency serializes writers; main SHA and manifest-base checks reject races.
Failures after a branch push may leave an orphan branch. They never trigger an
automatic retry, main update, merge, rebase, or cleanup.

The only permitted publication diff is an updated manifest plus one new
UUID-versioned folder containing board, breakdowns, and receipt JSON. Existing
archives cannot change or disappear. Files, Git modes, path traversal, extra
manifest edits, source changes mixed with data, and untracked writer changes
are rejected. Candidate validation retains all existing model fingerprint,
player/game/team coverage, classification, source-cutoff, probability and JSON
checks. Current NFL schedule retrieval must succeed and match the candidate.
Historical candidates are never permitted through this path.

Freshness is checked at PR creation and every PR safety run: maximum age is
30 minutes within six hours of kickoff, six hours within 48 hours, and 24 hours
otherwise. Both prediction time and source cutoff must qualify. At least ten
minutes must remain before **every** candidate kickoff. A changed schedule,
started game, stale manifest, or stale candidate requires regeneration on main.

`reviewed-data-checks.yml` runs on all main PRs, without path filters. The
same read-only checks also run on narrowly scoped pushes to
`feature/nfl-pm-reviewed-publication`, without generating a real candidate or
creating any publication branch/PR. Feature runs compare against current main;
PR runs continue using trusted base code.
The
`Publication safety` job checks out the trusted **base** source, fetches PR Git
objects, and compares the entire diff to current main without running PR code.
The bootstrap exception allows source-only PRs when the base lacks this new
validator; it forbids any data change. Ordinary source PRs may not bundle data.
After safety passes, unprivileged jobs run Python tests and the frontend build,
lint and freshness tests against the proposed merge. No secrets, environments,
write permissions, or `pull_request_target` are used in these PR jobs.

Time passing does not automatically invalidate a green GitHub status. This
implementation deliberately has no scheduled refresh or auto-merge. A human
must rerun **all** PR checks immediately before merging, verify their checked
SHA, freshness window, and kickoff margin again, and cancel if the window expires.
Require an up-to-date branch. There is still a time-of-check/time-of-merge gap;
fully unattended publication would require a separate merge-time enforcement
design and approval. Do not enable auto-merge or a merge queue for data PRs yet.

## GitHub settings (owner approval required; not configured by development)

1. Leave repository variables `NFL_PM_PUBLISHING_ENABLED` and
   `NFL_PM_VERIFY_DEPLOYMENTS` absent/false until their separate approvals.
   The first now opts into PR creation only. The second opts into read-only
   post-merge verification; neither enables a schedule.
2. Create `nfl-pm-production`: selected deployment **branch** `main` only, no
   tags; required trusted reviewers; prevent self-review; disable administrator
   bypass where supported. Use a second authorized reviewer; GitHub requires
   only one of configured reviewers, not every listed reviewer. A solo initiator
   cannot approve their own run under this policy.
3. Keep default Actions permissions read-only. Only the proposal job requests
   `contents: write` and `pull-requests: write`; checkout credentials are not
   persisted. Enable **Allow GitHub Actions to create and approve pull requests**
   only if needed for creation. This implementation never approves a PR.
4. Protect main: require a PR and independent approval, dismiss stale approvals,
   require the branch to be current, require `Publication safety`, `Python tests`,
   and `Frontend publication build`. Select the observed check names after the
   first approved development PR run. Protect workflow/model/publisher source
   through owner review (CODEOWNERS if appropriate). No bot bypass, force push,
   branch deletion of main, or direct-main permission exception is needed.
5. GitHub may require a human to approve checks for PRs created with
   `GITHUB_TOKEN`. If checks do not start, do not merge: approve the workflow
   run through GitHub or investigate account policy. Do not add a broad PAT to
   work around required checks. No PAT is required by this implementation.

GitHub settings and branch protection could not be read with administrative
credentials during development. Their live configuration must be verified by
the owner. Creating an unprotected environment implicitly is not sufficient.

## Vercel and exact-commit verification

Prefer existing Git-to-Vercel integration after a human-approved data PR merge.
Confirm production branch main, root `td-predictor-web`, Node 24, build settings,
Git integration and commit-author permissions in the dashboard. Branch pushes
may create previews; publication approval must include that behavior. No hook,
deployment API, promotion command or rollback command is run by these workflows.

`verify-published-data.yml` is opt-in, main-only, read-only, and environment-gated.
It reacts to data pushes on main or a manual main run. It checks the exact
event SHA (never silently substitutes latest), waits up to approximately ten
minutes for its production deployment, rejects failed/blocked/canceled builds,
and requires Ready plus the production alias. It compares every committed JSON
file, including inactive archives, byte for byte by SHA256, checks the manifest
again, confirms main and deployment did not advance, and runs actual production
browser smoke tests without intercepted data. Evidence is retained seven days.
Success is reported only when all steps succeed. It never treats a Git push as
proof of deployment and never invokes a hook.

The protected environment needs `NFL_PM_VERCEL_READ_TOKEN` only for Vercel API
inspection, scoped to the intended team/project with the least permissions the
account supports. It is exposed only to the Python verification step and sent
only to api.vercel.com, with redirects rejected. The implementation uses GET
requests exclusively; a broadly capable platform token is still a credential
risk and must be protected/rotated. Do not provision it during development.
Project/team IDs and the production origin are fixed in `verify_publication.py`.

Production HTTP/browser access must be permitted. A login redirect, 401/403, wrong
JSON or inaccessible protected deployment fails verification. No authentication
bypass is implemented or activated. If Vercel protection blocks hosted checks,
approve a scoped test-access design first; do not disable protection casually.
Read-only verification does not prevent Git integration from making a bad merge
live. For release-before-domain-assignment gating, implement and approve a staged
production deployment/promotion process separately.

Baseline rollback candidate recorded during Milestone 5 review:
`dpl_CQ9kvum5QqeLPTHftUE4eFrq2zEq`, commit
`0027d478e80fb0e85690448b5c6de1302d0f856b`. Reconfirm availability before release.

## First supervised publication (future approval, not performed)

1. Review/test this development diff; separately approve commit, push and PR.
   Pass hosted checks, approve the code merge and account for Vercel's normal
   frontend deployment on merge. Keep both opt-ins false and all cron absent.
2. Owner confirms GitHub protections, reviewer access, PR creation policy, Vercel
   settings and production test access. Record last good deployment ID, main SHA,
   manifest hash, and hashes of every existing archive.
3. Separately approve/configure read-only verification credentials and its opt-in;
   test manual verification on reviewed main without generating or publishing.
4. Separately approve one supervised proposal. Temporarily opt into PR creation,
   run weekly predictions on main with publish=true, then set the opt-in false
   after the proposal finishes. Keep schedules absent. Generation is fresh and
   candidate files remain unpublished until an approved PR merge.
5. Review draft PR: exact four paths, current base, all archive hashes, authentic
   pregame classification, injury Unknown limitations, source ages, complete
   roster/game coverage and kickoff margin. Approve workflows if GitHub requires
   it. Make ready only after human review. Rerun all checks immediately before
   the separately approved merge. If stale, close the PR, inspect/delete only its
   review branch, and request a new candidate; never rewrite an archived snapshot.
6. After approved merge, approve the read-only environment check promptly. Require
   exact-SHA Ready, production alias and JSON hashes, all served weekly selections
   and mobile tools, no browser runtime errors. Keep PR creation disabled until
   the supervised trial is accepted. No schedule activation is implied.

## Rollback and failure handling

1. Set both opt-ins false as appropriate, cancel queued/in-progress proposal jobs,
   close unmerged data PRs, and coordinate pending Vercel deployments. A running
   job may already have captured its gate value; do not rely on a variable alone.
2. For bad live data, an authorized owner selects the recorded known-good
   deployment in Vercel and performs Instant Rollback after approval. Record its
   ID and verify the restored website/data. This is a manual production action,
   never an automatic script in this milestone.
3. To restore Git's pointer, branch from current main as
   `nfl-pm/rollback/<incident-id>`. Restore **only**
   `td-predictor-web/public/data/manifest.json` from the known-good ancestor.
   Open a reviewed manifest-only PR. Retain every old/new immutable folder.
   The same safety/build/test checks apply; rollback manifests must exactly match
   a prior main manifest (bounded to the last 1000 manifest-changing commits).
   No historical freshness check applies to restoring an existing archive.
4. Do not revert a whole publication commit if that deletes its snapshot files.
   Never reset/force-push main or delete archives. Tests use temporary Git fixture
   repositories to verify exact manifest restoration and unchanged archive bytes.
5. After Git rollback, verify the exact resulting deployment and served manifest.
   Instant Rollback can disable automatic domain assignment: keep it that way
   until an explicitly approved promotion restores normal behavior. Investigate
   the original failure before re-enabling proposals.

Validation/source failure: no remote write. Main race: no automatic rebase/merge.
Branch push followed by PR API failure: orphan review branch only; inspect before
retry. Data PR merge followed by failed Vercel build: Git and production differ;
verify both before acting. Hash/smoke failure after Ready: mark release failed,
halt proposals and invoke the reviewed rollback process. No automated deletion,
republishing, forced retry, hook, or rollback is performed.

References: [GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[GitHub token events](https://docs.github.com/en/actions/concepts/security/github_token),
[Vercel Git integration](https://vercel.com/docs/git),
[Vercel Instant Rollback](https://vercel.com/docs/instant-rollback).
