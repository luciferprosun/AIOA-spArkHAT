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
                  'protocol/mobile_mission_v1.json'}
        self.assertTrue(required <= set(getattr(runtime_adapter,'SOURCE_FILES',())))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in runtime_adapter.SOURCE_FILES:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture-source')
            with patch.object(runtime_adapter,'ROOT',root),patch.object(subprocess,'run',
                    return_value=subprocess.CompletedProcess([],0,stdout='a'*40+'\n')):
                before=runtime_adapter.current_source()
                (root/'runtime/mobile_gateway/wire.py').write_text('changed-fixture-source')
                self.assertNotEqual(before,runtime_adapter.current_source())


if __name__=='__main__':unittest.main()
