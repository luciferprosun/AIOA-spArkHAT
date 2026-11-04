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
    command=sandbox_command(output,1280,900,source_sha)
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
            device=dict(device_id='e'*64,device_name='Synthetic legacy access',revoked=True,
                active_sessions=1,pending_enrollments=1)
            reads=0
            def synthetic_operation(value):
                nonlocal reads
                operations.append(value)
                if value=={'op':'status'}:
                    return {**self.app.public_settings(),'sessions':[],'history_truncated':False,
                        'observations':[{'proof':{'method':'GET','path':'/api/mobile/v1/status',
                            'issued_at':self.now,'expires_at':self.now+30,'source_sha':self.source[0],
                            'data_sha256':'a'*64},'signature':'SYNTHETIC_NOT_LIVE'}]}
                if value=={'op':'pairing_list'}:
                    reads+=1
                    if reads==8:raise OSError('Synthetic lost readback ACK')
                    pending=([row,other] if reads<4 else [other,row] if reads==4 else
                        [other,{**row,'request_digest':'f'*64}] if reads==5 else [other])
                    return {'pending':pending,'devices':[device]}
                self.fail('Browser probe attempted a mutation')
            prelude="""
            window.consoleProbeInitialURL=location.href;
            window.consoleProbeReads=0;
            window.consoleProbeStatusReads=0;
            const originalFetch=window.fetch.bind(window);
            window.fetch=async(...args)=>{const reply=await originalFetch(...args);
              if(args[0]==='/api/native-operator'){if(JSON.parse(args[1].body).op==='status')window.consoleProbeStatusReads++;else window.consoleProbeReads++;}
              return reply;};
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
                const statusButton=document.getElementById('cosmic-core-read');
                statusButton.click();
                for(let i=0;i<200&&(window.consoleProbeStatusReads<1||statusButton.disabled);i++)await new Promise(r=>setTimeout(r,20));
                result.existing_core_status_read=window.consoleProbeStatusReads===1&&
                  document.getElementById('cosmic-core-settings').textContent.includes('NATIVE_STATUS_READ_ONLY_V1')&&
                  document.getElementById('cosmic-core-observations').textContent.includes('/api/mobile/v1/status')&&
                  document.getElementById('cosmic-core-read-state').textContent.includes('Historical local operator readback');
                let navigationOK=true;
                for (const button of document.querySelectorAll('.cosmic-rail [data-cosmic-target]')) {
                  button.click();
                  const shown=Array.from(document.querySelectorAll('[data-cosmic-page]')).filter(x=>!x.hidden);
                  navigationOK=navigationOK&&shown.length===1&&shown[0].dataset.cosmicPage.split(' ').includes(button.dataset.cosmicTarget)&&
                    document.activeElement===shown[0].querySelector('h2');
                }
                result.cosmic_navigation_read_only=navigationOK&&window.consoleProbeReads===1;
                document.querySelector('[data-cosmic-target="devices"]').click();
                await document.fonts.ready;
                result.local_fonts_loaded=['CosmicBody','CosmicHeading','CosmicMono'].every(name=>
                  Array.from(document.fonts).some(font=>font.family===name&&font.status==='loaded'));
                document.documentElement.style.fontSize='200%';
                result.large_text_no_outer_overflow=document.documentElement.scrollWidth<=document.documentElement.clientWidth+1;
                result.bootstrap=location.pathname==='/devices'&&location.hash===''&&location.search===''&&pending().length===2;
                result.no_url_or_storage_credential=window.consoleProbeInitialURL===location.origin+'/devices'&&
                  document.referrer===''&&localStorage.length===0&&sessionStorage.length===0&&
                  !document.getElementById('aioa-console-credential')&&
                  !document.documentElement.outerHTML.includes('name="delivery"');
                const saved=document.getElementById('devices-trusted').textContent;
                result.revoked_reconnect_keeps_legacy_revoke=!!trusted()&&!trusted().disabled&&
                  saved.includes('Reconnect revoked')&&saved.includes('Active sessions: 1')&&saved.includes('Pending codes: 1');
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
                result.unknown_clears_cosmic_overview=document.getElementById('cosmic-trusted-count').textContent==='—'&&
                  document.getElementById('cosmic-session-count').textContent==='—'&&statusButton.disabled;
                document.getElementById('devices-lock').click();
                result.lock_clears_status_history=!document.getElementById('cosmic-core-settings').textContent.includes('NATIVE_STATUS_READ_ONLY_V1')&&
                  !document.getElementById('cosmic-core-observations').textContent.includes('/api/mobile/v1/status');
                result.empty_lists_and_locked_controls=document.getElementById('devices-pending').textContent.includes('No pending requests')&&
                  document.getElementById('devices-trusted').textContent.includes('No remembered devices')&&statusButton.disabled&&
                  document.getElementById('devices-add').disabled;
              } catch(error) {result.error=error.message;}
              document.getElementById('devices-title').textContent='Cosmic · TEST OFFLINE';
              const output=document.createElement('pre');output.id='console-browser-result';
              output.textContent=JSON.stringify(result);document.body.append(output);
            })();
            """
            preview_mode=[False]
            class BrowserHandler(webapp.AOIAWebHandler):
                def do_GET(handler):
                    capture.append(('GET',handler.path,handler.headers.get('Sec-Fetch-Site')))
                    super().do_GET()
                def do_POST(handler):
                    capture.append(('POST',handler.path,handler.headers.get('Sec-Fetch-Site')))
                    super().do_POST()
                def send_head(handler):
                    # Test-only scripts reuse allowed asset paths. All document and
                    # owner POST admission checks remain the real handler's checks.
                    script={'/qr.js':prelude,'/meta_mission.js':driver}.get(handler.path)
                    if preview_mode[0]:
                        script=("document.getElementById('devices-title').textContent='Cosmic · TEST OFFLINE';"
                            if handler.path=='/qr.js' else None)
                    if script is None:return super().send_head()
                    body=script.encode();handler.send_response(200)
                    handler.send_header('Content-Type','text/javascript');handler.send_header('Content-Length',str(len(body)))
                    handler.end_headers();return io.BytesIO(body)
            service=self.service()
            with patch.object(webapp,'AOIAWebHandler',BrowserHandler):request=self.tls(service)
            test_spki=base64.b64encode(hashlib.sha256(request.certificate_spki).digest()).decode('ascii')
            self.app.origin='https://host.example.org:'+str(request.server.server_address[1])
            grant=self.console_socket(service)({'op':'console'})['data']
            from runtime.mobile_gateway.chrome_console import Pipe,cleanup_owned,wait_for_document
            real_run=subprocess.run;outputs=[]
            # Use the same anonymous-pipe protocol as the real launcher. Only
            # the already contained, networkless fixture uses headless Chrome
            # and its synthetic TLS SPKI; production flags remain unchanged.
            browser_read,parent_write=os.pipe();parent_read,browser_write=os.pipe()
            args=[chrome,'--headless=new','--no-sandbox','--disable-dev-shm-usage','--remote-debugging-pipe',
                '--window-size=1280,900','--no-proxy-server',
                '--host-resolver-rules=MAP host.example.org 127.0.0.1',
                '--ignore-certificate-errors-spki-list='+test_spki,
                '--disable-background-networking','--disable-component-update',
                '--user-data-dir='+str(self.root/'chrome-profile'),'about:blank']
            command=['/bin/bash','-c','exec 3<&'+str(browser_read)+' 4>&'+str(browser_write)+'; exec "$@"','aioa-synthetic-pipe',*args]
            for secret in (grant['delivery'],service.csrf_token):self.assertNotIn(secret,repr(command))
            process=subprocess.Popen(command,pass_fds=(browser_read,browser_write),stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            os.close(browser_read);os.close(browser_write);pipe=Pipe(parent_write,parent_read)
            with patch.object(service,'mobile_operator_request',side_effect=synthetic_operation):
                try:
                    target=pipe.call('Target.createTarget',{'url':self.app.origin+'/devices'})['targetId']
                    session=pipe.call('Target.attachToTarget',{'targetId':target,'flatten':True})['sessionId']
                    wait_for_document(pipe,session,self.app.origin+'/devices')
                    expression='fetch("/devices",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:'+json.dumps('delivery='+grant['delivery'])+'}).then(r=>r.status)'
                    reply=pipe.call('Runtime.evaluate',{'expression':expression,'awaitPromise':True,'returnByValue':True},session)
                    self.assertEqual(200,reply.get('result',{}).get('value'),'Private one-use POST was not accepted')
                    pipe.call('Page.reload',{},session)
                    for _ in range(300):
                        result=pipe.call('Runtime.evaluate',{'expression':"document.getElementById('console-browser-result')?.textContent",'returnByValue':True},session)
                        if result.get('result',{}).get('value'):break
                        time.sleep(.02)
                    dom=pipe.call('Runtime.evaluate',{'expression':'document.documentElement.outerHTML','returnByValue':True},session)
                    outputs.append(dom['result']['value'])
                finally:
                    os.close(parent_write);os.close(parent_read);cleanup_owned(process,group=True,timeout=2)
            persisted={'delivery':[],'csrf':[]}
            for kind,secret in (('delivery',grant['delivery']),('csrf',service.csrf_token)):
                self.assertNotIn(secret,outputs[0])
                for path in (self.root/'chrome-profile').rglob('*'):
                    if not path.is_file():continue
                    with path.open('rb') as stream:
                        previous=b''
                        while chunk:=stream.read(65536):
                            if secret.encode() in previous+chunk:
                                persisted[kind].append(str(path.relative_to(self.root/'chrome-profile')));break
                            previous=chunk[-42:]
            print('CONSOLE_PROFILE_SCAN '+json.dumps(persisted,sort_keys=True),flush=True)
            self.assertFalse(persisted['csrf'],'Reusable CSRF persisted in browser profile')
            # Direct public navigation avoids capturing the spent launcher's
            # blank POST handoff. This second client has no owner credential.
            preview_mode[0]=True
            preview=real_run([chrome,'--headless=new','--no-sandbox','--disable-dev-shm-usage',
                '--no-proxy-server','--host-resolver-rules=MAP host.example.org 127.0.0.1',
                '--ignore-certificate-errors-spki-list='+test_spki,
                '--disable-background-networking','--disable-component-update','--window-size=1280,900',
                '--user-data-dir='+str(self.root/'chrome-preview-profile'),
                '--screenshot=/out/cosmic-web-offline.png','--virtual-time-budget=3000',self.app.origin+'/devices'],
                capture_output=True,text=True,timeout=25)
            self.assertEqual(0,preview.returncode,preview.stderr[-1000:])
            self.assertTrue(Path('/out/cosmic-web-offline.png').is_file(),'Offline screenshot missing')
            small=real_run([chrome,'--headless=new','--no-sandbox','--disable-dev-shm-usage',
                '--no-proxy-server','--host-resolver-rules=MAP host.example.org 127.0.0.1',
                '--ignore-certificate-errors-spki-list='+test_spki,
                '--disable-background-networking','--disable-component-update','--window-size=540,800',
                '--user-data-dir='+str(self.root/'chrome-small-profile'),
                '--screenshot=/out/cosmic-web-small-offline.png','--virtual-time-budget=3000',self.app.origin+'/devices'],
                capture_output=True,text=True,timeout=25)
            self.assertEqual(0,small.returncode,small.stderr[-1000:])
            self.assertTrue(Path('/out/cosmic-web-small-offline.png').is_file(),'Small-window screenshot missing')
            from urllib.parse import urlsplit
            code,raw=request('POST','/devices',('delivery='+grant['delivery']).encode(),
                {**self.navigation,'Host':urlsplit(self.app.origin).netloc})
            self.assertEqual(403,code)
            self.assertEqual('LOCAL_OPERATOR_REQUIRED',json.loads(raw)['error'])
            self.assertFalse(service.csrf_token.encode() in raw,'Replay exposed reusable credential')
            self.assertFalse(grant['delivery'].encode() in raw,'Replay echoed spent delivery ticket')
            self.assertIn(('POST','/devices','same-origin'),capture)
            self.assertTrue(all('?' not in path and '#' not in path for _,path,_ in capture))
            self.assertFalse(any(path=='/api/session' for _,path,_ in capture))
            for secret in (grant['delivery'],service.csrf_token):self.assertNotIn(secret,repr(capture))
            self.assertEqual(9,len(operations));self.assertEqual(8,operations.count({'op':'pairing_list'}))
            self.assertEqual(1,operations.count({'op':'status'}))
            found=re.search(r'<pre id="console-browser-result">(.*?)</pre>',outputs[0],re.S)
            self.assertIsNotNone(found,'Browser probe did not finish')
            result=json.loads(html.unescape(found[1]))
            self.assertEqual(dict.fromkeys(('bootstrap','busy_controls_disabled','pending_focus','device_focus',
                'reordered_exact_focus','changed_digest_not_focused','removed_request_not_focused',
                'deliberate_focus_preserved','unknown_suppresses_poll','revoked_reconnect_keeps_legacy_revoke',
                'no_url_or_storage_credential','cosmic_navigation_read_only','local_fonts_loaded',
                'large_text_no_outer_overflow','unknown_clears_cosmic_overview','existing_core_status_read',
                'lock_clears_status_history','empty_lists_and_locked_controls'),True),result)

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
