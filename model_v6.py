"""Leakage-aware chronological model evaluation for historical backfills."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from historical_data import EVALUATION_POSITIONS


FEATURES = [
    "opportunity_score", "red_zone_score", "efficiency_score", "opportunities_pg",
    "redzone_opportunity_pg", "td_rate", "targets_pg", "carries_pg", "receptions_pg",
    "target_share", "receiving_yards_pg", "rushing_yards_pg", "matchup_score",
    "team_environment_score", "is_home", "days_rest", "recent_ppg",
    "recent_points_allowed", "opp_recent_ppg", "opp_recent_points_allowed",
    "role_score", "games",
]


def validate_evaluation_data(frame):
    required = {"player_id", "game_id", "season", "week", "position", "actual_td",
                "actual_td_count", "td_score", "prediction_origin", "feature_cutoff_season",
                "feature_cutoff_week"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Evaluation dataset is missing fields: {sorted(missing)}")
    if not frame.prediction_origin.eq("retrospective_backfill").all():
        raise ValueError("Only explicitly retrospective rows are supported by this evaluation.")
    if frame[["player_id", "game_id"]].isna().any().any() or frame[["player_id", "game_id"]].astype(str).apply(lambda c: c.str.strip().eq("")).any().any():
        raise ValueError("Missing stable player/game identity.")
    if frame.duplicated(["season", "week", "player_id", "game_id"]).any():
        raise ValueError("Duplicate player/game prediction observations.")
    if not frame.position.isin(EVALUATION_POSITIONS).all():
        raise ValueError("Evaluation data includes a position outside QB/RB/WR/TE.")
    if not frame.actual_td.isin([0, 1]).all():
        raise ValueError("Actual touchdown labels must be binary.")
    td_count = pd.to_numeric(frame.actual_td_count, errors="coerce")
    if td_count.isna().any() or (td_count < 0).any() or not td_count.gt(0).astype(int).eq(frame.actual_td.astype(int)).all():
        raise ValueError("Actual touchdown counts and binary labels disagree.")
    if (pd.to_numeric(frame.td_score, errors="coerce").isna()).any():
        raise ValueError("V5 ranking score contains missing or invalid values.")
    weeks = pd.to_numeric(frame.week, errors="coerce")
    seasons = pd.to_numeric(frame.season, errors="coerce")
    expected_cutoff_season = seasons.where(weeks > 1, seasons - 1)
    expected_cutoff_week = weeks.where(weeks > 1, 18) - (weeks > 1).astype(int)
    if not pd.to_numeric(frame.feature_cutoff_season, errors="coerce").eq(expected_cutoff_season).all():
        raise ValueError("Feature cutoff season is inconsistent with the target week.")
    if not pd.to_numeric(frame.feature_cutoff_week, errors="coerce").eq(expected_cutoff_week).all():
        raise ValueError("Feature cutoff week is inconsistent with the target week.")
    return frame


def chronological_holdout(frame, holdout_season):
    """Split strictly earlier training seasons from the requested holdout."""
    train = frame[frame["season"] < holdout_season].copy()
    test = frame[frame["season"] == holdout_season].copy()
    if train.empty or test.empty:
        raise ValueError(f"Need earlier training data and holdout season {holdout_season}.")
    return train, test

def _probability_metrics(y, p):
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-8, 1 - 1e-8)
    auc = float(roc_auc_score(y, p)) if np.unique(y).size == 2 else None
    bins = np.linspace(0, 1, 11)
    labels = np.digitize(p, bins[1:-1], right=False)
    calibration = []
    ece = 0.0
    for index in range(10):
        mask = labels == index
        if not mask.any():
            continue
        predicted, observed, n = float(p[mask].mean()), float(y[mask].mean()), int(mask.sum())
        ece += n / len(y) * abs(predicted - observed)
        calibration.append({"bin_lower": round(float(bins[index]), 2),
                           "bin_upper": round(float(bins[index + 1]), 2),
                           "n": n, "mean_predicted": predicted,
                           "observed_rate": observed})
    return {
        "n": int(len(y)), "positives": int(y.sum()), "actual_rate": float(y.mean()),
        "mean_predicted": float(p.mean()), "bias_pred_minus_actual": float(p.mean() - y.mean()),
        "brier": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "auc": auc, "ece_10": float(ece), "calibration_bins": calibration,
    }


def _topn_metrics(group):
    out = {}
    ordered = group.sort_values("probability", ascending=False, kind="stable")
    for n in (10, 20, 30):
        top = ordered.head(min(n, len(ordered)))
        out[f"top{n}_n"] = int(len(top))
        out[f"top{n}_hits"] = int(top.actual_td.sum())
        out[f"top{n}_hit_rate"] = float(top.actual_td.mean()) if len(top) else None
    return out


def _prior_rate_baselines(frame, train):
    position_rates = train.groupby("position").actual_td.mean().to_dict()
    global_rate = float(train.actual_td.mean())
    histories = {}
    rates, recent = {}, {}
    # All predictions in a target week use data through the previous week.
    for (season, week), group in frame.sort_values(["season", "week"]).groupby(["season", "week"], sort=True):
        for idx, row in group.iterrows():
            pos_base = float(position_rates.get(row.position, global_rate))
            player_hist = histories.get(str(row.player_id), [])
            rates[idx] = (sum(player_hist) + 10 * pos_base) / (len(player_hist) + 10)
            recent_values = player_hist[-6:]
            recent[idx] = (sum(recent_values) + 3 * pos_base) / (len(recent_values) + 3)
        for _, row in group.iterrows():
            histories.setdefault(str(row.player_id), []).append(int(row.actual_td))
    return (pd.Series(rates).reindex(frame.index).clip(1e-6, 1 - 1e-6),
            pd.Series(recent).reindex(frame.index).clip(1e-6, 1 - 1e-6),
            position_rates, global_rate)

def _fit_probability_models(train, test, feature_columns):
    imp = SimpleImputer(strategy="median")
    xtr = imp.fit_transform(train[feature_columns])
    xte = imp.transform(test[feature_columns])
    ytr = train.actual_td.to_numpy(dtype=int)
    if len(np.unique(ytr)) < 2:
        raise ValueError("Training fold has only one outcome class.")
    scaler = StandardScaler()
    logit = LogisticRegression(max_iter=2000, C=1.0)
    logit.fit(scaler.fit_transform(xtr), ytr)
    logit_p = logit.predict_proba(scaler.transform(xte))[:, 1]
    gbm = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05,
                                         l2_regularization=1.0, random_state=0)
    gbm.fit(xtr, ytr)
    gbm_p = gbm.predict_proba(xte)[:, 1]

    opportunity_features = [c for c in ("opportunity_score", "red_zone_score", "opportunities_pg",
                                         "redzone_opportunity_pg", "targets_pg", "carries_pg") if c in feature_columns]
    oi = SimpleImputer(strategy="median")
    oxtr, oxte = oi.fit_transform(train[opportunity_features]), oi.transform(test[opportunity_features])
    oscaler = StandardScaler()
    opp_model = LogisticRegression(max_iter=2000, C=1.0)
    opp_model.fit(oscaler.fit_transform(oxtr), ytr)
    opp_p = opp_model.predict_proba(oscaler.transform(oxte))[:, 1]
    return logit_p, gbm_p, opp_p


def evaluate_chronologically(frame, validation_season, test_season, out_dir):
    frame = validate_evaluation_data(frame.copy())
    frame["season"] = pd.to_numeric(frame.season).astype(int)
    frame["week"] = pd.to_numeric(frame.week).astype(int)
    frame["actual_td"] = pd.to_numeric(frame.actual_td).astype(int)
    frame["position"] = frame.position.astype(str).str.upper()
    seasons = sorted(frame.season.unique().tolist())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prediction_frames = []
    folds = [(validation_season, [s for s in seasons if s < validation_season], "validation"),
             (test_season, [s for s in seasons if s < test_season], "retrospective_test")]
    features = [c for c in FEATURES if c in frame.columns and pd.api.types.is_numeric_dtype(frame[c])]
    if not features:
        raise ValueError("No eligible numeric pregame features are available for V6.")
    for holdout, train_seasons, fold_name in folds:
        train = frame[frame.season.isin(train_seasons)].copy()
        test = frame[frame.season == holdout].copy()
        if train.empty or test.empty:
            raise ValueError(f"Fold {fold_name} needs earlier training seasons and {holdout} rows.")
        print(f"Fitting {fold_name}: train seasons={train_seasons}; holdout={holdout}; "
              f"train n={len(train):,}; holdout n={len(test):,}", flush=True)
        calibrator = IsotonicRegression(y_min=1e-6, y_max=1 - 1e-6, out_of_bounds="clip")
        calibrator.fit(train.td_score.to_numpy(float), train.actual_td.to_numpy(int))
        v5_p = calibrator.predict(test.td_score.to_numpy(float))
        logit_p, gbm_p, opp_p = _fit_probability_models(train, test, features)
        prior_p, recent_p, _, _ = _prior_rate_baselines(frame[frame.season <= holdout], train)
        test = test.copy()
        test["fold"] = fold_name
        test["v5_calibrated_probability"] = np.clip(v5_p, 1e-6, 1 - 1e-6)
        test["logistic_probability"] = logit_p
        test["gradient_boosting_probability"] = gbm_p
        test["opportunity_baseline_probability"] = opp_p
        test["prior_player_td_rate_probability"] = prior_p.reindex(test.index).to_numpy()
        test["recent6_td_frequency_probability"] = recent_p.reindex(test.index).to_numpy()
        position_rates = train.groupby("position").actual_td.mean()
        test["position_rate_probability"] = test.position.map(position_rates).fillna(float(train.actual_td.mean())).to_numpy()
        prediction_frames.append(test)
    result = pd.concat(prediction_frames, ignore_index=True)
    model_cols = {
        "V5 ranking score + train-only isotonic": "v5_calibrated_probability",
        "Logistic regression": "logistic_probability",
        "Gradient boosting": "gradient_boosting_probability",
        "Opportunity logistic baseline": "opportunity_baseline_probability",
        "Prior player TD rate (shrunk)": "prior_player_td_rate_probability",
        "Recent six TD frequency (smoothed)": "recent6_td_frequency_probability",
        "Training position/global rate": "position_rate_probability",
    }
    metric_rows, calibration = [], []
    for model, col in model_cols.items():
        block = result[["season", "week", "position", "game_id", "actual_td", col]].rename(columns={col: "probability"})
        slices = [("overall", "all", block)]
        for dim in ("season", "week", "position"):
            for key, group in block.groupby(dim, dropna=False):
                slices.append((dim, str(key), group))
        for dimension, value, group in slices:
            metrics = _probability_metrics(group.actual_td, group.probability)
            ranking_rows = []
            for _, game_week in group.groupby(["season", "week"]):
                ranking_rows.append(_topn_metrics(game_week.rename(columns={"probability": "probability"})))
            if ranking_rows:
                for key in ("top10_hits", "top10_hit_rate", "top20_hits", "top20_hit_rate",
                            "top30_hits", "top30_hit_rate"):
                    values = [item[key] for item in ranking_rows if item[key] is not None]
                    metrics[f"weekly_mean_{key}"] = float(np.mean(values)) if values else None
            row_metrics = dict(metrics)
            bins_for_metric = row_metrics.pop("calibration_bins", [])
            metric_rows.append({"model": model, "dimension": dimension, "value": value, **row_metrics})
            if dimension == "overall":
                calibration.extend([{"model": model, **item} for item in bins_for_metric])
    metrics_frame = pd.DataFrame(metric_rows)
    result.to_csv(out_dir / "v5_v6_player_predictions.csv", index=False)
    metrics_frame.to_json(out_dir / "v5_v6_metrics.json", orient="records", indent=2)
    pd.DataFrame(calibration).to_csv(out_dir / "calibration_bins.csv", index=False)
    summary = ["# NFL PM historical model evaluation", "",
               "All rows are retrospective backfills conditioned on verified offensive participation; metrics do not establish genuine pregame forecasting accuracy on the full player pool.",
               "Week cutoffs are enforced, but upstream data vintages are not archived, so later corrections to earlier-week source statistics cannot be ruled out.",
               "The V5 fixed estimate curve was excluded; V5 ranking score was calibrated using each fold's earlier seasons only.",
               f"Validation season: {validation_season}; test season: {test_season}.",
               f"Training data seasons available: {seasons}; numeric features: {features}.",
               "V5 weights are unchanged. Neither 2024 nor 2025 is an independent V5 test: weight development used evidence from both years. V5 metrics are descriptive only.",
               "", "## Overall metrics", "",
               "| Model | N | Scorers | Actual | Predicted | Bias | Brier | Log loss | AUC | ECE |",
               "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    overall = metrics_frame[metrics_frame.dimension.eq("overall")]
    for _, row in overall.iterrows():
        auc = "NA" if pd.isna(row.auc) else f"{row.auc:.4f}"
        summary.append(f"| {row.model} | {int(row.n)} | {int(row.positives)} | {row.actual_rate:.4f} | {row.mean_predicted:.4f} | {row.bias_pred_minus_actual:+.4f} | {row.brier:.5f} | {row.log_loss:.5f} | {auc} | {row.ece_10:.5f} |")
    summary += ["", "## Validation and test results by season", "",
                "| Season | Model | N | Scorers | Actual | Predicted | Bias | Brier | Log loss | AUC | ECE |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    season_metrics = metrics_frame[metrics_frame.dimension.eq("season")]
    for _, row in season_metrics.iterrows():
        auc = "NA" if pd.isna(row.auc) else f"{row.auc:.4f}"
        summary.append(f"| {row.value} | {row.model} | {int(row.n)} | {int(row.positives)} | {row.actual_rate:.4f} | {row.mean_predicted:.4f} | {row.bias_pred_minus_actual:+.4f} | {row.brier:.5f} | {row.log_loss:.5f} | {auc} | {row.ece_10:.5f} |")
    summary += ["", f"## {test_season} retrospective test by position", "",
                "| Position | Model | N | Scorers | Actual | Predicted | Bias | Brier | Log loss | AUC |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for model, col in model_cols.items():
        for position in sorted(result.position.unique()):
            group = result[(result.season == test_season) & (result.position == position)]
            metrics = _probability_metrics(group.actual_td, group[col])
            auc = "NA" if metrics["auc"] is None else f"{metrics['auc']:.4f}"
            summary.append(f"| {position} | {model} | {metrics['n']} | {metrics['positives']} | {metrics['actual_rate']:.4f} | {metrics['mean_predicted']:.4f} | {metrics['bias_pred_minus_actual']:+.4f} | {metrics['brier']:.5f} | {metrics['log_loss']:.5f} | {auc} |")
    summary += ["", f"## {test_season} weekly ranking performance", "",
                "Mean actual touchdown scorers in each weekly top group; the test rows are participation-conditional.", "",
                "| Model | Top 10 mean hits | Top 20 mean hits | Top 30 mean hits |",
                "|---|---:|---:|---:|"]
    test_rows = result[result.season == test_season]
    for model, col in model_cols.items():
        weekly = [_topn_metrics(group.rename(columns={col: "probability"}))
                  for _, group in test_rows.groupby(["season", "week"])]
        means = [float(np.mean([week[f"top{n}_hits"] for week in weekly])) for n in (10, 20, 30)]
        summary.append(f"| {model} | {means[0]:.2f} | {means[1]:.2f} | {means[2]:.2f} |")
    summary += ["", "Predicted minus actual above zero means overestimation; below zero means underestimation.",
                "Top-N ranking metrics and season/week/position slices are in the machine-readable metrics file.",
                "V5 raw td_score is a ranking score, not a probability. Legacy td_estimate is retained for reference only and is not evaluated."]
    (out_dir / "evaluation_report.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return result, metrics_frame


def main():
    parser = argparse.ArgumentParser(description="Chronological V5/V6 and baseline evaluation.")
    parser.add_argument("--data", default="evaluation/historical_evaluation_data.csv")
    parser.add_argument("--validation-season", type=int, required=True)
    parser.add_argument("--test-season", type=int, required=True)
    parser.add_argument("--out-dir", default="evaluation")
    args = parser.parse_args()
    if args.validation_season >= args.test_season:
        parser.error("--validation-season must precede --test-season.")
    frame = pd.read_csv(args.data)
    _, metrics = evaluate_chronologically(frame, args.validation_season, args.test_season, args.out_dir)
    print(metrics[metrics.dimension.eq("overall")][["model", "n", "positives", "actual_rate", "mean_predicted",
                                                    "bias_pred_minus_actual", "brier", "log_loss", "auc", "ece_10"]].to_string(index=False))
    print("Wrote evaluation_report.md, v5_v6_metrics.json, calibration_bins.csv, and player-level predictions.")


if __name__ == "__main__":
    main()
