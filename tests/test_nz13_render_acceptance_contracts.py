"""Pure harness contracts; no sandbox, browser, service or host PID is started."""
import importlib.machinery
import importlib.util
import inspect
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

READY = b'CHROME_FILE_NAVIGATION_ACK\n'


class RenderAcceptanceContractTests(unittest.TestCase):
    def api(self):
        name = 'nz13_render_acceptance'
        tests = Path(__file__).resolve().parent
        expected = str(tests / (name + '.py'))
        if name not in sys.modules:
            spec = importlib.machinery.PathFinder.find_spec(name, [str(tests)])
            self.assertIsNotNone(spec, 'Missing source-bound real render acceptance')
            self.assertEqual(expected, spec.origin, 'Foreign render acceptance helper')
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            loaded = False
            try:
                spec.loader.exec_module(module)
                loaded = True
            finally:
                if not loaded and sys.modules.get(name) is module:
                    del sys.modules[name]
        module = sys.modules[name]
        self.assertEqual(expected, getattr(module, '__file__', None), 'Foreign render acceptance helper')
        return module

    def test_helper_origin_is_pinned_and_failed_loading_restores_the_cache(self):
        name = 'nz13_render_acceptance'
        expected = Path(__file__).resolve().with_name(name + '.py')
        original = sys.modules.get(name)
        with self.subTest('foreign cached helper'), patch.dict(sys.modules):
            sys.modules[name] = SimpleNamespace(__file__=str(expected.with_name('foreign.py')))
            with self.assertRaisesRegex(AssertionError, 'Foreign render acceptance helper'):
                self.api()
        self.assertIs(original, sys.modules.get(name))

        with self.subTest('foreign loader never executes'), patch.dict(sys.modules):
            sys.modules.pop(name, None)
            loader = SimpleNamespace(create_module=lambda _spec: None, exec_module=Mock())
            spec = importlib.machinery.ModuleSpec(name, loader, origin=str(expected.with_name('foreign.py')))
            spec.has_location = True
            with patch.object(importlib.machinery.PathFinder, 'find_spec', return_value=spec), \
                    self.assertRaisesRegex(AssertionError, 'Foreign render acceptance helper'):
                self.api()
            loader.exec_module.assert_not_called()
        self.assertIs(original, sys.modules.get(name))

        with self.subTest('failed exact loader leaves no partial cache'), patch.dict(sys.modules):
            sys.modules.pop(name, None)
            loader = SimpleNamespace(create_module=lambda _spec: None,
                                     exec_module=Mock(side_effect=RuntimeError('fixed loader failure')))
            spec = importlib.machinery.ModuleSpec(name, loader, origin=str(expected))
            spec.has_location = True
            with patch.object(importlib.machinery.PathFinder, 'find_spec', return_value=spec), \
                    self.assertRaisesRegex(RuntimeError, 'fixed loader failure'):
                self.api()
            self.assertFalse(name in sys.modules, 'Failed loader kept a partial helper module')
        self.assertIs(original, sys.modules.get(name))

    def test_stopped_unknown_requires_cleanup_and_must_not_require_a_successful_readback(self):
        api = self.api()
        self.assertIn('require_readback', inspect.signature(api.receipt).parameters)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'run-fixture'
            run.mkdir(mode=0o700)
            value = {'warrant_digest': 'sha256:' + 'a' * 64, 'status': 'UNKNOWN',
                     'project_code_started': True, 'cgroup_absent_after_cleanup': True,
                     'unit_terminal_observed': True, 'cgroup_populated_zero_directly_observed': False}
            receipt = run / 'receipt.json'
            receipt.write_text(json.dumps(value))
            receipt.chmod(0o400)
            warrant = SimpleNamespace(digest=lambda: value['warrant_digest'])
            step = SimpleNamespace(arguments={'warrant': warrant},
                                   route=SimpleNamespace(executor=SimpleNamespace(config=SimpleNamespace(root=root))))
            result = api.receipt(step, require_readback=False)
            self.assertEqual('UNKNOWN', result['status'])
            self.assertTrue(result['cleaned'])
            self.assertFalse(result['direct_zero_readback_observed'])
            with self.assertRaises(AssertionError):
                api.receipt(step)

    def test_worker_host_ack_without_actual_chrome_navigation_does_not_open_the_stop_barrier(self):
        api = self.api()
        cls = getattr(api, 'RenderReadyObservation', None)
        self.assertTrue(callable(cls), 'ACK-only barrier cannot prove active Chrome')
        active = threading.Event()
        order = []

        def original(*_, **__):
            order.append('keeper_ready')
            return {'stage': 'WORK_READY', 'work_cgroup': '/fixture/never-read'}

        def not_ready(_):
            order.append('chrome_not_observed')
            raise ValueError('RENDER_READY_NOT_OBSERVED')

        observer = cls(original, active, probe=not_ready)
        observer(None)
        self.assertFalse(active.is_set())
        with self.assertRaisesRegex(ValueError, 'RENDER_READY_NOT_OBSERVED'):
            observer(None, 24)
        self.assertFalse(active.is_set())
        self.assertEqual(['keeper_ready', 'chrome_not_observed'], order)

    def test_active_barrier_requires_a_real_readiness_witness_before_the_terminal_wait(self):
        api = self.api()
        cls = getattr(api, 'RenderReadyObservation', None)
        self.assertTrue(callable(cls))
        active = threading.Event()
        order = []
        import hashlib
        witness = {'schema': 'aioa.render-navigation-witness.v1', 'pid': 123,
                   'marker_sha256': hashlib.sha256(READY).hexdigest()}

        def original(_stream, *args, **kwargs):
            if not args:
                return {'stage': 'WORK_READY', 'work_cgroup': '/fixture/never-read'}
            self.assertTrue(active.is_set())
            order.append('terminal_wait')
            raise ValueError('SANDBOX_CANCELLED')

        def probe(_):
            self.assertFalse(active.is_set())
            order.append('actual_navigation_witness')
            return witness

        observer = cls(original, active, probe=probe)
        observer(None)
        with self.assertRaisesRegex(ValueError, 'SANDBOX_CANCELLED'):
            observer(None, 24)
        self.assertEqual(witness, observer.witness)
        self.assertEqual(['actual_navigation_witness', 'terminal_wait'], order)

    def test_readiness_observer_rejects_non_job_cgroup_paths_before_host_process_inspection(self):
        api = self.api()
        method = getattr(api, 'wait_for_chrome_ready', None)
        self.assertTrue(callable(method))
        for path in ('/sys/fs/cgroup', '/proc', '/home/l', '../work', '/fixture/never-read', None):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'RENDER_CGROUP_WITNESS_REQUIRED'):
                method(path)

    def test_a_valid_job_path_passes_scope_check_but_missing_chrome_never_becomes_ready(self):
        api = self.api()
        method = getattr(api, 'wait_for_chrome_ready', None)
        self.assertTrue(callable(method))
        uid = str(os.getuid())
        path = '/sys/fs/cgroup/user.slice/user-' + uid + '.slice/user@' + uid + '.service/app.slice/aioa-sandbox-' + 'a' * 32 + '.service/work'
        with patch('builtins.open', return_value=io.StringIO('')) as opened, \
                patch.object(api.time, 'monotonic', side_effect=(0, .1, 11)), \
                patch.object(api.time, 'sleep'), \
                self.assertRaisesRegex(ValueError, 'RENDER_READY_NOT_OBSERVED'):
            method(path)
        opened.assert_called_once_with(path + '/cgroup.procs')
