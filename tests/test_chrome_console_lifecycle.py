"""Isolated owned-process lifecycle; no Chrome/network/real owner started."""
import io,json,stat,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from runtime.mobile_gateway import chrome_console

class ChromeLifecycleTests(unittest.TestCase):
    def test_about_blank_complete_cannot_receive_owner_delivery(self):
        from unittest.mock import Mock
        url='https://host.example.org/devices'
        pipe=Mock()
        pipe.call.side_effect=[
            {'result':{'value':{'href':'about:blank','origin':'null','state':'complete','secure':False}}},
            {'result':{'value':{'href':url,'origin':'https://host.example.org','state':'complete','secure':True}}}]
        with patch.object(chrome_console.time,'sleep'):
            chrome_console.wait_for_document(pipe,'session',url)
        self.assertEqual(2,pipe.call.call_count)
        self.assertTrue(all(call.args[0]=='Runtime.evaluate' for call in pipe.call.call_args_list))
        self.assertTrue(all('fetch(' not in call.args[1]['expression'] for call in pipe.call.call_args_list))

    def test_wrong_document_or_insecure_context_never_becomes_ready(self):
        from unittest.mock import Mock
        url='https://host.example.org/devices'
        for state in (
            {'href':url,'origin':'https://other.example.org','state':'complete','secure':True},
            {'href':url,'origin':'https://host.example.org','state':'complete','secure':False},
            {'href':url+'/other','origin':'https://host.example.org','state':'complete','secure':True}):
            pipe=Mock();pipe.call.return_value={'result':{'value':state}}
            with patch.object(chrome_console.time,'sleep'),self.assertRaisesRegex(ValueError,'CONSOLE_DOCUMENT_NOT_READY_NO_DELIVERY'):
                chrome_console.wait_for_document(pipe,'session',url)
            self.assertEqual(50,pipe.call.call_count)
            self.assertTrue(all('fetch(' not in call.args[1]['expression'] for call in pipe.call.call_args_list))

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
        actual_stat=Path.stat
        def fixture_stat(path,*args,**kwargs):
            if str(path)=='/usr/bin/google-chrome':
                return SimpleNamespace(st_uid=0,st_mode=stat.S_IFREG|0o755)
            return actual_stat(path,*args,**kwargs)
        # The child/CDP are synthetic; never depend on a host Chrome install.
        # All private profile directory checks still use the real filesystem.
        with tempfile.TemporaryDirectory() as directory,patch.object(Path,'home',return_value=Path(directory)),patch.object(Path,'stat',fixture_stat),patch('subprocess.Popen',return_value=process) as popen,patch.object(chrome_console.Pipe,'call',side_effect=ValueError('CDP_STALLED')) as cdp:
            with self.assertRaises(ValueError):chrome_console.run({'url':'https://host.example.org/devices','delivery':'A'*43})
            self.assertEqual(1,popen.call_count)
            self.assertEqual(1,cdp.call_count) # No fetch/delivery and no retry.
            self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertTrue(process.stopped)
        self.assertEqual([2],process.waits)

if __name__=='__main__':unittest.main()
