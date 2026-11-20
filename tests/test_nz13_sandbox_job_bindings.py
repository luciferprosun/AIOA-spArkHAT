"""One existing Core/broker retains exact successive host-derived configs."""
import hashlib
import json
import os
import stat
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from threading import RLock
from unittest.mock import patch

import test_nz11_general_recipe as recipe_support
from nz11_support import BareRepository

from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import (
    Capability,
    CoreAdmission,
    LocalOwnerAssignment,
    OwnerScope,
)
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.persistence.ports import (
    LocalCoreRecordFactory,
    LocalCoreTransaction,
    RecordKind,
    StoredRecord,
    TransactionRunner,
)
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import (
    CoreDualGovernor,
    GovernorPolicy,
    Limits,
    ReservationRequest,
)
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.job_contracts import JobEnvelope
from runtime.mission.liability import CoreLiabilityLedger
from runtime.mission.repair_validation import PreparedValidationStep, _pin_prepared_spec
from runtime.mission.sandbox_bindings import (
    BINDING_SCHEMA,
    BOUND_CONTEXT,
    MaterializationBindingInput,
    TrustedSandboxBindingPolicy,
    binding_key,
    read_binding,
)
from runtime.mission.sandbox_contracts import SandboxOperation
from runtime.mission.sandbox_linux import LinuxSandboxBroker, prepare_linux_sandbox
from runtime.mission.tools import CoreToolRoute, SessionGrant, TargetSnapshot
from runtime.mission.warrant import CoreWarrantLedger
from runtime.mission.worker import CandidateFile, CandidatePatch, WorkerSession
from runtime.providers.exact import CancellationToken

LOCAL_MODEL='aioa/offline-host-worker-v1'


class SandboxJobBindingTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(mkdtemp(prefix='sandbox-binding-',dir=os.environ['NZ13_NATIVE_TASK_FIXTURES']))
        self.scope=OwnerScope('owned-fixture','local-owner','one-native','same-slot')
        self.now=100
        self.core=CoreAdmission(LocalOwnerAssignment(self.scope,frozenset(Capability),
            frozenset({'workspace-1'}),frozenset({LOCAL_MODEL}),operator_approved=True))
        self.addCleanup(self.core.close)
        self.store=LocalCoreRecordFactory(self.root/'core.sqlite3',self.core)
        self.runner=TransactionRunner(self.core,self.store);self.addCleanup(self.runner.close)
        limits=Limits(1000,200)
        self.gov=CoreDualGovernor(self.core,self.runner,
            GovernorPolicy(self.scope,'task2-approved-fixture-budget',limits,limits,limits,
                           failure_threshold=getattr(self,'fixture_failure_threshold',24)),clock=lambda:self.now)
        self.epoch=self.gov.start_epoch(self.p(Capability.MANAGE))
        self.liability=CoreLiabilityLedger(self.core,self.runner,self.scope)
        self.ledger=CoreWarrantLedger(self.core,self.runner,self.scope,
            clock=lambda:datetime.fromtimestamp(self.now,UTC))
        self.journal=CoreIntentJournal(self.ledger,self.gov)
        self.guard=RLock()
        self.snapshot=TargetSnapshot('sha256:'+'d'*64,'owned-v1',DecisionDependencyRoot(()))
        source=recipe_support.GeneralRecipeTests('test_source_is_actual_git_commit_tree_and_independently_exported_bytes')
        source.root=self.root/'source';source.root.mkdir(mode=0o700)
        source.repo=BareRepository(source.root/'source.git',{'README.md':b'# Text utilities\n',
            'src/textutil.py':b'def slug(text):\n    return text.strip()\n',
            'tests/test_textutil.py':b'# Protected fixture tests.\n'})
        self.source_support=source
        self.source_snapshot,self.base,self.source,self.task,self.candidate,self.patch,self.archive=source.proposal()
        self.profile=source.profile()
        candidate_b=CandidatePatch((CandidateFile('src/textutil.py',
            'def slug(text):\n    return "-".join(text.lower().split()) + ""\n'),))
        self.candidates=(self.candidate,candidate_b)
        self.binding_inputs=tuple(MaterializationBindingInput(self.task,
            WorkerSession('worker-'+suffix,self.task.task_id,self.task.run_id,self.task.digest,'owned-worker'),candidate)
            for suffix,candidate in zip(('a','b'),self.candidates,strict=True))
        self.specs=tuple(self.profile.materialization_spec(self.base,source=self.source,task=item.task,
            worker_session_id=item.session.session_id,candidate=item.candidate)[2] for item in self.binding_inputs)
        runtime=self.root/'runtime';runtime.mkdir(mode=0o700)
        raw=Path('/usr/bin/python3.12').read_bytes()
        target=runtime/'python3.12';target.write_bytes(raw);target.chmod(0o500)
        self.manifest={'/usr/bin/python3.12':{'snapshot':str(target),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}}

    def p(self,purpose=Capability.COMMIT):
        return self.core.local_operator(purpose)

    def prepare(self,index):
        config=prepare_linux_sandbox(self.root/('config-'+str(index)),self.manifest,
            workspace='workspace-1',recipes={'0':self.specs[index]})
        return replace(config,registry=replace(config.registry,
            recipes=tuple(replace(r,timeout_ms=20000) for r in config.registry.recipes)))

    def route(self,broker):
        return CoreToolRoute(self.journal,self.liability,workspace='workspace-1',policy_revision=2,
            probe=lambda:self.snapshot,executor=broker,target_guard=lambda:self.guard,clock=lambda:self.now,
            verifier=broker.verify,variant='sandbox',sandbox_jobs=True)

    def managed(self,*,max_configs=32,max_jobs=64):
        config=self.prepare(0)
        policy=TrustedSandboxBindingPolicy(self.root,'workspace-1',config.profile_digest,self.profile,
            self.source_snapshot,self.source_support.repo.path,self.base,max_configs=max_configs,max_jobs=max_jobs)
        broker=LinuxSandboxBroker(config,binding_policy=policy)
        route=self.route(broker)
        capture=broker.capture_config(config,binding_input=self.binding_inputs[0],recipe_stages=(('0','MATERIALIZE'),))
        return broker,route,capture

    def parts(self,route,capture,identity,*,recipe_id='0'):
        operation=route.operation({'action':'run_recipe','recipe_id':recipe_id,'task_id':identity,'step_id':'effect'},
                                  self.snapshot,sandbox_config=capture)
        trace=FaultTrace(FaultKind.LOST_ACK,identity,identity,'sha256:'+canonical_sha256(operation))
        graph=DependencyGraph(identity,(DependencyNode('effect',NodeKind.OPERATION,
            liability_ids=(classify_fault(trace).liability_id,)),
            DependencyNode('completion',NodeKind.COMPLETION_CANDIDATE,('effect',))))
        completion=TaskCompletionBinding.for_graph(self.scope,graph,'completion')
        envelope=JobEnvelope.for_offline_host(self.scope,identity,request_id=identity,
            request_digest=canonical_sha256(('owned-offline',identity)),deadline_at=160)
        return operation,trace,graph,completion,envelope

    def bind(self,route,capture,parts):
        operation,_trace,_graph,completion,envelope=parts
        return route.bind_sandbox_job(self.p(Capability.MANAGE),capture,envelope=envelope,
            completion=completion,operations=(SandboxOperation.parse(operation),))

    def start(self,route,capture,identity,*,bind=True,recipe_id='0',stage='MATERIALIZE'):
        parts=self.parts(route,capture,identity,recipe_id=recipe_id)
        operation,trace,graph,completion,envelope=parts
        handle=self.bind(route,capture,parts) if bind else None
        self.liability.initialize(self.p(),graph)
        self.gov.submit_job(self.p(Capability.MANAGE),envelope,completion=completion,
                            sandbox_binding_digest=handle.digest if handle is not None else None)
        claim=self.gov.claim_job(self.p(),identity,'owned-host-worker',self.epoch,lease_seconds=60)
        self.assertTrue(self.gov.begin_job(self.p(),claim)['local_step_now'])
        grant=SessionGrant(identity,self.scope,'workspace-1',2,('SANDBOX_EXEC',),completion.digest,
            99,160,self.epoch,100,200,20,16384)
        route.create_session(self.p(Capability.OWNER_APPROVAL),grant)
        warrant=route.authorize(self.p(),identity,operation,completion,graph,trace,
            nonce=identity,model_id=LOCAL_MODEL,money_nano=1,risk_units=5)
        step=PreparedValidationStep(stage,route,self.p(),{'session_id':identity,
            'warrant':warrant,'operation':operation,'completion':completion,
            'reservation':ReservationRequest(warrant.money_reservation_id,identity,'sandbox-exec',
                LOCAL_MODEL,canonical_sha256(operation),1,5)})
        return step,handle,claim

    def test_R1_two_configs_retain_exact_job_registry(self):
        broker,route,first=self.managed()
        second_config=self.prepare(1)
        second=broker.capture_config(second_config,binding_input=self.binding_inputs[1],recipe_stages=(('0','MATERIALIZE'),))
        self.assertEqual(first.config.profile_digest,second.config.profile_digest)
        self.assertNotEqual(first.config_digest,second.config_digest)
        for index,capture in enumerate((first,second)):
            step,_handle,_claim=self.start(route,capture,'successive-'+str(index))
            _pin_prepared_spec(self.journal,step,self.specs[index])
            self.assertIs(capture.config,route.sandbox_config_for_operation(step.arguments['operation']))
        self.assertIs(first.config,broker.config)
        with self.assertRaises(AttributeError):broker.config=second.config

    def test_N01_immutable_and_idempotent_binding(self):
        broker,route,capture=self.managed()
        parts=self.parts(route,capture,'immutable')
        handle=self.bind(route,capture,parts)
        self.assertIs(handle,self.bind(route,capture,parts))
        self.assertEqual((canonical_json_bytes(parts[0]),),handle.operation_bytes)
        changed=list(parts);changed[4]=replace(parts[4],request_id='different-request')
        with self.assertRaisesRegex(ValueError,'REBIND'):self.bind(route,capture,changed)
        self.gov.submit_job(self.p(Capability.MANAGE),parts[4],completion=parts[3],sandbox_binding_digest=handle.digest)
        with self.assertRaisesRegex(ValueError,'AFTER_SUBMIT'):self.bind(route,capture,parts)
        self.assertEqual(handle.digest,broker._bindings['immutable'][0].digest)

    def test_N02_exact_owner_and_copied_capture_denied(self):
        broker,route,capture=self.managed()
        with self.assertRaisesRegex(ValueError,'OWNER'):self.route(broker)
        with self.assertRaisesRegex(ValueError,'CAPTURE_OWNER'):
            route.operation({'action':'run_recipe','recipe_id':'0','task_id':'copy','step_id':'effect'},
                            self.snapshot,sandbox_config=replace(capture))
        foreign=CoreAdmission(LocalOwnerAssignment(self.scope,frozenset(Capability),
            frozenset({'workspace-1'}),frozenset({LOCAL_MODEL}),operator_approved=True))
        self.addCleanup(foreign.close)
        parts=self.parts(route,capture,'foreign')
        with self.assertRaises(ValueError):
            route.bind_sandbox_job(foreign.local_operator(Capability.MANAGE),capture,
                envelope=parts[4],completion=parts[3],operations=(SandboxOperation.parse(parts[0]),))
        self.assertFalse(broker._bindings)

    def test_N03_N04_closed_producer_and_exact_source_spec(self):
        broker,_route,_capture=self.managed()
        config=self.prepare(1)
        for invalid in ({'task':self.task},self.candidate):
            with self.subTest(invalid=type(invalid).__name__),self.assertRaisesRegex(ValueError,'BINDING_INPUT'):
                broker.capture_config(config,binding_input=invalid,recipe_stages=(('0','MATERIALIZE'),))
        with self.assertRaisesRegex(ValueError,'STAGE'):
            broker.capture_config(config,binding_input=self.binding_inputs[1],recipe_stages=(('0','SHELL'),))
        with self.assertRaisesRegex(ValueError,'VALIDATION_INPUTS'):
            broker.capture_config(config,binding_input=self.binding_inputs[0],recipe_stages=(('0','MATERIALIZE'),))
        (self.base/'src/textutil.py').write_text('forged = True\n')
        with self.assertRaises(ValueError):
            broker.capture_config(config,binding_input=self.binding_inputs[1],recipe_stages=(('0','MATERIALIZE'),))
        self.assertFalse((config.root/'host-config.json').exists())

    def test_N05_private_link_and_root_identity_denials(self):
        broker,_route,capture=self.managed()
        os.link(capture.config.root/'host-config.json',self.root/'descriptor-hardlink')
        with self.assertRaisesRegex(ValueError,'PRIVATE_CACHE'):broker.revalidate_capture(capture)
        from runtime.mission.sandbox_bindings import root_member
        for name in ('..','/absolute','a/b','a\\b','a\n'):
            with self.subTest(name=name),self.assertRaises(ValueError):root_member(name)

    def test_N06_bound_field_and_raw_audit_joins(self):
        broker,route,capture=self.managed()
        parts=self.parts(route,capture,'canonical')
        before=self.gov.inspect(self.p(Capability.READ))
        handle=self.bind(route,capture,parts)
        self.assertEqual(before,self.gov.inspect(self.p(Capability.READ)))
        with self.assertRaisesRegex(ValueError,'BINDING_REQUIRED'):
            self.gov.submit_job(self.p(Capability.MANAGE),parts[4],completion=parts[3])
        key=binding_key(self.scope,self.gov.policy.deployment_id,'workspace-1','canonical')
        self.store.db.execute('DELETE FROM core_records_v1 WHERE kind=? AND record_id=?',
                              (RecordKind.OUTBOX.value,'sandbox-binding-proof-'+key))
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError,'BINDING_OUTBOX'):self.bind(route,capture,parts)
        self.assertEqual(handle.digest,broker._bindings['canonical'][0].digest)

    def test_N07_stale_claim_and_revoked_session(self):
        _broker,route,capture=self.managed()
        step,_handle,_claim=self.start(route,capture,'stale')
        self.now=161
        with self.assertRaises(ValueError):route.dispatch(step.principal,**step.arguments)
        self.assertEqual('STARTED',self.gov.inspect_job(self.p(Capability.READ),'stale')['state'])

    def test_N08_cross_job_and_cross_step_do_not_select_seed(self):
        broker,route,capture=self.managed()
        parts=self.parts(route,capture,'bound');self.bind(route,capture,parts)
        for field,value in (('task_id','unbound'),('step_id','other-step'),('tool_input_digest','a'*64)):
            operation=json.loads(canonical_json_bytes(parts[0]));operation['payload'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                route.sandbox_config_for_operation(operation)
        self.assertEqual(1,len(broker._bindings))

    def test_N09_stop_and_close_before_worker(self):
        broker,route,capture=self.managed()
        step,_handle,_claim=self.start(route,capture,'cancel')
        cancel=CancellationToken();cancel.cancel()
        with patch.object(broker,'_run',side_effect=AssertionError('worker called')):
            with self.assertRaisesRegex(ValueError,'CANCELLED'):
                route.dispatch(step.principal,**step.arguments,cancel=cancel)
            broker.close()
            with self.assertRaisesRegex(ValueError,'HISTORY_ONLY'):
                route.sandbox_config_for_operation(step.arguments['operation'])
        self.assertIs(capture.config,route.sandbox_config_for_operation(step.arguments['operation'],historical=True))

    def test_N10_restore_is_history_only_without_preparation(self):
        broker,route,capture=self.managed()
        step,handle,_claim=self.start(route,capture,'history')
        broker.close()
        restored=LinuxSandboxBroker(broker.config,binding_policy=broker.binding_policy)
        history_route=self.route(restored)
        with patch('runtime.mission.sandbox_linux.prepare_linux_sandbox',side_effect=AssertionError('prepare')):
            handles=history_route.restore_sandbox_bindings(self.p(Capability.READ),task_ids=('history',))
        self.assertEqual(('HISTORY_ONLY',handle.digest),(handles[0].mode,handles[0].digest))
        with self.assertRaisesRegex(ValueError,'HISTORY_ONLY'):
            history_route.sandbox_config_for_operation(step.arguments['operation'])
        self.assertEqual(capture.config_digest,restored._bindings['history'][1].config_digest)
        with self.assertRaises(ValueError):
            history_route.restore_sandbox_bindings(self.p(Capability.READ),task_ids=('absent',))

    def test_N11_quotas_do_not_evict_old_capture(self):
        broker,_route,capture=self.managed(max_configs=1)
        config=self.prepare(1)
        with self.assertRaisesRegex(ValueError,'CONFIG_QUOTA'):
            broker.capture_config(config,binding_input=self.binding_inputs[1],recipe_stages=(('0','MATERIALIZE'),))
        self.assertIs(capture,broker._captures[capture.config.root.name])

    def test_N12_registration_retry_callback_has_no_domain_io(self):
        broker,route,capture=self.managed()
        parts=self.parts(route,capture,'pure-callback')
        original=self.runner.run
        active=False
        observed=[]
        def guarded_run(context,callback):
            def checked(tx):
                nonlocal active
                active=True
                try:return callback(tx)
                finally:active=False
            return original(context,checked)
        def guard(name,method):
            def call(*args,**kwargs):
                self.assertFalse(active,'domain I/O inside transaction: '+name)
                observed.append(name)
                return method(*args,**kwargs)
            return call
        with patch.object(self.runner,'run',side_effect=guarded_run), \
             patch.object(broker,'revalidate_capture',side_effect=guard('capture',broker.revalidate_capture)), \
             patch.object(broker,'_source_check',side_effect=guard('source',broker._source_check)), \
             patch.object(broker,'publish_binding',side_effect=guard('publish',broker.publish_binding)):
            self.bind(route,capture,parts)
        self.assertIn('publish',observed)

    def test_addendum_raw_key_never_decodes_as_execution(self):
        _broker,route,capture=self.managed()
        parts=self.parts(route,capture,'raw-metadata');handle=self.bind(route,capture,parts)
        key=binding_key(self.scope,self.gov.policy.deployment_id,'workspace-1','raw-metadata')
        from runtime.memory_patch.persistence.idempotency import (
            OperationBinding,
            reconcile,
        )
        with self.assertRaisesRegex(MemoryPatchError,'IDEMPOTENCY_CONFLICT'):
            route._run(self.p(),Capability.COMMIT,lambda tx:reconcile(tx,
                OperationBinding.bind(key,'SANDBOX_JOB_CONFIG_BINDING',{'fake':'execution'})))
        value=route._run(self.p(Capability.READ),Capability.READ,lambda tx:read_binding(
            tx,self.scope,self.gov.policy.deployment_id,'workspace-1','raw-metadata',expected_digest=handle.digest))
        self.assertEqual(BINDING_SCHEMA,value['schema'])

    def test_managed_context_ddr_and_historical_job_version(self):
        _broker,route,capture=self.managed()
        step,handle,claim=self.start(route,capture,'context')
        context=route._run(self.p(Capability.READ),Capability.READ,lambda tx:route._context(tx,step.arguments['warrant'])[0])
        self.assertEqual((BOUND_CONTEXT,handle.digest,3),tuple(context[k] for k in ('schema','job_config_binding_digest','job_version')))
        self.assertEqual(claim.task_id,context['job_claim']['task_id'])
        kinds={ref.kind for ref in step.arguments['warrant'].decision_dependency_root.evidence_refs}
        self.assertIn('sandbox-job-binding',kinds)
        self.assertIn('sandbox-job-version',kinds)

    def test_R3_otherwise_valid_unbound_job_cannot_authorize(self):
        _broker,route,capture=self.managed()
        with self.assertRaisesRegex(ValueError,'SANDBOX_JOB_BINDING_REQUIRED'):
            self.start(route,capture,'missing-job-link',bind=False)
        self.assertEqual('STARTED',self.gov.inspect_job(self.p(Capability.READ),'missing-job-link')['state'])

    def test_addendum_serialization_retry_is_atomic_and_publishes_once(self):
        broker,route,capture=self.managed()
        parts=self.parts(route,capture,'retry')
        class SerializationFailure(Exception):
            sqlstate='40001'
        original=LocalCoreTransaction.commit
        calls=[]
        def retry_once(transaction):
            calls.append(1)
            if len(calls)==1:raise SerializationFailure()
            return original(transaction)
        with patch.object(LocalCoreTransaction,'commit',retry_once), \
             patch.object(broker,'publish_binding',wraps=broker.publish_binding) as publication:
            self.bind(route,capture,parts)
        self.assertEqual((2,1),(len(calls),publication.call_count))
        key=binding_key(self.scope,self.gov.policy.deployment_id,'workspace-1','retry')
        rows=route._run(self.p(Capability.READ),Capability.READ,lambda tx:tx.scan(RecordKind.AUDIT,limit=1024))
        self.assertEqual(1,sum(row.record_id=='sandbox-binding-audit-'+key for row in rows))

    def test_addendum_unknown_binding_commit_never_publishes_live(self):
        broker,route,capture=self.managed()
        parts=self.parts(route,capture,'unknown-commit')
        original=LocalCoreTransaction.commit
        def commit_unknown(transaction):
            original(transaction)
            raise CommitOutcomeUnknown()
        with patch.object(LocalCoreTransaction,'commit',commit_unknown), self.assertRaises(CommitOutcomeUnknown):
            self.bind(route,capture,parts)
        self.assertFalse(broker._bindings)
        with self.assertRaisesRegex(ValueError,'COMMIT_UNKNOWN'):self.bind(route,capture,parts)
        value=route._run(self.p(Capability.READ),Capability.READ,lambda tx:read_binding(
            tx,self.scope,self.gov.policy.deployment_id,'workspace-1','unknown-commit'))
        self.assertEqual('unknown-commit',value['task_id'])

    def test_addendum_shared_history_quota_is_not_filtered_away(self):
        _broker,route,capture=self.managed()
        parts=self.parts(route,capture,'quota')
        def fill(tx):
            count=len(tx.scan(RecordKind.OPERATION,limit=1024))
            for index in range(1024-count):
                tx.insert(StoredRecord(RecordKind.OPERATION,'owned-quota-'+str(index),self.scope,1,
                                       {'schema':'owned.inert.quota.v1'}))
        route._run(self.p(),Capability.COMMIT,fill)
        with self.assertRaisesRegex(ValueError,'HISTORY_QUOTA'):self.bind(route,capture,parts)

    def test_addendum_domain_outbox_remains_audit_only(self):
        _broker,route,capture=self.managed()
        parts=self.parts(route,capture,'audit-only');self.bind(route,capture,parts)
        key=binding_key(self.scope,self.gov.policy.deployment_id,'workspace-1','audit-only')
        from runtime.memory_patch.audit import _publication_payload, decode_audit
        def read(tx):
            event=decode_audit(tx.get(RecordKind.AUDIT,'sandbox-binding-audit-'+key))
            outbox=tx.get(RecordKind.OUTBOX,'sandbox-binding-proof-'+key)
            return _publication_payload(outbox,event)
        publication=route._run(self.p(Capability.READ),Capability.READ,read)
        self.assertEqual('DOMAIN_AUDIT_ONLY',publication['authority'])

    def test_N09_stop_during_last_core_check_denies_before_Y(self):
        broker,route,capture=self.managed()
        step,_handle,_claim=self.start(route,capture,'late-stop')
        token=CancellationToken();probes=[];would_release=[]
        def probe():
            probes.append(1)
            if len(probes)==4:token.cancel()
            return self.snapshot
        def worker(_request,release,_config_path,_run,_inputs,**_kwargs):
            try:release()
            except ValueError:pass
            else:would_release.append('Y')
            return {'cgroup_absent_after_cleanup':True,'unit_terminal_observed':True,
                    'cgroup_populated_zero_directly_observed':True}
        route.probe=probe
        with patch.object(broker,'_run',side_effect=worker):
            route.dispatch(step.principal,**step.arguments,cancel=token)
        self.assertTrue(token.cancelled)
        self.assertEqual([],would_release)

    def test_N02_second_live_broker_cannot_replace_owner_route(self):
        broker,_route,_capture=self.managed()
        other=LinuxSandboxBroker(broker.config,binding_policy=broker.binding_policy)
        with self.assertRaisesRegex(ValueError,'OWNER'):self.route(other)

    def test_N04_binding_implementation_is_in_approved_profile(self):
        _broker,_route,capture=self.managed()
        source=Path(__file__).resolve().parents[1]/'runtime/mission/sandbox_bindings.py'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         capture.config.profile().get('binding_source_sha256'))

    def test_N06_deleted_effect_context_keeps_reverse_join_denial(self):
        broker,route,capture=self.managed()
        first,_handle,_claim=self.start(route,capture,'unresolved-a')
        second,_handle,_claim=self.start(route,capture,'unresolved-b')
        with patch.object(broker,'_run',side_effect=ValueError('OWNED_UNKNOWN')):
            self.assertEqual('Unknown',route.dispatch(first.principal,**first.arguments)['outcome']['contract_type'])
        self.store.db.execute('DELETE FROM core_records_v1 WHERE kind=? AND record_id=?',
            (RecordKind.OPERATION.value,route._context_key(first.arguments['warrant'])))
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError,'TOOL_CONTEXT_REQUIRED'):
            route.dispatch(second.principal,**second.arguments)

    def test_N10_live_mapping_cannot_be_restored_as_an_execution_handle(self):
        _broker,route,capture=self.managed()
        self.start(route,capture,'still-live')
        with self.assertRaisesRegex(ValueError,'RESTORE_LIVE_DENIED'):
            route.restore_sandbox_bindings(self.p(Capability.READ),task_ids=('still-live',))

    def test_addendum_existing_legacy_context_survives_managed_metadata(self):
        config=self.prepare(0)
        earlier=LinuxSandboxBroker(config)
        legacy=CoreToolRoute(self.journal,self.liability,workspace='workspace-1',policy_revision=2,
            probe=lambda:self.snapshot,executor=earlier,target_guard=lambda:self.guard,clock=lambda:self.now,
            verifier=earlier.verify,variant='sandbox',sandbox_registry=earlier.config.registry)
        step,_handle,_claim=self.start(legacy,None,'legacy-history',bind=False)
        _operation,trace,graph,_completion,_envelope=self.parts(legacy,None,'legacy-history')
        def start(tx):
            self.journal.start_in_transaction(tx,step.arguments['warrant'],step.arguments['operation'],
                                               step.arguments['reservation'])
            self.liability.record_unknown_in_transaction(tx,trace,graph,datetime.fromtimestamp(self.now,UTC))
        legacy._run(self.p(),Capability.COMMIT,start)
        earlier.close()
        policy=TrustedSandboxBindingPolicy(self.root,'workspace-1',config.profile_digest,self.profile,
            self.source_snapshot,self.source_support.repo.path,self.base)
        broker=LinuxSandboxBroker(config,binding_policy=policy);route=self.route(broker)
        capture=broker.capture_config(config,binding_input=self.binding_inputs[0],recipe_stages=(('0','MATERIALIZE'),))
        self.bind(route,capture,self.parts(route,capture,'later-managed-metadata'))
        # Pure historical accounting can validate an older context while the
        # managed dispatch boundary still rejects an absent config identity.
        context=route._run(self.p(Capability.READ),Capability.READ,
                           lambda tx:route._context(tx,step.arguments['warrant'])[0])
        self.assertNotIn('job_config_binding_digest',context)

    def test_addendum_published_outbox_keeps_exact_binding_readable(self):
        _broker,route,capture=self.managed()
        parts=self.parts(route,capture,'published');handle=self.bind(route,capture,parts)
        key=binding_key(self.scope,self.gov.policy.deployment_id,'workspace-1','published')
        from runtime.memory_patch.audit import CorePublicationReceipt, mark_published
        def publish(tx):
            outbox=tx.get(RecordKind.OUTBOX,'sandbox-binding-proof-'+key)
            receipt=CorePublicationReceipt(outbox.record_id,outbox.payload['event_digest'],
                                           outbox.payload['operation_digest'],'a'*64)
            return mark_published(tx,outbox,receipt).revision
        self.assertEqual(2,route._run(self.p(),Capability.COMMIT,publish))
        value=route._run(self.p(Capability.READ),Capability.READ,lambda tx:read_binding(
            tx,self.scope,self.gov.policy.deployment_id,'workspace-1','published',expected_digest=handle.digest))
        self.assertEqual(handle.digest,canonical_sha256(value))

    def test_N07_epoch_above_one_and_later_epoch_denies_current_dispatch(self):
        self.epoch=self.gov.start_epoch(self.p(Capability.MANAGE))
        self.assertEqual(2,self.epoch)
        broker,route,capture=self.managed()
        step,_handle,claim=self.start(route,capture,'epoch-two')
        self.assertEqual(2,step.arguments['warrant'].lease_epoch)
        before=self.gov.inspect(self.p(Capability.READ))['reservations']
        self.gov.start_epoch(self.p(Capability.MANAGE))
        self.assertEqual(before,self.gov.inspect(self.p(Capability.READ))['reservations'])
        with patch.object(broker,'_run',side_effect=AssertionError('stale epoch worker')), \
             self.assertRaisesRegex(ValueError,'STALE_EPOCH'):
            route.dispatch(step.principal,**step.arguments)
        self.assertEqual(2,claim.governor_epoch)

    def test_FIX_I01_fresh_legacy_route_cannot_downgrade_managed_job(self):
        broker,route,capture=self.managed()
        step,_handle,_claim=self.start(route,capture,'managed-no-downgrade')
        operation,trace,graph,completion,_envelope=self.parts(route,capture,'managed-no-downgrade')
        before=tuple(self.store.db.execute('SELECT * FROM core_records_v1 ORDER BY scope_key,kind,record_id'))
        exposure=self.gov.inspect(self.p(Capability.READ))
        with patch.object(broker,'_run',side_effect=AssertionError('legacy worker')) as worker:
            with self.assertRaisesRegex(ValueError,'SANDBOX_MANAGED_ROUTE_REQUIRED'):
                legacy=CoreToolRoute(self.journal,self.liability,workspace='workspace-1',policy_revision=2,
                    probe=lambda:self.snapshot,executor=broker,target_guard=lambda:self.guard,clock=lambda:self.now,
                    verifier=broker.verify,variant='sandbox',sandbox_registry=broker.config.registry)
                legacy.authorize(self.p(),'managed-no-downgrade',operation,completion,graph,trace,
                    nonce='legacy-downgrade',model_id=LOCAL_MODEL,money_nano=1,risk_units=5)
            self.assertEqual(0,worker.call_count)
        self.assertEqual(before,tuple(self.store.db.execute('SELECT * FROM core_records_v1 ORDER BY scope_key,kind,record_id')))
        self.assertEqual(exposure,self.gov.inspect(self.p(Capability.READ)))
        self.assertEqual(3,route._run(self.p(Capability.READ),Capability.READ,
            lambda tx:route._context(tx,step.arguments['warrant'])[0])['job_version'])

    def test_FIX_I02_parent_swap_refused_before_foreign_read(self):
        for family in ('descriptor','input','runtime','artifact'):
            with self.subTest(family=family):self._parent_swap_case(family)

    def _parent_swap_case(self,family):
        from runtime.mission.sandbox_linux import _private_bytes
        owned=self.root/('race-'+family);owned.mkdir(mode=0o700)
        parent=owned/'parent';parent.mkdir(mode=0o700)
        foreign=owned/'foreign';foreign.mkdir(mode=0o700)
        leaf=parent/'payload';leaf.write_bytes(b'identical owned private bytes');leaf.chmod(0o600)
        other=foreign/'payload';other.write_bytes(leaf.read_bytes());other.chmod(0o600)
        self.assertEqual(hashlib.sha256(leaf.read_bytes()).digest(),hashlib.sha256(other.read_bytes()).digest())
        swapped=[];foreign_reads=[]
        original_resolve=Path.resolve;original_open=os.open;original_read=os.read
        foreign_identity=(other.stat().st_dev,other.stat().st_ino)
        def swap():
            if not swapped:
                parent.rename(owned/'retained-parent');parent.symlink_to(foreign,target_is_directory=True)
                swapped.append(family)
        def resolve(path,*args,**kwargs):
            result=original_resolve(path,*args,**kwargs)
            if path==leaf:swap()
            return result
        def open_file(path,*args,**kwargs):
            # Exercise the replacement reader's pinned-parent cut point,
            # too: no vacuous PASS when pathname resolve is removed.
            if path=='payload' and kwargs.get('dir_fd') is not None:swap()
            return original_open(path,*args,**kwargs)
        def read_file(fd,*args):
            info=os.fstat(fd)
            if (info.st_dev,info.st_ino)==foreign_identity:foreign_reads.append(family)
            return original_read(fd,*args)
        caught=None
        with patch.object(Path,'resolve',resolve),patch.object(os,'open',open_file),patch.object(os,'read',read_file):
            try:_private_bytes(leaf,owned,1024)
            except ValueError as error:caught=str(error)
        print('PARENT_SWAP',family,'exercised',len(swapped),'foreign_reads',len(foreign_reads),'denial',caught)
        self.assertEqual([family],swapped,'owned parent swap must actually execute')
        self.assertEqual([],foreign_reads,'foreign bytes must never be read')
        self.assertIsNotNone(caught)
        self.assertRegex(caught,'SANDBOX_CACHE_(PATH_DENIED|CHANGED)')


    def test_FIX_I03_private_reader_uid_denial_precedes_read(self):
        for family in ('descriptor','input','runtime','artifact'):
            with self.subTest(family=family):self._foreign_uid_case(family)

    def _foreign_uid_case(self,family):
        from runtime.mission.sandbox_linux import _private_bytes
        target=self.root/('uid-'+family);target.write_bytes(b'owned private bytes');target.chmod(0o600)
        identity=target.stat();original=os.fstat
        def foreign_uid(fd):
            info=original(fd)
            if (info.st_dev,info.st_ino)==(identity.st_dev,identity.st_ino):
                fields=list(info);fields[4]=os.getuid()+1;return os.stat_result(fields)
            return info
        with patch.object(os,'fstat',foreign_uid),patch.object(os,'read',wraps=os.read) as reader:
            with self.assertRaisesRegex(ValueError,'SANDBOX_PRIVATE_CACHE_REQUIRED'):
                _private_bytes(target,self.root,1024)
            self.assertEqual(0,reader.call_count)

    def test_FIX_I02_managed_receipt_parent_swap_refused_before_foreign_read(self):
        broker,route,capture=self.managed()
        step,handle,_claim=self.start(route,capture,'receipt-parent-race')
        operation,trace,graph,_completion,_envelope=self.parts(route,capture,'receipt-parent-race')
        def unknown(tx):
            self.journal.start_in_transaction(tx,step.arguments['warrant'],operation,step.arguments['reservation'])
            self.liability.record_unknown_in_transaction(tx,trace,graph,datetime.fromtimestamp(self.now,UTC))
        route._run(self.p(),Capability.COMMIT,unknown)
        request=route._run(self.p(Capability.READ),Capability.READ,
            lambda tx:route._historical_request(tx,operation,step.arguments['warrant']))
        run=capture.config.root/('run-'+request.digest);run.mkdir(mode=0o700)
        foreign=self.root/'foreign-receipt-cache';foreign.mkdir(mode=0o700)
        foreign_run=foreign/run.name;foreign_run.mkdir(mode=0o700)
        # Locator-only read fixture, never a fabricated Applied/kernel receipt.
        value={'request':request.to_dict(),'dispatch_digest':request.digest,
            'operation_digest':request.operation_digest,'warrant_digest':step.arguments['warrant'].digest(),
            'profile_digest':capture.config.profile_digest,'job_config_binding_digest':handle.digest,
            'config_digest':capture.config_digest}
        raw=canonical_json_bytes(value)
        for target in (run/'receipt.json',foreign_run/'receipt.json'):
            target.write_bytes(raw);target.chmod(0o600)
        self.assertEqual(raw,route.sandbox_receipt(self.p(Capability.READ),operation=operation,
            warrant=step.arguments['warrant'])[0])
        before=self._stored_rows();exposure=self.gov.inspect(self.p(Capability.READ))
        parent=capture.config.root;swapped=[];foreign_reads=[]
        foreign_info=(foreign_run/'receipt.json').stat()
        original_open=os.open;original_read=os.read
        def open_file(path,*args,**kwargs):
            if str(path) in (str(run),run.name) and not swapped:
                parent.rename(self.root/'retained-receipt-cache');parent.symlink_to(foreign,target_is_directory=True)
                swapped.append('managed-receipt')
            return original_open(path,*args,**kwargs)
        def read_file(fd,*args):
            info=os.fstat(fd)
            if (info.st_dev,info.st_ino)==(foreign_info.st_dev,foreign_info.st_ino):foreign_reads.append(1)
            return original_read(fd,*args)
        caught=None
        with patch.object(os,'open',open_file),patch.object(os,'read',read_file), \
             patch.object(broker,'_run',side_effect=AssertionError('receipt worker')) as worker:
            try:route.sandbox_receipt(self.p(Capability.READ),operation=operation,warrant=step.arguments['warrant'])
            except ValueError as error:caught=str(error)
            self.assertEqual(0,worker.call_count)
        print('MANAGED_RECEIPT_PARENT_SWAP','exercised',len(swapped),'foreign_reads',len(foreign_reads),'denial',caught)
        self.assertEqual(['managed-receipt'],swapped)
        self.assertEqual([],foreign_reads)
        self.assertIsNotNone(caught);self.assertRegex(caught,'SANDBOX_CACHE_(PATH_DENIED|CHANGED)')
        self.assertEqual(before,self._stored_rows());self.assertEqual(exposure,self.gov.inspect(self.p(Capability.READ)))

    def test_FIX_I02_owned_transit_preserves_private_input_compatibility(self):
        from runtime.mission.sandbox_linux import _private_bytes
        transit=self.root/'owned-transit';transit.mkdir(mode=0o700);transit.chmod(0o775)
        private=transit/'private-input';private.mkdir(mode=0o700)
        target=private/'snapshot';target.write_bytes(b'approved private retained input');target.chmod(0o600)
        self.assertEqual(b'approved private retained input',_private_bytes(target,self.root,1024))
        for component,mode in ((self.root,0o755),(private,0o755),(target,0o644)):
            previous=stat.S_IMODE(component.stat().st_mode)
            component.chmod(mode)
            try:
                with self.assertRaisesRegex(ValueError,'SANDBOX_PRIVATE_CACHE_REQUIRED'):
                    _private_bytes(target,self.root,1024)
            finally:component.chmod(previous)

    def test_FIX_I02_whole_root_identity_precedes_validation_and_restore(self):
        for mode in ('validation','restore'):
            with self.subTest(mode=mode):self._whole_root_identity_case(mode)

    def _whole_root_identity_case(self,mode):
        import runtime.mission.sandbox_linux as backend
        owned=SandboxJobBindingTests();owned.setUp()
        try:
            broker,route,capture=owned.managed()
            owned.start(route,capture,'root-identity')
            broker.revalidate_capture(capture)
            if mode=='restore':
                broker.close();broker=LinuxSandboxBroker(capture.config,binding_policy=broker.binding_policy)
                route=owned.route(broker)
                handles=route.restore_sandbox_bindings(owned.p(Capability.READ),task_ids=('root-identity',))
                self.assertEqual('HISTORY_ONLY',handles[0].mode)
            original=capture.config.root;replacement=owned.root/'replacement-root';replacement.mkdir(mode=0o700)
            members=['worker_gate','bootstrap','setup_filter.bpf','final_filter.bpf','host-config.json']
            for entry in capture.config.inputs().values():
                members.extend(str(Path(filename).relative_to(original)) for filename in entry['files'].values())
            foreign=set()
            for name in members:
                origin=original/name;raw=origin.read_bytes();target=replacement/name
                if target.parent!=replacement and not target.parent.exists():target.parent.mkdir(mode=0o700)
                target.write_bytes(raw);target.chmod(stat.S_IMODE(origin.stat().st_mode))
                self.assertEqual(hashlib.sha256(raw).digest(),hashlib.sha256(target.read_bytes()).digest())
                info=target.stat();foreign.add((info.st_dev,info.st_ino))
            initial=original.stat();replacement_inode=replacement.stat().st_ino
            before=owned._stored_rows();exposure=owned.gov.inspect(owned.p(Capability.READ))
            mappings=dict(broker._bindings);swapped=[];restored=[];foreign_reads=[]
            path_reader=backend._private_path;byte_reader=backend._private_bytes;read_file=os.read
            def swap():
                original.rename(owned.root/'retained-original-root');replacement.rename(original);swapped.append(1)
            def path_check(path,*args,**kwargs):
                info=path_reader(path,*args,**kwargs)
                if Path(path)==original and kwargs.get('directory') and not swapped:swap()
                return info
            def bytes_check(path,*args,**kwargs):
                if Path(path)==original/'host-config.json' and not swapped:swap()
                return byte_reader(path,*args,**kwargs)
            def read_check(fd,*args):
                info=os.fstat(fd)
                if (info.st_dev,info.st_ino) in foreign:
                    foreign_reads.append(1)
                    if not restored:
                        original.rename(owned.root/'retained-replacement-root')
                        (owned.root/'retained-original-root').rename(original);restored.append(1)
                return read_file(fd,*args)
            with patch.object(backend,'_private_path',side_effect=path_check if mode=='validation' else path_reader), \
                 patch.object(backend,'_private_bytes',side_effect=bytes_check if mode=='restore' else byte_reader), \
                 patch.object(os,'read',side_effect=read_check), \
                 patch.object(broker,'_run',side_effect=AssertionError('root worker')) as worker:
                with self.assertRaisesRegex(ValueError,'SANDBOX_(CAPTURE|CACHE)_CHANGED'):
                    if mode=='validation':broker.revalidate_capture(capture)
                    else:route.restore_sandbox_bindings(owned.p(Capability.READ),task_ids=('root-identity',))
                self.assertEqual(0,worker.call_count)
            self.assertEqual([1],swapped);self.assertNotEqual(initial.st_ino,replacement_inode)
            self.assertEqual([],foreign_reads,'root mismatch must deny before bytes, including ABA')
            self.assertEqual(before,owned._stored_rows());self.assertEqual(exposure,owned.gov.inspect(owned.p(Capability.READ)))
            self.assertEqual(mappings,broker._bindings)
            print('WHOLE_ROOT_DENIED',mode,'original_inode',initial.st_ino,'replacement_inode',replacement_inode,
                  'foreign_reads',len(foreign_reads),'worker',0,'Y',0,flush=True)
        finally:owned.doCleanups()

    def _stored_rows(self):
        return tuple(tuple(row) for row in self.store.db.execute(
            'SELECT * FROM core_records_v1 ORDER BY scope_key,kind,record_id'))

    def _replace_corrupt_row(self,kind,identity,change):
        from runtime.memory_patch.adapters.cockroach.repositories import (
            canonical_record,
        )
        row=self.store.db.execute('SELECT record_json FROM core_records_v1 WHERE kind=? AND record_id=?',
                                  (kind.value,identity)).fetchone()
        value=json.loads(row[0]);change(value)
        record=StoredRecord(RecordKind(value['kind']),value['record_id'],OwnerScope(**value['scope']),
                            value['revision'],value['payload'])
        self.store.db.execute('UPDATE core_records_v1 SET revision=?,record_json=?,record_digest=? WHERE kind=? AND record_id=?',
            (record.revision,canonical_record(record),record.payload_digest,kind.value,identity))
        self.store.db.commit()

    def _corrupt_audit_chain(self,identity,field,value):
        # Rehash the event and its descendants so event-type/content checks,
        # rather than an accidental stale event hash, remain exercised.
        rows=self.store.db.execute('SELECT record_id,record_json FROM core_records_v1 WHERE kind=?',
                                   (RecordKind.AUDIT.value,)).fetchall()
        rows=sorted(rows,key=lambda row:json.loads(row[1])['payload']['sequence_number'])
        previous=None
        for record_id,raw in rows:
            payload=json.loads(raw)['payload']
            if record_id==identity:
                if field.startswith('content_hashes.'):
                    payload['content_hashes'][field.split('.')[1]]=value
                else:payload[field]=value
            payload['previous_event_hash']=previous
            payload['event_hash']=canonical_sha256({k:v for k,v in payload.items() if k!='event_hash'})
            previous=payload['event_hash']
            self._replace_corrupt_row(RecordKind.AUDIT,record_id,lambda data,payload=payload:data.update(payload=payload))
            for proof_id,proof_raw in self.store.db.execute('SELECT record_id,record_json FROM core_records_v1 WHERE kind=?',
                                                          (RecordKind.OUTBOX.value,)).fetchall():
                if json.loads(proof_raw)['payload'].get('event_id')==record_id:
                    self._replace_corrupt_row(RecordKind.OUTBOX,proof_id,
                        lambda data,digest=previous:data['payload'].update(event_digest=digest))

    def test_FIX_I03_binding_history_corruption_matrix(self):
        cases=(
            'binding.remove','binding.kind','binding.scope','binding.revision','binding.content','binding.operation_digest',
            'audit.remove','audit.kind','audit.scope','audit.revision','audit.event_kind','audit.content','audit.operation_digest',
            'outbox.remove','outbox.kind','outbox.scope','outbox.revision','outbox.proof_id','outbox.event_id',
            'outbox.event_digest','outbox.operation_digest','outbox.extra_field','pending.core_hash','pending.revision2',
            'published.revision1','published.revision3','published.hash_none','published.hash_int',
            'published.hash_short','published.hash_nonhex','published.hash_prefixed','published.proof_id',
            'published.event_digest','published.operation_digest','published.scope','published.state')
        for name in cases:
            with self.subTest(corruption=name):self._binding_corruption_case(name)

    def _binding_corruption_case(self,name):
        owned=SandboxJobBindingTests();owned.setUp()
        try:
            broker,route,capture=owned.managed()
            step,handle,_claim=owned.start(route,capture,'corrupt-history')
            operation,trace,graph,_completion,_envelope=owned.parts(route,capture,'corrupt-history')
            def unknown(tx):
                owned.journal.start_in_transaction(tx,step.arguments['warrant'],operation,step.arguments['reservation'])
                owned.liability.record_unknown_in_transaction(tx,trace,graph,datetime.fromtimestamp(owned.now,UTC))
            route._run(owned.p(),Capability.COMMIT,unknown)
            exposure=owned.gov.inspect(owned.p(Capability.READ))
            key=binding_key(owned.scope,owned.gov.policy.deployment_id,'workspace-1','corrupt-history')
            audit='sandbox-binding-audit-'+key;proof='sandbox-binding-proof-'+key
            family,field=name.split('.')
            if family=='published':
                from runtime.memory_patch.audit import (
                    CorePublicationReceipt,
                    mark_published,
                )
                def publish(tx):
                    row=tx.get(RecordKind.OUTBOX,proof)
                    return mark_published(tx,row,CorePublicationReceipt(proof,row.payload['event_digest'],
                        row.payload['operation_digest'],'a'*64))
                route._run(owned.p(),Capability.COMMIT,publish)
            positive=route._run(owned.p(Capability.READ),Capability.READ,lambda tx:read_binding(
                tx,owned.scope,owned.gov.policy.deployment_id,'workspace-1','corrupt-history',expected_digest=handle.digest))
            self.assertEqual(handle.digest,canonical_sha256(positive))
            original=owned._stored_rows()
            kind={'binding':RecordKind.OPERATION,'audit':RecordKind.AUDIT}.get(family,RecordKind.OUTBOX)
            identity=key if family=='binding' else audit if family=='audit' else proof
            if field=='remove':
                owned.store.db.execute('DELETE FROM core_records_v1 WHERE kind=? AND record_id=?',(kind.value,identity))
                owned.store.db.commit()
            elif family=='audit' and field in ('event_kind','content','operation_digest'):
                target={'event_kind':'event_type','content':'content_hashes.content',
                        'operation_digest':'content_hashes.operation'}[field]
                owned._corrupt_audit_chain(audit,target,'OTHER_DOMAIN_EVENT' if field=='event_kind' else 'f'*64)
            else:
                def corrupt(data):
                    payload=data['payload']
                    if field=='kind':data['kind']=RecordKind.RECEIPT.value
                    elif field=='scope':data['scope']['owner_id']='foreign-owner'
                    elif field in ('revision','revision2','revision1','revision3'):
                        data['revision']={'revision':2,'revision2':2,'revision1':1,'revision3':3}[field]
                    elif family=='binding' and field=='content':payload['config_digest']='f'*64
                    elif family=='binding' and field=='operation_digest':payload['allowed_operations'][0]['operation_digest']='sha256:'+'f'*64
                    elif field in ('proof_id','event_id'):payload[field]='foreign-'+field
                    elif field in ('event_digest','operation_digest'):payload[field]='f'*64
                    elif field=='extra_field':payload['extra']='not-authority'
                    elif field in ('core_hash','hash_none'):payload['core_entry_hash']='a'*64 if field=='core_hash' else None
                    elif field=='hash_int':payload['core_entry_hash']=7
                    elif field=='hash_short':payload['core_entry_hash']='a'*63
                    elif field=='hash_nonhex':payload['core_entry_hash']='z'*64
                    elif field=='hash_prefixed':payload['core_entry_hash']='sha256:'+'a'*64
                    elif field=='state':payload['state']='PENDING'
                    else:raise AssertionError(name)
                owned._replace_corrupt_row(kind,identity,corrupt)
            corrupted=owned._stored_rows();self.assertNotEqual(original,corrupted)
            broker.close();restored=LinuxSandboxBroker(broker.config,binding_policy=broker.binding_policy)
            history=owned.route(restored)
            denial='SANDBOX_(JOB_BINDING_REQUIRED|BINDING_(INTEGRITY|AUDIT|OUTBOX))|PROVENANCE_CORRUPT|INTEGRITY_FAILED'
            with patch.object(restored,'_run',side_effect=AssertionError('corrupt worker')) as worker, \
                 patch.object(restored,'publish_binding',side_effect=AssertionError('corrupt LIVE')) as publication, \
                 patch.object(owned.gov,'claim_job',side_effect=AssertionError('corrupt claim')) as claims:
                with self.assertRaisesRegex((ValueError,MemoryPatchError),denial):
                    history._run(owned.p(Capability.READ),Capability.READ,lambda tx:read_binding(
                        tx,owned.scope,owned.gov.policy.deployment_id,'workspace-1','corrupt-history',expected_digest=handle.digest))
                with self.assertRaisesRegex((ValueError,MemoryPatchError),denial):
                    history.restore_sandbox_bindings(owned.p(Capability.READ),task_ids=('corrupt-history',))
                self.assertEqual((0,0,0),(worker.call_count,publication.call_count,claims.call_count))
            self.assertEqual(corrupted,owned._stored_rows(),'reader must not repair corrupt history')
            self.assertEqual(handle.record_bytes,broker._bindings['corrupt-history'][0].record_bytes)
            self.assertFalse(restored._bindings)
            # SQL equality includes governor exposure/reservations, all
            # job/claim/context/intent/liability history and audit rows.
            self.assertTrue(exposure['reservations'])
            print('CORRUPTION_DENIED',name,'root',owned.root,'rows',len(corrupted),'ACKS',0)
        finally:owned.doCleanups()

    def test_FIX_I03_exact_64_job_quota_retains_history(self):
        broker,route,capture=self.managed()
        handles=[]
        for index in range(64):
            parts=self.parts(route,capture,'quota-64-'+str(index));handles.append(self.bind(route,capture,parts))
        self.assertEqual(64,len(broker._bindings))
        before=self._stored_rows();exposure=self.gov.inspect(self.p(Capability.READ))
        with patch.object(broker,'_run',side_effect=AssertionError('quota worker')) as worker:
            with self.assertRaisesRegex(ValueError,'SANDBOX_JOB_QUOTA'):
                self.bind(route,capture,self.parts(route,capture,'quota-65-denied'))
            self.assertEqual(0,worker.call_count)
        self.assertEqual(before,self._stored_rows());self.assertEqual(exposure,self.gov.inspect(self.p(Capability.READ)))
        self.assertEqual(handles[0].digest,broker._bindings['quota-64-0'][0].digest)
        self.assertIs(handles[0],self.bind(route,capture,self.parts(route,capture,'quota-64-0')))
        self.assertEqual(before,self._stored_rows());self.assertEqual(64,len(broker._bindings))
        broker.close();history_broker=LinuxSandboxBroker(broker.config,binding_policy=broker.binding_policy)
        history=self.route(history_broker)
        for index in range(64):
            # The exact raw reader still validates every retained record; no
            # restoration of capacity or fabricated submit/claim is required.
            value=history._run(self.p(Capability.READ),Capability.READ,lambda tx,index=index:read_binding(
                tx,self.scope,self.gov.policy.deployment_id,'workspace-1','quota-64-'+str(index),expected_digest=handles[index].digest))
            self.assertEqual('quota-64-'+str(index),value['task_id'])
        self.assertEqual(before,self._stored_rows());self.assertFalse(history_broker._bindings)
        fresh=prepare_linux_sandbox(self.root/'after-close-config',self.manifest,workspace='workspace-1',recipes={'0':self.specs[0]})
        fresh=replace(fresh,registry=replace(fresh.registry,recipes=tuple(replace(recipe,timeout_ms=20000) for recipe in fresh.registry.recipes)))
        recaptured=history_broker.capture_config(fresh,binding_input=self.binding_inputs[0],recipe_stages=(('0','MATERIALIZE'),))
        with self.assertRaisesRegex(ValueError,'SANDBOX_JOB_QUOTA'):
            self.bind(history,recaptured,self.parts(history,recaptured,'quota-after-close-denied'))
        self.assertEqual(before,self._stored_rows());self.assertFalse(history_broker._bindings)


    def test_FIX_I03_restore_file_source_mutation_and_link_matrix(self):
        for family in ('descriptor','input','runtime','source'):
            for change in ('mutation','symlink','hardlink','parent_symlink','type','mode'):
                with self.subTest(family=family,change=change):
                    owned=SandboxJobBindingTests();owned.setUp()
                    try:
                        broker,route,capture=owned.managed()
                        _step,handle,_claim=owned.start(route,capture,'restore-file')
                        before=owned._stored_rows();exposure=owned.gov.inspect(owned.p(Capability.READ))
                        broker.revalidate_capture(capture)  # Independent positive control.
                        broker.close();restored=LinuxSandboxBroker(broker.config,binding_policy=broker.binding_policy)
                        history=owned.route(restored)
                        if family=='descriptor':target=capture.config.root/'host-config.json'
                        elif family=='input':target=Path(next(iter(capture.config.inputs()['0']['files'].values())))
                        elif family=='runtime':target=Path(next(iter(capture.config.runtime().values()))['snapshot'])
                        else:target=owned.base/'src/textutil.py'
                        raw=target.read_bytes();preserved=owned.root/'retained-original-file'
                        if change=='mutation':
                            preserved.write_bytes(raw);preserved.chmod(0o600)
                            mode=stat.S_IMODE(target.stat().st_mode)
                            self.assertEqual(raw,target.read_bytes());target.chmod(mode|0o200)
                            target.write_bytes(raw+b' ');target.chmod(mode)
                        elif change=='symlink':
                            target.rename(preserved);target.symlink_to(preserved)
                        elif change=='hardlink':os.link(target,preserved)
                        elif change=='parent_symlink':
                            parent=target.parent;retained=parent.with_name(parent.name+'-retained')
                            parent.rename(retained);parent.symlink_to(retained,target_is_directory=True)
                        elif change=='type':
                            target.rename(preserved);target.mkdir(mode=0o700)
                        elif change=='mode':target.chmod(0o666)
                        denial=('PATCHSET_[A-Z_]+|GIT_SOURCE_EXPORT_DRIFT' if family=='source' else
                                'SANDBOX_(CACHE_[A-Z_]+|PRIVATE_CACHE_REQUIRED|BINDING_INTEGRITY)|PINNED_(INPUT|RUNTIME)_CHANGED')
                        with patch('runtime.mission.sandbox_linux.prepare_linux_sandbox',side_effect=AssertionError('restore prepare')), \
                             patch.object(restored,'_run',side_effect=AssertionError('restore worker')) as worker, \
                             patch.object(restored,'publish_binding',wraps=restored.publish_binding) as publication:
                            with self.assertRaisesRegex(ValueError,denial):
                                history.restore_sandbox_bindings(owned.p(Capability.READ),task_ids=('restore-file',))
                            self.assertEqual(0,worker.call_count)
                            self.assertTrue(all(call.kwargs.get('historical') is True for call in publication.call_args_list))
                        self.assertEqual(before,owned._stored_rows());self.assertEqual(exposure,owned.gov.inspect(owned.p(Capability.READ)))
                        self.assertFalse(restored._bindings)
                        self.assertEqual(handle.record_bytes,broker._bindings['restore-file'][0].record_bytes)
                        print('RESTORE_FILE_DENIED',family,change,'positive_control',True,'root',owned.root,'ACKS',0,flush=True)
                    finally:owned.doCleanups()

    def test_FIX_I03_unfiltered_audit_1024_quota_does_not_append(self):
        from runtime.memory_patch.audit import domain_chain
        from runtime.memory_patch.contracts.serialization import to_canonical_data
        _broker,route,capture=self.managed()
        parts=self.parts(route,capture,'audit-limit');handle=self.bind(route,capture,parts)
        exposure=self.gov.inspect(self.p(Capability.READ))
        def fill(tx):
            events=domain_chain(tx);previous=events[-1]
            for index in range(len(events),1024):
                event=replace(previous,audit_event_id='owned-audit-quota-'+str(index),sequence_number=index,
                    previous_event_hash=previous.event_hash,resource_id='owned-audit-resource-'+str(index))
                tx.insert(StoredRecord(RecordKind.AUDIT,event.audit_event_id,self.scope,1,to_canonical_data(event)))
                previous=event
        route._run(self.p(),Capability.COMMIT,fill)
        before=self._stored_rows()
        with self.assertRaisesRegex(MemoryPatchError,'QUOTA_EXCEEDED'):
            route._run(self.p(Capability.READ),Capability.READ,lambda tx:read_binding(tx,self.scope,
                self.gov.policy.deployment_id,'workspace-1','audit-limit',expected_digest=handle.digest))
        with self.assertRaisesRegex(MemoryPatchError,'QUOTA_EXCEEDED'):
            self.bind(route,capture,self.parts(route,capture,'audit-overflow-denied'))
        self.assertEqual(before,self._stored_rows());self.assertEqual(exposure,self.gov.inspect(self.p(Capability.READ)))



class LowThresholdSandboxCircuitTests(unittest.TestCase):
    setUp=SandboxJobBindingTests.setUp
    p=SandboxJobBindingTests.p
    fixture_failure_threshold=3

    def test_ordinary_threshold_three_opens_before_fourth_release(self):
        releases=[]
        for index in range(3):
            identity='low-threshold-'+str(index)
            request=ReservationRequest(identity,identity,'owned-local-circuit',LOCAL_MODEL,
                                       canonical_sha256(identity),1,5)
            self.gov.reserve(self.p(),request,1)
            self.gov.dispatch_commit(self.p(),identity,1)
            self.gov.mark_unknown(self.p(),identity,1,canonical_sha256(('owned-unknown',identity)))
        self.assertEqual('OPEN',self.gov.inspect(self.p(Capability.READ))['circuits']['owned-local-circuit']['state'])
        with self.assertRaisesRegex(ValueError,'CIRCUIT_OPEN'):
            self.gov.reserve(self.p(),ReservationRequest('fourth','fourth','owned-local-circuit',LOCAL_MODEL,
                                                        canonical_sha256('fourth'),1,5),1)
            releases.append('unexpected release')
        self.assertEqual([],releases)
