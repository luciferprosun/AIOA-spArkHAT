"""Unprivileged checks for the external disposable-host supervisor."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.unification import native_role_supervisor as supervisor


class NativeRoleSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        roles = ('core', 'broker', 'verifier')
        self.native = {
            'session': '1'*32, 'uids':dict(zip(roles, range(1001,1004))),
            'gids':dict(zip(roles, range(2001,2004))),
            'domains':{r:{'cgroup':'0::/system.slice/'+r+'.service',
                          'apparmor':'aioa-'+r+' (enforce)'} for r in roles}}
        self.manifest = {'schema':'aioa.noble-operator-pins.v1', 'native':self.native,
                         'host':{'source':'2'*40, 'tree':'3'*40}}

    def test_distinct_users_groups_enforced_profiles_and_real_cgroups(self):
        self.assertEqual(self.native['domains']['core'],
                         supervisor.role_config(self.manifest,'core')[2])
        for key in ('uids','gids','domains'):
            with self.subTest(key=key), patch.dict(self.native[key],core=self.native[key]['broker']):
                with self.assertRaisesRegex(ValueError,'DISTINCT'):
                    supervisor.role_config(self.manifest,'core')
        with patch.dict(self.native['domains']['core'],apparmor='unconfined'):
            with self.assertRaisesRegex(ValueError,'DOMAIN_PIN'):
                supervisor.role_config(self.manifest,'core')

    def test_tree_includes_ignored_python_and_preserves_git_order_and_executable_mode(self):
        for path in ('a/', 'a.c', 'a/z', '.gitignore'):
            p = self.root/path
            if path.endswith('/'):
                p.mkdir(mode=0o755)
            else:
                p.write_bytes(b'ignored.py\n')
                p.chmod(0o755 if path == 'a/z' else 0o644)
        env = {'PATH':'/usr/bin:/bin','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
        def git(*args):
            return subprocess.check_output(['/usr/bin/git','-C',str(self.root),*args],
                                           env=env, stderr=subprocess.DEVNULL).decode().strip()
        git('init','--quiet')
        git('add','--all')
        expected = git('write-tree')
        self.assertEqual(expected, supervisor.installed_tree(self.root, owner=os.getuid()))
        injected = self.root/'ignored.py'
        injected.write_bytes(b'')
        injected.chmod(0o644)
        self.assertNotEqual(expected, supervisor.installed_tree(self.root, owner=os.getuid()))
        injected.chmod(0o666)
        with self.assertRaisesRegex(ValueError,'WRITABLE_CHECKOUT'):
            supervisor.installed_tree(self.root, owner=os.getuid())

    def test_dangling_symlink_halts_measurement(self):
        (self.root/'trap').symlink_to(self.root/'missing')
        with self.assertRaises(ValueError):
            supervisor.installed_tree(self.root, owner=os.getuid())

    def test_one_launch_marker_survives_an_interrupted_role(self):
        supervisor.mark(self.root, 'broker')
        with self.assertRaises(FileExistsError):
            supervisor.mark(self.root, 'broker')
        supervisor.mark(self.root, 'core')
        self.assertEqual(0o600, (self.root/'started-probe-broker').stat().st_mode & 0o777)

    def test_broker_signer_identity_mode_and_single_link(self):
        keydir = self.root/'broker'
        keydir.mkdir(mode=0o700)
        key = keydir/'test-signing-key'
        key.write_bytes(b'disposable-public-test-sentinel')
        key.chmod(0o400)
        self.native.update(signer_dev=key.stat().st_dev, signer_ino=key.stat().st_ino)
        self.native['uids']['broker'] = os.getuid()
        with patch.object(supervisor, 'trusted', return_value=keydir.stat()):
            fd = supervisor.broker_fd(self.root, self.native)
            try:
                self.assertFalse(os.get_inheritable(fd))
                self.assertEqual(os.fstat(fd).st_ino, self.native['signer_ino'])
                with self.assertRaises(OSError):
                    os.write(fd,b'x')
            finally:
                os.close(fd)
            key.chmod(0o600)
            with self.assertRaisesRegex(ValueError,'CUSTODY'):
                supervisor.broker_fd(self.root, self.native)
            key.chmod(0o400)
            os.link(key, self.root/'another')
            with self.assertRaisesRegex(ValueError,'CUSTODY'):
                supervisor.broker_fd(self.root, self.native)

    def test_checkout_copy_cannot_start_a_role(self):
        with self.assertRaisesRegex(ValueError,'INSTALLED_OPERATOR_SUPERVISOR_ONLY'):
            supervisor.run('broker',hashlib.sha256(b'{}').hexdigest())
