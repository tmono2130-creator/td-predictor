import json
import tempfile
import unittest
from pathlib import Path

from data_schema import validate_board, validate_breakdowns
from export_json import board_payload, publish_week


def sample_board(season=2026, week=8, player_id="00-0030001"):
    return {
        "meta": {
            "season": season,
            "week": week,
            "generated_at": "2026-10-22T12:00:00+00:00",
            "model": "composite",
            "final_games": [],
            "games": [{
                "game_id": f"{season}_{week:02}_BUF_KC",
                "away_team": "KC",
                "home_team": "BUF",
                "kickoff_utc": "2026-10-30T00:15:00+00:00",
                "prediction_timing": "pregame_snapshot",
            }],
            "injury_report": {
                "source": "nflverse weekly official injury reports",
                "week_available": False,
                "unknown_is_not_active": True,
            },
        },
        "rows": [{
            "player_id": player_id,
            "game_id": f"{season}_{week:02}_BUF_KC",
            "player": "Test Player",
            "team": "BUF",
            "position": "RB",
            "opponent": "KC",
            "td_score": 45.2,
            "td_estimate": 21.3,
            "game_status": "Upcoming",
            "prediction_timing": "pregame_snapshot",
            "games": 6,
            "injury_status": "Unknown",
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
        with self.assertRaisesRegex(ValueError, "outside the selected week's schedule"):
            validate_breakdowns(payload, 2026, 8, [{"away_team": "KC", "home_team": "BUF"}])


class SnapshotMetadataTests(unittest.TestCase):
    def test_snapshot_preserves_timing_model_source_and_probability_semantics(self):
        import pandas as pd
        from data_schema import validate_board
        from datetime import datetime, timezone
        from unittest.mock import patch

        class PregameClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 30, 12, tzinfo=timezone.utc).astimezone(tz)

        scored = pd.DataFrame([{
            "player_id": "p1", "game_id": "2026_08_KC_BUF", "player": "Test Player",
            "team": "BUF", "position": "RB", "opponent": "KC", "td_score": 55.0,
            "td_estimate": 12.5, "games": 6, "injury_status": "Unknown",
            "game_status": "Upcoming", "actual_scored_td": False, "is_home": 1,
        }])
        schedule = pd.DataFrame([{
            "season": 2026, "week": 8, "game_type": "REG", "game_id": "2026_08_KC_BUF",
            "home_team": "BUF", "away_team": "KC", "gameday": "2026-10-30",
            "gametime": "20:15", "home_score": None, "away_score": None,
        }])
        # This regression verifies pregame semantics, independent of the real wall clock.
        with patch('export_json.datetime', PregameClock):
            board = board_payload(scored, 2026, 8, "composite", [], schedule)
        validate_board(board, 2026, 8)
        self.assertTrue(board["meta"]["model_version"].startswith("composite-sha256:"))
        self.assertIn("nflreadpy", board["meta"]["source_versions"])
        self.assertEqual(board["meta"]["snapshot_classification"], "pregame_snapshot")
        row = board["rows"][0]
        self.assertEqual(row["predicted_td_probability_pct"], 12.5)
        self.assertEqual(row["snapshot_classification"], "pregame_snapshot")
        self.assertEqual(row["prediction_timestamp_utc"], board["meta"]["generated_at"])
        self.assertIn("not established as calibrated", board["meta"]["probability_semantics"])
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

    def test_republishing_week_preserves_the_archived_snapshot(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            publish_week(2026, 8, sample_board(), None, tmp)
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            first = json.loads(manifest_path.read_text(encoding="utf-8"))
            first_ref = first["seasons"]["2026"]["weeks"]["8"]["board"]
            first_path = root / first_ref
            first_bytes = first_path.read_bytes()
            publish_week(2026, 8, sample_board(player_id="00-0030002"), None, tmp)
            second = json.loads(manifest_path.read_text(encoding="utf-8"))
            second_ref = second["seasons"]["2026"]["weeks"]["8"]["board"]
            self.assertNotEqual(first_ref, second_ref)
            self.assertEqual(first_path.read_bytes(), first_bytes)
            self.assertTrue((root / second_ref).is_file())
    def test_invalid_export_does_not_replace_published_manifest(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            publish_week(2026, 8, sample_board(), None, tmp)
            path = Path(tmp) / "manifest.json"
            before = path.read_bytes()
            invalid = sample_board(week=7)
            with self.assertRaisesRegex(ValueError, "week mismatch"):
                publish_week(2026, 8, invalid, None, tmp)
            self.assertEqual(path.read_bytes(), before)


class InjuryAndScheduleIntegrityTests(unittest.TestCase):
    def test_board_rows_must_match_scheduled_game(self):
        board = sample_board()
        board["rows"][0]["team"] = "MIA"
        with self.assertRaisesRegex(ValueError, "do not match scheduled game"):
            validate_board(board, 2026, 8)

    def test_board_rejects_unknown_timing_or_injury_status_alias(self):
        board = sample_board()
        board["rows"][0]["prediction_timing"] = "pre-game-ish"
        with self.assertRaisesRegex(ValueError, "prediction_timing has invalid value"):
            validate_board(board, 2026, 8)
        board = sample_board()
        board["rows"][0]["injury_status"] = "Healthy"
        with self.assertRaisesRegex(ValueError, "injury_status has invalid value"):
            validate_board(board, 2026, 8)

    def test_unknown_is_valid_and_never_interpreted_as_active(self):
        board = sample_board()
        self.assertEqual(board["rows"][0]["injury_status"], "Unknown")
        validate_board(board, 2026, 8)

    def test_schema_validates_game_identity_and_duplicate_player_game(self):
        board = sample_board()
        board["rows"][0]["game_id"] = "not-scheduled"
        with self.assertRaisesRegex(ValueError, "not scheduled for this week"):
            validate_board(board, 2026, 8)
        board = sample_board()
        board["rows"].append(dict(board["rows"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate player_id"):
            validate_board(board, 2026, 8)

    def test_week_completion_requires_every_scheduled_game_to_be_final(self):
        import pandas as pd
        from evaluation_utils import require_complete_regular_week

        schedule = pd.DataFrame([
            {"season": 2026, "week": 8, "game_type": "REG", "game_id": "a",
             "home_team": "BUF", "away_team": "KC", "home_score": 20, "away_score": 17},
            {"season": 2026, "week": 8, "game_type": "REG", "game_id": "b",
             "home_team": "MIA", "away_team": "NE", "home_score": None, "away_score": None},
            {"season": 2026, "week": 8, "game_type": "PRE", "game_id": "c",
             "home_team": "NYJ", "away_team": "NYG", "home_score": None, "away_score": None},
        ])
        with self.assertRaisesRegex(ValueError, "1 of 2 scheduled game"):
            require_complete_regular_week(schedule, 2026, 8)
        schedule.loc[1, ["home_score", "away_score"]] = [24, 21]
        self.assertEqual(len(require_complete_regular_week(schedule, 2026, 8)), 2)

    def test_prediction_rows_must_match_player_game_schedule_pair(self):
        import pandas as pd
        from evaluation_utils import validate_predictions_against_schedule

        predictions = pd.DataFrame([{"player_id": "p1", "game_id": "g1", "team": "BUF", "opponent": "KC"}])
        games = pd.DataFrame([{"game_id": "g1", "home_team": "BUF", "away_team": "KC"}])
        validate_predictions_against_schedule(predictions, games)
        predictions.loc[0, "opponent"] = "MIA"
        with self.assertRaisesRegex(ValueError, "team/opponent do not match schedule"):
            validate_predictions_against_schedule(predictions, games)

    def test_weekly_injury_loader_keeps_null_status_unknown(self):
        import pandas as pd
        import td_predictor_v5

        original = td_predictor_v5.nflreadpy.load_injuries
        try:
            td_predictor_v5.nflreadpy.load_injuries = lambda seasons: pd.DataFrame([
                {"season": 2026, "season_type": "REG", "week": 8, "gsis_id": "p1",
                 "full_name": "Player One", "report_status": None,
                 "practice_status": "Full Participation in Practice"},
                {"season": 2026, "season_type": "REG", "week": 8, "gsis_id": "p2",
                 "full_name": "Player Two", "report_status": "Questionable",
                 "practice_status": "Limited Participation in Practice"},
                {"season": 2026, "season_type": "REG", "week": 8, "gsis_id": "p3",
                 "full_name": "Player Three", "report_status": "Out",
                 "practice_status": "Did Not Participate In Practice"},
            ])
            report = td_predictor_v5.load_injury_report(2026, 8)
            got = dict(zip(report.player_id, report.injury_status))
            self.assertEqual(got, {"p1": "Unknown", "p2": "Questionable", "p3": "Out"})
            self.assertTrue(report.attrs["week_report_available"])
        finally:
            td_predictor_v5.nflreadpy.load_injuries = original

    def test_injury_status_normalizer_does_not_infer_active(self):
        from td_predictor_v5 import normalize_injury_status
        self.assertEqual(normalize_injury_status(None), "Unknown")
        self.assertEqual(normalize_injury_status(""), "Unknown")
        self.assertEqual(normalize_injury_status("Active"), "Active")
        self.assertEqual(normalize_injury_status("Doubtful"), "Doubtful")
        self.assertEqual(normalize_injury_status("Injured Reserve"), "IR")



    def test_game_state_uses_scheduled_kickoff_and_final_scores(self):
        import pandas as pd
        from datetime import datetime, timezone
        from td_predictor_v5 import get_week_game_statuses

        schedule = pd.DataFrame([{
            "season": 2026, "week": 7, "game_type": "REG", "game_id": "g1",
            "home_team": "PHI", "away_team": "DAL", "gameday": "2026-10-26",
            "gametime": "20:15", "home_score": None, "away_score": None,
        }])
        before = datetime(2026, 10, 27, 0, 14, tzinfo=timezone.utc)
        after = datetime(2026, 10, 27, 0, 16, tzinfo=timezone.utc)
        self.assertEqual(set(get_week_game_statuses(schedule, 2026, 7, before).values()), {"Upcoming"})
        self.assertEqual(set(get_week_game_statuses(schedule, 2026, 7, after).values()), {"In Progress"})
        schedule.loc[0, ["home_score", "away_score"]] = [24, 20]
        self.assertEqual(set(get_week_game_statuses(schedule, 2026, 7, before).values()), {"Final"})

    def test_injury_loader_marks_absent_week_report_unavailable(self):
        import pandas as pd
        import td_predictor_v5

        original = td_predictor_v5.nflreadpy.load_injuries
        try:
            td_predictor_v5.nflreadpy.load_injuries = lambda seasons: pd.DataFrame([
                {"season": 2026, "season_type": "REG", "week": 7, "gsis_id": "p1",
                 "full_name": "Player One", "report_status": "Questionable"},
            ])
            report = td_predictor_v5.load_injury_report(2026, 8)
            self.assertTrue(report.empty)
            self.assertFalse(report.attrs["week_report_available"])
        finally:
            td_predictor_v5.nflreadpy.load_injuries = original

    def test_training_data_requires_completed_week_provenance_and_cutoff(self):
        import pandas as pd
        from evaluation_utils import validate_training_data_frame

        valid = pd.DataFrame([{
            "player_id": "p1", "game_id": "g1", "season": 2025, "week": 8,
            "actual_td": 1, "td_score": 55.0, "td_estimate": 8.0,
            "week_complete": True, "prediction_origin": "retrospective_backfill",
            "prediction_generated_at": "2026-10-26T20:00:00+00:00",
            "feature_cutoff_season": 2025, "feature_cutoff_week": 7,
        }])
        validate_training_data_frame(valid)
        incomplete = valid.copy()
        incomplete["week_complete"] = False
        with self.assertRaisesRegex(ValueError, "not verified complete"):
            validate_training_data_frame(incomplete)
        leaked = valid.copy()
        leaked["feature_cutoff_week"] = 8
        with self.assertRaisesRegex(ValueError, "pre-week cutoff"):
            validate_training_data_frame(leaked)
        legacy = valid.drop(columns=["prediction_generated_at"])
        with self.assertRaisesRegex(ValueError, "lacks reliability metadata"):
            validate_training_data_frame(legacy)


    def test_v6_holdout_excludes_same_and_later_seasons_from_training(self):
        import pandas as pd
        from model_v6 import chronological_holdout

        frame = pd.DataFrame({"season": [2023, 2024, 2025, 2026], "x": [1, 2, 3, 4]})
        train, test = chronological_holdout(frame, 2025)
        self.assertEqual(set(train.season), {2023, 2024})
        self.assertEqual(set(test.season), {2025})

if __name__ == "__main__":
    unittest.main()
