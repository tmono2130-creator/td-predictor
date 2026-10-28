"""NFL PM weekly runner. Generation is unpublished unless publish is explicitly invoked."""
import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from weekly_schedule import plan_week, refresh_due, retrieve_schedule, utc_now
from weekly_storage import DEFAULT_DATA, final_forecasts, publish_candidate, validate_candidate, validate_manifest, write_new
from publication_policy import require_review_checkout


def verify_current_schedule(board, records, now=None):
    meta = board["meta"]
    plan = plan_week(records, now=now, season=meta["season"], week=meta["week"],
                     historical=meta["snapshot_classification"] == "historical_backfill")
    expected = {(g["game_id"], g["home_team"], g["away_team"], g["kickoff_utc"]) for g in plan["games"]}
    actual = {(g["game_id"], g["home_team"], g["away_team"], g["kickoff_utc"]) for g in meta["games"]}
    if expected != actual:
        raise ValueError("Schedule/remaining-game coverage changed since generation; regenerate")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "generate", "historical"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--season", type=int)
        cmd.add_argument("--week", type=int)
        cmd.add_argument("--data", type=Path, default=DEFAULT_DATA)
        if name == "plan":
            cmd.add_argument("--output", type=Path)
            cmd.add_argument("--due-only", action="store_true")
        else:
            cmd.add_argument("--candidate", type=Path, help="New directory; existing candidates are never overwritten")
    cmd = commands.add_parser("validate")
    cmd.add_argument("--data", type=Path, default=DEFAULT_DATA)
    cmd.add_argument("--candidate", type=Path)
    cmd.add_argument("--allow-historical", action="store_true")
    cmd = commands.add_parser("publish")
    cmd.add_argument("--candidate", required=True, type=Path)
    cmd.add_argument("--data", type=Path, default=DEFAULT_DATA)
    cmd.add_argument("--allow-historical", action="store_true", help="Explicitly approve a historical week with no existing published entry")
    cmd = commands.add_parser("index")
    cmd.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args(argv)
    if args.command == "validate":
        if args.candidate:
            validate_candidate(args.candidate, allow_historical=args.allow_historical)
        else:
            validate_manifest(args.data)
        print("Validation passed")
        return 0
    if args.command == "index":
        print(json.dumps(final_forecasts(args.data), indent=2))
        return 0
    if args.command == "publish":
        require_review_checkout(args.data, historical=args.allow_historical)
        board, _, _ = validate_candidate(args.candidate, allow_historical=args.allow_historical)
        verify_current_schedule(board, retrieve_schedule())
        relative = publish_candidate(args.candidate, args.data, allow_historical=args.allow_historical)
        print(json.dumps({"published_directory": relative, "data_root": str(args.data)}))
        return 0
    records = retrieve_schedule()
    plan = plan_week(records, season=args.season, week=args.week, historical=args.command == "historical")
    if args.command == "plan":
        if args.due_only and plan["status"] == "ready" and not refresh_due(plan, validate_manifest(args.data)):
            plan["status"] = "idle"
            plan["reason"] = "Published snapshot is within refresh interval"
        if args.output:
            write_new(args.output, plan)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                stream.write("ready=" + str(plan["status"] == "ready").lower() + "\n")
        print(json.dumps(plan, indent=2))
        return 0
    if plan["status"] != "ready":
        print(json.dumps(plan))
        return 0
    # Heavy model dependencies load only after the schedule gate has work.
    from weekly_generation import generate_candidate
    from weekly_sources import FreshSources
    candidate = args.candidate or Path("work") / "weekly-candidates" / (utc_now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    validate_manifest(args.data)
    generate_candidate(plan, records, FreshSources(), candidate, args.data)
    print(json.dumps({"candidate": str(candidate), "published": False, "classification": "historical_backfill" if plan["historical"] else "pregame_snapshot"}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Weekly pipeline failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
