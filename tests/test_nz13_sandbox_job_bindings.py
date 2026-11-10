"""One existing Core/broker retains exact successive host-derived configs."""
import hashlib
import json
import os
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
        broker,route,_capture=self.managed()
        legacy=CoreToolRoute(self.journal,self.liability,workspace='workspace-1',policy_revision=2,
            probe=lambda:self.snapshot,executor=broker,target_guard=lambda:self.guard,clock=lambda:self.now,
            verifier=broker.verify,variant='sandbox',sandbox_registry=broker.config.registry)
        step,_handle,_claim=self.start(legacy,None,'legacy-history',bind=False)
        _operation,trace,graph,_completion,_envelope=self.parts(legacy,None,'legacy-history')
        def start(tx):
            self.journal.start_in_transaction(tx,step.arguments['warrant'],step.arguments['operation'],
                                               step.arguments['reservation'])
            self.liability.record_unknown_in_transaction(tx,trace,graph,datetime.fromtimestamp(self.now,UTC))
        legacy._run(self.p(),Capability.COMMIT,start)
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
