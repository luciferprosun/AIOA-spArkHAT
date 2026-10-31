"""Owned Chrome process for networkless LOCAL UI fixture verification.

Public browser READ remains blocked: there is no approved external egress
broker or domain authority. This driver cannot attach, click, type or execute
model commands. Its fixed worker renders the existing webapp in private Linux
namespaces with no owner home, credentials or host network mounted.
"""
from datetime import datetime, timezone
import errno
from functools import partial
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import stat
import struct
import subprocess
import threading
import time

from runtime.providers.exact import CancellationToken
from .chrome_read_adapter import BrowserReadError

ROOT = Path(__file__).resolve().parents[2]


def require(value, code='CHROME_FIXTURE_DENIED'):
    if not value: raise BrowserReadError(code)


def run_bounded(argv, cancel, timeout, *, max_bytes=2097152):
    require(type(cancel) is CancellationToken and not cancel.cancelled, 'BROWSER_STOPPED')
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, close_fds=True, start_new_session=True,
        env={'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8', 'PYTHONDONTWRITEBYTECODE':'1'})
    selector=None; buffers=[bytearray(),bytearray()]
    deadline=time.monotonic()+timeout
    try:
        selector=selectors.DefaultSelector()
        for number,pipe in enumerate((process.stdout,process.stderr)):
            selector.register(pipe,selectors.EVENT_READ,number)
        while True:
            require(not cancel.cancelled,'BROWSER_STOPPED')
            require(time.monotonic()<deadline,'BROWSER_TIMEOUT_UNKNOWN')
            # WNOWAIT pins the leader PID until group cleanup, including after
            # its exit. EOF does not imply process completion or cancel ACK.
            exited=os.waitid(os.P_PID,process.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
            if not selector.get_map() and exited is not None:break
            ready=selector.select(.02) if selector.get_map() else ()
            if not selector.get_map():time.sleep(.01)
            for key,_ in ready:
                data=os.read(key.fileobj.fileno(),16384)
                if not data:selector.unregister(key.fileobj);continue
                buffers[key.data].extend(data)
                require(sum(map(len,buffers))<=max_bytes,'BROWSER_OUTPUT_LIMIT_UNKNOWN')
    finally:
        # Clean descendants even if the leader has exited. It is not reaped
        # until after signalling, so this PGID cannot be reused in the meantime.
        for sig in (signal.SIGTERM,signal.SIGKILL):
            try:os.killpg(process.pid,sig)
            except ProcessLookupError:pass
            if sig==signal.SIGTERM:time.sleep(.02)
        process.wait(timeout=1)
        if selector is not None:selector.close()
        process.stdout.close();process.stderr.close()
    return process.returncode,bytes(buffers[0]),bytes(buffers[1])


def sandbox_command(output, width, height, source_sha):
    output=Path(output).absolute(); info=output.lstat()
    require(output.resolve()==output and stat.S_ISDIR(info.st_mode) and info.st_uid==os.getuid()
            and stat.S_IMODE(info.st_mode)==0o700)
    require((width,height) in ((390,844),(1280,900)) and re.fullmatch('[a-f0-9]{40}',source_sha))
    argv=['/usr/bin/bwrap','--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL',
        '--clearenv','--setenv','PATH','/usr/bin:/bin','--setenv','HOME','/tmp/home',
        '--setenv','LANG','C.UTF-8','--setenv','PYTHONPATH','/app',
        '--setenv','AIOA_FIXTURE_SOURCE_HEAD',source_sha,
        '--setenv','AIOA_HOST_NETNS',os.readlink('/proc/self/ns/net')]
    for name in ('/usr','/bin','/lib','/lib64','/opt/google/chrome',
                 '/etc/ld.so.cache','/etc/fonts','/etc/nsswitch.conf','/etc/hosts','/etc/localtime'):
        if Path(name).exists():argv+=['--ro-bind',name,name]
    # Deliberately exclude .git, .local, .env, the home directory and other repos.
    for name in ('runtime','web','lab'):
        argv+=['--ro-bind',str(ROOT/name),'/app/'+name]
    argv+=['--ro-bind',str(ROOT/'tests/fixtures/meta_p03_ui_probe.js'),'/app/probe.js',
        '--bind',str(output),'/out','--proc','/proc','--dev','/dev','--tmpfs','/tmp',
        '--dir','/tmp/home','--chdir','/app','--','/usr/bin/python3','-B','-m',
        'runtime.browser_agent.chrome_process_read','--worker',str(width),str(height)]
    return argv


class NetworklessChromeReadDriver:
    def navigate_read(self, url):
        # No env variable, caller flag, forged receipt or model URL can enable it.
        raise BrowserReadError('CHROME_LIVE_BLOCKED_CONTAINMENT')

    def capture_ui(self, output, *, width=390, height=844, source_sha, cancel=None):
        cancel=cancel or CancellationToken()
        require(not any(Path(output).iterdir()),'CHROME_OUTPUT_NOT_EMPTY')
        status,raw,_=run_bounded(sandbox_command(output,width,height,source_sha),cancel,15)
        require(status==0,'CHROME_LOCAL_PROCESS_UNKNOWN')
        try:value=json.loads(raw)
        except Exception:raise BrowserReadError('CHROME_LOCAL_READBACK_UNKNOWN') from None
        require(value.get('scope')=='LOCAL_UI_BROWSER_TESTED' and value.get('external_network') is False
                and value.get('source_sha')==source_sha and value.get('ui',{}).get('passed') is True)
        return value


class _ProofParser(HTMLParser):
    def __init__(self):super().__init__();self.selected=False;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag=='pre' and dict(attrs).get('id')=='p03-ui-proof':self.selected=True
    def handle_endtag(self,tag):
        if tag=='pre':self.selected=False
    def handle_data(self,data):
        if self.selected:self.parts.append(data)


def _worker(width,height):
    """Fixed test worker, never an alternate product entrypoint or LIVE host."""
    os.umask(0o077)
    namespace=os.readlink('/proc/self/ns/net')
    require(namespace!=os.environ.get('AIOA_HOST_NETNS')
        and {name for _,name in socket.if_nameindex()}=={'lo'}
        and len(Path('/proc/net/route').read_text().splitlines())==1
        and not Path('/home/l').exists() and not Path('/run/user/1000').exists())
    require(int(re.search(r'^CapEff:\s+([a-f0-9]+)',Path('/proc/self/status').read_text(),re.M)[1],16)==0)
    with socket.socket() as sock:
        sock.settimeout(.2)
        require(sock.connect_ex(('198.51.100.1',443)) in (errno.ENETUNREACH,errno.EHOSTUNREACH,errno.ENETDOWN))
    from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition,current_source
    from runtime.webapp import AOIAWebHandler,WebRuntimeService,make_server
    source_sha=os.environ['AIOA_FIXTURE_SOURCE_HEAD']
    host=OfflineMetaComposition('/tmp/core-state',delay_seconds=.45,
                                source_probe=lambda:(source_sha,current_source()[1]))
    service=WebRuntimeService(runtime=host.runtime,meta_missions=host.missions,meta_owner=host)
    class Handler(AOIAWebHandler):
        def do_GET(self):
            if self.path=='/p03-local-clock':
                if not self._check_local_request():return
                # The test browser advances virtual timers faster than the Core
                # fixture's wall-clock cancellation delay. Synchronize the test
                # actor over this namespace-local endpoint, not production API.
                time.sleep(.03)
                self.send_response(204);self.send_header('Content-Length','0');self.end_headers()
                return
            if self.path in ('/','/p03-local-probe.js'):
                if not self._check_local_request():return
                body=(ROOT/'web/index.html').read_bytes().replace(b'</body>',
                    b'<script type="module" src="/p03-local-probe.js"></script></body>') if self.path=='/' else Path('/app/probe.js').read_bytes()
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8' if self.path=='/' else 'text/javascript')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            else:super().do_GET()
    server=make_server('127.0.0.1',0,service);server.RequestHandlerClass=partial(Handler,service=service)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    profile=Path('/tmp/chrome-profile');profile.mkdir(mode=0o700)
    url='http://127.0.0.1:'+str(server.server_port)+'/'
    chrome=['/opt/google/chrome/chrome','--headless','--disable-gpu','--disable-dev-shm-usage',
        '--no-first-run','--no-default-browser-check','--disable-background-networking',
        '--disable-sync','--disable-extensions','--disable-component-update','--user-data-dir='+str(profile),
        '--window-size='+str(width)+','+str(height),'--force-device-scale-factor=1',
        '--timeout=10000','--virtual-time-budget=6500','--screenshot=/out/ui.png','--dump-dom',url]
    try:
        status,dom,err=run_bounded(chrome,CancellationToken(),12)
        require(status==0,'CHROME_LOCAL_EXIT_UNKNOWN')
        parser=_ProofParser();parser.feed(dom.decode('utf-8'))
        proof=json.loads(''.join(parser.parts))
        Path('/out/UI_TEST_RESULT.json').write_text(json.dumps(proof,indent=2)+'\n')
        Path('/out/CHROME.stderr').write_bytes(err)
        require(proof.get('passed') is True,'CHROME_UI_PROBE_FAILED')
        screenshot=Path('/out/ui.png');info=screenshot.lstat()
        require(stat.S_ISREG(info.st_mode) and 32<info.st_size<=2097152)
        png=screenshot.read_bytes();require(png[:8]==b'\x89PNG\r\n\x1a\n')
        dimensions=struct.unpack('>II',png[16:24]);require(min(dimensions)>200)
        record={'schema':'aioa.meta.p03.local-chrome.v1','scope':'LOCAL_UI_BROWSER_TESTED',
            'source_sha':source_sha,'capsule_digest':current_source()[1],
            'captured_at_utc':datetime.now(timezone.utc).isoformat(), 'final_url':url,
            'external_network':False,'network_namespace':namespace,'host_home_mounted':False,
            'chrome_sandbox_disabled':False,'profile_mode':oct(stat.S_IMODE(profile.stat().st_mode)),
            'screenshot_sha256':hashlib.sha256(png).hexdigest(),'screenshot_dimensions':dimensions,
            'visible_text_sha256':proof['visible_text_sha256'],'ui':proof,
            'actual_meta_calls':0,'public_browser_reads':0}
        Path('/out/CHROME_UI_PROOF.json').write_text(json.dumps(record,indent=2)+'\n')
        print(json.dumps(record))
    finally:
        server.shutdown();server.server_close();thread.join(2);service.close()


if __name__=='__main__':
    import sys
    require(len(sys.argv)==4 and sys.argv[1]=='--worker')
    _worker(int(sys.argv[2]),int(sys.argv[3]))
