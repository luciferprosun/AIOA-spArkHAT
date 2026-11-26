"""Closed trusted Native composition data; existing Core routes perform all effects.

Offline candidates are finite advisory host data. This module owns no issuer,
executor, server, credential permission or model-to-command translation.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.mission.warrant import require


def startup_observation(owner, reader_capture):
    """One current signed READ of this graph; no health/approval/model grant."""
    from .native_authority import NativeAuthorityCapture
    f = owner.foundation
    require(f is not None and type(reader_capture) is NativeAuthorityCapture, "NATIVE_READ_CAPTURE_REQUIRED")
    f.access.require_capture(reader_capture, Capability.READ)
    f.require_bindings()
    def read(tx):
        f.access.require_capture(reader_capture, Capability.READ, tx=tx)
        governor = f.governor._load(tx)
        target = None
        if getattr(owner, 'portable_target', None) is not None:
            row, state = f.target_projection.load(tx)
            target = {'revision': row.revision, 'generation': state['generation'],
                      'history_digest': state['history_digest'], 'state_root': state['state_root'],
                      'in_flight': state['in_flight'] is not None}
        return governor, target
    governor, target = owner.runner.run(
        TransactionContext(
            reader_capture.principal, Capability.READ), read)
    physical = 'UNBOUND'
    if getattr(owner, 'portable_target', None) is not None:
        with owner.portable_target.target_guard():
            owner.portable_target.probe()
        physical = 'ADOPTED_CURRENT'
    ticks = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]
    observation = {
        'schema': 'aioa.native-startup-observation.v1', 'authority': 'NONE',
        'model_certification': 'NOT_CERTIFIED', 'host_source_sha': owner.source[0],
        'capsule_digest': owner.source[1], 'composition_digest': f.spec.digest,
        'startup_config_digest': f.spec.digest, 'pid': os.getpid(), 'process_start_ticks': ticks,
        'process': {'executable': Path(sys.executable).name, 'argv_digest': hashlib.sha256(json.dumps(sys.orig_argv).encode()).hexdigest(),
                    'isolated': bool(sys.flags.isolated), 'dont_write_bytecode': sys.dont_write_bytecode},
        'origin': owner.origin, 'listener': getattr(owner, '_native_listener_observation', None),
        'tls': {'qualified': owner.tls_verified is True, 'pin': getattr(owner, 'tls_pin', None),
                'expires_at': str(getattr(owner, '_tls_expires', None))},
        'admission': {'method': owner.operator_authentication['method'], 'instance_id': owner.instance_id,
                      'revision': reader_capture.assignment_revision, 'phase': f.lifecycle.phase.value,
                      'auth_deadline': str(owner._auth_deadline)},
        'coding_state': 'CONFIGURED' if getattr(owner, 'coding_tasks', None) is not None else 'UNBOUND',
        'governor': {'epoch': governor['epoch'], 'version': governor['version'],
                     'execution_capacity': governor.get('execution_capacity'), 'circuits': governor['circuits'],
                     'kill': governor['kill'], 'exposure': governor.get('exposure')},
        'portable_state': physical, 'target': target,
        'safe_effective_config': {'worker': 'UNBOUND' if owner._offline_candidates is None else 'OFFLINE_HOST',
                                  'model_calls': owner.model_calls(), 'external': 'DISABLED', 'aws': 'DISABLED',
                                  'guest_network': 'OFF', 'automatic_retry': False},
    }
    require(len(canonical_json_bytes(observation)) <= 32768, "NATIVE_STARTUP_OBSERVATION_BOUND")
    f.access.require_capture(reader_capture, Capability.READ)
    return {'observation': observation, 'signature': owner.identity.sign(observation)}


@dataclass(frozen=True, slots=True)
class NativeValidationPlan:
    preparer: object
    task: object
    root: Path
    patchset: object
    archive: bytes
    source: object
    profile_digest: str
    host_source: tuple
    session_id: str


class NativeStagePreparer:
    """One run's closed JIT plan; only the requested stage gets a Core job."""
    def __init__(self, host, task, cancel):
        from runtime.mission.worker import Task
        from runtime.providers.exact import CancellationToken
        require(type(host) is NativeCodingHost and type(task) is Task
                and type(cancel) is CancellationToken, 'NATIVE_STAGE_BINDING')
        self.host, self.task, self.cancel = host, task, cancel
        self._plans, self._requested = {}, set()
        self._lock = threading.RLock()

    def freeze(self, root, patchset, cancel):
        from runtime.mission.patchset import PatchSet
        from runtime.mission.repair_validation import pack_workspace
        h = self.host
        require(type(patchset) is PatchSet and cancel is self.cancel
                and patchset.task_id == self.task.task_id and patchset.run_id == self.task.run_id
                and patchset.task_digest == self.task.digest
                and patchset.worker_session_id in h.materializations
                and h.materializations[patchset.worker_session_id].task == self.task,
                'NATIVE_VALIDATION_PLAN_BINDING')
        h.project_probe()
        h.profile.validate_patch(patchset)
        root = Path(root)
        require(root.is_absolute() and root.is_relative_to(h.candidate_root), 'NATIVE_VALIDATION_ROOT')
        archive = pack_workspace(root, patchset)
        plan = NativeValidationPlan(self, self.task, root, patchset, archive, h.spec.project_source,
                                    h.profile.digest, h.owner.source, patchset.worker_session_id)
        with self._lock:
            require(len(self._plans) < 3, 'NATIVE_VALIDATION_PLAN_BOUND')
            self._plans[id(plan)] = plan
        return plan

    def prepare_stage(self, plan, stage, cancel):
        from runtime.mission.repair import TEST_STAGES
        from runtime.mission.repair_validation import pack_workspace
        from runtime.mission.sandbox_bindings import ObservationBindingInput
        with self._lock:
            require(type(plan) is NativeValidationPlan and self._plans.get(id(plan)) is plan
                    and plan.preparer is self and plan.task is self.task and cancel is self.cancel
                    and stage in TEST_STAGES and (id(plan), stage) not in self._requested,
                    'NATIVE_STAGE_SINGLE_USE')
            self._requested.add((id(plan), stage))
        require(not cancel.cancelled, 'NATIVE_STAGE_CANCELLED')
        h = self.host
        require(plan.host_source == h.owner.source and plan.profile_digest == h.profile.digest
                and plan.source == h.spec.project_source, 'NATIVE_STAGE_SOURCE_BINDING')
        h.project_probe()
        require(pack_workspace(plan.root, plan.patchset) == plan.archive, 'VALIDATION_TREE_CHANGED')
        spec = h.profile.observation_spec(stage, plan.archive, plan.patchset)
        return h.prepare_job(self.task, plan.session_id, stage, spec,
                             ObservationBindingInput(plan.patchset, plan.archive), cancel)


class NativeCodingHost:
    """Retained same-graph data and fixed existing factories, never an actuator."""
    def __init__(self, owner, candidates):
        self.owner, self.foundation, self.spec = owner, owner.foundation, owner.foundation.spec
        self.profile = self.spec.recipe
        body = self.spec.to_dict()
        self.base_root = Path(body['base_root'])
        self.candidate_root = Path(body['candidate_root'])
        self.source_repository = Path(body['source_repository'])
        self.git_target_repository = Path(body['git_target_repository'])
        self.seed_root = Path(body['sandbox_cache_root'])
        self.cache_root = self.seed_root.parent
        self.qualification_port = None
        self.candidates = candidates
        self.source_snapshot = self.spec.source_snapshot
        self.graph_complete = False
        self.lock, self.prepare_lock = threading.RLock(), threading.RLock()
        self.materializations, self.jobs, self.runs, self.effects = {}, {}, {}, {}

    @contextmanager
    def authority(self, purpose):
        from .native_authority import NativeAccessUse, NativePhase
        f = self.foundation
        use = NativeAccessUse.READ if purpose is Capability.READ else NativeAccessUse.EXECUTION
        if f.lifecycle.phase is not NativePhase.ACTIVE and purpose is not Capability.READ:
            use = NativeAccessUse.CONTROL
        if getattr(f.lifecycle._boundary, 'settlement_handle', None) is not None:
            use = NativeAccessUse.SETTLEMENT
        capture = f.access.capture(purpose, use=use)
        try:
            f.access.require_capture(capture, purpose)
            yield capture.principal
            f.access.require_capture(capture, purpose)
        finally:
            capture.close()

    def project_probe(self):
        with self.authority(Capability.READ):
            self.source_snapshot.verify(self.source_repository)
            self.source_snapshot.verify_export(self.base_root)
            return self.spec.project_source

    def sandbox_probe(self):
        from lab.archaioa.decision_root import DecisionDependencyRoot
        from lab.archaioa.evidence import EvidenceRef

        from runtime.mission.tools import TargetSnapshot
        source = self.spec.project_source
        return TargetSnapshot('sha256:' + source.base_tree_sha256, 'source-' + source.source_base_sha,
            DecisionDependencyRoot((EvidenceRef('native-host-source', 'context',
                'sha256:' + self.owner.source[1], self.owner.source[0]),
                EvidenceRef('native-project-source', 'context', 'sha256:' + source.base_tree_sha256,
                            source.source_base_sha))))

    def _ready_stage(self, task, cancel):
        f = self.foundation
        f.lifecycle.require_execution()
        while True:
            require(not cancel.cancelled, 'NATIVE_STAGE_CANCELLED')
            now = int(time.time())
            require(now + 30 < task.deadline_at, 'NATIVE_STAGE_DEADLINE')
            with self.authority(Capability.READ) as principal:
                state = f.governor.inspect(principal)
            require(state['kill'] is False, 'KILL_SWITCH')
            circuit = state['circuits'].get('sandbox-exec')
            if circuit is None or circuit['state'] != 'OPEN':
                return state['epoch']
            remaining = circuit['opened_at'] + f.governor.policy.cooldown_seconds - now
            if remaining <= 0:
                return state['epoch']
            require(now + remaining + 30 < task.deadline_at, 'NATIVE_STAGE_BACKPRESSURE_DEADLINE')
            # Cancel-aware bounded host waiting, never a retry of a released job.
            time.sleep(min(0.05, remaining))

    def prepare_job(self, task, session_id, stage, spec, binding_input, cancel):
        from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
        from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind

        from runtime.mission.completion import TaskCompletionBinding
        from runtime.mission.governor import ReservationRequest
        from runtime.mission.job_contracts import JobEnvelope
        from runtime.mission.repair_validation import PreparedValidationStep
        from runtime.mission.sandbox_contracts import SandboxOperation
        from runtime.mission.sandbox_linux import prepare_linux_sandbox
        from runtime.mission.tools import SessionGrant
        f = self.foundation
        epoch = self._ready_stage(task, cancel)
        self.project_probe()
        from .native_authority import _directory_identity
        require(_directory_identity(self.cache_root) == dict(f.root_observations)[str(self.cache_root)],
                'NATIVE_SANDBOX_PARENT_IDENTITY')
        identity = 'native-' + canonical_sha256((task.digest, session_id, stage,
                                                canonical_sha256({part: {name: hashlib.sha256(data).hexdigest()
                                                    for name, data in values.items()} for part, values in spec.items()})))[:40]
        with self.prepare_lock:
            require(identity not in self.jobs and len(self.jobs) < 64, 'NATIVE_STAGE_REPLAY_DENIED')
            retained = {'stage': stage, 'claim': None, 'warrant': None, 'uncertain': False}
            self.jobs[identity] = retained
            config = prepare_linux_sandbox(self.cache_root / identity, self.owner.broker.config.runtime(),
                workspace=task.workspace_id, recipes={'0': spec}, input_profile=self.profile.sandbox_input_profile)
            template = self.owner.broker.config.registry.recipes[0]
            config = replace(config, registry=replace(config.registry, recipes=tuple(replace(template,
                recipe_id=recipe.recipe_id, project_root_ref=recipe.project_root_ref,
                tool_input_digest=recipe.tool_input_digest) for recipe in config.registry.recipes)))
            capture = self.owner.broker.capture_config(config, binding_input=binding_input,
                                                       recipe_stages=(('0', stage),))
        require(_directory_identity(self.cache_root) == dict(f.root_observations)[str(self.cache_root)],
                'NATIVE_SANDBOX_PARENT_IDENTITY')
        require(not cancel.cancelled, 'NATIVE_STAGE_CANCELLED')
        route = self.owner.sandbox_route
        snapshot = self.sandbox_probe()
        operation = route.operation({'action': 'run_recipe', 'recipe_id': '0', 'task_id': identity,
                                      'step_id': 'effect'}, snapshot, sandbox_config=capture)
        trace = FaultTrace(FaultKind.LOST_ACK, identity, identity, 'sha256:' + canonical_sha256(operation))
        graph = DependencyGraph(identity, (DependencyNode('effect', NodeKind.OPERATION,
            liability_ids=(classify_fault(trace).liability_id,)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('effect',))))
        completion = TaskCompletionBinding.for_graph(f.ledger.scope, graph, 'completion')
        deadline = task.deadline_at
        envelope = JobEnvelope.for_offline_host(f.ledger.scope, identity, request_id=identity,
            request_digest=canonical_sha256((task.digest, session_id, stage)), deadline_at=deadline)
        try:
            with self.authority(Capability.MANAGE) as principal:
                binding = route.bind_sandbox_job(principal, capture, envelope=envelope,
                    completion=completion, operations=(SandboxOperation.parse(operation),))
            with self.authority(Capability.COMMIT) as principal:
                f.liability.initialize(principal, graph)
            with self.authority(Capability.MANAGE) as principal:
                f.governor.submit_job(principal, envelope, completion=completion, sandbox_binding_digest=binding.digest)
            require(not cancel.cancelled, 'NATIVE_STAGE_CANCELLED')
            with (self.authority(Capability.OWNER_APPROVAL) as owner_principal,
                  self.authority(Capability.COMMIT) as principal):
                retained['claim_requested_at'] = int(time.time())
                claim = f.governor.claim_job(principal, identity, 'native-offline-host', epoch, lease_seconds=60)
                retained['claim_returned_at'] = int(time.time())
                retained['claim'] = claim
                require(not cancel.cancelled, 'NATIVE_STAGE_CANCELLED')
                require(f.governor.begin_job(principal, claim)['local_step_now'], 'NATIVE_JOB_START_ACK_REQUIRED')
                now = int(time.time())
                grant = SessionGrant(identity, f.ledger.scope, task.workspace_id, 2, ('SANDBOX_EXEC',),
                                     completion.digest, now - 1, claim.lease_until, epoch, 1, 5, 20, 16384)
                route.create_session(owner_principal, grant)
                warrant = route.authorize(principal, identity, operation, completion, graph, trace,
                    nonce=identity, model_id='aioa/offline-host-worker-v1', money_nano=1, risk_units=5)
                retained['warrant'] = warrant
                step = PreparedValidationStep(stage, route, principal, {'session_id': identity, 'warrant': warrant,
                    'operation': operation, 'completion': completion,
                    'reservation': ReservationRequest(warrant.money_reservation_id, identity, 'sandbox-exec',
                        'aioa/offline-host-worker-v1', canonical_sha256(operation), 1, 5)})
            retained['step'] = step
            return step
        except BaseException:
            retained['uncertain'] = True
            raise

    def finish_step(self, step):
        f = self.foundation
        identity = step.arguments['completion'].task_id
        retained = self.jobs.get(identity)
        require(retained is not None and retained.get('step') is step
                and retained['warrant'] is step.arguments['warrant'], 'NATIVE_JOB_SETTLEMENT_BINDING')
        with self.authority(Capability.COMMIT) as principal:
            result = f.governor.finish_offline_host_job(principal, retained['claim'])
        retained['finished'] = True
        return result

    def job_observation(self):
        with self.authority(Capability.READ) as principal:
            return [self.foundation.governor.inspect_job(principal, identity) for identity in self.jobs]

    def run_factory(self, task, cancel):
        from runtime.mission.coding_tasks import CodingRun
        from runtime.mission.git_publish import _git_target_identity
        from runtime.mission.git_recipe import canonical, sha256
        from runtime.mission.repair import SandboxedCandidateProducer
        from runtime.mission.repair_validation import (
            CoreRepositoryMaterializer,
            CoreSandboxValidation,
        )
        from runtime.mission.sandbox_bindings import MaterializationBindingInput
        from runtime.mission.worker import SyntheticWorker
        self.foundation.lifecycle.require_execution()
        require(task.workspace_id == self.spec.project_source.workspace_id
                and task.repository_id == self.spec.project_source.repository_id
                and task.source_base_sha == self.spec.project_source.source_base_sha
                and int(time.time()) + 30 < task.deadline_at <= int(time.time()) + self.spec.to_dict()['limits_plan']['max_duration_seconds'],
                'NATIVE_TASK_CONFIG_BINDING')
        self.project_probe()
        preparer = NativeStagePreparer(self, task, cancel)
        def materialize(spec, _predicted, *, binding_input):
            require(type(binding_input) is MaterializationBindingInput and binding_input.task == task,
                    'NATIVE_MATERIALIZATION_BINDING')
            self.materializations[binding_input.session.session_id] = binding_input
            return self.prepare_job(task, binding_input.session.session_id, 'MATERIALIZE', spec, binding_input, cancel)
        materializer = CoreRepositoryMaterializer(self.foundation.intent_journal, materialize,
            profile=self.profile, source_snapshot=self.source_snapshot, source_repository=self.source_repository,
            base_root=self.base_root, output_root=self.candidate_root, cancel=cancel, sandbox_jobs=True)
        producer = SandboxedCandidateProducer(task, SyntheticWorker(self.candidates,
            model_id='offline-host-worker-v1'), materializer, cancel=cancel)
        validator = CoreSandboxValidation(self.foundation.intent_journal, stage_preparer=preparer,
            profile=self.profile, cancel=cancel, sandbox_jobs=True)
        target = 'sha256:' + sha256(canonical({'repository_id': self.source_snapshot.repository_id,
            'target_identity': _git_target_identity(self.git_target_repository), 'profile': 'DISPOSABLE_BARE_PATCH_V1'}))
        run = CodingRun(producer, validator, self.base_root, self.spec.project_source, target,
                        'git-' + self.source_snapshot.source_base_sha, task.deadline_at)
        self.runs[task.task_id] = run
        return run

    def git_target_guard(self):
        return self.lock

    def local_git_binding(self, task_id, capsule_digest):
        """Inert exact-plan data; only approve_local_patch writes an owner witness."""
        from decimal import Decimal

        from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
        from lab.archaioa.warrant import EffectWarrant, RevisionPolicy

        from runtime.mission.git_publish import CoreRemoteGitRoute
        from runtime.mission.governor import ReservationRequest
        from runtime.mission.patch_capsule import KIND as CAPSULE_KIND
        from runtime.mission.warrant import KIND as WARRANT_KIND
        from runtime.mission.warrant import approval_digest

        f, tasks = self.foundation, self.owner.coding_tasks
        require(type(task_id) is str and 0 < len(task_id) <= 96
                and type(capsule_digest) is str and len(capsule_digest) == 64
                and all(value in '0123456789abcdef' for value in capsule_digest),
                'NATIVE_GIT_PLAN_INPUT')
        key = task_id, capsule_digest
        nonce = 'native-git-' + capsule_digest[:40]
        with self.prepare_lock:
            f.require_bindings()
            retained = self.effects.get(key)
            if retained is not None:
                return retained[0]
            require(len(self.effects) < self.spec.to_dict()['limits_plan']['local_git_effects'],
                    'NATIVE_GIT_PLAN_BOUND')

            def read(tx):
                row = tx.get(RecordKind.OPERATION, canonical_sha256([CAPSULE_KIND, capsule_digest]))
                require(row is not None, 'CAPSULE_REQUIRED')
                capsule = tasks.capsules._decode(row)
                _, coding, task = tasks._load(tx, task_id)
                last = coding['receipts'][-1]['receipt']
                require(capsule.task_id == task.task_id == task_id
                        and capsule.task_digest == task.digest
                        and capsule.digest == last['capsule_digest'] == capsule_digest
                        and last['state'] in ('REVIEW_REQUIRED', 'APPROVED', 'APPLYING', 'UNKNOWN', 'VERIFIED'),
                        'NATIVE_GIT_CAPSULE_TASK')
                state = f.governor._load(tx)
                row = tx.get(RecordKind.OPERATION, canonical_sha256((WARRANT_KIND, f.ledger.scope, nonce)))
                existing = None
                if row is not None:
                    value = json.loads(canonical_json_bytes(row.payload))
                    existing = EffectWarrant.from_dict(value['active'])
                    _, _, existing = f.ledger._load(tx, existing)
                    require(existing.nonce == nonce, 'NATIVE_GIT_WARRANT_HISTORY')
                return capsule, task, last['state'], state, existing

            with self.authority(Capability.READ) as principal:
                capsule, task, coding_state, governor, existing = tasks._run(principal, Capability.READ, read)
            preparation = CoreRemoteGitRoute.prepare_patchset(self.base_root,
                self.candidate_root / ('candidate-' + capsule.worker_session_id),
                source=self.spec.project_source, task=task,
                worker_session_id=capsule.worker_session_id, capsule_digest=capsule.digest)
            port = self.qualification_port
            with self.authority(Capability.COMMIT) as principal:
                route = CoreRemoteGitRoute.for_local_patch(principal, f.intent_journal,
                    capsules=tasks.capsules, preparation=preparation, profile=self.profile,
                    source_snapshot=self.source_snapshot, source_repository=self.source_repository,
                    target_repository=self.git_target_repository, check=f.require_bindings,
                    target_guard=self.git_target_guard, native_access=f.access,
                    native_device_id=None if port is None else port.device_id,
                    native_stop_cas_gate=None if port is None else port.gate,
                    qualification_port=port)
            if existing is None:
                require(coding_state == 'REVIEW_REQUIRED' and route.historical_operation is None,
                        'NATIVE_GIT_WARRANT_HISTORY_REQUIRED')
                now = f.ledger.clock()
                end = datetime.fromtimestamp(min(capsule.expires_at, task.deadline_at,
                                                 int(now.timestamp()) + 300), UTC)
                require(now < end, 'CAPSULE_EXPIRED')
                epoch = governor['epoch']
                operation = route.operation(self.owner.instance_id, epoch)
                owner_scope = canonical_sha256(f.ledger.scope)
                scope = AuthorityScope(operation_classes=('GIT_COMMIT',),
                    target_scope=operation['target_fingerprint'], risk_ceiling=RiskLevel.MODERATE,
                    monetary_ceiling=Money(Decimal(0), 'USD'), not_before=now, expires_at=end,
                    owner_scope=owner_scope, task_scope=task_id)
                warrant = EffectWarrant(warrant_id=nonce, task_id=task_id, owner_scope=owner_scope,
                    operation_class='GIT_COMMIT', operation_hash='sha256:' + canonical_sha256(operation),
                    target_fingerprint=operation['target_fingerprint'],
                    expected_target_revision=operation['expected_target_revision'],
                    revision_policy=RevisionPolicy.REQUIRE, decision_dependency_root=route.dependency_root,
                    lease_epoch=epoch, authority_scope=scope, approval_digest='sha256:' + '0' * 64,
                    money_reservation_id='NONE',
                    risk_reservation_id=canonical_sha256(('native-local-git-effect', f.ledger.scope, nonce)),
                    nonce=nonce, issued_at=now, expires_at=end)
                warrant = replace(warrant, approval_digest=approval_digest(warrant))
            else:
                # Old timestamps/session approval are immutable history. A fresh
                # Native caller may inspect/reconcile, never renew that witness.
                warrant = existing
                operation = route.historical_operation or route.operation(self.owner.instance_id, warrant.lease_epoch)
            route._local_warrant(warrant, operation)
            reservation = ReservationRequest(warrant.risk_reservation_id, task_id, 'local-git',
                self.spec.to_dict()['accounting']['effect_model_binding_id'], canonical_sha256(operation), 0, 1)
            previous = governor['reservations'].get(reservation.request_id)
            if previous is not None:
                require(previous['binding_digest'] == canonical_sha256(reservation),
                        'NATIVE_GIT_RESERVATION_HISTORY')
            binding = route, warrant, reservation
            self.effects[key] = (binding, route.plan, route.capsule, route.source_repository,
                route.target_repository, route.check, route.owner_check, route.target_guard,
                canonical_json_bytes(route.historical_operation), port)
            try:
                f.require_bindings()
            except BaseException:
                self.effects.pop(key, None)
                raise
            return binding

    def effect_factory(self, task_id, capsule_digest):
        # Exact route binding is supplied below after a canonical signed capsule;
        # no arbitrary command/remote mode can be selected by callers.
        return self.local_git_binding(task_id, capsule_digest)


def require_native_graph(owner):
    from lab.archaioa.warrant import EffectWarrant
    from nonzero_cloudops.adapters.portable import PortableExecutor, PortableStateStore

    from runtime.mission.coding_tasks import CoreCodingTasks
    from runtime.mission.git_publish import CoreRemoteGitRoute
    from runtime.mission.governor import ReservationRequest
    from runtime.mission.patch_capsule import CorePatchCapsules
    from runtime.mission.portable_target import CorePortableTarget
    from runtime.mission.sandbox_linux import LinuxSandboxBroker
    from runtime.mission.tools import CoreToolRoute
    h, f = owner._native_coding, owner.foundation
    from types import MethodType
    require(type(h) is NativeCodingHost and h.owner is owner and h.foundation is f, 'NATIVE_SINGLE_GRAPH_REQUIRED')
    body = f.spec.to_dict()
    require(h.profile is f.spec.recipe and h.source_snapshot is f.spec.source_snapshot
            and h.base_root == Path(body['base_root']) and h.candidate_root == Path(body['candidate_root'])
            and h.source_repository == Path(body['source_repository'])
            and h.git_target_repository == Path(body['git_target_repository'])
            and h.seed_root == Path(body['sandbox_cache_root']) and h.cache_root == h.seed_root.parent
            and h.candidates == owner._offline_candidates, 'NATIVE_RETAINED_HOST_DATA')
    require(type(h) is NativeCodingHost and h.owner is owner and h.foundation is f
            and h.spec is f.spec and h.graph_complete
            and type(owner.coding_tasks) is CoreCodingTasks and owner.coding_tasks.native_access is f.access
            and owner.coding_tasks.journal is f.intent_journal
            and type(owner.coding_tasks.capsules) is CorePatchCapsules
            and owner.coding_tasks.capsules.identity is owner.identity
            and type(owner.broker) is LinuxSandboxBroker and type(owner.sandbox_route) is CoreToolRoute
            and owner.sandbox_route.executor is owner.broker and owner.sandbox_route.journal is f.intent_journal
            and owner.sandbox_route.liability is f.liability and owner.sandbox_route.native_access is f.access
            and type(owner.portable_store) is PortableStateStore and type(owner.portable_executor) is PortableExecutor
            and owner.portable_executor._state is owner.portable_store
            and type(owner.portable_target) is CorePortableTarget
            and owner.portable_target.store is owner.portable_store and owner.portable_target.executor is owner.portable_executor
            and owner.portable_target.projection is f.target_projection and owner.portable_target.native_access is f.access,
            'NATIVE_SINGLE_GRAPH_REQUIRED')
    for policy, route in ((4, owner.portable_release_route), (5, owner.portable_rearm_route)):
        require(type(route) is CoreToolRoute and route.policy_revision == policy and route.executor is owner.portable_target
                and route.journal is f.intent_journal and route.liability is f.liability
                and route.target_settlement is f.target_projection and route.native_access is f.access,
                'NATIVE_SINGLE_GRAPH_REQUIRED')
    for actual, method in ((owner.coding_tasks.run_factory, NativeCodingHost.run_factory),
                           (owner.coding_tasks.effect_factory, NativeCodingHost.effect_factory),
                           (owner.coding_tasks.capsules.source_probe, NativeCodingHost.project_probe),
                           (owner.sandbox_route.probe, NativeCodingHost.sandbox_probe),
                           (h.local_git_binding, NativeCodingHost.local_git_binding),
                           (h.git_target_guard, NativeCodingHost.git_target_guard)):
        require(type(actual) is MethodType and actual.__self__ is h and actual.__func__ is method,
                'NATIVE_RETAINED_FACTORY_BINDING')
    require(owner.broker.binding_policy is h.sandbox_policy and owner.broker.config is h.seed_config
            and owner.broker.binding_policy.recipe is h.profile
            and owner.broker.binding_policy.source_snapshot is h.source_snapshot
            and owner.broker.binding_policy.trusted_root is h.cache_root
            and owner.broker.binding_policy.source_repository is h.source_repository
            and owner.broker.binding_policy.base_root is h.base_root,
            'NATIVE_SANDBOX_POLICY_BINDING')
    require(type(h.effects) is dict, 'NATIVE_GIT_RETAINED_BINDING')
    for key, retained in tuple(h.effects.items()):
        require(type(key) is tuple and len(key) == 2 and type(retained) is tuple
                and len(retained) == 10 and type(retained[0]) is tuple and len(retained[0]) == 3,
                'NATIVE_GIT_RETAINED_BINDING')
        route, warrant, reservation = retained[0]
        require(type(route) is CoreRemoteGitRoute and type(warrant) is EffectWarrant
                and type(reservation) is ReservationRequest
                and route.plan is retained[1] and route.capsule is retained[2]
                and route.source_repository is retained[3] and route.target_repository is retained[4]
                and route.check is retained[5] and route.owner_check is retained[6]
                and route.target_guard is retained[7]
                and canonical_json_bytes(route.historical_operation) == retained[8]
                and route.qualification_port is h.qualification_port is retained[9]
                and (h.qualification_port is None or route.native_stop_cas_gate is h.qualification_port.gate)
                and route.journal is f.intent_journal and route.native_access is f.access
                and route.core is f.core and route.runner is f.runner and route.scope is f.ledger.scope
                and route.capsules is owner.coding_tasks.capsules and route.identity is owner.identity
                and route.test_profile is h.profile and route.plan.source is h.source_snapshot
                and route.source_repository == h.source_repository
                and route.target_repository == h.git_target_repository
                and route.mode == 'LOCAL_PATCH_FIXTURE'
                and (route.capsule.task_id, route.capsule.digest) == key
                and warrant.task_id == key[0] == reservation.task_id
                and reservation.request_id == warrant.risk_reservation_id
                and reservation.money_nano == 0 and reservation.risk_units == 1,
                'NATIVE_GIT_RETAINED_BINDING')
        for actual, owner_object, method in (
                (route.check, route, CoreRemoteGitRoute._historical_local_check
                 if route.historical_operation is not None else CoreRemoteGitRoute._local_check),
                (route.owner_check, f, type(f).require_bindings),
                (route.target_guard, h, NativeCodingHost.git_target_guard)):
            require(type(actual) is MethodType and actual.__self__ is owner_object
                    and actual.__func__ is method, 'NATIVE_GIT_RETAINED_BINDING')
    owner.broker.require_route_binding(owner.sandbox_route)


def bind_native_coding(owner, candidates):
    from nonzero_cloudops.adapters.portable import PortableExecutor, PortableStateStore

    from runtime.mission.coding_tasks import CoreCodingTasks
    from runtime.mission.patch_capsule import CorePatchCapsules
    from runtime.mission.portable_target import CorePortableTarget
    from runtime.mission.sandbox_bindings import TrustedSandboxBindingPolicy
    from runtime.mission.sandbox_linux import LinuxSandboxBroker, load_host_config
    from runtime.mission.tools import CoreToolRoute

    from .native_authority import NativePhase, _private_bytes
    f = owner.foundation
    require(f.lifecycle.phase is NativePhase.CONSTRUCTING and getattr(owner, '_native_coding', None) is None,
            'NATIVE_CONSTRUCTION_BINDING')
    h = NativeCodingHost(owner, candidates)
    owner._native_coding = h  # Retain partial ownership before the first resource.
    portable = f.spec.portable
    owner.portable_store = PortableStateStore(portable.inventory_path)
    owner.portable_store.assert_ready()
    owner.portable_executor = PortableExecutor(owner.portable_store, clock=lambda: datetime.now(UTC))
    owner.portable_target = CorePortableTarget(f.target_projection, owner.portable_store,
        executor=owner.portable_executor, clock=lambda: datetime.now(UTC), native_access=f.access)
    with owner.portable_store.target_guard():
        observed = owner.portable_store.observe_guarded_inventory()
        def adopted(tx):
            row, state = f.target_projection.load(tx)
            registration = tx.get(RecordKind.OPERATION,
                                  f.target_projection.registration_key)
            require(registration is not None and registration.payload['state'] == 'ADOPTED'
                    and registration.payload_digest == portable.registration_digest
                    and state['adoption_digest'] == portable.adoption_digest
                    and row.revision == portable.expected_head_revision and state['generation'] == portable.generation
                    and state['history_digest'] == portable.history_digest and state['in_flight'] is None
                    and (state['state_root'], state['resources_root'], state['receipts_root'])
                        == (observed.state_root, observed.resources_root, observed.receipts_root),
                    'NATIVE_ADOPTED_TARGET_REQUIRED')
        owner.runner.run(TransactionContext(owner.core.local_operator(Capability.READ), Capability.READ), adopted)
    body = f.spec.to_dict()
    seed_path = Path(body['sandbox_seed']['descriptor_path'])
    require(hashlib.sha256(_private_bytes(seed_path, 4194304)).hexdigest()
            == body['sandbox_seed']['descriptor_sha256'], 'NATIVE_SANDBOX_SEED_PIN')
    seed = load_host_config(seed_path.parent, trusted_root=h.cache_root)
    policy = TrustedSandboxBindingPolicy(h.cache_root, f.spec.project_source.workspace_id, seed.profile_digest,
        h.profile, h.source_snapshot, h.source_repository, h.base_root)
    h.seed_config, h.sandbox_policy = seed, policy
    owner.broker = LinuxSandboxBroker(seed, binding_policy=policy)
    owner.sandbox_route = CoreToolRoute(f.intent_journal, f.liability, workspace=f.spec.project_source.workspace_id,
        policy_revision=2, probe=h.sandbox_probe, executor=owner.broker, target_guard=lambda: h.lock,
        verifier=owner.broker.verify, variant='sandbox', sandbox_jobs=True, native_access=f.access)
    for policy_revision, name in ((4, 'portable_release_route'), (5, 'portable_rearm_route')):
        route = CoreToolRoute(f.intent_journal, f.liability, workspace=f.spec.project_source.workspace_id,
            policy_revision=policy_revision, probe=owner.portable_target.probe, executor=owner.portable_target,
            target_guard=owner.portable_target.target_guard, verifier=owner.portable_target.verify,
            variant='portable', target_settlement=f.target_projection, native_access=f.access)
        setattr(owner, name, route)
    capsules = CorePatchCapsules(f.intent_journal, owner.identity, source_probe=h.project_probe,
                                 target_guard=lambda: h.lock)
    owner.coding_tasks = CoreCodingTasks(f.intent_journal, capsules, run_factory=h.run_factory,
        effect_factory=h.effect_factory, native_access=f.access)
    h.graph_complete = True
    require_native_graph(owner)
