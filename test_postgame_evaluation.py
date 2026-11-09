import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from postgame_evaluation import evaluate, load_forecast, metrics, score_summary, write_report


def fixture():
    games = [dict(game_id='2026_09_JAX_BAL', season=2026, week=9, game_type='REG', away_team='JAX', home_team='BAL',
                  kickoff_utc='2026-11-06T01:15:00Z', away_score=14, home_score=21),
             dict(game_id='2026_09_BUF_MIN', season=2026, week=9, game_type='REG', away_team='BUF', home_team='MIN',
                  kickoff_utc='2026-11-10T01:15:00Z', away_score='', home_score='')]
    board = {'meta': {'season': 2026, 'week': 9, 'generated_at': '2026-11-05T20:00:00Z', 'games': copy.deepcopy(games)},
             'rows': [dict(game_id=games[0]['game_id'], player_id='00-0000001', player='Test one', team='JAX', position='RB', td_estimate=20, td_score=1),
                      dict(game_id=games[0]['game_id'], player_id='00-0000002', player='Test two', team='BAL', position='WR', td_estimate=80, td_score=2),
                      dict(game_id=games[1]['game_id'], player_id='00-0000003', player='Test pending', team='BUF', position='QB', td_estimate=10, td_score=1)]}
    pbp = pd.DataFrame([dict(game_id=games[0]['game_id'], play_id=1, desc='TD', play_type='run', touchdown=1,
                             td_player_id='00-0000001', td_team='JAX', two_point_attempt=0, return_touchdown=0, rush_touchdown=1, pass_touchdown=0,
                             total_home_score=0, total_away_score=6),
                        dict(game_id=games[0]['game_id'], play_id=2, desc='END GAME', play_type='no_play', touchdown=0,
                             total_home_score=21, total_away_score=14)])
    stats = pd.DataFrame([dict(game_id=games[0]['game_id'], season=2026, week=9, team='JAX', player_id='00-0000001', rushing_tds=1, receiving_tds=0, carries=2),
                          dict(game_id=games[0]['game_id'], season=2026, week=9, team='BAL', player_id='00-0000002', rushing_tds=0, receiving_tds=0, targets=2)])
    return board, None, None, {'source_metadata': {}}, {'board.json': 'a'*64, 'receipt.json': 'b'*64}, games, pbp, stats, '2026-11-09T19:00:00Z'


class PostgameTests(unittest.TestCase):
    def test_metrics_hand_calculation_and_single_class(self):
        rows = [{'actual_td': False, 'estimate_pct': 20}, {'actual_td': True, 'estimate_pct': 80}]
        result = metrics(rows)
        self.assertAlmostEqual(result['brier'], .04)
        self.assertAlmostEqual(result['log_loss'], -math.log(.8))
        self.assertEqual(result['auc'], 1)
        self.assertIsNone(metrics(rows[:1])['auc'])
        self.assertEqual(metrics([])['n'], 0)
        for value in [float('nan'), -1, 101]:
            with self.assertRaises(ValueError):
                metrics([{'actual_td': True, 'estimate_pct': value}])

    def test_partial_week_does_not_change_forecasts_or_label_pending_game(self):
        args = fixture()
        original = copy.deepcopy(args[0])
        report = evaluate(*args)
        self.assertEqual((report['games_completed'], report['games_pending'], report['status']), (1, 1, 'partial'))
        self.assertEqual([p['actual_td'] for p in report['players']], [True, False, None])
        self.assertEqual(args[0], original)
        self.assertEqual(report['missing_labels'], {'pending_game': 1})

    def test_score_presence_alone_does_not_establish_final(self):
        args = list(fixture())
        args[6] = args[6].iloc[:1].copy()
        report = evaluate(*args)
        self.assertEqual(report['games_completed'], 0)
        self.assertTrue(all(p['actual_td'] is None for p in report['players']))

    def test_missing_malformed_or_conflicting_evidence_stays_unknown(self):
        for value in [None, float('nan'), -1, True, 'bad']:
            args = list(fixture())
            args[7]['receiving_tds'] = args[7].receiving_tds.astype(object)
            args[7].loc[1, 'receiving_tds'] = value
            self.assertIsNone(evaluate(*args)['players'][1]['actual_td'])
        args = list(fixture()); args[7].loc[1, 'team'] = 'JAX'
        self.assertEqual(evaluate(*args)['players'][1]['outcome_reason'], 'player_team_conflict')
        args = list(fixture()); args[7].loc[1, 'rushing_tds'] = 1
        self.assertEqual(evaluate(*args)['players'][1]['outcome_reason'], 'stats_pbp_touchdown_conflict')

    def test_missing_stat_row_is_not_a_confirmed_negative(self):
        args = list(fixture()); args[7] = args[7].iloc[:1]
        self.assertIsNone(evaluate(*args)['players'][1]['actual_td'])

    def test_duplicate_identity_and_changed_schedule_fail_closed(self):
        args = list(fixture()); args[7] = pd.concat([args[7], args[7].iloc[:1]])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            evaluate(*args)
        args = list(fixture()); args[5][0]['home_team'] = 'KC'
        with self.assertRaisesRegex(ValueError, 'identity'):
            evaluate(*args)

    def test_unidentified_td_blocks_negative_labels_and_passing_td_is_not_passer_td(self):
        args = list(fixture()); args[6].loc[0, 'td_player_id'] = None
        self.assertIsNone(evaluate(*args)['players'][1]['actual_td'])
        args = list(fixture()); args[0]['rows'][1]['position'] = 'QB'
        args[7]['passing_tds'] = [0, 3]
        self.assertIs(evaluate(*args)['players'][1]['actual_td'], False)

    def test_snapshot_tampering_rejected_before_evaluation(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            p = Path(root)
            (p/'receipt.json').write_text(json.dumps({'board_sha256': 'a'*64, 'breakdowns_sha256': 'b'*64}))
            (p/'board.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                load_forecast(p)

    def test_immutable_idempotent_export_and_new_revision_after_final(self):
        report = evaluate(*fixture())
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            first = write_report(report, root, {})
            original = (first/'evaluation.json').read_bytes()
            report['evaluated_as_of'] = '2026-11-09T20:00:00+00:00'
            self.assertEqual(write_report(report, root, {'updated_retrieval': True}), first)
            self.assertEqual((first/'evaluation.json').read_bytes(), original)
            args = list(fixture())
            args[5][-1].update(away_score=17, home_score=24)
            args[6] = pd.concat([args[6], pd.DataFrame([{'game_id': '2026_09_BUF_MIN', 'play_id': 1, 'desc': 'END GAME',
                                                       'play_type': 'no_play', 'touchdown': 0, 'total_home_score': 24, 'total_away_score': 17}])])
            args[-1] = '2026-11-10T06:00:00Z'
            final = evaluate(*args)
            self.assertEqual(final['status'], 'complete')
            self.assertNotEqual(write_report(final, root, {}), first)
            self.assertEqual((first/'evaluation.json').read_bytes(), original)
            bad = copy.deepcopy(report); bad['players'][-1]['actual_td'] = False
            with self.assertRaisesRegex(ValueError, 'game state'):
                write_report(bad, root, {})
            (first/'evaluation.json').write_bytes(original+b' ')
            with self.assertRaisesRegex(ValueError, 'hash binding'):
                write_report(report, root, {})

    def test_error_metrics_known_values(self):
        games = [{'status': 'final', 'prediction': {'away': 21, 'home': 24}, 'actual': {'away': 20, 'home': 27}}]
        result = score_summary(games)
        self.assertEqual(result['team_score_mae'], 2)
        self.assertEqual(result['total_mae'], 2)
        self.assertEqual(result['margin_mae'], 4)
        self.assertEqual(result['winner_accuracy'], 1)


if __name__ == '__main__':
    unittest.main()
