"""Normal-function and renderer policies belong to the existing Native seal."""
import unittest
from pathlib import PurePosixPath

from runtime.meta_hackathon.runtime_adapter import SOURCE_FILES

REQUIRED = {
    'runtime/mission/python_test_contracts.py',
    'runtime/mission/dependency_lock.py', 'runtime/mission/function_isolation.py',
    'runtime/mission/python_function_worker.py', 'runtime/mission/python_function_child.py',
    'runtime/mission/repository_worker.py', 'runtime/mission/render_recipe.py',
    'runtime/mission/render_worker.py', 'runtime/mission/render_runtime.py',
    'runtime/mission/render_observation.py', 'runtime/mission/repair_validation.py',
    'runtime/mission/worker.py', 'runtime/mission/codex_worker.py',
    'runtime/mission/patchset.py', 'runtime/mission/repair.py',
    'runtime/mission/patch_capsule.py', 'runtime/mission/coding_tasks.py',
    'runtime/mission/target_settlement.py',
    'runtime/mission/target_projection.py',
    'runtime/mission/portable_target.py',
}


class ProfileSourceSealTests(unittest.TestCase):
    def test_all_profile_helpers_and_core_validation_authority_are_covered_by_one_existing_seal(self):
        self.assertFalse(REQUIRED - set(SOURCE_FILES), 'Unsealed function/render/Core policy helpers')

    def test_profile_seal_has_no_duplicate_or_private_paths_and_keeps_existing_core_boundaries(self):
        self.assertEqual(len(SOURCE_FILES), len(set(SOURCE_FILES)))
        for name in SOURCE_FILES:
            path = PurePosixPath(name)
            self.assertFalse(path.is_absolute())
            self.assertNotIn('..', path.parts)
            self.assertNotIn(path.name, {'REVIEW_NZ12_MAIN_RANGE.md', 'REVIEW_NZ12_RAW.json'})
            self.assertNotIn(path.suffix, ('.pem', '.sqlite3', '.db'))
        self.assertTrue({'runtime/core_admission.py', 'runtime/mission/warrant.py',
                         'runtime/mission/intent.py', 'runtime/mission/sandbox_linux.py',
                         'runtime/mission/native/bootstrap.c', 'runtime/failure_boundary.py'} <= set(SOURCE_FILES))
