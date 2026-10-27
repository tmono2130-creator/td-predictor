"""Safety contract for the feature-only, read-only hosted validation workflow."""
from pathlib import Path
import re
import unittest
import yaml


class FeatureValidationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path('.github/workflows/weekly-validation.yml').read_text(encoding='utf-8-sig')
        cls.workflow = yaml.load(cls.text, Loader=yaml.BaseLoader)

    def test_only_scoped_feature_pushes_trigger_validation(self):
        trigger = self.workflow['on']
        self.assertEqual(set(trigger), {'push'})
        self.assertEqual(trigger['push']['branches'], ['feature/nfl-pm-weekly-automation'])
        self.assertIn('.github/workflows/weekly-validation.yml', trigger['push']['paths'])
        self.assertIn('test_*.py', trigger['push']['paths'])
        self.assertNotIn('**', trigger['push']['paths'])

    def test_repository_access_is_read_only_and_no_production_capabilities(self):
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertEqual(set(self.workflow['jobs']), {'validate', 'frontend'})
        self.assertNotIn('secrets.', self.text)
        for job in self.workflow['jobs'].values():
            self.assertNotIn('environment', job)
            self.assertNotIn('permissions', job)
            self.assertNotIn('continue-on-error', job)
        for step in [step for job in self.workflow['jobs'].values() for step in job['steps']]:
            command = step.get('run', '')
            self.assertNotRegex(command, r'(?i)\bgit\s+(?:commit|push)\b|\bvercel\b|deploy_hook|\bpublish\b|--allow-historical')
            self.assertNotIn('continue-on-error', step)
            self.assertNotIn('env', step)
            if 'uses' in step:
                self.assertRegex(step['uses'], r'^actions/(?:checkout|setup-python|setup-node|upload-artifact)@[a-f0-9]{40}$')
            if step.get('uses', '').startswith('actions/checkout@'):
                self.assertEqual(step['with']['persist-credentials'], 'false')

    def test_frontend_build_is_isolated_and_failures_are_visible(self):
        self.assertIn('td-predictor-web/**', self.workflow['on']['push']['paths'])
        job = self.workflow['jobs']['frontend']
        self.assertEqual(job['runs-on'], 'ubuntu-latest')
        self.assertLessEqual(int(job['timeout-minutes']), 15)
        self.assertEqual(job['defaults']['run']['working-directory'], 'td-predictor-web')
        self.assertNotIn('needs', job)
        commands = [step['run'] for step in job['steps'] if 'run' in step]
        self.assertIn('npm ci --no-audit --no-fund', commands)
        self.assertIn('npm run lint', commands)
        self.assertIn('node --experimental-strip-types --test scripts/freshness.test.mjs', commands)
        self.assertIn('npm run build', commands)
        self.assertIn('git diff --exit-code HEAD -- .', commands)
        for step in job['steps']:
            if 'run' in step:
                self.assertIn('timeout-minutes', step)
                self.assertNotIn('|| true', step['run'])

    def test_candidates_and_artifacts_use_temporary_storage_only(self):
        steps = self.workflow['jobs']['validate']['steps']
        generation = next(s for s in steps if s.get('name', '').startswith('Generate unpublished'))
        self.assertIn("main(['generate'", generation['run'])
        self.assertIn("os.environ['RUNNER_TEMP']", generation['run'])
        self.assertIn("'--candidate', str(folder / 'candidate')", generation['run'])
        self.assertNotIn('public/data', generation['run'])
        self.assertEqual(generation['if'], "steps.plan.outputs.ready == 'true'")
        validation = next(s for s in steps if s.get('name', '').startswith('Validate candidate'))
        self.assertIn('weekly_pipeline.py validate --candidate "$RUNNER_TEMP/', validation['run'])
        artifact = next(s for s in steps if s.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertEqual(artifact['with']['path'], '${{ runner.temp }}/nfl-pm-validation/**/*.json')
        self.assertEqual(artifact['with']['retention-days'], '7')
        self.assertEqual(artifact['with']['if-no-files-found'], 'error')

    def test_timeouts_and_failure_propagation(self):
        job = self.workflow['jobs']['validate']
        self.assertEqual(job['runs-on'], 'ubuntu-latest')
        self.assertLessEqual(int(job['timeout-minutes']), 40)
        for step in job['steps']:
            if 'run' in step:
                self.assertIn('timeout-minutes', step)
                self.assertNotIn('|| true', step['run'])
                self.assertNotIn('set +e', step['run'])
        plan = next(s for s in job['steps'] if s.get('id') == 'plan')
        self.assertIn('weekly_pipeline.py plan', plan['run'])
        self.assertIn('$RUNNER_TEMP/', plan['run'])


if __name__ == '__main__':
    unittest.main()
