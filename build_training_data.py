"""
BUILD VALIDATED HISTORICAL TRAINING DATA.

Reconstructs each requested week's V5 feature rows, requires the whole
regular-season schedule to be final, and joins actual outcomes by player_id
and game_id. Every row is labeled retrospective_backfill with a generation
time and documented pre-week feature cutoff. This is not an archived pregame
prediction record; source vintages are not preserved.

USAGE:
    python build_training_data.py --seasons 2023 2024 2025 --out training_data_validated.csv
"""

import argparse
from datetime import datetime, timezone

import pandas as pd

from td_predictor_v5 import get_predictions, load_player_stats, clean_num, load_schedule
from evaluation_utils import require_complete_regular_week, validate_predictions_against_schedule

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
    """Actual rushing/receiving TD labels keyed to player and game."""
    stats = load_player_stats([season])
    stats["week"] = clean_num(stats["week"])
    wk = stats[stats["week"] == week].copy()
    if "season_type" in wk.columns:
        wk = wk[wk["season_type"].astype(str).str.upper() == "REG"]
    if wk.empty:
        raise ValueError(f"No weekly player statistics available for {season} week {week}.")
    if not {"player_id", "game_id"}.issubset(wk.columns):
        raise ValueError("Player statistics lack player_id or game_id; labels cannot be joined safely.")
    for col in ["receiving_tds", "rushing_tds"]:
        if col not in wk.columns:
            wk[col] = 0
        wk[col] = clean_num(wk[col])
    wk["actual_td"] = ((wk["receiving_tds"] + wk["rushing_tds"]) > 0).astype(int)
    wk["player_id"] = wk["player_id"].astype(str)
    wk["game_id"] = wk["game_id"].astype(str)
    return wk.groupby(["player_id", "game_id"], as_index=False)["actual_td"].max()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    parser.add_argument("--start-week", type=int, default=1)
    parser.add_argument("--end-week", type=int, default=18)
    parser.add_argument("--out", type=str, default="training_data.csv")
    args = parser.parse_args()
    if not (1 <= args.start_week <= args.end_week <= 18):
        raise SystemExit("Weeks must be an increasing range from 1 through 18.")

    all_rows = []
    for season in args.seasons:
        schedule = load_schedule(season)
        for week in range(args.start_week, args.end_week + 1):
            print(f"\n=== {season} week {week} ===")
            try:
                games = require_complete_regular_week(schedule, season, week)
            except ValueError as e:
                print(f"  skipped before label generation: {e}")
                continue
            try:
                predicted, _ = get_predictions(season, week)
                validate_predictions_against_schedule(predicted, games)
                actual = load_actual_results(season, week)
                merged = predicted.merge(actual, on=["player_id", "game_id"], how="left", validate="one_to_one")
            except Exception as e:
                print(f"  skipped: {e}")
                continue

            merged["actual_td"] = merged["actual_td"].fillna(0).astype(int)
            merged["season"] = season
            merged["week"] = week
            merged["week_complete"] = True
            merged["prediction_origin"] = "retrospective_backfill"
            merged["prediction_generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if week > 1:
                merged["feature_cutoff_season"] = season
                merged["feature_cutoff_week"] = week - 1
            else:
                merged["feature_cutoff_season"] = season - 1
                merged["feature_cutoff_week"] = 18

            keep = ["player_id", "game_id", "player", "team", "position", "opponent",
                    "season", "week", "actual_td", "td_score", "td_estimate",
                    "week_complete", "prediction_origin", "prediction_generated_at",
                    "feature_cutoff_season", "feature_cutoff_week"]
            keep += [c for c in FEATURE_COLUMNS if c in merged.columns]
            all_rows.append(merged[[c for c in keep if c in merged.columns]])
            print(f"  {len(merged)} player/game rows, {merged['actual_td'].sum()} scored a TD")

    if not all_rows:
        raise RuntimeError("No complete, labeled weeks generated — check the season/week range and data feeds.")

    df = pd.concat(all_rows, ignore_index=True)
    duplicate = df.duplicated(["player_id", "game_id", "season", "week"], keep=False)
    if duplicate.any():
        raise RuntimeError("Generated training data contains duplicate player/game rows.")
    df.to_csv(args.out, index=False)
    print(f"\nSaved {len(df):,} validated retrospective rows to {args.out}")
    print(f"Positive rate: {df['actual_td'].mean() * 100:.2f}% "
          f"({df['actual_td'].sum():,} players scored)")
    print(f"Seasons: {sorted(df['season'].unique().tolist())}")
    print("These are retrospective reconstructions, not evidence of pregame publication.")
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        print(f"NOTE: these features weren't available and were skipped: {missing}")


if __name__ == "__main__":
    main()