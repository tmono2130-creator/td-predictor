"""Shared integrity checks for historical player-game evaluation data."""


def regular_week_games(schedule, season, week):
    """Return the regular-season schedule rows for one season and week."""
    if schedule is None or schedule.empty:
        return schedule
    games = schedule.copy()
    if "season" in games.columns:
        games = games[games["season"] == season]
    if "week" not in games.columns:
        return games.iloc[0:0]
    games = games[games["week"] == week]

    type_col = "game_type" if "game_type" in games.columns else (
        "season_type" if "season_type" in games.columns else None
    )
    if type_col:
        games = games[games[type_col].astype(str).str.strip().str.upper().isin(
            {"REG", "REGULAR", "REGULAR SEASON"}
        )]
    return games.copy()


def require_complete_regular_week(schedule, season, week):
    """Raise unless every scheduled regular-season game has a final score."""
    games = regular_week_games(schedule, season, week)
    if games is None or games.empty:
        raise ValueError(f"No regular-season games found for {season} week {week}.")
    required = {"home_team", "away_team", "home_score", "away_score"}
    missing = required.difference(games.columns)
    if missing:
        raise ValueError(
            f"Cannot verify {season} week {week} completion; schedule is missing "
            f"{', '.join(sorted(missing))}."
        )
    incomplete = games[games[["home_score", "away_score"]].isna().any(axis=1)]
    if not incomplete.empty:
        raise ValueError(
            f"{season} week {week} is incomplete: {len(incomplete)} of {len(games)} "
            "scheduled game(s) do not have final scores yet."
        )
    return games


def validate_player_game_keys(rows):
    """Check that prediction rows have valid, unique player/game identities."""
    required = {"player_id", "game_id"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"Prediction rows are missing {', '.join(sorted(missing))}.")
    invalid = rows["player_id"].isna() | rows["game_id"].isna()
    if invalid.any():
        raise ValueError("Prediction rows contain a missing player ID or game ID.")
    duplicates = rows.duplicated(["player_id", "game_id"], keep=False)
    if duplicates.any():
        sample = rows.loc[duplicates, ["player_id", "game_id"]].iloc[0].to_dict()
        raise ValueError(
            "Duplicate player/game prediction: "
            f"player_id={sample['player_id']!r}, game_id={sample['game_id']!r}."
        )
    return rows


def validate_predictions_against_schedule(rows, games):
    """Verify every player row references its scheduled team/opponent game."""
    validate_player_game_keys(rows)
    needed = {"game_id", "home_team", "away_team"}
    missing = needed.difference(games.columns)
    if missing:
        raise ValueError(f"Schedule is missing {', '.join(sorted(missing))}.")
    by_id = {}
    for game in games.itertuples(index=False):
        game_id = str(getattr(game, "game_id", "")).strip()
        if not game_id:
            raise ValueError("Scheduled game is missing game_id.")
        by_id[game_id] = {str(game.home_team), str(game.away_team)}
    for row in rows.itertuples(index=False):
        game_id = str(row.game_id)
        if game_id not in by_id:
            raise ValueError(f"Prediction game_id {game_id!r} is not scheduled this week.")
        if {str(row.team), str(row.opponent)} != by_id[game_id]:
            raise ValueError(
                f"Player {row.player_id!r} team/opponent do not match schedule game {game_id!r}."
            )
    return rows


def validate_training_data_frame(frame):
    """Reject legacy datasets lacking completed-week and provenance controls."""
    required = {
        "player_id", "game_id", "season", "week", "actual_td", "td_score",
        "td_estimate", "week_complete", "prediction_origin", "prediction_generated_at",
        "feature_cutoff_season", "feature_cutoff_week",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(
            "Training data lacks reliability metadata ("
            f"{', '.join(sorted(missing))}). Regenerate it with build_training_data.py."
        )
    if not frame["week_complete"].astype(str).str.casefold().isin({"true", "1"}).all():
        raise ValueError("Training data includes a week that was not verified complete.")
    if not frame["prediction_origin"].eq("retrospective_backfill").all():
        raise ValueError("Training data contains rows without retrospective-backfill provenance.")
    if frame[["prediction_generated_at", "feature_cutoff_season", "feature_cutoff_week"]].isna().any().any():
        raise ValueError("Training data is missing generation time or feature-cutoff metadata.")
    if frame.duplicated(["player_id", "game_id"], keep=False).any():
        raise ValueError("Training data contains duplicate player/game rows.")
    cutoff_season = frame["season"].where(frame["week"] > 1, frame["season"] - 1)
    cutoff_week = frame["week"].where(frame["week"] > 1, 18)
    if not frame["feature_cutoff_season"].eq(cutoff_season).all() or not frame["feature_cutoff_week"].eq(cutoff_week - (frame["week"] > 1).astype(int)).all():
        raise ValueError("Training features do not match the documented pre-week cutoff.")
    if not frame["actual_td"].isin([0, 1, False, True]).all():
        raise ValueError("Training data actual_td labels must be binary.")
    return frame
