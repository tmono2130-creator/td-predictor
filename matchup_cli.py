"""Local-only immutable matchup sidecars. No prediction generation or publishing."""
import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from matchup_intelligence import build_intelligence
from matchup_schema import validate_intelligence
from publication_policy import is_live_path, REPOSITORY


def frame(path):
    path = Path(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".csv":
        return pd.read_csv(path, low_memory=False)
    return pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))


def served_path(path):
    path = Path(path).resolve()
    return is_live_path(path) or any(path.is_relative_to(root) for root in
                                    (REPOSITORY / "td-predictor-web/public", REPOSITORY / "public"))


def write_artifact(artifact, board, output):
    validate_intelligence(artifact, board)
    output = Path(output).resolve()
    if served_path(output):
        raise ValueError("Matchup publishing is not activated; live paths forbidden")
    m = artifact["meta"]
    folder = output / str(m["season"]) / f"week-{m['week']}" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True, exist_ok=False)
    target = folder / "matchup-intelligence.json"
    data = json.dumps(artifact, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with target.open("xb") as stream:
        stream.write(data)
    return target, hashlib.sha256(data).hexdigest()


def attach_artifact(candidate, artifact_path, now=None):
    """Attach a validated sidecar to a local candidate; never alter a served snapshot."""
    from weekly_storage import validate_candidate, digest
    from matchup_publication import SIDECAR, HASH_KEY, validate_sidecar
    candidate = Path(candidate).resolve()
    if served_path(candidate):
        raise ValueError("Only local non-production candidates may be extended")
    board, _, receipt = validate_candidate(candidate, now=now)
    if HASH_KEY in receipt:
        raise ValueError("Candidate already contains immutable matchup evidence")
    data = Path(artifact_path).read_bytes()
    receipt[HASH_KEY] = hashlib.sha256(data).hexdigest()
    validate_sidecar(artifact_path, board, receipt, now=now or datetime.now(timezone.utc))
    sidecar = candidate / SIDECAR
    temporary = candidate / (".receipt-" + uuid.uuid4().hex)
    original_receipt_hash = digest(candidate / "receipt.json")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, allow_nan=False, separators=(",", ":"))
            stream.flush(); os.fsync(stream.fileno())
        with sidecar.open("xb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        if digest(candidate / "receipt.json") != original_receipt_hash:
            raise ValueError("Candidate receipt changed concurrently; inspect and rebuild")
        os.replace(temporary, candidate / "receipt.json")
    finally:
        temporary.unlink(missing_ok=True)
    validate_candidate(candidate, now=now)
    return receipt[HASH_KEY]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    for key in ("board", "schedule", "pbp", "player-games", "weekly-rosters", "players", "cutoff", "output"):
        build.add_argument("--" + key, required=True)
    build.add_argument("--source-as-of", help="JSON mapping of source names to actual retrieval timestamps")
    build.add_argument("--snaps", help="Optional normalized GSIS player/game/team snap records")
    validate = commands.add_parser("validate")
    validate.add_argument("--artifact", required=True); validate.add_argument("--board", required=True)
    attach = commands.add_parser("attach")
    attach.add_argument("--candidate", required=True); attach.add_argument("--artifact", required=True)
    args = parser.parse_args(argv)
    if args.command == "attach":
        print(json.dumps({"sha256": attach_artifact(args.candidate, args.artifact), "published": False}))
        return
    board = json.loads(Path(args.board).read_text(encoding="utf-8"))
    if args.command == "validate":
        validate_intelligence(json.loads(Path(args.artifact).read_text(encoding="utf-8")), board)
        print("Matchup schema, identities, temporal references, denominators and V5 binding passed")
        return
    if served_path(args.output):
        parser.error("Only local non-production output paths are allowed")
    schedule_frame = frame(args.schedule)
    schedule = schedule_frame.astype(object).where(pd.notna(schedule_frame), None).to_dict("records")
    artifact = build_intelligence(board, schedule, frame(args.pbp), frame(args.player_games), frame(args.weekly_rosters), frame(args.players),
                                  args.cutoff, source_as_of=json.loads(Path(args.source_as_of).read_text()) if args.source_as_of else None,
                                  snaps=frame(args.snaps) if args.snaps else None)
    path, digest = write_artifact(artifact, board, args.output)
    print(json.dumps({"artifact": str(path), "sha256": digest, "published": False, "classification": artifact["meta"]["evidence_mode"]}))


if __name__ == "__main__":
    main()
