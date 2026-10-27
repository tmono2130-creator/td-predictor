import unittest

import pandas as pd

from model_v6 import _probability_metrics, _prior_rate_baselines, validate_evaluation_data
from evaluation_utils import require_complete_regular_week
from historical_data import build_actual_player_games


def fixtures():
    schedule = pd.DataFrame([{
        "season": 2024, "week": 1, "game_type": "REG", "game_id": "g1",
        "home_team": "BUF", "away_team": "KC", "home_score": 20, "away_score": 17,
        "gameday": "2024-09-05", "gametime": "20:20",
    }])
    stats = pd.DataFrame([
        {"season": 2024, "week": 1, "season_type": "REG", "player_id": "gs-rb",
         "game_id": "g1", "team": "BUF", "opponent_team": "KC", "position": "RB",
         "player_display_name": "A Runner", "rushing_tds": 2, "receiving_tds": 1,
         "passing_tds": 0},
        {"season": 2024, "week": 1, "season_type": "REG", "player_id": "gs-qb",
         "game_id": "g1", "team": "BUF", "opponent_team": "KC", "position": "QB",
         "player_display_name": "B Passer", "rushing_tds": 0, "receiving_tds": 0,
         "passing_tds": 3},
    ])
    snaps = pd.DataFrame([
        {"season": 2024, "week": 1, "game_type": "REG", "game_id": "g1",
         "team": "BUF", "position": "RB", "offense_snaps": 25, "pfr_player_id": "p-rb",
         "player": "A Runner"},
        {"season": 2024, "week": 1, "game_type": "REG", "game_id": "g1",
         "team": "BUF", "position": "QB", "offense_snaps": 50, "pfr_player_id": "p-qb",
         "player": "B Passer"},
    ])
    crosswalk = pd.DataFrame([{"pfr_id": "p-rb", "gsis_id": "gs-rb"},
                              {"pfr_id": "p-qb", "gsis_id": "gs-qb"}])
    return schedule, stats, snaps, crosswalk


class HistoricalOutcomeTests(unittest.TestCase):
    def build(self, schedule=None, stats=None, snaps=None, crosswalk=None):
        a, b, c, d = fixtures()
        return build_actual_player_games(stats if stats is not None else b,
                                         snaps if snaps is not None else c,
                                         crosswalk if crosswalk is not None else d,
                                         schedule if schedule is not None else a, 2024, 1)

    def test_td_labels_exclude_passing_and_keep_multiple_scores(self):
        rows = self.build().set_index("player_id")
        self.assertEqual(rows.loc["gs-rb", "actual_td"], 1)
        self.assertEqual(rows.loc["gs-rb", "actual_td_count"], 3)
        self.assertEqual(rows.loc["gs-qb", "actual_td"], 0)
        self.assertEqual(rows.loc["gs-qb", "actual_td_count"], 0)

    def test_unplayed_week_is_rejected(self):
        schedule, *_ = fixtures()
        schedule.loc[0, ["home_score", "away_score"]] = [None, None]
        with self.assertRaisesRegex(ValueError, "not verified complete|incomplete"):
            self.build(schedule=schedule)

    def test_no_snap_zero_td_players_are_not_included(self):
        _, _, snaps, _ = fixtures()
        snaps = snaps.iloc[0:0]
        rows = self.build(snaps=snaps)
        self.assertEqual(set(rows.player_id), {"gs-rb"})

    def test_duplicate_player_game_stats_rejected(self):
        _, stats, *_ = fixtures()
        stats = pd.concat([stats, stats.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "duplicate player/game"):
            self.build(stats=stats)

    def test_name_matched_pfr_participant_keeps_known_td_outcome(self):
        _, stats, snaps, _ = fixtures()
        stats = pd.concat([stats, stats.iloc[[0]].assign(player_id="gs-rb-alt", rushing_tds=0,
                                                        receiving_tds=0)], ignore_index=True)
        rows = self.build(stats=stats, crosswalk=pd.DataFrame(columns=["pfr_id", "gsis_id"]))
        pfr_row = rows[rows.player_id.eq("pfr:p-rb")].iloc[0]
        self.assertEqual(pfr_row.actual_td, 1)
        self.assertEqual(pfr_row.actual_td_count, 3)
        self.assertEqual(pfr_row.participation_source, "offensive_snap+offensive_td_stat")
    def test_mismatched_team_is_rejected(self):
        _, _, snaps, _ = fixtures()
        snaps.loc[0, "team"] = "MIA"
        with self.assertRaisesRegex(ValueError, "does not match schedule"):
            self.build(snaps=snaps)


class EvaluationIntegrityTests(unittest.TestCase):
    def test_brier_log_loss_and_calibration_use_probabilities(self):
        metrics = _probability_metrics([0, 1], [0.2, 0.8])
        self.assertAlmostEqual(metrics["brier"], 0.04)
        self.assertAlmostEqual(metrics["log_loss"], -__import__("math").log(0.8))
        self.assertAlmostEqual(metrics["bias_pred_minus_actual"], 0)
        self.assertEqual(metrics["auc"], 1.0)

    def test_baseline_never_uses_same_week_outcomes(self):
        rows = pd.DataFrame([
            {"season": 2023, "week": 1, "game_id": "g1", "player_id": "p", "position": "RB", "actual_td": 1},
            {"season": 2023, "week": 2, "game_id": "g2", "player_id": "p", "position": "RB", "actual_td": 0},
            {"season": 2023, "week": 2, "game_id": "g3", "player_id": "q", "position": "RB", "actual_td": 1},
        ])
        train = rows[rows.season == 2023]
        _, recent, _, _ = _prior_rate_baselines(rows, train)
        self.assertAlmostEqual(recent.loc[1], 0.75, places=5)
        self.assertAlmostEqual(recent.loc[2], 2 / 3, places=5)

    def test_validation_rejects_cutoff_leakage(self):
        frame = pd.DataFrame([{
            "player_id": "p1", "game_id": "g1", "season": 2025, "week": 8,
            "position": "RB", "actual_td": 0, "actual_td_count": 0, "td_score": 50,
            "prediction_origin": "retrospective_backfill", "feature_cutoff_season": 2025,
            "feature_cutoff_week": 8,
        }])
        with self.assertRaisesRegex(ValueError, "cutoff week"):
            validate_evaluation_data(frame)


if __name__ == "__main__":
    unittest.main()
