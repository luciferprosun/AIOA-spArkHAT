"""No ambient execution authority, including an installed runtime."""
import importlib.util
import unittest
from unittest.mock import patch

class LinuxSandboxBoundaryTests(unittest.TestCase):
    def backend(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mission.sandbox_linux'), 'Missing sandbox broker')
        from runtime.mission.sandbox_linux import LinuxSandboxBroker
        return LinuxSandboxBroker

    def test_import_and_unconfigured_backend_never_spawn(self):
        with patch('subprocess.Popen', side_effect=AssertionError('ambient spawn')):
            cls=self.backend()
            with self.assertRaisesRegex(ValueError,'TRUSTED_SANDBOX_CONFIGURATION_REQUIRED'):cls()

    def test_raw_request_never_supplies_gate_authority(self):
        cls=self.backend()
        with patch('subprocess.Popen', side_effect=AssertionError('ambient spawn')):
            with self.assertRaisesRegex(ValueError,'TRUSTED_SANDBOX_CONFIGURATION_REQUIRED'):cls(config={})

    def test_filter_has_native_abi_and_namespace_guards(self):
        self.backend()
        from runtime.mission.sandbox_linux import build_filter
        import struct
        code=build_filter(final=True)
        rows=[struct.unpack('<HBBI',code[i:i+8]) for i in range(0,len(code),8)]
        self.assertIn((0x15,1,0,0xc000003e),rows)
        self.assertIn((0x06,0,0,0x00050026),rows) # clone3 ENOSYS
        self.assertIn((0x54,0,0,0x7e020080),rows) # all CLONE_NEW flags
