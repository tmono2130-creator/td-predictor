"""Build participation-verified historical player/game touchdown outcomes."""

import re

import pandas as pd

from evaluation_utils import require_complete_regular_week
from outcome_semantics import touchdown_count

EVALUATION_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
POSITION_ALIASES = {"HB": "RB"}


def canonical_position(value):
    position = str(value or "").strip().upper()
    return POSITION_ALIASES.get(position, position)


def normalized_name(value):
    name = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    for suffix in ("junior", "senior", "jr", "sr", "iii", "ii", "iv", "v"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return name


def _week_rows(frame, season, week, type_columns):
    rows = frame.copy()
    if "season" in rows:
        rows = rows[pd.to_numeric(rows["season"], errors="coerce") == season]
    if "week" in rows:
        rows = rows[pd.to_numeric(rows["week"], errors="coerce") == week]
    for column in type_columns:
        if column in rows:
            rows = rows[rows[column].astype(str).str.strip().str.upper() == "REG"]
            break
    return rows.copy()


def _prepare_stats(player_stats, season, week):
    stats = _week_rows(player_stats, season, week, ("season_type", "game_type"))
    required = {"player_id", "game_id", "team", "position"}
    missing = required.difference(stats.columns)
    if missing:
        raise ValueError(f"Player stats are missing required columns: {', '.join(sorted(missing))}.")
    for column in ("player_id", "game_id", "team"):
        stats[column] = stats[column].fillna("").astype(str).str.strip()
    stats["position"] = stats["position"].map(canonical_position)
    stats = stats[stats["position"].isin(EVALUATION_POSITIONS)].copy()
    stats = stats[(stats.player_id != "") & (stats.game_id != "")].copy()
    for column in ("rushing_tds", "receiving_tds"):
        if column not in stats:
            raise ValueError(f'Player stats are missing touchdown evidence: {column}')
        stats[column] = stats[column].map(touchdown_count)
    stats["actual_rushing_tds"] = stats.rushing_tds.astype(float)
    stats["actual_receiving_tds"] = stats.receiving_tds.astype(float)
    stats["actual_td_count"] = stats.actual_rushing_tds + stats.actual_receiving_tds
    stats["actual_td"] = (stats.actual_td_count > 0).astype(int)
    name_column = next((c for c in ("player_display_name", "player_name", "player") if c in stats), None)
    stats["player"] = stats[name_column].fillna("").astype(str) if name_column else ""
    stats["_name_key"] = stats.player.map(normalized_name)
    if stats.duplicated(["player_id", "game_id"], keep=False).any():
        raise ValueError("Player stats contain duplicate player/game rows.")
    return stats


def build_actual_player_games(player_stats, snap_counts, player_id_crosswalk,
                              schedule, season, week):
    """Build outcomes only for positive-offense-snap participants or TD scorers.

    TD labels include rushing and receiving touchdowns, exclude passing TDs,
    and retain multi-TD counts. An offense snap verifies participation, not a negative TD label; a
    recorded offensive TD is participation evidence when snap ID mapping fails.
    """
    games = require_complete_regular_week(schedule, season, week)
    required_game = {"game_id", "home_team", "away_team", "home_score", "away_score"}
    if not required_game.issubset(games.columns):
        raise ValueError("Completed schedule is missing matchup or score columns.")
    if games.game_id.isna().any() or games.game_id.astype(str).duplicated().any():
        raise ValueError("Schedule has a missing or duplicate game ID.")
    game_by_id = {str(row.game_id): row for row in games.itertuples(index=False)}
    stats = _prepare_stats(player_stats, season, week)
    stat_by_key = {(str(row.player_id), str(row.game_id)): row for row in stats.itertuples(index=False)}
    crosswalk = player_id_crosswalk.copy()
    if not {"pfr_id", "gsis_id"}.issubset(crosswalk.columns):
        raise ValueError("Player ID crosswalk must contain pfr_id and gsis_id columns.")
    crosswalk = crosswalk.dropna(subset=["pfr_id", "gsis_id"])[["pfr_id", "gsis_id"]].copy()
    crosswalk["pfr_id"] = crosswalk.pfr_id.astype(str).str.strip()
    crosswalk["gsis_id"] = crosswalk.gsis_id.astype(str).str.strip()
    if (crosswalk.groupby("pfr_id").gsis_id.nunique() > 1).any():
        raise ValueError("Player ID crosswalk maps a PFR ID to multiple GSIS IDs.")
    pfr_to_gsis = dict(zip(crosswalk.drop_duplicates("pfr_id").pfr_id,
                           crosswalk.drop_duplicates("pfr_id").gsis_id))

    snaps = _week_rows(snap_counts, season, week, ("game_type", "season_type"))
    required_snap = {"game_id", "team", "position", "offense_snaps", "pfr_player_id", "player"}
    missing_snap = required_snap.difference(snaps.columns)
    if missing_snap:
        raise ValueError(f"Snap counts are missing required columns: {', '.join(sorted(missing_snap))}.")
    for column in ("game_id", "team", "pfr_player_id"):
        snaps[column] = snaps[column].fillna("").astype(str).str.strip()
    snaps["position"] = snaps.position.map(canonical_position)
    snaps["offense_snaps"] = pd.to_numeric(snaps.offense_snaps, errors="coerce").fillna(0)
    snaps = snaps[snaps.position.isin(EVALUATION_POSITIONS) & (snaps.offense_snaps > 0)].copy()
    snaps["player"] = snaps.player.fillna("").astype(str)
    snaps["_name_key"] = snaps.player.map(normalized_name)

    rows = []
    present_gsis = set()
    for _, snap in snaps.iterrows():
        game_id, team = str(snap.game_id), str(snap.team)
        game = game_by_id.get(game_id)
        if game is None:
            raise ValueError(f"Snap-count game {game_id!r} is not scheduled in {season} week {week}.")
        if team not in {str(game.home_team), str(game.away_team)}:
            raise ValueError(f"Snap-count team does not match schedule game {game_id!r}.")
        player_id = pfr_to_gsis.get(str(snap.pfr_player_id))
        namespace = "gsis" if player_id else "pfr"
        if not player_id:
            player_id = str(snap.pfr_player_id)
        if not player_id:
            continue
        stat = stat_by_key.get((str(player_id), game_id)) if namespace == "gsis" else None
        if stat is not None and str(stat.team) != team:
            raise ValueError(f"Player {player_id!r} stats and snaps disagree on team in {game_id}.")
        position = canonical_position(stat.position) if stat is not None else canonical_position(snap.position)
        if position not in EVALUATION_POSITIONS:
            continue
        player_name = str(stat.player) if stat is not None and str(stat.player) else str(snap.player)
        opponent = str(game.away_team) if team == str(game.home_team) else str(game.home_team)
        row = {
            "player_id": str(player_id) if namespace == "gsis" else f"pfr:{player_id}",
            "player_id_namespace": namespace,
            "game_id": game_id, "season": int(season), "week": int(week),
            "player": player_name, "team": team, "opponent": opponent,
            "position": position,
            "kickoff_utc": f"{getattr(game, 'gameday', '')} {getattr(game, 'gametime', '')}".strip(),
            "offense_snaps": float(snap.offense_snaps),
            "actual_rushing_tds": float(stat.actual_rushing_tds) if stat is not None else None,
            "actual_receiving_tds": float(stat.actual_receiving_tds) if stat is not None else None,
            "actual_td_count": float(stat.actual_td_count) if stat is not None else None,
            "actual_td": int(stat.actual_td) if stat is not None else None,
            "outcome_verified": stat is not None,
            "participation_source": "offensive_snap",
        }
        rows.append(row)
        if namespace == "gsis":
            present_gsis.add((str(player_id), game_id))

    # Positive rushing/receiving TD rows are independently verified game participation.
    for stat in stats.itertuples(index=False):
        if int(stat.actual_td) != 1:
            continue
        key = (str(stat.player_id), str(stat.game_id))
        if key in present_gsis:
            continue
        game = game_by_id.get(str(stat.game_id))
        if game is None:
            raise ValueError(f"Scoring player game {stat.game_id!r} is not scheduled in {season} week {week}.")
        team = str(stat.team)
        if team not in {str(game.home_team), str(game.away_team)}:
            raise ValueError(f"Scoring player team does not match schedule game {stat.game_id!r}.")
        opponent = str(game.away_team) if team == str(game.home_team) else str(game.home_team)
        if hasattr(stat, "opponent_team") and pd.notna(stat.opponent_team) and str(stat.opponent_team).strip():
            if str(stat.opponent_team).strip() != opponent:
                raise ValueError(f"Scoring player opponent does not match schedule game {stat.game_id!r}.")
        rows.append({
            "player_id": str(stat.player_id), "player_id_namespace": "gsis",
            "game_id": str(stat.game_id), "season": int(season), "week": int(week),
            "player": str(stat.player), "team": team, "opponent": opponent,
            "position": canonical_position(stat.position),
            "kickoff_utc": f"{getattr(game, 'gameday', '')} {getattr(game, 'gametime', '')}".strip(),
            "offense_snaps": pd.NA,
            "actual_rushing_tds": float(stat.actual_rushing_tds),
            "actual_receiving_tds": float(stat.actual_receiving_tds),
            "actual_td_count": float(stat.actual_td_count), "actual_td": 1,
            "outcome_verified": True,
            "participation_source": "offensive_td_stat",
        })

    if not rows:
        raise ValueError(f"No participation-verified players found for {season} week {week}.")
    outcomes = pd.DataFrame(rows)
    key = ["season", "week", "player_id_namespace", "player_id", "game_id"]
    if outcomes.duplicated(key, keep=False).any():
        raise ValueError("Historical outcomes contain duplicate player/game observations.")
    if outcomes["team"].eq(outcomes["opponent"]).any():
        raise ValueError("Historical outcomes contain invalid team/opponent pairs.")
    return outcomes.sort_values(["game_id", "team", "position", "player_id"]).reset_index(drop=True)
