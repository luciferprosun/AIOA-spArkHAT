"""Isolated owned-process lifecycle; no Chrome/network/real owner started."""
import io,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from runtime.mobile_gateway import chrome_console

class ChromeLifecycleTests(unittest.TestCase):
    def test_launcher_timeout_reaps_only_its_own_helper(self):
        class Process:
            pid=123456789
            stdin=io.BytesIO();stdout=io.BytesIO()
            def __init__(self):self.stopped=False;self.waits=[]
            def poll(self):return None if not self.stopped else -15
            def terminate(self):self.stopped=True
            def wait(self,timeout=None):self.waits.append(timeout);return -15
        child=Process()
        with tempfile.TemporaryDirectory() as directory,patch('subprocess.Popen',return_value=child),patch('select.select',return_value=([],[],[])):
            with self.assertRaises(ValueError):chrome_console.launch({'url':'https://host.example.org/devices','delivery':'A'*43},Path(directory))
        self.assertTrue(child.stopped)
        self.assertTrue(child.waits);self.assertTrue(all(t is not None and t<=5 for t in child.waits))

    def test_failed_browser_bootstrap_has_bounded_cleanup_without_redelivery(self):
        class Process:
            def __init__(self):self.stopped=False;self.waits=[]
            def poll(self):return None if not self.stopped else -15
            def terminate(self):self.stopped=True
            def wait(self,timeout=None):self.waits.append(timeout);return -15
            def kill(self):self.stopped=True
        process=Process()
        with tempfile.TemporaryDirectory() as directory,patch.object(Path,'home',return_value=Path(directory)),patch('subprocess.Popen',return_value=process) as popen,patch.object(chrome_console.Pipe,'call',side_effect=ValueError('CDP_STALLED')) as cdp:
            with self.assertRaises(ValueError):chrome_console.run({'url':'https://host.example.org/devices','delivery':'A'*43})
            self.assertEqual(1,popen.call_count)
            self.assertEqual(1,cdp.call_count) # No fetch/delivery and no retry.
            self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertTrue(process.stopped)
        self.assertEqual([2],process.waits)

if __name__=='__main__':unittest.main()
