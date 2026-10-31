"""Generate unpublished weekly candidates using unchanged V5 scoring functions."""
import hashlib
from pathlib import Path
import pandas as pd
import nflreadpy
import td_predictor_v5 as v5
import game_breakdown as breakdown
from export_json import breakdown_payload, df_records, BOARD_COLUMNS
from weekly_schedule import kickoff, utc_now
from weekly_storage import digest, write_new, validate_candidate


def redzone_opportunities(pbp):
    # Same V5 red-zone weights/aggregation, applied only to pre-week PBP.
    rz = pbp[(pbp.yardline_100 <= 20) & pbp.play_type.isin(["pass", "run"])].copy()
    rz["opp_weight"] = 1.0
    rz.loc[rz.yardline_100 <= 10, "opp_weight"] = 1.5
    parts = []
    for field in ("receiver_player_id", "rusher_player_id"):
        parts.append(rz.dropna(subset=[field]).groupby([field, "season", "week"]).opp_weight.sum().reset_index().rename(columns={field: "player_id"}))
    return pd.concat(parts).groupby(["player_id", "season", "week"], as_index=False).opp_weight.sum().rename(columns={"opp_weight": "redzone_opportunity"})


def score_v5(roster, histories, pbp, injuries, plan):
    season = plan["season"]
    prior = histories[season - 1].copy()
    prior["model_source_weight"] = 0.65
    current = histories.get(season, pd.DataFrame()).copy()
    if not current.empty:
        current["model_source_weight"] = 1.0
    stats = pd.concat([prior, current], ignore_index=True) if not current.empty else prior
    profiles = v5.build_historical_player_profiles(stats, redzone_opportunities(pbp))
    # Remove retired/transferred/other-week identities from the actual candidate pool.
    profiles = profiles[profiles.player_id.isin(set(roster.player_id))].copy()
    roster_map = roster.set_index("player_id")
    profiles["team"] = profiles.player_id.map(roster_map.team)
    profiles["position"] = profiles.player_id.map(roster_map.position)
    matchups = {g[t]: g[o] for g in plan["games"] for t, o in (("home_team", "away_team"), ("away_team", "home_team"))}
    profiles = v5.inject_missing_roster_players(profiles, roster, matchups)
    profiles = profiles[profiles.team.isin(matchups)].copy()
    profiles = profiles.merge(injuries[["player_id", "injury_status"]], on="player_id", how="left", validate="one_to_one")
    profiles["injury_status"] = profiles.injury_status.fillna("Unknown")
    profiles["opponent"] = profiles.team.map(matchups)
    defense = []
    for year in range(season - 3, season):
        frame = histories[year].copy()
        frame["model_source_weight"] = 0.6 ** (season - year)
        defense.append(frame)
    if not current.empty:
        defense.append(current)
    scored = v5.score_players(v5.build_role_scores(profiles), v5.build_team_environment(stats),
                              v5.build_defensive_matchups(pd.concat(defense, ignore_index=True)))
    game_by_team = {g[t]: g for g in plan["games"] for t in ("away_team", "home_team")}
    scored["game_id"] = scored.team.map(lambda team: game_by_team[team]["game_id"])
    scored["is_home"] = scored.team.map(lambda team: int(game_by_team[team]["home_team"] == team))
    return scored


def build_breakdowns(histories, pbp, schedule, injuries, plan, lookback=6):
    season, week = plan["season"], plan["week"]
    window = breakdown.team_windows(breakdown.build_team_games(schedule), season, week, lookback)
    clean = pbp[pd.to_numeric(pbp.two_point_attempt, errors="coerce").fillna(0).eq(0)].copy()
    info = pd.concat([histories[y] for y in (season - 1, season) if y in histories], ignore_index=True)
    info = info.sort_values(["season", "week"]).drop_duplicates("player_id", keep="last")
    info["group"] = info.position.map(breakdown.POSITION_GROUPS)
    context = {"season": season, "week": week, "lookback": lookback, "window": window,
               "pbp": clean, "profile": breakdown.aggregate_team_profile(breakdown.per_game_team_metrics(clean, window)),
               "info": info.set_index("player_id"), "first_td": breakdown.first_offensive_td_counts(clean),
               "injury_by_id": dict(zip(injuries.player_id, injuries.injury_status)), "injury_by_name": {}}
    games = {}
    for game in plan["games"]:
        key = f"{game['away_team']}@{game['home_team']}"
        games[key] = breakdown_payload(breakdown.build_game_from_context(context, game["away_team"], game["home_team"]))
    return {"meta": {"season": season, "week": week, "lookback": lookback, "generated_at": utc_now().isoformat()},
            "games": games, "errors": {}}


def generate_candidate(plan, schedule_records, sources, destination, data_root, clock=utc_now):
    if plan["status"] != "ready":
        raise ValueError("No scheduled games eligible for generation")
    base_manifest_hash = digest(Path(data_root) / "manifest.json")
    source_cutoff = sources.cutoff if hasattr(sources, "cutoff") else clock()
    scheduled_teams = {g[t] for g in plan['games'] for t in ('home_team', 'away_team')}
    roster = sources.rosters(plan["season"], plan["week"], plan["historical"], teams=scheduled_teams)
    histories, pbp = sources.history(schedule_records, plan["season"], plan["week"], source_cutoff)
    injuries = sources.injuries(plan["season"], plan["week"], source_cutoff, plan["historical"], roster)
    known_injury_ids = set(injuries.loc[injuries.injury_status.ne("Unknown"), "player_id"])
    sources.metadata["injury_coverage"] = {
        "eligible_players": len(roster), "known_designations": len(known_injury_ids),
        "unknown_players": len(roster) - len(known_injury_ids),
        "unknown_is_not_active": True,
        "limitation": "Missing final designations are Unknown; roster membership and practice participation do not establish game-day activation",
    }
    scored = score_v5(roster, histories, pbp, injuries, plan)
    schedule = pd.DataFrame(schedule_records)
    schedule["season"] = pd.to_numeric(schedule.season)
    schedule["week"] = pd.to_numeric(schedule.week)
    for column in ("home_score", "away_score"):
        schedule[column] = pd.to_numeric(schedule[column], errors="coerce")
    # Only verified historical finals may enter legacy report windows.
    if hasattr(sources, 'cutoff'):
        from weekly_schedule import regular_games
        verified_ids = {g['game_id'] for g in regular_games(schedule_records, min_season=plan['season'] - 3)
                        if g['complete'] and kickoff(g) < source_cutoff}
        schedule.loc[~schedule.game_id.isin(verified_ids), ['home_score', 'away_score']] = None
    reports = build_breakdowns(histories, pbp, schedule, injuries, plan)
    generated = clock()
    if not plan["historical"] and any(generated >= kickoff(g) for g in plan["games"]):
        raise ValueError("Kickoff passed during generation; discard this batch and regenerate")
    kind = "historical_backfill" if plan["historical"] else "pregame_snapshot"
    generated_text = generated.isoformat()
    reports["meta"]["generated_at"] = generated_text
    scored["game_status"] = "Final" if plan["historical"] else "Upcoming"
    scored["prediction_timing"] = kind
    scored["snapshot_classification"] = kind
    scored["prediction_timestamp_utc"] = generated_text
    scored["actual_scored_td"] = None
    for column in ("td_score", "td_estimate"):
        scored[column] = pd.to_numeric(scored[column], errors="raise").round(3)
    scored["predicted_td_probability_pct"] = scored.td_estimate
    version = "v5-composite-sha256:" + hashlib.sha256(Path(v5.__file__).read_bytes()).hexdigest()
    games = [{k: g[k] for k in ("game_id", "home_team", "away_team", "kickoff_utc")} |
             {"prediction_timing": kind, "snapshot_classification": kind} for g in plan["games"]]
    board = {"meta": {"season": plan["season"], "week": plan["week"], "generated_at": generated_text,
                     "model": "composite", "model_version": version, "snapshot_classification": kind,
                     "probability_semantics": "unchanged V5 estimate; not established as calibrated across seasons",
                     "source_versions": {"nflreadpy": getattr(nflreadpy, "__version__", "unknown"),
                                         "upstream_revision": "not supplied by feed; retrieved input fingerprints in receipt",
                                         "feature_cutoff": f"prior to {plan['season']} week {plan['week']}"},
                     "games": games, "final_games": [],
                     "injury_report": {"source": "nflverse weekly report; historical publication times unavailable",
                                       "week_available": bool(injuries.attrs.get("week_report_available", False)), "unknown_is_not_active": True}},
             "rows": df_records(scored[[c for c in BOARD_COLUMNS if c in scored]])}
    team_game = {g[t]: (g, g[o]) for g in plan["games"] for t, o in (("home_team", "away_team"), ("away_team", "home_team"))}
    expected = [{"player_id": r.player_id, "game_id": team_game[r.team][0]["game_id"], "team": r.team,
                 "opponent": team_game[r.team][1]} for r in roster.itertuples() if r.team in team_game]
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    write_new(destination / "board.json", board)
    write_new(destination / "breakdowns.json", reports)
    receipt = {"source_cutoff_utc": source_cutoff.isoformat(), "scheduled_games": plan["games"],
               "eligible_players": expected, "source_metadata": sources.metadata,
               "base_manifest_sha256": base_manifest_hash,
               "board_sha256": digest(destination / "board.json"), "breakdowns_sha256": digest(destination / "breakdowns.json"),
               "limitations": ["public feeds do not preserve immutable upstream vintages", "historical injuries excluded",
                               "zero-history roster players use the existing V5 no-history prior, not observed zero stats"]}
    write_new(destination / "receipt.json", receipt)
    validate_candidate(destination, now=generated, allow_historical=plan["historical"])
    return destination
