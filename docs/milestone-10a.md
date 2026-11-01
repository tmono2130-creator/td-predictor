# Milestone 10A: read-only production reliability

This source change does not publish, generate predictions, enable schedules, merge,
deploy, change credentials/settings or authorize a release. V5, PPP, parlay and
Market Check calculations and all released JSON remain unchanged.

## Supervised Week 8 refresh

At the November 1 audit the production SHA was
`0631ea9f6d0ffbb69185c54bd7ee722d840514e7`; the source cutoff was October 31
20:23:51 UTC and the earliest remaining kickoff was November 1 18:00 UTC.
These are recorded observations, not current eligibility evidence. Recheck the
actual NFL schedule and clock immediately before generation and merge.

1. Verify main, strict required checks, required PRs, no bypass, main-only
   `nfl-pm-production`, Actions PR creation permission and a known-good rollback
   deployment/manifest. This is a solo-maintainer approval, not independent review.
2. Inspect open publication/rollback PRs AND remote publication branches. Close
   stale proposals unmerged; remove only their owner-reviewed obsolete branches.
   The publisher intentionally refuses competing or orphan branches.
3. With owner approval temporarily set `NFL_PM_PUBLISHING_ENABLED`,
   `NFL_PM_GAME_PREDICTOR_ENABLED`, `NFL_PM_MATCHUP_INTELLIGENCE_ENABLED` to `true`.
4. Actions -> **NFL PM weekly predictions** -> Run workflow on **main**:
   `season=2026`, `week=8`, `features=all`, `publish=true`,
   `diagnostic_only=false`. This creates a proposal only. Never reuse old captures.
5. Review captured source timestamps/cutoff, current games, authoritative roster
   decisions, injury uncertainty, all-feature completeness, exact replay, schemas,
   receipt hashes and browser evidence before approving the protected job.
6. Expect exactly six paths: manifest plus NEW board, breakdowns, receipt,
   matchup-intelligence and game-predictor JSON in one immutable directory.
   Existing snapshots must remain byte-identical. No source changes in the data PR.
7. Disable all three opt-ins immediately after proposal completion. Confirm no
   other proposal runs are queued/running. This does not retract an existing PR.
8. Approve Actions-created PR workflows if requested; confirm the actual checks
   run on its exact head. If no run exists, investigate the trigger; never bypass
   checks. Review main/base consistency and actual freshness again before a
   separately approved human merge. Regenerate if either moved or expired.
9. Preserve strict limits: >48h to kickoff: age <24h; <=48h: <6h; <=6h: <30m.
   Generation/publication is prohibited at or inside 10m before any target kickoff.
   Crossing a 48h/6h boundary can expire an older capture immediately. A six-hour
   age limit now does not promise six hours of future eligibility.
10. Use Git-to-Vercel, then the unchanged exact-SHA deployment verifier: Ready,
    current onopm.space alias, committed JSON hashes, browser checks, then repeat
    alias/manifest checks. Content health alone cannot authorize or verify release.
    Preserve the known-good deployment and prior manifest for reviewed rollback;
    never delete snapshots or revert a data commit in a way that deletes them.

## Health monitoring

`production_health.py --expected-commit <40-character-reviewed-production-SHA>`
reads the fixed public production origin without credentials, redirects or writes.
It checks the HTTP shell (not JavaScript execution), every committed JSON file and
archive, exact bytes/hashes, manifest stability, receipt/sidecar binding and schema/
semantic identities. Freshness is evaluated for the newest generated snapshot by
default; `--season` and `--week` must be supplied together for a specific selection.

Statuses:

| State | Meaning |
| --- | --- |
| ERROR (exit 1) | Missing file, HTTP error, byte/hash mismatch, invalid contract, manifest race or verified deployment/alias failure |
| DEGRADED (exit 0, warning) | Stale predictions, kickoff margin or legacy missing provenance; not integrity success for a release |
| UNKNOWN (exit 0, warning) | Content checks complete but deployment identity was not independently checked |
| HEALTHY (exit 0) | Content and supplied exact deployment checks succeeded; still never release authorization |

Unpublished weeks and absent optional pointers are explicitly `expected_unavailable`;
a pinned file that is missing is an ERROR. Archived forecasts are distinguished
from new stale pregame data. Saved V5 estimates may remain visible with a refresh
warning; no new forecast or current recommendation is manufactured.

Optional `--verify-deployment` uses the EXISTING `VERCEL_READ_TOKEN` environment
variable and unchanged verifier for exact commit, Ready state and production alias.
It repeats the deployment check after fetching content. It never creates access.
Without that access the report must say unverified, never imply deployment proof.

The new **NFL PM read-only content health** workflow is manual-only, main-only,
contents-read, without a production environment, secrets or publishing opt-ins.
It retains reports 14 days and warns on DEGRADED/UNKNOWN. No schedules are added.
Do not interpret a green job containing a warning as a fresh-release approval.

Source CI uses a distinct localhost content-health browser mode ONLY when the
trusted-base publication validator returns `source`. It still checks bytes, hashes,
coverage, exact fresh scores and stale-score suppression. Missing classification,
data PRs and production post-merge verification use the unchanged default strict
fresh-release path. Health mode is rejected on production URLs. There are no
intercepted production responses or changed clocks in this CI distinction.

## Refresh planning

`refresh_status()` budgets 20 minutes: generation 5, CI 8, human review 5,
deployment 2. `refresh_due()` retains its existing boolean API. The receipt cutoff
can be supplied to `refresh_status()`; `plan --due-only` reads it from the current
receipt when available, reports the deadline/reason, and otherwise uses generation
time for legacy snapshots. Planning is not a substitute for receipt validation.

Refresh starts at deadline minus budget, including tighter FUTURE freshness
windows. A new candidate must fit the budget before both strict freshness expiry
and kickoff-minus-10m; otherwise planning says insufficient headroom, not ready.
These durations are estimates, not an assurance of review availability. With a
30-minute freshness window and 20-minute release budget, a refresh can be due
after only 10 minutes. Frequent human review is required; retain suppression if
the review cannot finish. No freshness limit or protected approval is relaxed.

## Next: 10B (not implemented here)

Pin immutable snapshot/receipt hashes and deployment revision; capture verified
final outcomes separately with source URLs, retrieval times, hashes and revisions.
Match GSIS/game/team IDs; missing evidence stays unknown. Evaluate the published
cohort's rushing/receiving TD event with Brier, log loss, probability-bin calibration
and ranking performance; document DNP and missing outcomes without post-hoc
selection. Evaluate baseline PPP scores, margins and totals against official finals
and separately reconcile offensive-drive scoring definitions. Keep adjusted ridge
experimental. Never rewrite forecasts, retrain or tune on this evaluation.

Future dormant scheduling should plan across actual NFL kickoff times in UTC,
generate only when due, require a separate scheduled-proposal opt-in and protected
approval, create draft data-only PRs, and never merge. Implement/tests may prepare
this, but no schedule or unattended publishing is authorized now. Preserve raw
capture evidence beyond the current January 29, 2027 artifact expiry if long-term
evaluation/replay is required. No storage configuration is changed here.
