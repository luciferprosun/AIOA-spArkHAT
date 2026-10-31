"""Process/namespace constraints, no website or actual Chrome in unit tests."""
import importlib
import importlib.util
import os
import signal
import subprocess
import time
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from runtime.providers.exact import CancellationToken


class ChromeProcessTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.browser_agent.chrome_process_read'),
                             'networkless Chrome process adapter missing')
        self.api=importlib.import_module('runtime.browser_agent.chrome_process_read')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)

    def test_public_navigation_never_launches_without_egress_and_domain_authority(self):
        driver=self.api.NetworklessChromeReadDriver()
        with patch.object(self.api.subprocess,'Popen') as launch:
            for url in ['https://docs.example.org','http://127.0.0.1','file:///etc/passwd',
                        'https://169.254.169.254','https://xn--example.com']:
                with self.subTest(url=url),self.assertRaisesRegex(ValueError,'CHROME_LIVE_BLOCKED_CONTAINMENT'):
                    driver.navigate_read(url)
        self.assertEqual(0,launch.call_count)
        self.assertFalse(any(hasattr(driver,n) for n in ('click','type','execute','upload','attach')))

    def test_namespace_command_excludes_personal_home_credentials_and_network(self):
        command=self.api.sandbox_command(Path(self.tmp.name),390,844,'1'*40)
        self.assertIn('--unshare-all',command)
        self.assertIn('--clearenv',command)
        self.assertIn('--cap-drop',command)
        self.assertNotIn('--no-sandbox',command)
        self.assertNotIn('--share-net',command)
        self.assertNotIn('--ro-bind / /',' '.join(command))
        self.assertFalse(any('/.config/' in s or '/.codex' in s or 'DevToolsActivePort' in s for s in command))
        self.assertNotIn('/home/l',command)

    def test_cancelled_operation_has_zero_child_launches(self):
        cancel=CancellationToken();cancel.cancel()
        with patch.object(self.api.subprocess,'Popen') as child:
            with self.assertRaisesRegex(ValueError,'STOPPED'):
                self.api.run_bounded(['/usr/bin/python3','-c','print(1)'],cancel,1)
        self.assertEqual(0,child.call_count)

    def test_owned_child_stdout_limit_stops_child_and_returns_unknown(self):
        with self.assertRaisesRegex(ValueError,'OUTPUT_LIMIT_UNKNOWN'):
            self.api.run_bounded(['/usr/bin/python3','-c','print("x"*100000)'],CancellationToken(),1,max_bytes=1024)

    def test_owned_child_timeout_and_stop_are_bounded(self):
        with self.assertRaisesRegex(ValueError,'TIMEOUT_UNKNOWN'):
            self.api.run_bounded(['/usr/bin/python3','-c','import time;time.sleep(5)'],CancellationToken(),.05)
        cancel=CancellationToken();timer=threading.Timer(.03,cancel.cancel);timer.start()
        self.addCleanup(timer.cancel)
        with self.assertRaisesRegex(ValueError,'STOPPED'):
            self.api.run_bounded(['/usr/bin/python3','-c','import time;time.sleep(5)'],cancel,1)

    def test_successful_owned_child_is_reaped_and_only_bounded_bytes_return(self):
        status,out,err=self.api.run_bounded(['/usr/bin/python3','-c','print("fixture")'],CancellationToken(),1)
        self.assertEqual((0,b'fixture\n',b''),(status,out,err))

    def test_output_directory_symlink_is_denied_before_mount_or_browser(self):
        link=Path(self.tmp.name)/'link';link.symlink_to(Path(self.tmp.name),target_is_directory=True)
        with self.assertRaises(ValueError):self.api.sandbox_command(link,390,844,'1'*40)

    def test_new_receipt_code_is_bound_into_source_capsule(self):
        from runtime.meta_hackathon.runtime_adapter import current_source
        before=current_source()[1];original=Path.read_bytes
        def changed(p):
            value=original(p)
            return value+b'\n# simulated drift\n' if str(p).endswith('/providers/meta_receipts.py') else value
        with patch.object(Path,'read_bytes',changed):after=current_source()[1]
        self.assertNotEqual(before,after,'new receipt verifier is outside source capsule')

    def test_review_r5_spend_stop_and_warrant_dependencies_are_in_capsule(self):
        from runtime.meta_hackathon.runtime_adapter import current_source
        before=current_source()[1];original=Path.read_bytes
        for suffix in ('/mission/governor.py','/providers/exact.py','/archaioa/warrant.py',
                       '/memory_patch/persistence/ports.py'):
            def changed(p):
                value=original(p)
                return value+b'\n# simulated authority drift\n' if str(p).endswith(suffix) else value
            with self.subTest(suffix=suffix),patch.object(Path,'read_bytes',changed):
                self.assertNotEqual(before,current_source()[1])

    def test_review_r4_stop_after_pipe_eof_is_prompt(self):
        cancel=CancellationToken();timer=threading.Timer(.07,cancel.cancel);timer.start();self.addCleanup(timer.cancel)
        started=time.monotonic()
        with self.assertRaisesRegex(ValueError,'STOPPED'):
            self.api.run_bounded(['/usr/bin/python3','-c','import os,time;os.close(1);os.close(2);time.sleep(2)'],cancel,1)
        self.assertLess(time.monotonic()-started,.5)

    def test_review_r4_exited_leader_does_not_leave_pipe_holding_child(self):
        pid_file=Path(self.tmp.name)/'child.pid';owned=[];original=subprocess.Popen
        def track(*args,**kwargs):
            child=original(*args,**kwargs);owned.append(child);return child
        def cleanup():
            if not pid_file.exists():return
            pid=int(pid_file.read_text())
            try:
                if owned and os.getpgid(pid)==owned[0].pid:os.killpg(owned[0].pid,signal.SIGKILL)
            except ProcessLookupError:pass
        self.addCleanup(cleanup)
        script='import os,time,pathlib;pid=os.fork();\nif pid:os._exit(0)\npathlib.Path('+repr(str(pid_file))+').write_text(str(os.getpid()));time.sleep(3)'
        cancel=CancellationToken();timer=threading.Timer(.15,cancel.cancel);timer.start();self.addCleanup(timer.cancel)
        with patch.object(self.api.subprocess,'Popen',side_effect=track):
            with self.assertRaisesRegex(ValueError,'STOPPED'):
                self.api.run_bounded(['/usr/bin/python3','-c',script],cancel,1)
        self.assertTrue(pid_file.exists())
        pid=int(pid_file.read_text())
        for _ in range(50):
            p=Path('/proc')/str(pid)/'stat'
            if not p.exists() or p.read_text().split()[2]=='Z':break
            time.sleep(.01)
        else:self.fail('owned descendant remains running after STOP')


if __name__=='__main__':unittest.main()
