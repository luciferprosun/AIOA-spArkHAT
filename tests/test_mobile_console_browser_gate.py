"""Browser invocation contract; these tests launch no browser or namespace."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_mobile_device_console as console


class BrowserGateTests(unittest.TestCase):
    def gate(self):
        path=Path(__file__).with_name('mobile_device_console_browser.py')
        self.assertTrue(path.is_file(),'checked-in isolated browser gate missing')
        spec=importlib.util.spec_from_file_location('mobile_console_gate',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_default_console_discovery_never_includes_browser_execution(self):
        suite=unittest.defaultTestLoader.loadTestsFromModule(console)
        ids=[case.id() for group in suite for case in group]
        self.assertFalse(any('chrome_private_launcher' in name for name in ids),ids)

    def test_explicit_gate_retains_existing_containment_and_exact_fixture_mounts(self):
        gate=self.gate()
        with tempfile.TemporaryDirectory() as output:
            command=gate.browser_command(output,'1'*40)
        for flag in ('--unshare-all','--clearenv','--cap-drop','--die-with-parent'):
            self.assertIn(flag,command)
        self.assertNotIn('--share-net',command)
        self.assertNotIn('--no-sandbox',command)
        mounts=[(command[n+1],command[n+2]) for n,x in enumerate(command) if x=='--ro-bind']
        self.assertNotIn((str(gate.ROOT),'/app'),mounts)
        self.assertFalse(any(host==str(Path.home()) or '/.codex' in host or '/.git' in host for host,_ in mounts))
        expected={str(gate.ROOT/'tests'/name) for name in (
            'test_mobile_device_console.py','test_mobile_pairing.py','mobile_device_console_browser.py')}
        self.assertEqual(expected,{host for host,_ in mounts if host.startswith(str(gate.ROOT/'tests')+'/')
            and not host.endswith('meta_p03_ui_probe.js')})
        self.assertEqual(['/usr/bin/python3','-B','/app/tests/mobile_device_console_browser.py','--worker'],
            command[command.index('--')+1:])

    def test_uncontained_direct_worker_is_denied_before_browser_or_fixture(self):
        gate=self.gate()
        with patch.dict('os.environ',{},clear=True),patch.object(gate,'run_bounded') as launch:
            with self.assertRaisesRegex(RuntimeError,'ISOLATION_REQUIRED'):gate.verify_isolation()
        launch.assert_not_called()

    def test_required_prerequisite_failure_never_becomes_skip_or_browser_launch(self):
        gate=self.gate()
        for missing in ('/usr/bin/bwrap','/usr/bin/python3','/opt/google/chrome/chrome'):
            with self.subTest(missing=missing),patch.object(gate.os,'access',side_effect=lambda name,_:name!=missing),\
                    patch.object(gate,'run_bounded') as launch:
                with self.assertRaisesRegex(RuntimeError,'PREREQUISITE_REQUIRED: '+missing):gate.require_prerequisites()
            launch.assert_not_called()


    def test_startup_counters_do_not_read_command_or_environment(self):
        import io
        from types import SimpleNamespace
        gate=self.gate();opened=[]
        payload={'stat':'42 (chrome) S 1 2 3 0 0 0 11 0 2 0 13 7 0 0 20 0 4 0 12345 0 0',
                 'schedstat':'111 222 3\n','wchan':'futex_wait_queue\n'}
        def read_only(path,*args,**kwargs):
            opened.append(str(path));return io.StringIO(payload[path.name])
        with patch.object(gate.Path,'open',read_only):
            result=gate.startup_process_state(SimpleNamespace(pid=42,poll=lambda:None))
        self.assertEqual({'state':'S','minor_faults':11,'major_faults':2,'user_ticks':13,
                          'system_ticks':7,'schedstat':[111,222,3],'wchan':'futex_wait_queue'},result)
        self.assertEqual(['/proc/42/stat','/proc/42/schedstat','/proc/42/wchan'],opened)

    def test_failed_startup_counters_never_mask_original_failure(self):
        from types import SimpleNamespace
        gate=self.gate()
        with patch.object(gate.Path,'open',side_effect=PermissionError()):
            self.assertEqual({'state':'UNAVAILABLE','schedstat':'UNAVAILABLE','wchan':'UNAVAILABLE'},
                             gate.startup_process_state(SimpleNamespace(pid=42,poll=lambda:None)))

    def test_exited_owned_browser_does_not_inspect_a_reused_pid(self):
        from types import SimpleNamespace
        gate=self.gate()
        with patch.object(gate.Path,'open') as opened:
            self.assertEqual({'state':'EXITED','returncode':-9},
                             gate.startup_process_state(SimpleNamespace(pid=42,poll=lambda:-9)))
        opened.assert_not_called()


if __name__=='__main__':unittest.main()
