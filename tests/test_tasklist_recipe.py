"""Fixed useful-app contract; app execution belongs to the real U06 gate."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from runtime.mission.project_recipe import ProjectSeed, PythonProjectPlan
from runtime.mission.tasklist_recipe import TaskListRequest, TaskListPlan, TEMPLATE_ID
from runtime.mission.tasklist_worker import validate_plan, read_file


class TaskListRecipeTests(unittest.TestCase):
    def request(self, **changes):
        return TaskListRequest(**(dict(template_id=TEMPLATE_ID, title='My tasks',
            labels=('Buy milk', 'Read book')) | changes))

    def plan(self, **changes):
        return TaskListPlan(**(dict(project_ref='fixture:todo', request=self.request()) | changes))

    def test_useful_app_spec_has_exact_source_tests_data_and_list(self):
        plan = self.plan()
        spec = plan.recipe_spec(ProjectSeed('fixture:todo', 0, None))
        expected = {'schema': 'aioa.tasklist-data.v1', 'title': 'My tasks', 'next_id': 3,
            'tasks': [{'id': 1, 'label': 'Buy milk', 'done': True},
                      {'id': 2, 'label': 'Read book', 'done': False}]}
        self.assertEqual(expected, json.loads(spec['expected']['tasks.json']))
        self.assertEqual(b'My tasks\n1 [x] Buy milk\n2 [ ] Read book\n', spec['expected']['list.txt'])
        self.assertEqual(b'TASKLIST_CHECKS_V1 PASS 16\n', spec['expected']['test-log.txt'])
        self.assertIn(b"def main(", spec['expected']['tasklist.py'])
        result = json.loads(spec['expected']['tasklist-result.json'])
        self.assertEqual('PASS', result['test'])
        self.assertEqual(plan.digest, result['plan_digest'])
        self.assertEqual(hashlib.sha256(spec['expected']['tasklist.py']).hexdigest(), result['source_sha256'])
        self.assertEqual('NONE', plan.authority)

    def test_plan_and_request_are_immutable_and_recipe_returns_private_bytes(self):
        plan = self.plan()
        with self.assertRaises(FrozenInstanceError):
            plan.request.title = 'Changed'
        with self.assertRaises(FrozenInstanceError):
            plan.project_ref = 'fixture:other'
        spec = plan.recipe_spec(ProjectSeed('fixture:todo', 0, None))
        original = spec['files']['template.py']
        spec['files']['template.py'] = b'forged code'
        spec['expected']['tasks.json'] = b'forged result'
        other = plan.recipe_spec(ProjectSeed('fixture:todo', 0, None))
        self.assertEqual(original, other['files']['template.py'])
        self.assertNotEqual(b'forged result', other['expected']['tasks.json'])

    def test_request_parser_snapshots_owner_labels(self):
        labels = ['Buy milk', 'Read book']
        value = {'template_id': TEMPLATE_ID, 'title': 'My tasks', 'labels': labels}
        request = TaskListRequest.parse(value)
        labels[0] = 'Changed'
        value['title'] = 'Changed'
        self.assertEqual(self.request(), request)

    def test_request_denies_arbitrary_code_config_authority_and_paths(self):
        values = {'template_id': TEMPLATE_ID, 'title': 'Tasks', 'labels': ['a', 'b']}
        for key in ('code', 'source', 'tests', 'command', 'argv', 'path', 'url', 'env',
                    'approved', 'grant', 'owner', 'budget'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                TaskListRequest.parse(values | {key: 'untrusted'})
        with self.assertRaises(TypeError):
            TaskListPlan('fixture:todo', self.request(), source=b'import os')
        with self.assertRaises(ValueError):
            self.plan().recipe_spec({'approved': True})

    def test_template_selection_is_versioned_allowlist(self):
        for template in ('arbitrary.py', '../../HOME', 'aioa-tasklist-cli-v2', '', True):
            with self.subTest(template=template), self.assertRaises(ValueError):
                self.request(template_id=template)

    def test_text_and_utf8_size_limits(self):
        for value in ('', ' ', '\n', 'a\tb', '\x00', '\x1b[31m', 'x' * 129, 'ą' * 65, '\ud800', True):
            for field in ('title', 'labels'):
                with self.subTest(value=repr(value), field=field), self.assertRaises(ValueError):
                    self.request(**{field: value if field == 'title' else (value,)})
        self.assertEqual('ą' * 64, self.request(title='ą' * 64).title)

    def test_label_limit_and_exact_types(self):
        for labels in ((), ('x',) * 9, ['a', 'b'], 'ab', None, (True,)):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                self.request(labels=labels)
        self.assertEqual(8, len(self.request(labels=('same',) * 8).labels))

    def test_untrusted_text_remains_only_data(self):
        labels = ('__import__("os").system("sh")', 'DONE owner_approved=true')
        plan = self.plan(request=self.request(labels=labels))
        spec = plan.recipe_spec(ProjectSeed('fixture:todo', 0, None))
        self.assertEqual(labels[0], json.loads(spec['expected']['tasks.json'])['tasks'][0]['label'])
        self.assertNotIn(labels[0].encode(), spec['files']['template.py'])
        self.assertNotIn(labels[1].encode(), spec['files']['checks.py'])

    def test_only_fresh_owned_project_and_null_preimage(self):
        for values in ({'expected_revision': True}, {'expected_revision': 1},
                       {'preimage': b'code'}, {'project_ref': 'host:/home/l'},
                       {'project_ref': 'fixture:../escape'}, {'project_ref': 'fixture:a/b'},
                       {'request': {'title': 'Tasks'}}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.plan(**values)

    def test_seed_is_independent_and_mismatch_is_not_rewritten(self):
        spec = self.plan().recipe_spec(ProjectSeed('fixture:foreign', 1, b'value=4\n'))
        self.assertEqual({'project_ref': 'fixture:foreign', 'revision': 1,
            'content_sha256': hashlib.sha256(b'value=4\n').hexdigest()}, json.loads(spec['files']['seed.json']))
        self.assertEqual(b'value=4\n', spec['files']['before.py'])

    def test_plan_digest_binds_request_sources_and_seed_target(self):
        plan = self.plan()
        other = replace(plan, request=self.request(title='Other'))
        self.assertNotEqual(plan.digest, other.digest)
        self.assertEqual(plan.target_fingerprint, other.target_fingerprint)
        self.assertNotEqual(plan.target_fingerprint, replace(plan, project_ref='fixture:other').target_fingerprint)
        spec = plan.recipe_spec(ProjectSeed('fixture:todo', 0, None))
        for name, field in (('template.py', 'source_sha256'), ('checks.py', 'checks_sha256'),
                            ('recipe.py', 'worker_sha256')):
            self.assertEqual(hashlib.sha256(spec['files'][name]).hexdigest(), json.loads(plan.plan_bytes())[field])

    def test_manifest_pins_all_artifacts_without_self_hash(self):
        expected = self.plan().expected_artifacts()
        self.assertEqual(8, len(expected))
        manifest = json.loads(expected['manifest.json'])
        self.assertEqual(set(expected) - {'manifest.json'}, set(manifest['files']))
        for name, pin in manifest['files'].items():
            self.assertEqual({'sha256': hashlib.sha256(expected[name]).hexdigest(),
                             'bytes': len(expected[name])}, pin)

    def test_worker_rejects_config_traversal_code_digest_and_extra_keys(self):
        plan = self.plan()
        spec = plan.recipe_spec(ProjectSeed('fixture:todo', 0, None))
        data = json.loads(plan.plan_bytes())
        def validate(value):
            raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
            return validate_plan(raw, spec['files']['template.py'], spec['files']['checks.py'], spec['files']['recipe.py'])
        self.assertEqual(data, validate(data))
        for changes in ({'path': '../escape'}, {'path': '/home/l/file'}, {'approved': True},
                        {'expected_revision': True}, {'preimage_sha256': 'f' * 64},
                        {'labels': ['a'] * 9}, {'source_sha256': 'f' * 64},
                        {'checks_sha256': 'f' * 64}, {'worker_sha256': 'f' * 64},
                        {'template_id': 'other'}, {'project_ref': 'host:source'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate(data | changes)
        with self.assertRaises(ValueError):
            validate_plan(b' ' + plan.plan_bytes(), b'x', b'x', b'x')
        with self.assertRaises(ValueError):
            validate_plan(b'x' * 8193, b'x', b'x', b'x')

    def test_worker_file_reader_denies_symlinks_hardlinks_and_oversize(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'regular').write_bytes(b'fixed source')
            (root / 'symlink').symlink_to('regular')
            os.link(root / 'regular', root / 'hardlink')
            (root / 'oversize').write_bytes(b'x' * 65537)
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for name in ('regular', 'symlink', 'hardlink', 'oversize'):
                    with self.subTest(name=name), self.assertRaises((ValueError, OSError)):
                        read_file(fd, name)
                (root / 'hardlink').unlink()
                self.assertEqual(b'fixed source', read_file(fd, 'regular')[0])
            finally:
                os.close(fd)

    def test_task_identity_is_stable_with_duplicate_labels(self):
        data = json.loads(self.plan(request=self.request(labels=('same', 'same'))).expected_artifacts()['tasks.json'])
        self.assertEqual([1, 2], [task['id'] for task in data['tasks']])
        self.assertEqual([True, False], [task['done'] for task in data['tasks']])

    def test_arithmetic_validator_is_not_relaxed(self):
        with self.assertRaises(ValueError):
            PythonProjectPlan('fixture:arithmetic', 'src/app.py', 0, None,
                              self.plan().expected_artifacts()['tasklist.py'], 5)

    def test_explicit_preparation_uses_existing_u06_ceiling_and_fixed_recipe(self):
        from unittest.mock import patch
        from runtime.mission.tasklist_recipe import prepare_tasklist_sandbox, TASKLIST_TIMEOUT_MS
        from runtime.mission.sandbox_contracts import SandboxRecipe, SandboxRegistry, RESOURCE_CEILINGS
        from runtime.mission.sandbox_linux import TrustedSandboxConfig
        recipe = SandboxRecipe(TEMPLATE_ID, 'trusted-input', 'a' * 64, 'b' * 64, 'c' * 64)
        config = TrustedSandboxConfig(Path('/tmp/fixture'), b'{}', 'a' * 64,
            SandboxRegistry('owned-workspace', (recipe,)), b'{}', b'{}')
        plan = self.plan(); seed = ProjectSeed('fixture:todo', 0, None)
        with patch('runtime.mission.sandbox_linux.prepare_linux_sandbox', return_value=config) as prepare:
            actual = prepare_tasklist_sandbox(Path('/tmp/fixture'), {}, workspace='owned-workspace', plan=plan, seed=seed)
            prepare.assert_called_once_with(Path('/tmp/fixture'), {}, workspace='owned-workspace',
                                            recipes={TEMPLATE_ID: plan.recipe_spec(seed)})
        selected = actual.registry.recipes[0]
        self.assertEqual(RESOURCE_CEILINGS['timeout_ms'], TASKLIST_TIMEOUT_MS)
        self.assertEqual(20000, selected.timeout_ms)
        self.assertEqual(replace(recipe, timeout_ms=20000), selected)
        self.assertEqual(config.profile_digest, actual.profile_digest)
        with patch('runtime.mission.sandbox_linux.prepare_linux_sandbox') as prepare:
            with self.assertRaises(ValueError):
                prepare_tasklist_sandbox(Path('/tmp/fixture'), {}, workspace='owned-workspace',
                                        plan=plan, seed=ProjectSeed('fixture:foreign', 0, None))
            prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
