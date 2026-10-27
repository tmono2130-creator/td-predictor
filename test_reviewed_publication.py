"""Temporary Git fixtures only: no real remote, predictions, publication or release."""
import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import yaml
import automation_publish as publisher
from reviewed_publication import PREFIX, MANIFEST, fresh, validate_change, tree
from test_weekly_automation import candidate, game, NOW, rewrite
from weekly_storage import digest, publish_candidate, validate_manifest
from verify_publication import wait_ready, verify_json, PROJECT, read_url


class DataPRTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.data = self.repo / PREFIX
        self.data.mkdir(parents=True)
        self.fixture_git('init', '-q'); self.fixture_git('config', 'core.autocrlf', 'false')
        self.fixture_git('config', 'user.name', 'Fixture'); self.fixture_git('config', 'user.email', 'fixture@example.invalid')
        (self.data / 'manifest.json').write_text(json.dumps(validate_manifest(self.data)), encoding='utf-8')
        self.initial = self.commit()
        c, _ = candidate(self.repo / 'old', base=digest(self.data/'manifest.json'))
        self.old_folder = publish_candidate(c, self.data, now=NOW)
        self.base = self.commit()
        self.now = NOW + timedelta(minutes=5)
        self.candidate, _ = candidate(self.repo / 'new', now=self.now, base=digest(self.data/'manifest.json'))
        self.folder = publish_candidate(self.candidate, self.data, now=self.now)
        self.head = self.commit()

    def fixture_git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL).decode().strip()

    def commit(self):
        self.fixture_git('add', '--', PREFIX)
        self.fixture_git('commit', '-qm', 'Fixture data')
        return self.fixture_git('rev-parse', 'HEAD')

    def check(self, head=None, now=None, branch='nfl-pm/publication/123-1', base=None):
        return validate_change(self.repo, base or self.base, head or self.head, branch, [game()], now or self.now)

    def test_valid_data_only_pr_and_complete_coverage(self):
        self.assertEqual(self.check()['players'], 2)
        self.assertEqual(self.check()['games'], 1)
        self.assertEqual(len(tree(self.repo, self.head))-len(tree(self.repo, self.base)), 3)

    def test_source_changes_with_data_fail(self):
        (self.repo/'model.py').write_text('unexpected', encoding='utf-8')
        self.fixture_git('add', 'model.py'); self.fixture_git('commit', '-qm', 'Fixture unrelated')
        with self.assertRaisesRegex(ValueError, 'unrelated'):
            self.check(self.fixture_git('rev-parse','HEAD'))

    def test_existing_archive_modification_and_deletion_fail(self):
        path = self.data / self.old_folder / 'board.json'
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'Immutable'):
            self.check(self.commit())

    def test_existing_archive_bytes_cannot_change(self):
        path = self.data / self.old_folder / 'receipt.json'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError, 'Immutable'):
            self.check(self.commit())

    def test_stale_candidate_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Stale'):
            self.check(now=self.now+timedelta(hours=7))

    def test_kickoff_and_safety_margin(self):
        from weekly_schedule import kickoff
        with self.assertRaisesRegex(ValueError, 'Kickoff'):
            self.check(now=kickoff(game()))
        # A fresh generation still cannot enter the final ten minutes.
        board=json.loads((self.candidate/'board.json').read_text())
        receipt=json.loads((self.candidate/'receipt.json').read_text())
        near=kickoff(game())-timedelta(minutes=5)
        board['meta']['generated_at']=near.isoformat(); receipt['source_cutoff_utc']=near.isoformat()
        with self.assertRaisesRegex(ValueError, 'margin'):
            fresh(board,receipt,near)

    def test_invalid_manifest_reference(self):
        rewrite(self.data,'manifest.json',lambda m:m['seasons']['2026']['weeks']['1'].update(board='../missing.json'))
        with self.assertRaises(ValueError): self.check(self.commit())

    def test_manifest_cannot_remove_other_week(self):
        rewrite(self.data,'manifest.json',lambda m:m.update(extra='unexpected'))
        with self.assertRaisesRegex(ValueError, 'single approved'):
            self.check(self.commit())

    def test_receipt_base_mismatch_is_concurrent_publication(self):
        rewrite(self.data/self.folder,'receipt.json',lambda r:r.update(base_manifest_sha256='0'*64))
        with self.assertRaisesRegex(ValueError, 'Concurrent'):
            self.check(self.commit())

    def test_historical_candidate_never_accepted(self):
        rewrite(self.data/self.folder,'board.json',lambda b:b['meta'].update(snapshot_classification='historical_backfill'))
        with self.assertRaises(ValueError): self.check(self.commit())

    def test_schedule_change_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            validate_change(self.repo,self.base,self.head,'nfl-pm/publication/123-1',[game(time='21:15')],self.now)

    def test_missing_player_coverage_fails(self):
        rewrite(self.data/self.folder,'board.json',lambda b:b['rows'].pop())
        with self.assertRaisesRegex(ValueError, 'coverage'):
            self.check(self.commit())

    def test_rollback_restores_manifest_only_and_retains_archives(self):
        snapshots={p:v for p,v in tree(self.repo,self.head).items() if p!=MANIFEST}
        previous=self.fixture_git('show',f'{self.base}:{MANIFEST}')
        (self.data/'manifest.json').write_text(previous,encoding='utf-8')
        rollback=self.commit()
        result=self.check(rollback,base=self.head,branch='nfl-pm/rollback/incident-1')
        self.assertEqual(result['kind'],'rollback')
        self.assertEqual(snapshots,{p:v for p,v in tree(self.repo,rollback).items() if p!=MANIFEST})

    def test_rollback_cannot_invent_manifest_or_delete_archives(self):
        rewrite(self.data,'manifest.json',lambda m:m.update(extra='invented'))
        with self.assertRaisesRegex(ValueError, 'previous main'):
            self.check(self.commit(),base=self.head,branch='nfl-pm/rollback/incident-1')

    def test_wrong_branch_and_non_sha_rejected(self):
        with self.assertRaisesRegex(ValueError, 'require'):
            self.check(branch='feature/test')
        with self.assertRaises(ValueError): self.check(base='main')


class PublisherTests(unittest.TestCase):
    def test_open_pr_blocks_parallel_candidate(self):
        with patch.object(publisher,'github',return_value=[{'head':{'ref':'nfl-pm/publication/1-1'}}]):
            with self.assertRaisesRegex(ValueError,'Concurrent'): publisher.assert_no_pending()

    def test_main_race_fails_before_any_branch_or_push(self):
        repo=Path.cwd()
        with patch.object(publisher,'git',side_effect=['a'*40,'',str(repo),'b'*40]) as run:
            with self.assertRaisesRegex(ValueError,'Main moved'):
                publisher.create_data_pr('candidate','a'*40,'1','1')
            self.assertFalse(any(c.args[0] in {'switch','commit','push'} for c in run.call_args_list))

    def test_creation_pushes_unique_branch_opens_draft_and_never_main(self):
        repo=Path.cwd(); folder='2026/week-1/20260909T120000Z-0123456789ab'
        allowed={MANIFEST}|{PREFIX+folder+'/'+n for n in ('board.json','breakdowns.json','receipt.json')}
        def fake_git(*args):
            if args==('rev-parse','HEAD'): return 'a'*40
            if args[0]=='status': return ''
            if args==('rev-parse','--show-toplevel'): return str(repo)
            if args[:2]==('ls-remote','origin'):
                return '' if args[-1].endswith('/*') else 'a'*40+' refs/heads/main'
            if args==('diff','--cached','--name-only'): return '\n'.join(sorted(allowed))
            if args==('diff','--name-only'): return MANIFEST
            if args[:1]==('ls-files',): return '\n'.join(sorted(allowed-{MANIFEST}))
            return ''
        summary={'season':2026,'week':1,'players':2,'games':1,'manifest_sha256':'f'*64}
        with patch.object(publisher,'git',side_effect=fake_git) as run, \
             patch.object(publisher,'assert_no_pending'), patch.object(publisher,'fresh'), \
             patch.object(publisher,'validate_candidate',return_value=({'meta':{'season':2026,'week':1}},None,{})), \
             patch.object(publisher,'retrieve_schedule',return_value=[]), patch.object(publisher,'verify_current_schedule'), \
             patch.object(publisher,'publish_candidate',return_value=folder), \
             patch.object(publisher,'validate_change',return_value=summary), \
             patch.object(publisher,'github',return_value={'html_url':'https://github.com/example/repo/pull/1'}) as api:
            publisher.create_data_pr('candidate','a'*40,'123','2')
            calls=[c.args for c in run.call_args_list]
            self.assertIn(('switch','-c','nfl-pm/publication/123-2'),calls)
            self.assertIn(('push','origin','HEAD:refs/heads/nfl-pm/publication/123-2'),calls)
            self.assertTrue(api.call_args.args[1]['draft'])
            self.assertFalse(any('HEAD:refs/heads/main' in c or '--force' in c for c in calls))

    def test_api_error_does_not_expose_token(self):
        with patch.dict(os.environ,{'GITHUB_REPOSITORY':'example/repo','GH_PUSH_TOKEN':'secret-fixture'}), \
             patch.object(publisher,'build_opener',side_effect=OSError('secret-fixture')):
            with self.assertRaises(RuntimeError) as caught: publisher.github('/pulls')
            self.assertNotIn('secret-fixture',str(caught.exception))


class DeploymentTests(unittest.TestCase):
    def detail(self, state='READY', sha='a'*40):
        return {'readyState':state,'target':'production','projectId':PROJECT,
                'meta':{'githubCommitSha':sha},'alias':['td-predictor.vercel.app'], 'deploymentId':'dpl_fixture'}

    def listing(self,state='READY',sha='a'*40):
        return {'deployments':[{'uid':'dpl_fixture','created':1,'state':state,'target':'production',
                                'meta':{'githubCommitSha':sha,'githubCommitRef':'main'}}]}

    def test_exact_commit_ready_and_alias_required(self):
        with patch('verify_publication.api'):
            def fetch(path,token):return self.listing() if path.startswith('/v6/') else self.detail()
            self.assertEqual(wait_ready('a'*40,'test',fetch=fetch)['deployment_id'],'dpl_fixture')
            with self.assertRaises(TimeoutError):
                wait_ready('b'*40,'test',fetch=fetch,attempts=1)

    def test_failure_timeout_and_wrong_alias(self):
        with self.assertRaisesRegex(ValueError,'failed'):
            wait_ready('a'*40,'test',fetch=lambda *_:self.listing('ERROR'),attempts=1)
        sleep=[]
        with self.assertRaises(TimeoutError):
            wait_ready('a'*40,'test',fetch=lambda *_:{'deployments':[]},sleep=sleep.append,attempts=2)
        self.assertEqual(sleep,[15])
        def fetch(path,token):
            if path.startswith('/v6/'):return self.listing()
            value=self.detail();value['alias']=[];return value
        with self.assertRaisesRegex(ValueError,'alias'):wait_ready('a'*40,'test',fetch=fetch)

    def test_current_alias_cannot_be_another_ready_deployment(self):
        def fetch(path,token):
            if path.startswith('/v6/'): return self.listing()
            result=self.detail()
            if path.startswith('/v4/'): result['deploymentId']='dpl_other'
            return result
        with self.assertRaisesRegex(ValueError,'another deployment'):
            wait_ready('a'*40,'test',fetch=fetch)

    def test_all_json_hashes_and_manifest_race(self):
        expected={MANIFEST:b'{}',PREFIX+'old/board.json':b'{"fixture":1}'}
        def fetch(url):return expected[PREFIX+url.split('/data/')[1]]
        self.assertEqual(len(verify_json(expected,fetch)),2)
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            verify_json(expected,lambda _:b'wrong')
        counter=[0]
        def race(url):
            counter[0]+=1
            return b'changed' if counter[0]==3 else fetch(url)
        with self.assertRaisesRegex(ValueError,'moved'):verify_json(expected,race)

    def test_credentials_never_sent_to_production_url(self):
        with self.assertRaisesRegex(ValueError,'only be sent'):
            read_url('https://td-predictor.vercel.app','secret-fixture')


class WorkflowSafetyTests(unittest.TestCase):
    def test_pr_checks_have_no_secrets_and_no_privileged_trigger(self):
        text=Path('.github/workflows/reviewed-data-checks.yml').read_text(encoding='utf-8-sig')
        workflow=yaml.load(text,Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']),{'pull_request','push'})
        self.assertEqual(workflow['on']['push']['branches'],['feature/nfl-pm-reviewed-publication'])
        self.assertIn('reviewed_publication.py',workflow['on']['push']['paths'])
        self.assertNotIn('**',workflow['on']['push']['paths'])
        self.assertEqual(workflow['on']['pull_request']['branches'],['main'])
        self.assertNotIn('paths',workflow['on']['pull_request'])
        self.assertEqual(workflow['permissions'],{'contents':'read'})
        self.assertNotIn('secrets.',text);self.assertNotIn('pull_request_target',text.replace('never pull_request_target',''))
        self.assertIn('github.event.pull_request.base.sha',text)
        self.assertIn('current',text)

    def test_verifier_is_opt_in_read_only_and_never_deploys(self):
        text=Path('.github/workflows/verify-published-data.yml').read_text(encoding='utf-8-sig')
        workflow=yaml.load(text,Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']),{'push','workflow_dispatch'})
        self.assertEqual(workflow['permissions'],{'contents':'read'})
        self.assertIn("vars.NFL_PM_VERIFY_DEPLOYMENTS == 'true'",workflow['jobs']['verify']['if'])
        self.assertEqual(workflow['jobs']['verify']['environment'],'nfl-pm-production')
        self.assertNotIn('schedule',workflow['on'])
        self.assertNotIn('DEPLOY_HOOK',text)
        for step in workflow['jobs']['verify']['steps']:
            self.assertNotRegex(step.get('run',''),r'git push|vercel deploy|vercel promote|vercel rollback')


if __name__=='__main__':unittest.main()
