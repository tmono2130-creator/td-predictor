import json
import tempfile
import unittest
from pathlib import Path

from data_schema import validate_board, validate_breakdowns
from export_json import publish_week


def sample_board(season=2026, week=8, player_id="00-0030001"):
    return {
        "meta": {
            "season": season,
            "week": week,
            "generated_at": "2026-10-22T12:00:00+00:00",
            "model": "composite",
            "final_games": [],
        },
        "rows": [{
            "player_id": player_id,
            "player": "Test Player",
            "team": "BUF",
            "position": "RB",
            "opponent": "KC",
            "td_score": 45.2,
            "td_estimate": 21.3,
            "game_status": "Upcoming",
            "games": 6,
            "injury_status": "Active",
            "actual_scored_td": False,
            "is_home": 1,
        }],
    }


class BoardSchemaTests(unittest.TestCase):
    def test_accepts_export_contract_and_ranges(self):
        validate_board(sample_board(), 2026, 8)

    def test_rejects_requested_week_mismatch(self):
        with self.assertRaisesRegex(ValueError, "week mismatch"):
            validate_board(sample_board(week=7), 2026, 8)

    def test_rejects_missing_required_fields(self):
        board = sample_board()
        del board["rows"][0]["td_estimate"]
        with self.assertRaisesRegex(ValueError, "missing required fields.*td_estimate"):
            validate_board(board, 2026, 8)

    def test_rejects_invalid_team_and_probability(self):
        board = sample_board()
        board["rows"][0]["team"] = "XXX"
        with self.assertRaisesRegex(ValueError, "invalid NFL team code"):
            validate_board(board, 2026, 8)
        board = sample_board()
        board["rows"][0]["td_estimate"] = 101
        with self.assertRaisesRegex(ValueError, "between 0 and 100"):
            validate_board(board, 2026, 8)

    def test_rejects_duplicate_players_and_empty_boards(self):
        board = sample_board()
        board["rows"].append(dict(board["rows"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate player_id"):
            validate_board(board, 2026, 8)
        board = sample_board()
        board["rows"] = []
        with self.assertRaisesRegex(ValueError, "at least one real prediction"):
            validate_board(board, 2026, 8)

    def test_breakdowns_must_match_requested_week(self):
        payload = {"meta": {"season": 2026, "week": 8}, "games": {"BUF@KC": {}}, "errors": {}}
        validate_breakdowns(payload, 2026, 8)
        with self.assertRaisesRegex(ValueError, "week mismatch"):
            validate_breakdowns(payload, 2026, 7)


class WeeklyPublicationTests(unittest.TestCase):
    def test_publishes_separate_week_files_and_manifest(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            publish_week(2026, 8, sample_board(), None, tmp)
            publish_week(2026, 9, sample_board(week=9, player_id="00-0030002"), None, tmp)
            root = Path(tmp)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(set(manifest["seasons"]["2026"]["weeks"]), {"8", "9"})
            ref8 = manifest["seasons"]["2026"]["weeks"]["8"]["board"]
            ref9 = manifest["seasons"]["2026"]["weeks"]["9"]["board"]
            self.assertIn("week-8", ref8)
            self.assertIn("week-9", ref9)
            week8 = json.loads((root / ref8).read_text(encoding="utf-8"))
            week9 = json.loads((root / ref9).read_text(encoding="utf-8"))
            self.assertEqual(week8["meta"]["week"], 8)
            self.assertEqual(week9["meta"]["week"], 9)

    def test_invalid_export_does_not_replace_published_manifest(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            publish_week(2026, 8, sample_board(), None, tmp)
            path = Path(tmp) / "manifest.json"
            before = path.read_bytes()
            invalid = sample_board(week=7)
            with self.assertRaisesRegex(ValueError, "week mismatch"):
                publish_week(2026, 8, invalid, None, tmp)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
