"""Deterministic tests: no live source retrieval or real publication."""
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from weekly_schedule import kickoff, plan_week, refresh_due, retrieve_schedule, utc
from weekly_storage import digest, write_new, publish_candidate, validate_candidate, validate_manifest, final_forecasts
from weekly_sources import FreshSources, prior_rows, STAT_COLUMNS, PBP_REQUIRED
from weekly_generation import generate_candidate, score_v5
from weekly_pipeline import verify_current_schedule
from automation_publish import publication_allowed, validate_hook_url, trigger_deploy_hook, commit_data

NOW = utc('2026-09-09T12:00:00+00:00')


def game(season=2026, week=1, day='2026-09-10', time='20:15', away='KC', home='BUF', complete=False):
    return dict(season=season, week=week, game_type='REG', game_id=f'{season}_{week:02}_{away}_{home}',
                gameday=day, gametime=time, away_team=away, home_team=home,
                away_score=20 if complete else None, home_score=24 if complete else None)


def candidate(root, now=NOW, historical=False, base=None):
    planned = game()
    planned.update(kickoff_utc=kickoff(planned).isoformat(), complete=historical)
    if historical:
        now = utc('2026-09-12T12:00:00Z')
    kind = 'historical_backfill' if historical else 'pregame_snapshot'
    bd_game = {k:planned[k] for k in ('game_id','home_team','away_team','kickoff_utc')}
    bd_game.update(prediction_timing=kind,snapshot_classification=kind)
    rows=[]
    eligible=[]
    for i,(team,opp) in enumerate([('KC','BUF'),('BUF','KC')],1):
        pid=f'00-003000{i}'
        eligible.append(dict(player_id=pid,game_id=planned['game_id'],team=team,opponent=opp))
        rows.append(dict(player_id=pid,game_id=planned['game_id'],team=team,opponent=opp,player=f'Fixture {i}',position='RB',
                         td_score=50.,td_estimate=20.,predicted_td_probability_pct=20.,injury_status='Unknown',
                         game_status='Final' if historical else 'Upcoming', is_home=int(team=='BUF'), prediction_timing=kind,
                         snapshot_classification=kind,prediction_timestamp_utc=now.isoformat(),actual_scored_td=None))
    board={'meta':dict(season=2026,week=1,generated_at=now.isoformat(),model='composite',model_version='v5-composite-sha256:'+hashlib.sha256(Path('td_predictor_v5.py').read_bytes()).hexdigest(),
                       snapshot_classification=kind,source_versions={'fixture':'test-only'},final_games=[],games=[bd_game],
                       injury_report=dict(source='fixture',week_available=False,unknown_is_not_active=True)), 'rows':rows}
    breakdowns={'meta':dict(season=2026,week=1,generated_at=now.isoformat(),lookback=6),
                'games':{'KC@BUF':dict(teams=['KC','BUF'],offense=[{'Team':'KC'},{'Team':'BUF'}],defense=[{'Team':'KC'},{'Team':'BUF'}],players={'KC':{},'BUF':{}},injuries={'KC':[],'BUF':[]},flags=[],meta={'lookback':6,'games_used':{'KC':1,'BUF':1},'prior_season_games':{'KC':1,'BUF':1}})},'errors':{}}
    root=Path(root);root.mkdir()
    write_new(root/'board.json',board);write_new(root/'breakdowns.json',breakdowns)
    receipt=dict(source_cutoff_utc=now.isoformat(),scheduled_games=[planned],eligible_players=eligible,
                 base_manifest_sha256=base,source_metadata={'fixture':{'retrieved_at_utc':now.isoformat()}},board_sha256=digest(root/'board.json'),breakdowns_sha256=digest(root/'breakdowns.json'))
    write_new(root/'receipt.json',receipt)
    return root,now


def rewrite(root,name,callback):
    path=root/name
    value=json.loads(path.read_text());callback(value)
    path.write_text(json.dumps(value),encoding='utf-8')
    if name in ('board.json','breakdowns.json'):
        receipt=json.loads((root/'receipt.json').read_text());receipt[name.split('.')[0]+'_sha256']=digest(path)
        (root/'receipt.json').write_text(json.dumps(receipt),encoding='utf-8')


class ScheduleTests(unittest.TestCase):
    def test_auto_detection_uses_schedule_not_generated_week(self):
        p=plan_week([game()],NOW)
        self.assertEqual((p['season'],p['week']),(2026,1))
    def test_international_early_and_monday_kickoffs(self):
        games=[game(day='2026-09-13',time='09:30'),game(day='2026-09-14',time='22:10',away='SF',home='SEA')]
        self.assertEqual(kickoff(games[0]).isoformat(),'2026-09-13T13:30:00+00:00')
        self.assertEqual(kickoff(games[1]).day,15)
        self.assertEqual(len(plan_week(games,NOW)['games']),2)
    def test_dst_and_utc_year_boundary(self):
        g=game(day='2027-01-04',time='20:15',week=18)
        self.assertEqual(kickoff(g).isoformat(),'2027-01-05T01:15:00+00:00')
        self.assertEqual(plan_week([g],utc('2027-01-03T00:00:00Z'))['season'],2026)
    def test_mixed_week_excludes_started_and_final_games(self):
        g1=game(day='2026-09-08',complete=True)
        g2=game(away='SF',home='SEA')
        p=plan_week([g1,g2],NOW)
        self.assertEqual([g['game_id'] for g in p['games']],[g2['game_id']])
        g1.update(home_score=None,away_score=None)
        self.assertEqual(len(plan_week([g1,g2],NOW)['games']),1)
    def test_offseason_is_idle_not_last_week(self):
        self.assertEqual(plan_week([game()],utc('2026-06-01T12:00:00Z'))['status'],'idle')
        self.assertEqual(plan_week([game(complete=True)],utc('2027-02-01T12:00:00Z'))['status'],'idle')
    def test_no_postseason_or_nonexistent_week(self):
        with self.assertRaises(ValueError):plan_week([game()],NOW,2026,19)
        with self.assertRaises(ValueError):plan_week([game()],NOW,2026,2)
        g=game();g['game_type']='POST'
        with self.assertRaises(ValueError):plan_week([g],NOW)
    def test_invalid_kickoff_or_duplicate_team_fail(self):
        with self.assertRaises(ValueError):plan_week([game(time='unknown')],NOW)
        with self.assertRaises(ValueError):plan_week([game(),game(away='SF')],NOW)
        with self.assertRaises(ValueError):plan_week([game()],datetime(2026,9,9))
    def test_distant_tbd_kickoff_does_not_block_current_slate(self):
        distant=game(week=18,day='2027-01-03',time='TBD',away='SF',home='SEA')
        self.assertEqual(plan_week([game(),distant],NOW)['week'],1)
        with self.assertRaisesRegex(ValueError,'TBD'):
            plan_week([game(time='TBD')],NOW)
        with self.assertRaisesRegex(ValueError,'TBD'):
            plan_week([distant],NOW,2026,18)

    def test_historical_requires_complete_week(self):
        with self.assertRaises(ValueError):plan_week([game()],utc('2026-09-12T12:00:00Z'),2026,1,historical=True)
        self.assertTrue(plan_week([game(complete=True)],utc('2026-09-12T12:00:00Z'),2026,1,historical=True)['historical'])
    def test_refresh_frequency_uses_actual_kickoff(self):
        p=plan_week([game()],NOW)
        m={'seasons':{'2026':{'weeks':{'1':{'generated_at':(NOW-timedelta(hours=1)).isoformat()}}}}}
        self.assertFalse(refresh_due(p,m,NOW))
        near=kickoff(game())-timedelta(hours=1)
        self.assertTrue(refresh_due(p,m,near))
    def test_failed_source_retry_is_not_offseason(self):
        with patch('weekly_schedule.urlopen',side_effect=OSError('outage')) as fetch:
            with self.assertRaisesRegex(RuntimeError,'unchanged'):retrieve_schedule(sleep=lambda _:None)
            self.assertEqual(fetch.call_count,3)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_publish_and_immutability_and_final_valid_forecast(self):
        c,n=candidate(self.root/'one');data=self.root/'data'
        first=publish_candidate(c,data,now=n)
        before=(data/first/'board.json').read_bytes()
        c2,n2=candidate(self.root/'two',now=n+timedelta(hours=1),base=digest(data/'manifest.json'))
        second=publish_candidate(c2,data,now=n2)
        self.assertNotEqual(first,second)
        self.assertEqual(before,(data/first/'board.json').read_bytes())
        self.assertEqual(final_forecasts(data)[0]['prediction_timestamp_utc'],n2.isoformat())
        validate_manifest(data)
    def test_evaluation_index_rejects_modified_archive(self):
        c,n=candidate(self.root/'one');data=self.root/'data';relative=publish_candidate(c,data,now=n)
        path=data/relative/'board.json';board=json.loads(path.read_text());board['rows'][0]['td_estimate']=21.0
        path.write_text(json.dumps(board),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):final_forecasts(data)

    def test_invalid_export_preserves_old_manifest(self):
        c,n=candidate(self.root/'one');data=self.root/'data';publish_candidate(c,data,now=n)
        old=digest(data/'manifest.json')
        c2,n2=candidate(self.root/'two',base=old)
        rewrite(c2,'board.json',lambda b:b['rows'][0].update(td_estimate=120))
        with self.assertRaises(ValueError):publish_candidate(c2,data,now=n2)
        self.assertEqual(old,digest(data/'manifest.json'))
    def test_missing_json_rejected(self):
        c,n=candidate(self.root/'one');(c/'breakdowns.json').unlink()
        with self.assertRaises(FileNotFoundError):validate_candidate(c,now=n)
    def test_missing_manifest_reference_rejected(self):
        c,n=candidate(self.root/'one');data=self.root/'data';relative=publish_candidate(c,data,now=n)
        (data/relative/'board.json').unlink()
        with self.assertRaisesRegex(ValueError,'missing'):validate_manifest(data)
    def test_concurrent_manifest_change_rejected(self):
        c,n=candidate(self.root/'one');data=self.root/'data';publish_candidate(c,data,now=n)
        with self.assertRaisesRegex(ValueError,'changed since'):publish_candidate(c,data,now=n)
    def test_lock_prevents_concurrent_publication(self):
        c,n=candidate(self.root/'one');data=self.root/'data';data.mkdir();(data/'.weekly-publish.lock').touch()
        with self.assertRaises(FileExistsError):publish_candidate(c,data,now=n)
        self.assertTrue((data/'.weekly-publish.lock').exists())
    def test_failed_manifest_swap_preserves_last_good_files(self):
        c,n=candidate(self.root/'one');data=self.root/'data';first=publish_candidate(c,data,now=n)
        before=(data/'manifest.json').read_bytes();archive=(data/first/'board.json').read_bytes()
        c2,n2=candidate(self.root/'two',base=digest(data/'manifest.json'))
        with patch('weekly_storage.os.replace',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):publish_candidate(c2,data,now=n2)
        self.assertEqual(before,(data/'manifest.json').read_bytes())
        self.assertEqual(archive,(data/first/'board.json').read_bytes())
        self.assertFalse((data/'.weekly-publish.lock').exists())

    def test_invalid_player_id_rejected(self):
        c,n=candidate(self.root/'one');rewrite(c,'board.json',lambda b:b['rows'][0].update(player_id='unknown'))
        with self.assertRaises(ValueError):validate_candidate(c,now=n)
    def test_duplicate_and_missing_players_rejected(self):
        for name,change in [('duplicate',lambda b:b['rows'].append(b['rows'][0].copy())),('missing',lambda b:b['rows'].pop())]:
            with self.subTest(name=name):
                c,n=candidate(self.root/name);rewrite(c,'board.json',change)
                with self.assertRaises(ValueError):validate_candidate(c,now=n)
    def test_wrong_team_and_nan_probability_rejected(self):
        for name,change in [('team',lambda b:b['rows'][0].update(team='SEA')),('nan',lambda b:b['rows'][0].update(td_estimate=float('nan')))]:
            c,n=candidate(self.root/name);rewrite(c,'board.json',change)
            with self.assertRaises(ValueError):validate_candidate(c,now=n)
    def test_kickoff_recheck_and_bad_timestamp(self):
        c,n=candidate(self.root/'one')
        with self.assertRaisesRegex(ValueError,'Kickoff'):validate_candidate(c,now=utc('2026-09-11T00:15:00Z'))
        rewrite(c,'board.json',lambda b:b['rows'][0].update(prediction_timestamp_utc='invalid'))
        with self.assertRaises(ValueError):validate_candidate(c,now=n)
    def test_partial_breakdown_rejected(self):
        c,n=candidate(self.root/'one');rewrite(c,'breakdowns.json',lambda b:b['errors'].update({'KC@BUF':'outage'}))
        with self.assertRaisesRegex(ValueError,'coverage'):validate_candidate(c,now=n)
    def test_historical_never_becomes_authentic_forecast(self):
        c,n=candidate(self.root/'one',historical=True)
        with self.assertRaisesRegex(ValueError,'approval'):validate_candidate(c,now=n)
        data=self.root/'data';publish_candidate(c,data,allow_historical=True,now=n)
        self.assertEqual(final_forecasts(data),[])
        c2,n=candidate(self.root/'two',historical=True,base=digest(data/'manifest.json'))
        with self.assertRaisesRegex(ValueError,'cannot replace'):publish_candidate(c2,data,allow_historical=True,now=n)
    def test_postkickoff_relabel_rejected(self):
        c,n=candidate(self.root/'one',historical=True)
        rewrite(c,'board.json',lambda b:b['meta'].update(snapshot_classification='pregame_snapshot'))
        with self.assertRaises(ValueError):validate_candidate(c,now=n)
    def test_changed_schedule_refuses_publication(self):
        c,n=candidate(self.root/'one');b=json.loads((c/'board.json').read_text());g=game(time='21:15')
        with self.assertRaisesRegex(ValueError,'changed'):verify_current_schedule(b,[g],now=n)
    def test_manifest_path_traversal_rejected(self):
        c,n=candidate(self.root/'one');data=self.root/'data';publish_candidate(c,data,now=n)
        rewrite(data,'manifest.json',lambda m:m['seasons']['2026']['weeks']['1'].update(board='../board.json'))
        with self.assertRaises(ValueError):validate_manifest(data)


class SourceTests(unittest.TestCase):
    def test_retry_required_source_fails_closed(self):
        with patch('weekly_sources.utc_now',return_value=NOW):
            f=FreshSources({'stats':lambda _:(_ for _ in ()).throw(OSError('outage'))},sleep=lambda _:None)
            with self.assertRaisesRegex(RuntimeError,'Required source'):f.get('stats',2026)
    def test_missing_injuries_remain_unknown(self):
        f=FreshSources({'injuries':lambda _:(_ for _ in ()).throw(OSError('outage'))},sleep=lambda _:None)
        injuries=f.injuries(2026,1,NOW)
        self.assertTrue(injuries.empty);self.assertFalse(injuries.attrs['week_report_available'])
    def test_injury_future_updates_excluded_and_blank_not_active(self):
        frame=pd.DataFrame([dict(week=1,gsis_id='00-0030001',report_status=None,date_modified='2026-09-09T10:00:00Z'),
                            dict(week=1,gsis_id='00-0030002',report_status='Active',date_modified='2026-09-12T10:00:00Z')])
        f=FreshSources({'injuries':lambda _:frame},sleep=lambda _:None)
        result=f.injuries(2026,1,NOW)
        self.assertEqual(result.injury_status.tolist(),['Unknown'])
    def test_target_week_and_postseason_rows_never_enter_features(self):
        frame=pd.DataFrame([dict(season=2026,week=1,season_type='REG'),dict(season=2026,week=2,season_type='REG'),dict(season=2025,week=20,season_type='POST')])
        result=prior_rows(frame,2026,2);self.assertEqual(result.week.tolist(),[1])
    def test_historical_needs_weekly_roster(self):
        f=FreshSources({'weekly_rosters':lambda _:pd.DataFrame([dict(week=2)])},sleep=lambda _:None)
        with self.assertRaisesRegex(ValueError,'week-specific'):f.rosters(2026,1,historical=True)
    def test_invalid_roster_id_rejected(self):
        frame=pd.DataFrame([dict(week=1,gsis_id='invalid',full_name='Fixture',team='KC',position='RB',status='ACT')])
        f=FreshSources({'weekly_rosters':lambda _:frame},sleep=lambda _:None)
        with self.assertRaisesRegex(ValueError,'identifiers'):f.rosters(2026,1)
    def test_practice_squad_is_not_current_forecast_pool(self):
        frame=pd.DataFrame([dict(week=1,gsis_id='00-0030001',full_name='Fixture',team='KC',position='RB',status='ACT'),
                            dict(week=1,gsis_id=None,full_name='Practice fixture',team='KC',position='RB',status='DEV')])
        players=pd.DataFrame([dict(gsis_id='00-0030001')])
        f=FreshSources({'weekly_rosters':lambda _:frame,'players':lambda _:players},sleep=lambda _:None)
        self.assertEqual(f.rosters(2026,1).player_id.tolist(),['00-0030001'])


class GenerationTests(unittest.TestCase):
    def test_unpublished_candidate_runs_real_v5_and_breakdown_functions(self):
        roster=pd.DataFrame([dict(player_id='00-0030001',model_player_name='Fixture A',team='KC',position='RB'),
                             dict(player_id='00-0030002',model_player_name='Fixture B',team='BUF',position='WR')])
        histories={};schedule=[]
        for year in (2023,2024,2025):
            g=game(season=year,day=f'{year}-09-01',complete=True);schedule.append(g)
            rows=[]
            for player in roster.itertuples():
                row={c:1.0 for c in STAT_COLUMNS}
                row.update(player_id=player.player_id,player_display_name=player.model_player_name,team=player.team,
                           position=player.position,season=year,week=1,game_id=g['game_id'],season_type='REG')
                rows.append(row)
            histories[year]=pd.DataFrame(rows)
        schedule.append(game())
        plays=[]
        for i,player in enumerate(roster.itertuples(),1):
            row={c:0 for c in PBP_REQUIRED}
            row.update(game_id='2025_01_KC_BUF',season=2025,week=1,season_type='REG',play_id=i,drive=i,
                       posteam=player.team,defteam='BUF' if player.team=='KC' else 'KC',play_type='run',
                       yardline_100=5,rusher_player_id=player.player_id,receiver_player_id=None,
                       touchdown=1,rush_touchdown=1,pass_touchdown=0,td_team=player.team,td_player_id=player.player_id,yards_gained=5)
            plays.append(row)
        pbp=pd.DataFrame(plays)
        class FixtureSources:
            metadata={'fixture':'test only'}
            def rosters(self,*args):return roster.copy()
            def history(self,*args):return histories,pbp
            def injuries(self,*args):
                result=pd.DataFrame(columns=['player_id','injury_status']);result.attrs['week_report_available']=False
                return result
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root=Path(temporary);output=root/'candidate';data=root/'published'
            generate_candidate(plan_week(schedule,NOW),schedule,FixtureSources(),output,data,clock=lambda:NOW)
            board,reports,_=validate_candidate(output,now=NOW)
            self.assertEqual(len(board['rows']),2)
            self.assertEqual({r['injury_status'] for r in board['rows']},{'Unknown'})
            self.assertEqual(set(reports['games']),{'KC@BUF'})
            self.assertFalse(data.exists())
            with self.assertRaises(FileExistsError):
                generate_candidate(plan_week(schedule,NOW),schedule,FixtureSources(),output,data,clock=lambda:NOW)


class WorkflowTests(unittest.TestCase):
    def test_publication_opt_in_and_main_required(self):
        self.assertFalse(publication_allowed('workflow_dispatch','refs/heads/main','true','false'))
        self.assertFalse(publication_allowed('schedule','refs/heads/test','true','true'))
        self.assertFalse(publication_allowed('schedule','refs/heads/main','false','true'))
        self.assertTrue(publication_allowed('workflow_dispatch','refs/heads/main','true','true'))
    def test_hooks_validate_host_and_do_not_leak_secret(self):
        with self.assertRaises(ValueError):validate_hook_url('https://evil.example/secret')
        with patch('automation_publish.urlopen',side_effect=OSError('secret-url')):
            with self.assertRaisesRegex(RuntimeError,'Vercel deploy hook failed') as error:
                trigger_deploy_hook('https://api.vercel.com/v1/integrations/deploy/fixture-secret')
            self.assertNotIn('fixture-secret',str(error.exception))
    def test_main_race_never_commits_or_merges(self):
        with patch('automation_publish.git',side_effect=['a'*40,'','b'*40]) as run:
            with self.assertRaisesRegex(ValueError,'Main moved'):commit_data('fixture','a'*40)
            self.assertFalse(any('commit' in call.args or 'push' in call.args for call in run.call_args_list))
    def test_ci_stages_only_new_bundle_and_manifest(self):
        root=Path.cwd()/'td-predictor-web'/'public'/'data';directory='2026/week-1/test-run'
        allowed={'td-predictor-web/public/data/manifest.json'} | {'td-predictor-web/public/data/'+directory+'/'+name for name in ('board.json','breakdowns.json','receipt.json')}
        def fake_git(*args):
            if args==('rev-parse','HEAD'):return 'a'*40
            if args[:1]==('status',):return ''
            if args[:1]==('ls-remote',):return 'a'*40+' refs/heads/main'
            if args==('rev-parse','--show-toplevel'):return str(Path.cwd())
            if args==('diff','--cached','--name-only'):return '\n'.join(sorted(allowed))
            return ''
        with patch('automation_publish.git',side_effect=fake_git) as run, patch('automation_publish.validate_candidate',return_value=({'meta':{'season':2026,'week':1}},None,None)), patch('automation_publish.verify_current_schedule'), patch('automation_publish.retrieve_schedule',return_value=[]), patch('automation_publish.publish_candidate',return_value=directory):
            commit_data('fixture','a'*40,root)
            staged=next(c.args for c in run.call_args_list if c.args[0]=='add')
            self.assertEqual(set(staged[2:]),allowed)
            self.assertIn(('push','origin','HEAD:refs/heads/main'),[c.args for c in run.call_args_list])
            self.assertFalse(any('--force' in c.args or 'merge' in c.args or 'rebase' in c.args for c in run.call_args_list))

    def test_yaml_is_dormant_and_permissions_scoped(self):
        import yaml
        workflow=yaml.load(Path('.github/workflows/weekly-predictions.yml').read_text(encoding='utf-8-sig'),Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']),{'workflow_dispatch'})
        self.assertEqual(workflow['on']['workflow_dispatch']['inputs']['publish']['default'],'false')
        self.assertEqual(workflow['permissions'],{'contents':'read'})
        self.assertEqual(workflow['jobs']['publish']['permissions'],{'contents':'write'})
        self.assertEqual(workflow['jobs']['publish']['environment'],'nfl-pm-production')
        for job in workflow['jobs'].values():
            for step in job['steps']:
                if 'uses' in step:
                    self.assertRegex(step['uses'],r'@[a-f0-9]{40}$')
                if step.get('uses','').startswith('actions/checkout@'):
                    self.assertEqual(step['with']['persist-credentials'],'false')
        text=Path('automation_publish.py').read_text(encoding='utf-8-sig')
        self.assertNotIn('"--force"',text);self.assertIn('td-predictor-web/public/data/',text)


if __name__=='__main__':unittest.main()
