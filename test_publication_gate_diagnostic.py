"""Read-only workflow diagnostics; no capture, publication or remote requests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


class PublicationGateDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load(Path('.github/workflows/weekly-predictions.yml').read_text(), Loader=yaml.BaseLoader)
        self.job = self.workflow['jobs']['publication-gates']

    def test_diagnostic_cannot_publish_or_access_production_environment(self):
        self.assertEqual(self.job['permissions'], {'contents': 'read'})
        self.assertNotIn('environment', self.job)
        self.assertEqual(self.job['needs'], 'generate')
        self.assertEqual(self.job['if'], '${{ !cancelled() }}')
        self.assertEqual(len(self.job['steps']), 1)
        step = self.job['steps'][0]
        self.assertNotIn('uses', step)  # no checkout or external actions
        for value in step['env'].values():
            self.assertNotIn('secrets.', value)
            self.assertNotIn('github.token', value)
        self.assertNotIn('toJSON(vars)', str(step))
        self.assertNotIn('toJSON(github)', str(step))
        for command in ('git push', 'automation_publish', 'capture-generate', 'vercel'):
            self.assertNotIn(command, step['run'])

    def test_diagnostic_only_skips_generation_and_preserves_all_publication_gates(self):
        inputs = self.workflow['on']['workflow_dispatch']['inputs']
        self.assertEqual(inputs['diagnostic_only'], {
            'description': 'Read-only gate report; skips generation and PR creation even if publish is checked',
            'type': 'boolean', 'default': 'false'})
        jobs = self.workflow['jobs']
        self.assertEqual(jobs['plan']['if'], 'inputs.diagnostic_only != true')
        self.assertEqual(jobs['generate']['needs'], 'plan')
        self.assertEqual(jobs['generate']['if'], "needs.plan.outputs.ready == 'true'")
        publish = jobs['publish']
        self.assertEqual(publish['needs'], ['generate', 'publication-gates'])
        self.assertEqual(publish['environment'], 'nfl-pm-production')
        self.assertEqual(' '.join(publish['if'].split()),
                         "inputs.diagnostic_only != true && github.ref == 'refs/heads/main' && vars.NFL_PM_PUBLISHING_ENABLED == 'true' && inputs.publish == true")
        self.assertEqual(self.job['steps'][0]['env']['GATE_ORIGINAL'],
                         "${{ github.ref == 'refs/heads/main' && vars.NFL_PM_PUBLISHING_ENABLED == 'true' && inputs.publish == true }}")
        self.assertNotIn('schedule', self.workflow['on'])

    def run_report(self, **overrides):
        source = self.job['steps'][0]['run'].split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        env = {**os.environ, 'EVENT_NAME': 'workflow_dispatch', 'ACTUAL_REF': 'refs/heads/main',
               'WORKFLOW_REF': 'TEST FIXTURE', 'WORKFLOW_SHA': 'a'*40, 'GENERATE_RESULT': 'skipped',
               'DIAGNOSTIC_ONLY': 'true', 'GATE_MAIN': 'true', 'GATE_ENABLED': 'true',
               'GATE_PUBLISH': 'true', 'GATE_ORIGINAL': 'true', 'PUBLISH_VALUE_JSON': 'true',
               'EVENT_PUBLISH_JSON': '"true"', 'ENABLED_VALUE_JSON': '"true"',
               'GAME_VALUE_JSON': '"true"', 'MATCHUP_VALUE_JSON': '"true"', **overrides}
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            summary = Path(temporary)/'summary.md'
            env['GITHUB_STEP_SUMMARY'] = str(summary)
            result = subprocess.run([sys.executable, '-B', '-c', source], env=env, capture_output=True, text=True, check=True)
            report = json.loads(result.stdout)
            self.assertIn('Read-only publication gates', summary.read_text())
        return report

    def test_report_distinguishes_typed_input_from_raw_event_string(self):
        report = self.run_report()
        self.assertTrue(report['gates']['original_condition'])
        self.assertEqual(report['observations']['PUBLISH_VALUE_JSON'], {'type': 'bool', 'value': True, 'length': None})
        self.assertEqual(report['observations']['EVENT_PUBLISH_JSON']['type'], 'str')
        self.assertTrue(report['diagnostic_only'])
        self.assertEqual(report['generation_result'], 'skipped')

    def test_report_exposes_false_gates_missing_flags_and_whitespace(self):
        for key, field in [('GATE_MAIN', 'main_ref'), ('GATE_ENABLED', 'repository_publishing_flag'), ('GATE_PUBLISH', 'typed_publish_input')]:
            with self.subTest(key=key):
                report = self.run_report(**{key: 'false', 'GATE_ORIGINAL': 'false'})
                self.assertFalse(report['gates'][field])
                self.assertFalse(report['gates']['original_condition'])
        self.assertEqual(self.run_report(ENABLED_VALUE_JSON='""')['observations']['ENABLED_VALUE_JSON']['value'], '')
        self.assertEqual(self.run_report(ENABLED_VALUE_JSON='"true "')['observations']['ENABLED_VALUE_JSON']['value'], 'true ')

    def test_unexpected_variable_contents_are_redacted(self):
        report = self.run_report(ENABLED_VALUE_JSON='"TEST FIXTURE accidental non-boolean"')
        self.assertEqual(report['observations']['ENABLED_VALUE_JSON']['value'], '<non-boolean value redacted>')
        self.assertNotIn('accidental', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
