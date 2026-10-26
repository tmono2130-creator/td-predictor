"""
EXPORT JSON — runs your Python model and writes the JSON files the website reads.

Why this exists: the model (nflreadpy, pandas, the fitted .joblib) can only run
in Python. The website is Next.js/Node. Instead of hosting a heavy Python
server, this script does the heavy work on your machine (or a scheduled job)
and writes versioned static files plus a manifest that the site reads:

    manifest.json                      index of generated season/week exports
    {season}/week-{week}/{run-id}/board.json
    {season}/week-{week}/{run-id}/breakdowns.json (unless --skip-breakdowns)

The website needs no Python at all after this. Re-run it whenever you want the
site refreshed -- after injury reports update, after a week's games finish, and
after retraining the model (train_final_model.py).

USAGE:
    python export_json.py --season 2026 --week 6 --out ../my-site/public/data
    python export_json.py --season 2026 --out ../my-site/public/data     # week auto-detected
    python export_json.py --season 2026 --week 6 --skip-breakdowns       # board only (fast)

Run it from the folder that contains td_predictor_v5.py and model_v6.joblib
(the model file is looked up relative to where you run it).
"""

import argparse
import json
import os
import uuid
from datetime import datetime, timezone

import pandas as pd

from td_predictor_v5 import get_predictions, get_final_scores, load_schedule
from game_breakdown import load_breakdown_context, build_game_from_context, list_week_games
from data_schema import SCHEMA_VERSION, SUPPORTED_WEEKS, validate_board, validate_breakdowns

BOARD_COLUMNS = [
    "player_id", "player", "team", "position", "opponent",
    "td_score", "td_estimate", "games", "injury_status",
    "game_status", "actual_scored_td", "is_home",
]


def df_records(df):
    """DataFrame -> plain JSON-safe list of dicts (NaN becomes null)."""
    if df is None or len(df) == 0:
        return []
    return json.loads(df.to_json(orient="records"))


def write_json(path, payload):
    """Write atomically so the site never serves a half-written file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, path)
    print(f"  wrote {path} ({os.path.getsize(path) / 1024:.0f} KB)")


def detect_current_week(season):
    """The first week that still has a game today or later (rolls over after Monday night)."""
    sched = load_schedule(season)
    if sched is None or sched.empty or "gameday" not in sched.columns:
        raise RuntimeError("Could not detect the current week -- pass --week explicitly.")
    s = sched.copy()
    s["week"] = pd.to_numeric(s["week"], errors="coerce")
    if "game_type" in s.columns:
        reg = s[s["game_type"].astype(str).str.upper() == "REG"]
        if not reg.empty:
            s = reg
    s["_day"] = pd.to_datetime(s["gameday"], errors="coerce").dt.date
    upcoming = s[s["_day"] >= datetime.now().date()]
    if upcoming.empty:
        return int(s["week"].max())
    return int(upcoming["week"].min())


def board_payload(scored, season, week, model_in_use, final_games):
    cols = [c for c in BOARD_COLUMNS if c in scored.columns]
    rows = scored[cols].copy()
    for c in ("td_score", "td_estimate"):
        rows[c] = pd.to_numeric(rows[c], errors="coerce").round(3)
    if "games" in rows.columns:
        rows["games"] = pd.to_numeric(rows["games"], errors="coerce").fillna(0).astype(int)
    if "actual_scored_td" in rows.columns:
        rows["actual_scored_td"] = rows["actual_scored_td"].fillna(False).astype(bool)
    return {
        "meta": {
            "season": int(season), "week": int(week),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model_in_use,
            "final_games": final_games,
        },
        "rows": df_records(rows),
    }


def breakdown_payload(result):
    return {
        "teams": result["teams"],
        "offense": df_records(result["offense"]),
        "defense": df_records(result["defense"]),
        "players": {t: {g: df_records(df) for g, df in groups.items()}
                    for t, groups in result["players"].items()},
        "injuries": {t: df_records(df) for t, df in result["injuries"].items()},
        "flags": result["flags"],
        "meta": result["meta"],
    }


def export_board(season, week, out_dir):
    print(f"\n[board] {season} week {week}")
    messages = []
    scored, _ = get_predictions(season, week, status_callback=messages.append)
    model_in_use = "fitted" if any("applied fitted model" in m for m in messages) else "composite"
    print(f"  model in use: {model_in_use}")
    if model_in_use == "composite":
        print("  NOTE: no fitted model was applied (model_v6.joblib not found next to where you "
              "ran this, or scikit-learn missing). The site will show composite-model numbers.")
    final_games = get_final_scores(load_schedule(season), season, week)
    payload = board_payload(scored, season, week, model_in_use, final_games)
    return payload


def export_breakdowns(season, week, lookback, out_dir):
    print(f"\n[breakdowns] {season} week {week}, last {lookback} games per team")
    games = list_week_games(season, week)
    if not games:
        raise RuntimeError("No games found for this week.")
    ctx = load_breakdown_context(season, week, lookback)   # heavy load happens ONCE
    out, errors = {}, {}
    for away, home in games:
        key = f"{away}@{home}"
        try:
            out[key] = breakdown_payload(build_game_from_context(ctx, away, home))
            print(f"  built {key}")
        except Exception as e:  # one bad game must not sink the rest
            errors[key] = str(e)
            print(f"  SKIPPED {key}: {e}")
    payload = {
        "meta": {"season": int(season), "week": int(week), "lookback": int(lookback),
                 "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "games": out,
        "errors": errors,
    }
    return payload


def publish_week(season, week, board, breakdowns, out_dir):
    """Write versioned weekly artifacts, then atomically publish the manifest pointer."""
    validate_board(board, season, week)
    if breakdowns is not None:
        validate_breakdowns(breakdowns, season, week)

    manifest_path = os.path.join(out_dir, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        if (not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION
                or not isinstance(manifest.get("seasons"), dict)):
            raise ValueError(f"Invalid existing data manifest: {manifest_path}")
    else:
        manifest = {"schema_version": SCHEMA_VERSION, "supported_weeks": list(SUPPORTED_WEEKS),
                    "seasons": {}}

    season_key = str(season)
    season_record = manifest["seasons"].setdefault(season_key, {"weeks": {}})
    if not isinstance(season_record, dict) or not isinstance(season_record.get("weeks"), dict):
        raise ValueError(f"Invalid manifest entry for season {season}")
    previous = season_record["weeks"].get(str(week), {})

    # Unique filenames keep the last known good files untouched until the manifest swap.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    week_prefix = f"{season}/week-{week}/{run_id}"
    board_rel = f"{week_prefix}/board.json"
    breakdowns_rel = f"{week_prefix}/breakdowns.json"
    week_dir = os.path.join(out_dir, str(season), f"week-{week}", run_id)
    write_json(os.path.join(week_dir, "board.json"), board)
    if breakdowns is not None:
        write_json(os.path.join(week_dir, "breakdowns.json"), breakdowns)

    breakdown_ref = breakdowns_rel if breakdowns is not None else previous.get("breakdowns")
    if breakdown_ref and not os.path.isfile(os.path.join(out_dir, *breakdown_ref.split("/"))):
        breakdown_ref = None
    season_record["weeks"][str(week)] = {
        "board": board_rel,
        "breakdowns": breakdown_ref,
        "generated_at": board["meta"]["generated_at"],
        "model": board["meta"]["model"],
    }
    write_json(manifest_path, manifest)
    print(f"  published season {season}, week {week} in {manifest_path}")


def main():
    ap = argparse.ArgumentParser(description="Export validated model output for the website.")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int, default=None, help="Omit to auto-detect the current regular-season week.")
    ap.add_argument("--out", type=str, default="./public/data", help="Folder the site serves data from.")
    ap.add_argument("--lookback", type=int, default=6, help="Games of history per team for breakdowns.")
    ap.add_argument("--skip-breakdowns", action="store_true", help="Board only (much faster).")
    a = ap.parse_args()

    if a.season < 1999:
        ap.error("--season must be 1999 or later")
    week = a.week if a.week is not None else detect_current_week(a.season)
    if week not in SUPPORTED_WEEKS:
        ap.error("--week must be a regular-season week from 1 through 18")
    if a.week is None:
        print(f"Auto-detected current week: {week}")

    board = export_board(a.season, week, a.out)
    validate_board(board, a.season, week)
    breakdowns = None if a.skip_breakdowns else export_breakdowns(a.season, week, a.lookback, a.out)
    publish_week(a.season, week, board, breakdowns, a.out)
    print("\nDone. Deploy/refresh the site to publish the new data.")

if __name__ == "__main__":
    main()