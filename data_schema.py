"""Validation helpers for the Python-to-JSON website data contract.

Schema version 1 uses a board object with ``meta`` and ``rows``. ``td_score``
keeps V5's 0..100 ranking-score scale; ``td_estimate`` remains the calibrated
TD probability in percent. In fitted-model mode, V5 itself sets both to
probability * 100. Validation does not reinterpret or transform either field.
"""

import math

SCHEMA_VERSION = 1
INJURY_STATUSES = frozenset({"Active", "Questionable", "Doubtful", "Out", "IR", "Unknown"})
GAME_STATUSES = frozenset({"Upcoming", "In Progress", "Final", "Unknown"})
PREDICTION_TIMINGS = frozenset({"pregame_snapshot", "historical_backfill", "unknown"})
SUPPORTED_WEEKS = tuple(range(1, 19))
TEAM_CODES = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS",
})
BOARD_FIELDS = (
    "player_id", "game_id", "player", "team", "position", "opponent", "td_score",
    "td_estimate", "game_status", "injury_status", "prediction_timing",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _finite_number(value, field, row_index):
    _require(isinstance(value, (int, float)) and not isinstance(value, bool),
             f"rows[{row_index}].{field} must be a number")
    _require(math.isfinite(value), f"rows[{row_index}].{field} must be finite")
    _require(0 <= value <= 100, f"rows[{row_index}].{field} must be between 0 and 100")


def validate_board(payload, season, week):
    """Raise ValueError unless payload matches this export's requested week."""
    _require(isinstance(payload, dict), "board must be a JSON object")
    meta = payload.get("meta")
    _require(isinstance(meta, dict), "board.meta must be an object")
    _require(meta.get("season") == season, f"board season mismatch: expected {season}")
    _require(meta.get("week") == week, f"board week mismatch: expected {week}")
    _require(week in SUPPORTED_WEEKS, f"week {week} is outside supported regular season weeks 1-18")
    _require(isinstance(meta.get("generated_at"), str) and meta["generated_at"],
             "board.meta.generated_at is required")
    _require(meta.get("model") in ("fitted", "composite"),
             "board.meta.model must be 'fitted' or 'composite'")
    _require(isinstance(meta.get("final_games"), list), "board.meta.final_games must be an array")
    _require(isinstance(meta.get("games"), list) and len(meta["games"]) > 0,
             "board.meta.games must list the selected week's scheduled games")
    _require(isinstance(meta.get("injury_report"), dict), "board.meta.injury_report must be an object")
    _require(meta["injury_report"].get("unknown_is_not_active") is True,
             "board.meta.injury_report must document Unknown as distinct from Active")
    game_by_id = {}
    team_to_game = {}
    for i, game in enumerate(meta["games"]):
        _require(isinstance(game, dict), f"board.meta.games[{i}] must be an object")
        for field in ("game_id", "home_team", "away_team", "kickoff_utc", "prediction_timing"):
            _require(isinstance(game.get(field), str) and game[field].strip(),
                     f"board.meta.games[{i}].{field} must be a non-empty string")
        _require(game["game_id"] not in game_by_id, f"duplicate scheduled game_id {game['game_id']!r}")
        _require(game["home_team"] in TEAM_CODES and game["away_team"] in TEAM_CODES,
                 f"board.meta.games[{i}] has an invalid NFL team code")
        _require(game["home_team"] != game["away_team"], f"board.meta.games[{i}] has the same home and away team")
        _require(game["prediction_timing"] in PREDICTION_TIMINGS,
                 f"board.meta.games[{i}].prediction_timing is invalid")
        game_by_id[game["game_id"]] = game
        for team in (game["home_team"], game["away_team"]):
            _require(team not in team_to_game, f"team {team} appears in multiple scheduled games")
            team_to_game[team] = game["game_id"]
    rows = payload.get("rows")
    _require(isinstance(rows, list), "board.rows must be an array")
    _require(len(rows) > 0, "board.rows must contain at least one real prediction")

    seen = set()
    for i, row in enumerate(rows):
        _require(isinstance(row, dict), f"rows[{i}] must be an object")
        missing = [field for field in BOARD_FIELDS if field not in row]
        _require(not missing, f"rows[{i}] missing required fields: {', '.join(missing)}")
        for field in ("player_id", "player", "position", "game_status"):
            _require(isinstance(row[field], str) and row[field].strip(),
                     f"rows[{i}].{field} must be a non-empty string")
        player_id = row["player_id"].strip()
        _require(player_id not in seen, f"duplicate player_id {player_id!r}")
        seen.add(player_id)
        _require(row["game_id"] in game_by_id,
                 f"rows[{i}].game_id {row['game_id']!r} is not scheduled for this week")
        _require(row["game_status"] in GAME_STATUSES,
                 f"rows[{i}].game_status has invalid value {row['game_status']!r}")
        _require(row["injury_status"] in INJURY_STATUSES,
                 f"rows[{i}].injury_status has invalid value {row['injury_status']!r}")
        _require(row["prediction_timing"] in PREDICTION_TIMINGS,
                 f"rows[{i}].prediction_timing has invalid value {row['prediction_timing']!r}")
        _require(row["prediction_timing"] == game_by_id[row["game_id"]]["prediction_timing"],
                 f"rows[{i}].prediction_timing does not match its scheduled game")
        for field in ("team", "opponent"):
            _require(isinstance(row[field], str) and row[field] in TEAM_CODES,
                     f"rows[{i}].{field} has invalid NFL team code {row[field]!r}")
        for field in ("td_score", "td_estimate"):
            _finite_number(row[field], field, i)
        game = game_by_id[row["game_id"]]
        _require({row["team"], row["opponent"]} == {game["home_team"], game["away_team"]},
                 f"rows[{i}] team/opponent do not match scheduled game {row['game_id']!r}")
    return payload


def validate_breakdowns(payload, season, week, board_games=None):
    _require(isinstance(payload, dict), "breakdowns must be a JSON object")
    meta = payload.get("meta")
    _require(isinstance(meta, dict), "breakdowns.meta must be an object")
    _require(meta.get("season") == season, f"breakdowns season mismatch: expected {season}")
    _require(meta.get("week") == week, f"breakdowns week mismatch: expected {week}")
    _require(isinstance(payload.get("games"), dict), "breakdowns.games must be an object")
    _require(len(payload["games"]) > 0, "breakdowns.games must contain at least one successful game breakdown")
    _require(isinstance(payload.get("errors"), dict), "breakdowns.errors must be an object")
    if board_games is not None:
        expected = {f"{g['away_team']}@{g['home_team']}" for g in board_games}
        actual = set(payload["games"]) | set(payload["errors"])
        _require(actual.issubset(expected), "breakdowns contain a game outside the selected week's schedule")
        for key, game in payload["games"].items():
            _require(isinstance(game, dict) and game.get("teams") == key.split("@"),
                     f"breakdowns game {key!r} does not match its team pair")
    return payload
