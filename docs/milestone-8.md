# Milestone 8 — Multi-Team TD Filter and Game Predictor

## Status and independent stages

Implemented locally on `feature/nfl-pm-game-predictor`, based on main `4b168c2b59bf7d667a1d1a1e66d0f8e0d597298e`. PR #8 was inspected: open, unmerged, head `74a889a9f3237fa9db64bdb4ecca174cc8a1c871`. None of its unmerged code is imported or required. No commits, pushes, PRs, publication, deployment, schedule or repository-setting changes are authorized for this milestone.

Stage A can be reviewed independently: rankings component, `lib/team-filter.ts`, team-filter Node/browser tests, existing smoke selector update and the `.teamPicker` CSS block. The default is All Teams; empty selection restores All Teams. All 32 franchise options remain available even when a team has no rows in the selected week. Two or more arbitrary teams form a union; opponents are not a restriction. Removable chips preserve selections through other filters and sorting; existing season/week component keys reset selections. No probability or player row is modified.

Stage B contains the projection engine/evaluator, optional JSON schema/contract, separate Game Predictor navigation and UI, publication/deployment validation and tests. The `.gamePredictor` CSS block belongs to Stage B. Keep future approved commits separated by these stage boundaries; nothing is staged or committed now.

## Baseline formulas and event definitions

- Offensive PPP = offensive-drive points / qualifying offensive plays.
- Defensive PPP allowed = opponent offensive-drive points / qualifying plays faced.
- Expected plays = (team offensive plays/game + opponent plays faced/game) / 2.
- Expected PPP = (team offensive PPP + opponent defensive PPP allowed) / 2.
- Projected baseline points = expected PPP × expected plays, using full precision. Display alone rounds to one decimal.

Qualifying plays are run/pass (including sacks and scrambles), excluding kneels, spikes, no-plays and two-point tries. Offensive-drive points count touchdowns on run/pass plays by the possession team, their verified successful PAT/two-point conversions, and made field goals. Defensive/return touchdowns and their conversions and safeties are excluded. PAT points are not credited without the corresponding offensive touchdown. Missing event evidence or incomplete completed-game coverage fails instead of becoming zero. Offensive and defensive numerators and denominators use the same rules.

The baseline therefore estimates offensive-drive scoring, while the UI shows it as a baseline final-score projection and evaluation compares against actual total final scores including overtime. Excluding rare defensive/return points is a known baseline limitation, not a claim that those events cannot happen. The adjusted residual can learn an aggregate offset but does not explicitly model those event types.

Each team uses its last eight completed prior-week regular-season games, with at least four required, drawn from the current and previous seasons only. Same-week games are excluded even if they finish earlier than another kickoff, so unfinished overlapping games cannot leak final statistics. All input games must predate cutoff and target kickoff. Teams and opponents are corroborated against the schedule. Source capture hashes/timestamps are preserved; a current reconstruction cannot establish original pregame vintage.

## Adjusted experiment and evaluation

The adjusted method is a fixed ridge residual regression: `max(0, baseline + intercept + coefficients · features)`. Features are baseline points, own offensive PPP, opponent defensive PPP allowed, expected plays, and verified non-neutral home-field indicator. Alpha is fixed at 100. Standardization and all coefficients are fitted on training data only. No sportsbook lines, target-game outcomes, injuries, weather, quarterback lineup guesses or test-set tuning are used.

734 training games from 2020–2022; 272 validation games in 2023; 272 held-out games in each of 2024 and 2025. Early warmup games without four prior observations are excluded. The actual 2025 tie is excluded only from winner accuracy, leaving 271 winner games; it remains in score/margin/total metrics. The model stays frozen through both test seasons; rolling inputs may use already completed prior-week test-season games, as a real weekly process would.

| Split | Method | Games | Score MAE | Score RMSE | Margin MAE | Total MAE | Winner accuracy |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023 validation | baseline | 272 | 7.669 | 9.707 | 10.564 | 10.410 | 61.40% (272 non-ties) |
| 2023 validation | adjusted | 272 | 7.560 | 9.554 | 10.512 | 10.356 | 59.56% (272 non-ties) |
| 2024 | baseline | 272 | 7.620 | 9.489 | 10.541 | 10.204 | 64.34% (272 non-ties) |
| 2024 | adjusted | 272 | 7.447 | 9.307 | 10.439 | 9.866 | 64.71% (272 non-ties) |
| 2025 | baseline | 272 | 7.550 | 9.511 | 10.467 | 10.685 | 65.31% (271 non-ties) |
| 2025 | adjusted | 272 | 7.518 | 9.436 | 10.373 | 10.634 | 61.99% (271 non-ties) |

The PPP baseline remains primary. A conservative release gate also requires validation winner accuracy not to regress; the adjusted method fails that gate. It also loses winner accuracy in 2025 despite slightly lower scoring errors. No general superiority or statistically significant improvement is claimed. Adjusted is experimental. There is no calibrated probability model, no margin-to-probability conversion, and no advertised calibrated prediction interval. Training residual quantiles are diagnostic metadata only. Favored team means the higher conditional projected mean; this is not a probability estimate from a validated scoring distribution.

Model fingerprint: `2c746d2a6c64d5b2620b688d1f424db89abfa31d7c1fefdcb60af36dcd9c41a0`. Runtime: scikit-learn 1.9.1, pandas 3.0.5, numpy 2.5.3. Output includes feature order, coefficients, intercept, training cutoff/count and fingerprint. The V5 TD model and its weights are not used by this engine.

## Real data, reproducibility and limitations

Sources: [nflverse schedule](https://github.com/nflverse/nfldata/blob/master/data/games.csv), [nflverse play-by-play releases](https://github.com/nflverse/nflverse-data/releases/tag/pbp), [nflfastR field definitions](https://nflfastr.com/articles/field_descriptions.html). Ridge and chronological separation follow the [scikit-learn linear-model documentation](https://scikit-learn.org/stable/modules/linear_model.html#ridge-regression-and-classification) and [time-series splitting guidance](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html). These sources describe data and methods, not this implementation’s predictive accuracy.

Run `python game_projection_evaluate.py --output work/<new-analysis-directory>` to fetch real 2020–2025 PBP, preserve slim raw captures and SHA-256 provenance, prepare team-game tables, fit training-only residuals and reproduce metrics. Only a separate local analysis directory is allowed; production and existing evaluation directories are rejected. Existing report/model outputs are opened exclusively. Cached team-game files must match their capture metadata hashes and the exact normalized scoring implementation hash; older caches without that engine identity are rejected. Local results are in `work/m8-game-evaluation-v2/`; they are not production artifacts and should not be included in the source commit.

A local-only 2024 Week 10 SF–TB reconstruction was rendered and browser-verified: baseline SF 25.619505373340584, TB 24.200425270472127 (SF +1.419080102868456; total 49.81993064381271). Experimental adjusted SF 24.974864814648008, TB 25.401826656783136 (TB +0.4269618421351282; total 50.376691471431144). Sources were captured in October 2026, so this is explicitly retrospective and cannot be published as a genuine 2024 forecast. No historical V5 board was generated or substituted. The temporary review page and copied JSON existed only in an isolated local test tree and are excluded from the final frontend build and source delivery.

Unsupported inputs: strength-of-schedule correction, possession forecasts, turnover-specific decomposition, personnel, weather and pregame QB/injury availability. Red-zone drives per game is displayed from observed drives; a red-zone TD conversion-rate feature is not invented or used. Source feeds may be revised. Across the evaluated 2020–2025 schedule, the smallest observed prior-team-game kickoff separation was 92.5 hours (2024 Week 17 KC–PIT), which avoids overlapping-game completion leakage in this dataset. This is an observed audit, not a universal assumption about rescheduled games; a future producer must confirm completion from its actual captured sources. The adjusted comparison has no uncertainty significance test and does not justify a “better model” claim. Future supervised validation with authentic captured inputs remains necessary.

## JSON and reviewed publication contract — inactive

`schemas/game-predictor.schema.json` is a Draft 2020-12 structural contract. `game_projection_artifact.py` adds semantic schedule/sample, identity, denominator, arithmetic, model fingerprint, train-cutoff, source timing and output checks. Every scheduled game must be represented. Local insufficient-data entries have empty scores and explicit warnings; incomplete artifacts are refused for publication. Win probabilities must be null.

An optional weekly manifest pair `game_predictor` / `game_predictor_sha256` points to exactly `game-predictor.json` in the same new immutable directory as board/breakdowns/receipt. The receipt must contain the identical SHA-256. Original three-file bundles still work. Only the explicit original three or original three plus this named file are accepted; extra files, symlinks, missing pins, hash edits, wrong timestamps or schedule coverage fail closed. Bytes are copied exclusively without reserialization. Existing archives cannot be changed. A data PR changes only the manifest plus three original files (or four snapshot files with Game Predictor).

`weekly_storage`, trusted-base `reviewed_publication`, the draft PR publisher and deployment verifier all validate this optional extension. Both draft-proposal creation and live manifest staging require an additional `NFL_PM_GAME_PREDICTOR_ENABLED=true` process opt-in. No existing workflow supplies it and no variable or secret was changed. No workflow or Vercel build invokes the artifact generator. A source merge alone supplies no Game Predictor data.

`game_projection_cli.py` consumes already captured local team-games, schedule, source metadata and optional model files; source hashes must match those actual input files. Output is new local season/week/run JSON, never the served public tree. Its local attachment helper validates the candidate before modifying only its receipt and appending the new artifact. It does not publish, create branches/PRs or call Vercel. A failed/concurrent attachment remains fail-closed; inspect and rebuild rather than repairing hashes. The current automated weekly generator still produces only its original candidate.

Before production activation: review an explicit captured-input producer and attachment integration, preserve raw source evidence, approve model/version and availability requirements, reconcile any later PR #8 merge, run required fresh data-only checks, and obtain separate owner approval. Retain all protected-environment, main-only manual dispatch, opt-in, concurrency, snapshot, premerge freshness and human-merge requirements. Publishing schedules remain unchanged/disabled in code.

PR #8 overlap: it separately extends the same storage/manifest/receipt and PR-validator files for Matchup Intelligence. A future merge must explicitly combine the two known filename/hash validators and test original, each optional sidecar and both sidecars together. Do not preallow an unmerged artifact without its validator, take one side of a conflict blindly, or loosen wildcards. Current M8 code has no dependency on PR #8 and leaves Game Breakdown untouched.

Deployment verification still identifies exact main commit, Ready Vercel deployment and production alias, then hashes every JSON including inactive archives and rechecks the manifest. The new manifest hash pair is checked before network access. No hook is activated. Rollback remains a reviewed manifest-only PR restoring byte-identical prior main manifest bytes; retain every old/new immutable file. Record the prior Ready deployment and manifest before any supervised merge and verify after separately approved rollback. No rollback or deployment was executed.

## Validation and review inventory

Stage A browser checks cover two/three/all32 teams, clear/reset, combined search/sort/injury filters, empty states, week reset, Add-to-Parlay and bounded mobile controls. New Game Predictor Node/Python tests cover scoring, pace, missing evidence, schedule identities, no future/target leakage, chronological training, probabilities refused, schemas, stale sources, hashes, optional data-only PR restrictions, opt-in required, deployment byte verification and archive-preserving rollback. Real historical UI checks verify exact computed scores, method switching and 320/390/768/1440px widths.

Completed validation: 140 Python tests (124 existing + 16 new), 20 Node tests (freshness + team filtering + Game Predictor), Ruff correctness lint, frontend ESLint, normal production build, existing browser and published-data compatibility suites, and 200 unchanged parlay/Market comparisons against main, all passed. A clean Linux production build used normal `npm ci --no-audit --no-fund && npm run build`, Node v24.22.1, Next 16.4.3; compiled, typechecked and prerendered `/` and `/_not-found` with `BUILD_EXIT_CODE=0`. Temporary nonpersistent sandbox `sbx_WfcDhQp8kQ9hYUSdoz8IuFoa7aKV`, command `cmd_bc1fe43eeb5346b0a8f57064ded2`, was stopped with no exposed routes or snapshot requested. The connector retains sandbox metadata and has no delete operation. No credentials, environment files, caches or unrelated data were uploaded. Log: `work/m8-linux-build.log`. Windows source-only builds compiled/typechecked but encountered local output-directory EPERM during prerendering; this remains a local environment limitation, not a suppressed passing check. A stale temporary-route dev validator was avoided with a fresh source-only validation tree. Browser suites used the local development server for full Stage B and real historical reconstruction; the independent Stage A browser test also passed against its local production build. No skipped build/type checks were used. All 13 existing production JSON files remain byte-identical; V5, parlay/Market calculations, old evaluation datasets, workflows, dependency and deployment configuration are unchanged.

New Python: `game_projection.py`, `game_projection_artifact.py`, `game_projection_cli.py`, `game_projection_evaluate.py`, `test_game_projection.py`.
Modified Python publication support: `weekly_storage.py`, `reviewed_publication.py`, `automation_publish.py`, `verify_publication.py`.
New frontend: `components/game-predictor.tsx`, `lib/team-filter.ts`, `lib/game-projection.ts`, `scripts/team-filter.test.mjs`, `scripts/game-projection.test.mjs`, `scripts/multi-team-smoke.mjs`, `scripts/game-predictor-smoke.mjs` (under `td-predictor-web`).
Modified frontend: `app/page.tsx`, `app/page.module.css`, `components/rankings.tsx`, `lib/types.ts`, `lib/data.ts`, `scripts/browser-smoke.mjs` (under `td-predictor-web`).
Schema/docs: `schemas/game-predictor.schema.json`, this document and `README.md`.

Exclude `work/`, source downloads, fitted model/report outputs, screenshots, caches, unrelated local files and temporary review routes from any future approved commit. No commit, push, PR, merge, production-data change or activation occurred during implementation.

## Final PR integration audit

Main remains `4b168c2b59bf7d667a1d1a1e66d0f8e0d597298e`; PR #8 is open and unmerged at `74a889a9f3237fa9db64bdb4ecca174cc8a1c871`. Ten files overlap:

- `README.md`
- `automation_publish.py`
- `reviewed_publication.py`
- `td-predictor-web/app/page.module.css`
- `td-predictor-web/app/page.tsx`
- `td-predictor-web/lib/data.ts`
- `td-predictor-web/lib/types.ts`
- `td-predictor-web/scripts/browser-smoke.mjs`
- `verify_publication.py`
- `weekly_storage.py`

Potential conflicts are behavioral as well as textual. `weekly_storage.py` and `reviewed_publication.py` must ultimately derive one explicit allowed bundle from both validated receipt pins; running two separate exact-file allowlists would incorrectly reject a bundle containing both sidecars. The eventual combined contract must validate old bundles, each sidecar independently, both together, mismatched pins, extra files, immutable archives and manifest-only rollback. Neither validator may be silently dropped or changed to a wildcard.

Frontend manifest validation must require both optional URL/hash pairs independently, types must retain both additions, and page navigation must keep the separate Game Predictor while preserving Matchup Intelligence's Game Breakdown props. Retain distinct CSS classes and both browser test additions. Deployment checks must verify both hash pins and all archived JSON bytes. Keep per-feature publishing opt-ins and provenance requirements; the evaluator now reports baseline as primary unconditionally, even if an experimental validation gate passes in another analysis.

Recommended order, subject to separate owner approvals: review the independent Stage A commit; merge reviewed Milestone 7 PR #8 first; then explicitly reconcile/rebase Milestone 8 Stage B against the resulting main, resolve these shared-contract changes and rerun all combined-contract tests before considering its merge. No merge, rebase onto PR #8, source absorption or production activation is performed by this audit. A Git mergeability result against today's main does not prove the two feature branches will integrate cleanly.

Historical source vintage remains an activation blocker, not evidence of verified pregame availability. The retrospective model fingerprint and every held-out metric were reproduced from preserved local team-game inputs during final review. Inputs are prior-week/as-of filtered, with train through 2022, validation 2023, untouched test seasons 2024–2025; original capture availability cannot be established from current revised feeds. A future captured-input producer and exact-commit/Ready/alias/JSON/browser deployment verification require separate approval and review before any publication.

Final scoring audit also rejects missing field-goal, PAT and two-point attempt outcomes and missing touchdown-team identity. Verified non-attempts and explicit source “No Play” records are excluded, rather than interpreted as failed kicks. The preserved/new source comparison confirms this hardening changes no valid 2020–2025 team aggregates or reported model metrics. Regression subtests cover each missing-result path and nullified/non-attempt conversions.

A read-only `git merge-tree` simulation of the two feature tips confirmed nine textual conflicts: README.md, automation_publish.py, reviewed_publication.py, td-predictor-web/app/page.module.css, td-predictor-web/app/page.tsx, td-predictor-web/lib/data.ts, td-predictor-web/lib/types.ts, verify_publication.py and weekly_storage.py. The tenth overlapping file, browser-smoke.mjs, merged textually in the simulation but still needs combined behavioral checks. No branch, index or working-tree merge was performed. Both source PRs currently share the same main base; these conflicts are between the feature branches, not evidence of a present conflict against main.


## Milestone 7 main integration — 2026-10-30

This section supersedes the earlier pre-merge PR #8 integration audit. Verified origin/main is `5bceee124df9edbdb0fcfaab4468cc51bf73861f`. Backup `backup/m8-before-m7-integration` preserves `de83b8ebb3acf0e06f10978f166f6576bc09ff08`. Main was integrated locally into the Game Predictor feature branch; no push, PR, production merge or deployment is authorized by this integration review.

Nine conflict resolutions preserve both implementations: README retains both feature descriptions; page CSS retains independent intelligence, predictor and team-filter rules; page TSX retains Game Predictor navigation and Matchup Intelligence props on Game Breakdown; types and manifest decoding require each optional URL/hash pair independently; publisher stages the shared explicit bundle; reviewed publication permits only core, core plus either known sidecar, or core plus both; storage validates and copies both artifacts with both manifest pins; deployment verification checks both pins before production requests. `matchup_publication.bundle_files` is the single receipt-derived file allowlist, reused by Game Predictor candidate handling. Existing allowlist, regular-file and symlink guards remain enforced. No wildcard permissions were added.

New combined regression tests exercise both attachment orders, exact archived bytes, each hash and missing-file rejection, stale candidates, a data-only PR containing both artifacts, deployment hash failures for either artifact, and manifest rollback retaining both immutable files. Existing tests retain kickoff, freshness, identity, provenance, opt-in and immutable-archive protection. Both optional features remain unavailable on published weeks with absent sidecars; browser tests verify that no invented scores or recommendations appear. PPP remains primary and adjusted ridge experimental, with null win probabilities.

Integration validation: 196 Python tests passed; 35 Node tests passed; Ruff F checks and frontend ESLint passed; both JSON schemas, local historical Game Predictor artifact, isolated test-only matchup artifact and all published manifest references validated. Five browser suites passed: browser-smoke, publication-smoke, multi-team-smoke, game-predictor-smoke and matchup-smoke. All 200 parlay/Market calculation comparisons match origin/main. All 13 production JSON files remain byte-identical, and V5, parlay/Market, historical evaluation data, workflows and deployment configuration are unchanged.

The clean Linux normal install/build logs show successful compilation, TypeScript, static prerendering of all four pages, final optimization and route summary (Node 24.22.1, Next 16.4.3). Temporary nonpersistent environment `sbx_o8CZf17FAATN8F1BnTSSh7ZfpqAP` had no exposed routes, received no credentials and was stopped after completion logs. Its command metadata had not populated the terminal exit field before stop; a later wait request was unavailable because it was stopped. Build completion evidence is preserved in `work/m8-integration-linux-build.json`. Windows compiled/typechecked but again failed on EPERM mkdir while prerendering /_not-found. No specific Windows antivirus, ACL or lock root cause has been proven; no validation or build checks were disabled.

Release blockers remain: authentic original pregame source vintage (historical captures are retrospective), five unresolved historical Matchup Intelligence roster records, a reviewed captured-input producer/attachment integration, separate owner activation approval, and exact merged-commit Ready/production-alias/JSON-hash/browser verification with recorded rollback deployment. No source merge activates either artifact. Existing manual-only publication workflow, false-default publish input, protected environment, reviewed draft PRs and all opt-ins remain unchanged. No predictions were generated or published during this integration.
