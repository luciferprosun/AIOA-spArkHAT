"""Strict sandbox requests carry bindings without creating authority."""
from importlib.util import find_spec
import json
import unittest
from dataclasses import replace, FrozenInstanceError
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256


class SandboxContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(find_spec('runtime.mission.sandbox_contracts'),
                             'Missing strict acyclic sandbox operation/request contract')
        from runtime.mission.sandbox_contracts import SandboxOperation, SandboxDispatchRequest
        self.Operation,self.Request=SandboxOperation,SandboxDispatchRequest
        self.payload={'tool':'run_recipe','workspace':'workspace-1','task_id':'task-1','step_id':'effect',
            'recipe_id':'tiny-python-v1','argv':['/usr/bin/python3.12','-I','-S','-B','/inputs/recipe.py'],
            'project_root_ref':'root-1','sandbox_profile_digest':'a'*64,'tool_input_digest':'b'*64,
            'timeout_ms':5000,'max_output_bytes':4096,'memory_bytes':536870912,
            'cpu_quota_us':100000,'cpu_period_us':100000,'pids_max':16,'work_bytes':33554432,
            'tmp_bytes':16777216,'artifacts_bytes':8388608,'network_profile':'OFF','env_policy_digest':'c'*64}
        self.operation={'operation_class':'SANDBOX_EXEC','target_fingerprint':'sha256:'+'d'*64,
            'expected_target_revision':'revision-1','payload':self.payload}
        self.args={'operation_bytes':canonical_json_bytes(self.operation),
            'operation_digest':'sha256:'+canonical_sha256(self.operation),'task_id':'task-1','step_id':'effect',
            'session_id':'session-1','session_grant_digest':'1'*64,'policy_epoch':1,
            'warrant_digest':'sha256:'+'2'*64,'ddr_digest':'sha256:'+'3'*64,'reservation_digest':'4'*64,
            'completion_digest':'5'*64,'idempotency_key':'nonce-1'}

    def test_operation_rejects_authority_fields_and_unknown_schema(self):
        for field in ['session_id','session_grant_digest','warrant_digest','completion_digest','idempotency_key','approved']:
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.Operation.parse({**self.operation,'payload':{**self.payload,field:'forged'}})
        with self.assertRaises(ValueError):self.Operation.parse({**self.operation,'extra':True})

    def test_operation_rejects_bool_numeric_fields(self):
        for field in ['timeout_ms','max_output_bytes','memory_bytes','cpu_quota_us','cpu_period_us',
                      'pids_max','work_bytes','tmp_bytes','artifacts_bytes']:
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.Operation.parse({**self.operation,'payload':{**self.payload,field:True}})

    def test_operation_rejects_shell_env_network_and_traversal(self):
        for change in [{'argv':'echo forged'},{'argv':['/bin/sh','-c','echo forged']},
                       {'argv':['/usr/bin/python3.12','../escape.py']},{'network_profile':'ON'},
                       {'env':{'TOKEN':'forged'}},{'cwd':'/home'}]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.Operation.parse({**self.operation,'payload':{**self.payload,**change}})

    def test_operation_returns_private_immutable_canonical_bytes(self):
        op=self.Operation.parse(self.operation)
        before=op.operation_bytes
        self.payload['argv'][0]='/bin/sh'
        self.assertEqual(before,op.operation_bytes)
        with self.assertRaises(FrozenInstanceError):op.operation_bytes=b'{}'

    def test_dispatch_rejects_hash_task_step_mismatch(self):
        for change in [{'operation_digest':'sha256:'+'0'*64},{'task_id':'other'},{'step_id':'other'},
                       {'operation_bytes':bytearray(self.args['operation_bytes'])},{'policy_epoch':True}]:
            with self.subTest(change=change),self.assertRaises(ValueError):self.Request(**{**self.args,**change})

    def test_dispatch_hash_is_separate_from_pregrant_operation(self):
        request=self.Request(**self.args)
        changed=replace(request,session_grant_digest='6'*64)
        self.assertEqual(request.operation_digest,changed.operation_digest)
        self.assertNotEqual(request.digest,changed.digest)
        payload=json.loads(request.operation_bytes)['payload']
        self.assertNotIn('session_grant_digest',payload)
        self.assertNotIn('digest',request.to_dict())
        self.assertEqual('aioa.sandbox-dispatch.v1',request.to_dict()['schema'])

    def test_request_denies_noncanonical_and_oversized_input(self):
        with self.assertRaises(ValueError):self.Request(**{**self.args,'operation_bytes':json.dumps(self.operation).encode()})
        with self.assertRaises(ValueError):self.Operation.parse({**self.operation,'payload':{**self.payload,'recipe_id':'r'*5000}})

    def test_unknown_policy_revision_or_variant_denies(self):
        from runtime.mission.sandbox_contracts import tool_variant
        for rev,cap in [(True,'SANDBOX_EXEC'),(999,'SANDBOX_EXEC'),(1,'SANDBOX_EXEC'),(2,'SYSTEM_INSTALL')]:
            with self.subTest(rev=rev,cap=cap),self.assertRaises(ValueError):tool_variant(rev,cap)
        self.assertEqual('synthetic',tool_variant(1,'PROJECT_WRITE').provider_id)
        self.assertEqual('sandbox-exec',tool_variant(2,'SANDBOX_EXEC').provider_id)
        self.assertEqual('SYNTHETIC_ONLY',tool_variant(2,'PROJECT_WRITE').mode)


    def test_exact_dispatch_preimage_and_immutable_request(self):
        request=self.Request(**self.args)
        self.assertEqual(canonical_sha256({'domain':'aioa.sandbox-dispatch.v1','request':request.to_dict()}),request.digest)
        value=request.to_dict();value['operation']['payload']['argv'][0]='/bin/sh'
        self.assertEqual('/usr/bin/python3.12',json.loads(request.operation_bytes)['payload']['argv'][0])
        with self.assertRaises(FrozenInstanceError):request.policy_epoch=2

    def test_resource_boundaries_reject_zero_negative_float_and_overflow(self):
        from runtime.mission.sandbox_contracts import RESOURCE_CEILINGS
        for field,maximum in RESOURCE_CEILINGS.items():
            for value in [0,-1,1.0,maximum+1]:
                with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                    self.Operation.parse({**self.operation,'payload':{**self.payload,field:value}})
        with self.assertRaises(ValueError):
            self.Operation.parse({**self.operation,'payload':{**self.payload,'cpu_period_us':99999}})

    def test_registry_rejects_duplicate_unknown_recipe_and_mutation(self):
        from runtime.mission.sandbox_contracts import SandboxRecipe,SandboxRegistry
        recipe=SandboxRecipe('tiny-python-v1','root-1','a'*64,'b'*64,'c'*64)
        registry=SandboxRegistry('workspace-1',(recipe,))
        with self.assertRaises(ValueError):SandboxRegistry('workspace-1',(recipe,recipe))
        with self.assertRaises(FrozenInstanceError):registry.workspace='other'
        with self.assertRaises(ValueError):registry.payload({'action':'run_recipe','recipe_id':'unknown','task_id':'task-1','step_id':'effect'})
        self.assertEqual(self.operation,registry.validate(self.operation).to_dict())
        for field,value in [('workspace','other'),('project_root_ref','root-2'),
                            ('sandbox_profile_digest','f'*64),('tool_input_digest','f'*64),
                            ('env_policy_digest','f'*64),('timeout_ms',4999)]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                registry.validate({**self.operation,'payload':{**self.payload,field:value}})

if __name__=='__main__':unittest.main()
