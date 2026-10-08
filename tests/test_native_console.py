"""Native READ projection; default UI/token behavior remains unchanged."""
import importlib.util,json,http.client,threading,unittest
from pathlib import Path
from unittest.mock import patch
import test_dual_governor as native
from runtime.core_admission import Capability

class ConsolePresenceTests(unittest.TestCase):
    def test_existing_ui_has_optional_native_console_binding(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.native_console'))

class NativeConsoleTests(unittest.TestCase):
    def setUp(self):
        from runtime.native_console import NativeConsoleBinding
        self.fx=native.DualGovernorTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.binding=NativeConsoleBinding(self.fx.gov,model_id=native.MODEL)
    def test_native_read_is_exact_bounded_and_has_no_mutation_or_private_ids(self):
        self.fx.reserve();before=self.fx.path.read_bytes()
        value=self.binding.read(self.fx.principal(Capability.READ));text=json.dumps(value)
        self.assertEqual('50',value['governor']['money_nano']);self.assertEqual('5',value['governor']['risk_units'])
        self.assertEqual(1,value['governor']['reservation_counts']['RESERVED'])
        self.assertEqual('NONE',value['authority']);self.assertFalse(value['execution_authority'])
        self.assertNotIn('governor-owner',text);self.assertNotIn('task1',text)
        self.assertEqual(before,self.fx.path.read_bytes());self.assertLessEqual(len(text.encode()),8192)
        self.assertEqual('UNBOUND',value['readback']['status'])
    def test_unknown_keeps_exposure_and_kill_is_readable(self):
        self.fx.reserve();self.fx.dispatch()
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        self.fx.gov.mark_unknown(self.fx.principal(),'r1',self.fx.epoch,canonical_sha256('lost'))
        self.fx.gov.set_kill(self.fx.principal(Capability.MANAGE),True)
        value=self.binding.read(self.fx.principal(Capability.READ))
        self.assertTrue(value['governor']['kill']);self.assertEqual(1,value['governor']['open_liabilities'])
        self.assertEqual('50',value['governor']['money_nano']);self.assertFalse(value['auto_retry'])
    def test_foreign_commit_and_expired_principal_are_denied(self):
        from test_memory_patch_persistence_ports import make_admission
        from datetime import datetime,timezone
        other=make_admission(owner='foreign');self.addCleanup(other.close)
        for p in (self.fx.principal(),other.local_operator(Capability.READ)):
            with self.assertRaises(ValueError):self.binding.read(p)
        p=self.fx.principal(Capability.READ)
        with patch.object(self.fx.core,'_clock',return_value=datetime(2030,1,1,1,tzinfo=timezone.utc)):
            with self.assertRaises(ValueError):self.binding.read(p)
    def test_native_error_projection_is_unknown_without_exception_text(self):
        with patch.object(type(self.fx.gov),'inspect',side_effect=ValueError('private-message')):
            value=self.binding.read(self.fx.principal(Capability.READ))
        self.assertEqual('UNKNOWN',value['governor']['status']);self.assertIsNone(value['governor']['kill'])
        self.assertNotIn('private-message',json.dumps(value))
    def test_large_money_is_exact_decimal_text(self):
        from runtime.native_console import project_governor
        state=self.fx.inspect();state['exposure']['global']['money_nano']=2**63-1
        self.assertEqual(str(2**63-1),project_governor(state)['money_nano'])
    def test_http_requires_token_and_get_preserves_store(self):
        import tempfile
        from webapp import WebRuntimeService,make_server
        from nv09_support import LocalTarget,GuardFixture
        from runtime.mission.governor import CoreDualGovernor,GovernorPolicy,Limits
        from runtime.native_console import NativeConsoleBinding
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);root=Path(temporary.name)
        target=LocalTarget(root/'target');self.addCleanup(target.close)
        fx=GuardFixture(root/'guard',target.client,model_id=native.MODEL);self.addCleanup(fx.close)
        policy=GovernorPolicy(fx.scope,'console',Limits(0,10),Limits(0,10),Limits(0,10))
        gov=CoreDualGovernor(fx.core,fx.runner,policy,clock=fx.clock);gov.start_epoch(fx.core.local_operator(Capability.MANAGE))
        binding=NativeConsoleBinding(gov,guard=fx.guard,operation_id=fx.operation_id)
        service=WebRuntimeService(runtime=fx.runtime,native_console=binding)
        server=make_server('127.0.0.1',0,service);thread=threading.Thread(target=server.serve_forever);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(3)))
        before=(fx.root/'native-fixture.json').read_bytes()
        def get(headers):
            c=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=3)
            c.request('GET','/api/authority-timeline',headers=headers);r=c.getresponse();status=r.status;v=json.loads(r.read());c.close();return status,v
        self.assertEqual(403,get({})[0])
        status,value=get({'X-AIOA-Session-Token':service.csrf_token})
        self.assertEqual(200,status);self.assertIn('native_console',value);self.assertEqual(before,(fx.root/'native-fixture.json').read_bytes())
    def test_unrelated_runtime_cannot_acquire_console_core_read(self):
        from webapp import WebRuntimeService
        from test_authority_timeline import _Runtime
        with self.assertRaises(ValueError):WebRuntimeService(runtime=_Runtime(),native_console=self.binding)
    def test_failed_refresh_clears_current_looking_metadata(self):
        script=(Path(__file__).resolve().parents[1]/'web/app.js').read_text()
        self.assertIn('renderNativeConsole({status: "UNKNOWN"',script)
    def test_renderer_uses_metadata_text_and_old_controls_are_present(self):
        root=Path(__file__).resolve().parents[1];js=(root/'web/app.js').read_text();html=(root/'web/index.html').read_text()
        self.assertIn('renderNativeConsole',js);self.assertIn('native-console-metadata',html)
        self.assertIn('textContent',js);self.assertIn('nonzero',html);self.assertIn('cpl',html)
