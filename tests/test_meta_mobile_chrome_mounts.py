"""Command construction only: no browser/network/process execution."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runtime.browser_agent import chrome_process_read as chrome
from runtime.meta_hackathon.runtime_adapter import SOURCE_FILES
from runtime.browser_agent.chrome_read_adapter import BrowserReadError


class MobileCapsuleMountTests(unittest.TestCase):
    def test_every_capsule_file_is_covered_by_an_intended_readonly_mount(self):
        with tempfile.TemporaryDirectory() as output:
            command=chrome.sandbox_command(output,390,844,'a'*40)
        mounts=[(Path(command[n+1]),Path(command[n+2]))
                for n,value in enumerate(command) if value=='--ro-bind']
        directories={'runtime','web','lab'}
        for name in SOURCE_FILES:
            with self.subTest(source=name):
                source=chrome.ROOT/name; destination=Path('/app')/name
                self.assertTrue(any(source==host and destination==guest or
                    host in {chrome.ROOT/p for p in directories} and
                    source.is_relative_to(host) and destination==guest/source.relative_to(host)
                    for host,guest in mounts),name)
        self.assertIn((chrome.ROOT/'LICENSE',Path('/app/LICENSE')),mounts)
        self.assertNotIn((chrome.ROOT,Path('/app')),mounts)
        self.assertFalse(any(host==Path.home() or '.git' in host.parts or '.local' in host.parts
                             for host,guest in mounts))

    def test_only_declared_mobile_source_files_are_visible_to_existing_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            command=chrome.sandbox_command(directory,390,844,'a'*40)
        mounts=[command[n+1] for n,x in enumerate(command) if x=='--ro-bind']
        self.assertNotIn(str(chrome.ROOT/'clients'),mounts)
        self.assertNotIn(str(chrome.ROOT/'protocol'),mounts)
        expected={str(chrome.ROOT/p) for p in SOURCE_FILES if p.startswith(('clients/','protocol/'))}
        actual={p for p in mounts if p.startswith(str(chrome.ROOT/'clients')+'/') or p.startswith(str(chrome.ROOT/'protocol')+'/')}
        self.assertEqual(expected,actual)

    def test_symlink_mobile_source_is_denied_before_mount_or_read(self):
        with tempfile.TemporaryDirectory() as directory,tempfile.TemporaryDirectory() as output:
            root=Path(directory)
            for name in SOURCE_FILES:
                if name.startswith(('runtime/','web/','lab/')):continue
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture-source')
            path=root/'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/Wire.kt'
            path.unlink();path.symlink_to(root/'protocol/mobile_mission_v1.json')
            with patch.object(chrome,'ROOT',root),self.assertRaises(BrowserReadError):
                chrome.sandbox_command(output,390,844,'a'*40)

    def test_symlink_root_license_is_denied_before_mount_or_read(self):
        with tempfile.TemporaryDirectory() as directory,tempfile.TemporaryDirectory() as output:
            root=Path(directory)
            for name in SOURCE_FILES:
                if name=='LICENSE' or name.startswith(('runtime/','web/','lab/')):continue
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('fixture-source')
            (root/'LICENSE').symlink_to(chrome.ROOT/'LICENSE')
            with patch.object(chrome,'ROOT',root),self.assertRaises(BrowserReadError):
                chrome.sandbox_command(output,390,844,'a'*40)


if __name__=='__main__':unittest.main()
