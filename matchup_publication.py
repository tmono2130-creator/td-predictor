"""Explicit optional sidecar contract; imports analytics only when requested."""
import hashlib
import json
from pathlib import Path
from weekly_schedule import utc, kickoff

SIDECAR = "matchup-intelligence.json"
HASH_KEY = "matchup_intelligence_sha256"
CORE_FILES = frozenset({"board.json", "breakdowns.json", "receipt.json"})


def bundle_files(receipt):
    return CORE_FILES | ({SIDECAR} if HASH_KEY in receipt else set()) | ({"game-predictor.json"} if "game_predictor_sha256" in receipt else set())


def manifest_fields(folder, receipt):
    if HASH_KEY not in receipt:
        return {}
    return {"matchup_intelligence": folder + "/" + SIDECAR, HASH_KEY: receipt[HASH_KEY]}


def validate_sidecar(path, board, receipt, now=None):
    """Archived integrity is timeless; new proposals additionally require fresh pregame sources."""
    from matchup_schema import validate_intelligence
    from matchup_intelligence import evidence_ready
    path = Path(path)
    data = path.read_bytes()
    expected = receipt.get(HASH_KEY)
    if not isinstance(expected, str) or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Matchup receipt hash mismatch")
    artifact = json.loads(data)
    meta = artifact["meta"]
    if meta["evidence_mode"] != "pregame_snapshot":
        raise ValueError("Only verified pregame matchup evidence may be published")
    if now is not None:
        now = utc(now)
        earliest = min(kickoff(g) for g in board["meta"]["games"])
        sources = meta["source_as_of"]
        if (utc(meta["generated_at"]) > now or not evidence_ready(
                sources, meta["data_as_of"], now, earliest,
                meta["source_fingerprints"], meta["board_generated_at"])
                or not evidence_ready({"artifact": meta["generated_at"]}, meta["data_as_of"], now,
                                      earliest, ["artifact"], meta["board_generated_at"])):
            raise ValueError("Stale matchup sources, generation time or kickoff safety margin")
    validate_intelligence(artifact, board)
    return artifact


def validate_optional(candidate, board, receipt, now=None):
    candidate = Path(candidate)
    names = {p.name for p in candidate.iterdir()}
    if names != bundle_files(receipt) or any(not p.is_file() or p.is_symlink() for p in candidate.iterdir()):
        raise ValueError("Unexpected or missing candidate bundle files")
    if HASH_KEY in receipt:
        return validate_sidecar(candidate / SIDECAR, board, receipt, now)
    return None
