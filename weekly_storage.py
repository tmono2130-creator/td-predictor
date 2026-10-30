"""Strict candidate validation, immutable archives, and atomic manifest publication."""
import copy
import hashlib
import json
import math
import os
import re
import uuid
from pathlib import Path
from weekly_schedule import kickoff, utc, utc_now
from data_schema import validate_board, validate_breakdowns, SCHEMA_VERSION, SUPPORTED_WEEKS
from publication_policy import require_review_checkout, fresh

from matchup_publication import SIDECAR, HASH_KEY, validate_optional, validate_sidecar, manifest_fields

GSIS_ID = re.compile(r"00-\d{7}\Z")
DEFAULT_DATA = Path(__file__).resolve().parent / "td-predictor-web" / "public" / "data"


def digest(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def load_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, allow_nan=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())


def safe_file(root, reference):
    if not isinstance(reference, str) or not re.fullmatch(r"[\w-]+(?:/[\w.-]+)*\.json", reference, flags=re.ASCII):
        raise ValueError("Unsafe manifest reference")
    target = (Path(root) / reference).resolve()
    if not target.is_relative_to(Path(root).resolve()) or not target.is_file():
        raise ValueError("Manifest references a missing or unsafe JSON file")
    return target


def validate_manifest(root):
    path = Path(root) / "manifest.json"
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "supported_weeks": list(SUPPORTED_WEEKS), "seasons": {}}
    manifest = load_json(path)
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION
            or manifest.get("supported_weeks") != list(SUPPORTED_WEEKS) or not isinstance(manifest.get("seasons"), dict)):
        raise ValueError("Invalid manifest")
    for season, entry in manifest["seasons"].items():
        if not re.fullmatch(r"\d{4}", season) or not isinstance(entry, dict) or not isinstance(entry.get("weeks"), dict):
            raise ValueError("Invalid manifest season")
        for week, files in entry["weeks"].items():
            if not week.isdigit() or str(int(week)) != week or int(week) not in SUPPORTED_WEEKS or not isinstance(files, dict):
                raise ValueError("Invalid manifest week")
            board = load_json(safe_file(root, files.get("board")))
            validate_board(board, int(season), int(week))
            if files.get("generated_at") != board["meta"]["generated_at"] or files.get("model") != board["meta"]["model"]:
                raise ValueError("Manifest metadata does not match board")
            if files.get("breakdowns") is not None:
                validate_breakdowns(load_json(safe_file(root, files["breakdowns"])), int(season), int(week), board["meta"]["games"])
            if "matchup_intelligence" in files or HASH_KEY in files:
                if "matchup_intelligence" not in files or HASH_KEY not in files:
                    raise ValueError("Matchup manifest reference and hash must be paired")
                sidecar = safe_file(root, files["matchup_intelligence"])
                board_path = safe_file(root, files["board"])
                if sidecar.name != SIDECAR or sidecar.parent != board_path.parent:
                    raise ValueError("Matchup artifact must belong to the same immutable snapshot")
                receipt = load_json(sidecar.with_name("receipt.json"))
                if (receipt.get(HASH_KEY) != files[HASH_KEY] or receipt.get("board_sha256") != digest(board_path)
                        or receipt.get("breakdowns_sha256") != digest(sidecar.with_name("breakdowns.json"))):
                    raise ValueError("Matchup manifest/receipt binding mismatch")
                validate_sidecar(sidecar, board, receipt)
    return manifest


def validate_candidate(candidate, now=None, allow_historical=False):
    candidate = Path(candidate)
    board, breakdowns, receipt = [load_json(candidate / name) for name in ("board.json", "breakdowns.json", "receipt.json")]
    meta = board["meta"]
    season, week = meta["season"], meta["week"]
    if type(season) is not int or season < 2002 or type(week) is not int or week not in SUPPORTED_WEEKS:
        raise ValueError("Invalid candidate season/week")
    validate_board(board, season, week)
    validate_breakdowns(breakdowns, season, week, meta["games"])
    generated = utc(meta["generated_at"])
    now = utc(now or utc_now())
    kind = meta.get("snapshot_classification")
    historical = kind == "historical_backfill"
    if kind not in {"pregame_snapshot", "historical_backfill"} or historical and not allow_historical:
        raise ValueError("Historical publication requires explicit approval")
    expected_model = "v5-composite-sha256:" + hashlib.sha256(Path(__file__).with_name("td_predictor_v5.py").read_bytes()).hexdigest()
    if meta["model"] != "composite" or meta.get("model_version") != expected_model:
        raise ValueError("Only the unchanged V5 composite model is allowed")
    if breakdowns["meta"].get("generated_at") != meta["generated_at"]:
        raise ValueError("Board and breakdown must share the same snapshot timestamp")
    if generated > now or utc(receipt["source_cutoff_utc"]) > generated:
        raise ValueError("Invalid prediction/source timestamp")
    if receipt.get("board_sha256") != digest(candidate / "board.json") or receipt.get("breakdowns_sha256") != digest(candidate / "breakdowns.json"):
        raise ValueError("Candidate file hash mismatch")
    if not isinstance(receipt.get("source_metadata"), dict) or not receipt["source_metadata"]:
        raise ValueError("Source retrieval provenance is required")
    for source in receipt["source_metadata"].values():
        if isinstance(source, dict) and "retrieved_at_utc" in source and utc(source["retrieved_at_utc"]) > generated:
            raise ValueError("Source retrieval occurred after prediction time")
    expected = receipt["scheduled_games"]
    ids = {g["game_id"] for g in expected}
    if len(ids) != len(expected) or ids != {g["game_id"] for g in meta["games"]}:
        raise ValueError("Incomplete scheduled game coverage")
    expected_pairs = {f"{g['away_team']}@{g['home_team']}" for g in expected}
    if breakdowns["errors"] or set(breakdowns["games"]) != expected_pairs:
        raise ValueError("Incomplete breakdown coverage")
    def table(value):
        return isinstance(value, list) and all(isinstance(r, dict) and all(
            c is None or isinstance(c, (str, bool)) or isinstance(c, (int, float)) and math.isfinite(c)
            for c in r.values()) for r in value)
    for key, report in breakdowns["games"].items():
        teams = key.split("@")
        if (not all(table(report.get(field)) and report[field] for field in ("offense", "defense")) or
                not isinstance(report.get("flags"), list) or not all(isinstance(flag, str) for flag in report["flags"]) or
                not isinstance(report.get("meta"), dict) or
                not isinstance(report["meta"].get("lookback"), int) or report["meta"]["lookback"] <= 0):
            raise ValueError("Invalid breakdown tables or metadata")
        for field in ("games_used", "prior_season_games"):
            counts = report["meta"].get(field)
            if not isinstance(counts, dict) or any(not isinstance(counts.get(t), int) or counts[t] < (1 if field == "games_used" else 0) for t in teams):
                raise ValueError("Missing breakdown sample coverage")
        if not isinstance(report.get("players"), dict) or not isinstance(report.get("injuries"), dict):
            raise ValueError("Invalid breakdown player groups")
        for team in teams:
            groups = report["players"].get(team)
            if not isinstance(groups, dict) or not all(table(rows) for rows in groups.values()) or not table(report["injuries"].get(team)):
                raise ValueError("Invalid breakdown player/injury tables")
    roster = receipt["eligible_players"]
    required = {(r["player_id"], r["game_id"], r["team"], r["opponent"]) for r in roster}
    actual = {(r["player_id"], r["game_id"], r["team"], r["opponent"]) for r in board["rows"]}
    if len(required) != len(roster) or actual != required or len(actual) != len(board["rows"]):
        raise ValueError("Incomplete or duplicate player-game coverage")
    audit = receipt['source_metadata'].get('roster_eligibility')
    if audit is not None:
        if not isinstance(audit, dict) or not isinstance(audit.get('decisions'), list) or any(not isinstance(d, dict) for d in audit['decisions']):
            raise ValueError('Invalid roster eligibility audit')
        decisions = audit.get('decisions', [])
        counts = {key:sum(d.get('decision') == key for d in decisions) for key in ('include','exclude','pending')}
        included = [(d.get('player_id'), d.get('team'), d.get('position')) for d in decisions if d.get('decision') == 'include']
        expected_pool = {(r['player_id'],r['team'],r['position']) for r in board['rows']}
        if (audit.get('policy_version') != 'week-aware-v1' or audit.get('season') != season or audit.get('week') != week
                or audit.get('counts') != counts or counts['pending'] or len(included) != len(set(included))
                or set(audit.get('scheduled_teams', [])) != {g[t] for g in expected for t in ('home_team','away_team')}
                or any(d.get('decision') not in counts for d in decisions)
                or set(included) != expected_pool or any(d.get('roster_status') != 'ACT' for d in decisions if d.get('decision') == 'include')):
            raise ValueError('Roster eligibility audit differs from candidate or has pending decisions')
    if {r["team"] for r in roster} != {g[t] for g in expected for t in ("away_team", "home_team")}:
        raise ValueError("Missing team player coverage")
    by_id = {g["game_id"]: g for g in expected}
    for game in meta["games"]:
        original = by_id[game["game_id"]]
        if any(game.get(k) != original.get(k) for k in ("home_team", "away_team", "kickoff_utc")):
            raise ValueError("Game differs from retrieved schedule")
        if game.get("prediction_timing") != kind or game.get("snapshot_classification") != kind:
            raise ValueError("Invalid game classification")
        if historical:
            if not original.get("complete") or kickoff(game) >= generated:
                raise ValueError("Backfill is not a completed game")
        elif now >= kickoff(game) or original.get("complete"):
            raise ValueError("Kickoff has passed; refuse publication of a new pregame forecast")
    if not isinstance(meta.get("source_versions"), dict) or not meta["source_versions"]:
        raise ValueError("Source metadata is required")
    for row in board["rows"]:
        if row.get("position") not in {"QB", "RB", "FB", "WR", "TE"}:
            raise ValueError("Invalid player position")
        game = by_id[row["game_id"]]
        if row.get("is_home") != int(row["team"] == game["home_team"]):
            raise ValueError("Player home/away assignment is inconsistent")
        if not meta["injury_report"].get("week_available") and row["injury_status"] != "Unknown":
            raise ValueError("Unavailable injury report cannot imply Active")
        if not GSIS_ID.fullmatch(row["player_id"]):
            raise ValueError("Invalid GSIS player identifier")
        if row.get("prediction_timestamp_utc") != meta["generated_at"] or row.get("snapshot_classification") != kind:
            raise ValueError("Invalid player snapshot timestamp/classification")
        if row.get("game_status") != ("Final" if historical else "Upcoming") or row.get("prediction_timing") != kind:
            raise ValueError("Invalid game-status classification")
        if row.get("predicted_td_probability_pct") != row["td_estimate"] or not math.isfinite(row["td_estimate"]):
            raise ValueError("Probability fields differ")
        if row.get("actual_scored_td") is not None:
            raise ValueError("Forecast boards do not infer observed outcomes")
        if historical and row["injury_status"] != "Unknown":
            raise ValueError("Historical injury publication times are unavailable")
    validate_optional(candidate, board, receipt, now=now)
    return board, breakdowns, receipt


def publish_candidate(candidate, root=DEFAULT_DATA, allow_historical=False, now=None):
    """Append one immutable bundle; swap only the manifest, under an exclusive lock.

    A failed transaction may leave an unreferenced immutable directory. It cannot
    change any previously served bundle. Never repair/delete a lock automatically.
    """
    root = Path(root).resolve()
    require_review_checkout(root, historical=allow_historical)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".weekly-publish.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.close(descriptor)
        board, breakdowns, receipt = validate_candidate(candidate, now=now, allow_historical=allow_historical)
        if not allow_historical:
            fresh(board, receipt, utc(now or utc_now()))
        manifest_path = root / "manifest.json"
        if digest(manifest_path) != receipt.get("base_manifest_sha256"):
            raise ValueError("Published manifest changed since generation; regenerate the candidate")
        manifest = validate_manifest(root)
        season, week = board["meta"]["season"], board["meta"]["week"]
        previous = manifest.get("seasons", {}).get(str(season), {}).get("weeks", {}).get(str(week))
        if allow_historical and previous:
            raise ValueError("Historical backfills cannot replace an existing published week")
        run_id = utc(board["meta"]["generated_at"]).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
        relative = f"{season}/week-{week}/{run_id}"
        folder = root / relative
        if not folder.resolve().is_relative_to(root):
            raise ValueError("Archive path escapes data root")
        folder.mkdir(parents=True, exist_ok=False)
        for name, value in (("board.json", board), ("breakdowns.json", breakdowns), ("receipt.json", receipt)):
            write_new(folder / name, value)
        if HASH_KEY in receipt:
            with (folder / SIDECAR).open("xb") as stream:
                stream.write((Path(candidate) / SIDECAR).read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
        validate_candidate(folder, now=now, allow_historical=allow_historical)
        updated = copy.deepcopy(manifest)
        updated["seasons"].setdefault(str(season), {"weeks": {}})["weeks"][str(week)] = {
            "board": relative + "/board.json", "breakdowns": relative + "/breakdowns.json",
            "generated_at": board["meta"]["generated_at"], "model": board["meta"]["model"], **manifest_fields(relative, receipt)}
        temporary = root / (".manifest-" + uuid.uuid4().hex + ".json")
        try:
            write_new(temporary, updated)
            os.replace(temporary, manifest_path)
        finally:
            temporary.unlink(missing_ok=True)
        return relative
    finally:
        lock.unlink(missing_ok=True)


def final_forecasts(root=DEFAULT_DATA):
    """Latest genuinely pregame row for each player/game; never select a backfill."""
    result = {}
    for path in Path(root).glob("*/week-*/*/board.json"):
        board = load_json(path)
        meta = board["meta"]
        if meta.get("snapshot_classification") not in {"pregame_snapshot", "mixed_pregame_and_historical"} or not meta.get("model_version"):
            continue
        validate_board(board, meta["season"], meta["week"])
        receipt_path = path.with_name("receipt.json")
        if receipt_path.exists() and load_json(receipt_path).get("board_sha256") != digest(path):
            raise ValueError("Archived board hash mismatch; do not evaluate a modified snapshot")
        games = {g["game_id"]: g for g in meta["games"]}
        for row in board["rows"]:
            game = games[row["game_id"]]
            if row.get("prediction_timestamp_utc") != meta["generated_at"]:
                continue
            generated = utc(row["prediction_timestamp_utc"])
            if (row.get("snapshot_classification") != "pregame_snapshot" or
                    game.get("snapshot_classification") != "pregame_snapshot" or
                    row.get("prediction_timing") != "pregame_snapshot" or generated >= kickoff(game)):
                continue
            key = (row["game_id"], row["player_id"])
            if key not in result or utc(result[key]["prediction_timestamp_utc"]) < generated:
                result[key] = {"season": meta["season"], "week": meta["week"], "game_id": key[0], "player_id": key[1],
                               "predicted_td_probability_pct": row["td_estimate"], "prediction_timestamp_utc": generated.isoformat(),
                               "kickoff_utc": game["kickoff_utc"], "model_version": meta.get("model_version"),
                               "board": path.relative_to(root).as_posix()}
    return sorted(result.values(), key=lambda r: (r["game_id"], r["player_id"]))
