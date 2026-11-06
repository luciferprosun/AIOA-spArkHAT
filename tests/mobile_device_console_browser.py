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


def startup_process_state(process):
    """Bounded counters for our synthetic Chrome; no cmdline or environment."""
    code=process.poll()
    if code is not None:return {'state':'EXITED','returncode':code}
    root=Path('/proc')/str(process.pid)
    result={}
    try:
        with (root/'stat').open() as stream:fields=stream.read(1024).rsplit(')',1)[1].split()
        result.update(state=fields[0],minor_faults=int(fields[7]),major_faults=int(fields[9]),
                      user_ticks=int(fields[11]),system_ticks=int(fields[12]))
    except (OSError,ValueError,IndexError):result['state']='UNAVAILABLE'
    for name in ('schedstat','wchan'):
        try:
            with (root/name).open() as stream:value=stream.read(1024).strip()
            if name=='schedstat':
                values=[int(x) for x in value.split()]
                if len(values)!=3:raise ValueError()
                result[name]=values
            else:
                if not re.fullmatch('[A-Za-z0-9_.]{1,128}',value):raise ValueError()
                result[name]=value
        except (OSError,ValueError):result[name]='UNAVAILABLE'
    return result


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
                if value.get('op') in ('command_advice','mail_preview','critic_transform_preview'):
                    # The new pure previews use real temporary Native/Core/audit;
                    # only the pairing registry below is a presentation fixture.
                    return self.app.operator_request(os.getuid(),value)
                if value=={'op':'status'}:
                    return {**self.app.public_settings(),'sessions':[],'history_truncated':False,
                        'observations':[{'proof':{'method':'GET','path':'/api/mobile/v1/status',
                            'issued_at':self.now,'expires_at':self.now+30,'source_sha':self.source[0],
                            'data_sha256':'a'*64},'signature':'SYNTHETIC_NOT_LIVE'}]}
                if value=={'op':'pairing_list'}:
                    reads+=1
                    if reads==8:raise OSError('Synthetic lost readback ACK')
                    if reads==10:
                        from runtime.mobile_gateway.wire import MobileError
                        raise MobileError(403)
                    pending=([row,other] if reads<4 else [other,row] if reads==4 else
                        [other,{**row,'request_digest':'f'*64}] if reads==5 else [other])
                    return {'pending':pending,'devices':[device]}
                self.fail('Browser probe attempted a mutation')
            prelude="""
            window.consoleProbeInitialURL=location.href;
            window.consoleProbeReads=0;
            window.consoleProbeStatusReads=0;
            window.consoleProbePreviewReads=0;
            window.consoleProbeDeliveryFetches=0;
            const originalFetch=window.fetch.bind(window);
            window.fetch=async(...args)=>{
              if(String(args[0]).endsWith('/devices'))window.consoleProbeDeliveryFetches++;
              const reply=await originalFetch(...args);
              if(args[0]==='/api/native-operator'){
                const op=JSON.parse(args[1].body).op;
                if(op==='status')window.consoleProbeStatusReads++;
                else if(['command_advice','mail_preview','critic_transform_preview'].includes(op))window.consoleProbePreviewReads++;
                else window.consoleProbeReads++;
              }
              return reply;};
            const originalInterval=window.setInterval.bind(window);
            window.setInterval=(fn,ms,...args)=>ms===5000?(window.consoleProbePoll=fn,0):originalInterval(fn,ms,...args);
            """
            driver="""
            (async()=>{
              const result={};
              const wait=async(n)=>{for(let i=0;i<200;i++){
                if(window.consoleProbeReads>=n&&!document.getElementById('devices-refresh').disabled&&
                    document.getElementById('devices-pending').getAttribute('aria-busy')!=='true')return;
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
                document.querySelector('[data-cosmic-target="approvals"]').click();
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
                result.background_controls_available=pending().every(x=>!x.disabled)&&!trusted().disabled;
                await wait(2);
                result.pending_focus=document.activeElement===pending()[0];
                document.querySelector('[data-cosmic-target="devices"]').click();
                trusted().focus();window.consoleProbePoll();await wait(3);
                result.device_focus=document.activeElement===trusted();
                document.querySelector('[data-cosmic-target="approvals"]').click();
                pending()[0].focus();window.consoleProbePoll();await wait(4);
                result.reordered_exact_focus=document.activeElement===pending()[1];
                window.consoleProbePoll();await wait(5);
                result.changed_digest_not_focused=document.activeElement===document.body;
                pending()[1].focus();window.consoleProbePoll();await wait(6);
                result.removed_request_not_focused=document.activeElement===document.body;
                pending()[0].focus();window.consoleProbePoll();
                const view=document.getElementById('devices-view');view.tabIndex=-1;view.focus();
                await wait(7);result.deliberate_focus_preserved=document.activeElement===view;
                window.consoleProbePoll();await wait(8);
                result.unknown_clears_cosmic_overview=document.getElementById('cosmic-trusted-count').textContent==='—'&&
                  document.getElementById('cosmic-session-count').textContent==='—'&&statusButton.disabled;
                window.consoleProbePoll();await wait(9);
                result.stale_read_recovers=window.consoleProbeReads===9&&pending().every(x=>!x.disabled)&&
                  !statusButton.disabled&&document.getElementById('cosmic-trusted-count').textContent!=='—';
                document.querySelector('[data-cosmic-target="repositories"]').click();
                const preview=async(id,n)=>{
                  const button=document.getElementById(id);button.click();
                  for(let i=0;i<200&&(window.consoleProbePreviewReads<n||button.disabled);i++)await new Promise(r=>setTimeout(r,20));
                  return JSON.parse(document.getElementById('cosmic-advisory-result').textContent);
                };
                document.getElementById('cosmic-command-input').value='ls /tmp&touch /tmp/not-executed';
                let local=await preview('cosmic-command-preview',1);
                result.command_preview_core_receipt=local.receipt.operation==='command_advice'&&
                  local.receipt.execution_authorized===false&&local.data.classification.danger==='unknown'&&!!local.signature;
                for(const [id,value] of [['sender','author@example.org'],['to','reviewer@example.org'],
                    ['subject','Synthetic local preview'],['body','No mail is sent.']])document.getElementById('cosmic-mail-'+id).value=value;
                local=await preview('cosmic-mail-preview',2);
                result.mail_preview_core_receipt=local.receipt.operation==='mail_preview'&&
                  local.receipt.execution_authorized===false&&local.receipt.external_calls===0&&
                  local.data.status==='DRAFT_PREVIEW_ONLY'&&!!local.signature;
                document.querySelector('[data-cosmic-target="critical"]').click();
                document.getElementById('cosmic-cpt-input').value='A private synthetic <script> prompt to review.';
                local=await preview('cosmic-cpt-preview',3);
                result.cpt_preview_core_receipt=local.receipt.operation==='critic_transform_preview'&&
                  local.receipt.provider_calls===0&&local.data.status==='CPT_DRAFT_PREVIEW_ONLY'&&
                  document.getElementById('cosmic-cpt-result').textContent===local.preview.transformed_prompt&&
                  !document.getElementById('cosmic-cpt-result').querySelector('script')&&!!local.signature;
                document.getElementById('devices-refresh').click();await wait(10);
                result.auth_denial_clears_private_preview=
                  document.getElementById('devices-message').textContent.includes('local operator session')&&
                  document.getElementById('cosmic-advisory-result').textContent==='No preview recorded.'&&
                  document.getElementById('cosmic-cpt-result').textContent==='No critical prompt preview.'&&
                  document.getElementById('cosmic-cpt-input').value===''&&
                  document.getElementById('cosmic-mail-body').value===''&&
                  document.getElementById('cosmic-command-input').value===''&&
                  document.getElementById('cosmic-github-approve').disabled&&
                  document.getElementById('cosmic-github-history-read').disabled;
                window.consoleProbePoll();await new Promise(resolve=>setTimeout(resolve,20));
                result.auth_denial_no_automatic_request=window.consoleProbeReads===10;
                document.getElementById('devices-lock').click();
                result.lock_clears_cpt_preview=document.getElementById('cosmic-cpt-result').textContent==='No critical prompt preview.'&&
                  document.getElementById('cosmic-cpt-input').value===''&&document.getElementById('cosmic-cpt-input').disabled;
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
            from runtime.mobile_gateway.chrome_console import Pipe,cleanup_owned,open_document,deliver_once
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
            # Synthetic, networkless Chrome only. Keep a bounded diagnostic
            # tail on bootstrap failure instead of discarding its start log.
            chrome_stderr=tempfile.TemporaryFile()
            self.addCleanup(chrome_stderr.close)
            process=subprocess.Popen(command,pass_fds=(browser_read,browser_write),stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=chrome_stderr,start_new_session=True)
            os.close(browser_read);os.close(browser_write);pipe=Pipe(parent_write,parent_read)
            with patch.object(service,'mobile_operator_request',side_effect=synthetic_operation):
                try:
                    started=time.monotonic()
                    try:session=open_document(pipe,self.app.origin+'/devices')
                    except Exception:
                        chrome_stderr.seek(0,os.SEEK_END)
                        chrome_stderr.seek(max(0,chrome_stderr.tell()-8192))
                        tail=chrome_stderr.read(8192).decode('utf-8','replace')
                        for secret in (grant['delivery'],service.csrf_token):tail=tail.replace(secret,'[REDACTED]')
                        print('CONSOLE_BROWSER_STARTUP_DIAGNOSTIC '+json.dumps({
                            'elapsed_seconds':round(time.monotonic()-started,3),
                            'returncode':process.poll(),'command_id':pipe.sequence,
                            'buffered_bytes':len(pipe.buffer),'process':startup_process_state(process),'stderr_tail':tail}),file=sys.stderr,flush=True)
                        raise
                    # Invalid canary, never an owner grant: a changed document
                    # must be rejected before fetch is called at all.
                    with self.assertRaisesRegex(ValueError,'CONSOLE_DELIVERY_UNKNOWN_NO_RETRY'):
                        deliver_once(pipe,session,'https://other.example.invalid/devices','Z'*43)
                    calls=pipe.call('Runtime.evaluate',{'expression':'window.consoleProbeDeliveryFetches','returnByValue':True},session)
                    self.assertEqual(0,calls['result']['value'],'Changed-document guard invoked fetch')
                    deliver_once(pipe,session,self.app.origin+'/devices',grant['delivery'])
                    pipe.call('Page.reload',{},session)
                    for _ in range(300):
                        result=pipe.call('Runtime.evaluate',{'expression':"document.getElementById('console-browser-result')?.textContent",'returnByValue':True},session)
                        if result.get('result',{}).get('value'):break
                        time.sleep(.02)
                    dom=pipe.call('Runtime.evaluate',{'expression':'document.documentElement.outerHTML','returnByValue':True},session)
                    outputs.append(dom['result']['value'])
                    # Layout fixtures use the same real markup/styles. They do
                    # not assert LIVE content or issue a model/tool operation.
                    geometry=[]
                    for width,height in ((945,720),(1280,720),(1366,768),(1920,1080)):
                        pipe.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,
                            'deviceScaleFactor':1,'mobile':False},session)
                        for font in (100,200):
                            expression="""(()=>{
                              document.documentElement.style.fontSize=FONT+'%';
                              document.querySelector('[data-cosmic-target="chat"]').click();
                              const box=document.getElementById('native-chat-messages');box.replaceChildren();
                              for(let n=0;n<30;n++){const p=document.createElement('p');
                                p.textContent='TEST_ONLY layout fixture — '+n+' '+('long-source-'.repeat(20));box.append(p);}
                              window.scrollTo(0,0);
                              const log=box.getBoundingClientRect(),composer=document.querySelector('.native-chat-composer').getBoundingClientRect();
                              const control=document.getElementById('native-chat-stop');control.scrollIntoView({block:'nearest'});
                              const button=control.getBoundingClientRect();
                              return {width:innerWidth,height:innerHeight,font:FONT,
                                no_overflow:document.documentElement.scrollWidth<=innerWidth+1,
                                log_height:log.height,independent_scroll:box.scrollHeight>box.clientHeight,
                                no_overlap:log.bottom<=composer.top+1,
                                composer_visible:composer.bottom<=innerHeight+1,
                                control_reachable:button.top>=0&&button.bottom<=innerHeight+1,
                                pages:Array.from(document.querySelectorAll('[data-cosmic-page]')).filter(x=>!x.hidden).length};
                            })()""".replace('FONT',str(font))
                            result=pipe.call('Runtime.evaluate',{'expression':expression,'returnByValue':True},session)['result']['value']
                            geometry.append(result)
                            self.assertTrue(result['no_overflow'],result);self.assertTrue(result['independent_scroll'],result)
                            self.assertTrue(result['no_overlap'],result);self.assertTrue(result['control_reachable'],result)
                            self.assertEqual(1,result['pages']);self.assertGreaterEqual(result['log_height'],96)
                            if font==100:self.assertTrue(result['composer_visible'],result)
                            shot=pipe.call('Page.captureScreenshot',{'format':'png'},session)
                            Path('/out/cosmic-test-layout-'+str(width)+'-'+str(font)+'.png').write_bytes(base64.b64decode(shot['data']))
                    Path('/out/cosmic-test-geometry.json').write_text(json.dumps(geometry,indent=2))
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
            found=re.search(r'<pre id="console-browser-result">(.*?)</pre>',outputs[0],re.S)
            self.assertIsNotNone(found,'Browser probe did not finish')
            result=json.loads(html.unescape(found[1]))
            self.assertNotIn('error',result,result)
            self.assertEqual(14,len(operations));self.assertEqual(10,operations.count({'op':'pairing_list'}))
            self.assertEqual(1,operations.count({'op':'status'}))
            from runtime.mobile_gateway import wire
            from runtime.mobile_gateway.service import plain
            for value in (v for v in operations if v['op'] in ('command_advice','mail_preview','critic_transform_preview')):
                saved=plain(self.app.mobile._get('native-advisory-'+value['request_id']).payload['result'])
                wire.verify(self.app.identity.spki,saved['signature'],saved['receipt'])
                self.assertFalse(saved['receipt']['execution_authorized'])
                self.assertNotIn('preview',saved)
            self.assertTrue(all(value is True for value in result.values()),
                {key:value for key,value in result.items() if value is not True})
            self.assertEqual(dict.fromkeys(('bootstrap','background_controls_available','pending_focus','device_focus',
                'reordered_exact_focus','changed_digest_not_focused','removed_request_not_focused',
                'deliberate_focus_preserved','stale_read_recovers','revoked_reconnect_keeps_legacy_revoke',
                'no_url_or_storage_credential','cosmic_navigation_read_only','local_fonts_loaded',
                'large_text_no_outer_overflow','unknown_clears_cosmic_overview','existing_core_status_read',
                'lock_clears_status_history','empty_lists_and_locked_controls',
                'command_preview_core_receipt','mail_preview_core_receipt',
                'cpt_preview_core_receipt','lock_clears_cpt_preview',
                'auth_denial_clears_private_preview','auth_denial_no_automatic_request'),True),result)

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
