"""Deterministic synthetic unit fixtures, never production statistics."""
import copy
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
import pandas as pd
from game_projection import prepare_team_games,project_matchup,training_rows,fit_adjusted,evaluate,FEATURES
from game_projection_artifact import build_artifact,validate_artifact,NAME,HASH
from game_projection_cli import attach,local
from weekly_storage import validate_candidate,publish_candidate,validate_manifest,digest,write_new
from test_weekly_automation import candidate,game,NOW,rewrite
from reviewed_publication import validate_change,MANIFEST,tree,PREFIX
import test_reviewed_publication as fixtures
from verify_publication import verify_json,PRODUCTION


def history():
    return pd.DataFrame([dict(game_id=f"2025_{week:02}_KC_BUF",season=2025,week=week,kickoff_utc=f"2025-12-{week-14:02}T18:00:00+00:00",team=t,opponent=o,
        plays=60,faced=64,off_points=24.,allowed_points=21.,final_points=24.,rz_drives=3,drives=10,home=int(t=="BUF"),neutral=False)
        for week in range(15,19) for t,o in (("KC","BUF"),("BUF","KC"))])


def artifact(now=NOW):
    sources={name:{"as_of":now.isoformat(),"sha256":"a"*64,"origin":"https://example.invalid/TEST-FIXTURE"} for name in ('schedule','team_games')}
    return build_artifact(history(),[game()],2026,1,now,sources,generated_at=now)


class ProjectionTests(unittest.TestCase):
    def test_game_publication_opt_in_is_required_and_not_implied(self):
        from automation_publish import game_publication_allowed
        self.assertTrue(game_publication_allowed({},None))
        self.assertFalse(game_publication_allowed({HASH:"a"*64},None))
        self.assertFalse(game_publication_allowed({HASH:"a"*64},"false"))
        self.assertTrue(game_publication_allowed({HASH:"a"*64},"true"))

    def test_baseline_pace_precision_and_winner(self):
        value=artifact();g=value['games'][game()['game_id']]
        p=g['teams']['KC'];self.assertEqual(p['expected_plays'],62.)
        self.assertAlmostEqual(p['baseline'],((24/60+21/64)/2)*62)
        self.assertIsNone(g['methods']['baseline']['favored']);self.assertIsNone(g['methods']['baseline']['win_probability'])
        self.assertEqual(g['methods']['baseline']['total'],2*p['baseline'])

    def test_scoring_excludes_return_td_and_its_conversion(self):
        schedule=[game(complete=True)];plays=[]
        for n,(team,other) in enumerate((('KC','BUF'),('BUF','KC'))):
            for i,kind in enumerate(('pass','extra_point','field_goal')):
                plays.append(dict(game_id=game()['game_id'],play_id=n*10+i,posteam=team,defteam=other,play_type=kind,
                    two_point_attempt=0,touchdown=int(i==0),td_team=team if i==0 else None,return_touchdown=0,
                    extra_point_result='good' if i==1 else None,two_point_conv_result=None,field_goal_result='made' if i==2 else None,yardline_100=10,drive=1,extra_point_attempt=int(i==1),field_goal_attempt=int(i==2),desc='TEST FIXTURE'))
        row=copy.deepcopy(plays[0]);row.update(play_id=50,td_team='BUF',return_touchdown=1);plays.append(row)
        row=copy.deepcopy(plays[1]);row.update(play_id=51);plays.append(row)
        out=prepare_team_games(schedule,pd.DataFrame(plays));self.assertEqual(out.off_points.tolist(),[10.,10.])
        self.assertEqual(out.plays.tolist(),[1,2])
        original=copy.deepcopy(plays)
        for index,key in ((1,'extra_point_result'),(2,'field_goal_result'),(0,'td_team')):
            changed=copy.deepcopy(original);changed[index][key]=None
            with self.subTest(missing=key),self.assertRaisesRegex(ValueError,'Missing'):
                prepare_team_games(schedule,pd.DataFrame(changed))
        changed=copy.deepcopy(original);changed[0].update(two_point_attempt=1,two_point_conv_result=None)
        with self.assertRaisesRegex(ValueError,'two-point'):prepare_team_games(schedule,pd.DataFrame(changed))
        # Explicit no-play/non-attempt evidence is ignored, never treated as a missed kick.
        changed=copy.deepcopy(original);extra=copy.deepcopy(changed[1]);extra.update(play_id=9,extra_point_result=None,extra_point_attempt=0,desc='Penalty - No Play.');changed.append(extra)
        self.assertEqual(prepare_team_games(schedule,pd.DataFrame(changed)).off_points.tolist(),[10.,10.])
        plays[0]['touchdown']=None
        with self.assertRaisesRegex(ValueError,'touchdown'):prepare_team_games(schedule,pd.DataFrame(plays))

    def test_no_target_or_future_game_leakage(self):
        h=history();base=project_matchup(h,game(),NOW)
        extra=h.iloc[[0]].assign(game_id=game()['game_id'],season=2026,week=1,kickoff_utc='2026-09-08T10:00:00Z',off_points=999)
        self.assertEqual(project_matchup(pd.concat([h,extra]),game(),NOW),base)
        self.assertEqual(len(training_rows(h,[game(complete=True)])),0)

    def test_incomplete_completed_history_is_not_silently_used(self):
        old=game(season=2025,week=15,day='2025-12-01',time='13:00',complete=True)
        sources=artifact()['meta']['sources']
        with self.assertRaisesRegex(ValueError,'Incomplete completed'):
            build_artifact(history()[history().week.ne(15)],[old,game()],2026,1,NOW,sources,generated_at=NOW)

    def test_missing_stats_and_kickoff(self):
        self.assertIsNone(project_matchup(history().iloc[:2],game(),NOW))
        from weekly_schedule import kickoff
        with self.assertRaises(ValueError):project_matchup(history(),game(),kickoff(game()))

    def test_chronological_fit_ignores_future_targets(self):
        records=[dict(game_id=str(i//2),season=2022,features=[20.,.3,.4,60.,i%2],baseline=20.,actual=21.+i%2,kickoff_utc='2022-12-01T18:00:00Z') for i in range(240)]
        model=fit_adjusted(records,2022)
        future=dict(records[0],season=2024,actual=10000.,game_id='future')
        self.assertEqual(fit_adjusted(records+[future],2022),model)
        with self.assertRaises(ValueError):evaluate(records,model,2022)
        self.assertEqual(model['features'],FEATURES)

    def test_semantic_schema_rejects_tampering(self):
        games=[{k:v for k,v in artifact()['games'][game()['game_id']].items() if k in ('game_id','home_team','away_team','kickoff_utc')}]
        mutations=[lambda a:a['meta'].update(week=2),lambda a:a['games'].clear(),
            lambda a:a['games'][game()['game_id']]['methods']['baseline']['scores'].update(KC=99),
            lambda a:a['games'][game()['game_id']]['methods']['baseline'].update(win_probability=.75),
            lambda a:a['games'][game()['game_id']]['teams']['KC']['summary'].update(game_ids=[game()['game_id']]*4),
            lambda a:a['meta'].update(data_cutoff='2026-09-12T00:00:00Z')]
        for mutation in mutations:
            value=artifact();mutation(value)
            with self.subTest(mutation=mutation),self.assertRaises((ValueError,KeyError,TypeError)):validate_artifact(value,games,2026,1)

    def test_freshness_and_margin_fail_closed(self):
        v=artifact();games=list(v['games'].values())
        with self.assertRaisesRegex(ValueError,'Stale'):validate_artifact(v,games,2026,1,NOW+timedelta(days=1),True)
        from weekly_schedule import kickoff
        with self.assertRaisesRegex(ValueError,'margin'):validate_artifact(v,games,2026,1,kickoff(game())-timedelta(minutes=5),True)
        v['meta']['classification']='retrospective_analysis'
        with self.assertRaisesRegex(ValueError,'Historical'):validate_artifact(v,games,2026,1,NOW,True)

    def test_local_output_refuses_served_paths(self):
        from publication_policy import REPOSITORY
        for root in ('public','td-predictor-web/public'):
            with self.assertRaises(ValueError):local(REPOSITORY/root/'review')


class GamePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.c,_=candidate(self.root/'candidate');self.path=self.root/NAME;write_new(self.path,artifact())

    def test_live_staging_requires_separate_game_opt_in(self):
        attach(self.c,self.path,NOW)
        with patch('weekly_storage.require_review_checkout'),patch('weekly_storage.is_live_path',return_value=True),patch.dict('os.environ',{},clear=True):
            with self.assertRaisesRegex(ValueError,'inactive'):
                publish_candidate(self.c,self.root/'live',now=NOW)
        self.assertFalse((self.root/'live/manifest.json').exists())

    def test_optional_receipt_bundle_persists_exact_bytes(self):
        pin=attach(self.c,self.path,NOW);out=self.root/'data';relative=publish_candidate(self.c,out,now=NOW)
        files=validate_manifest(out)['seasons']['2026']['weeks']['1']
        self.assertEqual(files[HASH],pin);self.assertEqual((out/relative/NAME).read_bytes(),self.path.read_bytes())
        rewrite(out,'manifest.json',lambda m:m['seasons']['2026']['weeks']['1'].pop(HASH))
        with self.assertRaises(ValueError):validate_manifest(out)

    def test_unreceipted_extra_missing_and_modified_files_fail(self):
        write_new(self.c/NAME,artifact())
        with self.assertRaises(ValueError):validate_candidate(self.c,now=NOW)
        (self.c/NAME).unlink();attach(self.c,self.path,NOW)
        with (self.c/NAME).open('ab') as out:out.write(b' ')
        with self.assertRaisesRegex(ValueError,'hash'):validate_candidate(self.c,now=NOW)

    def test_immutable_attachment_and_stale_rejection(self):
        attach(self.c,self.path,NOW)
        with self.assertRaises(ValueError):attach(self.c,self.path,NOW)
        with self.assertRaises(ValueError):validate_candidate(self.c,now=NOW+timedelta(days=1))


class DataPRTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.DataPRTests('test_valid_data_only_pr_and_complete_coverage');self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;rewrite(f.candidate,'receipt.json',lambda r:r.update(base_manifest_sha256=digest(f.data/'manifest.json')))
        source=f.repo/NAME;write_new(source,artifact(f.now));attach(f.candidate,source,f.now)
        f.folder=publish_candidate(f.candidate,f.data,now=f.now);self.head=f.commit()

    def test_data_only_pr_accepted(self):
        f=self.f;self.assertEqual(validate_change(f.repo,f.head,self.head,'nfl-pm/publication/99-1',[game()],f.now)['players'],2)

    def test_deployment_verifies_new_hash_and_rollback_preserves_file(self):
        f=self.f;expected=tree(f.repo,self.head)
        def fetch(url):return expected[PREFIX+url.removeprefix(PRODUCTION+'/data/')]
        self.assertIn(f.folder+'/'+NAME,verify_json(expected,fetch))
        with self.assertRaises(ValueError):verify_json(expected,lambda url:b'{}' if url.endswith(NAME) else fetch(url))
        (f.data/'manifest.json').write_text(f.fixture_git('show',f'{f.head}:{MANIFEST}'),encoding='utf-8')
        rollback=f.commit();self.assertEqual(validate_change(f.repo,self.head,rollback,'nfl-pm/rollback/game-test',[game()],f.now)['kind'],'rollback')
        self.assertIn(PREFIX+f.folder+'/'+NAME,tree(f.repo,rollback))


class CombinedSidecarTests(unittest.TestCase):
    def test_both_attachment_orders_and_fail_closed_integrity(self):
        from test_matchup_publication import attach as attach_matchup
        from matchup_publication import SIDECAR, HASH_KEY, bundle_files
        for matchup_first in (True, False):
            with self.subTest(matchup_first=matchup_first), tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
                root = Path(temp)
                c, _ = candidate(root / 'candidate')
                source = root / NAME
                write_new(source, artifact())
                if matchup_first:
                    attach_matchup(c)
                    attach(c, source, NOW)
                else:
                    attach(c, source, NOW)
                    attach_matchup(c)
                _, _, receipt = validate_candidate(c, now=NOW)
                self.assertEqual(bundle_files(receipt), {'board.json', 'breakdowns.json', 'receipt.json', NAME, SIDECAR})
                out = root / 'data'
                relative = publish_candidate(c, out, now=NOW)
                files = validate_manifest(out)['seasons']['2026']['weeks']['1']
                for name, key in ((NAME, HASH), (SIDECAR, HASH_KEY)):
                    self.assertEqual(files[key], digest(c / name))
                    self.assertEqual((out / relative / name).read_bytes(), (c / name).read_bytes())
                    original = (c / name).read_bytes()
                    (c / name).write_bytes(original + b' ')
                    with self.assertRaises(ValueError): validate_candidate(c, now=NOW)
                    (c / name).write_bytes(original)
                    (c / name).unlink()
                    with self.assertRaises(ValueError): validate_candidate(c, now=NOW)
                    (c / name).write_bytes(original)
                with self.assertRaises(ValueError): validate_candidate(c, now=NOW + timedelta(days=1))

    def test_combined_review_deployment_and_rollback(self):
        from test_matchup_publication import attach as attach_matchup
        from matchup_publication import SIDECAR
        f = fixtures.DataPRTests('test_valid_data_only_pr_and_complete_coverage')
        f.setUp()
        self.addCleanup(f.doCleanups)
        rewrite(f.candidate, 'receipt.json', lambda r: r.update(base_manifest_sha256=digest(f.data / 'manifest.json')))
        source = f.repo / NAME
        write_new(source, artifact(f.now))
        attach(f.candidate, source, f.now)
        attach_matchup(f.candidate, f.now)
        folder = publish_candidate(f.candidate, f.data, now=f.now)
        head = f.commit()
        self.assertEqual(validate_change(f.repo, f.head, head, 'nfl-pm/publication/99-1', [game()], f.now)['players'], 2)
        expected = tree(f.repo, head)
        def fetch(url): return expected[PREFIX + url.removeprefix(PRODUCTION + '/data/')]
        result = verify_json(expected, fetch)
        for name in (NAME, SIDECAR):
            self.assertIn(folder + '/' + name, result)
            with self.assertRaises(ValueError):
                verify_json(expected, lambda url: b'{}' if url.endswith(name) else fetch(url))
        (f.data / 'manifest.json').write_text(f.fixture_git('show', f'{f.head}:{MANIFEST}'), encoding='utf-8')
        rollback = f.commit()
        self.assertEqual(validate_change(f.repo, head, rollback, 'nfl-pm/rollback/both', [game()], f.now)['kind'], 'rollback')
        for name in (NAME, SIDECAR): self.assertIn(PREFIX + folder + '/' + name, tree(f.repo, rollback))
