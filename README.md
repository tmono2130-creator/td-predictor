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
