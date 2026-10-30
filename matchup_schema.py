"""Strict runtime contract plus semantic checks for immutable matchup sidecars."""
import math
import re
from matchup_intelligence import GROUPS, POLICY, VERSION, designation, evidence_ready
from weekly_schedule import utc

PROFILE_FIELDS = {"games", "game_ids", "plays", "run_plays", "pass_plays", "run_rate", "plays_per_game",
                  "rz_plays", "rz_runs", "rz_passes", "rz_run_rate", "goal_line_opportunities", "rush_tds", "pass_tds",
                  "rz_trips", "rz_td_drives", "rz_td_rate", "yards", "yards_per_play", "epa_per_play", "epa_sample",
                  "success_rate", "position_td_exclusions", "position_identity_matched", "position_identity_total", "position_identity_coverage",
                  "field_position_sample", "drive_sample"}
PROFILE_INTS = PROFILE_FIELDS - {"game_ids", "run_rate", "plays_per_game", "rz_run_rate", "rz_td_rate", "yards",
                                "yards_per_play", "epa_per_play", "success_rate", "position_identity_coverage"}
POSITION_FIELDS = {"position", "opportunities", "targets", "carries", "tds", "rz_opportunities", "rz_tds",
                   "td_rate", "rz_td_rate", "yards", "yards_per_opportunity"}
USAGE_FIELDS = {"player_id", "player", "team", "position", "targets", "carries", "opportunities", "rz_targets", "rz_carries",
                "rz_opportunities", "goal_line_opportunities", "target_share", "carry_share", "rz_share", "team_targets",
                "team_carries", "team_rz_opportunities", "snap_participation_pct", "snap_sample_games"}
RECOMMENDATION_FIELDS = USAGE_FIELDS | {"opponent", "game_id", "v5_probability_pct", "advantage", "explanation",
                                        "defense_position", "league_position", "offense_games", "defense_games"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def number(value, nullable=False):
    return (nullable and value is None) or (type(value) in (int, float) and math.isfinite(value))


def count(v):
    return type(v) is int and v >= 0


def rate(n, d, value):
    require(value is None if not d else number(value) and abs(value - n / d) <= .000001, "Rate/denominator mismatch")


def check_profile(p, inputs):
    require(isinstance(p, dict) and set(p) == PROFILE_FIELDS, "Invalid profile fields")
    require(all(count(p[c]) for c in PROFILE_INTS), "Invalid profile sample count")
    require(isinstance(p["game_ids"], list) and len(set(p["game_ids"])) == len(p["game_ids"]) == p["games"]
            and set(p["game_ids"]).issubset(inputs), "Invalid sample game references")
    require(p["run_plays"] + p["pass_plays"] == p["plays"] and p["rz_runs"] + p["rz_passes"] == p["rz_plays"] <= p["plays"], "Invalid play denominators")
    require(p["goal_line_opportunities"] <= p["rz_plays"] and p["rz_td_drives"] <= p["rz_trips"]
            and p["position_identity_matched"] <= p["position_identity_total"] <= p["plays"]
            and max(p["drive_sample"], p["field_position_sample"], p["epa_sample"], p["rush_tds"] + p["pass_tds"]) <= p["plays"], "Invalid profile coverage")
    for n, d, v in (("run_plays", "plays", "run_rate"), ("plays", "games", "plays_per_game"),
                    ("rz_runs", "rz_plays", "rz_run_rate"), ("rz_td_drives", "rz_trips", "rz_td_rate"),
                    ("position_identity_matched", "position_identity_total", "position_identity_coverage")):
        rate(p[n], p[d], p[v])
    for key in ("yards", "yards_per_play", "epa_per_play", "success_rate"):
        require(number(p[key], True), "Invalid numeric profile")
    if p["yards"] is not None:
        rate(p["yards"], p["plays"], p["yards_per_play"])
    else:
        require(p["yards_per_play"] is None, "Missing yards cannot imply efficiency")
    require(p["success_rate"] is None or 0 <= p["success_rate"] <= 1, "Invalid success rate")
    if p["epa_sample"] != p["plays"]:
        require(p["epa_per_play"] is None and p["success_rate"] is None, "Partial EPA sample cannot imply full efficiency")


def check_positions(rows):
    require(isinstance(rows, list) and len(rows) == 4 and {r.get("position") for r in rows if isinstance(r, dict)} == set(GROUPS), "Invalid position groups")
    for r in rows:
        require(set(r) == POSITION_FIELDS and all(count(r[k]) for k in ("opportunities", "targets", "carries", "tds", "rz_opportunities", "rz_tds")), "Invalid position sample")
        require(r["targets"] + r["carries"] == r["opportunities"] and r["rz_tds"] <= r["rz_opportunities"] <= r["opportunities"] and r["tds"] <= r["opportunities"], "Invalid position denominators")
        rate(r["tds"], r["opportunities"], r["td_rate"])
        rate(r["rz_tds"], r["rz_opportunities"], r["rz_td_rate"])
        require(number(r["yards"], True) and number(r["yards_per_opportunity"], True), "Invalid position yards")
        if r["yards"] is not None:
            rate(r["yards"], r["opportunities"], r["yards_per_opportunity"])
        else:
            require(r["yards_per_opportunity"] is None, "Unknown yards cannot imply an average")


def check_usage(p, eligible):
    require(isinstance(p, dict) and set(p) == USAGE_FIELDS and p["player_id"] in eligible, "Invalid player usage identity")
    require((p["team"], p["position"]) == eligible[p["player_id"]] and isinstance(p["player"], str) and p["player"].strip(), "Usage roster mismatch")
    for key in ("targets", "carries", "opportunities", "rz_targets", "rz_carries", "rz_opportunities", "goal_line_opportunities", "team_targets", "team_carries", "team_rz_opportunities", "snap_sample_games"):
        require(count(p[key]), "Invalid player sample")
    require(p["targets"] + p["carries"] == p["opportunities"] and p["rz_targets"] + p["rz_carries"] == p["rz_opportunities"] <= p["opportunities"] and p["goal_line_opportunities"] <= p["rz_opportunities"], "Invalid usage denominators")
    for n, d, v in (("targets", "team_targets", "target_share"), ("carries", "team_carries", "carry_share"), ("rz_opportunities", "team_rz_opportunities", "rz_share")):
        require(p[n] <= p[d], "Player share exceeds team")
        rate(p[n], p[d], p[v])
    require(p["snap_participation_pct"] is None or number(p["snap_participation_pct"]) and 0 <= p["snap_participation_pct"] <= 100, "Invalid snap percentage")
    require((p["snap_participation_pct"] is None) == (p["snap_sample_games"] == 0), "Missing snap evidence")


def validate_intelligence(artifact, board):
    require(isinstance(artifact, dict) and set(artifact) == {"meta", "games"}, "Invalid matchup artifact")
    m = artifact["meta"]
    required = {"schema_version", "methodology_version", "season", "week", "board_generated_at", "data_as_of", "generated_at", "evidence_mode", "source_as_of", "source_fingerprints", "policy", "roster_audit", "input_games", "limitations"}
    require(isinstance(m, dict) and set(m) == required and type(m["schema_version"]) is int and m["schema_version"] == 1 and m["methodology_version"] == VERSION and m["policy"] == POLICY, "Invalid methodology/schema")
    require(type(m["season"]) is int and type(m["week"]) is int and m["season"] >= 2002 and 1 <= m["week"] <= 18 and (m["season"], m["week"], m["board_generated_at"]) == (board["meta"]["season"], board["meta"]["week"], board["meta"]["generated_at"]), "Artifact/board snapshot mismatch")
    cutoff, generated = utc(m["data_as_of"]), utc(m["generated_at"])
    require(cutoff <= generated and utc(m["board_generated_at"]) <= generated, "Invalid generation/source timing")
    require(m["evidence_mode"] in ("pregame_snapshot", "retrospective_analysis"), "Invalid evidence classification")
    require(isinstance(m["source_as_of"], dict) and all(utc(v) <= cutoff for v in m["source_as_of"].values()), "Invalid source cutoff")
    require(isinstance(m["source_fingerprints"], dict) and {"schedule", "pbp", "player_games", "weekly_rosters", "players"}.issubset(m["source_fingerprints"])
            and all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for v in m["source_fingerprints"].values()), "Missing source fingerprints")
    timestamps_known = set(m["source_fingerprints"]).issubset(m["source_as_of"])
    known = m["evidence_mode"] == "pregame_snapshot" and evidence_ready(m["source_as_of"], cutoff, generated, min(utc(g["kickoff_utc"]) for g in board["meta"]["games"]), m["source_fingerprints"], m["board_generated_at"])
    require(isinstance(m["limitations"], list) and all(isinstance(v, str) for v in m["limitations"]), "Missing limitations")
    require(isinstance(m["input_games"], list), "Missing sample audit")
    inputs = {}
    for g in m["input_games"]:
        require(set(g) == {"game_id", "kickoff_utc", "week"} and re.fullmatch(r"[0-9]{4}_[0-9]{2}_[A-Z]+_[A-Z]+", g["game_id"]) and g["game_id"].startswith(str(m["season"]) + "_")
                and g["game_id"] not in inputs and type(g["week"]) is int and 1 <= g["week"] < m["week"] and utc(g["kickoff_utc"]) < cutoff, "Future/duplicate sample game")
        inputs[g["game_id"]] = g
    audit = m["roster_audit"]
    require(isinstance(audit, dict) and audit.get("season") == m["season"] and audit.get("week") == m["week"] and audit.get("policy_version") == "week-aware-v1", "Invalid roster audit")
    decisions = audit.get("decisions", [])
    counts = {k: sum(d.get("decision") == k for d in decisions) for k in ("include", "exclude", "pending")}
    require(counts == audit.get("counts") and counts["pending"] == 0, "Pending roster evidence")
    require(all(d.get("decision") in counts for d in decisions), "Unknown roster decision")
    eligible = {}
    for r in decisions:
        if r.get("decision") == "include":
            require(r["roster_status"] == "ACT" and re.fullmatch(r"00-\d{7}", r["player_id"]) and r["player_id"] not in eligible, "Invalid eligible identity")
            eligible[r["player_id"]] = (r["team"], r["position"])
    require({r[0] for r in eligible.values()} == {g[t] for g in board["meta"]["games"] for t in ("home_team", "away_team")}, "Missing eligible team coverage")
    board_rows = {r["player_id"]: r for r in board["rows"]}
    require(len(board_rows) == len(board["rows"]), "Duplicate board identity")
    expected = {g["game_id"]: g for g in board["meta"]["games"]}
    require(isinstance(artifact["games"], dict) and set(artifact["games"]) == set(expected), "Game coverage mismatch")
    for gid, g in artifact["games"].items():
        require(set(g) == {"game_id", "home_team", "away_team", "kickoff_utc", "offenses", "defenses", "recommendations"}, "Invalid game fields")
        b = expected[gid]
        require(g["game_id"] == gid and (g["home_team"], g["away_team"], utc(g["kickoff_utc"])) == (b["home_team"], b["away_team"], utc(b["kickoff_utc"])), "Game identity/kickoff mismatch")
        require(cutoff < utc(g["kickoff_utc"]), "Post-kickoff cutoff")
        if m["evidence_mode"] == "pregame_snapshot":
            require(timestamps_known and generated < utc(g["kickoff_utc"]), "Unverified pregame vintage")
        require(set(g["offenses"]) == set(g["defenses"]) == {g["home_team"], g["away_team"]}, "Team coverage mismatch")
        usage_by_id = {}
        for team in g["offenses"]:
            off, defense = g["offenses"][team], g["defenses"][team]
            require(set(off) == {"recent", "season", "trend", "players", "personnel"} and set(defense) == {"recent", "season", "trend", "positions", "league", "opponent_adjustment"}, "Invalid team sections")
            require(off["personnel"] is None and defense["opponent_adjustment"] is None, "Unsupported statistics supplied")
            for key in ("recent", "season", "trend"):
                check_profile(off[key], inputs); check_profile(defense[key], inputs)
                require(off[key]["game_ids"] == defense[key]["game_ids"] and all(team in gid.split("_")[2:] for gid in off[key]["game_ids"]), "Team sample identity mismatch")
            require(len(off["recent"]["game_ids"]) <= 6 and len(off["trend"]["game_ids"]) <= 3 and set(off["recent"]["game_ids"]).issubset(off["season"]["game_ids"]) and set(off["trend"]["game_ids"]).issubset(off["recent"]["game_ids"]), "Invalid trend window")
            check_positions(defense["positions"])
            require(sum(p["opportunities"] for p in defense["positions"]) == defense["recent"]["position_identity_matched"]
                    and sum(p["tds"] for p in defense["positions"]) + defense["recent"]["position_td_exclusions"] == defense["recent"]["rush_tds"] + defense["recent"]["pass_tds"], "Position/profile attribution differs")
            check_profile(defense["league"]["sample"], inputs); check_positions(defense["league"]["positions"])
            require(sum(p["opportunities"] for p in defense["league"]["positions"]) == defense["league"]["sample"]["position_identity_matched"]
                    and sum(p["tds"] for p in defense["league"]["positions"]) + defense["league"]["sample"]["position_td_exclusions"] == defense["league"]["sample"]["rush_tds"] + defense["league"]["sample"]["pass_tds"], "League/profile attribution differs")
            require({p["player_id"] for p in off["players"]} == {pid for pid, membership in eligible.items() if membership[0] == team}, "Incomplete eligible player usage")
            for p in off["players"]:
                check_usage(p, eligible)
                require(p["team"] == team and p["player_id"] not in usage_by_id, "Duplicate/wrong-team usage")
                usage_by_id[p["player_id"]] = p
        expected_players = {pid for pid in usage_by_id if pid in board_rows}
        require(isinstance(g["recommendations"], list) and {r["player_id"] for r in g["recommendations"]} == expected_players and len(g["recommendations"]) == len(expected_players), "Recommendation player coverage mismatch")
        for row in g["recommendations"]:
            require(set(row) == RECOMMENDATION_FIELDS, "Invalid recommendation fields")
            p, b = usage_by_id[row["player_id"]], board_rows[row["player_id"]]
            opponent = g["home_team"] if p["team"] == g["away_team"] else g["away_team"]
            require(all(row[k] == v for k, v in p.items()) and (row["game_id"], row["team"], row["position"], row["opponent"], row["v5_probability_pct"]) == (b["game_id"], b["team"], b["position"], b["opponent"], b["td_estimate"]) and row["opponent"] == opponent, "V5 probability or identity changed")
            off, defense = g["offenses"][p["team"]], g["defenses"][opponent]
            label, reasons, dp, lp = designation(p, off, defense, defense["league"], known)
            require((row["advantage"], row["explanation"], row["defense_position"], row["league_position"], row["offense_games"], row["defense_games"]) == (label, reasons, dp, lp, off["recent"]["games"], defense["recent"]["games"]), "Unsupported or inconsistent matchup designation")
    return artifact
