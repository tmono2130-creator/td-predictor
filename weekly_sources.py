"""Fresh nflverse inputs with explicit cutoffs; no stale-cache or statistics fallback."""
import hashlib
import time
import pandas as pd
import nflreadpy
import td_predictor_v5 as v5
from weekly_schedule import regular_games, kickoff, utc, utc_now
from roster_eligibility import EligibilityError, resolve_roster, select_weekly

STAT_COLUMNS = {"player_id", "player_display_name", "position", "team", "season", "week",
                "targets", "carries", "receptions", "receiving_tds", "rushing_tds", "passing_tds",
                "receiving_yards", "rushing_yards", "target_share"}
PBP_REQUIRED = {"play_id", "game_id", "season", "week", "season_type", "yardline_100", "play_type",
                "receiver_player_id", "rusher_player_id", "touchdown", "rush_touchdown", "pass_touchdown",
                "posteam", "defteam", "drive", "td_team", "td_player_id", "yards_gained", "two_point_attempt"}


def require_columns(frame, columns, source):
    missing = set(columns).difference(frame.columns)
    if missing:
        raise ValueError(f"{source} missing required fields: {', '.join(sorted(missing))}")


def prior_rows(frame, season, week):
    require_columns(frame, {"season", "week"}, "history")
    years, weeks = pd.to_numeric(frame.season, errors="raise"), pd.to_numeric(frame.week, errors="raise")
    before = (years < season) | ((years == season) & (weeks < week))
    result = frame[before].copy()
    type_col = next((c for c in ("season_type", "game_type") if c in result), None)
    if type_col:
        result = result[result[type_col].astype(str).str.upper().eq("REG")].copy()
    return result


class FreshSources:
    def __init__(self, fetchers=None, sleep=time.sleep):
        self.fetchers = fetchers or {
            "stats": lambda season: nflreadpy.load_player_stats(seasons=[season], summary_level="week"),
            "pbp": lambda season: nflreadpy.load_pbp(seasons=[season]),
            "weekly_rosters": lambda season: nflreadpy.load_rosters_weekly(seasons=[season]),
            "rosters": lambda season: nflreadpy.load_rosters(seasons=[season]),
            "players": lambda _: nflreadpy.load_players(),
            "injuries": lambda season: nflreadpy.load_injuries(seasons=[season]),
        }
        self.sleep = sleep
        self.cache = {}
        self.metadata = {}
        # Every process/run starts fresh. No persistent data-source caches in Actions.
        if fetchers is None:
            from nflreadpy.config import update_config
            update_config(cache_mode="off", timeout=90)

    def get(self, name, season, optional=False):
        key = (name, season)
        if key not in self.cache:
            for attempt in range(3):
                try:
                    raw = self.fetchers[name](season)
                    if name == "pbp" and hasattr(raw, "select") and not isinstance(raw, pd.DataFrame):
                        raw = raw.select([c for c in PBP_REQUIRED | {"desc", "extra_point_attempt", "extra_point_result", "field_goal_attempt", "field_goal_result", "return_touchdown", "two_point_conv_result", "total_home_score", "total_away_score", "epa"} if c in raw.columns])
                    frame = v5.to_pandas(raw)
                    if frame.empty:
                        raise ValueError("source returned no rows")
                    self.cache[key] = frame
                    self.metadata[f"{name}:{season}"] = {
                        "retrieved_at_utc": utc_now().isoformat(), "rows": len(frame),
                        "sha256": hashlib.sha256(frame.to_json(date_format="iso").encode()).hexdigest()}
                    break
                except Exception as exc:
                    if attempt == 2:
                        if not optional:
                            raise RuntimeError(f"Required source retrieval failed: {name}/{season}") from exc
                        self.cache[key] = pd.DataFrame()
                        self.metadata[f"{name}:{season}"] = {"available": False, "reason": "source unavailable"}
                    else:
                        self.sleep(2 ** attempt)
        return self.cache[key].copy(deep=True)

    def rosters(self, season, week, historical=False, teams=None):
        weekly = self.get("weekly_rosters", season, optional=not historical)
        target = select_weekly(weekly, season, week)
        if target.empty and historical:
            raise ValueError("Historical boards require a week-specific roster")
        live = self.get('rosters', season) if target.empty else pd.DataFrame()
        known = self.get("players", season)
        try:
            roster, audit = resolve_roster(weekly, live, known, season, week, teams, historical)
        except EligibilityError as exc:
            self.metadata['roster_eligibility'] = exc.audit
            raise
        self.metadata['roster_eligibility'] = audit
        self.metadata['roster_scope'] = audit['scope']
        self.metadata['roster_pool_policy'] = 'verified ACT skill players on scheduled teams; unresolved eligibility blocks publication; injury status independent'
        self.metadata['excluded_roster_rows'] = audit['counts']['exclude']
        return roster

    def history(self, schedule, season, week, cutoff):
        games = regular_games(schedule, min_season=season - 3, max_season=season)
        completed = [g for g in games if g["complete"] and kickoff(g) < utc(cutoff) and
                     (g["season"] < season or g["season"] == season and g["week"] < week)]
        by_season = {}
        for year in range(season - 3, season + 1):
            expected = [g for g in completed if g["season"] == year]
            if not expected:
                if year < season:
                    raise ValueError(f"Missing completed schedule history for {year}")
                continue
            stats = prior_rows(self.get("stats", year), season, week)
            require_columns(stats, STAT_COLUMNS, "player statistics")
            require_columns(stats, {"game_id"}, "player statistics")
            expected_ids = {g["game_id"] for g in expected}
            stats = stats[stats.game_id.isin(expected_ids)].copy()
            if stats.duplicated(["player_id", "game_id"]).any():
                raise ValueError("Duplicate player/game statistics")
            # Fail when an earlier completed game is missing, rather than imputing an entire source gap.
            for game in expected:
                if set(stats.loc[stats.game_id.eq(game["game_id"]), "team"]) != {game["away_team"], game["home_team"]}:
                    raise ValueError(f"Statistics are missing completed-game coverage: {game['game_id']}")
            for column in STAT_COLUMNS - {"player_id", "player_display_name", "position", "team"}:
                numeric = pd.to_numeric(stats[column], errors="coerce")
                if numeric.isna().any() or not numeric.map(lambda x: x == x and abs(x) != float("inf")).all():
                    raise ValueError(f"Missing or invalid observed statistic: {column}")
            by_season[year] = stats
        pbps = []
        for year in (season - 1, season):
            expected_ids = {g["game_id"] for g in completed if g["season"] == year}
            if not expected_ids:
                continue
            pbp = prior_rows(self.get("pbp", year), season, week)
            require_columns(pbp, PBP_REQUIRED, "play-by-play")
            pbp = pbp[pbp.game_id.isin(expected_ids)].copy()
            if not expected_ids.issubset(set(pbp.game_id)):
                raise ValueError("Play-by-play is missing completed games")
            pbps.append(pbp)
        if not pbps:
            raise ValueError("No prior play-by-play available")
        return by_season, pd.concat(pbps, ignore_index=True)

    def injuries(self, season, week, cutoff, historical=False):
        empty = pd.DataFrame(columns=["player_id", "injury_status"])
        empty.attrs["week_report_available"] = False
        if historical:
            return empty
        raw = self.get("injuries", season, optional=True)
        if raw.empty or "week" not in raw:
            return empty
        raw = raw[pd.to_numeric(raw.week, errors="coerce").eq(week)].copy()
        if "season_type" in raw:
            raw = raw[raw.season_type.astype(str).str.upper().eq("REG")]
        # A source retrieved during this live run is pregame information. If an
        # explicit source update time exists, reject updates later than retrieval cutoff.
        if "date_modified" in raw:
            modified = pd.to_datetime(raw.date_modified, errors="coerce", utc=True)
            raw = raw[modified.isna() | (modified <= utc(cutoff))].copy()
            raw["_modified"] = modified.loc[raw.index]
            raw = raw.sort_values("_modified")
        id_col = next((c for c in ("gsis_id", "player_id", "nfl_id") if c in raw), None)
        status_col = next((c for c in ("report_status", "game_status", "status") if c in raw), None)
        if not id_col or not status_col:
            return empty
        result = raw[[id_col, status_col]].rename(columns={id_col: "player_id", status_col: "injury_status"})
        result["injury_status"] = result.injury_status.map(v5.normalize_injury_status)
        result = result.dropna(subset=["player_id"]).drop_duplicates("player_id", keep="last")
        result.attrs["week_report_available"] = not result.empty
        return result
