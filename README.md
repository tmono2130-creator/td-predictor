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
