"""Actual documented CLI startup on an owned random loopback port."""
import http.client
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class UnifiedLaunchTests(unittest.TestCase):
    def test_real_module_command_reopens_the_same_private_cache(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state';first_identity=None
            for attempt in range(2):
                with tempfile.TemporaryFile() as errors:
                    process=subprocess.Popen([sys.executable,'-B','-m','runtime.webapp','--unified-offline',
                        '--state-dir',str(state),'--host','127.0.0.1','--port','0'],cwd=root,
                        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,stderr=errors)
                    try:
                        deadline=time.monotonic()+40;address=None
                        while time.monotonic()<deadline and process.poll() is None:
                            if select.select([process.stdout],[],[],.2)[0]:
                                line=process.stdout.readline().decode()
                                found=re.search(r'http://127\.0\.0\.1:([0-9]+)',line)
                                if found:address=int(found.group(1));break
                        errors.seek(0);message=errors.read(8192).decode(errors='replace')
                        self.assertIsNotNone(address,message)
                        def get(path,headers=None):
                            c=http.client.HTTPConnection('127.0.0.1',address,timeout=8)
                            try:
                                c.request('GET',path,headers=headers or {});r=c.getresponse()
                                return r.status,json.loads(r.read())
                            finally:c.close()
                        token=get('/api/session')[1]['token']
                        status,data=get('/api/status',{'X-AIOA-Session-Token':token})
                        self.assertEqual(200,status);self.assertTrue(data['unified_profile'])
                        self.assertEqual('NOT_BUILT',data['capabilities']['apk'])
                        self.assertFalse(data['capabilities']['meta_live'])
                        key=state/'fixture-transport-key.pem'
                        self.assertEqual(0o600,key.stat().st_mode&0o777)
                        identity=__import__('hashlib').sha256(key.read_bytes()).hexdigest()
                        if attempt==0:first_identity=identity
                        else:self.assertEqual(first_identity,identity)
                    finally:
                        if process.poll() is None:process.send_signal(signal.SIGINT)
                        try:process.wait(timeout=15)
                        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                        process.stdout.close()


if __name__=='__main__':unittest.main()
