"""Profile-specific input bounds; inert compiler fixtures never execute code."""
import hashlib
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.mission import sandbox_linux as linux
from runtime.mission.sandbox_contracts import SandboxOperation

PROFILE = 'PYTEST_WHEELS_V1'


class PytestInputProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'inert-system-runtime'
        raw = b'INERT_BYTES_NEVER_EXECUTED\n'
        self.runtime.write_bytes(raw)
        self.runtime.chmod(0o400)
        self.entry = {'snapshot': str(self.runtime), 'bytes': len(raw),
                      'sha256': hashlib.sha256(raw).hexdigest()}
        self.number = 0

    def compiler(self, argv, **kwargs):
        self.assertEqual('/usr/bin/cc', argv[0])
        destination = Path(argv[argv.index('-o') + 1])
        self.assertTrue(destination.is_relative_to(self.root))
        destination.write_bytes(b'INERT_COMPILER_RESULT\n')
        return SimpleNamespace(returncode=0)

    def prepare(self, *, files=None, selected=None, renderer=None):
        options = {}
        if selected is not None:
            self.assertIn('input_profile', inspect.signature(linux.prepare_linux_sandbox).parameters,
                          'VERSIONED_INPUT_PROFILE_NOT_IMPLEMENTED')
            options['input_profile'] = selected
        root = self.root / ('config-' + str(self.number))
        self.number += 1
        recipes = {'recipe:closed-inputs': {
            'files': files or {'recipe.py': b'# trusted inert recipe\n'},
            'expected': {'finished.txt': b'complete\n'}}}
        with patch.object(linux.subprocess, 'run', side_effect=self.compiler), \
                patch.object(linux.subprocess, 'Popen', side_effect=AssertionError('NO_EXECUTION_IN_DATA_TEST')):
            return linux.prepare_linux_sandbox(root, {'/usr/bin/python3.12': self.entry},
                                               workspace='workspace', recipes=recipes,
                                               resource_profile=renderer, **options)

    def files(self, count, size=1):
        return {'recipe.py': b'# trusted inert recipe\n',
                **{'data_' + str(i) + '.bin': b'x' * size for i in range(count - 1)}}

    def operation(self, config):
        return {'operation_class': 'SANDBOX_EXEC', 'target_fingerprint': 'sha256:' + '0' * 64,
                'expected_target_revision': 'recipe-v1',
                'payload': config.registry.recipes[0].payload('workspace', 'task', 'step')}

    def test_default_profile_retains_its_old_filter_and_resource_contract(self):
        config = self.prepare()
        self.assertNotIn('input_profile', config.profile())
        self.assertNotIn('input_profile', self.operation(config)['payload'])
        self.assertEqual(16, config.profile()['resources']['pids_max'])
        self.assertEqual(536870912, config.profile()['resources']['memory_bytes'])
        self.assertEqual('9a3611e0becc74bd45f3ccb7b8b35eb19bb61f56307128049db0ee0156dadb36',
                         hashlib.sha256((config.root / 'final_filter.bpf').read_bytes()).hexdigest())

    def test_default_count_sixteen_remains_accepted_and_seventeen_denied(self):
        self.prepare(files=self.files(16))
        with self.assertRaisesRegex(ValueError, '^INVALID_TRUSTED_RECIPE$'):
            self.prepare(files=self.files(17))

    def test_default_one_mib_remains_a_per_input_limit(self):
        self.prepare(files={'recipe.py': b'x' * 1048576})
        with self.assertRaisesRegex(ValueError, '^INVALID_TRUSTED_INPUT$'):
            self.prepare(files={'recipe.py': b'x' * 1048577})

    def test_named_profile_accepts_exactly_twenty_four_and_two_mib(self):
        files = self.files(24)
        files['data_0.bin'] = b'x' * 2097152
        config = self.prepare(selected=PROFILE, files=files)
        entry = config.inputs()['recipe:closed-inputs']
        self.assertEqual(24, len(entry['files']))
        self.assertEqual(2097152, Path(entry['files']['data_0.bin']).stat().st_size)

    def test_named_profile_refuses_the_twenty_fifth_input(self):
        with self.assertRaisesRegex(ValueError, '^INVALID_TRUSTED_RECIPE$'):
            self.prepare(selected=PROFILE, files=self.files(25))

    def test_named_profile_refuses_two_mib_plus_one(self):
        with self.assertRaisesRegex(ValueError, '^INVALID_TRUSTED_INPUT$'):
            self.prepare(selected=PROFILE, files={'recipe.py': b'x' * 2097153})

    def test_named_profile_binds_a_finite_eight_mib_sum(self):
        with self.assertRaisesRegex(ValueError, '^TRUSTED_INPUT_SUM_BOUND$'):
            self.prepare(selected=PROFILE, files=self.files(6, 2097152))

    def test_profile_is_bound_to_operation_config_and_existing_resource_caps(self):
        config = self.prepare(selected=PROFILE)
        self.assertEqual(PROFILE, config.profile()['input_profile'])
        self.assertEqual({'files': 24, 'per_file_bytes': 2097152, 'total_bytes': 8388608},
                         config.profile()['input_limits'])
        self.assertEqual(PROFILE, self.operation(config)['payload']['input_profile'])
        self.assertNotIn('resource_profile', config.profile())
        self.assertEqual(16, config.profile()['resources']['pids_max'])
        self.assertEqual(linux.build_filter(final=True), (config.root / 'final_filter.bpf').read_bytes())
        config.registry.validate(self.operation(config))

    def test_input_profile_cannot_borrow_renderer_resources_or_ipc(self):
        with self.assertRaisesRegex(ValueError, '^INCOMPATIBLE_SANDBOX_INPUT_PROFILE$'):
            self.prepare(selected=PROFILE, renderer='HEADLESS_RENDER_V1')
        self.assertFalse((self.root / 'config-0').exists())

    def test_unknown_and_model_chosen_ceilings_refuse_before_any_config_directory(self):
        for value in ('', 'UNLIMITED', True, {'files': 1000}):
            with self.subTest(value=value), \
                    self.assertRaisesRegex(ValueError, '^INVALID_SANDBOX_INPUT_PROFILE$'):
                self.prepare(selected=value)
        self.assertFalse(any(self.root.glob('config-*')))

    def test_host_configuration_roundtrip_preserves_the_exact_profile(self):
        config = self.prepare(selected=PROFILE)
        linux.save_host_config(config)
        restored = linux.load_host_config(config.root, trusted_root=self.root)
        self.assertEqual(config, restored)
        self.assertEqual(PROFILE, restored.registry.recipes[0].input_profile)

    def test_registry_refuses_profile_downgrade_and_unknown_or_renderer_mix(self):
        config = self.prepare(selected=PROFILE)
        operation = self.operation(config)
        operation['payload'].pop('input_profile')
        with self.assertRaisesRegex(ValueError, '^SANDBOX_REGISTRY_BINDING$'):
            config.registry.validate(operation)
        operation = self.operation(config)
        operation['payload']['input_profile'] = 'UNKNOWN'
        with self.assertRaisesRegex(ValueError, '^INVALID_SANDBOX_INPUT_PROFILE$'):
            SandboxOperation.parse(operation)
        operation = self.operation(config)
        operation['payload']['resource_profile'] = 'HEADLESS_RENDER_V1'
        with self.assertRaises(ValueError):
            SandboxOperation.parse(operation)


    def request(self, config):
        from runtime.mission.sandbox_contracts import SandboxDispatchRequest
        operation = SandboxOperation.parse(self.operation(config))
        return SandboxDispatchRequest(
            operation.operation_bytes, operation.digest, 'task', 'step', 'session',
            '1' * 64, 1, 'sha256:' + '2' * 64, 'sha256:' + '3' * 64,
            '4' * 64, '5' * 64, 'nonce')

    def assert_predispatch_denied(self, config, profile, reason):
        from dataclasses import replace
        changed = replace(config, profile_bytes=linux.canonical_json_bytes(profile),
                          profile_digest=linux.canonical_sha256(profile))
        broker = linux.LinuxSandboxBroker(changed)
        with patch.object(linux.subprocess, 'Popen', side_effect=AssertionError('NO_SPAWN')), \
                self.assertRaisesRegex(ValueError, '^' + reason + '$'):
            broker.dispatch(self.request(config), lambda: self.fail('NO_RELEASE_CALLBACK'))

    def test_broker_refuses_operation_and_config_profile_mismatch_before_any_release(self):
        config = self.prepare(selected=PROFILE)
        profile = config.profile()
        profile.pop('input_profile')
        profile.pop('input_limits')
        self.assert_predispatch_denied(config, profile, 'PINNED_INPUT_PROFILE_MISMATCH')

    def test_broker_refuses_mutated_input_limits_before_any_release(self):
        config = self.prepare(selected=PROFILE)
        profile = config.profile()
        profile['input_limits']['total_bytes'] += 1
        self.assert_predispatch_denied(config, profile, 'PINNED_INPUT_LIMITS_MISMATCH')


    def test_exact_eight_mib_is_accepted_and_one_additional_byte_refused(self):
        recipe = b'# inert recipe\n'
        files = {'recipe.py': recipe, 'one.bin': b'x' * 2097152,
                 'two.bin': b'x' * 2097152, 'three.bin': b'x' * 2097152,
                 'four.bin': b'x' * (2097152 - len(recipe))}
        self.assertEqual(8388608, sum(map(len, files.values())))
        config = self.prepare(selected=PROFILE, files=files)
        self.assertEqual(5, len(config.inputs()['recipe:closed-inputs']['files']))
        files['four.bin'] += b'x'
        with self.assertRaisesRegex(ValueError, '^TRUSTED_INPUT_SUM_BOUND$'):
            self.prepare(selected=PROFILE, files=files)


    def host_pin_fixture(self):
        import nz11_kernel_acceptance as kernel
        fixture = kernel.fixture_core()
        self.addCleanup(fixture.doCleanups)
        spec = {'files': {'recipe.py': b'# inert, never executed\n',
                          'large.bin': b'x' * 2097152},
                'expected': {'finished.txt': b'complete\n'}}
        preparer = kernel.SandboxPreparer(fixture, {'/usr/bin/python3.12': self.entry},
            self.root / ('host-pin-' + str(self.number)), input_profile=PROFILE)
        self.number += 1
        with patch.object(linux.subprocess, 'run', side_effect=self.compiler), \
                patch.object(linux.subprocess, 'Popen', side_effect=AssertionError('NO_EXECUTION_IN_DATA_TEST')):
            step = preparer.steps((('FAST_TESTS', spec),))[0]
        return fixture.fx.journal, step, spec

    def test_actual_host_pin_accepts_two_mib_without_dispatch_or_widening_default_read(self):
        from runtime.mission.repair_validation import _pin_prepared_spec
        journal, step, spec = self.host_pin_fixture()
        path = Path(step.route.executor.config.inputs()['0']['files']['large.bin'])
        with self.assertRaisesRegex(ValueError, '^READBACK_FILE_TYPE_DENIED$'):
            linux.read_evidence_file(path.parent, path.name)
        with patch.object(linux.subprocess, 'Popen', side_effect=AssertionError('NO_DISPATCH')):
            _pin_prepared_spec(journal, step, spec)
        self.assertEqual(2097152, path.stat().st_size)

    def test_actual_host_pin_rejects_same_size_input_tampering(self):
        from runtime.mission.repair_validation import _pin_prepared_spec
        journal, step, spec = self.host_pin_fixture()
        path = Path(step.route.executor.config.inputs()['0']['files']['large.bin'])
        path.chmod(0o600)
        path.write_bytes(b'y' * 2097152)
        path.chmod(0o400)
        with self.assertRaisesRegex(ValueError, '^VALIDATION_INPUT_CHANGED$'), \
                patch.object(linux.subprocess, 'Popen', side_effect=AssertionError('NO_DISPATCH')):
            _pin_prepared_spec(journal, step, spec)

    def test_actual_host_pin_rejects_symlink_and_hardlink_substitution(self):
        import os

        from runtime.mission.repair_validation import _pin_prepared_spec
        for kind in ('symlink', 'hardlink'):
            with self.subTest(kind=kind):
                journal, step, spec = self.host_pin_fixture()
                path = Path(step.route.executor.config.inputs()['0']['files']['large.bin'])
                foreign = self.root / ('foreign-' + kind + '.bin')
                foreign.write_bytes(spec['files']['large.bin'])
                path.unlink()
                if kind == 'symlink':
                    path.symlink_to(foreign)
                else:
                    os.link(foreign, path)
                with self.assertRaises((OSError, ValueError)), \
                        patch.object(linux.subprocess, 'Popen', side_effect=AssertionError('NO_DISPATCH')):
                    _pin_prepared_spec(journal, step, spec)
