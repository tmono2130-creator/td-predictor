"""Schedule-only planning. Standard library only, so idle jobs avoid model dependencies."""
import csv
import io
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from data_schema import TEAM_CODES

SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"


def utc_now():
    return datetime.now(timezone.utc)


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return value.astimezone(timezone.utc)


def present(value):
    return value is not None and str(value).strip().lower() not in {"", "nan", "none", "nat"}


def kickoff(game):
    if present(game.get("kickoff_utc")):
        return utc(game["kickoff_utc"])
    try:
        local = datetime.strptime(f"{str(game['gameday'])[:10]} {str(game['gametime'])[:5]}", "%Y-%m-%d %H:%M")
        return local.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid kickoff for game {game.get('game_id')}") from exc


def regular_games(records, min_season=None, max_season=None):
    records = list(records)
    if min_season is None:
        min_season = max((int(r["season"]) for r in records if str(r.get("game_type", "")).upper() == "REG"), default=2002) - 3
    games = []
    seen = set()
    for raw in records:
        if str(raw.get("game_type", raw.get("season_type", ""))).upper() != "REG":
            continue
        game = dict(raw)
        game["season"], game["week"] = int(game["season"]), int(game["week"])
        if game["season"] < max(2002, min_season) or max_season is not None and game["season"] > max_season:
            continue
        if game["week"] not in range(1, 19):
            raise ValueError("Invalid season/week in schedule")
        if not present(game.get("game_id")) or game["game_id"] in seen:
            raise ValueError("Missing or duplicate schedule game ID")
        if game.get("home_team") not in TEAM_CODES or game.get("away_team") not in TEAM_CODES or game["home_team"] == game["away_team"]:
            raise ValueError("Invalid schedule team assignment")
        seen.add(game["game_id"])
        try:
            game["kickoff_utc"] = kickoff(game).isoformat()
        except ValueError:
            # Later weeks can legitimately retain TBD kickoff times. Preserve the
            # unknown value; never manufacture a kickoff for them.
            game["kickoff_utc"] = None
        scores = present(game.get("home_score")) and present(game.get("away_score"))
        state = str(game.get("game_status", "")).strip().lower()
        evidence = game.get("completion_evidence")
        final = state in {"final", "completed"} or (isinstance(evidence, dict) and evidence.get("kind") == "pbp_end_game")
        if final and (not scores or any(float(game[k]) < 0 or not float(game[k]).is_integer() for k in ("home_score", "away_score"))):
            raise ValueError("Verified final state lacks valid final scores")
        game["complete"] = bool(final and scores)
        game["completion_state"] = "verified_final" if game["complete"] else "unverified_result" if scores else "not_final"
        games.append(game)
    if not games:
        raise ValueError("Schedule contains no regular-season games")
    return games


def retrieve_schedule(attempts=3, sleep=time.sleep):
    for attempt in range(attempts):
        try:
            request = Request(SCHEDULE_URL, headers={"User-Agent": "NFL-PM-weekly/1", "Cache-Control": "no-cache"})
            with urlopen(request, timeout=45) as response:
                records = list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))
            regular_games(records)  # Never interpret an empty/error response as offseason.
            return records
        except Exception as exc:
            if attempt + 1 == attempts:
                raise RuntimeError("Schedule retrieval failed; published data is unchanged") from exc
            sleep(2 ** attempt)


def plan_week(records, now=None, season=None, week=None, horizon_days=10, historical=False):
    now = utc(now or utc_now())
    if (season is None) != (week is None):
        raise ValueError("Supply both season and week, or neither")
    games = regular_games(records, min_season=season - 3 if season is not None else None, max_season=season)
    if historical and season is None:
        raise ValueError("Historical reconstruction requires an explicit season/week")
    if season is None:
        upcoming = []
        for game in games:
            if game["complete"]:
                continue
            if game["kickoff_utc"] is None:
                try:
                    day = datetime.strptime(str(game["gameday"])[:10], "%Y-%m-%d").date()
                except (KeyError, ValueError) as exc:
                    raise ValueError("Upcoming schedule has an unresolved game date") from exc
                if now.date() - timedelta(days=1) <= day <= (now + timedelta(days=horizon_days)).date():
                    raise ValueError("A nearby game has a TBD/invalid kickoff; wait for schedule confirmation")
                continue
            if now < kickoff(game) <= now + timedelta(days=horizon_days):
                upcoming.append(game)
        if not upcoming:
            return {"status": "idle", "reason": "No upcoming regular-season games in the next 10 days", "games": []}
        first = min(upcoming, key=kickoff)
        season, week = first["season"], first["week"]
    if isinstance(season, bool) or season < 2002 or isinstance(week, bool) or week not in range(1, 19):
        raise ValueError("Season must be >= 2002 and week must be 1–18")
    selected = [g for g in games if g["season"] == season and g["week"] == week]
    if not selected:
        raise ValueError("No games exist for the requested regular-season week")
    teams = [g[t] for g in selected for t in ("away_team", "home_team")]
    if len(set(teams)) != len(teams):
        raise ValueError("Duplicate team in weekly schedule")
    if any(g["kickoff_utc"] is None for g in selected if historical or not g["complete"]):
        raise ValueError("Selected week contains TBD/invalid kickoff times")
    if historical:
        if any(not g["complete"] or kickoff(g) >= now for g in selected):
            raise ValueError("Historical boards require every game to be completed")
        eligible = selected
    else:
        eligible = [g for g in selected if not g["complete"] and kickoff(g) > now]
    return {"status": "ready" if eligible else "idle", "season": season, "week": week,
            "planned_at": now.isoformat(), "historical": historical,
            "games": eligible, "excluded_game_ids": [g["game_id"] for g in selected if g not in eligible]}


def refresh_due(plan, manifest, now=None):
    if plan["status"] != "ready":
        return False
    now = utc(now or utc_now())
    entry = manifest.get("seasons", {}).get(str(plan["season"]), {}).get("weeks", {}).get(str(plan["week"]))
    if not entry:
        return True
    age = now - utc(entry["generated_at"])
    remaining = min(kickoff(g) for g in plan["games"]) - now
    interval = timedelta(minutes=30) if remaining <= timedelta(hours=6) else timedelta(hours=6) if remaining <= timedelta(days=2) else timedelta(days=1)
    return age >= interval
