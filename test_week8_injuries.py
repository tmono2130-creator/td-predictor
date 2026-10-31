"""Synthetic injury identity/uncertainty regressions; never production inputs."""
import unittest
import pandas as pd
from weekly_sources import FreshSources
from weekly_schedule import utc


class InjuryScopeTests(unittest.TestCase):
    def report(self, rows, roster=None):
        source = FreshSources({'injuries': lambda _: pd.DataFrame(rows)})
        return source.injuries(2026, 8, utc('2026-10-30T23:00:00Z'), roster=roster)

    def test_completed_game_reports_do_not_claim_target_player_coverage(self):
        roster = pd.DataFrame([dict(player_id='00-0030001', team='SEA')])
        report = self.report([dict(season=2026, week=8, gsis_id='00-0030002', team='GB', report_status='Out')], roster)
        self.assertTrue(report.empty)
        self.assertFalse(report.attrs['week_report_available'])

    def test_prior_team_and_prior_season_reports_do_not_follow_identity(self):
        roster = pd.DataFrame([dict(player_id='00-0030001', team='SEA')])
        report = self.report([
            dict(season=2026, week=8, gsis_id='00-0030001', team='GB', report_status='Out'),
            dict(season=2025, week=8, gsis_id='00-0030001', team='SEA', report_status='Out'),
            dict(season=2026, week=8, gsis_id='00-0030001', team='SEA', report_status=None)], roster)
        self.assertEqual(report.injury_status.tolist(), ['Unknown'])
        self.assertFalse(report.attrs['week_report_available'])

    def test_explicit_target_designation_keeps_existing_v5_normalization(self):
        roster = pd.DataFrame([dict(player_id='00-0030001', team='SEA')])
        report = self.report([dict(week=8, gsis_id='00-0030001', team='SEA', report_status='Questionable')], roster)
        self.assertEqual(report.injury_status.tolist(), ['Questionable'])
        self.assertTrue(report.attrs['week_report_available'])

    def test_unordered_conflicts_and_malformed_timestamps_fail(self):
        with self.assertRaisesRegex(ValueError, 'Conflicting injury'):
            self.report([dict(week=8, gsis_id='00-0030001', report_status=x) for x in ('Out', 'Active')])
        with self.assertRaisesRegex(ValueError, 'Malformed injury'):
            self.report([dict(week=8, gsis_id='00-0030001', report_status='Out', date_modified='broken')])

    def test_missing_team_evidence_cannot_attach_injury_to_roster(self):
        with self.assertRaisesRegex(ValueError, 'team identity'):
            self.report([dict(week=8, gsis_id='00-0030001', report_status='Out')],
                        pd.DataFrame([dict(player_id='00-0030001', team='SEA')]))

    def test_conflicting_timestamp_ties_fail_and_latest_explicit_update_wins(self):
        rows = [dict(week=8, gsis_id='00-0030001', report_status=x, date_modified='2026-10-30T12:00:00Z') for x in ('Out', 'Questionable')]
        with self.assertRaisesRegex(ValueError, 'Conflicting injury'):
            self.report(rows)
        rows[1]['date_modified'] = '2026-10-30T13:00:00Z'
        self.assertEqual(self.report(rows).injury_status.tolist(), ['Questionable'])

    def test_unrelated_malformed_timestamp_does_not_block_target_players(self):
        report = self.report([dict(week=8, gsis_id='00-0030002', team='GB', report_status='Out', date_modified='broken')],
                             pd.DataFrame([dict(player_id='00-0030001', team='SEA')]))
        self.assertTrue(report.empty)
