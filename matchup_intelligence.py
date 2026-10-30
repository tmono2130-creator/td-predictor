"""Pregame-cutoff scouting analytics. Independent of V5; no publication writes."""
import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone, timedelta
import pandas as pd
from data_schema import TEAM_CODES
from weekly_schedule import regular_games, kickoff, utc
from roster_eligibility import resolve_roster

VERSION = "matchup-v1"
GROUPS = ("QB", "RB", "WR", "TE")
REQUIRED = {"game_id", "play_id", "season", "week", "season_type", "posteam", "defteam", "play_type",
            "yardline_100", "yards_gained", "two_point_attempt", "touchdown", "rush_touchdown", "pass_touchdown",
            "td_team", "td_player_id", "rusher_player_id", "receiver_player_id", "drive"}
POLICY = {"min_games": 4, "min_player_opportunities": 10, "min_player_rz": 3,
          "min_defense_position_rz": 12, "min_league_position_rz": 100, "min_identity_coverage": .95,
          "wilson_z": 1.96, "relative_rate_threshold": .25, "min_absolute_rate_gap": .05, "min_player_rz_share": .15}
LIMITATIONS = ["Separate heuristic matchup signal; not a calibrated touchdown probability or demonstrated accuracy improvement.",
              "No personnel, formation, route, coverage or opponent-strength adjustment supplied.",
              "Run/pass play types exclude kneels, spikes, no-plays and two-point attempts; passes include sacks.",
              "Target denominator is plays with an intended receiver ID; unidentified throws are not assigned to positions.",
              "Position rates exclude lateral/unattributed scoring plays; exclusions and attribution coverage are reported.",
              "Public historical feed revisions do not establish the original pregame source vintage."]


def ratio(n, d):
    return None if not d else round(n / d, 6)


def canonical(value):
    return isinstance(value, str) and re.fullmatch(r"00-\d{7}", value) is not None


def fingerprint(frame):
    return hashlib.sha256(frame.to_json(orient="split", date_format="iso").encode()).hexdigest()


def clean_inputs(schedule, pbp, info, known, season, week, cutoff):
    games = regular_games(schedule, min_season=season, max_season=season)
    if len({g["game_id"] for g in games}) != len(games):
        raise ValueError("Duplicate schedule game")
    history = {g["game_id"]: g for g in games if g["week"] < week and g["complete"] and kickoff(g) < cutoff}
    if not REQUIRED.issubset(pbp):
        raise ValueError("PBP missing fields: " + ", ".join(sorted(REQUIRED - set(pbp.columns))))
    if not {"player_id", "game_id", "team", "position", "season", "week"}.issubset(info):
        raise ValueError("Player-game identity records are incomplete")
    p = pbp[pbp.game_id.isin(history)].copy()
    if p.duplicated(["game_id", "play_id"]).any():
        raise ValueError("Duplicate play identity")
    if not p.season.eq(season).all() or not p.season_type.eq("REG").all():
        raise ValueError("PBP season/type differs from schedule")
    if any(int(r.week) != history[r.game_id]["week"] or
           {r.posteam, r.defteam} != {history[r.game_id]["away_team"], history[r.game_id]["home_team"]}
           for r in p[p.play_type.isin(["run", "pass"])].itertuples()):
        raise ValueError("Play team/week differs from schedule")
    p = p[p.play_type.isin(["run", "pass"])].copy()
    for col in ("two_point_attempt", "touchdown", "rush_touchdown", "pass_touchdown"):
        p[col] = pd.to_numeric(p[col], errors="coerce")
        if not p[col].isin([0, 1]).all():
            raise ValueError("Missing or malformed event evidence: " + col)
    p = p[p.two_point_attempt.eq(0)].copy()
    for col in ("yardline_100", "yards_gained"):
        p[col] = pd.to_numeric(p[col], errors="coerce")
        if not p[col].map(lambda v: pd.isna(v) or math.isfinite(v)).all():
            raise ValueError("Nonfinite play metric")
    if not p.yardline_100.dropna().between(0, 100).all():
        raise ValueError("Invalid field position")
    ids = set(known.gsis_id.dropna()) if "gsis_id" in known else set()
    i = info[info.game_id.isin(history)].copy()
    if i.duplicated(["game_id", "player_id", "team"]).any():
        raise ValueError("Ambiguous historical player identity")
    positions = {}
    for r in i.itertuples():
        game = history[r.game_id]
        if r.team not in (game["away_team"], game["home_team"]) or r.season != season or r.week != game["week"]:
            raise ValueError("Player identity team/date mismatch")
        if r.player_id in ids and canonical(r.player_id):
            positions[(r.game_id, r.player_id, r.team)] = "RB" if r.position in ("FB", "HB") else r.position
    for game_id, game in history.items():
        if set(p.loc[p.game_id.eq(game_id), "posteam"]) != {game["away_team"], game["home_team"]}:
            raise ValueError("Missing completed-game play coverage: " + game_id)
    p["is_run"] = p.play_type.eq("run")
    p["is_pass"] = p.play_type.eq("pass")
    p["rz"] = p.yardline_100.le(20) & p.yardline_100.notna()
    p["gl"] = p.yardline_100.le(5) & p.yardline_100.notna()
    p["off_td"] = p.touchdown.eq(1) & p.td_team.eq(p.posteam) & (p.rush_touchdown.eq(1) | p.pass_touchdown.eq(1))
    p["opportunity_player_id"] = p.rusher_player_id.where(p.is_run, p.receiver_player_id)
    p["has_opportunity"] = p.opportunity_player_id.map(lambda v: isinstance(v, str) and bool(v.strip())).astype(bool)
    p["position"] = [positions.get((r.game_id, r.opportunity_player_id, r.posteam)) for r in p.itertuples()]
    # A lateral TD is not assigned to the original ball carrier/target.
    p["player_td"] = p.off_td & p.td_player_id.eq(p.opportunity_player_id)
    p.loc[p.off_td & ~p.player_td, "position"] = None
    if "epa" in p:
        p["epa"] = pd.to_numeric(p.epa, errors="coerce")
        p.loc[~p.epa.map(lambda v: pd.notna(v) and math.isfinite(v)), "epa"] = float("nan")
    return p, history


def profile(p, ids):
    q = p[p.game_id.isin(ids)].copy()
    opportunities = q[q.has_opportunity]
    known = opportunities[opportunities.position.isin(GROUPS)]
    drives = q.dropna(subset=["drive"]).groupby(["game_id", "posteam", "drive"]).agg(rz=("rz", "max"), td=("off_td", "max"))
    trips = int(drives.rz.sum())
    rz_td = int((drives.rz & drives.td).sum())
    rz = int(q.rz.sum())
    yards = q.yards_gained.dropna()
    epa = q.epa.dropna() if "epa" in q else pd.Series(dtype=float)
    return {"games": len(ids), "game_ids": list(ids), "plays": len(q), "run_plays": int(q.is_run.sum()),
            "pass_plays": int(q.is_pass.sum()), "run_rate": ratio(int(q.is_run.sum()), len(q)),
            "plays_per_game": ratio(len(q), len(ids)), "rz_plays": rz, "rz_runs": int((q.rz & q.is_run).sum()),
            "rz_passes": int((q.rz & q.is_pass).sum()), "rz_run_rate": ratio(int((q.rz & q.is_run).sum()), rz),
            "goal_line_opportunities": int(q.gl.sum()), "rush_tds": int((q.off_td & q.rush_touchdown.eq(1)).sum()),
            "pass_tds": int((q.off_td & q.pass_touchdown.eq(1)).sum()), "rz_trips": trips, "rz_td_drives": rz_td,
            "rz_td_rate": ratio(rz_td, trips), "yards": None if len(yards) != len(q) else float(yards.sum()),
            "yards_per_play": ratio(float(yards.sum()), len(q)) if len(yards) == len(q) else None,
            "epa_per_play": ratio(float(epa.sum()), len(q)) if len(epa) == len(q) else None,
            "epa_sample": len(epa), "success_rate": ratio(int(epa.gt(0).sum()), len(q)) if len(epa) == len(q) else None,
            "position_td_exclusions": int((q.off_td & ~(q.player_td & q.position.isin(GROUPS))).sum()),
            "position_identity_matched": len(known), "position_identity_total": len(opportunities),
            "position_identity_coverage": ratio(len(known), len(opportunities)),
            "field_position_sample": int(q.yardline_100.notna().sum()), "drive_sample": int(q.drive.notna().sum())}


def position_rates(p):
    result = []
    for position in GROUPS:
        q = p[p.position.eq(position) & p.has_opportunity]
        rz = q[q.rz]
        yards = q.yards_gained.dropna()
        result.append({"position": position, "opportunities": len(q), "targets": int(q.is_pass.sum()),
                       "carries": int(q.is_run.sum()), "tds": int(q.player_td.sum()), "rz_opportunities": len(rz),
                       "rz_tds": int(rz.player_td.sum()), "td_rate": ratio(int(q.player_td.sum()), len(q)),
                       "rz_td_rate": ratio(int(rz.player_td.sum()), len(rz)),
                       "yards": float(yards.sum()) if len(yards) == len(q) else None,
                       "yards_per_opportunity": ratio(float(yards.sum()), len(q)) if len(yards) == len(q) else None})
    return result


def usage(p, player, snaps=None):
    q = p[p.opportunity_player_id.eq(player.player_id)]
    targets, carries = int(q.is_pass.sum()), int(q.is_run.sum())
    all_targets, all_carries = int((p.is_pass & p.has_opportunity).sum()), int((p.is_run & p.has_opportunity).sum())
    rz = p[p.rz & p.has_opportunity]
    s = snaps[snaps.player_id.eq(player.player_id) & snaps.game_id.isin(set(p.game_id))] if snaps is not None else pd.DataFrame()
    return {"player_id": player.player_id, "player": player.model_player_name, "team": player.team, "position": player.position,
            "targets": targets, "carries": carries, "opportunities": len(q), "rz_targets": int((q.rz & q.is_pass).sum()),
            "rz_carries": int((q.rz & q.is_run).sum()), "rz_opportunities": int(q.rz.sum()),
            "goal_line_opportunities": int(q.gl.sum()), "target_share": ratio(targets, all_targets),
            "carry_share": ratio(carries, all_carries), "rz_share": ratio(int(q.rz.sum()), len(rz)),
            "team_targets": all_targets, "team_carries": all_carries, "team_rz_opportunities": len(rz),
            "snap_participation_pct": float(s.offense_pct.mean()) * 100 if not s.empty else None,
            "snap_sample_games": int(s.game_id.nunique()) if not s.empty else 0}


def evidence_ready(sources, cutoff, generated, earliest, names, board_time):
    remaining = earliest - generated
    if not set(names).issubset(sources) or remaining <= timedelta(minutes=10):
        return False
    limit = timedelta(minutes=30) if remaining <= timedelta(hours=6) else timedelta(hours=6) if remaining <= timedelta(hours=48) else timedelta(hours=24)
    return all(timedelta(0) <= generated - utc(t) < limit for t in [cutoff, board_time, *sources.values()])


def wilson(n, d):
    if not d:
        return 0, 1
    z = POLICY["wilson_z"]
    center = n / d + z*z/(2*d)
    margin = z * math.sqrt((n/d)*(1-n/d)/d + z*z/(4*d*d))
    return (center-margin)/(1+z*z/d), (center+margin)/(1+z*z/d)


def designation(player, offense, defense, league, cutoff_known):
    reasons = []
    dp = next(r for r in defense["positions"] if r["position"] == ("RB" if player["position"] == "FB" else player["position"]))
    lp = next(r for r in league["positions"] if r["position"] == dp["position"])
    for ok, reason in ((cutoff_known, "Source availability or freshness is insufficient"),
                       (offense["recent"]["games"] >= POLICY["min_games"], "Fewer than four offensive games"),
                       (defense["recent"]["games"] >= POLICY["min_games"], "Fewer than four defensive games"),
                       (player["opportunities"] >= POLICY["min_player_opportunities"], "Too few player opportunities"),
                       (player["rz_opportunities"] >= POLICY["min_player_rz"], "Too few player red-zone opportunities"),
                       (dp["rz_opportunities"] >= POLICY["min_defense_position_rz"], "Too few defensive position red-zone opportunities"),
                       (lp["rz_opportunities"] >= POLICY["min_league_position_rz"], "Too few league position red-zone opportunities"),
                       ((defense["recent"]["position_identity_coverage"] or 0) >= POLICY["min_identity_coverage"], "Incomplete defensive position identity coverage"),
                       ((league["sample"]["position_identity_coverage"] or 0) >= POLICY["min_identity_coverage"], "Incomplete league position identity coverage"),
                       (league["sample"]["field_position_sample"] == league["sample"]["plays"], "Missing league field position"),
                       (defense["recent"]["field_position_sample"] == defense["recent"]["plays"], "Missing defensive field position"),
                       (offense["recent"]["field_position_sample"] == offense["recent"]["plays"], "Missing offensive field position")):
        if not ok:
            reasons.append(reason)
    if reasons or lp["rz_td_rate"] is None or dp["rz_td_rate"] is None:
        return "Insufficient Data", reasons or ["Missing reference rate"], dp, lp
    gap = dp["rz_td_rate"] - lp["rz_td_rate"]
    threshold = max(POLICY["min_absolute_rate_gap"], POLICY["relative_rate_threshold"] * lp["rz_td_rate"])
    involved = (player["rz_share"] or 0) >= POLICY["min_player_rz_share"]
    dlo, dhi = wilson(dp["rz_tds"], dp["rz_opportunities"])
    llo, lhi = wilson(lp["rz_tds"], lp["rz_opportunities"])
    if involved and gap >= threshold and dlo > lhi:
        return "Favorable", ["Meaningful red-zone involvement against an elevated position TD/opportunity rate"], dp, lp
    if gap <= -threshold and dhi < llo:
        return "Unfavorable", ["Opponent position TD/opportunity rate is materially below the league reference"], dp, lp
    return "Neutral", ["Evidence meets sample thresholds without a material favorable or unfavorable rate gap"], dp, lp


def build_intelligence(board, schedule, pbp, info, weekly_rosters, known, cutoff, generated_at=None, source_as_of=None, snaps=None):
    """Pure calculation. Never scores V5 or mutates any supplied frame/board."""
    cutoff = utc(cutoff)
    generated = utc(generated_at or datetime.now(timezone.utc))
    meta = board["meta"]
    season, week = meta["season"], meta["week"]
    games = [g for g in regular_games(schedule, min_season=season, max_season=season) if g["week"] == week]
    if not games or len({g["game_id"] for g in games}) != len(games) or {g["game_id"] for g in games} != {g["game_id"] for g in meta["games"]}:
        raise ValueError("Board and target schedule differ")
    earliest = min(kickoff(g) for g in games)
    if cutoff >= earliest or cutoff > generated:
        raise ValueError("Data cutoff must predate kickoff and generation")
    for g in games:
        b = next(r for r in meta["games"] if r["game_id"] == g["game_id"])
        if (b["home_team"], b["away_team"], utc(b["kickoff_utc"])) != (g["home_team"], g["away_team"], kickoff(g)):
            raise ValueError("Board matchup/kickoff mismatch")
    p, history = clean_inputs(schedule, pbp, info, known, season, week, cutoff)
    roster, audit = resolve_roster(weekly_rosters, pd.DataFrame(), known, season, week,
                                 {g[t] for g in games for t in ("home_team", "away_team")}, historical=True)
    if snaps is not None:
        if not {"player_id", "team", "game_id", "offense_pct"}.issubset(snaps):
            raise ValueError("Normalized GSIS snap records required")
        snaps = snaps[snaps.game_id.isin(history)].copy()
        if snaps.duplicated(["player_id", "game_id"]).any() or not snaps.offense_pct.map(lambda v: isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1).all():
            raise ValueError("Invalid snap participation")
        identity_keys = set(zip(info.game_id, info.player_id, info.team))
        if any((r.game_id, r.player_id, r.team) not in identity_keys for r in snaps.itertuples()):
            raise ValueError("Snap/player-game identity mismatch")
        if any(not canonical(r.player_id) or r.player_id not in set(known.gsis_id) or r.team not in (history[r.game_id]["home_team"], history[r.game_id]["away_team"]) for r in snaps.itertuples()):
            raise ValueError("Snap identity mismatch")
    inputs = {"pbp": pbp, "player_games": info, "weekly_rosters": weekly_rosters, "players": known}
    if snaps is not None:
        inputs["snaps"] = snaps
    sources = source_as_of or {}
    if any(utc(v) > cutoff for v in sources.values()):
        raise ValueError("Source availability exceeds cutoff")
    known_cutoff = set(inputs).issubset(sources) and "schedule" in sources
    mode = "pregame_snapshot" if known_cutoff and generated < earliest else "retrospective_analysis"
    # Retrospective analytics may be inspected, but unknown vintage never earns a designation.
    evidence_known = known_cutoff and mode == "pregame_snapshot" and evidence_ready(sources, cutoff, generated, earliest, [*inputs, "schedule"], meta["generated_at"])
    fingerprints = {k: fingerprint(v) for k, v in inputs.items()}
    fingerprints["schedule"] = hashlib.sha256(json.dumps(schedule, sort_keys=True, default=str).encode()).hexdigest()
    ordered = sorted(history, key=lambda gid: kickoff(history[gid]))
    league_ids = sorted({r.game_id for r in p.itertuples()})
    league = {"sample": profile(p, league_ids), "positions": position_rates(p)}
    out = {"meta": {"schema_version": 1, "methodology_version": VERSION, "season": season, "week": week,
                    "board_generated_at": meta["generated_at"], "data_as_of": cutoff.isoformat(), "generated_at": generated.isoformat(), "evidence_mode": mode,
                    "source_as_of": sources, "source_fingerprints": fingerprints,
                    "policy": copy.deepcopy(POLICY), "roster_audit": audit,
                    "input_games": [{"game_id": gid, "kickoff_utc": history[gid]["kickoff_utc"], "week": history[gid]["week"]} for gid in ordered],
                    "limitations": copy.deepcopy(LIMITATIONS)}, "games": {}}
    board_by_id = {}
    for row in board["rows"]:
        if row["player_id"] in board_by_id or not canonical(row["player_id"]) or row["team"] not in TEAM_CODES:
            raise ValueError("Invalid or duplicate board identity")
        if not isinstance(row["td_estimate"], (int, float)) or isinstance(row["td_estimate"], bool) or not math.isfinite(row["td_estimate"]) or not 0 <= row["td_estimate"] <= 100:
            raise ValueError("Invalid V5 probability")
        board_by_id[row["player_id"]] = row
    for game in games:
        offenses, defenses = {}, {}
        for team in (game["away_team"], game["home_team"]):
            ids = [gid for gid in ordered if team in (history[gid]["away_team"], history[gid]["home_team"]) and gid in set(p.game_id)]
            recent = ids[-6:]
            off = p[p.posteam.eq(team)]
            defense = p[p.defteam.eq(team)]
            offenses[team] = {"recent": profile(off, recent), "season": profile(off, ids), "trend": profile(off, ids[-3:]),
                              "players": [usage(off[off.game_id.isin(recent)], r, snaps) for r in roster[roster.team.eq(team)].itertuples()],
                              "personnel": None}
            defenses[team] = {"recent": profile(defense, recent), "season": profile(defense, ids), "trend": profile(defense, ids[-3:]),
                              "positions": position_rates(defense[defense.game_id.isin(recent)]), "league": league,
                              "opponent_adjustment": None}
        recommendations = []
        for team, opponent in ((game["away_team"], game["home_team"]), (game["home_team"], game["away_team"])):
            for player in offenses[team]["players"]:
                row = board_by_id.get(player["player_id"])
                if row is None:
                    continue
                if (row["game_id"], row["team"], row["opponent"], row["position"]) != (game["game_id"], team, opponent, player["position"]):
                    raise ValueError("Board/roster player matchup mismatch")
                label, explanation, dp, lp = designation(player, offenses[team], defenses[opponent], league, evidence_known)
                recommendations.append({**player, "opponent": opponent, "game_id": game["game_id"], "v5_probability_pct": row["td_estimate"],
                                        "advantage": label, "explanation": explanation, "defense_position": dp, "league_position": lp,
                                        "offense_games": offenses[team]["recent"]["games"], "defense_games": defenses[opponent]["recent"]["games"]})
        out["games"][game["game_id"]] = {"game_id": game["game_id"], "home_team": game["home_team"], "away_team": game["away_team"],
                                           "kickoff_utc": game["kickoff_utc"], "offenses": offenses, "defenses": defenses,
                                           "recommendations": recommendations}
    return out
