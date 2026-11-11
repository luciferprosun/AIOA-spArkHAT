"""Explicit Native host composition, original call captures and capacity controls.

This module owns no Core issuer, signer, executor, approval store or transport.
Only trusted host construction can opt in; capacity administration never enables
project work. All filesystem/OS qualification precedes pure retry callbacks.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from runtime.core_admission import AdmissionError, Capability, CoreActor, CoreAdmission
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    TransactionContext,
    TransactionRunner,
)
from runtime.mission import execution_capacity as codec
from runtime.mission.governor import CoreDualGovernor, GovernorPolicy, Limits, _exposure
from runtime.mission.intent import INTENT_KINDS, CoreIntentJournal
from runtime.mission.liability import KIND as LIABILITY_KIND
from runtime.mission.liability import CoreLiabilityLedger
from runtime.mission.patchset import SourceIdentity
from runtime.mission.target_projection import CoreTargetProjection
from runtime.mission.target_settlement import TargetBinding
from runtime.mission.warrant import KIND as WARRANT_KIND
from runtime.mission.warrant import CoreWarrantLedger
from runtime.providers.coding_contracts import (
    CodingBackendRegistry,
    CodingContractError,
    SelectedCodingProfileV2,
)

if TYPE_CHECKING:
    from .runtime_adapter import NativeMobileComposition


CONFIG_FIELDS = {'schema', 'profile', 'host_source', 'bootstrap_policy_digest', 'base_root',
    'candidate_root', 'source_repository', 'git_target_repository', 'sandbox_cache_root',
    'project_source', 'source_snapshot', 'recipe', 'sandbox_seed', 'retained_sandbox_task_ids',
    'accounting', 'operations', 'portable', 'limits_plan'}
CAPACITY_FIELDS = {
    'native_access_status': {'op'},
    'governor_initialize': {'op', 'request_id', 'expected_version', 'expected_epoch',
        'bootstrap_policy_digest', 'composition_digest', 'source_sha', 'capsule_digest'},
    'execution_capacity_review': {'op', 'request_id', 'proposed'},
    'execution_capacity_approve': {'op', 'request_id', 'review_digest'},
    'execution_capacity_apply': {'op', 'request_id', 'review_digest', 'warrant_digest'},
    'execution_capacity_status': {'op', 'request_id'},
    'execution_capacity_abort': {'op', 'request_id'}}


def deny(condition):
    if not condition:
        raise AdmissionError()


def _private_bytes(path, maximum=2097152):
    """No-follow every component; only bounded single-link owner-private data."""
    path = _path(path)
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    fd = None
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            os.close(parent); parent = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        first = os.fstat(fd)
        deny(stat.S_ISREG(first.st_mode) and first.st_uid == os.getuid() and first.st_nlink == 1
             and not first.st_mode & 0o077 and first.st_size <= maximum)
        raw = b''
        while len(raw) <= maximum:
            chunk = os.read(fd, min(65536, maximum + 1 - len(raw)))
            if not chunk: break
            raw += chunk
        after = os.fstat(fd)
        named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        def identity(info):
            # Reading cold data may update atime; the file identity and content
            # metadata must remain stable across the complete guarded read.
            return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                    info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        deny(identity(first) == identity(after) == identity(named)
             and len(raw) == first.st_size)
        return raw
    finally:
        if fd is not None: os.close(fd)
        os.close(parent)


def _path(value):
    deny(type(value) in (str, Path) or isinstance(value, Path))
    text = str(value); path = Path(text)
    deny(path.is_absolute() and path != Path('/') and str(path) == text
         and '..' not in path.parts and '\\' not in text and '\x00' not in text)
    return path


def _host_bytes(value):
    # Private descriptors include locators. Public canonical records retain only
    # their digest; the existing canonical record path prohibition is unchanged.
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _directory_identity(path):
    path = _path(path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd); fd = child
        info = os.fstat(fd)
        deny(info.st_uid == os.getuid() and not info.st_mode & 0o077)
        return info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)
    finally:
        os.close(fd)


@dataclass(frozen=True, slots=True, repr=False)
class NativePortableBindingConfig:
    binding: TargetBinding
    inventory_path: Path
    registration_digest: str
    adoption_digest: str
    expected_head_revision: int
    generation: int
    history_digest: str
    resource_query: object

    @classmethod
    def from_dict(cls, value):
        from runtime.core_admission import OwnerScope
        from runtime.nonzero_cloudops.models.contracts import ResourceQuery
        codec.exact(value, {'binding', 'inventory_path', 'registration_digest', 'adoption_digest',
                            'expected_head_revision', 'generation', 'history_digest', 'resource_query'})
        binding = codec.exact(value['binding'], {'scope', 'workspace', 'target_id', 'incarnation', 'guard_fingerprint'})
        deny(type(binding['scope']) is list and len(binding['scope']) == 4
             and all(type(v) is str for v in binding['scope']))
        actual = TargetBinding(OwnerScope(*binding['scope']), binding['workspace'], binding['target_id'],
                               binding['incarnation'], binding['guard_fingerprint'])
        codec.exact(value['resource_query'], {'resource_type', 'resource_id', 'region'})
        deny(all(type(v) is str for v in value['resource_query'].values()))
        query = ResourceQuery.model_validate(value['resource_query'])
        deny(query.model_dump(mode='json') == value['resource_query'])
        for name in ('registration_digest', 'adoption_digest', 'history_digest'):
            codec.hexdigest(value[name])
        codec.integer(value['expected_head_revision'], 1)
        codec.integer(value['generation'])
        return cls(actual, _path(value['inventory_path']), value['registration_digest'], value['adoption_digest'],
                   value['expected_head_revision'], value['generation'], value['history_digest'], query)


@dataclass(frozen=True, slots=True, repr=False)
class NativeHostCompositionConfig:
    _bytes: bytes
    project_source: SourceIdentity
    source_snapshot: object
    recipe: object
    portable: NativePortableBindingConfig
    _descriptor_path: Path | None = None
    _descriptor_bytes: bytes | None = None
    coding_backend_registry: CodingBackendRegistry | None = None

    @classmethod
    def from_dict(cls, value):
        from runtime.mission.git_publish import GitSourceSnapshot
        from runtime.mission.project_recipe import (
            PythonFunctionCase,
            PythonRepositoryRecipe,
        )
        from runtime.mission.sandbox_contracts import PYTHON_ARGV
        v2 = type(value) is dict and value.get('schema') == 'aioa.native-host-composition.v2'
        codec.exact(value, CONFIG_FIELDS | {'coding_profiles'} if v2 else CONFIG_FIELDS)
        deny(value['schema'] in ('aioa.native-host-composition.v1', 'aioa.native-host-composition.v2')
             and value['profile'] == 'OWNED_OFFLINE_PROOF_V1')
        codec.exact(value['host_source'], {'source_sha', 'capsule_digest'})
        codec.hexdigest(value['host_source']['source_sha'], 40); codec.hexdigest(value['host_source']['capsule_digest'])
        registry = None
        if v2:
            profiles = value['coding_profiles']
            deny(type(profiles) is list and 1 <= len(profiles) <= 16)
            try:
                captured = tuple(SelectedCodingProfileV2.from_dict(profile) for profile in profiles)
                registry = CodingBackendRegistry(captured)
            except CodingContractError as error:
                raise AdmissionError() from error
            deny(all(profile.to_dict()['host_source'] == value['host_source'] for profile in captured))
        codec.hexdigest(value['bootstrap_policy_digest'])
        codec.exact(value['project_source'], set(SourceIdentity.__dataclass_fields__))
        project = SourceIdentity(**value['project_source'])
        snap = codec.exact(value['source_snapshot'], set(GitSourceSnapshot.__dataclass_fields__))
        deny(type(snap['files']) is list and 1 <= len(snap['files']) <= 256)
        files = []
        for row in snap['files']:
            deny(type(row) is list and len(row) == 2 and type(row[0]) is str and type(row[1]) is str)
            try: data = base64.b64decode(row[1].encode('ascii'), validate=True)
            except (ValueError, UnicodeError) as error: raise AdmissionError() from error
            deny(base64.b64encode(data).decode('ascii') == row[1])
            files.append((row[0], data))
        snapshot = GitSourceSnapshot(**{**snap, 'files': tuple(files)})
        deny(snapshot.repository_id == project.repository_id and snapshot.workspace_id == project.workspace_id
             and snapshot.source_base_sha == project.source_base_sha
             and snapshot.export_tree_sha256 == project.base_tree_sha256)
        r = codec.exact(value['recipe'], {'schema', 'repository_id', 'source_base_sha', 'allowed_paths',
                                          'import_roots', 'command', 'stages'})
        deny(r['schema'] == 'aioa.python-repository-recipe.v2'
             and r['command'] == list(PYTHON_ARGV) and type(r['command']) is list
             and type(r['allowed_paths']) is list and type(r['import_roots']) is list and type(r['stages']) is list)
        stages = []
        for stage in r['stages']:
            codec.exact(stage, {'stage', 'cases'}); deny(type(stage['cases']) is list)
            cases = []
            for case in stage['cases']:
                codec.exact(case, {'case_id', 'module', 'function', 'arguments', 'expected'})
                cases.append(PythonFunctionCase(case['case_id'], case['module'], case['function'],
                                                canonical_json_bytes(case['arguments']), canonical_json_bytes(case['expected'])))
            stages.append((stage['stage'], tuple(cases)))
        recipe = PythonRepositoryRecipe(r['repository_id'], r['source_base_sha'], tuple(r['allowed_paths']),
                                         tuple(r['import_roots']), tuple(stages), tuple(r['command']))
        deny(json.loads(recipe.manifest_bytes()) == r and recipe.repository_id == project.repository_id
             and recipe.source_base_sha == project.source_base_sha)
        roots = [_path(value[name]) for name in ('base_root', 'candidate_root', 'source_repository',
                                                'git_target_repository', 'sandbox_cache_root')]
        deny(all(type(value[name]) is str for name in ('base_root', 'candidate_root', 'source_repository',
                                                      'git_target_repository', 'sandbox_cache_root')))
        for index, root in enumerate(roots):
            deny(all(not root.is_relative_to(other) and not other.is_relative_to(root) for other in roots[:index]))
        codec.exact(value['sandbox_seed'], {'descriptor_path', 'descriptor_sha256'})
        codec.hexdigest(value['sandbox_seed']['descriptor_sha256'])
        deny(_path(value['sandbox_seed']['descriptor_path']) == roots[-1] / 'host-config.json')
        ids = value['retained_sandbox_task_ids']
        deny(type(ids) is list and len(ids) <= 64 and all(type(item) is str and 0 < len(item) <= 180 for item in ids)
             and ids == sorted(set(ids)))
        deny(value['accounting'] == {'job_model_id': 'aioa/offline-host-worker-v1', 'job_provider_id': 'offline-host',
                                     'effect_model_binding_id': 'aioa/offline-host-worker-v1'})
        deny(type(value['accounting']) is dict and type(value['operations']) is list
             and value['operations'] == ['GIT_COMMIT', 'PORTABLE_REARM_DEMO_V1', 'PORTABLE_RELEASE_ELASTIC_IP', 'SANDBOX_EXEC'])
        plan = codec.exact(value['limits_plan'], {'sandbox_effects', 'local_git_effects', 'portable_effects',
                                                 'max_duration_seconds', 'proposed_capacity'})
        for name, upper in (('sandbox_effects', 64), ('local_git_effects', 2), ('portable_effects', 2)):
            codec.integer(plan[name], 0, upper)
        codec.integer(plan['max_duration_seconds'], 1, 3600); codec.proposal(plan['proposed_capacity'])
        portable = NativePortableBindingConfig.from_dict(value['portable'])
        deny(portable.binding.workspace == project.workspace_id)
        deny(all(not portable.inventory_path.is_relative_to(root) and not root.is_relative_to(portable.inventory_path.parent)
                 for root in roots))
        raw = _host_bytes(value); deny(len(raw) <= 2097152)
        return cls(raw, project, snapshot, recipe, portable, coding_backend_registry=registry)

    @classmethod
    def load(cls, path):
        raw = _private_bytes(path)
        result = cls.from_dict(codec.strict_json(raw, maximum=2097152))
        object.__setattr__(result, '_descriptor_path', _path(path))
        object.__setattr__(result, '_descriptor_bytes', raw)
        return result

    def to_dict(self):
        return codec.strict_json(self._bytes, maximum=2097152)

    @property
    def digest(self):
        return hashlib.sha256(self._bytes).hexdigest()

    def coding_model_ids(self) -> frozenset[str]:
        """Pure eligibility from the retained full profiles; no selection or spend."""
        value = self.to_dict()
        registry = self.coding_backend_registry
        if registry is None:
            deny(value['schema'] == 'aioa.native-host-composition.v1' and 'coding_profiles' not in value)
            return frozenset()
        profiles = value.get('coding_profiles')
        deny(type(registry) is CodingBackendRegistry and value['schema'] == 'aioa.native-host-composition.v2'
             and type(profiles) is list and 1 <= len(profiles) <= 16)
        deny(registry._profiles == tuple(canonical_json_bytes(profile) for profile in profiles)
             and all(profile['host_source'] == value['host_source'] for profile in profiles))
        return frozenset(profile['model_id'] for profile in profiles)

    def observe(self, owner):
        """Host-owned source/config/root observations, never called in SQL."""
        value = self.to_dict()
        deny((value['host_source']['source_sha'],value['host_source']['capsule_digest']) == owner.source)
        if self._descriptor_path is not None:
            deny(_private_bytes(self._descriptor_path) == self._descriptor_bytes)
        roots = [Path(value[name]) for name in ('base_root', 'candidate_root', 'source_repository',
                                               'git_target_repository', 'sandbox_cache_root')]
        source_root = Path(__file__).absolute().parents[2]
        deny(all(not owner.root.is_relative_to(root) and not root.is_relative_to(owner.root)
                 and not root.is_relative_to(source_root) and not source_root.is_relative_to(root) for root in roots))
        deny(not self.portable.inventory_path.is_relative_to(owner.root))
        identities = tuple((str(root), _directory_identity(root)) for root in (*roots, self.portable.inventory_path.parent))
        self.source_snapshot.verify_export(roots[0])
        return identities


class NativeAccessUse(str, Enum):
    READ = 'READ'
    CONTROL = 'CONTROL'
    EXECUTION = 'EXECUTION'
    SETTLEMENT = 'SETTLEMENT'
    CAPACITY = 'CAPACITY'


class CapacityStage(str, Enum):
    REVIEW = 'REVIEW'
    APPROVE = 'APPROVE'
    APPLY = 'APPLY'


class NativePhase(str, Enum):
    CONSTRUCTING = 'CONSTRUCTING'
    CAPACITY_ADMIN = 'CAPACITY_ADMIN'
    ACTIVE = 'ACTIVE'
    FENCED = 'FENCED'
    DRAINING = 'DRAINING'
    QUARANTINED = 'QUARANTINED'
    CLOSED = 'CLOSED'


class _Original:
    __slots__ = ('_access', '_closed', '_facts')

    def __new__(cls, *_a, **_kw):
        raise TypeError('NATIVE_ORIGINAL_CAPTURE_REQUIRED')

    def __setattr__(self, _name, _value):
        raise TypeError('IMMUTABLE_NATIVE_CAPTURE')

    def __copy__(self):
        raise TypeError('NATIVE_CAPTURE_NOT_TRANSFERABLE')

    def __deepcopy__(self, _memo):
        raise TypeError('NATIVE_CAPTURE_NOT_TRANSFERABLE')

    def __reduce_ex__(self, _protocol):
        raise TypeError('NATIVE_CAPTURE_NOT_SERIALIZABLE')

    def close(self):
        self._access._close(self)


class NativeAuthorityCapture(_Original):
    __slots__ = (
        'admission_generation',
        'assignment_revision',
        'auth_deadline',
        'captured_at',
        'composition_digest',
        'composition_generation',
        'core',
        'fence_sequence',
        'instance_id',
        'ledger',
        'monotonic_at',
        'native_digest',
        'native_record_id',
        'native_revision',
        'owner',
        'pid',
        'principal',
        'purpose',
        'runner',
        'source',
        'thread_id',
        'tls_expires',
        'uid',
        'use',
        'work_handle',
    )

    def close(self) -> None:
        super().close()


class NativeCapacityFence(_Original):
    __slots__ = (
        'admission_generation',
        'composition_generation',
        'expires_at',
        'foundation',
        'instance_id',
        'pid',
        'request_id',
        'sequence',
        'work_generation',
    )


class NativeQuiescenceCapture(_Original):
    __slots__ = ('fence', 'foundation', 'pid', 'projection', 'thread_id', 'view')


class NativeCapacityHostCapture(_Original):
    __slots__ = (
        'applied_at',
        'authorities',
        'captured_at',
        'controller',
        'expires_at',
        'fence',
        'foundation',
        'pid',
        'quiescence',
        'review',
        'stage',
        'thread_id',
    )

    def require_live(self, stage, *, tx=None):
        self.controller.require_host(self, stage, tx=tx)

    def close(self):
        if not self._closed:
            for authority in self.authorities: authority.close()
            self.quiescence.close()
        super().close()


def _original(cls, access, **fields):
    value = object.__new__(cls)
    for name, item in {'_access': access, '_closed': False, **fields}.items():
        object.__setattr__(value, name, item)
    facts = tuple((name, item) for name, item in fields.items())
    object.__setattr__(value, '_facts', facts)
    access._register(value, facts)
    return value


@dataclass(frozen=True, slots=True, repr=False)
class NativeCapacityCoreView:
    _bytes: bytes

    def to_dict(self):
        return codec.core_view(codec.strict_json(self._bytes, maximum=2097152))

    @property
    def digest(self):
        return canonical_sha256(self.to_dict())

    @classmethod
    def read_in_transaction(cls, tx, foundation) -> NativeCapacityCoreView:
        from lab.archaioa.warrant import EffectWarrant
        from runtime.mission.jobs import KIND as JOB_KIND
        from runtime.mission.jobs import load_job
        deny(type(foundation) is NativeAuthorityFoundation)
        foundation.require_bindings()
        rows = tx.scan(RecordKind.OPERATION, limit=1024)
        deny(len(rows) < 1024)
        state = foundation.governor._load(tx)
        admission = foundation.access.native_row(tx)
        job_tasks, warrants = set(), {}
        from .agent_operations import KIND as AGENT_KIND
        from .agent_operations import STATES as AGENT_STATES
        from .mission_service import KIND as MISSION_KIND
        from .mission_service import MissionState
        for row in rows:
            row.verify()
            if row.payload.get('schema')==MISSION_KIND:
                deny(row.payload.get('state') in tuple(s.value for s in MissionState)
                     and row.payload.get('task_id')==row.record_id)
            if row.payload.get('schema')==AGENT_KIND:
                deny(row.payload.get('state') in AGENT_STATES and row.payload.get('task_id')==row.record_id)
            if row.payload.get('schema') == WARRANT_KIND:
                warrant = EffectWarrant.from_dict(codec.plain(row.payload['active']))
                _, _, active = foundation.ledger._load(tx, warrant)
                warrants[active.digest()] = active
            if row.payload.get('operation_kind') == JOB_KIND:
                job_tasks.add(row.payload['outcome']['job']['envelope']['task_id'])
        live_jobs = []
        for task in sorted(job_tasks):
            job = load_job(foundation.governor, tx, task)
            deny(job is not None)
            if job['state'] in ('CLAIMED', 'STARTED', 'UNKNOWN'): live_jobs.append(task)
        unresolved_intents, unresolved_liabilities = [], []
        target_rows = []
        for row in rows:
            schema = row.payload.get('schema')
            if schema in INTENT_KINDS:
                warrant = warrants.get(row.payload.get('warrant_digest'))
                deny(warrant is not None)
                _, intent = foundation.intent_journal._load(tx, warrant)
                if intent['resolution'] is None: unresolved_intents.append(row.record_id)
            if schema == LIABILITY_KIND:
                task = row.payload['graph']['task_id']
                _, liability = foundation.liability._load(tx, task)
                references = {identity for node in liability['graph']['nodes'] for identity in node['liability_ids']}
                deny(references <= set(liability['entries']))
                unresolved_liabilities.extend(identity for identity, entry in liability['entries'].items()
                                               if entry['record']['status'] != 'CLOSED')
            if type(schema) is str and schema.startswith('aioa-core-target-'):
                target_rows.append(row)
        flights = []
        if target_rows:
            projection = foundation.target_projection
            _, target = projection.load(tx)
            allowed = {projection.head_key, projection.genesis_key, projection.registration_key}
            deny(all(row.record_id in allowed or row.payload.get('target_key') == projection.head_key for row in target_rows))
            if target['in_flight'] is not None: flights.append(projection.target_id)
        deny(not any(c['state'] == 'HALF_OPEN' or c['probe'] is not None for c in state['circuits'].values()))
        legacy = foundation.owner.missions.retained_in_transaction(tx)
        live_jobs.extend(row.record_id for row in legacy if row.payload['state'] in ('RUNNING', 'UNKNOWN'))
        from . import agent_operations, github_write
        agents = agent_operations.retained_in_transaction(tx)
        live_jobs.extend(row.record_id for row in agents if row.payload['state'] in ('AGENT_RUNNING', 'AGENT_UNKNOWN'))
        github = github_write.retained_in_transaction(tx)
        live_jobs.extend(row.record_id for row in github if row.payload['state'] in (
            'GITHUB_PROPOSAL_READING', 'GITHUB_APPROVAL_PENDING', 'GITHUB_APPROVED', 'GITHUB_RUNNING',
            'GITHUB_RECONCILING', 'GITHUB_UNKNOWN'))
        value = {'schema': codec.CORE_VIEW_SCHEMA, 'governor_version': state['version'], 'governor_epoch': state['epoch'],
            'governor_state_digest': canonical_sha256(state), 'governor_exposure_digest': canonical_sha256(_exposure(state['reservations'])),
            'native_admission_record_digest': admission.payload_digest, 'live_job_ids': sorted(set(live_jobs)),
            'unresolved_reservation_ids': sorted(identity for identity, entry in state['reservations'].items()
                                                if entry['state'] in ('RESERVED', 'DISPATCHED', 'UNKNOWN')),
            'unresolved_intent_ids': sorted(set(unresolved_intents)), 'unresolved_liability_ids': sorted(set(unresolved_liabilities)),
            'in_flight_target_ids': sorted(set(flights))}
        return cls(canonical_json_bytes(codec.core_view(value)))

    def require_idle(self):
        value = self.to_dict()
        deny(all(not value[name] for name in ('live_job_ids', 'unresolved_reservation_ids', 'unresolved_intent_ids',
                                              'unresolved_liability_ids', 'in_flight_target_ids')))


@dataclass(slots=True, eq=False, repr=False)
class NativeOwnedWorkHandle:
    foundation: NativeAuthorityFoundation
    producer: object
    role: str
    task_id: str
    cancel: object
    thread: threading.Thread
    done: threading.Event
    started: bool = False
    broker: object = None
    target: object = None
    cleanup: object = None
    quarantined: bool = False
    synchronous: bool = False
    parent: object = None
    kind: str = ''
    context: tuple = ()
    returned: object = None


class NativeLifecycle:
    def __init__(self, foundation):
        self.foundation = foundation
        self.lock = threading.RLock()
        self._phase = NativePhase.CONSTRUCTING
        self.admission_generation = self.composition_generation = 1
        self.fence_sequence = self.work_generation = 0
        self._fence = None
        self._handles = {}
        self._roles = {}
        self._calls = set()
        self._capturing = 0
        self._renewing = 0
        self._boundary = threading.local()

    @property
    def phase(self):
        return self._phase

    def _snapshot(self):
        return self._phase, self.admission_generation, self.composition_generation, self.fence_sequence, self.work_generation

    def bind_producers(self):
        from .mission_service import MissionService
        from .runtime_adapter import NativeMobileComposition
        owner = self.foundation.owner
        deny(type(owner) is NativeMobileComposition and type(owner.missions) is MissionService)
        with self.lock:
            deny(self._phase is NativePhase.CONSTRUCTING and not self._roles)
            self._roles = {'LEGACY_MISSION': owner.missions, 'NATIVE_GITHUB': owner}
            owner.missions._native_foundation = self.foundation
            self._phase = NativePhase.CAPACITY_ADMIN

    def _coverage(self):
        owner = self.foundation.owner
        deny(self._roles == {'LEGACY_MISSION': owner.missions, 'NATIVE_GITHUB': owner}
             and self._roles['LEGACY_MISSION'] is owner.missions and self._roles['NATIVE_GITHUB'] is owner
             and owner.missions._native_foundation is self.foundation)
        deny(self._phase is NativePhase.CAPACITY_ADMIN)
        # Unknown or partially attached future domains cannot be called absent.
        deny(not any(getattr(owner, name, None) is not None for name in ('coding_tasks', 'broker', 'portable_executor'))
             and not hasattr(owner.missions, 'agent_route')
             and getattr(owner.runtime, '_coding_tasks', None) is None)
        for key, worker in tuple(owner.missions._workers.items()):
            handle = self._handles.get(key)
            deny(handle is not None and handle.thread is worker
                 and owner.missions._cancels.get(key) is handle.cancel)
        return [{'role': role, 'state': 'BOUND_IDLE' if role in self._roles else 'ABSENT_FENCED'} for role in codec.ROLES]

    @contextmanager
    def operator_call(self,operation):
        token=object()
        with self.lock:
            deny(len(self._calls)<64 and (self._phase is NativePhase.CAPACITY_ADMIN or
                 operation=='operator_auth_status' and self._phase is NativePhase.FENCED
                  or operation=='github_write_reconcile' and self._phase is NativePhase.ACTIVE))
            self._calls.add(token)
        try:yield
        finally:
            with self.lock:self._calls.remove(token)

    def require_ingress(self, operation):
        with self.lock:
            if operation=='github_write_reconcile':
                deny(self._phase in (NativePhase.CAPACITY_ADMIN,NativePhase.ACTIVE) and self._fence is None)
                return
            deny(self._phase is NativePhase.CAPACITY_ADMIN)
            if self._fence is not None:
                deny(operation in CAPACITY_FIELDS or operation == 'operator_auth_status')
            else:
                deny(operation in CAPACITY_FIELDS or operation in ('settings', 'status', 'enroll', 'revoke', 'operator_auth_status', 'operator_renew'))

    def require_execution(self):
        with self.lock:
            deny(self._phase is NativePhase.ACTIVE and self._fence is None)

    def begin_work(self, producer, role, task, cancel, thread, done):
        """Closed publication used by actual mission/GitHub hooks before claims."""
        deny(role in ('LEGACY_MISSION', 'NATIVE_GITHUB') and type(task) is str
             and type(thread) is threading.Thread and type(done) is threading.Event)
        with self.lock:
            deny(self._roles.get(role) is producer and self._phase is NativePhase.ACTIVE and self._fence is None
                 and task not in self._handles and len(self._handles) < 64)
            handle = NativeOwnedWorkHandle(self.foundation, producer, role, task, cancel, thread, done)
            self._handles[task] = handle; self.work_generation += 1
            return handle

    def before_start(self,handle):
        with self.lock:
            deny(type(handle) is NativeOwnedWorkHandle and self._handles.get(handle.task_id) is handle
                 and self._phase is NativePhase.ACTIVE and self._fence is None
                 and not handle.started and not handle.cancel.cancelled)
            handle.started=True

    def quarantine(self,handle):
        with self.lock:
            deny(type(handle) is NativeOwnedWorkHandle and self._handles.get(handle.task_id) is handle)
            handle.quarantined=True;self.work_generation+=1

    def begin_synchronous(self,producer,role,identity,cancel,*,parent=None):
        from runtime.providers.exact import CancellationToken
        deny(role in ('LEGACY_MISSION','NATIVE_GITHUB') and type(identity) is str
             and type(cancel) is CancellationToken)
        with self.lock:
            deny(self._roles.get(role) is producer and self._fence is None and identity not in self._handles
                 and len(self._handles)<64 and (self._phase is NativePhase.ACTIVE or
                    parent is not None and self._phase is NativePhase.CAPACITY_ADMIN
                    and self._handles.get(parent.task_id) is parent))
            handle=NativeOwnedWorkHandle(self.foundation,producer,role,identity,cancel,threading.current_thread(),
                threading.Event(),started=True,synchronous=True,parent=parent)
            self._handles[identity]=handle;self.work_generation+=1
            return handle

    def complete_synchronous(self,handle):
        # Positive completion is the return of this exact same source-owned
        # synchronous boundary, never thread death or a caller ACK boolean.
        deny(handle.synchronous and handle.thread is threading.current_thread())
        handle.done.set()
        with self.lock:
            deny(self._handles.get(handle.task_id) is handle and not handle.quarantined)
            handle.cleanup=('SYNCHRONOUS_BOUNDARY_RETURN',os.getpid(),threading.get_ident(),handle.done)
            del self._handles[handle.task_id];self.work_generation+=1

    def retire_work(self, handle):
        """Only the fixed actual producer observes return/join/terminal cleanup."""
        deny(type(handle) is NativeOwnedWorkHandle)
        with self.lock:
            if self._handles.get(handle.task_id) is not handle:return False
            if handle.synchronous or handle.quarantined:return False
        service=self.foundation.owner.missions
        cleanup=service._native_retirement_observation(handle)
        if cleanup is None:return False
        with self.lock:
            deny(self._handles.get(handle.task_id) is handle and handle.returned is cleanup[0]
                 and handle.thread is cleanup[1] and handle.cancel is cleanup[2] and handle.done is cleanup[3]
                 and service._workers.get(handle.task_id) is handle.thread
                 and service._cancels.get(handle.task_id) is handle.cancel and not handle.quarantined)
            handle.cleanup=cleanup
            del service._workers[handle.task_id];del service._cancels[handle.task_id]
            del self._handles[handle.task_id];self.work_generation+=1
            return True

    def invalidate_admission(self):
        with self.lock:
            self.admission_generation += 1
            self.fence_sequence += 1
            fence=self._fence
            self._fence = None
            if fence is not None:fence.close()
            if self._phase not in (NativePhase.CLOSED, NativePhase.DRAINING, NativePhase.QUARANTINED):
                self._phase = NativePhase.FENCED

    def begin_capacity_review(self, request_id: str) -> NativeCapacityFence:
        codec.hexdigest(request_id, 32)
        self.foundation.owner.missions._retire_native_workers()
        with self.lock:
            self._coverage()
            deny(self._fence is None and not self._handles)
            self.fence_sequence += 1
            f = _original(NativeCapacityFence, self.foundation.access, foundation=self.foundation, request_id=request_id,
                instance_id=self.foundation.owner.instance_id, admission_generation=self.admission_generation,
                composition_generation=self.composition_generation, sequence=self.fence_sequence,
                work_generation=self.work_generation, pid=os.getpid(), expires_at=datetime.now(UTC) + timedelta(seconds=300))
            self._fence = f
            return f

    def require_fence(self, fence):
        with self.lock:
            deny(type(fence) is NativeCapacityFence and self._fence is fence and not fence._closed
                 and fence.foundation is self.foundation and fence.pid == os.getpid()
                 and fence.instance_id == self.foundation.owner.instance_id
                 and fence.admission_generation == self.admission_generation
                 and fence.composition_generation == self.composition_generation
                 and fence.sequence == self.fence_sequence and fence.work_generation == self.work_generation
                 and datetime.now(UTC) < fence.expires_at)
            self.foundation.access._require_original(fence)
            self._coverage(); deny(not self._handles)

    def capture_quiescence(self, fence: NativeCapacityFence) -> NativeQuiescenceCapture:
        self.require_fence(fence)
        captures = getattr(self._boundary, 'authorities', None)
        deny(type(captures) is tuple and bool(captures))
        authority = captures[-1]
        self.foundation.access.require_capture(authority, authority.purpose)
        def read(tx):
            self.foundation.access.require_capture(authority, authority.purpose, tx=tx)
            self.require_fence(fence)
            view = NativeCapacityCoreView.read_in_transaction(tx, self.foundation)
            self.foundation.access.require_capture(authority, authority.purpose, tx=tx)
            return view
        view = self.foundation.runner.run(TransactionContext(authority.principal, authority.purpose), read)
        view.require_idle()
        with self.lock:
            self.require_fence(fence)
            projection = {'schema': codec.QUIESCENCE_SCHEMA, 'instance_id': fence.instance_id,
                'admission_generation': self.admission_generation, 'composition_generation': self.composition_generation,
                'fence_sequence': self.fence_sequence, 'work_generation': self.work_generation,
                'role_coverage': self._coverage(), 'owned_work_ids': [], 'quarantined_work_ids': [], 'core_view_digest': view.digest}
            return _original(NativeQuiescenceCapture, self.foundation.access, foundation=self.foundation, fence=fence,
                view=view, projection=canonical_json_bytes(codec.quiescence(projection)), pid=os.getpid(), thread_id=threading.get_ident())

    def abort(self, fence):
        with self.lock:
            deny(self._fence is fence)
            self.fence_sequence += 1; self._fence = None
            fence.close()

    def drain(self):
        self.foundation.owner.missions._retire_native_workers()
        with self.lock:
            if self._phase is NativePhase.CLOSED: return True
            owner=self.foundation.owner
            if (self._phase is NativePhase.CONSTRUCTING
                    or self._roles.get('LEGACY_MISSION') is not owner.missions
                    or self._roles.get('NATIVE_GITHUB') is not owner):
                self.invalidate_admission()
                self._phase=NativePhase.QUARANTINED
                return False
            self.invalidate_admission(); self._phase = NativePhase.DRAINING
            handles = tuple(self._handles.values())
            active = bool(self._calls or self._capturing or self._renewing or self.foundation.access._originals)
            workers = tuple(self.foundation.owner.missions._workers.values())
        for handle in handles: handle.cancel.cancel()
        # No joins or OS/process observations under the lifecycle lock.
        alive = any(worker.is_alive() for worker in workers)
        with self.lock:
            if active or handles or alive:
                self._phase = NativePhase.QUARANTINED
                return False
            return True


class NativeCoreAccess:
    def __init__(self, foundation):
        self.foundation = foundation
        self._originals = {}

    def _register(self, value, facts):
        with self.foundation.lifecycle.lock:
            deny(len(self._originals) < 64 and id(value) not in self._originals)
            self._originals[id(value)] = [value, facts, datetime.now(UTC), time.monotonic()]

    def _require_original(self, value):
        registered = self._originals.get(id(value))
        deny(registered is not None and registered[0] is value and not value._closed
             and value._access is self and value._facts is registered[1])
        for name, item in registered[1]:
            current = getattr(value, name)
            if type(item) in (str, int, float, tuple, datetime, Capability, NativeAccessUse, CapacityStage):
                deny(type(current) is type(item) and current == item)
            else:
                deny(current is item)

    def _close(self, value):
        with self.foundation.lifecycle.lock:
            registered = self._originals.get(id(value))
            if registered is not None:
                deny(registered[0] is value)
                self._originals.pop(id(value))
            object.__setattr__(value, '_closed', True)

    def native_row(self, tx):
        from runtime.mobile_gateway.service import SCHEMA
        owner = self.foundation.owner
        row = tx.get(RecordKind.OPERATION, 'mobile-operator-' + owner.instance_id)
        deny(row is not None and row.scope == self.foundation.ledger.scope)
        row.verify(); value = codec.plain(row.payload)
        fields = {'schema', 'state', 'authentication', 'source_sha', 'capsule_digest', 'core_instance_id'}
        deny(set(value) in (fields, fields | {'policy_epoch'}) and value['schema']==SCHEMA
             and value['state'] == 'MOBILE_OPERATOR_ADMISSION'
             and (value['source_sha'], value['capsule_digest']) == owner.source
             and value['core_instance_id'] == owner.instance_id
             and value['authentication'] == owner.operator_authentication)
        return row

    def capture(self, purpose: Capability, *, use: NativeAccessUse) -> NativeAuthorityCapture:
        deny(type(purpose) is Capability and type(use) is NativeAccessUse)
        f = self.foundation; owner = f.owner; lifecycle = f.lifecycle
        with lifecycle.lock:
            settlement=getattr(lifecycle._boundary,'settlement_handle',None)
            if use is NativeAccessUse.SETTLEMENT:
                deny(type(settlement) is NativeOwnedWorkHandle and lifecycle._handles.get(settlement.task_id) is settlement
                     and settlement.parent is not None and lifecycle._handles.get(settlement.parent.task_id) is settlement.parent
                     and settlement.thread is threading.current_thread()
                     and settlement.kind in ('AGENT_SETTLEMENT','GITHUB_SETTLEMENT')
                     and settlement.parent.foundation is f and purpose in (Capability.READ,Capability.COMMIT)
                     and lifecycle._fence is None)
            deny((lifecycle.phase is NativePhase.CAPACITY_ADMIN or
                  use is NativeAccessUse.SETTLEMENT and lifecycle.phase is NativePhase.ACTIVE) and not owner._closed
                 and purpose in (Capability.READ, Capability.MANAGE, Capability.COMMIT, Capability.OWNER_APPROVAL)
                 and use in (NativeAccessUse.READ, NativeAccessUse.CONTROL, NativeAccessUse.CAPACITY, NativeAccessUse.SETTLEMENT)
                 and len(self._originals) + lifecycle._capturing < 64)
            expected = lifecycle._snapshot(); lifecycle._capturing += 1
        try:
            owner._require_qualified_operator()
            deny(os.getuid() == owner.uid and f.spec.observe(owner) == f.root_observations)
            f.require_bindings()
            captured_at, monotonic_at = datetime.now(UTC), time.monotonic()
            principal = owner.core.local_operator(purpose)
            row = owner.runner.run(TransactionContext(principal, purpose), self.native_row)
            with lifecycle.lock:
                deny(expected == lifecycle._snapshot() and not owner._closed
                     and (lifecycle.phase is NativePhase.CAPACITY_ADMIN or use is NativeAccessUse.SETTLEMENT and lifecycle.phase is NativePhase.ACTIVE))
                return _original(NativeAuthorityCapture, self, owner=owner, core=owner.core, runner=owner.runner,
                    ledger=owner.ledger, principal=principal, purpose=purpose, use=use, instance_id=owner.instance_id,
                    assignment_revision=principal.assignment_revision, admission_generation=lifecycle.admission_generation,
                    composition_generation=lifecycle.composition_generation, fence_sequence=lifecycle.fence_sequence,
                    native_record_id=row.record_id, native_revision=row.revision, native_digest=row.payload_digest,
                    source=owner.source, composition_digest=f.spec.digest, captured_at=captured_at, monotonic_at=monotonic_at,
                    auth_deadline=owner._auth_deadline, tls_expires=owner._tls_expires, pid=os.getpid(),
                    thread_id=threading.get_ident(), work_handle=settlement, uid=owner.uid)
        finally:
            with lifecycle.lock: lifecycle._capturing -= 1

    def require_capture(self, capture: NativeAuthorityCapture, purpose: Capability, *, tx=None) -> None:
        deny(type(capture) is NativeAuthorityCapture and type(purpose) is Capability)
        f = self.foundation; owner = f.owner; lifecycle = f.lifecycle
        with lifecycle.lock:
            self._require_original(capture)
            deny(capture.owner is owner and capture.core is f.core and capture.runner is f.runner
                 and capture.ledger is f.ledger and capture.purpose is purpose
                 and capture.pid == os.getpid() and capture.thread_id == threading.get_ident()
                 and capture.instance_id == owner.instance_id and capture.uid == owner.uid and not owner._closed
                 and capture.admission_generation == lifecycle.admission_generation
                 and capture.composition_generation == lifecycle.composition_generation
                 and capture.fence_sequence == lifecycle.fence_sequence
                 and capture.source == owner.source and capture.composition_digest == f.spec.digest
                 and capture.auth_deadline == owner._auth_deadline and capture.tls_expires == owner._tls_expires
                 and (lifecycle.phase is NativePhase.CAPACITY_ADMIN or capture.use is NativeAccessUse.SETTLEMENT and lifecycle.phase is NativePhase.ACTIVE)
                 and owner.tls_verified is True)
        if capture.use is NativeAccessUse.SETTLEMENT:
            deny(type(capture.work_handle) is NativeOwnedWorkHandle
                 and lifecycle._handles.get(capture.work_handle.task_id) is capture.work_handle
                 and getattr(lifecycle._boundary,'settlement_handle',None) is capture.work_handle
                 and capture.work_handle.thread is threading.current_thread()
                 and lifecycle._handles.get(capture.work_handle.parent.task_id) is capture.work_handle.parent
                 and capture.work_handle.parent.foundation is f and lifecycle._fence is None)
        now, mono = datetime.now(UTC), time.monotonic()
        with lifecycle.lock:
            observed=self._originals.get(id(capture))
            deny(observed is not None and observed[0] is capture and now>=observed[2] and mono>=observed[3])
            observed[2],observed[3]=now,mono
        deny(now >= capture.captured_at and capture.monotonic_at <= mono < capture.auth_deadline
             and now.timestamp() < capture.tls_expires
             and (capture.principal.expires_at - capture.principal.issued_at).total_seconds() == 300
             and capture.principal.actor_session_id == owner.instance_id
             and capture.principal.assignment_revision == capture.assignment_revision
             and capture.principal.actor is (CoreActor.COMMIT_SERVICE if purpose is Capability.COMMIT else CoreActor.OWNER_HUMAN))
        f.require_bindings()
        f.core.require(capture.principal, purpose, scope=f.ledger.scope)
        if tx is not None:
            deny(tx.context.principal is capture.principal and tx.context.purpose is purpose)
            row = self.native_row(tx)
            deny(row.record_id == capture.native_record_id and row.revision == capture.native_revision
                 and row.payload_digest == capture.native_digest)


class NativeAuthorityFoundation:
    @classmethod
    def bind_owner(cls, owner: NativeMobileComposition, spec: NativeHostCompositionConfig) -> NativeAuthorityFoundation:
        from .runtime_adapter import NativeMobileComposition
        deny(cls is NativeAuthorityFoundation and type(owner) is NativeMobileComposition and type(spec) is NativeHostCompositionConfig
             and getattr(owner, 'foundation', None) is None and owner._host_composition is spec)
        self = cls()
        self.owner, self.spec = owner, spec
        self.coding_backend_registry = spec.coding_backend_registry
        self.core, self.runner, self.ledger = owner.core, owner.runner, owner.ledger
        self.runtime,self.missions,self.mobile,self.identity=owner.runtime,owner.missions,owner.mobile,owner.identity
        self.lifecycle = NativeLifecycle(self)
        self.access = NativeCoreAccess(self)
        # Publish ownership even if a later binding step fails. A construction
        # failure cannot become an ABSENT_FENCED producer or lose its lease.
        owner.foundation = self
        existing = getattr(owner, 'chat_governor', None)
        if existing is None:
            limits = Limits(50000000, 20)
            existing = CoreDualGovernor(self.core, self.runner, GovernorPolicy(self.ledger.scope,
                'native-mobile-chat-v1', limits, limits, limits, max_clock_step_seconds=3600))
        self.governor = existing
        deny(existing.policy.digest == spec.to_dict()['bootstrap_policy_digest'])
        self.intent_journal = CoreIntentJournal(self.ledger, self.governor)
        self.liability = CoreLiabilityLedger(self.core, self.runner, self.ledger.scope)
        self.target_projection = CoreTargetProjection(self.intent_journal, self.liability, spec.portable.binding)
        owner.intent_journal = self.intent_journal
        self.controller = NativeCapacityOwnerController(self)
        self.root_observations = spec.observe(owner)
        self.require_bindings()
        self.lifecycle.bind_producers()
        return self

    def require_bindings(self):
        from main import AgentRuntime

        from runtime.memory_patch.persistence.ports import LocalCoreRecordFactory
        from runtime.mobile_gateway.service import MobileGateway
        from runtime.mobile_gateway.wire import Identity

        from .mission_service import MissionService
        from .runtime_adapter import NativeMobileComposition
        owner = self.owner
        deny(owner.foundation is self and type(self.spec) is NativeHostCompositionConfig
             and owner._host_composition is self.spec and type(self.access) is NativeCoreAccess
             and self.access.foundation is self
             and self.coding_backend_registry is self.spec.coding_backend_registry)
        self.spec.coding_model_ids()
        if self.coding_backend_registry is not None:
            deny(all(source == owner.source for source in self.coding_backend_registry._host_sources()))
        deny(type(owner) is NativeMobileComposition and type(owner.runtime) is AgentRuntime
             and owner.runtime is self.runtime and type(owner.missions) is MissionService and owner.missions is self.missions
             and type(owner.mobile) is MobileGateway and owner.mobile is self.mobile
             and type(owner.identity) is Identity and owner.identity is self.identity and owner.mobile.identity is self.identity
             and owner.mobile.native_host is owner and owner.mobile.missions is self.missions
             and type(self.target_projection) is CoreTargetProjection and self.target_projection.core is self.core
             and self.target_projection.runner is self.runner and self.target_projection.binding is self.spec.portable.binding
             and type(self.core) is CoreAdmission and type(self.runner) is TransactionRunner
             and type(self.ledger) is CoreWarrantLedger and self.core is owner.core
             and self.runner is owner.runner and self.runner._admission is self.core
             and type(self.runner._factory) is LocalCoreRecordFactory and self.runner._factory.core is self.core
             and self.ledger is owner.ledger and self.ledger.core is self.core and self.ledger.runner is self.runner
             and self.ledger.scope == self.core._assignment.scope
             and owner.runtime._memory_patch_admission is self.core and owner.runtime._owns_memory_patch_admission is False
             and owner.missions.core is self.core and owner.missions.runner is self.runner and owner.missions.ledger is self.ledger
             and owner.mobile.core is self.core and owner.mobile.runner is self.runner
             and type(self.governor) is CoreDualGovernor and self.governor.core is self.core
             and self.governor.runner is self.runner and self.governor.policy.scope == self.ledger.scope
             and type(self.intent_journal) is CoreIntentJournal and self.intent_journal.ledger is self.ledger
             and self.intent_journal.governor is self.governor and owner.intent_journal is self.intent_journal
             and type(self.liability) is CoreLiabilityLedger and self.liability.core is self.core
             and self.liability.runner is self.runner and self.liability.scope == self.ledger.scope
             and self.target_projection.journal is self.intent_journal and self.target_projection.liability is self.liability
             and self.spec.portable.binding.scope == self.ledger.scope
             and owner.instance_id == self.core._session
             and getattr(owner.missions,'_chat_governor',None) in (None,self.governor))


@dataclass(slots=True, repr=False)
class _Pending:
    fence: NativeCapacityFence
    review: codec.ExecutionCapacityReview | None = None
    warrant: object = None
    state: str = 'REVIEWING'


class NativeCapacityOwnerController:
    def __init__(self, foundation):
        self.foundation = foundation
        self._pending = {}

    def capture_host(self, stage: CapacityStage, fence: NativeCapacityFence) -> NativeCapacityHostCapture:
        deny(type(stage) is CapacityStage)
        f = self.foundation; lifecycle = f.lifecycle
        lifecycle.require_fence(fence)
        purposes = {CapacityStage.REVIEW: (Capability.READ,), CapacityStage.APPROVE: (Capability.OWNER_APPROVAL,),
                    CapacityStage.APPLY: (Capability.MANAGE, Capability.COMMIT)}[stage]
        authorities = []
        quiescence = None
        try:
            for purpose in purposes: authorities.append(f.access.capture(purpose, use=NativeAccessUse.CAPACITY))
            lifecycle._boundary.authorities = tuple(authorities)
            try: quiescence = lifecycle.capture_quiescence(fence)
            finally: del lifecycle._boundary.authorities
            captured_at = datetime.now(UTC)
            expires_at = min(fence.expires_at, *(a.principal.expires_at for a in authorities),
                datetime.fromtimestamp(min(a.tls_expires for a in authorities), UTC),
                captured_at + timedelta(seconds=min(a.auth_deadline - time.monotonic() for a in authorities)))
            pending = self._pending[fence.request_id]
            if pending.review is not None:
                r = pending.review.to_dict()
                deny(quiescence.projection == canonical_json_bytes(r['quiescence']))
                expires_at = min(expires_at, codec.utc(r['expires_at']))
            host = _original(NativeCapacityHostCapture, f.access, foundation=f, controller=self, stage=stage,
                fence=fence, quiescence=quiescence, authorities=tuple(authorities), review=pending.review,
                captured_at=captured_at, expires_at=expires_at, applied_at=captured_at if stage is CapacityStage.APPLY else None,
                pid=os.getpid(), thread_id=threading.get_ident())
            host.require_live(stage)
            return host
        except BaseException:
            if quiescence is not None: quiescence.close()
            for authority in authorities: authority.close()
            raise

    def require_host(self, host, stage, *, tx=None):
        f = self.foundation
        deny(type(host) is NativeCapacityHostCapture and host.foundation is f and host.controller is self
             and host.stage is stage and host.pid == os.getpid() and host.thread_id == threading.get_ident())
        f.access._require_original(host)
        f.lifecycle.require_fence(host.fence)
        f.access._require_original(host.quiescence)
        deny(host.quiescence.foundation is f and host.quiescence.fence is host.fence
             and host.quiescence.pid == os.getpid() and host.quiescence.thread_id == threading.get_ident()
             and datetime.now(UTC) < host.expires_at)
        pending = self._pending.get(host.fence.request_id)
        deny(pending is not None and pending.fence is host.fence and pending.review is host.review)
        expected = {CapacityStage.REVIEW: (Capability.READ,), CapacityStage.APPROVE: (Capability.OWNER_APPROVAL,),
                    CapacityStage.APPLY: (Capability.MANAGE, Capability.COMMIT)}[stage]
        deny(tuple(a.purpose for a in host.authorities) == expected)
        for authority in host.authorities:
            f.access.require_capture(authority, authority.purpose,
                                     tx=tx if tx is not None and tx.context.purpose is authority.purpose else None)
        deny(len({(a.instance_id, a.assignment_revision, a.admission_generation, a.composition_generation,
                   a.native_revision, a.native_digest) for a in host.authorities}) == 1)
        if host.review is not None:
            r = host.review.to_dict(); a = host.authorities[0]
            deny(a.instance_id == r['actor_session_id'] and a.assignment_revision == r['assignment_revision']
                 and a.native_revision == r['native_admission_revision'] and a.native_digest == r['native_admission_digest']
                 and a.admission_generation == r['admission_generation'] and a.composition_generation == r['composition_generation']
                 and a.source == (r['host_source_sha'], r['host_source_capsule_digest'])
                 and a.composition_digest == r['composition_digest']
                 and host.quiescence.projection == canonical_json_bytes(r['quiescence']))
        if tx is not None:
            deny(tx.context.principal is host.authorities[-1].principal and tx.context.purpose is expected[-1])

    def require_core_view(self,host,tx):
        current=NativeCapacityCoreView.read_in_transaction(tx,self.foundation)
        current.require_idle();deny(current.digest==host.quiescence.view.digest)

    def _readback(self, request_id, review_digest=None, warrant_digest=None, proposed=None):
        f = self.foundation
        authority = f.access.capture(Capability.READ, use=NativeAccessUse.READ)
        try:
            def read(tx):
                f.access.require_capture(authority, Capability.READ, tx=tx)
                result = f.governor._capacity_readback(tx, request_id, review_digest, warrant_digest, proposed)
                f.access.require_capture(authority, Capability.READ, tx=tx)
                return result
            return f.runner.run(TransactionContext(authority.principal, Capability.READ), read)
        finally: authority.close()

    @contextmanager
    def _call(self):
        lifecycle = self.foundation.lifecycle
        token = object()
        with lifecycle.lock:
            deny(not lifecycle._calls and lifecycle.phase is NativePhase.CAPACITY_ADMIN)
            lifecycle._calls.add(token)
        try: yield
        finally:
            with lifecycle.lock: lifecycle._calls.remove(token)

    def dispatch(self, peer_uid: int, value: dict) -> dict:
        f = self.foundation; owner = f.owner
        deny(type(value) is dict and type(value.get('op')) is str)
        deny(type(peer_uid) is int and peer_uid == owner.uid)
        codec.exact(value, CAPACITY_FIELDS.get(value.get('op'), set()))
        operation = value['op']
        deny(operation in CAPACITY_FIELDS)
        if operation != 'native_access_status': codec.hexdigest(value['request_id'], 32)
        if 'review_digest' in value: codec.hexdigest(value['review_digest'])
        if 'warrant_digest' in value:
            deny(type(value['warrant_digest']) is str and value['warrant_digest'].startswith('sha256:'))
            codec.hexdigest(value['warrant_digest'][7:])
        with self._call():
            if operation == 'native_access_status':
                authority = f.access.capture(Capability.READ, use=NativeAccessUse.READ)
                try:
                    f.access.require_capture(authority, Capability.READ)
                    return {'schema': 'aioa.native-access-status.v1', 'phase': f.lifecycle.phase.value,
                        'composition_digest': f.spec.digest, 'source_sha': owner.source[0], 'capsule_digest': owner.source[1],
                        'admission_generation': f.lifecycle.admission_generation,
                        'composition_generation': f.lifecycle.composition_generation, 'authority': 'NONE', 'model_certification': 'NOT_CERTIFIED'}
                finally: authority.close()
            if operation == 'governor_initialize': return self._initialize(value)
            identity = value['request_id']
            if operation in ('execution_capacity_status', 'execution_capacity_apply', 'execution_capacity_approve', 'execution_capacity_review'):
                proposed=codec.proposal(value['proposed']) if operation=='execution_capacity_review' else None
                readback = self._readback(identity, value.get('review_digest'), value.get('warrant_digest'),proposed)
                if readback is not None: return readback.to_dict()
            if operation == 'execution_capacity_status':
                pending = self._pending.get(identity)
                return {'status': pending.state if pending is not None else 'NOT_FOUND', 'authority': 'NONE', 'automatic_retry': False}
            if operation == 'execution_capacity_review':
                deny(identity not in self._pending and len(self._pending) < 64)
                proposed = codec.proposal(value['proposed'])
                fence = f.lifecycle.begin_capacity_review(identity)
                pending = _Pending(fence); self._pending[identity] = pending
                try:
                    host = self.capture_host(CapacityStage.REVIEW, fence)
                    try:
                        review = f.governor.execution_capacity_review(host.authorities[0].principal, proposed,
                            request_id=identity, host_capture=host, composition_digest=f.spec.digest)
                    finally: host.close()
                    pending.review = review; pending.warrant = codec.capacity_warrant(review); pending.state = 'REVIEWED'
                    return {'status': 'REVIEWED', 'review': review.to_dict(), 'warrant': pending.warrant.to_dict(),
                            'warrant_digest': pending.warrant.digest(), 'authority': 'NONE'}
                except BaseException:
                    f.lifecycle.abort(fence); pending.state = 'ABORTED'
                    raise
            pending = self._pending.get(identity)
            deny(pending is not None)
            if operation == 'execution_capacity_abort':
                authority = f.access.capture(Capability.READ, use=NativeAccessUse.CONTROL)
                try:
                    f.access.require_capture(authority, Capability.READ)
                    if f.lifecycle._fence is pending.fence: f.lifecycle.abort(pending.fence)
                    pending.state = 'ABORTED'
                    return {'status': 'ABORTED', 'authority': 'NONE', 'automatic_retry': False}
                finally: authority.close()
            deny(pending.review is not None and pending.review.to_dict()['review_digest'] == value['review_digest']
                 and pending.state in ('REVIEWED', 'APPROVED'))
            stage = CapacityStage.APPROVE if operation == 'execution_capacity_approve' else CapacityStage.APPLY
            host = self.capture_host(stage, pending.fence)
            try:
                if stage is CapacityStage.APPROVE:
                    deny(pending.state == 'REVIEWED')
                    def approve(tx):
                        host.require_live(stage, tx=tx)
                        self.require_core_view(host,tx)
                        f.ledger.approve_in_transaction(tx, pending.warrant)
                        host.require_live(stage, tx=tx)
                    f.runner.run(TransactionContext(host.authorities[0].principal, Capability.OWNER_APPROVAL), approve)
                    host.require_live(stage); pending.state = 'APPROVED'
                    return {'status': 'APPROVED', 'warrant_digest': pending.warrant.digest(), 'authority': 'NONE', 'automatic_retry': False}
                deny(pending.state == 'APPROVED' and value['warrant_digest'] == pending.warrant.digest())
                receipt = f.governor.apply_execution_capacity(host.authorities[1].principal, pending.review, pending.warrant,
                    management_principal=host.authorities[0].principal, ledger=f.ledger, host_capture=host,
                    quiescence_capture=host.quiescence)
                try:
                    host.require_live(stage)
                    owner._require_qualified_operator()
                    deny(f.spec.observe(owner)==f.root_observations)
                except (ValueError,OSError):
                    pending.state='READBACK_ONLY'
                    raise
                pending.state = 'APPLIED'
                host.close()
                f.lifecycle.abort(pending.fence)
                return receipt.to_dict()
            except (CommitOutcomeUnknown,codec.CapacityAcknowledgedButFenced):
                pending.state = 'READBACK_ONLY'
                raise
            finally: host.close()

    def _initialize(self, value):
        f = self.foundation; owner = f.owner
        deny(type(value['expected_version']) is int and value['expected_version'] == 0
             and type(value['expected_epoch']) is int and value['expected_epoch'] == 0
             and value['bootstrap_policy_digest'] == f.governor.policy.digest
             and value['composition_digest'] == f.spec.digest
             and (value['source_sha'], value['capsule_digest']) == owner.source)
        authority = f.access.capture(Capability.MANAGE, use=NativeAccessUse.CONTROL)
        try:
            epoch=f.governor.start_epoch(authority.principal,native_capture=authority)
            return {'status':'INITIALIZED','version':1,'epoch':epoch,'authority':'NONE'}
        finally: authority.close()
