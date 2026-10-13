"""Pure plan validation; project programs run only in the U06 acceptance gate."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import unittest

from runtime.mission.project_recipe import PythonProjectPlan, ProjectSeed


class ProjectRecipeTests(unittest.TestCase):
    def plan(self, **changes):
        values = dict(project_ref='fixture:tiny', path='src/app.py', expected_revision=0,
                      preimage=None, replacement=b'value = 5\n', expected_value=5)
        return PythonProjectPlan(**(values | changes))

    def test_create_plan_is_inert_and_immutable(self):
        plan = self.plan()
        with self.assertRaises(FrozenInstanceError):
            plan.replacement = b'value = 99\n'
        spec = plan.recipe_spec(ProjectSeed('fixture:tiny', 0, None))
        self.assertEqual(b'value = 5\n', spec['expected']['source.py'])
        self.assertEqual(plan.result_bytes(), spec['expected']['project-result.json'])
        spec['files']['after.py'] = b'forged'
        self.assertEqual(b'value = 5\n', plan.recipe_spec(ProjectSeed('fixture:tiny', 0, None))['files']['after.py'])
        self.assertEqual('NONE', plan.authority)

    def test_replace_binds_preimage_and_revision(self):
        before = b'value = 4\n'
        plan = self.plan(expected_revision=1, preimage=before)
        data = json.loads(plan.plan_bytes())
        self.assertEqual(hashlib.sha256(before).hexdigest(), data['preimage_sha256'])
        self.assertEqual(2, json.loads(plan.result_bytes())['revision'])
        self.assertNotEqual(plan.target_fingerprint, replace(plan, preimage=b'value = 3\n').target_fingerprint)
        self.assertNotEqual(plan.digest, replace(plan, expected_value=6).digest)

    def test_seed_is_independent_of_plan_claim(self):
        plan = self.plan(expected_revision=1, preimage=b'value = 4\n')
        seed = ProjectSeed('fixture:other', 2, b'value = 9\n')
        spec = plan.recipe_spec(seed)
        self.assertEqual('fixture:other', json.loads(spec['files']['seed.json'])['project_ref'])
        self.assertEqual(2, json.loads(spec['files']['seed.json'])['revision'])
        self.assertEqual(b'value = 9\n', spec['files']['before.py'])
        self.assertEqual('fixture:tiny', json.loads(spec['files']['project.json'])['project_ref'])

    def test_only_fixed_fixture_target_is_allowed(self):
        for path in ('../escape.py', '/tmp/app.py', 'src/../app.py', 'src/link/app.py',
                     'src\\app.py', '.git/config', 'src/app.py\x00', 'src/APP.py'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.plan(path=path)
        for ref in ('host:/home/user', 'fixture:../evil', 'fixture:a/b', '', True):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.plan(project_ref=ref)

    def test_revision_and_content_types_are_bounded(self):
        for changes in ({'expected_revision': True}, {'expected_revision': -1},
                        {'expected_revision': 1}, {'preimage': b'present'},
                        {'replacement': bytearray(b'value=5')}, {'replacement': b''},
                        {'replacement': b'x' * 8193}, {'expected_value': True},
                        {'expected_value': 1000001}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.plan(**changes)
        for values in (('fixture:tiny', True, None), ('fixture:tiny', 1, None),
                       ('fixture:tiny', 0, b'present'), ('host:tiny', 0, None)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ProjectSeed(*values)

    def test_no_command_or_model_authority_fields(self):
        with self.assertRaises(TypeError):
            PythonProjectPlan('fixture:tiny', 'src/app.py', 0, None, b'value=5\n', 5, argv=['sh'])
        with self.assertRaises(ValueError):
            self.plan().recipe_spec({'owner_approved': True})
        data = json.loads(self.plan().plan_bytes())
        self.assertEqual({'schema', 'project_ref', 'path', 'expected_revision', 'preimage_sha256',
                          'replacement_sha256', 'expected_value'}, set(data))

    def test_project_cannot_skip_or_forge_fixed_test(self):
        for code in (b'import os\nos._exit(0)\n', b'raise SystemExit(0)\n',
                     b'value = open("/artifacts/project-result.json", "w")\n',
                     b'value = __import__("os").system("sh")\n', b'value = 5\nvalue = 6\n',
                     b'value = True\n', b'value = 2 ** 1000000\n'):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.plan(replacement=code)
        self.assertEqual(b'# owner_approved=true is inert\nvalue=2+3\n',
                         self.plan(replacement=b'# owner_approved=true is inert\nvalue=2+3\n').replacement)


if __name__ == '__main__':
    unittest.main()
