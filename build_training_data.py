"""Build participation-verified historical rows and retrospective V5 scores.

The files created here are not archived pregame forecasts. They reconstruct
weekly V5 rankings after completed games, use week-specific roster snapshots,
exclude same-week outcomes and injury statuses with unknown publication time,
and preserve source-version limitations in every row.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import nflreadpy
import pandas as pd

import td_predictor_v5 as v5
from evaluation_utils import require_complete_regular_week, validate_predictions_against_schedule
from historical_data import build_actual_player_games


def reconstruct(seasons, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_hash = hashlib.sha256(Path(v5.__file__).read_bytes()).hexdigest()
    player_stats = nflreadpy.load_player_stats(seasons=seasons, summary_level="week").to_pandas()
    snap_counts = nflreadpy.load_snap_counts(seasons=seasons).to_pandas()
    schedule = nflreadpy.load_schedules(seasons=seasons).to_pandas()
    players = nflreadpy.load_players().to_pandas()
    if not {"pfr_id", "gsis_id"}.issubset(players.columns):
        raise RuntimeError("nflverse player crosswalk lacks pfr_id/gsis_id identifiers.")
    crosswalk = players[["pfr_id", "gsis_id"]].dropna().drop_duplicates()

    original_stats = v5.load_player_stats
    original_redzone = v5.load_redzone_opportunity
    original_schedule = v5.load_schedule
    @lru_cache(maxsize=None)
    def stats_cached(season):
        return original_stats([season])
    def stats_loader(season_list):
        pieces = [stats_cached(int(season)).copy(deep=True) for season in season_list]
        return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
    @lru_cache(maxsize=None)
    def redzone_cached(season_key):
        return original_redzone(list(season_key))
    def redzone_loader(season_list):
        return redzone_cached(tuple(sorted(int(s) for s in season_list))).copy(deep=True)
    @lru_cache(maxsize=None)
    def schedule_cached(season):
        return original_schedule(season)
    v5.load_player_stats = stats_loader
    v5.load_redzone_opportunity = redzone_loader
    v5.load_schedule = lambda season: schedule_cached(int(season)).copy(deep=True)

    all_outcomes, all_predictions = [], []
    try:
        schedule["season"] = pd.to_numeric(schedule.season, errors="coerce")
        schedule["week"] = pd.to_numeric(schedule.week, errors="coerce")
        for season in seasons:
            season_schedule = schedule[schedule.season == season]
            regular = season_schedule[season_schedule.game_type.astype(str).str.upper() == "REG"]
            for week in sorted(regular.week.dropna().astype(int).unique()):
                try:
                    games = require_complete_regular_week(season_schedule, season, week)
                except ValueError:
                    continue
                print(f"Reconstructing {season} week {week} ...", flush=True)
                outcomes = build_actual_player_games(
                    player_stats, snap_counts, crosswalk, schedule, season, week
                )
                all_outcomes.append(outcomes)
                generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
                try:
                    predicted, _ = v5.get_predictions(
                        season, week, historical_reconstruction=True
                    )
                    validate_predictions_against_schedule(predicted, games)
                except Exception as exc:
                    raise RuntimeError(f"V5 reconstruction failed for {season} week {week}: {exc}") from exc
                predicted = predicted.copy()
                predicted["player_id"] = predicted.player_id.astype(str)
                predicted["game_id"] = predicted.game_id.astype(str)
                eligible = outcomes[outcomes.player_id_namespace.eq("gsis") & outcomes.actual_td.notna()].copy()
                joined = predicted.merge(
                    eligible, on=["player_id", "game_id"], how="inner",
                    validate="one_to_one", suffixes=("", "_outcome"),
                )
                if joined.empty:
                    raise RuntimeError(f"No participant predictions matched for {season} week {week}.")
                joined["prediction_origin"] = "retrospective_backfill"
                joined["snapshot_classification"] = "retrospective_backfill"
                joined["prediction_generated_at"] = generated
                joined["feature_cutoff_season"] = season if week > 1 else season - 1
                joined["feature_cutoff_week"] = week - 1 if week > 1 else 18
                joined["feature_cutoff_rule"] = "target_week_minus_one; prior season through week 18 for week 1"
                joined["injury_feature_used"] = False
                joined["injury_source_vintage"] = "unavailable; excluded"
                joined["prediction_available"] = True
                joined["raw_model_score"] = pd.to_numeric(joined.td_score, errors="coerce")
                joined["model_score_semantics"] = "V5 ranking score; not a probability"
                joined["raw_td_estimate_pct"] = pd.to_numeric(joined.td_estimate, errors="coerce")
                joined["raw_td_estimate_semantics"] = "legacy V5 curve; excluded from evaluation calibration"
                joined["nflreadpy_version"] = getattr(nflreadpy, "__version__", "unknown")
                joined["upstream_source_revision"] = "not archived by source"
                joined["model_version"] = f"v5-composite-sha256:{model_hash}"
                all_predictions.append(joined)
                print(f"  {len(eligible):,} eligible participants; {len(joined):,} matched V5 rows; "
                      f"{int(joined.actual_td.sum()):,} scorers", flush=True)
    finally:
        v5.load_player_stats = original_stats
        v5.load_redzone_opportunity = original_redzone
        v5.load_schedule = original_schedule

    if not all_outcomes or not all_predictions:
        raise RuntimeError("No completed participant weeks were reconstructed.")
    outcomes = pd.concat(all_outcomes, ignore_index=True)
    predictions = pd.concat(all_predictions, ignore_index=True)
    key = ["season", "week", "player_id_namespace", "player_id", "game_id"]
    if outcomes.duplicated(key).any():
        raise RuntimeError("Duplicate participant outcome player/game rows.")
    if predictions.duplicated(["season", "week", "player_id", "game_id"]).any():
        raise RuntimeError("Duplicate prediction player/game rows.")
    outcomes.to_csv(out_dir / "historical_player_games.csv", index=False)
    predictions.to_csv(out_dir / "historical_evaluation_data.csv", index=False)
    gsis_outcomes = outcomes[outcomes.player_id_namespace.eq("gsis") & outcomes.actual_td.notna()]
    outcome_by_season = {}
    prediction_by_season = {}
    for season in sorted(outcomes.season.unique().tolist()):
        observed = gsis_outcomes[gsis_outcomes.season == season]
        scored = predictions[predictions.season == season]
        outcome_by_season[str(int(season))] = {
            "eligible_gsis_player_games": int(len(observed)),
            "eligible_touchdown_player_games": int(observed.actual_td.sum()),
            "eligible_player_games_missing_prediction": int(len(observed) - len(scored)),
            "prediction_match_coverage": float(len(scored) / len(observed)) if len(observed) else None,
            "completed_weeks": int(observed.week.nunique()),
        }
        prediction_by_season[str(int(season))] = {
            "rows": int(len(scored)), "scorers": int(scored.actual_td.sum()),
            "actual_rate": float(scored.actual_td.mean()),
        }
    summary = {
        "dataset_classification": "retrospective_backfill",
        "seasons": sorted(int(s) for s in outcomes.season.unique()),
        "eligible_participation_rows_including_unmatched_pfr_ids": int(len(outcomes)),
        "unknown_outcome_rows_excluded_from_evaluation": int(outcomes.actual_td.isna().sum()),
        "verified_touchdown_player_games": int(outcomes.actual_td.sum()),
        "matched_evaluation_rows": int(len(predictions)),
        "matched_evaluation_scorers": int(predictions.actual_td.sum()),
        "position_scope": ["QB", "RB", "WR", "TE"],
        "touchdown_definition": "rushing or receiving TD; passing TD excluded",
        "participation_rule": "positive offensive snap or positive rushing/receiving TD evidence",
        "feature_cutoff": "prior target week; prior completed season for week 1",
        "injury_data": "excluded from historical features because publication timestamps are unavailable",
        "source": {"nflreadpy": getattr(nflreadpy, "__version__", "unknown"),
                   "upstream_revision": "not provided by the public feed"},
        "by_season": outcome_by_season,
        "matched_predictions_by_season": prediction_by_season,
        "limitations": ["retrospective source vintages and later corrections are not archived", "V5 weights have 2024-25 development overlap",
                        "prediction coverage is conditional on stable GSIS-ID matches", "evaluation is participation-conditional"],
    }
    (out_dir / "historical_data_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved {len(outcomes):,} verified participants; {len(predictions):,} matched predictions.")
    print(f"Scorers: {int(outcomes.actual_td.sum()):,}; seasons: "
          f"{sorted(outcomes.season.unique().tolist())}")
    print("These are retrospective reconstructions, not authenticated pregame snapshots.")
    return outcomes, predictions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    parser.add_argument("--out-dir", default="evaluation")
    args = parser.parse_args()
    reconstruct(args.seasons, args.out_dir)


if __name__ == "__main__":
    main()
