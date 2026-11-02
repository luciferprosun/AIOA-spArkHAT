"""Dirty gateway/contract bytes must invalidate the same existing capsule."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from runtime.meta_hackathon import runtime_adapter


class MobileSourceSealTests(unittest.TestCase):
    def test_mobile_gateway_and_contract_are_part_of_existing_capsule(self):
        required={'runtime/mobile_gateway/wire.py','runtime/mobile_gateway/service.py',
                  'protocol/mobile_mission_v1.json','runtime/mobile_gateway/pairing.py',
                  'protocol/mobile_pairing_v1.json','web/mobile_devices.js',
                  'web/mobile_devices_dom.js','web/qr.js'}
        self.assertTrue(required <= set(getattr(runtime_adapter,'SOURCE_FILES',())))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in runtime_adapter.SOURCE_FILES:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture-source')
            with patch.object(runtime_adapter,'ROOT',root),patch.object(subprocess,'run',
                    return_value=subprocess.CompletedProcess([],0,stdout='a'*40+'\n')):
                for name in required:
                    with self.subTest(path=name):
                        before=runtime_adapter.current_source()
                        (root/name).write_text('changed-fixture-source')
                        self.assertNotEqual(before,runtime_adapter.current_source())

    def test_symlink_source_fails_before_hash_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in runtime_adapter.SOURCE_FILES:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture-source')
            path=root/'runtime/mobile_gateway/wire.py';path.unlink()
            path.symlink_to(root/'protocol/mobile_mission_v1.json')
            with (patch.object(runtime_adapter,'ROOT',root),patch.object(subprocess,'run',
                    return_value=subprocess.CompletedProcess([],0,stdout='a'*40+'\n')),
                    self.assertRaises(ValueError)):
                runtime_adapter.current_source()


if __name__=='__main__':unittest.main()
