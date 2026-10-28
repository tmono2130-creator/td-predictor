"""Safety regressions use fixtures only; never generate live predictions."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import export_json
from historical_data import _prepare_stats, build_actual_player_games
from test_historical_evaluation import fixtures


def roster_row(**changes):
    row = dict(season=2026, week=8, game_type='REG', gsis_id='00-0030001',
               full_name='Fixture Rookie', team='KC', position='RB', status='ACT')
    row.update(changes)
    return row


class BoundaryRegressionTests(unittest.TestCase):
    def test_legacy_export_rejects_live_directory_before_writing(self):
        live = Path(export_json.__file__).parent / 'td-predictor-web/public/data'
        # Pure path preflight: this test never attempts a production write.
        with self.assertRaisesRegex(ValueError, 'reviewed'):
            export_json.assert_local_export_path(live)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            export_json.assert_local_export_path(folder)

    def test_live_candidate_publication_requires_review_branch(self):
        from publication_policy import require_review_checkout
        live = Path(export_json.__file__).parent / 'td-predictor-web/public/data'
        with patch('publication_policy.subprocess.check_output', return_value=b'main\n'):
            with self.assertRaisesRegex(ValueError, 'review branch'):
                require_review_checkout(live)

    def test_legacy_cli_refuses_live_output_before_loading_model(self):
        live = Path(export_json.__file__).parent / 'td-predictor-web/public/data'
        with patch('sys.argv',['export_json.py','--season','2026','--week','9','--out',str(live)]), \
             patch.object(export_json,'get_predictions') as score:
            with self.assertRaises(SystemExit):export_json.main()
            score.assert_not_called()

    def test_live_path_descendants_and_parent_traversal_are_rejected(self):
        live = Path(export_json.__file__).parent / 'td-predictor-web/public/data'
        for path in (live/'manifest.json',live/'2026/week-9',live/'../data'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):export_json.assert_local_export_path(path)


class OutcomeRegressionTests(unittest.TestCase):
    def test_future_live_and_unverified_final_outcomes_stay_null(self):
        from outcome_semantics import forecast_outcomes
        frame = pd.DataFrame([dict(player_id='p',game_id='g',game_status=status,actual_scored_td=False)
                              for status in ('Upcoming','In Progress','Final')])
        self.assertTrue(forecast_outcomes(frame).isna().all())

    def test_only_verified_final_counts_become_booleans(self):
        from outcome_semantics import forecast_outcomes
        rows=pd.DataFrame([dict(player_id=str(i),game_id='g',game_status='Final') for i in range(3)])
        evidence=pd.DataFrame([dict(player_id='0',game_id='g',actual_td_count=0,outcome_verified=True,game_complete=True),
                               dict(player_id='1',game_id='g',actual_td_count=2,outcome_verified=True,game_complete=True)])
        result=forecast_outcomes(rows,evidence).tolist()
        self.assertEqual(result[:2],[False,True]);self.assertIsNone(result[2])

    def test_live_rows_cannot_receive_verified_final_evidence(self):
        from outcome_semantics import forecast_outcomes
        for status in ('Upcoming','In Progress'):
            rows=pd.DataFrame([dict(player_id='p',game_id='g',game_status=status)])
            evidence=pd.DataFrame([dict(player_id='p',game_id='g',actual_td_count=1,outcome_verified=True,game_complete=True)])
            self.assertIsNone(forecast_outcomes(rows,evidence).iloc[0])

    def test_duplicate_and_malformed_evidence_are_rejected(self):
        from outcome_semantics import forecast_outcomes
        rows=pd.DataFrame([dict(player_id='p',game_id='g',game_status='Final')])
        evidence=pd.DataFrame([dict(player_id='p',game_id='g',actual_td_count='bad',outcome_verified=True,game_complete=True)])
        with self.assertRaises(ValueError):forecast_outcomes(rows,evidence)
        evidence['actual_td_count']=0
        with self.assertRaises(ValueError):forecast_outcomes(rows,pd.concat([evidence,evidence]))

    def test_serializer_does_not_trust_legacy_final_annotations(self):
        rows=pd.DataFrame([dict(player_id='p',game_id='g',game_status='Final',team='BUF',opponent='KC',
                                position='RB',player='Fixture',td_score=50,td_estimate=10,injury_status='Unknown',
                                actual_scored_td=False)])
        future=pd.DataFrame([dict(game_id='g',season=2099,week=8,game_type='REG',home_team='BUF',away_team='KC',
                                  gameday='2099-10-30',gametime='20:15',home_score=None,away_score=None)])
        evidence=pd.DataFrame([dict(player_id='p',game_id='g',actual_td_count=0,outcome_verified=True,game_complete=True)])
        result=export_json.board_payload(rows,2099,8,'composite',[],future,evidence)
        self.assertIsNone(result['rows'][0]['actual_scored_td'])

    def test_historical_missing_or_bad_touchdown_fields_fail_closed(self):
        _, stats, _, _ = fixtures()
        for field in ('rushing_tds','receiving_tds'):
            with self.subTest(field=field):
                with self.assertRaises(ValueError): _prepare_stats(stats.drop(columns=field),2024,1)
        for value in (None,'invalid',float('inf'),-1,0.5,True):
            bad=stats.copy();bad['rushing_tds']=bad.rushing_tds.astype(object);bad.at[0,'rushing_tds']=value
            with self.subTest(value=value):
                with self.assertRaises(ValueError): _prepare_stats(bad,2024,1)

    def test_participation_without_outcome_evidence_is_unknown(self):
        schedule,stats,snaps,crosswalk=fixtures()
        result=build_actual_player_games(stats[stats.player_id.ne('gs-qb')],snaps,crosswalk,schedule,2024,1)
        self.assertTrue(pd.isna(result.set_index('player_id').loc['gs-qb','actual_td']))


class RosterRegressionTests(unittest.TestCase):
    def resolve(self, rows, known=None, live=None):
        from roster_eligibility import resolve_roster
        known = pd.DataFrame([{'gsis_id':'00-0030001'}]) if known is None else known
        return resolve_roster(pd.DataFrame(rows),pd.DataFrame(live or []),known,2026,8,{'KC'})

    def test_authoritative_week_and_active_rookie(self):
        pool,audit=self.resolve([roster_row(),roster_row(week=7,status='CUT')],live=[roster_row(status='CUT')])
        self.assertEqual(pool.player_id.tolist(),['00-0030001'])
        self.assertEqual(audit['scope'],'target-week roster')

    def test_known_exclusions_and_unrelated_bad_id(self):
        rows=[roster_row(),roster_row(gsis_id='bad',team='BUF'),
              *[roster_row(gsis_id='unresolved',status=s) for s in ('CUT','RET','RES','DEV')]]
        pool,audit=self.resolve(rows)
        self.assertEqual(len(pool),1)
        self.assertEqual(audit['counts']['exclude'],4)

    def test_unknown_status_is_pending_not_silently_excluded(self):
        from roster_eligibility import EligibilityError
        for status in ('',None,'INA','NEW_STATUS'):
            with self.subTest(status=status):
                with self.assertRaises(EligibilityError) as error:self.resolve([roster_row(status=status)])
                self.assertEqual(error.exception.audit['counts']['pending'],1)

    def test_name_alone_never_resolves_identity(self):
        from roster_eligibility import EligibilityError
        with self.assertRaises(EligibilityError):
            self.resolve([roster_row(gsis_id=None)],known=pd.DataFrame([{'gsis_id':'00-0030001','display_name':'Fixture Rookie'}]))

    def test_two_stable_identifiers_can_resolve_missing_gsis(self):
        known=pd.DataFrame([{'gsis_id':'00-0030001','pfr_id':'fixture1','espn_id':'123'}])
        pool,audit=self.resolve([roster_row(gsis_id=None,pfr_id='fixture1',espn_id='123')],known=known)
        self.assertEqual(pool.player_id.tolist(),['00-0030001'])
        self.assertEqual(audit['decisions'][0]['identity_method'],'corroborated-stable-ids')

    def test_injury_designation_does_not_change_membership(self):
        for injury in ('Unknown','Questionable','Out'):
            pool,_=self.resolve([roster_row(status=' act ',injury_status=injury)])
            self.assertEqual(len(pool),1)

    def test_conflicting_ids_and_transfers_block_instead_of_guessing(self):
        from roster_eligibility import EligibilityError
        with self.assertRaises(EligibilityError):
            self.resolve([roster_row(player_id='00-0030002')])
        with self.assertRaises(EligibilityError):
            self.resolve([roster_row(),roster_row()])

    def test_missing_crosswalk_is_pending_and_does_not_drop_rookie(self):
        from roster_eligibility import EligibilityError
        with self.assertRaises(EligibilityError) as error:
            self.resolve([roster_row(gsis_id='00-0030002')])
        self.assertEqual(error.exception.audit['decisions'][0]['reason'],'authoritative-id-not-in-crosswalk')

    def test_one_alias_or_conflicting_aliases_cannot_resolve_identity(self):
        from roster_eligibility import EligibilityError
        known=pd.DataFrame([dict(gsis_id='00-0030001',pfr_id='a',espn_id='1'),
                            dict(gsis_id='00-0030002',pfr_id='b',espn_id='2')])
        for values in (dict(pfr_id='a'),dict(pfr_id='a',espn_id='2')):
            with self.assertRaises(EligibilityError):
                self.resolve([roster_row(gsis_id=None,**values)],known=known)

    def test_wrong_season_and_future_roster_cannot_be_used(self):
        from roster_eligibility import resolve_roster
        known=pd.DataFrame([dict(gsis_id='00-0030001')])
        for row in (roster_row(season=2025),roster_row(week=9)):
            with self.assertRaises(ValueError):
                resolve_roster(pd.DataFrame(),pd.DataFrame([row]),known,2026,8,{'KC'})

    def test_historical_rosters_cannot_fall_back_to_current_membership(self):
        from roster_eligibility import resolve_roster
        with self.assertRaisesRegex(ValueError,'week-specific'):
            resolve_roster(pd.DataFrame(),pd.DataFrame([roster_row()]),pd.DataFrame([dict(gsis_id='00-0030001')]),2026,8,{'KC'},True)


class ReceiptAndScoringRegressionTests(unittest.TestCase):
    def test_pending_or_inactive_audit_cannot_validate(self):
        from test_weekly_automation import candidate,rewrite,NOW
        from weekly_storage import validate_candidate
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root,_=candidate(Path(folder)/'candidate')
            audit={'policy_version':'week-aware-v1','season':2026,'week':1,
                   'scheduled_teams':['KC','BUF'],
                   'counts':{'include':2,'exclude':0,'pending':0},'decisions':[
                       dict(player_id='00-0030001',team='KC',position='RB',decision='include',roster_status='ACT'),
                       dict(player_id='00-0030002',team='BUF',position='RB',decision='include',roster_status='ACT')]}
            rewrite(root,'receipt.json',lambda r:r['source_metadata'].update(roster_eligibility=copy.deepcopy(audit)))
            validate_candidate(root,now=NOW)
            rewrite(root,'receipt.json',lambda r:r['source_metadata']['roster_eligibility']['decisions'][0].update(roster_status='CUT'))
            with self.assertRaisesRegex(ValueError,'eligibility audit'):validate_candidate(root,now=NOW)

    def test_v5_formula_and_outputs_match_reviewed_baseline_for_identical_pool(self):
        import td_predictor_v5 as v5
        from weekly_generation import score_v5
        from weekly_sources import STAT_COLUMNS,PBP_REQUIRED
        from test_weekly_automation import game,NOW
        from weekly_schedule import plan_week
        # Frozen from the reviewed M5B source, works in shallow hosted checkouts.
        self.assertEqual(hashlib.sha256(Path(v5.__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
                         'f1af81376bf6de6881c0a457696e39bd84d488a6536de2f402b73b851862caba')
        roster=pd.DataFrame([dict(player_id='00-0030001',model_player_name='Fixture A',team='KC',position='RB'),
                             dict(player_id='00-0030002',model_player_name='Fixture B',team='BUF',position='WR')])
        histories={}
        for year in (2023,2024,2025):
            records=[]
            for r in roster.itertuples():
                data={c:1.0 for c in STAT_COLUMNS}
                data.update(player_id=r.player_id,player_display_name=r.model_player_name,position=r.position,
                            team=r.team,season=year,week=1,season_type='REG')
                records.append(data)
            histories[year]=pd.DataFrame(records)
        plays=[]
        for r in roster.itertuples():
            data={c:0 for c in PBP_REQUIRED}
            data.update(season=2025,week=1,season_type='REG',yardline_100=5,play_type='run',
                        rusher_player_id=r.player_id,receiver_player_id=None)
            plays.append(data)
        injuries=pd.DataFrame([dict(player_id=r.player_id,injury_status='Unknown') for r in roster.itertuples()])
        args=(roster,histories,pd.DataFrame(plays),injuries,plan_week([game()],NOW))
        actual=score_v5(*copy.deepcopy(args)).sort_values('player_id').reset_index(drop=True)
        # These exact outputs were compared to origin/main before recording them.
        self.assertEqual(actual.td_score.tolist(),[85.5,85.5])
        self.assertEqual(actual.td_estimate.tolist(),[18.085384615384616,18.085384615384616])


if __name__ == '__main__':
    unittest.main()
