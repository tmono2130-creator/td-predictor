"""
RETROSPECTIVE V5 BACKTEST — rebuilds historical feature rows and matches them
against completed rushing/receiving TD outcomes. This is not an archived
as-published pregame forecast record. Player features are cut off before the
target week; current source vintages, historical roster snapshots, and exact
injury-feed versions are not preserved by the repository.

Incomplete weeks are skipped. Outcomes are joined on player_id + game_id,
and each result is labeled retrospective_backfill. Use the output to inspect
the historical reconstruction, not as proof of production pregame accuracy.

USAGE:
    python backtest.py --season 2025 --start-week 1 --end-week 18
"""

import argparse
import sys

import numpy as np
import pandas as pd

from td_predictor_v5 import get_predictions, load_player_stats, clean_num, load_schedule
from evaluation_utils import require_complete_regular_week, validate_predictions_against_schedule

COMPONENTS = [
    "opportunity_score", "red_zone_score", "efficiency_score",
    "matchup_score", "team_environment_score", "role_score",
]


def load_actual_results(season, week):
    """Completed-game rushing/receiving TD labels by player and game."""
    stats = load_player_stats([season])
    stats["week"] = clean_num(stats["week"])
    wk = stats[stats["week"] == week].copy()
    if "season_type" in wk.columns:
        wk = wk[wk["season_type"].astype(str).str.upper() == "REG"]
    if wk.empty or not {"player_id", "game_id"}.issubset(wk.columns):
        raise ValueError(f"No safely keyed player-game outcomes available for {season} week {week}.")
    for col in ["receiving_tds", "rushing_tds"]:
        if col not in wk.columns:
            wk[col] = 0
        wk[col] = clean_num(wk[col])
    wk["actual_td"] = ((wk["receiving_tds"] + wk["rushing_tds"]) > 0).astype(int)
    wk["player_id"] = wk["player_id"].astype(str)
    wk["game_id"] = wk["game_id"].astype(str)
    return wk.groupby(["player_id", "game_id"], as_index=False)["actual_td"].max()


def run_backtest(season, start_week, end_week):
    all_weeks = []
    schedule = load_schedule(season)

    for week in range(start_week, end_week + 1):
        print(f"\n--- Week {week} ---")
        try:
            games = require_complete_regular_week(schedule, season, week)
            predicted, _ = get_predictions(season, week)
            validate_predictions_against_schedule(predicted, games)
            actual = load_actual_results(season, week)
            merged = predicted.merge(actual, on=["player_id", "game_id"], how="left", validate="one_to_one")
        except Exception as e:
            print(f"  Skipping week {week}: {e}")
            continue

        merged["actual_td"] = merged["actual_td"].fillna(0).astype(int)
        merged["week"] = week
        merged["season"] = season
        merged["prediction_origin"] = "retrospective_backfill"
        all_weeks.append(merged)
        print(f"  {len(merged)} player/game rows, {merged['actual_td'].sum()} actually scored a TD")

    if not all_weeks:
        raise RuntimeError("No complete weeks produced results -- check season/week range and data feeds.")

    result = pd.concat(all_weeks, ignore_index=True)
    duplicate = result.duplicated(["season", "week", "player_id", "game_id"], keep=False)
    if duplicate.any():
        raise RuntimeError("Backtest produced duplicate player/game rows.")
    return result


def probability_metrics(df):
    """Descriptive probability metrics for retrospective reconstructions."""
    y = pd.to_numeric(df["actual_td"], errors="raise").to_numpy(dtype=float)
    p = (pd.to_numeric(df["td_estimate"], errors="raise").to_numpy(dtype=float) / 100.0)
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return {
        "actual_rate_pct": float(y.mean() * 100),
        "mean_estimate_pct": float(p.mean() * 100),
        "mean_bias_pp": float((p.mean() - y.mean()) * 100),
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(np.mean(-(y * np.log(p) + (1 - y) * np.log(1 - p)))),
    }


def calibration_table(df, bins=10):
    """Buckets players by predicted td_estimate and checks real TD rate per bucket."""
    df = df.copy()
    df["bucket"] = pd.qcut(df["td_score"], q=bins, duplicates="drop")
    table = df.groupby("bucket", observed=True).agg(
        n=("actual_td", "size"),
        avg_predicted_pct=("td_estimate", "mean"),
        actual_td_rate_pct=("actual_td", lambda x: x.mean() * 100),
    ).reset_index()
    return table


def top_n_hit_rate(df, n_values=(10, 20, 30)):
    results = {}
    for n in n_values:
        per_week = df.groupby("week", group_keys=False).apply(
            lambda g: g.nlargest(n, "td_score")["actual_td"].sum()
        )
        total_possible = df.groupby("week").size().clip(upper=n).sum()
        results[n] = {
            "avg_scorers_in_topN_per_week": per_week.mean(),
            "total_topN_hits": int(per_week.sum()),
        }
    return results


def component_correlations(df):
    corrs = {}
    for comp in COMPONENTS:
        if comp in df.columns:
            corrs[comp] = df[comp].corr(df["actual_td"])
    return pd.Series(corrs).sort_values(ascending=False)


def suggest_weights_via_logistic_regression(df):
    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        print("\n(scikit-learn not installed -- skipping data-driven weight suggestion. "
              "Run: python -m pip install scikit-learn  to enable this.)")
        return None

    X = df[COMPONENTS].fillna(50).values
    y = df["actual_td"].values

    model = LogisticRegression(max_iter=1000)
    model.fit(X, y)

    coefs = pd.Series(model.coef_[0], index=COMPONENTS)
    positive_only = coefs.clip(lower=0)
    if positive_only.sum() == 0:
        print("\nLogistic regression found no positive-signal components -- "
              "skipping weight suggestion (this would need more data/weeks to be reliable).")
        return None

    suggested = (positive_only / positive_only.sum()).round(3)
    return suggested


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--start-week", type=int, default=2)
    parser.add_argument("--end-week", type=int, default=18)
    args = parser.parse_args()

    results = run_backtest(args.season, args.start_week, args.end_week)
    results.to_csv(f"backtest_{args.season}_wk{args.start_week}-{args.end_week}.csv", index=False)

    print("\nRETROSPECTIVE RECONSTRUCTION — not a stored pregame prediction record")
    print(pd.Series(probability_metrics(results)).to_string())
    print("\n" + "=" * 70)
    print("CALIBRATION (does 'Est. TD%' mean what it says?)")
    print("=" * 70)
    print(calibration_table(results).to_string(index=False))
    print("\nRead this as: if avg_predicted_pct and actual_td_rate_pct are close "
          "for each row, the model is well-calibrated. If predicted is "
          "consistently higher than actual, the model is overconfident "
          "(and vice versa).")

    print("\n" + "=" * 70)
    print("TOP-N HIT RATE (does ranking players highly actually mean they score?)")
    print("=" * 70)
    for n, stats in top_n_hit_rate(results).items():
        print(f"  Top {n}: avg {stats['avg_scorers_in_topN_per_week']:.2f} actual scorers/week "
              f"({stats['total_topN_hits']} total hits)")

    print("\n" + "=" * 70)
    print("COMPONENT CORRELATION WITH ACTUAL SCORING")
    print("=" * 70)
    print("(Higher = that component actually predicts real TDs. Near-zero or negative")
    print(" = that component isn't pulling its weight in the current formula.)\n")
    print(component_correlations(results).to_string())

    print("\n" + "=" * 70)
    print("SUGGESTED WEIGHTS (data-driven, from logistic regression)")
    print("=" * 70)
    suggested = suggest_weights_via_logistic_regression(results)
    if suggested is not None:
        print(suggested.to_string())
        print("\nCompare this to your current WEIGHTS dict in td_predictor_v5.py. "
              "This is a suggestion based on this season's data only -- worth "
              "sanity-checking against another season before actually changing "
              "WEIGHTS, since one season is a fairly small sample.")

    print(f"\nFull per-player, per-week results saved to: "
          f"backtest_{args.season}_wk{args.start_week}-{args.end_week}.csv")


if __name__ == "__main__":
    main()