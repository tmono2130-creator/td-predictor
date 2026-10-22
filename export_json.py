"""
EXPORT JSON — runs your Python model and writes the JSON files the website reads.

Why this exists: the model (nflreadpy, pandas, the fitted .joblib) can only run
in Python. The website is Next.js/Node. Instead of hosting a heavy Python
server, this script does the heavy work on your machine (or a scheduled job)
and writes two small static files the site simply displays:

    manifest.json     index of all successfully published season/week snapshots
    seasons/<year>/week-<week>/board.json
    seasons/<year>/week-<week>/breakdowns.json

The website needs no Python at all after this. Re-run it whenever you want the
site refreshed -- after injury reports update, after a week's games finish, and
after retraining the model (train_final_model.py). Each season/week is stored separately so exporting Week 8 cannot overwrite Week 7. The manifest is updated only after the requested export succeeds.

USAGE:
    python export_json.py --season 2026 --week 6 --out ../td-predictor-web/public/data
    python export_json.py --season 2026 --out ../td-predictor-web/public/data     # week auto-detected
    python export_json.py --season 2026 --week 6 --skip-breakdowns --out ../td-predictor-web/public/data

Run it from the folder that contains td_predictor_v5.py and model_v6.joblib
(the model file is looked up relative to where you run it).
"""

import argparse
import json
import os
from datetime import datetime, timezone

import pandas as pd

from td_predictor_v5 import get_predictions, get_final_scores, load_schedule
from game_breakdown import load_breakdown_context, build_game_from_context, list_week_games

REQUIRED_BOARD_COLUMNS = ["player_id", "player", "team", "position", "opponent", "td_score", "td_estimate", "game_status"]

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
    missing = [c for c in REQUIRED_BOARD_COLUMNS if c not in scored.columns]
    if missing:
        raise RuntimeError(f"Refusing to publish board: missing required columns: {', '.join(missing)}")
    if scored.empty:
        raise RuntimeError("Refusing to publish an empty player board.")
    if scored["player_id"].astype(str).duplicated().any():
        raise RuntimeError("Refusing to publish duplicate player_id values.")
    cols = [c for c in BOARD_COLUMNS if c in scored.columns]
    rows = scored[cols].copy()
    for c in ("td_score", "td_estimate"):
        rows[c] = pd.to_numeric(rows[c], errors="coerce").round(3)
    if "games" in rows.columns:
        rows["games"] = pd.to_numeric(rows["games"], errors="coerce").fillna(0).astype(int)
    if "actual_scored_td" in rows.columns:
        rows["actual_scored_td"] = rows["actual_scored_td"].fillna(False).astype(bool)
    payload = {
        "meta": {
            "season": int(season), "week": int(week),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model_in_use,
            "final_games": final_games,
        },
        "rows": df_records(rows),
    }
    validate_board_payload(payload, season, week)
    return payload


def validate_board_payload(payload, season, week):
    meta = payload.get("meta", {})
    if meta.get("season") != int(season) or meta.get("week") != int(week):
        raise RuntimeError("Board metadata does not match requested season/week.")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Board payload must contain at least one player.")
    seen = set()
    for index, row in enumerate(rows):
        missing = [key for key in REQUIRED_BOARD_COLUMNS if key not in row or row[key] is None]
        if missing:
            raise RuntimeError(f"Board row {index} is missing required values: {', '.join(missing)}")
        player_id = str(row["player_id"]).strip()
        if not player_id or player_id in seen:
            raise RuntimeError(f"Board has an empty or duplicate player_id at row {index}.")
        seen.add(player_id)
        try:
            estimate = float(row["td_estimate"])
            score = float(row["td_score"])
        except (TypeError, ValueError):
            raise RuntimeError(f"Board row {index} has non-numeric TD score/estimate.")
        if not (0 <= estimate <= 100) or not pd.notna(score):
            raise RuntimeError(f"Board row {index} has an invalid TD score/estimate.")


def validate_breakdown_payload(payload, season, week):
    meta = payload.get("meta", {})
    if meta.get("season") != int(season) or meta.get("week") != int(week):
        raise RuntimeError("Breakdown metadata does not match requested season/week.")
    if not isinstance(payload.get("games"), dict) or not payload["games"]:
        raise RuntimeError("Breakdown payload contains no games.")


def week_output_dir(out_dir, season, week):
    return os.path.join(out_dir, "seasons", str(int(season)), f"week-{int(week)}")


def update_manifest(out_dir, season, week, board, breakdowns=None):
    """Publish the manifest last; it is the pointer to a complete weekly snapshot."""
    manifest_path = os.path.join(out_dir, "manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Existing manifest is unreadable; refusing to overwrite it: {exc}")
    else:
        manifest = {"schema_version": 1, "weeks": []}
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("weeks"), list):
        raise RuntimeError("Existing manifest has an unsupported schema; refusing to overwrite it.")

    previous = next((w for w in manifest["weeks"] if (
        isinstance(w, dict) and w.get("season") == int(season) and w.get("week") == int(week)
    )), {})
    breakdown_path = f"/data/seasons/{int(season)}/week-{int(week)}/breakdowns.json"
    entry = {
        "season": int(season),
        "week": int(week),
        "board": f"/data/seasons/{int(season)}/week-{int(week)}/board.json",
        "breakdowns": breakdown_path if breakdowns is not None else previous.get("breakdowns"),
        "generated_at": board["meta"]["generated_at"],
        "model": board["meta"]["model"],
    }
    weeks = [w for w in manifest["weeks"] if not (
        isinstance(w, dict) and w.get("season") == int(season) and w.get("week") == int(week)
    )]
    weeks.append(entry)
    weeks.sort(key=lambda w: (int(w["season"]), int(w["week"])))
    write_json(manifest_path, {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weeks": weeks,
    })


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
    write_json(os.path.join(week_output_dir(out_dir, season, week), "board.json"), payload)
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
    validate_breakdown_payload(payload, season, week)
    write_json(os.path.join(week_output_dir(out_dir, season, week), "breakdowns.json"), payload)
    return payload


def main():
    ap = argparse.ArgumentParser(description="Export model output as JSON for the website.")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int, default=None, help="Omit to auto-detect the current week.")
    ap.add_argument("--out", type=str, default="./public/data", help="Folder the site serves data from.")
    ap.add_argument("--lookback", type=int, default=6, help="Games of history per team for breakdowns.")
    ap.add_argument("--skip-breakdowns", action="store_true", help="Board only (much faster).")
    a = ap.parse_args()

    week = a.week if a.week is not None else detect_current_week(a.season)
    if a.week is None:
        print(f"Auto-detected current week: {week}")

    board = export_board(a.season, week, a.out)
    breakdowns = None
    if not a.skip_breakdowns:
        breakdowns = export_breakdowns(a.season, week, a.lookback, a.out)
    update_manifest(a.out, a.season, week, board, breakdowns)
    print(f"\nPublished season {a.season}, week {week} to manifest.json.")
    print("Deploy/refresh the site to publish the new data.")


if __name__ == "__main__":
    main()