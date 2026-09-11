import argparse
import os
import sys

import numpy as np
import pandas as pd
import nflreadpy


# ============================================================
# NFL TD PREDICTOR V5
# Fixes vs V4:
#   1. Recency weighting now sorted by (season, week), not week alone
#   2. model_source_weight is actually applied (was dead code in V4)
#   3. Real red-zone opportunity pulled from play-by-play, replacing
#      the season_tds/games proxy that duplicated efficiency_score
#   4. Opportunity/role percentiles computed WITHIN position group
#   5. Matchup split into pass-defense vs rush-defense allowed
# ============================================================

POSITIONS = {"RB", "FB", "WR", "TE"}

WEIGHTS = {
    # v4 -- rebuilt from correlation evidence averaged across BOTH the
    # 2025 and 2024 backtests, not from the logistic regression
    # suggestion. The regression output swung wildly between seasons
    # (role_score: 0.000 -> 0.461, opportunity: 0.650 -> 0.181) because
    # role_score and opportunity_score are collinear by construction --
    # that instability is a red flag about the regression, not a real
    # shift in what matters. role dropped to 0 here rather than chasing
    # an unstable coefficient.
    #
    # matchup_score correlation went 0.016 -> 0.022 -> -0.007 across
    # three independent checks (including after tripling its data
    # sample via load_defense_history). A correlation flipping sign near
    # zero across seasons is the signature of no real signal, not
    # "needs more tuning" -- weight cut hard and left there on purpose.
    "opportunity": 0.36,
    "red_zone": 0.35,
    "efficiency": 0.24,
    "matchup": 0.02,
    "team_environment": 0.03,
    "role": 0.00,
}

RECENCY_WINDOW_GAMES = 10  # only last N games count toward "current form"


def to_pandas(df):
    if isinstance(df, pd.DataFrame):
        return df.copy()
    if hasattr(df, "to_pandas"):
        return df.to_pandas()
    try:
        return pd.DataFrame(df)
    except Exception:
        return pd.DataFrame(df.to_dicts())


def clean_num(series):
    return pd.to_numeric(series, errors="coerce").fillna(0)


def percentile_score(value, series, neutral=50):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 5:
        return neutral
    if value is None or pd.isna(value):
        return neutral
    return float((s <= value).mean() * 100)


def position_percentile(df, value_col, position_col="position"):
    """
    FIX #4: percentile-rank each player only against others at the
    SAME position, so RB raw-touch volume doesn't dominate WR/TE
    opportunity scores just because carries > targets numerically.
    """
    return df.groupby(position_col)[value_col].transform(
        lambda s: percentile_score_series(s)
    )


def percentile_score_series(s):
    s_num = pd.to_numeric(s, errors="coerce")
    ranked = s_num.rank(pct=True) * 100
    return ranked.fillna(50)


def weighted_recent_average(df, value_col, season_col="season", week_col="week",
                             source_weight_col="model_source_weight"):
    """
    FIX #1 + #2: sort chronologically by (season, week) so cross-season
    data doesn't interleave, keep only the last RECENCY_WINDOW_GAMES,
    and multiply in model_source_weight (current season > prior season)
    on top of the within-window recency ramp.
    """
    if df.empty:
        return 0.0

    temp = df.copy()
    temp[value_col] = clean_num(temp[value_col])
    temp[week_col] = clean_num(temp[week_col])
    if season_col not in temp.columns:
        temp[season_col] = 0
    temp[season_col] = clean_num(temp[season_col])

    temp = temp.sort_values([season_col, week_col])
    temp = temp.tail(RECENCY_WINDOW_GAMES)

    if source_weight_col not in temp.columns:
        temp[source_weight_col] = 1.0
    temp[source_weight_col] = pd.to_numeric(
        temp[source_weight_col], errors="coerce"
    ).fillna(1.0)

    n = len(temp)
    recency_ramp = [1.0 + (i / max(1, n - 1)) * 1.5 for i in range(n)]
    final_weights = temp[source_weight_col].values * recency_ramp

    if final_weights.sum() == 0:
        return 0.0

    return float((temp[value_col].values * final_weights).sum() / final_weights.sum())


def load_player_stats(seasons):
    print(f"Loading player statistics for: {seasons}")
    stats = nflreadpy.load_player_stats(seasons=seasons, summary_level="week")
    stats = to_pandas(stats)
    if stats.empty:
        raise RuntimeError("No player statistics were returned.")
    return stats


def load_multi_season_stats(seasons):
    """
    Loads several seasons of weekly player stats at once, for the
    player-lookup feature's 'career vs. this opponent' history. Missing
    an individual season (e.g. a data-source gap) doesn't kill the whole
    lookup -- it just narrows the history to whatever loaded.
    """
    frames = []
    for s in seasons:
        try:
            frames.append(load_player_stats([s]))
        except Exception as e:
            print(f"Could not load {s} for player lookup: {e}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def find_player_matches(stats, name_query):
    """Case-insensitive substring search over every player name in the loaded stats."""
    name_query = name_query.strip().lower()
    if not name_query or stats.empty:
        return pd.DataFrame(columns=["player_id", "player_display_name"])
    names = stats[["player_id", "player_display_name"]].copy()
    names["player_id"] = names["player_id"].astype(str)
    names["player_display_name"] = names["player_display_name"].fillna("").astype(str)
    matches = names[names["player_display_name"].str.lower().str.contains(name_query, regex=False)]
    return matches.drop_duplicates("player_id").sort_values("player_display_name")


def player_vs_opponent_report(stats, player_id, opponent_code):
    """
    Returns the searched player's full game log, split into:
      - every past game specifically against opponent_code
      - their last 5 games overall (recent form, any opponent)

    This is intentionally team-level only. Individual-defender coverage
    data (who specifically guarded them) isn't available in any free
    dataset -- see the JSN-vs-Gonzalez research earlier in this project
    for why that required manual search/reporting instead of a query.
    """
    p = stats[stats["player_id"].astype(str) == str(player_id)].copy()
    if p.empty:
        return None

    for col in ["targets", "carries", "receptions", "receiving_yards", "rushing_yards",
                "receiving_tds", "rushing_tds", "season", "week", "opponent_team"]:
        if col not in p.columns:
            p[col] = 0

    for col in ["targets", "carries", "receptions", "receiving_yards", "rushing_yards",
                "receiving_tds", "rushing_tds", "season", "week"]:
        p[col] = clean_num(p[col])

    p["tds"] = p["receiving_tds"] + p["rushing_tds"]
    p = p.sort_values(["season", "week"])

    vs_opponent = p[p["opponent_team"].astype(str).str.upper() == str(opponent_code).upper()].copy()
    recent = p.tail(5).copy()

    return {
        "vs_opponent_games": vs_opponent,
        "recent_games": recent,
        "career_games_in_sample": len(p),
    }


def load_defense_history(season, lookback_seasons=3):
    """
    Pulls multiple PAST seasons (not including the current in-progress
    one) specifically for defensive matchup stability. build_defensive_
    matchups() was previously fed only ~1.5 seasons of data (prior season
    + partial current season), which the backtest showed produces a
    near-zero-signal matchup_score -- likely because 32 teams x ~17 games
    just isn't enough red-zone events to separate real defensive quality
    from noise. Pooling 3 prior seasons with recency decay (older seasons
    count less) gives a meaningfully larger, still recency-aware sample.
    """
    seasons = list(range(season - lookback_seasons, season))
    frames = []
    for s in seasons:
        try:
            df = load_player_stats([s])
        except Exception as e:
            print(f"Defense history: could not load {s}: {e}")
            continue
        years_ago = season - s
        df["model_source_weight"] = 0.6 ** years_ago  # more recent seasons weighted higher
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_redzone_opportunity(seasons):
    """
    FIX #3: pull actual red-zone (<=20 yd line) and end-zone (<=10 yd
    line) target/carry counts per player per game from play-by-play,
    instead of approximating red-zone involvement with season TD rate
    (which just duplicated efficiency_score).
    """
    print(f"Loading play-by-play for red-zone opportunity: {seasons}")
    pbp = to_pandas(nflreadpy.load_pbp(seasons=seasons))

    rz = pbp[
        (pbp["yardline_100"] <= 20)
        & (pbp["play_type"].isin(["pass", "run"]))
    ].copy()
    rz["is_endzone_shot"] = rz["yardline_100"] <= 10
    rz["opp_weight"] = 1.0
    rz.loc[rz["is_endzone_shot"], "opp_weight"] = 1.5

    rec = (
        rz.dropna(subset=["receiver_player_id"])
        .groupby(["receiver_player_id", "season", "week"])["opp_weight"]
        .sum().reset_index()
        .rename(columns={"receiver_player_id": "player_id"})
    )
    rush = (
        rz.dropna(subset=["rusher_player_id"])
        .groupby(["rusher_player_id", "season", "week"])["opp_weight"]
        .sum().reset_index()
        .rename(columns={"rusher_player_id": "player_id"})
    )
    combined = pd.concat([rec, rush]).groupby(
        ["player_id", "season", "week"], as_index=False
    )["opp_weight"].sum()
    combined = combined.rename(columns={"opp_weight": "redzone_opportunity"})
    return combined


def load_rosters(season):
    print(f"Loading {season} roster data...")
    try:
        rosters = to_pandas(nflreadpy.load_rosters(seasons=[season]))
        return rosters
    except Exception as e:
        print(f"Roster warning: {e}")
        return pd.DataFrame()


def load_schedule(season):
    print(f"Loading {season} schedule...")
    try:
        schedules = to_pandas(nflreadpy.load_schedules(seasons=[season]))
        return schedules
    except Exception as e:
        print(f"Schedule warning: {e}")
        return pd.DataFrame()


def load_injury_report(season, week):
    """
    Official team-submitted injury report (Out/Doubtful/Questionable/IR),
    same source ESPN and NFL.com use -- not derived from betting markets
    at all. This is the honest way to answer "is this player even live
    tonight," instead of inferring it from sportsbook prop availability.

    Note: this reflects the practice-week report (Wed/Thu/Fri designations
    plus final Friday status), which is normally the most current public
    info available at build time. It does NOT capture the official
    gameday-inactives list published ~90 minutes before kickoff -- there's
    no free structured feed for that; the printed Friday status is the
    closest free, legitimate proxy.
    """
    try:
        injuries = to_pandas(nflreadpy.load_injuries(seasons=[season]))
    except Exception as e:
        print(f"Injury report warning: {e}")
        return pd.DataFrame(columns=["player_id", "injury_status"])

    if injuries.empty:
        return pd.DataFrame(columns=["player_id", "injury_status"])

    if "week" in injuries.columns:
        injuries = injuries[pd.to_numeric(injuries["week"], errors="coerce") == week]

    id_col = next((c for c in ["player_id", "gsis_id", "nfl_id"] if c in injuries.columns), None)
    status_col = next((c for c in ["report_status", "game_status", "status"] if c in injuries.columns), None)

    if id_col is None or status_col is None:
        print(f"Injury report warning: unexpected columns {sorted(injuries.columns.tolist())}")
        return pd.DataFrame(columns=["player_id", "injury_status"])

    out = injuries[[id_col, status_col]].rename(
        columns={id_col: "player_id", status_col: "injury_status"}
    )
    out["player_id"] = out["player_id"].astype(str)
    out = out.dropna(subset=["injury_status"]).drop_duplicates("player_id", keep="last")
    return out


def normalize_rosters(rosters):
    if rosters.empty:
        return rosters
    name_col = None
    for col in ["player_display_name", "full_name", "player_name",
                "display_name", "football_name"]:
        if col in rosters.columns:
            name_col = col
            break
    rosters["model_player_name"] = (
        rosters[name_col].fillna("").astype(str).str.strip() if name_col else ""
    )
    # Roster tables in nflverse often key players by "gsis_id" while
    # player_stats keys by "player_id" -- they're the same value, just a
    # different column name. Check both instead of assuming one, or every
    # offseason team change (trades/free agency) silently fails to apply.
    id_col = None
    for col in ["player_id", "gsis_id", "nfl_id"]:
        if col in rosters.columns:
            id_col = col
            break
    if id_col is None:
        print("WARNING: no recognizable player ID column in roster data "
              f"(columns were: {sorted(rosters.columns.tolist())}); "
              "team updates from current rosters will not apply.")
        rosters["player_id"] = ""
    else:
        rosters["player_id"] = rosters[id_col].fillna("").astype(str)
    if "position" not in rosters.columns:
        rosters["position"] = ""
    if "team" not in rosters.columns:
        rosters["team"] = ""
    rosters["position"] = rosters["position"].fillna("").astype(str)
    rosters["team"] = rosters["team"].fillna("").astype(str)
    return rosters


def build_matchups(schedule, season, week):
    if schedule.empty:
        return {}
    required = {"week", "home_team", "away_team"}
    if not required.issubset(schedule.columns):
        print("Schedule missing expected columns:", sorted(schedule.columns.tolist()))
        return {}
    s = schedule.copy()
    s["week"] = pd.to_numeric(s["week"], errors="coerce")
    s = s[s["week"] == week]
    if "season_type" in s.columns:
        regular = s[s["season_type"].astype(str).str.lower().isin(
            ["reg", "regular", "regular season"])]
        if not regular.empty:
            s = regular
    matchups = {}
    for _, row in s.iterrows():
        home, away = str(row["home_team"]), str(row["away_team"])
        if home and away and home != "nan" and away != "nan":
            matchups[home] = away
            matchups[away] = home
    return matchups


def build_historical_player_profiles(stats, redzone):
    stats = stats.copy()

    required = ["player_id", "player_display_name", "position", "team", "season", "week",
                "targets", "carries", "receptions", "receiving_tds", "rushing_tds",
                "receiving_yards", "rushing_yards"]
    for col in required:
        if col not in stats.columns:
            stats[col] = 0

    numeric_cols = ["targets", "carries", "receptions", "receiving_tds", "rushing_tds",
                     "receiving_yards", "rushing_yards", "target_share", "week", "season"]
    for col in numeric_cols:
        if col not in stats.columns:
            stats[col] = 0
        stats[col] = clean_num(stats[col])

    stats["position"] = stats["position"].fillna("").astype(str)
    stats["team"] = stats["team"].fillna("").astype(str)
    stats = stats[stats["position"].isin(POSITIONS)].copy()
    if stats.empty:
        return pd.DataFrame()

    stats["opportunities"] = stats["targets"] + stats["carries"]
    stats["tds"] = stats["receiving_tds"] + stats["rushing_tds"]

    # merge in real red-zone opportunity per game (FIX #3)
    stats = stats.merge(redzone, on=["player_id", "season", "week"], how="left")
    stats["redzone_opportunity"] = stats["redzone_opportunity"].fillna(0)

    rows = []
    for player_id, group in stats.groupby("player_id", dropna=False):
        group = group.sort_values(["season", "week"])
        name = group["player_display_name"].iloc[-1]
        if not name or str(name) == "nan":
            continue
        position = group["position"].iloc[-1]
        team_counts = group["team"].value_counts()
        team = team_counts.index[0] if len(team_counts) else ""

        targets = weighted_recent_average(group, "targets")
        carries = weighted_recent_average(group, "carries")
        receptions = weighted_recent_average(group, "receptions")
        receiving_tds = weighted_recent_average(group, "receiving_tds")
        rushing_tds = weighted_recent_average(group, "rushing_tds")
        receiving_yards = weighted_recent_average(group, "receiving_yards")
        rushing_yards = weighted_recent_average(group, "rushing_yards")
        redzone_opp = weighted_recent_average(group, "redzone_opportunity")

        opportunities = targets + carries
        tds = receiving_tds + rushing_tds
        td_rate = tds / opportunities if opportunities > 0 else 0
        target_share = weighted_recent_average(group, "target_share") if "target_share" in group.columns else 0

        season_targets = clean_num(group["targets"]).sum()
        season_carries = clean_num(group["carries"]).sum()
        season_tds = clean_num(group["tds"]).sum()

        rows.append({
            "player_id": player_id, "player": str(name), "position": str(position), "team": str(team),
            "targets_pg": targets, "carries_pg": carries, "receptions_pg": receptions,
            "opportunities_pg": opportunities,
            "redzone_opportunity_pg": redzone_opp,
            "receiving_tds_pg": receiving_tds, "rushing_tds_pg": rushing_tds, "td_rate": td_rate,
            "receiving_yards_pg": receiving_yards, "rushing_yards_pg": rushing_yards,
            "target_share": target_share,
            "season_targets": season_targets, "season_carries": season_carries, "season_tds": season_tds,
            "games": len(group), "last_week": int(group["week"].max()),
        })

    return pd.DataFrame(rows)


def build_team_environment(stats):
    s = stats.copy()
    for col in ["passing_tds", "rushing_tds", "team"]:
        if col not in s.columns:
            s[col] = 0
    for col in ["passing_tds", "rushing_tds"]:
        s[col] = clean_num(s[col])
    s["offensive_tds"] = s["passing_tds"] + s["rushing_tds"]
    team = s.groupby("team")["offensive_tds"].sum().reset_index()
    return team.rename(columns={"offensive_tds": "offensive_td_total"})


def build_defensive_matchups(stats):
    """
    FIX #5: split TDs allowed into pass (receiving_tds) and rush
    (rushing_tds) buckets so a WR/TE matchup uses pass-D numbers and
    an RB matchup uses run-D numbers, instead of one blended figure.

    FIX (matchup accuracy): the raw pass_td_allowed/rush_td_allowed sums
    were computed but never actually turned into a RATE -- meaning a
    defense that faced 400 targets and allowed 20 TDs looked identical
    to one that faced 150 targets and allowed 20. That's almost
    certainly why backtest.py measured matchup_score's correlation with
    real scoring at 0.016 (pure noise). Now normalized to TDs allowed
    per opportunity faced, and recency-weighted via model_source_weight
    (current season counts more than prior season) same as the rest of
    the model already does for player-level stats.
    """
    s = stats.copy()
    for col in ["opponent_team", "receiving_tds", "rushing_tds", "targets", "carries"]:
        if col not in s.columns:
            s[col] = 0
    for col in ["receiving_tds", "rushing_tds", "targets", "carries"]:
        s[col] = clean_num(s[col])

    if "model_source_weight" not in s.columns:
        s["model_source_weight"] = 1.0
    s["model_source_weight"] = pd.to_numeric(s["model_source_weight"], errors="coerce").fillna(1.0)
    w = s["model_source_weight"]

    s["w_pass_td"] = s["receiving_tds"] * w
    s["w_rush_td"] = s["rushing_tds"] * w
    s["w_targets"] = s["targets"] * w
    s["w_carries"] = s["carries"] * w

    defense = s.groupby("opponent_team").agg(
        w_pass_td=("w_pass_td", "sum"),
        w_rush_td=("w_rush_td", "sum"),
        w_targets=("w_targets", "sum"),
        w_carries=("w_carries", "sum"),
        pass_td_allowed=("receiving_tds", "sum"),
        rush_td_allowed=("rushing_tds", "sum"),
        pass_opportunities_allowed=("targets", "sum"),
        rush_opportunities_allowed=("carries", "sum"),
    ).reset_index()

    # Rate = TDs allowed per opportunity faced, not raw count. This is
    # the actual fix -- a small-sample-safe TD rate instead of a count
    # that's really just measuring "how many games has this defense played."
    defense["pass_td_rate"] = defense["w_pass_td"] / defense["w_targets"].replace(0, pd.NA)
    defense["rush_td_rate"] = defense["w_rush_td"] / defense["w_carries"].replace(0, pd.NA)
    league_pass_avg = defense["pass_td_rate"].mean()
    league_rush_avg = defense["rush_td_rate"].mean()
    defense["pass_td_rate"] = defense["pass_td_rate"].fillna(league_pass_avg)
    defense["rush_td_rate"] = defense["rush_td_rate"].fillna(league_rush_avg)

    return defense.rename(columns={"opponent_team": "team"})


def build_role_scores(profiles):
    if profiles.empty:
        return profiles
    profiles = profiles.copy()
    opp_score = position_percentile(profiles, "opportunities_pg")
    target_score = position_percentile(profiles, "target_share")
    profiles["role_score"] = opp_score * 0.65 + target_score * 0.35
    return profiles


def score_players(profiles, team_environment, defensive_matchups):
    if profiles.empty:
        return profiles
    df = profiles.copy()

    # Opportunity: now position-relative (FIX #4)
    df["opportunity_score"] = position_percentile(df, "opportunities_pg")

    # Red zone: now real red-zone opportunity share, position-relative (FIX #3 + #4)
    df["red_zone_score"] = position_percentile(df, "redzone_opportunity_pg")

    # Efficiency unchanged conceptually
    df["efficiency_score"] = df["td_rate"].apply(lambda x: percentile_score(x, df["td_rate"]))

    # Matchup: now a real per-opportunity RATE, split by role
    pass_map = dict(zip(defensive_matchups["team"], defensive_matchups["pass_td_rate"]))
    rush_map = dict(zip(defensive_matchups["team"], defensive_matchups["rush_td_rate"]))

    def matchup_value(row):
        if row["position"] in ("WR", "TE"):
            return pass_map.get(row["opponent"], defensive_matchups["pass_td_rate"].median())
        return rush_map.get(row["opponent"], defensive_matchups["rush_td_rate"].median())

    df["opponent_td_allowed"] = df.apply(matchup_value, axis=1)

    def matchup_percentile(row):
        ref = (defensive_matchups["pass_td_rate"] if row["position"] in ("WR", "TE")
               else defensive_matchups["rush_td_rate"])
        return percentile_score(row["opponent_td_allowed"], ref)

    df["matchup_score"] = df.apply(matchup_percentile, axis=1)

    # Team environment unchanged
    team_td_map = dict(zip(team_environment["team"], team_environment["offensive_td_total"]))
    df["team_td_environment"] = df["team"].map(team_td_map).fillna(
        team_environment["offensive_td_total"].median() if not team_environment.empty else 0
    )
    df["team_environment_score"] = df["team_td_environment"].apply(
        lambda x: percentile_score(x, team_environment["offensive_td_total"])
    )

    df["role_score"] = df["role_score"].fillna(50)

    df["td_score"] = (
        df["opportunity_score"] * WEIGHTS["opportunity"]
        + df["red_zone_score"] * WEIGHTS["red_zone"]
        + df["efficiency_score"] * WEIGHTS["efficiency"]
        + df["matchup_score"] * WEIGHTS["matchup"]
        + df["team_environment_score"] * WEIGHTS["team_environment"]
        + df["role_score"] * WEIGHTS["role"]
    )

    # Injury penalty -- based on official team-submitted report, not
    # betting markets. "Out"/"IR"/"Doubtful" essentially zero the score
    # out (they may still get flipped to Active later in the week, at
    # which point rerunning the model picks that up automatically).
    # "Questionable" gets a moderate haircut since most Questionable
    # players do end up suiting up.
    if "injury_status" in df.columns:
        injury_multiplier = {
            "Out": 0.05, "IR": 0.0, "Injured Reserve": 0.0,
            "Doubtful": 0.15, "Questionable": 0.75,
        }
        df["injury_status"] = df["injury_status"].fillna("Active")
        df["td_score"] = df["td_score"] * df["injury_status"].map(injury_multiplier).fillna(1.0)

    # Calibrated against real 2025-season outcomes via backtest.py
    # (2025 wk2-18), refit after the opportunity-heavy reweighting above.
    # Re-run backtest.py after any future WEIGHTS change and update these
    # to match -- changing weights shifts the td_score distribution, so a
    # stale calibration curve will mislabel the percentage even if the
    # underlying ranking is still good.
    _CALIBRATION_SCORE_POINTS = [31, 33, 35, 40, 50, 60, 68, 76, 84, 97]
    _CALIBRATION_ACTUAL_PCT =   [0.28, 0.35, 0.07, 0.35, 1.34, 3.52, 5.76, 8.30, 16.32, 31.62]
    df["td_estimate"] = np.interp(
        df["td_score"], _CALIBRATION_SCORE_POINTS, _CALIBRATION_ACTUAL_PCT
    )

    return df


def inject_missing_roster_players(profiles, rosters, matchups):
    """
    Adds any skill-position player who's on a current roster for a team
    playing this week, but has zero rows in the historical stats (true
    rookies, or vets who just haven't played this specific stretch).
    Without this, players like a Week 1 rookie TE simply never appear in
    rankings at all -- not ranked low, just invisible.

    They're added with all-zero usage/efficiency numbers, which
    naturally sends their opportunity/red-zone/efficiency scores to the
    bottom of the percentile ranks (appropriately -- no track record
    means no demonstrated role). Their matchup_score and
    team_environment_score still compute normally off real team/opponent
    data, so they're not literally a flat zero -- just correctly
    low-confidence. The "games" column stays 0 so the UI can flag them
    as unproven/no-data rather than implying a real ranking.
    """
    if rosters.empty or not matchups:
        return profiles

    teams_playing = set(matchups.keys())
    pool = rosters[
        rosters["position"].isin(POSITIONS)
        & rosters["team"].isin(teams_playing)
        & (~rosters["player_id"].isin(["", "nan"]))
    ].copy()

    existing_ids = set(profiles["player_id"].astype(str))
    pool = pool[~pool["player_id"].astype(str).isin(existing_ids)]
    pool = pool.drop_duplicates("player_id")

    new_rows = []
    for _, r in pool.iterrows():
        name = str(r.get("model_player_name", "")).strip()
        if not name or name == "nan":
            continue
        new_rows.append({
            "player_id": str(r["player_id"]), "player": name,
            "position": str(r["position"]), "team": str(r["team"]),
            "targets_pg": 0.0, "carries_pg": 0.0, "receptions_pg": 0.0,
            "opportunities_pg": 0.0, "redzone_opportunity_pg": 0.0,
            "receiving_tds_pg": 0.0, "rushing_tds_pg": 0.0, "td_rate": 0.0,
            "receiving_yards_pg": 0.0, "rushing_yards_pg": 0.0, "target_share": 0.0,
            "season_targets": 0.0, "season_carries": 0.0, "season_tds": 0.0,
            "games": 0, "last_week": 0,
        })

    if not new_rows:
        return profiles

    return pd.concat([profiles, pd.DataFrame(new_rows)], ignore_index=True)


def print_rankings(df, top):
    print(f"{'RK':<4}{'PLAYER':<24}{'TM':<5}{'POS':<5}{'OPP':<5}{'SCORE':>8}{'EST. TD%':>10}")
    print("-" * 78)
    for rank, (_, row) in enumerate(df.head(top).iterrows(), start=1):
        print(f"{rank:<4}{row['player'][:23]:<24}{row['team']:<5}{row['position']:<5}"
              f"{row['opponent']:<5}{row['td_score']:>8.2f}{row['td_estimate']:>9.1f}%")
    print()


def get_predictions(season, week, status_callback=None):
    """
    Runs the full pipeline and returns (scored_df, matchups_dict).
    Reusable by the CLI (main, below) and by the Streamlit app --
    all the print() calls in the original main() became optional
    status_callback() calls so a UI can show progress instead of
    a terminal log.
    """
    def status(msg):
        print(msg)
        if status_callback:
            status_callback(msg)

    if week < 1 or week > 18:
        raise ValueError("Week must be between 1 and 18.")

    previous_season = season - 1
    historical = load_player_stats([previous_season])
    historical["model_source_weight"] = 0.65

    current = pd.DataFrame()
    if week > 1:
        try:
            current = load_player_stats([season])
            current = current[pd.to_numeric(current["week"], errors="coerce") < week].copy()
            current["model_source_weight"] = 1.0  # FIX #2: current season now actually weighted higher
        except Exception as e:
            status(f"Current-season stats unavailable: {e}")

    all_stats = pd.concat([historical, current], ignore_index=True) if not current.empty else historical.copy()

    seasons_needed = [previous_season] + ([season] if not current.empty else [])
    status("Loading red-zone opportunity data...")
    redzone = load_redzone_opportunity(seasons_needed)

    status("Loading rosters and schedule...")
    rosters = normalize_rosters(load_rosters(season))
    schedule = load_schedule(season)
    matchups = build_matchups(schedule, season, week)
    if not matchups:
        status(f"WARNING: Could not identify {season} Week {week} matchups from the schedule.")

    status("Building player profiles...")
    profiles = build_historical_player_profiles(all_stats, redzone)
    if profiles.empty:
        raise RuntimeError("No skill-position player profiles could be built.")

    if not rosters.empty:
        roster_lookup = {
            str(r["player_id"]): {"team": str(r.get("team", "")), "position": str(r.get("position", ""))}
            for _, r in rosters.iterrows() if str(r.get("player_id", "")) not in ("", "nan")
        }

        def update_roster(row):
            pid = str(row["player_id"])
            if pid in roster_lookup:
                nt, npos = roster_lookup[pid]["team"], roster_lookup[pid]["position"]
                if nt and nt != "nan":
                    row["team"] = nt
                if npos in POSITIONS:
                    row["position"] = npos
            return row

        profiles = profiles.apply(update_roster, axis=1)

    profiles = inject_missing_roster_players(profiles, rosters, matchups)

    status("Loading injury report...")
    injuries = load_injury_report(season, week)
    profiles["player_id"] = profiles["player_id"].astype(str)
    profiles = profiles.merge(injuries, on="player_id", how="left")
    profiles["injury_status"] = profiles["injury_status"].fillna("Active")

    profiles["opponent"] = profiles["team"].map(matchups)
    profiles = profiles[profiles["opponent"].notna()].copy()
    profiles = profiles[profiles["position"].isin(POSITIONS)].copy()

    team_environment = build_team_environment(all_stats)

    status("Loading multi-season defensive history...")
    defense_history = load_defense_history(season, lookback_seasons=3)
    if not current.empty:
        current_for_defense = current.copy()
        current_for_defense["model_source_weight"] = 1.0  # this season's games count fully
        defense_history = pd.concat([defense_history, current_for_defense], ignore_index=True)
    defensive_matchups = build_defensive_matchups(
        defense_history if not defense_history.empty else all_stats
    )

    profiles = build_role_scores(profiles)

    status("Scoring players...")
    scored = score_players(profiles, team_environment, defensive_matchups)
    if scored.empty:
        raise RuntimeError("No players could be scored.")

    scored = scored.sort_values("td_score", ascending=False).reset_index(drop=True)
    status("Done.")
    return scored, matchups


def main():
    parser = argparse.ArgumentParser(description="NFL TD Likelihood Predictor V5")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--teams", type=str, default=None,
                         help="Comma-separated team codes to filter to, e.g. SF,LA")
    args = parser.parse_args()

    try:
        scored, matchups = get_predictions(args.season, args.week)
    except (ValueError, RuntimeError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print_rankings(scored, args.top)

    output_path = os.path.join(os.getcwd(), f"td_scores_{args.season}_week{args.week}.csv")
    scored.to_csv(output_path, index=False)
    print(f"Saved results to: {output_path}")
    print("IMPORTANT: TD Estimate is a model estimate, not a calibrated probability.")

    if args.teams:
        wanted = set(t.strip().upper() for t in args.teams.split(","))
        tonight = scored[scored["team"].isin(wanted)].sort_values("td_score", ascending=False)
        print(f"\nFiltered to: {'/'.join(sorted(wanted))}\n")
        print_rankings(tonight, len(tonight))


if __name__ == "__main__":
    main()