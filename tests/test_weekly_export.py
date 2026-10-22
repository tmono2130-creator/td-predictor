"""Regression tests for the weekly JSON publication contract."""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

# Keep tests isolated from nflreadpy/model startup: these tests cover the
# export contract, not model inference or game-breakdown calculations.
td_stub = types.ModuleType("td_predictor_v5")
td_stub.get_predictions = lambda *a, **k: None
td_stub.get_final_scores = lambda *a, **k: []
td_stub.load_schedule = lambda *a, **k: None
breakdown_stub = types.ModuleType("game_breakdown")
breakdown_stub.load_breakdown_context = lambda *a, **k: None
breakdown_stub.build_game_from_context = lambda *a, **k: None
breakdown_stub.list_week_games = lambda *a, **k: []

with patch.dict(sys.modules, {
    "td_predictor_v5": td_stub,
    "game_breakdown": breakdown_stub,
}):
    from export_json import update_manifest, validate_board_payload, validate_breakdown_payload


def valid_board(season=2026, week=7):
    return {
        "meta": {"season": season, "week": week, "generated_at": "2026-10-20T00:00:00+00:00", "model": "composite"},
        "rows": [{
            "player_id": "player-1", "player": "Example Player", "team": "BUF",
            "position": "RB", "opponent": "KC", "td_score": 42.0,
            "td_estimate": 12.5, "game_status": "Upcoming",
        }],
    }


class WeeklyExportContractTests(unittest.TestCase):
    def test_valid_board_passes(self):
        validate_board_payload(valid_board(), 2026, 7)

    def test_empty_board_is_rejected(self):
        payload = valid_board()
        payload["rows"] = []
        with self.assertRaisesRegex(RuntimeError, "at least one player"):
            validate_board_payload(payload, 2026, 7)

    def test_duplicate_player_ids_are_rejected(self):
        payload = valid_board()
        payload["rows"].append(dict(payload["rows"][0]))
        with self.assertRaisesRegex(RuntimeError, "duplicate player_id"):
            validate_board_payload(payload, 2026, 7)

    def test_wrong_week_metadata_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "metadata"):
            validate_board_payload(valid_board(2026, 6), 2026, 7)

    def test_breakdown_must_match_week_and_contain_games(self):
        payload = {"meta": {"season": 2026, "week": 7}, "games": {"BUF@KC": {}}}
        validate_breakdown_payload(payload, 2026, 7)
        payload["games"] = {}
        with self.assertRaisesRegex(RuntimeError, "no games"):
            validate_breakdown_payload(payload, 2026, 7)

    def test_manifest_is_sorted_and_board_only_refresh_preserves_breakdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = valid_board(2026, 7)
            update_manifest(tmp, 2026, 7, board, {"games": {"BUF@KC": {}}})
            update_manifest(tmp, 2025, 18, valid_board(2025, 18), {"games": {"KC@BUF": {}}})
            update_manifest(tmp, 2026, 7, board, None)

            with open(os.path.join(tmp, "manifest.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)

            self.assertEqual([(w["season"], w["week"]) for w in manifest["weeks"]], [(2025, 18), (2026, 7)])
            current = manifest["weeks"][-1]
            self.assertEqual(current["board"], "/data/seasons/2026/week-7/snapshot/board.json")
            self.assertEqual(current["breakdowns"], "/data/seasons/2026/week-7/snapshot/breakdowns.json")


if __name__ == "__main__":
    unittest.main()
