"""Required, networkless Chrome regression. Invoke with /usr/bin/python3 -B.

This explicit test gate is outside unittest test*.py discovery. Its fixed worker
reuses existing capsule containment; it creates only synthetic fixture state.
No missing prerequisite or failed browser assertion is converted into a skip.
"""
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime.browser_agent.chrome_process_read import sandbox_command,run_bounded
from runtime.providers.exact import CancellationToken


def require_prerequisites():
    for name in ('/usr/bin/bwrap','/usr/bin/python3','/opt/google/chrome/chrome'):
        if not os.access(name,os.X_OK):
            raise RuntimeError('CONSOLE_BROWSER_PREREQUISITE_REQUIRED: '+name)
    result=subprocess.run(['/usr/bin/python3','-I','-B','-c','import cryptography'],
        capture_output=True,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
    if result.returncode:
        raise RuntimeError('CONSOLE_BROWSER_PREREQUISITE_REQUIRED: system Python cryptography')


def browser_command(output,source_sha):
    command=sandbox_command(output,390,844,source_sha)
    command=command[:command.index('--')]
    for name in ('test_mobile_device_console.py','test_mobile_pairing.py','mobile_device_console_browser.py'):
        command+=['--ro-bind',str(ROOT/'tests'/name),'/app/tests/'+name]
    return command+['--','/usr/bin/python3','-B','/app/tests/mobile_device_console_browser.py','--worker']


def verify_isolation():
    host_namespace=os.environ.get('AIOA_HOST_NETNS')
    if (not host_namespace or os.readlink('/proc/self/ns/net')==host_namespace
            or {name for _,name in socket.if_nameindex()}!={'lo'}
            or len(Path('/proc/net/route').read_text().splitlines())!=1
            or Path('/home').exists() or Path('/run/user').exists()
            or Path('/app/.git').exists() or os.environ.get('HOME')!='/tmp/home'
            or int(re.search(r'^CapEff:\s+([a-f0-9]+)',Path('/proc/self/status').read_text(),re.M)[1],16)!=0):
        raise RuntimeError('CONSOLE_BROWSER_ISOLATION_REQUIRED')


def worker():
    verify_isolation()
    import test_mobile_device_console as console
    class BrowserConsoleTests(console.DeviceConsoleTests):
        def test_chrome_private_launcher_bootstrap_and_exact_control_focus(self):
            """Fresh-profile Chrome, synthetic TLS/Core/rows; never physical acceptance."""
            import html
            import base64
            import hashlib
            import io
            import json
            import re
            import subprocess
            import time
            from pathlib import Path
            import runtime.webapp as webapp
            chrome='/opt/google/chrome/chrome'
            capture=[];operations=[]
            row=dict(request_id='1'*32,request_digest='a'*64,device_id='b'*64,
                device_name='Synthetic phone',sas='123456',state='PENDING',expires_at=int(time.time())+600)
            other={**row,'request_id':'2'*32,'request_digest':'c'*64,'device_id':'d'*64,'sas':'654321'}
            device=dict(device_id='e'*64,device_name='Synthetic trusted phone',revoked=False)
            reads=0
            def synthetic_operation(value):
                nonlocal reads
                operations.append(value)
                if value=={'op':'pairing_list'}:
                    reads+=1
                    if reads==8:raise OSError('Synthetic lost readback ACK')
                    pending=([row,other] if reads<4 else [other,row] if reads==4 else
                        [other,{**row,'request_digest':'f'*64}] if reads==5 else [other])
                    return {'pending':pending,'devices':[device]}
                self.fail('Browser probe attempted a mutation')
            prelude="""
            window.consoleProbeReads=0;
            const originalFetch=window.fetch.bind(window);
            window.fetch=async(...args)=>{const reply=await originalFetch(...args);window.consoleProbeReads++;return reply;};
            const originalInterval=window.setInterval.bind(window);
            window.setInterval=(fn,ms,...args)=>ms===5000?(window.consoleProbePoll=fn,0):originalInterval(fn,ms,...args);
            """
            driver="""
            (async()=>{
              const result={};
              const wait=async(n)=>{for(let i=0;i<200;i++){
                if(window.consoleProbeReads>=n&&!document.getElementById('devices-refresh').disabled)return;
                await new Promise(r=>setTimeout(r,20));
              }throw Error('readback timeout '+n);};
              const pending=()=>Array.from(document.querySelectorAll('#devices-pending button'));
              const trusted=()=>document.querySelector('#devices-trusted button');
              try {
                await wait(1);
                result.bootstrap=location.pathname==='/devices'&&location.hash===''&&pending().length===2;
                pending()[0].focus();window.consoleProbePoll();
                result.busy_controls_disabled=pending().every(x=>x.disabled)&&trusted().disabled;
                await wait(2);
                result.pending_focus=document.activeElement===pending()[0];
                trusted().focus();window.consoleProbePoll();await wait(3);
                result.device_focus=document.activeElement===trusted();
                pending()[0].focus();window.consoleProbePoll();await wait(4);
                result.reordered_exact_focus=document.activeElement===pending()[1];
                window.consoleProbePoll();await wait(5);
                result.changed_digest_not_focused=document.activeElement===document.body;
                pending()[1].focus();window.consoleProbePoll();await wait(6);
                result.removed_request_not_focused=document.activeElement===document.body;
                pending()[0].focus();window.consoleProbePoll();
                const view=document.getElementById('devices-view');view.tabIndex=-1;view.focus();
                await wait(7);result.deliberate_focus_preserved=document.activeElement===view;
                window.consoleProbePoll();await wait(8);window.consoleProbePoll();
                await new Promise(r=>setTimeout(r,50));
                result.unknown_suppresses_poll=window.consoleProbeReads===8&&pending().every(x=>x.disabled);
              } catch(error) {result.error=error.message;}
              const output=document.createElement('pre');output.id='console-browser-result';
              output.textContent=JSON.stringify(result);document.body.append(output);
            })();
            """
            class BrowserHandler(webapp.AOIAWebHandler):
                def do_GET(handler):
                    capture.append((handler.path,handler.headers.get('Sec-Fetch-Site')))
                    super().do_GET()
                def send_head(handler):
                    # Test-only scripts reuse allowed asset paths. All document and
                    # owner POST admission checks remain the real handler's checks.
                    script={'/qr.js':prelude,'/meta_mission.js':driver}.get(handler.path)
                    if script is None:return super().send_head()
                    body=script.encode();handler.send_response(200)
                    handler.send_header('Content-Type','text/javascript');handler.send_header('Content-Length',str(len(body)))
                    handler.end_headers();return io.BytesIO(body)
            service=self.service()
            with patch.object(webapp,'AOIAWebHandler',BrowserHandler):request=self.tls(service)
            test_spki=base64.b64encode(hashlib.sha256(request.certificate_spki).digest()).decode('ascii')
            self.app.origin='https://host.example.org:'+str(request.server.server_address[1])
            grant=self.console_socket(service)({'op':'console'})['data']
            real_run=subprocess.run;outputs=[];files=[]
            def launch(argv,**kwargs):
                self.assertEqual('/usr/bin/xdg-open',argv[0]);self.assertNotIn(grant['token'],str(argv))
                files.append(Path(argv[1].removeprefix('file://')))
                result=real_run([chrome,'--headless=new','--no-sandbox','--disable-dev-shm-usage',
                    '--no-proxy-server','--host-resolver-rules=MAP host.example.org 127.0.0.1',
                    '--ignore-certificate-errors-spki-list='+test_spki,
                    '--disable-background-networking','--disable-component-update',
                    '--user-data-dir='+str(self.root/'chrome-profile'),'--dump-dom','--virtual-time-budget=15000',argv[1]],
                    capture_output=True,text=True,timeout=40)
                outputs.append(result.stdout);self.assertEqual(0,result.returncode,result.stderr[-2000:]);return result
            with patch.object(service,'mobile_operator_request',side_effect=synthetic_operation),\
                    patch('subprocess.run',side_effect=launch),patch('time.sleep'):
                webapp._launch_mobile_console(grant,self.root)
            self.assertFalse(files[0].exists())
            self.assertIn(('/devices','cross-site'),capture)
            self.assertEqual(8,len(operations));self.assertTrue(all(x=={'op':'pairing_list'} for x in operations))
            found=re.search(r'<pre id="console-browser-result">(.*?)</pre>',outputs[0],re.S)
            self.assertIsNotNone(found,'Browser probe did not finish')
            result=json.loads(html.unescape(found[1]))
            self.assertEqual(dict.fromkeys(('bootstrap','busy_controls_disabled','pending_focus','device_focus',
                'reordered_exact_focus','changed_digest_not_focused','removed_request_not_focused',
                'deliberate_focus_preserved','unknown_suppresses_poll'),True),result)

    suite=unittest.TestSuite([BrowserConsoleTests('test_chrome_private_launcher_bootstrap_and_exact_control_focus')])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or result.testsRun!=1:
        raise SystemExit(1)


def main():
    if sys.argv[1:]==['--worker']:
        worker();return
    if sys.argv[1:]:raise RuntimeError('CONSOLE_BROWSER_INVOCATION_DENIED')
    require_prerequisites()
    source_sha=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    with tempfile.TemporaryDirectory(prefix='aioa-console-browser-') as output:
        status,stdout,stderr=run_bounded(browser_command(output,source_sha),CancellationToken(),55)
    sys.stdout.buffer.write(stdout);sys.stderr.buffer.write(stderr)
    if status:raise SystemExit(status)


if __name__=='__main__':main()
