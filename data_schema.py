"""Validation helpers for the Python-to-JSON website data contract.

Schema version 1 uses a board object with ``meta`` and ``rows``. ``td_score``
keeps V5's 0..100 ranking-score scale; ``td_estimate`` remains the calibrated
TD probability in percent. In fitted-model mode, V5 itself sets both to
probability * 100. Validation does not reinterpret or transform either field.
"""

import math

SCHEMA_VERSION = 1
SUPPORTED_WEEKS = tuple(range(1, 19))
TEAM_CODES = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS",
})
BOARD_FIELDS = (
    "player_id", "player", "team", "position", "opponent", "td_score",
    "td_estimate", "game_status",
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
        for field in ("team", "opponent"):
            _require(isinstance(row[field], str) and row[field] in TEAM_CODES,
                     f"rows[{i}].{field} has invalid NFL team code {row[field]!r}")
        for field in ("td_score", "td_estimate"):
            _finite_number(row[field], field, i)
    return payload


def validate_breakdowns(payload, season, week):
    _require(isinstance(payload, dict), "breakdowns must be a JSON object")
    meta = payload.get("meta")
    _require(isinstance(meta, dict), "breakdowns.meta must be an object")
    _require(meta.get("season") == season, f"breakdowns season mismatch: expected {season}")
    _require(meta.get("week") == week, f"breakdowns week mismatch: expected {week}")
    _require(isinstance(payload.get("games"), dict), "breakdowns.games must be an object")
    _require(len(payload["games"]) > 0, "breakdowns.games must contain at least one successful game breakdown")
    _require(isinstance(payload.get("errors"), dict), "breakdowns.errors must be an object")
    return payload
