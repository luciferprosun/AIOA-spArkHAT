"""Command construction only: no browser/network/process execution."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runtime.browser_agent import chrome_process_read as chrome
from runtime.meta_hackathon.runtime_adapter import SOURCE_FILES
from runtime.browser_agent.chrome_read_adapter import BrowserReadError


class MobileCapsuleMountTests(unittest.TestCase):
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
                if not name.startswith(('clients/','protocol/')):continue
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture-source')
            path=root/'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/Wire.kt'
            path.unlink();path.symlink_to(root/'protocol/mobile_mission_v1.json')
            with patch.object(chrome,'ROOT',root),self.assertRaises(BrowserReadError):
                chrome.sandbox_command(output,390,844,'a'*40)


if __name__=='__main__':unittest.main()
