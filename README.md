# NFL Touchdown Prediction Project

This repository keeps the existing Python predictor and static JSON website workflow. `td_predictor_v5.py` remains the production prediction entry point; `export_json.py` runs it and publishes validated weekly data under `td-predictor-web/public/data`.

## Current project map

- `td_predictor_v5.py` — V5 composite model, with optional fitted-model loading when a locally trained `model_v6.joblib` exists.
- `export_json.py` — runs the V5 model and writes weekly board/breakdown JSON plus the data manifest.
- `game_breakdown.py` — builds matchup and usage breakdowns from schedule and play-by-play data.
- `data_schema.py` — Python validation for the public JSON contract.
- `test_data_pipeline.py` — lightweight standard-library tests for validation and weekly publishing.
- `build_training_data.py`, `model_v6.py`, `train_final_model.py`, `backtest.py` — model evaluation/training tooling, separate from the default production workflow.
- `td-predictor-web/` — Next.js frontend. It loads static files from `public/data`; it does not call `api.py`.
- `api.py` and `streamlit_app.py` — alternate/older Python interfaces retained in the repository; not used by the Next.js frontend.

## Weekly JSON contract

Schema version 1 stores each export independently:

```text
public/data/manifest.json
public/data/{season}/week-{week}/{run-id}/board.json
public/data/{season}/week-{week}/{run-id}/breakdowns.json   (optional when exported with --skip-breakdowns)
```

The board uses `meta` and `rows`, matching both the exporter and the frontend. `meta` carries season, week, timestamp, model name, and final scores. Each row carries player identity, team/opponent, status, and `td_score`/`td_estimate`. `td_score` keeps V5's 0–100 ranking-score scale; `td_estimate` is the calibrated touchdown probability percentage. In fitted-model mode V5 sets both to probability × 100. This pipeline change does not alter model calculations or reinterpret the composite score. The manifest points only to weeks whose board export passed validation. It lists regular-season weeks 1–18 so the website can label ungenerated weeks and never substitute another week.

A publish validates the board and (when present) breakdown metadata before writing. Each export writes to a unique run folder and atomically replaces the manifest pointer last. A failed model run or validation error does not replace the last published files or manifest entry. Existing `public/data/board.json` is an old placeholder and is no longer consumed by the frontend.

## Windows setup and run

From the repository root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python export_json.py --season 2026 --week 8 --out .\td-predictor-web\public\data
```

Repeat the export for each week you want to publish. The site keeps prior weeks in their own folders. To skip matchup breakdowns:

```powershell
python export_json.py --season 2026 --week 8 --skip-breakdowns --out .\td-predictor-web\public\data
```

Start the website from its folder:

```powershell
cd .\td-predictor-web
npm ci
npm run dev
```

The season and week selectors include all supported regular-season weeks. The default is the latest generated week for the newest published season. Selecting a week without generated data shows an explicit message.

## Checks

From the repository root:

```powershell
python -m unittest -v test_data_pipeline.py
```

From `td-predictor-web`:

```powershell
npm run lint
npm run build
```

## Model status

The V5 composite is still the default. V6 contains held-out-season candidate evaluation for logistic regression and gradient boosting; `train_final_model.py` can create a fitted model bundle, and V5 will use that bundle if one is present. No `model_v6.joblib` is committed, so the repository's checked-in weekly placeholder is not evidence of live fitted-model predictions. Keep V6 evaluation separate and compare it on held-out seasons before treating a candidate as a production improvement.
## Milestone 2 — reliability and evaluation safeguards

### Injury statuses

The prediction pipeline uses nflverse weekly official team injury reports (`load_injuries`). The official dataset separates `report_status` (Out, Doubtful, Questionable, when designated) from `practice_status` (practice participation); those fields are not interchangeable. This feed does not publish an `Active` game status for every player. A missing weekly report, missing player row, or blank report designation is now `Unknown`; only an explicit source value can become `Active`. `Unknown` does not change the V5 score and is not displayed as confirmed Active. The website reports whether that week has any injury-report rows. Status does not represent final gameday inactives.

The feed was checked on 2026-10-26: the 2026 dataset returned injury report rows for Weeks 1–7 only (2,139 rows total; Week 7 had 350). There were no report rows for Weeks 8 or 9 yet. The repaired player-ID mapping matched 101 Week 7 player profiles; only 42 of those had explicit game designations. No player status is inferred for Weeks 8–9.

### Prediction timing and player/game integrity

V5's live stat features use the prior season plus current-season player stats strictly before the requested week. The team scoring environment and current-season defensive history also stop before the target week. Same-week scores and scorer stats are attached only to annotate completed games; they do not feed `td_score` or `td_estimate`. V5 weights and score calculations were not changed.

Each new board now includes the official schedule's `game_id`, matchup, UTC kickoff, and per-game record timing. An export timestamp before kickoff is labeled `pregame_snapshot`; after kickoff it is labeled `historical_backfill`. This documents when the artifact was saved relative to kickoff. Historical feature data does not have archived source vintages or input checksums, so reconstructed historical rows are not proof that the exact same source data was available then. Week 7's refreshed board has 13 retrospective games and one pregame snapshot; Weeks 8 and 9 were saved before their scheduled kickoffs on 2026-10-26.

Validation now requires every player row to map to a scheduled game and matching team/opponent pair, rejects duplicate player/game predictions, checks injury/game/timing categories, and verifies that all scheduled games are present in board metadata. The website rejects mismatched breakdown week/game pairs. Parlays and market comparisons use only games whose status is Upcoming; In Progress, Final, and Unknown games are excluded.

### Backtest and V6 status

The checked-in `training_data.csv` is not valid for V6 training. It contains 15,952 rows for 2026 Weeks 2–18, all labeled `actual_td=0`, although the current 2026 weekly player-stat source now contains touchdown outcomes through Week 7. This file is stale relative to the source and includes future/unplayed weeks. `model_v6_predictions_2025.csv` was produced using that dataset. The old V6 split trained on every season other than the holdout, including later seasons, so its held-out claims were temporally contaminated. Those artifacts are retained for provenance but must not be used as a trustworthy model comparison.

The 2024 and 2025 backtest CSVs are retrospective reconstructions with no export-time/source-vintage evidence. Their descriptive averages show an apparent 1.49 and 1.64 percentage-point mean probability shortfall respectively (Brier 0.0536/0.0549; log loss 0.1844/0.1904; score AUC 0.869/0.862). These are not valid calibration claims: V5's checked-in probability lookup was fit on 2025, and the rows were regenerated after the seasons ended. No V5 weights were changed.

The rebuilt data workflow skips any week whose full regular-season schedule lacks final scores, joins outcomes by both `player_id` and `game_id`, and labels every row `retrospective_backfill` with a generation time and pre-week feature cutoff. `model_v6.py` and `train_final_model.py` now reject legacy data without these checks. V6 trains only on seasons earlier than the held-out season, and its V5 ranking-score baseline is calibrated on earlier seasons only. Rebuild training data before running either script:

```powershell
python build_training_data.py --seasons 2023 2024 2025 --out training_data_validated.csv
python model_v6.py --data training_data_validated.csv --holdout 2025
```

Reconstruction remains useful for development, but a trustworthy pregame performance record requires forecasts archived before kickoff along with feature/feed versions. Save weekly exports before games, then evaluate those saved board rows only after the full week has final scores.

## Milestone 3 — historical evaluation (retrospective only)

Run the historical reconstruction from this directory:

```powershell
python build_training_data.py --seasons 2023 2024 2025 --out-dir evaluation
python model_v6.py --data evaluation/historical_evaluation_data.csv --validation-season 2024 --test-season 2025 --out-dir evaluation
```

The validated nflverse seasons are 2023–2025 (18 completed regular-season weeks each). `historical_player_games.csv` contains the full participation-verified set; `historical_evaluation_data.csv` contains rows with a matched V5 prediction and GSIS player ID. Participation requires a positive offensive snap or a positive rushing/receiving TD record. A rushing/receiving TD is independent evidence of participation. Passing TDs do not count as the player's anytime TD. Multiple TDs are retained in `actual_td_count`; `actual_td` is its binary form. Schedule game IDs, teams, opponents, score completion, and duplicates are checked before writing.

Historical V5 features are reconstructed with target-week player statistics cut off at the end of the prior week, complete prior-season information for Week 1, target-week roster snapshots, and prior-game team and opponent results. Injury designations are excluded because the public feed does not preserve when each designation was published. Weekly rosters and other upstream data are current retrospective downloads, not archived pregame vintages; later corrections to earlier-week statistics cannot be ruled out. Therefore these files are explicitly `retrospective_backfill`, not evidence of predictions made before kickoff. Evaluation is conditional on participation and stable player-ID matches; it does not measure how the model handled inactive players in the full pregame player pool.

`evaluation/historical_data_summary.json` documents dataset coverage and limitations. The evaluation script fits the V5-score calibrator and V6 candidates on seasons before each validation/test season; it reports Brier score, log loss, AUC when both labels exist, 10-bin ECE and calibration, ranking top-10/20/30, and season/week/position slices. `td_score` is a ranking score, not a probability. The legacy fixed `td_estimate` curve is retained in the player rows for inspection but excluded from metrics because it was fit using 2025 outcomes. The 2025 retrospective period is not an untouched final test: V5 weights were developed using 2024–25 evidence. Do not use these metrics as verified live forecasting claims or to retune V5 weights.

New JSON snapshots now include a source/model fingerprint, probability-field semantics, UTC prediction time, kickoff, and per-game/per-row snapshot classification. Each run has a unique immutable directory; a collision fails instead of replacing the prior artifact. Since the public upstream feeds do not supply immutable source revisions, metadata says so. No historical performance page was added to the website because no genuine archived pregame evaluation exists; all four existing tabs remain untouched.

## Milestone 5 — weekly automation (dormant pending approval)

The Python-to-static-JSON architecture and V5 scoring code are preserved. No backend or new model is introduced. The live website reads `/data/manifest.json`, backed by **`td-predictor-web/public/data`**. The repository-root `public/` folder is not the frontend data root. At the audit, the production manifest at [td-predictor.vercel.app](https://td-predictor.vercel.app/data/manifest.json) matched the local Weeks 7–9 manifest. Local main and GitHub main both pointed to Milestone 4 commit `07c116e` before implementation. No repository Actions workflows existed.

### Commands

From the repository root (Python 3.13):

```powershell
python -m pip install -r requirements-automation.txt
python weekly_pipeline.py plan
python weekly_pipeline.py plan --season 2026 --week 8
python weekly_pipeline.py generate
python weekly_pipeline.py generate --season 2026 --week 8 --candidate work/my-new-candidate
python weekly_pipeline.py validate --candidate work/my-new-candidate
python weekly_pipeline.py validate
python weekly_pipeline.py index --data td-predictor-web/public/data
```

Generation **does not publish**. Its default destination is a new `work/weekly-candidates/<UTC-run-id>` directory. An explicitly supplied candidate directory must not already exist; regeneration uses a fresh directory rather than overwriting an earlier forecast. Both board and breakdown must succeed. No fitted V6 artifact is consulted. `requirements-automation.txt` pins the top-level versions used for validation; upstream feed revisions remain outside our control.

After reviewing and approving a specific candidate, this command publishes it to the **local** frontend data directory; deployment still requires a reviewed Git push and supported deployment trigger:

```powershell
python weekly_pipeline.py publish --candidate work/my-new-candidate
```

Publication re-fetches the schedule, checks every remaining matchup/kickoff, and rejects any game that has started since generation. Do not use the older `export_json.py` CLI for unattended publishing: it remains available for legacy/manual workflows but lacks the new strict publication gates.

### Week detection, refresh cadence, and data cutoffs

`weekly_schedule.py` downloads the same nflverse schedules release used by nflreadpy. It uses regular-season game types, schedule season/week, actual kickoff dates and Eastern game times converted with `America/New_York` to aware UTC. It supports Weeks 1–18, international morning starts, Monday/Tuesday UTC crossings, DST, January games belonging to the previous season, byes, distant TBD kickoff times, and mixed completed/upcoming weeks. A TBD kickoff in the selected week fails safely. Calendar week numbers are never used. Automatic mode selects the week of the earliest future uncompleted regular-season game within ten days. Outside that window it returns idle, rather than generating a nonexistent week or replaying Week 18. Source failure is an error, not an offseason result. Manual mode requires both season and week.

Only future uncompleted games enter a live batch. The batch must cover **all** remaining games and the complete eligible roster pool for those games. Earlier games remain available in immutable archives; the new active board does not recompute their outcomes or relabel them as pregame. A kickoff during generation/publication aborts the batch; regenerate to obtain the remaining slate.

The proposed dormant schedule checks every six hours, plus twice hourly during broad possible kickoff hours, September–January. Cheap schedule checks run before heavy dependencies or model work. `plan --due-only` permits generation daily more than 48 hours before the next kickoff, every six hours within 48 hours, and every 30 minutes within six hours. Cron timing is UTC and GitHub can delay scheduled runs; this is not a guaranteed final-inactives or last-second service. On unusual game days the same schedule checks apply. No February–August schedule is proposed. Manual runs remain available for testing.

`weekly_sources.py` bypasses persistent caches and retries each source three times with bounded backoff/timeouts. Required-source failure, incomplete completed-game stats/PBP, ambiguous roster assignments, missing columns, or unresolved forecast IDs abort generation. Optional injury outages yield **Unknown**, never Active. The player pool uses skill-position players with explicit `ACT` roster membership, independently of injury status; practice squad (`DEV`), reserve (`RES`), released, and retired players are excluded until a later source update changes membership. Live runs prefer target-week rosters, falling back only to a live season roster fetched before kickoff. Historical runs forbid that fallback. Player GSIS IDs must resolve in the nflverse player crosswalk. The receipt records pool policy and exclusions.

All model and breakdown features use completed regular-season games **strictly before the target week**, including three prior seasons for defensive history and prior/current-season PBP. Completed games in the target week never enter features. This deliberately conservative cutoff also prevents the original breakdown loader's later-week player metadata from leaking into reconstruction. Carry, target, rushing/receiving, role and red-zone calculations use existing V5 functions and weights. Roster players with no game history retain the existing V5 no-history prior and `games=0`; these are not invented observed statistics. No odds/public-opinion features are added.

### Validation and immutable snapshots

`weekly_storage.py` validates schema, season/week, actual schedule pairs, complete eligible player/game/team coverage, stable IDs, duplicates, probability ranges and alias equality, game states, aware timestamps, model identity, exact breakdown coverage/table shapes/sample metadata, source provenance, and hashes. Candidate `receipt.json` records input retrieval times, hashes, row counts, pool policy, expected schedule/identities, and the base published manifest hash. These are retrieval fingerprints, **not** claims that upstream source releases are immutable.

The publication lock prevents two local writers. A base-manifest mismatch rejects stale publication. Every success creates a new UUID-versioned directory with `board.json`, `breakdowns.json`, and `receipt.json`; existing snapshot files are never replaced. Both files validate and are written before an atomic manifest replacement. Invalid data or a failed manifest swap leaves the last published manifest and old files intact. An interrupted run can leave an unreferenced immutable directory; review it manually rather than deleting archives automatically. A stale `.weekly-publish.lock` must be investigated and removed manually only after confirming no publisher is running.

`index` scans archive boards and selects the latest explicitly pregame prediction timestamp strictly before scheduled kickoff for each player/game. Historical boards cannot enter the index. A pregame row within an older mixed board must have explicit row/game classification and a recorded pre-kickoff timestamp. It prints an evaluation-ready reference list without changing evaluation datasets. Each row retains the model fingerprint, probability, player/game IDs, prediction timestamp, kickoff and archive reference. The receipt preserves source metadata. Existing historical evaluation files are unchanged; the missing `hashlib` and `json` imports were fixed in `build_training_data.py`.

### Historical board coverage

Historical boards use a **separate, unpublished** path, without the participation-only evaluation join:

```powershell
python weekly_pipeline.py historical --season 2026 --week 1 --candidate work/historical-week1-review
python weekly_pipeline.py validate --candidate work/historical-week1-review --allow-historical
```

A complete target-week schedule and weekly active roster are mandatory. Features use prior-week cutoffs, outcomes stay unavailable, and injuries stay Unknown because historical publication timestamps are unavailable. Every row/game/board is explicitly `historical_backfill`. Source-vintage and roster-revision limitations mean these boards are retrospective analysis, not evidence of genuine live prediction performance. A live-source Week 1 trial passed with 452 players/16 games. This does **not** certify all other missing weeks; each must be generated, validated, and reviewed separately. Existing Weeks 7–9 and their archived versions are untouched.

Historical publication is never allowed in the workflow. If a reviewed backfill is approved later, `publish --candidate <path> --allow-historical` still refuses to replace any existing week. No historical backfills have been published in this milestone; Not Generated remains visible for missing weeks.

### GitHub Actions and activation steps

`.github/workflows/weekly-predictions.yml` has **only `workflow_dispatch` active**. Scheduled cron examples are comments. A local commit does not activate workflows or publishing; activation requires the separate approval steps below.

1. Review this branch and approve committing/merging the implementation.
2. Run the workflow on the reviewed branch with **publish=false**. Leave season/week blank for auto-detection, or supply both. The plan is lightweight; generation installs pinned dependencies, runs all Python tests, generates/validates a fresh candidate, and uploads only candidate JSON for 14 days. Live GitHub-hosted execution has not been run yet.
3. Review the artifact's board, breakdown and receipt. Do not promote expired candidates: kickoff is checked again at publication.
4. Create GitHub environment **`nfl-pm-production`**, restrict deployment branches to **main**, and require an owner reviewer during initial validation. Branch protection must permit the data bot's normal push; if it rejects the push, stop and use the repository's reviewed process rather than granting force/bypass access.
5. Configure a Vercel **Deploy Hook for main**. Store its full URL as protected environment secret **`NFL_PM_VERCEL_DEPLOY_HOOK`**. Set repository variable **`NFL_PM_DEPLOYMENT_MODE=deploy_hook`**. Never paste the hook into source, workflow logs or chat. It is a bearer secret.
6. After explicit approval, set **`NFL_PM_PUBLISHING_ENABLED=true`**. A manual main run also needs **publish=true**, and must pass the protected environment. A feature-branch run cannot publish. The publication job alone has `contents: write`; checkout does not persist credentials. The token is scoped to the publication step, and staging is limited to the one new JSON bundle plus the manifest.
7. Verify a manual main publication end to end: normal data-only commit, Vercel deployment **READY**, production manifest references and generated timestamp match, all referenced files return HTTP 200, then browser smoke checks. A hook acceptance response is only a trigger acknowledgment.
8. Only after that test and your approval, uncomment the proposed `schedule` events. The same repository opt-in, main check and environment gate apply. Keep reviewers if desired; remove recurring manual review only after a separate approval for unattended publishing.

The workflow refuses publication if main moved after checkout; it never merges/rebases unrelated changes and never force-pushes. It stages exactly the new three JSON files and manifest. Jobs are serialized with `cancel-in-progress: false`.

**Disable automation:** set `NFL_PM_PUBLISHING_ENABLED=false` immediately to block publication, then remove/comment schedule triggers or disable the workflow in GitHub Actions. Existing static data continues to serve. Dry-run generation does not carry production secrets or write permissions.

### Vercel deployment behavior and verification status

GitHub documents that `GITHUB_TOKEN` pushes do not start additional GitHub Actions workflows ([token behavior](https://docs.github.com/en/actions/concepts/security/github_token)). This does not by itself prove that a third-party Vercel Git integration will or will not deploy the bot commit. Plan/account/author/project rules must be verified for this repository. Do **not** assume a data commit updates production automatically.

A main-branch [Vercel Deploy Hook](https://vercel.com/docs/deploy-hooks) is the supported explicit trigger implemented here; it is called only after a successful data push, using the protected environment secret without printing its URL. A failed trigger reports failure and leaves the committed data intact for a manual deployment. The alternative **`NFL_PM_DEPLOYMENT_MODE=verified_git`** is allowed only after independently proving that the actual repository token's data push produces a READY production deployment. No personal access token is hardcoded or requested.

Production's existing manifest and Week 8 board were read successfully during the audit. Vercel project-level inspection returned a team-scope 403; no bot-triggered deployment or hook has been executed. **Automated deployment is not verified or enabled.** See [Vercel GitHub integration](https://vercel.com/docs/git/vercel-for-github) for project settings. No deploy hook was created or secret configured by this work.

### Freshness and troubleshooting

The existing dark dashboard is preserved. Small metadata indicators show recorded model version, snapshot classification and freshness. Freshness compares the saved generation timestamp with actual kickoff proximity; it does not invent update times, fetch live predictions or imply historical forecasts are live. Stale snapshots remain viewable with a Refresh Due label, and missing weeks retain Not Generated.

- **Schedule/source outage:** inspect the failing source step and retry later; the last published data is unchanged. Required-source failures cannot silently fall back to stale forecasts or zero statistics.
- **Coverage/identifier error:** resolve upstream roster/game IDs or missing completed-game data; do not lower the coverage threshold to publish a partial batch.
- **Kickoff passed:** regenerate; never relabel a post-kickoff run as authentic pregame.
- **Manifest/main changed:** generate a fresh candidate on the current reviewed main; no auto-merge or overwrite is attempted.
- **Vercel trigger failure:** inspect whether the data commit exists, then trigger/verify the main deployment manually. Do not print the secret hook URL.
- **Turbopack worker cache error locally:** stop the local server and perform a fresh build with a fresh ignored `.next` cache; do not change model data or disable validation.

Checks:

```powershell
python -m unittest discover -v
cd td-predictor-web
npm run lint
npm run build
npm run start -- --port 3104
# Separate terminal in td-predictor-web, with Playwright available:
node scripts/browser-smoke.mjs
```

Freshness helper tests (Node 24+): `node --experimental-strip-types --test scripts/freshness.test.mjs` from `td-predictor-web`. Node may emit a harmless module-type inference warning; no package configuration change is required.

Unpublished candidate browser checks (after starting the frontend, Playwright + Chrome available):

```powershell
# Run inside td-predictor-web; these intercept requests without writing public/data:
$env:CANDIDATE_DIR='../work/my-new-candidate'
node scripts/candidate-smoke.mjs
```

Some legacy exports lack explicit model fingerprints or snapshot-classification fields. The UI shows unavailable metadata rather than inventing it, and the final-forecast index excludes archives without sufficient provenance. Those legacy files are preserved byte-for-byte.
