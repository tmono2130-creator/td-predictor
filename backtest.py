"""
BACKTEST — validates the TD predictor against real completed games.

For every week of a season you specify, this:
  1. Runs the model exactly as it would have at the time (only using data
     that existed before that week -- no lookahead/hindsight bias).
  2. Pulls the ACTUAL results for that week (who really scored).
  3. Compares predicted rankings/scores against real outcomes.

Outputs:
  - A calibration table: when the model says "~40%", did players in that
    score range actually score ~40% of the time historically?
  - Top-N hit rate: of the model's top 10/20/30 each week, how many
    actually scored?
  - Component correlation: which of the 6 scored components (opportunity,
    red_zone, efficiency, matchup, team_environment, role) actually
    correlates with real scoring -- vs. which ones are dead weight in
    the current WEIGHTS dict.
  - If scikit-learn is installed, a logistic regression fit on the
    components suggests data-driven weights to compare against the
    current hand-set ones (a SUGGESTION to consider, not something this
    script applies automatically -- changing WEIGHTS is still your call).

USAGE:
    python backtest.py --season 2025 --start-week 2 --end-week 18

NOTE: this reruns the full data pipeline once per week, so a full-season
backtest can take several minutes -- it's intentionally not optimized for
speed on a first pass. If you run this often, it's worth caching the
season-level data loads instead of reloading them every week.
"""

import argparse
import sys

import numpy as np
import pandas as pd

from td_predictor_v5 import get_predictions, load_player_stats, clean_num

COMPONENTS = [
    "opportunity_score", "red_zone_score", "efficiency_score",
    "matchup_score", "team_environment_score", "role_score",
]


def load_actual_results(season, week):
    """Who actually scored a TD in this specific week, by player_id."""
    stats = load_player_stats([season])
    stats["week"] = clean_num(stats["week"])
    wk = stats[stats["week"] == week].copy()

    for col in ["receiving_tds", "rushing_tds"]:
        if col not in wk.columns:
            wk[col] = 0
        wk[col] = clean_num(wk[col])

    wk["actual_td"] = ((wk["receiving_tds"] + wk["rushing_tds"]) > 0).astype(int)
    wk["player_id"] = wk["player_id"].astype(str)
    return wk[["player_id", "actual_td"]].drop_duplicates("player_id")


def run_backtest(season, start_week, end_week):
    all_weeks = []

    for week in range(start_week, end_week + 1):
        print(f"\n--- Week {week} ---")
        try:
            predicted, matchups = get_predictions(season, week)
        except Exception as e:
            print(f"  Skipping week {week}: {e}")
            continue

        actual = load_actual_results(season, week)
        merged = predicted.merge(actual, on="player_id", how="left")
        merged["actual_td"] = merged["actual_td"].fillna(0).astype(int)
        merged["week"] = week

        all_weeks.append(merged)
        print(f"  {len(merged)} players scored, {merged['actual_td'].sum()} actually scored a TD")

    if not all_weeks:
        raise RuntimeError("No weeks produced results -- check season/week range.")

    return pd.concat(all_weeks, ignore_index=True)


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