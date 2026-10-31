"""Release gates and publication rehearsals use isolated synthetic fixtures only."""
import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import yaml

import automation_publish as publisher
from game_projection_artifact import HASH as GAME_HASH
from matchup_publication import HASH_KEY as MATCHUP_HASH


def complete_receipt():
    return {GAME_HASH: 'a' * 64, MATCHUP_HASH: 'b' * 64,
            'input_capture': {'manifest': {'kind': 'TEST FIXTURE'}},
            'bundle_status': {'core': 'complete', 'three_features': True,
                              'requested': ['matchup', 'game'],
                              'available': ['core', 'game', 'matchup'], 'unavailable': {}}}


class LaunchGateTests(unittest.TestCase):
    def test_real_bundle_browser_runs_before_proposal_and_ci_stays_read_only(self):
        workflow = yaml.load(Path('.github/workflows/weekly-predictions.yml').read_text(), Loader=yaml.BaseLoader)
        steps = workflow['jobs']['generate']['steps']
        browser = next(i for i, step in enumerate(steps) if 'node scripts/weekly-data-smoke.mjs' in step.get('run', ''))
        self.assertEqual(steps[browser]['if'], "inputs.features == 'all'")
        self.assertTrue(any('validate --candidate' in step.get('run', '') for step in steps[browser+1:]))
        self.assertNotIn('environment', workflow['jobs']['generate'])
        ci = yaml.load(Path('.github/workflows/reviewed-data-checks.yml').read_text(), Loader=yaml.BaseLoader)
        capture = ci['jobs']['hosted-capture']
        self.assertEqual(capture['permissions'], {'contents': 'read'})
        self.assertIn('feature/nfl-pm-week8-launch', capture['if'])
        self.assertIn("github.event.action == 'opened'", capture['if'])
        self.assertNotIn('environment', capture)
        self.assertTrue(any('node scripts/weekly-data-smoke.mjs' in s.get('run', '') for s in capture['steps']))
        self.assertTrue(any('--season 2026 --week 8' in s.get('run', '') for s in capture['steps']))

    def test_full_bundle_and_core_selection_are_explicit(self):
        publisher.validate_requested_bundle({}, 'core')
        publisher.validate_requested_bundle(complete_receipt(), 'all')
        for features in ('game', 'matchup', '', 'ALL'):
            with self.assertRaises(ValueError): publisher.validate_requested_bundle({}, features)
        for key in (GAME_HASH, MATCHUP_HASH):
            with self.assertRaises(ValueError): publisher.validate_requested_bundle({key: 'a' * 64}, 'core')

    def test_requested_full_product_cannot_silently_degrade(self):
        changes = [lambda r: r.pop(GAME_HASH), lambda r: r.pop(MATCHUP_HASH),
                   lambda r: r.pop('input_capture'), lambda r: r.pop('bundle_status'),
                   lambda r: r['bundle_status'].update(three_features=False),
                   lambda r: r['bundle_status'].update(core='incomplete'),
                   lambda r: r['bundle_status'].update(requested=['matchup']),
                   lambda r: r['bundle_status'].update(available=['core', 'game']),
                   lambda r: r['bundle_status'].update(unavailable={'matchup': 'Missing weekly roster'})]
        for change in changes:
            receipt = complete_receipt(); change(receipt)
            with self.subTest(receipt=receipt), self.assertRaisesRegex(ValueError, 'complete captured'):
                publisher.validate_requested_bundle(receipt, 'all')

    def test_both_feature_opt_ins_required_before_review_branch_creation(self):
        for game_enabled, matchup_enabled in ((None, None), ('false', 'true'), ('true', 'false')):
            env = {'FEATURES_REQUESTED': 'all'}
            if game_enabled: env['NFL_PM_GAME_PREDICTOR_ENABLED'] = game_enabled
            if matchup_enabled: env['NFL_PM_MATCHUP_INTELLIGENCE_ENABLED'] = matchup_enabled
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(publisher, 'git', side_effect=['a'*40, '', str(Path.cwd()), 'a'*40+' refs/heads/main', '']) as git, \
                 patch.object(publisher, 'assert_no_pending'), \
                 patch.object(publisher, 'validate_candidate', return_value=({}, None, complete_receipt())):
                with self.assertRaisesRegex(ValueError, 'inactive'):
                    publisher.create_data_pr('TEST FIXTURE', 'a'*40, '1', '1')
                self.assertFalse(any(c.args[0] in {'switch', 'push', 'commit'} for c in git.call_args_list))

    def test_complete_proposal_still_pushes_only_unique_branch_and_opens_draft(self):
        from reviewed_publication import MANIFEST, PREFIX
        folder = '2026/week-8/20261030T120000Z-0123456789ab'
        names = ('board.json', 'breakdowns.json', 'receipt.json', 'game-predictor.json', 'matchup-intelligence.json')
        allowed = {MANIFEST} | {PREFIX+folder+'/'+n for n in names}
        def git(*args):
            if args == ('rev-parse', 'HEAD'): return 'a'*40
            if args[0] == 'status': return ''
            if args == ('rev-parse', '--show-toplevel'): return str(Path.cwd())
            if args[:2] == ('ls-remote', 'origin'):
                return '' if args[-1].endswith('/*') else 'a'*40+' refs/heads/main'
            if args == ('diff', '--cached', '--name-only'): return '\n'.join(sorted(allowed))
            if args == ('diff', '--name-only'): return MANIFEST
            if args[0] == 'ls-files': return '\n'.join(sorted(allowed-{MANIFEST}))
            return ''
        summary = dict(season=2026, week=8, players=2, games=1, manifest_sha256='f'*64)
        with patch.dict(os.environ, {'FEATURES_REQUESTED': 'all', 'NFL_PM_GAME_PREDICTOR_ENABLED': 'true',
                                    'NFL_PM_MATCHUP_INTELLIGENCE_ENABLED': 'true'}, clear=True), \
             patch.object(publisher, 'git', side_effect=git) as commands, \
             patch.object(publisher, 'assert_no_pending'), patch.object(publisher, 'fresh'), \
             patch.object(publisher, 'validate_candidate', return_value=({'meta': {'season': 2026, 'week': 8}}, None, complete_receipt())), \
             patch.object(publisher, 'retrieve_schedule', return_value=[]), patch.object(publisher, 'verify_current_schedule'), \
             patch.object(publisher, 'publish_candidate', return_value=folder), \
             patch.object(publisher, 'validate_change', return_value=summary), \
             patch.object(publisher, 'github', return_value={'html_url': 'https://example.invalid/TEST-FIXTURE'}) as api:
            publisher.create_data_pr('TEST FIXTURE', 'a'*40, '99', '2')
            calls = [c.args for c in commands.call_args_list]
            self.assertIn(('push', 'origin', 'HEAD:refs/heads/nfl-pm/publication/99-2'), calls)
            self.assertFalse(any('--force' in c or 'HEAD:refs/heads/main' in c for c in calls))
            self.assertTrue(api.call_args.args[1]['draft'])

    def test_workflow_remains_manual_opted_in_and_retains_full_evidence(self):
        workflow = yaml.load(Path('.github/workflows/weekly-predictions.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
        inputs = workflow['on']['workflow_dispatch']['inputs']
        self.assertEqual(inputs['features']['default'], 'core')
        self.assertEqual(inputs['features']['options'], ['core', 'all'])
        self.assertEqual(inputs['publish']['default'], 'false')
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        publish = workflow['jobs']['publish']
        self.assertEqual(publish['environment'], 'nfl-pm-production')
        self.assertIn("github.ref == 'refs/heads/main'", publish['if'])
        self.assertIn("vars.NFL_PM_PUBLISHING_ENABLED == 'true'", publish['if'])
        self.assertIn('inputs.publish == true', publish['if'])
        step = next(s for s in publish['steps'] if s.get('run') == 'python automation_publish.py')
        for name in ('NFL_PM_GAME_PREDICTOR_ENABLED', 'NFL_PM_MATCHUP_INTELLIGENCE_ENABLED'):
            self.assertIn('vars.'+name, step['env'][name])
        generation = workflow['jobs']['generate']
        self.assertNotIn('environment', generation)
        self.assertTrue(any('replay' in s.get('run', '') and 'validate_requested_bundle' in s.get('run', '') for s in generation['steps']))
        uploads = [s for s in generation['steps'] if 'upload-artifact@' in s.get('uses', '')]
        self.assertEqual(len(uploads), 2)
        self.assertTrue(all(s['with']['retention-days'] == '90' for s in uploads))


class CapturedReleaseRehearsalTests(unittest.TestCase):
    def test_full_capture_review_deployment_and_rollback_without_live_paths(self):
        from test_weekly_data import captures, FIXTURE_NOW
        from test_reviewed_publication import DataPRTests
        from test_weekly_automation import game
        from weekly_data import build_from_capture
        from weekly_storage import publish_candidate
        from reviewed_publication import validate_change, tree, MANIFEST, PREFIX
        from verify_publication import verify_json, PRODUCTION
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            f = DataPRTests('test_valid_data_only_pr_and_complete_coverage')
            f.setUp(); self.addCleanup(f.doCleanups)
            previous = (f.data/'manifest.json').read_bytes()
            before = tree(f.repo, f.head)
            with patch('weekly_capture.utc_now', return_value=FIXTURE_NOW+timedelta(seconds=1)), \
                 patch('weekly_data.utc_now', return_value=FIXTURE_NOW+timedelta(seconds=1)), \
                 patch('weekly_storage.utc_now', return_value=FIXTURE_NOW+timedelta(seconds=1)):
                captures(root/'inputs')
                result = build_from_capture(root/'inputs', root/'candidate', f.data, 2026, 9)
                receipt = json.loads((root/'candidate/receipt.json').read_bytes())
                publisher.validate_requested_bundle(receipt, 'all')
                # The standalone command keeps code/runtime guards; only synthetic
                # test clocks and the public schedule response are replaced here.
                import release_rehearsal
                with patch.object(release_rehearsal, 'utc_now', return_value=FIXTURE_NOW+timedelta(seconds=1)), \
                     patch('reviewed_publication.utc_now', return_value=FIXTURE_NOW+timedelta(seconds=1)), \
                     patch.object(release_rehearsal, 'retrieve_schedule', return_value=[game(week=9, day='2026-11-08')]):
                    staged = release_rehearsal.rehearse(root/'candidate', f.data, root/'rehearsal')
                    self.assertEqual(staged['artifact_sha256'], result['artifact_hashes'])
                    self.assertEqual(staged['baseline_manifest_sha256'], staged['restored_manifest_sha256'])
                    self.assertFalse(staged['production_modified'])
                    self.assertFalse(staged['remote_git_write_or_production_deployment_performed'])
                    self.assertEqual(len(staged['artifact_sha256']), 5)
                    with self.assertRaises(FileExistsError):
                        release_rehearsal.rehearse(root/'candidate', f.data, root/'rehearsal')
                with patch('urllib.request.urlopen', side_effect=AssertionError('Offline replay attempted network')):
                    repeated = build_from_capture(root/'inputs', root/'replay', f.data, 2026, 9, replay=True)
                self.assertEqual(result, repeated)
                relative = publish_candidate(root/'candidate', f.data, now=FIXTURE_NOW+timedelta(seconds=1))
                head = f.commit()
                records = [game(week=9, day='2026-11-08')]
                checked = validate_change(f.repo, f.head, head, 'nfl-pm/publication/99-1', records, FIXTURE_NOW+timedelta(seconds=1))
                self.assertEqual(checked['players'], 2)
                after = tree(f.repo, head)
                self.assertEqual(len(set(after)-set(before)), 5)
                def fetch(url): return after[PREFIX+url.removeprefix(PRODUCTION+'/data/')]
                verified = verify_json(after, fetch)
                for name in result['artifact_hashes']:
                    self.assertEqual((root/'candidate'/name).read_bytes(), (root/'replay'/name).read_bytes())
                    self.assertEqual(after[PREFIX+relative+'/'+name], (root/'candidate'/name).read_bytes())
                self.assertIn(relative+'/game-predictor.json', verified)
                self.assertIn(relative+'/matchup-intelligence.json', verified)
                (f.data/'manifest.json').write_bytes(previous)
                rollback = f.commit()
                self.assertEqual(validate_change(f.repo, head, rollback, 'nfl-pm/rollback/rehearsal', records, FIXTURE_NOW)['kind'], 'rollback')
                restored = tree(f.repo, rollback)
                self.assertEqual(restored[MANIFEST], before[MANIFEST])
                self.assertEqual({n: v for n, v in restored.items() if n != MANIFEST},
                                 {n: v for n, v in after.items() if n != MANIFEST})


if __name__ == '__main__':
    unittest.main()
