"""Protected baseline/source/data-only audit fixtures; no production or network writes."""
import unittest
from pathlib import Path
from unittest.mock import patch

from validation_tools import integrity


class IntegrityAuditTests(unittest.TestCase):
    def setUp(self):
        from test_reviewed_publication import DataPRTests
        self.f = DataPRTests('test_valid_data_only_pr_and_complete_coverage')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        f = self.f
        # Explicit synthetic orphan JSON pads this temporary baseline to 13 files.
        for i in range(6):
            (f.data/f'TEST-FIXTURE-{i}.json').write_text('{"fixture":true}', encoding='utf-8')
        for name in ('td_predictor_v5.py', 'game_projection.py', 'td-predictor-web/lib/parlay.ts'):
            path = f.repo/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(Path(name).read_bytes())
        f.fixture_git('add', '--', 'td_predictor_v5.py', 'game_projection.py', 'td-predictor-web/lib/parlay.ts')
        self.base = f.commit()

    def propose(self):
        from test_weekly_automation import candidate
        from weekly_storage import digest, publish_candidate
        f = self.f
        source, _ = candidate(f.repo/'integrity-candidate', now=f.now, base=digest(f.data/'manifest.json'))
        self.relative = publish_candidate(source, f.data, now=f.now)
        self.head = f.commit()
        return self.head

    def audit(self, branch=None, base=None):
        from test_weekly_automation import game
        with patch('reviewed_publication.retrieve_schedule', return_value=[game()]), \
             patch('reviewed_publication.utc_now', return_value=self.f.now):
            return integrity(base or self.base, branch=branch, repo=self.f.repo)

    def test_source_baseline_and_future_larger_baselines_are_supported(self):
        self.assertEqual(self.audit()['protected_json_files'], 13)
        head = self.propose()
        self.assertEqual(self.audit('nfl-pm/publication/99-1')['kind'], 'publication')
        self.assertEqual(self.audit(base=head)['protected_json_files'], 16)

    def test_real_data_only_diff_needs_explicit_review_branch(self):
        self.propose()
        with self.assertRaisesRegex(ValueError, 'explicit'): self.audit()
        with self.assertRaisesRegex(ValueError, 'publication or rollback'): self.audit('feature/unreviewed')

    def test_existing_snapshot_mutation_or_deletion_is_never_allowed(self):
        path = self.f.data/self.f.old_folder/'board.json'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError, 'snapshot'): self.audit()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'snapshot'): self.audit()

    def test_calculation_changes_rejected_in_worktree_and_commit(self):
        path = self.f.repo/'game_projection.py'
        original = path.read_bytes()
        path.write_bytes(original+b'\n# TEST FIXTURE forbidden calculation edit\n')
        with self.assertRaisesRegex(ValueError, 'calculation'): self.audit()
        self.f.fixture_git('add', 'game_projection.py')
        self.f.fixture_git('commit', '-qm', 'TEST FIXTURE forbidden protected edit')
        path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'calculation'): self.audit()

    def test_untracked_or_committed_extra_json_without_manifest_is_rejected(self):
        path = self.f.data/'TEST-FIXTURE-unexpected.json'
        path.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError): self.audit()
        self.f.commit()
        with self.assertRaises(ValueError): self.audit()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'hidden'): self.audit()

    def test_reviewed_publication_cannot_hide_untracked_data(self):
        self.propose()
        (self.f.data/'TEST-FIXTURE-untracked.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Uncommitted or untracked'):
            self.audit('nfl-pm/publication/99-1')

    def test_manifest_only_rollback_retains_all_old_and_new_archives(self):
        previous = (self.f.data/'manifest.json').read_bytes()
        head = self.propose()
        (self.f.data/'manifest.json').write_bytes(previous)
        self.f.commit()
        self.assertEqual(self.audit('nfl-pm/rollback/integrity', base=head)['kind'], 'rollback')
        self.assertTrue((self.f.data/self.relative/'board.json').exists())


if __name__ == '__main__':
    unittest.main()
