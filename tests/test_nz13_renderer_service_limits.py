"""Service properties must match the signed operation's canonical PID ceiling."""
import unittest

from runtime.mission import sandbox_linux as linux
from runtime.mission.sandbox_contracts import SandboxRecipe


class RendererServiceLimitTests(unittest.TestCase):
    def properties(self, *, renderer=False, pids=16):
        method = getattr(linux, '_systemd_properties', None)
        self.assertTrue(callable(method), 'Missing signed-payload systemd property binding')
        kwargs = {'resource_profile': 'HEADLESS_RENDER_V1'} if renderer else {}
        recipe = SandboxRecipe('recipe:service-v1', 'fixture', 'a' * 64, 'b' * 64, 'c' * 64,
                               pids_max=pids, **kwargs)
        operation = {'operation_class': 'SANDBOX_EXEC', 'target_fingerprint': 'sha256:' + 'd' * 64,
                     'expected_target_revision': 'recipe-v1', 'payload': recipe.payload('workspace', 'task', 'step')}
        return method(operation)

    def test_default_properties_keep_the_previous_sixteen_pid_and_512_mib_contract(self):
        self.assertEqual(('Delegate=yes', 'DelegateSubgroup=supervisor', 'Slice=app.slice',
                          'MemoryMax=536870912', 'MemorySwapMax=0', 'TasksMax=16', 'CPUQuota=100%',
                          'CPUQuotaPeriodSec=100ms', 'NoNewPrivileges=yes', 'LimitAS=536870912',
                          'LimitCPU=15', 'LimitFSIZE=8388608', 'LimitCORE=0', 'LimitNOFILE=64',
                          'RuntimeMaxSec=32s', 'TimeoutStopSec=2s', 'KillMode=control-group', 'UMask=0077'),
                         self.properties())

    def test_explicit_renderer_service_uses_actual_signed_pid_limit(self):
        properties = self.properties(renderer=True, pids=64)
        self.assertIn('TasksMax=64', properties)
        self.assertNotIn('TasksMax=16', properties)
        self.assertIn('MemoryMax=536870912', properties)
        self.assertIn('MemorySwapMax=0', properties)
        self.assertIn('LimitAS=4398046511104', properties)
        self.assertIn('TasksMax=32', self.properties(renderer=True, pids=32))

    def test_unknown_profile_or_out_of_range_pid_cannot_generate_a_service_command(self):
        self.assertTrue(callable(getattr(linux, '_systemd_properties', None)))
        for renderer, pids in ((False, 17), (True, 65), (True, True), (True, '64')):
            with self.subTest(renderer=renderer, pids=pids), self.assertRaises(ValueError):
                self.properties(renderer=renderer, pids=pids)
