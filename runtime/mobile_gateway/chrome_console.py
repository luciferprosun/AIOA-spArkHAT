"""Open the existing native console in Chrome through a private CDP pipe.

The one-use OS-delivered bootstrap exists only on stdin and the anonymous pipe.
No debug TCP port, HTML credential, query parameter, shell interpolation of a
secret, browser extension or alternate frontend is involved. TLS stays enabled.
"""
import json
import os
from pathlib import Path
import re
import select
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

def validate(data):
    from .wire import origin
    if type(data) is not dict or set(data)!={'url','delivery'} or not re.fullmatch('[A-Za-z0-9_-]{43}',data.get('delivery','')):
        raise ValueError('LOCAL_OPERATOR_REQUIRED')
    parsed=urlsplit(data['url'])
    if parsed.path!='/devices' or parsed.query or parsed.fragment or origin('https://'+parsed.netloc)+'/devices'!=data['url']:
        raise ValueError('LOCAL_OPERATOR_REQUIRED')
    return parsed

def launch(data,runtime_dir):
    validate(data);directory=Path(runtime_dir);info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or directory.is_symlink() or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError('PRIVATE_RUNTIME_DIRECTORY_REQUIRED')
    child=subprocess.Popen([sys.executable,'-B','-m','runtime.mobile_gateway.chrome_console'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True,
        cwd=Path(__file__).resolve().parents[2])
    child.stdin.write(json.dumps(data).encode()+b'\n');child.stdin.close()
    if not select.select([child.stdout],[],[],30)[0]:raise ValueError('CONSOLE_OPEN_UNKNOWN_NO_RETRY')
    raw=child.stdout.readline(1025);child.stdout.close()
    if json.loads(raw).get('status')!='AIOA_CHROME_CONSOLE_OPENED':raise ValueError('CONSOLE_OPEN_UNKNOWN_NO_RETRY')

class Pipe:
    def __init__(self,write_fd,read_fd):self.writer,self.reader,self.sequence,self.buffer=write_fd,read_fd,0,b''
    def call(self,method,params=None,session=None):
        self.sequence+=1;identity=self.sequence
        command={'id':identity,'method':method,'params':params or {}}
        if session is not None:command['sessionId']=session
        raw=json.dumps(command).encode()+b'\0';sent=0
        while sent<len(raw):sent+=os.write(self.writer,raw[sent:])
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            while b'\0' in self.buffer:
                raw,self.buffer=self.buffer.split(b'\0',1)
                value=json.loads(raw)
                if value.get('id')==identity:
                    if 'error' in value:raise ValueError('CHROME_COMMAND_FAILED')
                    return value.get('result',{})
            if not select.select([self.reader],[],[],max(.01,deadline-time.monotonic()))[0]:break
            chunk=os.read(self.reader,65536)
            if not chunk:raise ValueError('CHROME_PIPE_CLOSED')
            self.buffer+=chunk
            if len(self.buffer)>2*1024*1024:raise ValueError('CHROME_PIPE_LIMIT')
        raise ValueError('CHROME_COMMAND_UNKNOWN')

def run(data):
    parsed=validate(data);os.umask(0o077)
    executable=Path('/usr/bin/google-chrome')
    info=executable.stat()
    if info.st_uid!=0 or not stat.S_ISREG(info.st_mode) or info.st_mode&0o022:raise ValueError('TRUSTED_CHROME_REQUIRED')
    state=Path.home()/'.local/state/aioa-native-console'
    state.mkdir(parents=True,mode=0o700,exist_ok=True);info=state.lstat()
    if not stat.S_ISDIR(info.st_mode) or state.is_symlink() or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError('PRIVATE_CHROME_PROFILE_REQUIRED')
    with tempfile.TemporaryDirectory(prefix='chrome-',dir=state) as profile:
        browser_read,parent_write=os.pipe();parent_read,browser_write=os.pipe()
        args=[str(executable),'--user-data-dir='+profile,'--remote-debugging-pipe','--no-first-run',
            '--no-default-browser-check','--disable-background-networking',
            '--host-resolver-rules=MAP '+parsed.hostname+' 127.0.0.1:4317','--new-window','about:blank']
        # Only descriptor numbers are shell code; all Chrome arguments use "$@".
        command=['/bin/bash','-c','exec 3<&'+str(browser_read)+' 4>&'+str(browser_write)+'; exec "$@"','aioa-chrome',*args]
        process=subprocess.Popen(command,pass_fds=(browser_read,browser_write),stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        os.close(browser_read);os.close(browser_write)
        pipe=Pipe(parent_write,parent_read)
        try:
            target=pipe.call('Target.createTarget',{'url':data['url']})['targetId']
            session=pipe.call('Target.attachToTarget',{'targetId':target,'flatten':True})['sessionId']
            for _ in range(30):
                value=pipe.call('Runtime.evaluate',{'expression':'document.readyState','returnByValue':True},session)
                if value.get('result',{}).get('value')=='complete':break
                time.sleep(.2)
            # Nothing is inserted into DOM, location, storage or console logs.
            expression='fetch("/devices",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:'+json.dumps('delivery='+data['delivery'])+'}).then(r=>r.status)'
            value=pipe.call('Runtime.evaluate',{'expression':expression,'awaitPromise':True,'returnByValue':True},session)
            data.clear();expression=None
            if value.get('result',{}).get('value')!=200:raise ValueError('CONSOLE_DELIVERY_UNKNOWN_NO_RETRY')
            pipe.call('Page.reload',{},session)
            print(json.dumps({'status':'AIOA_CHROME_CONSOLE_OPENED'}),flush=True)
            # Hold the anonymous pipe while the owner's Chrome window is open.
            # No background model call or mutation is performed by this helper.
            while process.poll() is None:
                if select.select([parent_read],[],[],1)[0]:
                    if not os.read(parent_read,65536):break
        finally:
            os.close(parent_write);os.close(parent_read)
            if process.poll() is None:process.wait()

if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.readline(2049)
        if len(raw)>2048:raise ValueError()
        run(json.loads(raw))
    except Exception:
        print(json.dumps({'status':'CONSOLE_OPEN_UNKNOWN_NO_RETRY'}),flush=True)
