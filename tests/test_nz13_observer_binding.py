"""Prospective profile identity cannot be replaced by a historical oracle tag."""
import json
import unittest
from dataclasses import replace

from runtime.mission.project_recipe import PythonFunctionCase, PythonRepositoryRecipe
from runtime.mission.sandbox_contracts import PYTHON_ARGV


class ObserverVersionBindingTests(unittest.TestCase):
    def profile(self):
        self.assertTrue(hasattr(PythonRepositoryRecipe, 'accepts_observer'),
                        'Oracle receipt tags are not selected by the approved profile')
        case = PythonFunctionCase('case-1', 'textutil', 'slug', b'["x"]', b'"x"')
        return PythonRepositoryRecipe('repository-1', 'a' * 40, ('src/textutil.py',), ('src',),
                                      tuple((stage, (case,)) for stage in
                                            ('FAST_TESTS', 'TARGETED_TESTS', 'FINAL_TESTS')), PYTHON_ARGV)

    def test_default_profile_keeps_the_original_observer_identity(self):
        profile = self.profile()
        self.assertEqual('BOUNDED_AST_JSON_ORACLE_V2', profile.trusted_observer)
        self.assertTrue(profile.accepts_observer('BOUNDED_AST_JSON_ORACLE_V2'))

    def test_unrestricted_function_profile_has_a_distinct_versioned_observer(self):
        profile = replace(self.profile(), execution_profile='ISOLATED_PYTHON_FUNCTIONS_V1')
        self.assertEqual('ISOLATED_PYTHON_FUNCTION_ORACLE_V1', profile.trusted_observer)
        self.assertTrue(profile.accepts_observer('ISOLATED_PYTHON_FUNCTION_ORACLE_V1'))

    def test_prospective_effect_cannot_substitute_a_different_known_or_legacy_observer(self):
        original = self.profile()
        normal = replace(original, execution_profile='ISOLATED_PYTHON_FUNCTIONS_V1')
        for profile, marker in ((original, normal.trusted_observer), (normal, original.trusted_observer),
                                (original, 'EXTERNAL_JSON_ORACLE'), (normal, 'EXTERNAL_JSON_ORACLE')):
            with self.subTest(marker=marker):
                self.assertFalse(profile.accepts_observer(marker))

    def test_readback_accepts_only_the_closed_list_of_previously_qualified_versions(self):
        profile = self.profile()
        for marker in ('BOUNDED_AST_JSON_ORACLE_V2', 'ISOLATED_PYTHON_FUNCTION_ORACLE_V1', 'EXTERNAL_JSON_ORACLE'):
            with self.subTest(marker=marker):
                self.assertTrue(profile.accepts_observer(marker, historical=True))
        self.assertFalse(profile.accepts_observer('FUTURE_UNKNOWN_ORACLE', historical=True))

    def test_malformed_tags_and_ambiguous_history_flag_never_authorize_a_match(self):
        profile = self.profile()
        for marker in (None, False, {}, ['BOUNDED_AST_JSON_ORACLE_V2']):
            with self.subTest(marker=marker):
                self.assertFalse(profile.accepts_observer(marker, historical=True))
        for flag in ('true', 1, None):
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'RECIPE_OBSERVER_HISTORY_FLAG'):
                profile.accepts_observer(profile.trusted_observer, historical=flag)

    def test_manifest_cannot_override_the_trusted_observer_field(self):
        profile = self.profile()
        row = json.loads(profile.manifest_bytes())
        row['trusted_observer'] = 'ISOLATED_PYTHON_FUNCTION_ORACLE_V1'
        with self.assertRaisesRegex(ValueError, 'PYTHON_MANIFEST_SCHEMA'):
            PythonRepositoryRecipe.from_manifest(json.dumps(row).encode())
