"""TEST FIXTURES in temporary directories only; never live data or publication."""
import csv
import io
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from weekly_capture import Capture, load_capture, encode, source_url, verified_schedule
from weekly_data import build_from_capture
from weekly_schedule import SCHEDULE_URL, regular_games, plan_week, utc_now, utc
from weekly_sources import STAT_COLUMNS, PBP_REQUIRED
from weekly_storage import load_json, validate_candidate
from roster_eligibility import resolve_roster, EligibilityError
from test_weekly_automation import game


FIXTURE_NOW = utc('2026-10-30T12:00:00Z')


def captures(root, missing=None, status='ACT', weekly_missing=False, missing_ppp=False):
    """Mock HTTP capture of explicitly synthetic inputs, with real current capture clocks."""
    schedule, stats, plays = [], {}, {}
    roster = [dict(season=2026, week=9, game_type='REG', gsis_id=f'00-003000{i}',
                   full_name=f'TEST FIXTURE {i}', team=t, position='RB', status=status)
              for i, t in enumerate(('KC', 'BUF'), 1)]
    for year in range(2023, 2027):
        stats[year], plays[year] = [], []
        for week in range(1, 5):
            day = f'{year}-09-{week*7:02}'
            g = game(season=year, week=week, day=day, complete=True)
            schedule.append(g)
            for i, r in enumerate(roster):
                row = {c: 1. for c in STAT_COLUMNS}
                row.update(player_id=r['gsis_id'], player_display_name=r['full_name'], team=r['team'], position='RB',
                           season=year, week=week, game_id=g['game_id'], season_type='REG')
                stats[year].append(row)
                play = {c: 0 for c in PBP_REQUIRED}
                play.update(game_id=g['game_id'], play_id=i+1, season=year, week=week, season_type='REG',
                            posteam=r['team'], defteam='BUF' if r['team']=='KC' else 'KC', play_type='run',
                            rusher_player_id=r['gsis_id'], receiver_player_id=None, td_team=None, td_player_id=None,
                            yardline_100=50, yards_gained=3, drive=1, desc='TEST FIXTURE rush', return_touchdown=0,
                            extra_point_attempt=0, field_goal_attempt=0, extra_point_result=None,
                            field_goal_result=None, two_point_conv_result=None, total_home_score=24, total_away_score=20)
                plays[year].append(play)
            end = plays[year][-1].copy()
            end.update(play_id=999, play_type=None, desc='END GAME')
            plays[year].append(end)
    schedule.append(game(week=9, day='2026-11-08'))
    # Raw provider schedule has no explicit state; terminal captured PBP is required.
    for g in schedule:
        g.pop('game_status', None)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(schedule[0]))
    writer.writeheader(); writer.writerows(schedule)
    blobs = {SCHEDULE_URL: buf.getvalue().encode()}
    def parquet(frame):
        out = io.BytesIO(); frame.to_parquet(out, index=False); return out.getvalue()
    for year in stats:
        if missing_ppp:
            for play in plays[year]:
                play.pop('field_goal_result', None)
        blobs[source_url('stats', year)] = parquet(pd.DataFrame(stats[year]))
        blobs[source_url('pbp', year)] = parquet(pd.DataFrame(plays[year]))
    blobs[source_url('weekly_rosters', 2026)] = parquet(pd.DataFrame(roster))
    blobs[source_url('players', 2026)] = parquet(pd.DataFrame(roster)[['gsis_id']])
    blobs[source_url('rosters', 2026)] = parquet(pd.DataFrame(roster))
    blobs[source_url('injuries', 2026)] = parquet(pd.DataFrame(columns=['week', 'gsis_id', 'report_status']))
    class Response(io.BytesIO):
        status = 200
        headers = {}
    def opener(request, timeout):
        if request.full_url == missing or (weekly_missing and request.full_url == source_url('weekly_rosters',2026)):
            raise OSError('TEST FIXTURE unavailable source')
        return Response(blobs[request.full_url])
    capture = Capture(root, opener=opener, clock=lambda: FIXTURE_NOW)
    capture.fetch('schedule', SCHEDULE_URL)
    for year in stats:
        for name in ('stats', 'pbp'):
            capture.fetch(f'{name}_{year}', source_url(name, year))
    for name in ('weekly_rosters', 'players', 'injuries'):
        capture.fetch(f'{name}_2026', source_url(name, 2026), optional=name in ('injuries','weekly_rosters'))
    if weekly_missing:
        capture.fetch('rosters_2026', source_url('rosters',2026))
    capture.freeze()
    return capture, schedule, roster, plays


class CaptureReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module in ('weekly_capture', 'weekly_data', 'weekly_storage'):
            patched = patch(module + '.utc_now', return_value=FIXTURE_NOW+timedelta(seconds=1))
            patched.start(); self.addCleanup(patched.stop)

    def test_integrated_both_sidecars_and_identical_offline_replay(self):
        captures(self.root/'inputs')
        result = build_from_capture(self.root/'inputs', self.root/'candidate', self.root/'data', 2026, 9)
        self.assertTrue(result['bundle_status']['three_features'])
        self.assertEqual(result['players_expected'], result['players_generated'])
        self.assertEqual(result['games_generated'], 1)
        with patch('urllib.request.urlopen', side_effect=AssertionError('Replay must be offline')):
            repeated = build_from_capture(self.root/'inputs', self.root/'replay', self.root/'data', 2026, 9, replay=True)
        self.assertEqual(result, repeated)
        self.assertEqual(len(result['artifact_hashes']), 5)
        board, _, receipt = validate_candidate(self.root/'candidate')
        self.assertEqual(board['meta']['model'], 'composite')
        self.assertTrue(all(r['actual_scored_td'] is None for r in board['rows']))
        gp = load_json(self.root/'candidate/game-predictor.json')
        self.assertEqual(gp['meta']['primary_method'], 'baseline')
        self.assertIsNone(gp['meta']['model'])
        self.assertLessEqual(max(r['retrieved_at_utc'] for r in receipt['input_capture']['manifest']['sources'].values()), result['source_cutoff_utc'])

    def test_all_four_requested_bundle_combinations(self):
        for features in ((), ('game',), ('matchup',)):
            with self.subTest(features=features):
                name = '-'.join(features) or 'core'
                captures(self.root/name)
                result = build_from_capture(self.root/name, self.root/(name+'-candidate'), self.root/'data', 2026, 9, features)
                self.assertEqual(len(result['artifact_hashes']), 3+len(features))
                self.assertFalse(result['bundle_status']['three_features'])

    def test_source_hash_tamper_and_immutable_paths(self):
        captures(self.root/'inputs')
        with self.assertRaises(FileExistsError): Capture(self.root/'inputs')
        with (self.root/'inputs/stats_2026.parquet').open('ab') as stream: stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash'): load_capture(self.root/'inputs')
        from publication_policy import REPOSITORY
        with self.assertRaises(ValueError): Capture(REPOSITORY/'td-predictor-web/public/forbidden')

    def test_required_source_failure_cannot_freeze_or_generate(self):
        with self.assertRaisesRegex(RuntimeError, 'Required capture'):
            captures(self.root/'inputs', missing=source_url('stats',2026))
        self.assertFalse((self.root/'inputs/capture.json').exists())
        self.assertFalse((self.root/'candidate').exists())

    def test_pending_membership_blocks_without_override(self):
        captures(self.root/'inputs', status='INA')
        with self.assertRaises(EligibilityError):
            build_from_capture(self.root/'inputs', self.root/'candidate', self.root/'data', 2026, 9)
        self.assertFalse((self.root/'candidate').exists())

    def test_code_change_blocks_replay_and_capture_cannot_be_backdated(self):
        captures(self.root/'inputs')
        with patch('weekly_capture.code_identity', return_value={}):
            with self.assertRaisesRegex(ValueError, 'code'): load_capture(self.root/'inputs')
        manifest = load_json(self.root/'inputs/capture.json')
        manifest['source_cutoff_utc'] = (utc_now()-timedelta(days=10)).isoformat()
        (self.root/'inputs/capture.json').write_bytes(encode(manifest))
        with self.assertRaises(ValueError): load_capture(self.root/'inputs')

    def test_stale_capture_and_kickoff_race_fail(self):
        captures(self.root/'inputs')
        result = build_from_capture(self.root/'inputs', self.root/'candidate', self.root/'data', 2026, 9, ())
        from weekly_schedule import utc
        with self.assertRaises(ValueError):
            validate_candidate(self.root/'candidate', now=utc(result['generated_at'])+timedelta(days=2))
        with patch('weekly_data.utc_now', return_value=utc('2026-11-08T18:00:00Z')):
            with self.assertRaises(ValueError):
                build_from_capture(self.root/'inputs', self.root/'late', self.root/'data', 2026, 9, ())

    def test_missing_weekly_roster_is_not_replaced_by_historical_proof(self):
        captures(self.root/'inputs',weekly_missing=True)
        result=build_from_capture(self.root/'inputs',self.root/'candidate',self.root/'data',2026,9)
        self.assertFalse(result['bundle_status']['three_features'])
        self.assertIn('Target-week roster',result['bundle_status']['unavailable']['matchup'])
        self.assertFalse((self.root/'candidate/matchup-intelligence.json').exists())
        self.assertTrue((self.root/'candidate/game-predictor.json').exists())

    def test_missing_ppp_fields_do_not_fabricate_a_projection(self):
        captures(self.root/'inputs',missing_ppp=True)
        result=build_from_capture(self.root/'inputs',self.root/'candidate',self.root/'data',2026,9)
        self.assertFalse(result['bundle_status']['three_features'])
        self.assertIn('scoring evidence',result['bundle_status']['unavailable']['game'])
        self.assertFalse((self.root/'candidate/game-predictor.json').exists())
        self.assertTrue((self.root/'candidate/matchup-intelligence.json').exists())

    def test_stale_required_source_rejected_even_with_recent_common_cutoff(self):
        captures(self.root/'inputs')
        manifest=load_json(self.root/'inputs/capture.json')
        old=(FIXTURE_NOW-timedelta(days=2)).isoformat()
        manifest['started_at_utc']=old
        manifest['sources']['stats_2026'].update(started_at_utc=old,retrieved_at_utc=old)
        (self.root/'inputs/capture.json').write_bytes(encode(manifest))
        with self.assertRaisesRegex(ValueError,'Stale input'):
            build_from_capture(self.root/'inputs',self.root/'candidate',self.root/'data',2026,9)
        self.assertFalse((self.root/'candidate').exists())

    def test_captured_data_only_pr_deployment_and_rollback_contract(self):
        from test_reviewed_publication import DataPRTests
        from reviewed_publication import validate_change, tree, PREFIX
        from weekly_storage import publish_candidate
        from verify_publication import verify_json, PRODUCTION
        f=DataPRTests('test_valid_data_only_pr_and_complete_coverage')
        f.setUp(); self.addCleanup(f.doCleanups)
        previous=(f.data/'manifest.json').read_bytes()
        captures(self.root/'inputs')
        result=build_from_capture(self.root/'inputs',self.root/'candidate',f.data,2026,9)
        relative=publish_candidate(self.root/'candidate',f.data,now=FIXTURE_NOW+timedelta(seconds=1))
        proposed=f.commit()
        records=[game(week=9,day='2026-11-08')]
        self.assertEqual(validate_change(f.repo,f.head,proposed,'nfl-pm/publication/321-1',records,FIXTURE_NOW+timedelta(seconds=1))['players'],2)
        expected=tree(f.repo,proposed)
        def fetch(url):return expected[PREFIX+url.removeprefix(PRODUCTION+'/data/')]
        self.assertIn(relative+'/game-predictor.json',verify_json(expected,fetch))
        (f.data/'manifest.json').write_bytes(previous)
        restored=f.commit()
        self.assertEqual(validate_change(f.repo,proposed,restored,'nfl-pm/rollback/captured',records,FIXTURE_NOW)['kind'],'rollback')
        for name in result['artifact_hashes']:
            self.assertIn(PREFIX+relative+'/'+name,tree(f.repo,restored))


class TargetAndEligibilityTests(unittest.TestCase):
    def test_scores_alone_never_certify_completion(self):
        row=game(complete=True);row.pop('game_status')
        self.assertFalse(regular_games([row])[0]['complete'])
        row['game_status']='In Progress'
        self.assertFalse(regular_games([row])[0]['complete'])

    def test_terminal_evidence_conflict_is_rejected(self):
        row=game(complete=True)
        pbp=pd.DataFrame([dict(game_id=row['game_id'],play_id=1,desc='END GAME',total_home_score=99,total_away_score=20)])
        with self.assertRaisesRegex(ValueError,'conflict'):verified_schedule([row],{2026:pbp},utc_now())

    def test_remaining_games_are_shared_by_both_sidecar_builders(self):
        from test_game_projection import history, artifact
        from game_projection_artifact import build_artifact
        from test_weekly_automation import NOW
        early=game(day='2026-09-08',complete=True,away='SF',home='SEA')
        target=game()
        plan=plan_week([early,target],NOW)
        out=build_artifact(history(),[early,target],2026,1,NOW,artifact()['meta']['sources'],generated_at=NOW,
                           target_ids=[target['game_id']])
        self.assertEqual(set(out['games']),{target['game_id']})
        with self.assertRaisesRegex(ValueError,'target'):
            build_artifact(history(),[early,target],2026,1,NOW,artifact()['meta']['sources'],generated_at=NOW,target_ids=[])
        self.assertEqual(len(plan['excluded_game_ids']),1)

    def test_trd_documented_exclusion_ina_stays_pending(self):
        active=dict(season=2026,week=9,team='KC',position='RB',status='ACT',gsis_id='00-0030001',full_name='TEST FIXTURE')
        departed={**active,'status':'TRD','gsis_id':'00-0030002'}
        known=pd.DataFrame([{'gsis_id':'00-0030001'}])
        pool,audit=resolve_roster(pd.DataFrame([active,departed]),pd.DataFrame(),known,2026,9,{'KC'})
        self.assertEqual(len(pool),1);self.assertEqual(audit['counts']['exclude'],1)
        with self.assertRaises(EligibilityError):
            resolve_roster(pd.DataFrame([{**departed,'status':'INA'}]),pd.DataFrame(),known,2026,9,{'KC'})

    def test_sidecar_validation_dependencies_and_ci_remain_read_only(self):
        import yaml
        for name in ('reviewed-data-checks','verify-published-data'):
            workflow=yaml.load(Path(f'.github/workflows/{name}.yml').read_text(),Loader=yaml.BaseLoader)
            self.assertEqual(workflow['permissions'],{'contents':'read'})
            self.assertNotIn('schedule',workflow['on'])
            self.assertIn('requirements-validation.txt',Path(f'.github/workflows/{name}.yml').read_text())
        self.assertIn('onopm.space',Path('verify_publication.py').read_text())

    def test_data_only_descendant_preserves_capture_revision_binding(self):
        from weekly_capture import validate_revision
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            repo=Path(temporary)
            def git(*args):
                return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL,text=True).strip()
            git('init','-q'); git('config','user.name','TEST FIXTURE'); git('config','user.email','fixture@example.invalid')
            (repo/'weekly_data.py').write_text('# TEST FIXTURE reviewed source\n')
            git('add','.'); git('commit','-qm','TEST FIXTURE source')
            captured=git('rev-parse','HEAD')
            (repo/'manifest.json').write_text('{}')
            git('add','.'); git('commit','-qm','TEST FIXTURE data-only change')
            validate_revision(captured,repo)
            (repo/'weekly_data.py').write_text('# TEST FIXTURE changed source\n')
            git('add','.'); git('commit','-qm','TEST FIXTURE source change')
            with self.assertRaisesRegex(ValueError,'unchanged-code ancestor'):
                validate_revision(captured,repo)
            with self.assertRaises(ValueError): validate_revision('--bad-revision',repo)

    def test_hosted_capture_is_one_scoped_read_only_trial(self):
        import yaml
        workflow=yaml.load(Path('.github/workflows/reviewed-data-checks.yml').read_text(),Loader=yaml.BaseLoader)
        job=workflow['jobs']['hosted-capture']
        self.assertEqual(job['permissions'],{'contents':'read'})
        self.assertNotIn('environment',job)
        self.assertIn("github.event.action == 'opened'",job['if'])
        self.assertIn('feature/nfl-pm-weekly-data-pipeline',job['if'])
        self.assertIn('head.repo.full_name == github.repository',job['if'])
        for step in job['steps']:
            self.assertNotRegex(step.get('run',''),r'git push|git commit|vercel|automation_publish|--allow-historical')
        upload=job['steps'][-1]
        self.assertEqual(upload['with']['retention-days'],'90')

    def test_retrospective_evaluator_requires_terminal_evidence(self):
        from game_projection_evaluate import verified_evaluation_schedule
        row=game(season=2025,day='2025-09-01',complete=True)
        row.pop('game_status')
        frame=pd.DataFrame([dict(game_id=row['game_id'],play_id=999,desc='END GAME',total_home_score=24,total_away_score=20)])
        verified=verified_evaluation_schedule([row],2025,frame)
        self.assertTrue(regular_games(verified,min_season=2025)[0]['complete'])
        with self.assertRaisesRegex(ValueError,'final-state'):
            verified_evaluation_schedule([row],2025,frame.iloc[:0])
        canceled={**row,'home_score':None,'away_score':None}
        excluded=verified_evaluation_schedule([canceled],2025,frame.iloc[:0])
        self.assertFalse(regular_games(excluded,min_season=2025)[0]['complete'])
