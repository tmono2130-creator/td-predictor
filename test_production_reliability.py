"""Offline reliability boundaries. Synthetic fixtures never enter served paths."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

import yaml

from production_health import MissingFile, health
from publication_policy import fresh
from reviewed_publication import PREFIX
from test_weekly_automation import candidate, NOW
from weekly_schedule import forecast_deadline, refresh_status, refresh_due, utc


SHA = 'a' * 40
START = utc('2026-11-01T18:00:00Z')


class RefreshBoundaryTests(unittest.TestCase):
    def plan(self, now):
        return {'status': 'ready', 'season': 2026, 'week': 8,
                'games': [{'kickoff_utc': START.isoformat()}]}

    def manifest(self, capture):
        return {'seasons': {'2026': {'weeks': {'8': {'generated_at': capture.isoformat()}}}}}

    def test_deadlines_agree_with_unchanged_strict_publication_policy(self):
        for hours in [80, 60, 50, 40, 10, 6, 5, 1]:
            with self.subTest(hours=hours):
                captured = START - timedelta(hours=hours)
                deadline = forecast_deadline(captured, START)
                board = {'meta': {'generated_at': captured.isoformat(),
                                 'games': [{'kickoff_utc': START.isoformat()}]}}
                receipt = {'source_cutoff_utc': captured.isoformat()}
                fresh(board, receipt, deadline - timedelta(microseconds=1))
                with self.assertRaises(ValueError):
                    fresh(board, receipt, deadline)

    def test_future_window_transitions_can_expire_older_captures_immediately(self):
        self.assertEqual(forecast_deadline(START - timedelta(hours=60), START), START - timedelta(hours=48))
        self.assertEqual(forecast_deadline(START - timedelta(hours=10), START), START - timedelta(hours=6))

    def test_refresh_starts_before_expiry_including_equal_headroom_boundary(self):
        captured = START - timedelta(hours=20)
        due_at = captured + timedelta(hours=6) - timedelta(minutes=20)
        self.assertFalse(refresh_due(self.plan(due_at), self.manifest(captured), due_at - timedelta(microseconds=1)))
        self.assertTrue(refresh_due(self.plan(due_at), self.manifest(captured), due_at))

    def test_new_short_window_refresh_after_ten_minutes_not_thirty(self):
        captured = START - timedelta(hours=2)
        self.assertFalse(refresh_due(self.plan(captured), self.manifest(captured), captured + timedelta(minutes=9)))
        self.assertTrue(refresh_due(self.plan(captured), self.manifest(captured), captured + timedelta(minutes=10)))

    def test_budget_includes_future_six_hour_transition(self):
        captured = START - timedelta(hours=10)
        now = START - timedelta(hours=6, minutes=20)
        self.assertTrue(refresh_due(self.plan(now), self.manifest(captured), now))

    def test_receipt_cutoff_can_require_earlier_refresh(self):
        now = START - timedelta(hours=15)
        manifest = self.manifest(now - timedelta(hours=5))
        self.assertFalse(refresh_due(self.plan(now), manifest, now))
        self.assertTrue(refresh_status(self.plan(now), manifest, now,
                                       source_cutoff=now-timedelta(hours=5, minutes=45))['due'])

    def test_cannot_finish_at_or_inside_budget_plus_kickoff_margin(self):
        for minutes in [30, 29, 10, 0, -1]:
            now = START - timedelta(minutes=minutes)
            result = refresh_status(self.plan(now), {}, now)
            self.assertFalse(result['can_finish'])
            self.assertFalse(result['due'])
        now = START - timedelta(minutes=30, microseconds=1)
        self.assertTrue(refresh_status(self.plan(now), {}, now)['can_finish'])

    def test_idle_and_invalid_planning_inputs(self):
        self.assertFalse(refresh_due({'status': 'idle'}, {}, NOW))
        with self.assertRaises(ValueError):
            refresh_status(self.plan(NOW), {}, NOW, headroom=timedelta(0))
        with self.assertRaises(ValueError):
            refresh_due(self.plan(NOW), self.manifest(NOW + timedelta(seconds=1)), NOW)

    def test_due_only_cli_reports_blocked_headroom_instead_of_claiming_freshness(self):
        import weekly_pipeline
        from test_weekly_automation import game
        records = [game(week=8, day='2026-11-01', time='13:00')]
        output = io.StringIO()
        with patch('weekly_pipeline.retrieve_schedule', return_value=records), \
                patch('weekly_pipeline.validate_manifest', return_value={}), \
                patch('weekly_schedule.utc_now', return_value=START-timedelta(minutes=25)), \
                redirect_stdout(output):
            self.assertEqual(weekly_pipeline.main(['plan', '--season', '2026', '--week', '8', '--due-only']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['status'], 'idle')
        self.assertEqual(result['reason'], 'insufficient_release_headroom')


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        folder, self.now = candidate(Path(self.temp.name) / 'TEST-FIXTURE')
        self.folder = '2026/week-1/TEST-FIXTURE'
        self.files = {PREFIX + self.folder + '/' + p.name: p.read_bytes() for p in folder.iterdir()}
        receipt_name = PREFIX+self.folder+'/receipt.json'
        receipt = json.loads(self.files[receipt_name])
        capture = {'kind': 'live_capture', 'source_cutoff_utc': self.now.isoformat(),
                   'started_at_utc': self.now.isoformat(), 'sources': {'TEST-FIXTURE': {
                       'retrieved_at_utc': self.now.isoformat(), 'started_at_utc': self.now.isoformat(),
                       'available': True, 'optional': False}}}
        receipt['input_capture'] = {'manifest': capture, 'manifest_sha256': hashlib.sha256(
            json.dumps(capture, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
        self.files[receipt_name] = json.dumps(receipt).encode()
        self.manifest = {'schema_version': 1, 'supported_weeks': list(range(1, 19)),
                         'seasons': {'2026': {'weeks': {'1': {
                             'board': self.folder+'/board.json', 'breakdowns': self.folder+'/breakdowns.json',
                             'generated_at': self.now.isoformat(), 'model': 'composite'}}}}}
        self.encode_manifest()

    def encode_manifest(self):
        self.files[PREFIX+'manifest.json'] = json.dumps(self.manifest).encode()

    def fetch(self, url):
        from verify_publication import PRODUCTION
        if url == PRODUCTION + '/':
            return b'<html><title>NFL PM</title><script src="/_next/test.js"></script></html>'
        return self.files[PREFIX+url.removeprefix(PRODUCTION+'/data/')]

    def run_health(self, **kwargs):
        return health(self.files, SHA, now=kwargs.pop('now', self.now),
                      fetch=kwargs.pop('fetch', self.fetch), **kwargs)

    def test_current_content_without_deployment_access_is_unknown_not_verified(self):
        result = self.run_health()
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(result['snapshots'][0]['state'], 'current')
        self.assertEqual(result['snapshots'][0]['sidecars'], {
            'game_predictor': 'expected_unavailable', 'matchup_intelligence': 'expected_unavailable'})
        self.assertFalse(result['release_authorized'])

    def test_stale_data_is_warning_not_integrity_error(self):
        result = self.run_health(now=self.now+timedelta(hours=7))
        self.assertEqual(result['status'], 'DEGRADED')
        self.assertEqual(result['snapshots'][0]['state'], 'stale')
        self.assertNotIn('error', [c['status'] for c in result['checks']])

    def test_kickoff_margin_and_archive_are_distinct(self):
        board = json.loads(self.files[PREFIX+self.folder+'/board.json'])
        start = utc(board['meta']['games'][0]['kickoff_utc'])
        self.assertEqual(self.run_health(now=start-timedelta(minutes=10))['snapshots'][0]['state'], 'kickoff_margin')
        self.assertEqual(self.run_health(now=start)['snapshots'][0]['state'], 'archived')

    def test_missing_file_hash_and_network_failures_are_errors(self):
        for kind in ['missing_file', 'hash_mismatch', 'http_error']:
            def fetch(url):
                if url.endswith('/board.json'):
                    if kind == 'missing_file':
                        raise MissingFile()
                    if kind == 'http_error':
                        raise RuntimeError('TEST network failure')
                    return b'{}'
                return self.fetch(url)
            result = self.run_health(fetch=fetch)
            self.assertEqual(result['status'], 'ERROR')
            self.assertIn(kind, [c['kind'] for c in result['checks']])

    def test_unpublished_week_is_expected_unavailable(self):
        result = self.run_health(season=2026, week=10)
        self.assertEqual(result['snapshots'][0]['state'], 'expected_unavailable')
        self.assertNotIn('error', [c['status'] for c in result['checks']])

    def test_pinned_but_missing_sidecar_is_not_expected_unavailable(self):
        entry = self.manifest['seasons']['2026']['weeks']['1']
        entry.update(game_predictor=self.folder+'/game-predictor.json', game_predictor_sha256='f'*64)
        self.encode_manifest()
        self.assertEqual(self.run_health()['status'], 'ERROR')

    def test_manifest_race_and_archived_file_changes_fail(self):
        reads = []
        def fetch(url):
            if url.endswith('/manifest.json'):
                reads.append(url)
                if len(reads) > 1:
                    return b'{}'
            return self.fetch(url)
        self.assertEqual(self.run_health(fetch=fetch)['status'], 'ERROR')
        archive = PREFIX+'2025/week-1/TEST-ARCHIVE/board.json'
        self.files[archive] = b'{}'
        self.assertEqual(self.run_health(fetch=lambda u: b'BAD' if 'TEST-ARCHIVE' in u else self.fetch(u))['status'], 'ERROR')

    def test_deployment_errors_and_alias_movement_cannot_look_healthy(self):
        def failed(sha):
            raise ValueError('TEST failed exact deployment')
        self.assertEqual(self.run_health(deployment_check=failed)['status'], 'ERROR')
        replies = iter([{'deployment_id': 'first'}, {'deployment_id': 'second'}])
        self.assertEqual(self.run_health(deployment_check=lambda sha: next(replies))['status'], 'ERROR')
        result = self.run_health(deployment_check=lambda sha: {'deployment_id': 'fixed', 'commit': sha})
        self.assertEqual(result['status'], 'HEALTHY')

    def test_future_timestamp_and_receipt_tampering_fail_closed(self):
        self.assertEqual(self.run_health(now=self.now-timedelta(seconds=1))['status'], 'ERROR')
        name = PREFIX+self.folder+'/receipt.json'
        receipt = json.loads(self.files[name]); receipt['board_sha256'] = '0'*64
        self.files[name] = json.dumps(receipt).encode()
        self.assertEqual(self.run_health()['status'], 'ERROR')

    def test_login_or_error_shell_is_not_healthy(self):
        result = self.run_health(fetch=lambda url: b'<html>Login required</html>' if url.endswith('.space/') else self.fetch(url))
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('website_unavailable_or_unexpected_page', [c['kind'] for c in result['checks']])


class ReadOnlyWorkflowTests(unittest.TestCase):
    def test_monitor_is_manual_read_only_and_has_no_production_secrets(self):
        raw = Path('.github/workflows/production-health.yml').read_text()
        workflow = yaml.load(raw, Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        job = workflow['jobs']['health']
        self.assertEqual(job['if'], "github.ref == 'refs/heads/main'")
        self.assertNotIn('environment', job)
        for forbidden in ['secrets.', 'contents: write', 'pull-requests: write', 'automation_publish',
                          'git push', 'git commit', 'vercel deploy', 'schedule:']:
            self.assertNotIn(forbidden, raw)
        self.assertFalse(any('permissions' in step for step in job['steps']))

    def test_publishing_and_exact_release_verifier_are_not_replaced(self):
        raw = Path('.github/workflows/weekly-predictions.yml').read_text()
        workflow = yaml.load(raw, Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
        self.assertIn("inputs.publish == true", workflow['jobs']['publish']['if'])
        self.assertEqual(workflow['jobs']['publish']['environment'], 'nfl-pm-production')
        self.assertIn('verify_publication.py', Path('.github/workflows/verify-published-data.yml').read_text())

    def test_only_trusted_source_classification_enables_local_health_browser_mode(self):
        workflow = yaml.load(Path('.github/workflows/reviewed-data-checks.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow['jobs']['publication-safety']['outputs']['change_kind'],
                         '${{ steps.contract.outputs.kind }}')
        steps = workflow['jobs']['publication-safety']['steps']
        contract = next(s for s in steps if s.get('id') == 'contract')
        self.assertIn('result = validate_change(', contract['run'])
        browser = next(s for s in workflow['jobs']['frontend']['steps'] if 'CONTENT_HEALTH_ONLY' in s.get('env', {}))
        self.assertEqual(browser['env']['CONTENT_HEALTH_ONLY'],
                         "${{ needs.publication-safety.outputs.change_kind == 'source' }}")
        for filename in ['.github/workflows/weekly-predictions.yml', '.github/workflows/verify-published-data.yml']:
            self.assertNotIn('CONTENT_HEALTH_ONLY', Path(filename).read_text())
        source = Path('td-predictor-web/scripts/publication-smoke.mjs').read_text(encoding='utf-8')
        self.assertIn("process.env.CONTENT_HEALTH_ONLY === 'true'", source)
        self.assertIn('Source-only content health mode is restricted to localhost', source)
        self.assertIn("value.status, 'available'", source)


class ReleasedBundleReadOnlyTests(unittest.TestCase):
    def test_core_either_and_both_sidecars_using_released_bytes_in_memory_only(self):
        from reviewed_publication import tree
        from verify_publication import PRODUCTION
        # No writes, clock patching, or release eligibility claim. Real immutable
        # bytes exercise optional semantic validators at their original timestamp.
        files = tree(Path.cwd(), '0631ea9f6d0ffbb69185c54bd7ee722d840514e7')
        original = json.loads(files[PREFIX+'manifest.json'])
        for included in [(), ('game_predictor',), ('matchup_intelligence',),
                         ('game_predictor', 'matchup_intelligence')]:
            expected = dict(files)
            manifest = copy.deepcopy(original)
            entry = manifest['seasons']['2026']['weeks']['8']
            receipt_name = PREFIX+str(Path(entry['board']).with_name('receipt.json')).replace('\\', '/')
            receipt = json.loads(expected[receipt_name])
            for key in ['game_predictor', 'matchup_intelligence']:
                if key not in included:
                    del expected[PREFIX+entry.pop(key)]
                    entry.pop(key+'_sha256')
                    receipt.pop(key+'_sha256')
            expected[PREFIX+'manifest.json'] = json.dumps(manifest).encode()
            expected[receipt_name] = json.dumps(receipt).encode()
            result = health(expected, SHA, now=utc(entry['generated_at'])+timedelta(seconds=1),
                            fetch=lambda url: b'<title>NFL PM</title><script src="/_next/test.js"></script>'
                            if url == PRODUCTION+'/' else expected[PREFIX+url.removeprefix(PRODUCTION+'/data/')],
                            deployment_check=lambda sha: {'commit': sha, 'deployment_id': 'TEST ONLY'})
            self.assertEqual(result['status'], 'HEALTHY', result['checks'][-1])
            self.assertEqual(result['snapshots'][0]['state'], 'current')
            for key in ['game_predictor', 'matchup_intelligence']:
                self.assertEqual(result['snapshots'][0]['sidecars'][key],
                                 'present_verified' if key in included else 'expected_unavailable')


if __name__ == '__main__':
    unittest.main()
