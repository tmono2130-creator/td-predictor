import copy
import unittest

import pandas as pd

from data_quality import diagnose
from test_postgame_evaluation import fixture


class DataQualityTests(unittest.TestCase):
    def args(self):
        board, _, _, receipt, _, schedule, _, _, _ = fixture()
        teams = ['JAX', 'BAL', 'BUF', 'MIN']
        roster = pd.DataFrame([{'season': 2026, 'week': 9, 'team': team, 'gsis_id': f'00-{i+1:07}',
                                'position': 'RB', 'status': 'ACT', 'full_name': f'TEST {i}'} for i, team in enumerate(teams)])
        known = pd.DataFrame({'gsis_id': roster.gsis_id})

        for r in board['rows']:
            r['opponent'] = next(g['home_team'] if r['team'] == g['away_team'] else g['away_team'] for g in schedule if g['game_id'] == r['game_id'])
        return [board, receipt, roster, known, pd.DataFrame(), schedule, '2026-11-05T20:00:00Z']

    def test_optional_injury_absence_keeps_valid_roster_and_unknown_explicit(self):
        args = self.args(); before = copy.deepcopy(args[0]); result = diagnose(*args)
        self.assertEqual(result['roster_counts']['include'], 4)
        self.assertEqual(result['injury_source_rows'], 0)
        self.assertNotIn('Active', result['injury_report_status_values'])
        self.assertEqual(args[0], before)

    def test_inactive_is_pending_and_never_release_or_active(self):
        args = self.args(); args[2].loc[0, 'status'] = 'INA'; result = diagnose(*args)
        self.assertEqual(result['roster_counts']['pending'], 1)
        self.assertEqual(result['pending'][0]['reason'], 'inactive-status-needs-game-specific-resolution')
        self.assertFalse(result['ready_for_candidate'])

    def test_unrelated_identity_cannot_block_scheduled_teams(self):
        args = self.args()
        args[2] = pd.concat([args[2], pd.DataFrame([{'season': 2026, 'week': 9, 'team': 'KC', 'gsis_id': 'broken', 'position': 'RB', 'status': 'ACT'}])])
        self.assertEqual(diagnose(*args)['roster_counts']['pending'], 0)

    def test_duplicate_predictions_and_wrong_matchups_flagged(self):
        args = self.args(); args[0]['rows'].append(copy.deepcopy(args[0]['rows'][0]))
        for r in args[0]['rows']: r['opponent'] = 'KC'
        kinds = [i['kind'] for i in diagnose(*args)['issues']]
        self.assertIn('duplicate_prediction_identity', kinds)
        self.assertIn('prediction_matchup_identity', kinds)

    def test_future_week_roster_is_not_substituted_for_missing_target_week(self):
        args = self.args(); args[2]['week'] = 10
        result = diagnose(*args)
        self.assertEqual(result['target_week_roster_rows'], 0)
        self.assertFalse(result['ready_for_candidate'])

    def test_quarterback_annotation_does_not_establish_availability(self):
        args = self.args(); args[5][0]['away_qb_id'] = '00-0000001'; args[5][0]['away_qb_name'] = 'TEST QB'
        result = diagnose(*args)
        qb = result['quarterback_annotations'][0]
        self.assertTrue(qb['target_roster_match'])
        self.assertEqual(qb['starting_status'], 'unverified_provider_annotation')

    def test_week10_prime_time_and_munich_timezone_boundaries(self):
        from weekly_schedule import kickoff
        from zoneinfo import ZoneInfo
        thursday = kickoff({'game_id': '2026_10_WAS_NYG', 'gameday': '2026-11-12', 'gametime': '20:15'})
        self.assertEqual(thursday.isoformat(), '2026-11-13T01:15:00+00:00')
        self.assertEqual(thursday.astimezone(ZoneInfo('America/Los_Angeles')).strftime('%m-%d %H:%M'), '11-12 17:15')
        munich = kickoff({'game_id': '2026_10_NE_DET', 'gameday': '2026-11-15', 'gametime': '09:30'})
        self.assertEqual(munich.astimezone(ZoneInfo('Europe/Berlin')).strftime('%H:%M'), '15:30')
        self.assertEqual(munich.astimezone(ZoneInfo('America/Los_Angeles')).strftime('%H:%M'), '06:30')


if __name__ == '__main__':
    unittest.main()
