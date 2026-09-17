"""
BUILD TRAINING DATA — run this once, then iterate on models freely.

Runs the full feature pipeline for every week of the seasons you
specify and joins the real outcome (did this player score a TD that
week). Produces one flat CSV that model_v6.py trains on.

Split this way on purpose: generating the data is slow (the pipeline
reloads several seasons of stats per week), but model experimentation
should be fast. Generate once, then try as many models as you want
against the same CSV.

USAGE:
    python build_training_data.py --seasons 2023 2024 2025

Expect this to take a while -- roughly 17 weeks x N seasons full
pipeline runs. Leave it going.
"""

import argparse

import pandas as pd

from td_predictor_v5 import get_predictions, load_player_stats, clean_num

# Everything the model is allowed to look at. Deliberately includes the
# Layer 3 features (is_home, days_rest, recent scoring environment) so
# the fitted model decides from held-out data whether they carry signal
# -- rather than anyone assuming they do or don't.
FEATURE_COLUMNS = [
    # Layer 1/2 -- usage and scoring ability (the components that have
    # repeatedly validated across seasons)
    "opportunity_score", "red_zone_score", "efficiency_score",
    "opportunities_pg", "redzone_opportunity_pg", "td_rate",
    "targets_pg", "carries_pg", "receptions_pg", "target_share",
    "receiving_yards_pg", "rushing_yards_pg",
    # Layer 3 -- game environment (candidate features, unproven)
    "matchup_score", "team_environment_score",
    "is_home", "days_rest",
    "recent_ppg", "recent_points_allowed",
    "opp_recent_ppg", "opp_recent_points_allowed",
    # Layer 4 -- role (currently collinear with opportunity; the fitted
    # model with regularization handles that better than hand weights did)
    "role_score",
    # context
    "games",
]


def load_actual_results(season, week):
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    parser.add_argument("--start-week", type=int, default=2)
    parser.add_argument("--end-week", type=int, default=18)
    parser.add_argument("--out", type=str, default="training_data.csv")
    args = parser.parse_args()

    all_rows = []

    for season in args.seasons:
        for week in range(args.start_week, args.end_week + 1):
            print(f"\n=== {season} week {week} ===")
            try:
                predicted, _ = get_predictions(season, week)
            except Exception as e:
                print(f"  skipped: {e}")
                continue

            actual = load_actual_results(season, week)
            merged = predicted.merge(actual, on="player_id", how="left")
            merged["actual_td"] = merged["actual_td"].fillna(0).astype(int)
            merged["season"] = season
            merged["week"] = week

            keep = ["player_id", "player", "team", "position", "opponent",
                     "season", "week", "actual_td", "td_score", "td_estimate"]
            keep += [c for c in FEATURE_COLUMNS if c in merged.columns]
            all_rows.append(merged[[c for c in keep if c in merged.columns]])

            print(f"  {len(merged)} players, {merged['actual_td'].sum()} scored")

    if not all_rows:
        raise RuntimeError("No data generated — check your season/week range.")

    df = pd.concat(all_rows, ignore_index=True)
    df.to_csv(args.out, index=False)

    print(f"\nSaved {len(df):,} rows to {args.out}")
    print(f"Positive rate: {df['actual_td'].mean() * 100:.2f}% "
          f"({df['actual_td'].sum():,} players scored)")
    print(f"Seasons: {sorted(df['season'].unique().tolist())}")
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        print(f"NOTE: these features weren't available and were skipped: {missing}")


if __name__ == "__main__":
    main()