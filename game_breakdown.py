"""
GAME BREAKDOWN — a display-only scouting report for a single game.

This is deliberately SEPARATE from the scoring model. Nothing in here
touches td_score, the fitted model, WEIGHTS, or the rankings. It exists
so you can read the hard numbers behind a matchup and apply your own
judgment -- the same division of labor as the rest of this tool.

What it builds, all from free nflverse data (no odds, no market data):
  * Team scoring profile: how each offense scores and how each defense
    gets scored on (rush TDs, pass TDs, red-zone TD%, yards per carry)
    next to a league average for the same window.
  * Player usage by position group (RB / WR / TE / QB): carries,
    targets, red-zone and goal-line opportunities, how many of those
    became TDs, share of the team's red-zone work, first-TD history.
  * Injury impact: flagged players and how much usage they carry.
  * "Stats that stand out": automatic flags using simple thresholds and
    minimum sample sizes. These are prompts for your judgment, not
    model output.

SAMPLE-SIZE HONESTY: the default window is each team's last 6 games.
Red-zone counts over 6 games are small numbers. Every table shows the
games and opportunity counts so you can see how much weight a number
can bear. Early in a season the window reaches back into last season
(regular season only); the app tells you how many games came from there.
"""

import argparse

import numpy as np
import pandas as pd
import nflreadpy

from td_predictor_v5 import to_pandas, load_schedule, load_injury_report

PBP_COLUMNS = [
    "game_id", "season", "week", "season_type", "play_id", "drive",
    "posteam", "defteam", "play_type", "yardline_100", "yards_gained",
    "touchdown", "td_team", "td_player_id", "rush_touchdown", "pass_touchdown",
    "rusher_player_id", "receiver_player_id", "two_point_attempt",
]

POSITION_GROUPS = {"QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "WR": "WR", "TE": "TE"}
GROUP_ORDER = ["RB", "WR", "TE", "QB"]
GROUP_LIMITS = {"RB": 5, "WR": 6, "TE": 4, "QB": 2}
FLAG_STATUSES = {"out", "doubtful", "questionable", "ir", "injured reserve"}


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def _select_columns(raw, wanted):
    """Keep only the columns we need BEFORE converting to pandas (memory)."""
    keep = [c for c in wanted if c in list(raw.columns)]
    if hasattr(raw, "select") and not isinstance(raw, pd.DataFrame):
        return raw.select(keep)  # polars
    return raw[keep]


def _num(df, cols):
    for c in cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df


def load_pbp_slim(seasons):
    frames = []
    for s in seasons:
        try:
            raw = nflreadpy.load_pbp(seasons=[s])
        except Exception as e:
            print(f"Could not load play-by-play for {s}: {e}")
            continue
        frames.append(to_pandas(_select_columns(raw, PBP_COLUMNS)))
    if not frames:
        raise RuntimeError("No play-by-play data could be loaded.")
    pbp = pd.concat(frames, ignore_index=True)
    if "season_type" in pbp.columns:
        pbp = pbp[pbp["season_type"].astype(str).str.upper() == "REG"]
    # 2-point tries are tagged as ordinary run/pass plays from the 2-yard
    # line. Left in, they'd pad goal-line "opportunities" with plays that
    # aren't touchdown chances (a successful try is not a TD).
    if "two_point_attempt" in pbp.columns:
        pbp = pbp[pd.to_numeric(pbp["two_point_attempt"], errors="coerce").fillna(0) == 0]
    pbp["posteam"] = pbp["posteam"].astype(str)
    pbp["game_id"] = pbp["game_id"].astype(str)
    return pbp


def load_player_info(seasons):
    """player_id -> display name, position, position group (latest known)."""
    raw = nflreadpy.load_player_stats(seasons=seasons, summary_level="week")
    slim = to_pandas(_select_columns(
        raw, ["player_id", "player_display_name", "position", "season", "week"]))
    slim = _num(slim, ["season", "week"])
    slim["player_id"] = slim["player_id"].astype(str)
    slim = slim.sort_values(["season", "week"]).drop_duplicates("player_id", keep="last")
    slim["group"] = slim["position"].astype(str).map(POSITION_GROUPS)
    slim["player_display_name"] = slim["player_display_name"].fillna("").astype(str)
    return slim.set_index("player_id")


def load_schedules(seasons):
    frames = []
    for s in seasons:
        df = load_schedule(s)
        if df is not None and not df.empty:
            if "season" not in df.columns:
                df["season"] = s
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def list_week_games(season, week):
    """(away, home) pairs for the dropdown."""
    sched = load_schedule(season)
    if sched.empty:
        return []
    s = sched[pd.to_numeric(sched["week"], errors="coerce") == week]
    if "game_type" in s.columns:
        reg = s[s["game_type"].astype(str).str.upper() == "REG"]
        if not reg.empty:
            s = reg
    return [(str(r.away_team), str(r.home_team)) for r in s.itertuples()]


# ---------------------------------------------------------------------------
# Windows: each team's last N completed regular-season games before this week
# ---------------------------------------------------------------------------

def build_team_games(schedule):
    s = schedule.copy()
    s = _num(s, ["season", "week"])
    if "game_type" in s.columns:
        s = s[s["game_type"].astype(str).str.upper() == "REG"]
    if "game_id" not in s.columns:
        s["game_id"] = (s["season"].astype(int).astype(str) + "_"
                        + s["week"].astype(int).astype(str).str.zfill(2) + "_"
                        + s["away_team"].astype(str) + "_" + s["home_team"].astype(str))
    s["game_id"] = s["game_id"].astype(str)
    s = s.dropna(subset=["home_score", "away_score"])  # completed games only

    cols = ["game_id", "season", "week"]
    home = s[cols + ["home_team", "away_team", "home_score", "away_score"]].rename(columns={
        "home_team": "team", "away_team": "opponent",
        "home_score": "points_for", "away_score": "points_against"})
    away = s[cols + ["away_team", "home_team", "away_score", "home_score"]].rename(columns={
        "away_team": "team", "home_team": "opponent",
        "away_score": "points_for", "home_score": "points_against"})
    tg = pd.concat([home, away], ignore_index=True)
    tg["team"] = tg["team"].astype(str)
    tg["opponent"] = tg["opponent"].astype(str)
    return tg.sort_values(["team", "season", "week"]).reset_index(drop=True)


def team_windows(team_games, season, week, lookback):
    before = (team_games["season"] < season) | (
        (team_games["season"] == season) & (team_games["week"] < week))
    tg = team_games[before].sort_values(["team", "season", "week"]).copy()
    tg["recency_rank"] = tg.groupby("team").cumcount(ascending=False)  # 0 = latest
    return tg[tg["recency_rank"] < lookback].copy()


# ---------------------------------------------------------------------------
# Team scoring profile (offense and what each defense allows)
# ---------------------------------------------------------------------------

def per_game_team_metrics(pbp, window):
    ids = set(window["game_id"])
    p = pbp[pbp["game_id"].isin(ids) & pbp["play_type"].isin(["pass", "run"])].copy()
    p = _num(p, ["touchdown", "rush_touchdown", "pass_touchdown", "yardline_100", "yards_gained"])

    off_td = (p["touchdown"] == 1) & (p["td_team"].astype(str) == p["posteam"])
    p["is_rush_td"] = off_td & (p["rush_touchdown"] == 1)
    p["is_pass_td"] = off_td & (p["pass_touchdown"] == 1)
    p["is_off_td"] = p["is_rush_td"] | p["is_pass_td"]
    p["is_rz"] = p["yardline_100"] <= 20
    p["is_run"] = p["play_type"] == "run"
    p["run_yards"] = np.where(p["is_run"], p["yards_gained"], 0)

    base = p.groupby(["game_id", "posteam"]).agg(
        rush_td=("is_rush_td", "sum"), pass_td=("is_pass_td", "sum"),
        rush_att=("is_run", "sum"), rush_yds=("run_yards", "sum"),
    ).reset_index()

    drives = p.dropna(subset=["drive"]).groupby(["game_id", "posteam", "drive"]).agg(
        rz=("is_rz", "max"), td=("is_off_td", "max")).reset_index()
    drives["rz_trip"] = drives["rz"].astype(bool)
    drives["rz_td"] = drives["rz_trip"] & drives["td"].astype(bool)
    rz = drives.groupby(["game_id", "posteam"]).agg(
        rz_trips=("rz_trip", "sum"), rz_tds=("rz_td", "sum")).reset_index()

    off = base.merge(rz, on=["game_id", "posteam"], how="left").fillna(0)
    off = off.rename(columns={"posteam": "team"})

    mine = window[["game_id", "team", "opponent", "points_for", "points_against"]].merge(
        off, on=["game_id", "team"], how="left")
    theirs = off.rename(columns={
        "team": "opponent", "rush_td": "opp_rush_td", "pass_td": "opp_pass_td",
        "rush_att": "opp_rush_att", "rush_yds": "opp_rush_yds",
        "rz_trips": "opp_rz_trips", "rz_tds": "opp_rz_tds"})
    out = mine.merge(theirs, on=["game_id", "opponent"], how="left")
    num_cols = [c for c in out.columns if c not in ("game_id", "team", "opponent")]
    out[num_cols] = out[num_cols].fillna(0)
    return out


def aggregate_team_profile(per_game):
    g = per_game.groupby("team")

    def ratio(num, den, scale=1.0):
        return (g[num].sum() / g[den].sum().replace(0, np.nan)) * scale

    return pd.DataFrame({
        "games": g.size(),
        "ppg": g["points_for"].mean(),
        "rush_td_pg": g["rush_td"].mean(),
        "pass_td_pg": g["pass_td"].mean(),
        "rz_trips_pg": g["rz_trips"].mean(),
        "rz_td_pct": ratio("rz_tds", "rz_trips", 100),
        "papg": g["points_against"].mean(),
        "def_rush_td_pg": g["opp_rush_td"].mean(),
        "def_pass_td_pg": g["opp_pass_td"].mean(),
        "def_rush_yds_pg": g["opp_rush_yds"].mean(),
        "def_ypc": ratio("opp_rush_yds", "opp_rush_att"),
        "def_rz_td_pct": ratio("opp_rz_tds", "opp_rz_trips", 100),
    })


def profile_tables(profile, teams):
    league = profile.mean(numeric_only=True)
    offense_rows = [
        ("Points per game", "ppg"), ("Rush TD per game", "rush_td_pg"),
        ("Pass TD per game", "pass_td_pg"), ("Red-zone trips per game", "rz_trips_pg"),
        ("Red-zone TD %", "rz_td_pct")]
    defense_rows = [
        ("Points allowed per game", "papg"), ("Rush TD allowed per game", "def_rush_td_pg"),
        ("Pass TD allowed per game", "def_pass_td_pg"),
        ("Rush yards allowed per game", "def_rush_yds_pg"),
        ("Yards per carry allowed", "def_ypc"), ("Red-zone TD % allowed", "def_rz_td_pct")]

    def build(rows):
        data = {"Metric": [label for label, _ in rows]}
        for t in teams:
            data[t] = [round(float(profile.loc[t, key]), 2) if t in profile.index else None
                       for _, key in rows]
        data["League avg"] = [round(float(league[key]), 2) for _, key in rows]
        return pd.DataFrame(data)

    return build(offense_rows), build(defense_rows)


# ---------------------------------------------------------------------------
# First offensive TD history (rush/receiving TDs only; defensive/ST TDs ignored)
# ---------------------------------------------------------------------------

def first_offensive_td_counts(pbp):
    p = pbp[pbp["play_type"].isin(["pass", "run"])].copy()
    p = _num(p, ["touchdown", "rush_touchdown", "pass_touchdown", "play_id"])
    is_td = ((p["touchdown"] == 1) & (p["td_team"].astype(str) == p["posteam"])
             & ((p["rush_touchdown"] == 1) | (p["pass_touchdown"] == 1))
             & p["td_player_id"].notna())
    first = p[is_td].sort_values(["game_id", "play_id"]).drop_duplicates("game_id", keep="first")
    return first["td_player_id"].astype(str).value_counts()


# ---------------------------------------------------------------------------
# Player usage by position group
# ---------------------------------------------------------------------------

def build_player_frames(pbp, window, team, info, injury_by_id, injury_by_name, first_td):
    ids = set(window.loc[window["team"] == team, "game_id"])
    p = pbp[pbp["game_id"].isin(ids) & (pbp["posteam"] == team)
            & pbp["play_type"].isin(["pass", "run"])].copy()
    p = _num(p, ["touchdown", "rush_touchdown", "pass_touchdown", "yardline_100"])
    p["is_rz"] = (p["yardline_100"] <= 20).astype(int)
    p["is_gl"] = (p["yardline_100"] <= 5).astype(int)
    scored = (p["touchdown"] == 1) & (p["td_team"].astype(str) == p["posteam"])

    r = p[(p["play_type"] == "run") & p["rusher_player_id"].notna()].copy()
    r["td"] = (scored.loc[r.index] & (r["rush_touchdown"] == 1)).astype(int)
    r["rz_td"] = r["td"] * r["is_rz"]
    r["gl_td"] = r["td"] * r["is_gl"]
    rush = r.groupby(r["rusher_player_id"].astype(str)).agg(
        carries=("td", "size"), rz_carries=("is_rz", "sum"), gl_carries=("is_gl", "sum"),
        rush_td=("td", "sum"), rz_td_r=("rz_td", "sum"), gl_td_r=("gl_td", "sum"))

    t = p[(p["play_type"] == "pass") & p["receiver_player_id"].notna()].copy()
    t["td"] = (scored.loc[t.index] & (t["pass_touchdown"] == 1)).astype(int)
    t["rz_td"] = t["td"] * t["is_rz"]
    t["gl_td"] = t["td"] * t["is_gl"]
    rec = t.groupby(t["receiver_player_id"].astype(str)).agg(
        targets=("td", "size"), rz_targets=("is_rz", "sum"), gl_targets=("is_gl", "sum"),
        rec_td=("td", "sum"), rz_td_t=("rz_td", "sum"), gl_td_t=("gl_td", "sum"))

    pairs = pd.concat([
        pd.DataFrame({"pid": r["rusher_player_id"].astype(str), "game_id": r["game_id"]}),
        pd.DataFrame({"pid": t["receiver_player_id"].astype(str), "game_id": t["game_id"]}),
    ]).drop_duplicates()
    games = pairs.groupby("pid").size().rename("games")

    u = rush.join(rec, how="outer").join(games, how="left").fillna(0)
    u["rz_opps"] = u["rz_carries"] + u["rz_targets"]
    u["rz_tds"] = u["rz_td_r"] + u["rz_td_t"]
    u["gl_opps"] = u["gl_carries"] + u["gl_targets"]
    u["gl_tds"] = u["gl_td_r"] + u["gl_td_t"]
    u["tds"] = u["rush_td"] + u["rec_td"]
    u["team_rz_carries"] = float(rush["rz_carries"].sum()) if len(rush) else 0.0
    u["team_rz_targets"] = float(rec["rz_targets"].sum()) if len(rec) else 0.0

    u["name"] = [info["player_display_name"].get(pid, "") or pid for pid in u.index]
    u["group"] = [info["group"].get(pid, None) for pid in u.index]
    u = u[u["group"].notna()].copy()
    u["first_td"] = [int(first_td.get(pid, 0)) for pid in u.index]

    def status_for(pid, name):
        s = injury_by_id.get(pid) or injury_by_name.get(str(name).strip().lower())
        return s if isinstance(s, str) and s.strip() else "Active"
    u["status"] = [status_for(pid, nm) for pid, nm in zip(u.index, u["name"])]

    keep = (u["carries"] + u["targets"] >= 5) | (u["rz_opps"] >= 1) | (u["tds"] >= 1)
    return u[keep].copy()


def _group_view(u, group):
    d = u[u["group"] == group].copy()
    if d.empty:
        return pd.DataFrame()
    uses_carries = group in ("RB", "QB")
    team_total = d["team_rz_carries"] if uses_carries else d["team_rz_targets"]
    own = d["rz_carries"] if uses_carries else d["rz_targets"]
    d["rz_share"] = np.where(team_total > 0, own / team_total.replace(0, np.nan) * 100, np.nan)

    games = d["games"].replace(0, np.nan)
    out = pd.DataFrame({
        "Player": d["name"], "G": d["games"].astype(int),
        "Car/g": (d["carries"] / games).round(1), "Tgt/g": (d["targets"] / games).round(1),
        "RZ opps": d["rz_opps"].astype(int), "RZ TD": d["rz_tds"].astype(int),
        "RZ conv %": np.where(d["rz_opps"] > 0, d["rz_tds"] / d["rz_opps"].replace(0, np.nan) * 100, np.nan),
        "GL opps": d["gl_opps"].astype(int), "GL TD": d["gl_tds"].astype(int),
        "RZ share %": d["rz_share"], "TDs": d["tds"].astype(int),
        "1st TD (2 yrs)": d["first_td"], "Status": d["status"],
    })
    out["RZ conv %"] = out["RZ conv %"].round(0)
    out["RZ share %"] = out["RZ share %"].round(0)
    sort_key = d["carries"] if group == "QB" else d["rz_opps"] * 100 + d["tds"] * 10 + d["carries"] + d["targets"]
    out = out.loc[sort_key.sort_values(ascending=False).index]
    return out.head(GROUP_LIMITS[group]).reset_index(drop=True)


def injury_view(u):
    d = u[u["status"].astype(str).str.lower().isin(FLAG_STATUSES)].copy()
    if d.empty:
        return pd.DataFrame()
    games = d["games"].replace(0, np.nan)
    team_opps = (d["team_rz_carries"] + d["team_rz_targets"]).replace(0, np.nan)
    return pd.DataFrame({
        "Player": d["name"], "Pos": d["group"], "Status": d["status"],
        "Car/g": (d["carries"] / games).round(1), "Tgt/g": (d["targets"] / games).round(1),
        "RZ opps": d["rz_opps"].astype(int),
        "Share of team RZ opps %": (d["rz_opps"] / team_opps * 100).round(0),
    }).sort_values("RZ opps", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Automatic "stands out" flags -- simple thresholds with sample-size guards
# ---------------------------------------------------------------------------

def build_flags(teams, frames, profile):
    league = profile.mean(numeric_only=True)
    flags = []

    for t in teams:
        if t in profile.index:
            row = profile.loc[t]
            n = int(row["games"])
            if n >= 3:
                if row["def_rush_td_pg"] <= 0.5 * league["def_rush_td_pg"]:
                    flags.append(f"🛡️ {t}'s defense has allowed just {row['def_rush_td_pg']:.2f} rushing "
                                 f"TDs/game over {n} games (league avg {league['def_rush_td_pg']:.2f}) — "
                                 f"ground scoring against them has been hard.")
                elif row["def_rush_td_pg"] >= 1.25 * league["def_rush_td_pg"]:
                    flags.append(f"🏃 {t}'s defense has allowed {row['def_rush_td_pg']:.2f} rushing "
                                 f"TDs/game over {n} games (league avg {league['def_rush_td_pg']:.2f}).")
                if row["def_pass_td_pg"] >= 1.25 * league["def_pass_td_pg"]:
                    flags.append(f"🎯 {t}'s defense has allowed {row['def_pass_td_pg']:.2f} passing "
                                 f"TDs/game over {n} games (league avg {league['def_pass_td_pg']:.2f}).")
                elif row["def_pass_td_pg"] <= 0.5 * league["def_pass_td_pg"]:
                    flags.append(f"🛡️ {t}'s defense has allowed just {row['def_pass_td_pg']:.2f} passing "
                                 f"TDs/game over {n} games (league avg {league['def_pass_td_pg']:.2f}).")
                if pd.notna(row["rz_td_pct"]) and row["rz_td_pct"] >= league["rz_td_pct"] + 10:
                    flags.append(f"🔥 {t} turns {row['rz_td_pct']:.0f}% of red-zone trips into TDs "
                                 f"(league avg {league['rz_td_pct']:.0f}%).")
                elif pd.notna(row["rz_td_pct"]) and row["rz_td_pct"] <= league["rz_td_pct"] - 10:
                    flags.append(f"🧊 {t} turns only {row['rz_td_pct']:.0f}% of red-zone trips into TDs "
                                 f"(league avg {league['rz_td_pct']:.0f}%) — drives often end in field goals.")

        u = frames.get(t)
        if u is None or u.empty:
            continue
        for pid, p in u.iterrows():
            nm, g = p["name"], int(p["games"])
            if p["rz_opps"] >= 4 and p["rz_tds"] / p["rz_opps"] >= 0.5:
                flags.append(f"✅ {nm} ({t}) has scored on {int(p['rz_tds'])} of {int(p['rz_opps'])} "
                             f"red-zone opportunities ({p['rz_tds'] / p['rz_opps'] * 100:.0f}%) over {g} games.")
            elif p["rz_opps"] >= 6 and p["rz_tds"] == 0:
                flags.append(f"⚠️ {nm} ({t}) has {int(p['rz_opps'])} red-zone opportunities and no TDs "
                             f"over {g} games.")
            if p["group"] in ("RB", "QB") and p["team_rz_carries"] >= 6:
                share = p["rz_carries"] / p["team_rz_carries"]
                if share >= 0.6 and p["rz_carries"] >= 4:
                    flags.append(f"💪 {nm} holds {share * 100:.0f}% of {t}'s red-zone carries "
                                 f"({int(p['rz_carries'])} of {int(p['team_rz_carries'])}).")
            if p["group"] in ("WR", "TE") and p["team_rz_targets"] >= 8:
                share = p["rz_targets"] / p["team_rz_targets"]
                if share >= 0.25 and p["rz_targets"] >= 3:
                    flags.append(f"📡 {nm} has {share * 100:.0f}% of {t}'s red-zone targets "
                                 f"({int(p['rz_targets'])} of {int(p['team_rz_targets'])}).")
            if p["first_td"] >= 3:
                flags.append(f"🥇 {nm} ({t}) has scored the game's first offensive TD "
                             f"{int(p['first_td'])} times over the last two seasons.")
            if str(p["status"]).lower() in FLAG_STATUSES:
                total = p["team_rz_carries"] + p["team_rz_targets"]
                if total > 0 and p["rz_opps"] / total >= 0.15:
                    flags.append(f"🩹 {nm} ({t}, {p['status']}) accounts for "
                                 f"{p['rz_opps'] / total * 100:.0f}% of {t}'s red-zone opportunities.")
    return flags


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_breakdown_context(season, week, lookback_games=6, status=print, require_teams=None):
    """
    The heavy, league-wide part of a breakdown: schedules, play-by-play,
    team profiles, player info, first-TD history, injuries. Done ONCE so
    that many games can be built from it (the website export builds every
    game of a week from a single load instead of reloading two seasons of
    play-by-play per game).

    require_teams: fail fast (before the slow play-by-play load) if any of
    these teams has no completed games before this week.
    """
    prior = season - 1

    status("Loading schedules...")
    schedule = load_schedules([prior, season])
    if schedule.empty:
        raise RuntimeError("Could not load schedules.")
    team_games = build_team_games(schedule)
    window = team_windows(team_games, season, week, lookback_games)
    for t in (require_teams or []):
        if window[window["team"] == t].empty:
            raise RuntimeError(f"No completed games found for {t} before week {week}.")

    status("Loading play-by-play (this is the slow step)...")
    pbp = load_pbp_slim([prior, season])

    status("Computing team profiles...")
    per_game = per_game_team_metrics(pbp, window)
    profile = aggregate_team_profile(per_game)

    status("Computing player usage...")
    info = load_player_info([prior, season])
    first_td = first_offensive_td_counts(pbp)

    injuries = load_injury_report(season, week)
    injury_by_id, injury_by_name = {}, {}
    if injuries is not None and not injuries.empty:
        if "player_id" in injuries.columns:
            injury_by_id = dict(zip(injuries["player_id"].astype(str), injuries["injury_status"]))
        if "player_name" in injuries.columns:
            injury_by_name = dict(zip(injuries["player_name"].astype(str).str.lower(),
                                      injuries["injury_status"]))

    return {
        "season": season, "week": week, "lookback": lookback_games,
        "window": window, "pbp": pbp, "profile": profile, "info": info,
        "first_td": first_td, "injury_by_id": injury_by_id, "injury_by_name": injury_by_name,
    }


def build_game_from_context(ctx, away_team, home_team):
    """Cheap per-game step once the context is loaded."""
    teams = [away_team, home_team]
    window, season = ctx["window"], ctx["season"]
    for t in teams:
        if window[window["team"] == t].empty:
            raise RuntimeError(f"No completed games found for {t} before week {ctx['week']}.")

    offense_tbl, defense_tbl = profile_tables(ctx["profile"], teams)

    frames = {t: build_player_frames(ctx["pbp"], window, t, ctx["info"], ctx["injury_by_id"],
                                     ctx["injury_by_name"], ctx["first_td"])
              for t in teams}

    players = {t: {g: _group_view(frames[t], g) for g in GROUP_ORDER} for t in teams}
    injury_tables = {t: injury_view(frames[t]) for t in teams}
    flags = build_flags(teams, frames, ctx["profile"])

    games_used = {t: int((window["team"] == t).sum()) for t in teams}
    prior_games = {t: int(((window["team"] == t) & (window["season"] < season)).sum()) for t in teams}

    return {
        "teams": teams, "offense": offense_tbl, "defense": defense_tbl,
        "players": players, "injuries": injury_tables, "flags": flags,
        "meta": {"games_used": games_used, "prior_season_games": prior_games,
                 "lookback": ctx["lookback"]},
    }


def build_game_breakdown(season, week, away_team, home_team, lookback_games=6, status=print):
    ctx = load_breakdown_context(season, week, lookback_games, status,
                                 require_teams=[away_team, home_team])
    return build_game_from_context(ctx, away_team, home_team)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--away", type=str, required=True)
    ap.add_argument("--home", type=str, required=True)
    ap.add_argument("--lookback", type=int, default=6)
    a = ap.parse_args()

    res = build_game_breakdown(a.season, a.week, a.away.upper(), a.home.upper(), a.lookback)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    print("\nGAMES USED:", res["meta"])
    print("\nSTANDOUT FLAGS")
    for f in res["flags"]:
        print(" ", f)
    print("\nOFFENSE\n", res["offense"].to_string(index=False))
    print("\nDEFENSE (ALLOWS)\n", res["defense"].to_string(index=False))
    for t in res["teams"]:
        for g in GROUP_ORDER:
            df = res["players"][t][g]
            if not df.empty:
                print(f"\n{t} — {g}\n", df.to_string(index=False))
        if not res["injuries"][t].empty:
            print(f"\n{t} — INJURY IMPACT\n", res["injuries"][t].to_string(index=False))