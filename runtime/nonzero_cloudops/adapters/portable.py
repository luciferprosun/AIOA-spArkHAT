# Native semantic port; MIT attribution: LICENSE-NONZERO.txt.
# Source: cloudops/local_mock.py at 4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a.
# W7A repeat-demo semantics: 392487849eddc7444f5159994b66b72e73f15934.
"""Integrity-bound local mock inventory and protected execution boundary."""

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock, RLock, get_ident, local

from pydantic import TypeAdapter, ValidationError

from ..models import (
    ApprovalDecision,
    CloudResource,
    ElasticIpResource,
    LocalApprovalDecisionRecord,
    LocalExecutionIntent,
    LocalExecutionReceipt,
    LocalVerificationEvidence,
    RemediationOperation,
    RemediationProposal,
    ResourceEvidence,
    ResourceQuery,
    SecurityGroupResource,
    SecurityGroupRule,
)
from ..models.digest import compute_evidence_digest
from ..models.public_enums import AuthorityGate
from ..state.files import (
    LOCAL_STATE_MAX_BYTES,
    StateIntegrityError,
    atomic_write_private_json,
    locked_private_file,
    open_local_payload,
    read_private_json,
    seal_local_payload,
    validate_local_path,
)
from .resources import (
    CloudAdapterUnavailableError,
    CloudProviderError,
    CloudResourceNotFoundError,
    default_mock_resources,
)

_RESOURCE_ADAPTER = TypeAdapter(CloudResource)
_INVENTORY_PAYLOAD_TYPE = "AIOA_SANDBOX_INVENTORY"


class PortableMutationError(CloudProviderError):
    """Base typed failure for the isolated local mutation boundary."""


class PortablePolicyError(PortableMutationError):
    """The exact approval, proposal, evidence, or target policy was not satisfied."""


class PortableConflictError(PortableMutationError):
    """Durable local state conflicts with the approved action or idempotency key."""


def _canonical_inventory_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError):
        raise PortablePolicyError('local inventory observation is not canonical JSON') from None


@dataclass(frozen=True, slots=True)
class PortableInventoryObservation:
    """Immutable complete storage facts; no registration or effect authority.

    Core must separately bind these facts to its exact target incarnation and
    canonical history. Identical rolled-back payloads have identical roots.
    """
    canonical_state: bytes = field(repr=False)
    guard_identity: tuple = field(repr=False)
    state_root: str = field(init=False)
    resources_root: str = field(init=False)
    receipts_root: str = field(init=False)
    guard_fingerprint: str = field(init=False)

    def __post_init__(self):
        if (type(self.canonical_state) is not bytes
                or not 0 < len(self.canonical_state) <= LOCAL_STATE_MAX_BYTES
                or type(self.guard_identity) is not tuple or len(self.guard_identity) != 8
                or any(type(value) is not int or value < 0 for value in self.guard_identity)):
            raise PortablePolicyError('local inventory observation binding is invalid')
        try:
            payload = json.loads(self.canonical_state)
            valid = (type(payload) is dict
                     and set(payload) == {'format_version', 'resources', 'receipts'}
                     and type(payload['format_version']) is int and payload['format_version'] == 1
                     and type(payload['resources']) is list and type(payload['receipts']) is list
                     and _canonical_inventory_bytes(payload) == self.canonical_state)
        except (ValueError, RecursionError):
            valid = False
        if not valid:
            raise PortablePolicyError('local inventory observation payload is invalid')
        values = {
            'state_root': self.canonical_state,
            'resources_root': _canonical_inventory_bytes(payload['resources']),
            'receipts_root': _canonical_inventory_bytes(payload['receipts']),
            'guard_fingerprint': _canonical_inventory_bytes({
                'schema': 'aioa.portable-target-guard.v1', 'identity': self.guard_identity}),
        }
        for name, data in values.items():
            object.__setattr__(self, name, hashlib.sha256(data).hexdigest())

    @property
    def authority(self):
        return 'NONE'


_GUARD_LIFETIME_ISSUER = object()


class _NonTransferableGuardValue:
    __slots__ = ()

    def __copy__(self):
        raise TypeError('local guard values cannot be copied')

    def __deepcopy__(self, _memo):
        raise TypeError('local guard values cannot be copied')

    def __reduce_ex__(self, _protocol):
        raise TypeError('local guard values cannot be serialized')


class _PortableLockLifetime(_NonTransferableGuardValue):
    """Private lifetime of one physical flock; no effect or approval permit."""
    __slots__ = ('_active', '_config', '_descriptor', '_identity', '_pid', '_store', '_thread')

    def __init__(self, store, identity, issuer):
        if issuer is not _GUARD_LIFETIME_ISSUER or type(store) is not PortableStateStore:
            raise PortablePolicyError('local guard lifetime issuer is invalid')
        self._store, self._pid, self._thread = store, os.getpid(), get_ident()
        self._descriptor = store._held_lock.descriptor
        self._config = (store._path, store._lock_path, store._managed_layout)
        self._identity, self._active = identity, True

    def require_live(self, store):
        # Pure process/thread/config checks only. Physical identity checks stay
        # outside retried Core transactions, in the enclosing target guard.
        valid = (self._active and store is self._store and os.getpid() == self._pid
                 and get_ident() == self._thread
                 and (store._path, store._lock_path, store._managed_layout) == self._config
                 and getattr(store._held_lock, 'guard_lifetime', None) is self
                 and getattr(store._held_lock, 'exclusive', None) is True
                 and getattr(store._held_lock, 'descriptor', None) == self._descriptor)
        if not valid:
            raise PortablePolicyError('local guard lifetime is not current')

    def expire(self):
        self._active = False


@dataclass(frozen=True, slots=True)
class _PortableGuardEntry(_NonTransferableGuardValue):
    """One guard entry; nesting never claims a new physical acquisition."""
    _lifetime: object = field(repr=False)
    owns_outer_lock: bool
    _issuer: object = field(repr=False)

    def __post_init__(self):
        if (type(self._lifetime) is not _PortableLockLifetime
                or type(self.owns_outer_lock) is not bool or self._issuer is not _GUARD_LIFETIME_ISSUER):
            raise PortablePolicyError('local guard entry issuer is invalid')

    @property
    def authority(self):
        return 'NONE'

    def require_live(self, store):
        self._lifetime.require_live(store)
        binding = getattr(store._held_lock, 'target_binding', None)
        if (getattr(store._held_lock, 'guard_entry', None) is not self
                or type(binding) is not dict or binding.get('failed') is not False
                or binding.get('identity') != self._lifetime._identity):
            raise PortablePolicyError('local guard entry is not current')

    def require_outer_owner(self, store):
        self.require_live(store)
        if not self.owns_outer_lock:
            raise PortablePolicyError('local guard entry did not acquire the outer lock')


def _managed_layout_for(path):
    """A reserved path only restricts rights; it never grants Core authority."""
    # Relative names retain the current directory's reserved namespace signal.
    effective = path if path.is_absolute() else Path.cwd() / path
    positions = [index for index, part in enumerate(effective.parts)
                 if part.startswith('.aioa-core-managed')]
    if not positions:
        return None
    valid = (path.is_absolute() and '..' not in path.parts and len(positions) == 1
             and positions[0] == len(path.parts) - 4
             and path.parts[positions[0]] == '.aioa-core-managed-v1'
             and path.name == 'inventory.json')
    if not valid:
        raise PortablePolicyError('managed inventory namespace layout is invalid')
    index = positions[0]
    identities = path.parts[index + 1:index + 3]
    if any(len(value) != 64 or any(character not in '0123456789abcdef' for character in value)
           for value in identities):
        raise PortablePolicyError('managed inventory namespace identity is invalid')
    return (Path(*path.parts[:index]), *identities)


class PortableStateStore:
    """Atomically persist mock inventory and receipts in one crash-safe file."""

    def __init__(
        self,
        path: str | Path,
        *,
        initial_resources: tuple[CloudResource, ...] | None = None,
    ) -> None:
        resolved = Path(path) if isinstance(path, (str, Path)) else None
        if resolved is None or not str(resolved).strip():
            raise ValueError("local mock state path must be a non-empty path")
        # One CWD snapshot binds classification, guard and all later I/O.
        origin = None if resolved.is_absolute() else Path.cwd()
        resolved = resolved if origin is None else origin / resolved
        managed = _managed_layout_for(resolved)
        if origin is not None and managed is not None:
            raise PortablePolicyError('managed inventory requires an absolute target path')
        if managed is not None and initial_resources is not None:
            raise PortablePolicyError('managed inventory does not accept virtual initial resources')
        selected = initial_resources or default_mock_resources()
        identities = {
            (item.resource_type, item.resource_id, item.region) for item in selected
        }
        if len(identities) != len(selected):
            raise ValueError("local mock resources must have unique identities")
        try:
            validate_local_path(resolved)
            if managed is None:
                resolved.parent.mkdir(parents=True, exist_ok=True)
            validate_local_path(resolved)
        except (OSError, StateIntegrityError) as error:
            raise CloudAdapterUnavailableError(
                "local mock state directory is unavailable"
            ) from error
        self._path = resolved
        self._relative_cwd = origin
        self._managed_layout = managed
        self._lock_path = resolved.with_name(f"{resolved.name}.lock")
        self._initial_resources = tuple(selected)
        self._thread_lock = RLock()
        self._held_lock = local()
        self._require_managed_ready()

    def _require_managed_ready(self):
        if not self._path.is_absolute():
            raise PortablePolicyError('local inventory lost its absolute target binding')
        if self._relative_cwd is not None and Path.cwd() != self._relative_cwd:
            raise PortablePolicyError('local inventory working directory changed')
        current = _managed_layout_for(self._path)
        if current != self._managed_layout:
            raise PortablePolicyError('managed inventory path binding changed')
        if current is None:
            return
        if self._lock_path != self._path.with_name('inventory.json.lock'):
            raise PortablePolicyError('managed inventory guard path binding changed')
        try:
            validate_local_path(self._path)
            validate_local_path(self._lock_path)
            for parent in self._path.parents[:3]:
                info = parent.lstat()
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) & 0o077):
                    raise StateIntegrityError('managed inventory directory is not private')
            for path in (self._path, self._lock_path):
                info = path.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
                    raise StateIntegrityError('managed inventory file identity is invalid')
        except (OSError, StateIntegrityError) as error:
            raise CloudAdapterUnavailableError('managed inventory state is unavailable') from error

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _lock(self, *, exclusive: bool) -> object:
        with self._thread_lock:
            self._require_managed_ready()
            held = getattr(self._held_lock, 'exclusive', None)
            if held is not None:
                if exclusive and not held:
                    raise CloudAdapterUnavailableError('local mock lock upgrade is denied')
                lifetime = getattr(self._held_lock, 'guard_lifetime', None)
                if lifetime is not None:
                    lifetime.require_live(self)
                self._check_target_guard()
                try:
                    yield
                finally:
                    self._check_target_guard()
                return
            try:
                manager = (locked_private_file(self._lock_path, exclusive=exclusive)
                           if self._managed_layout is None else
                           locked_private_file(self._lock_path, exclusive=exclusive, create=False))
                with manager as descriptor:
                    self._held_lock.exclusive = exclusive
                    self._held_lock.descriptor = descriptor
                    lifetime = None
                    try:
                        if self._managed_layout is not None and exclusive:
                            lifetime = _PortableLockLifetime(self, self._target_guard_identity(), _GUARD_LIFETIME_ISSUER)
                            self._held_lock.guard_lifetime = lifetime
                        yield
                    finally:
                        if lifetime is not None:
                            lifetime.expire()
                            del self._held_lock.guard_lifetime
                        del self._held_lock.exclusive
                        del self._held_lock.descriptor
            except (OSError, StateIntegrityError) as error:
                raise CloudAdapterUnavailableError(
                    "local mock state lock is unavailable"
                ) from error

    def _target_guard_identity(self):
        validate_local_path(self._lock_path)
        descriptor = self._held_lock.descriptor
        if type(descriptor) is not int:
            raise StateIntegrityError('local mock lock descriptor is unavailable')
        parent = self._lock_path.parent.lstat()
        held, named = os.fstat(descriptor), self._lock_path.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
                or stat.S_IMODE(parent.st_mode) & 0o022
                or not stat.S_ISREG(held.st_mode) or held.st_uid != os.getuid()
                or stat.S_IMODE(held.st_mode) & 0o077 or held.st_nlink != 1
                or not stat.S_ISREG(named.st_mode) or named.st_nlink != 1
                or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)):
            raise StateIntegrityError('local mock target lock identity changed')
        return (parent.st_dev, parent.st_ino, parent.st_uid, parent.st_mode,
                held.st_dev, held.st_ino, held.st_uid, held.st_mode)

    def _check_target_guard(self):
        binding = getattr(self._held_lock, 'target_binding', None)
        if binding is None:
            return
        try:
            if binding['failed'] or self._target_guard_identity() != binding['identity']:
                raise StateIntegrityError('local mock target guard is fenced')
        except (OSError, StateIntegrityError) as error:
            binding['failed'] = True
            raise CloudAdapterUnavailableError('local mock target guard identity is unavailable') from error

    @contextmanager
    def _guard_entry_lifetime(self, owns_outer_lock):
        lifetime = getattr(self._held_lock, 'guard_lifetime', None)
        if lifetime is None:
            yield
            return
        previous = getattr(self._held_lock, 'guard_entry', None)
        self._held_lock.guard_entry = _PortableGuardEntry(lifetime, owns_outer_lock, _GUARD_LIFETIME_ISSUER)
        try:
            yield
        finally:
            if previous is None:
                del self._held_lock.guard_entry
            else:
                self._held_lock.guard_entry = previous

    def _current_guard_entry(self):
        entry = getattr(self._held_lock, 'guard_entry', None)
        if type(entry) is not _PortableGuardEntry:
            raise PortablePolicyError('local guard entry is unavailable')
        entry.require_live(self)
        return entry

    @contextmanager
    def target_guard(self):
        """Serialize one fixed target lifetime using its existing file lock.

        This is a storage lifecycle port, never approval or replay authority.
        Nested calls verify the held lock descriptor and current lock/parent
        identities. A detected substitution poisons this guard lifetime.
        This does not establish inventory CAS, a Core high-water revision,
        protection against an uncooperative OS owner, or effect authority.
        Missing inventory still requires a separate Core initialization policy.
        """
        owns_outer_lock = getattr(self._held_lock, 'exclusive', None) is None
        with self._lock(exclusive=True), self._guard_entry_lifetime(owns_outer_lock):
            if getattr(self._held_lock, 'target_binding', None) is not None:
                yield
                return
            try:
                identity = self._target_guard_identity()
            except (OSError, StateIntegrityError) as error:
                raise CloudAdapterUnavailableError('local mock target guard identity is unavailable') from error
            self._held_lock.target_binding = {'identity': identity, 'failed': False}
            try:
                self._check_target_guard()
                try:
                    yield
                finally:
                    self._check_target_guard()
            finally:
                del self._held_lock.target_binding

    def observe_guarded_inventory(self) -> PortableInventoryObservation:
        """Read full existing inventory in this thread's active named guard.

        No lock, inventory, registration or permission is lazily created by this
        method. The existing guard supplies storage serialization only.
        """
        binding = getattr(self._held_lock, 'target_binding', None)
        if (type(binding) is not dict
                or getattr(self._held_lock, 'exclusive', None) is not True
                or self._lock_path != self._path.with_name(f'{self._path.name}.lock')):
            raise PortablePolicyError('local inventory observation needs its exclusive target guard')
        self._check_target_guard()
        with self._lock(exclusive=False):
            resources, receipts = self._load(require_existing=True)
            result = PortableInventoryObservation(
                _canonical_inventory_bytes(self._payload(resources, receipts)),
                tuple(binding['identity']))
            self._check_target_guard()
            return result

    def _initial_snapshot(
        self,
    ) -> tuple[
        dict[tuple[object, str, str], CloudResource], dict[str, LocalExecutionReceipt]
    ]:
        resources = {
            (item.resource_type, item.resource_id, item.region): item
            for item in self._initial_resources
        }
        return resources, {}

    def _load(
        self,
        *,
        require_existing: bool = False,
    ) -> tuple[
        dict[tuple[object, str, str], CloudResource], dict[str, LocalExecutionReceipt]
    ]:
        if type(require_existing) is not bool:
            raise PortablePolicyError('local inventory existing-state flag is invalid')
        self._require_managed_ready()
        require_existing = require_existing or self._managed_layout is not None
        if not require_existing and not self._path.exists():
            return self._initial_snapshot()
        try:
            envelope = read_private_json(self._path)
            payload, _ = open_local_payload(
                envelope,
                payload_type=_INVENTORY_PAYLOAD_TYPE,
            )
        except (OSError, StateIntegrityError) as error:
            raise CloudAdapterUnavailableError(
                "local mock state is corrupt or unreadable"
            ) from error
        if not isinstance(payload, Mapping) or set(payload) != {
            "format_version",
            "receipts",
            "resources",
        }:
            raise CloudAdapterUnavailableError("local mock state shape is invalid")
        if (type(payload.get("format_version")) is not int
                or payload.get("format_version") != 1):
            raise CloudAdapterUnavailableError(
                "local mock state version is unsupported"
            )
        raw_resources = payload.get("resources")
        raw_receipts = payload.get("receipts")
        if not isinstance(raw_resources, list) or not isinstance(raw_receipts, list):
            raise CloudAdapterUnavailableError(
                "local mock state collections are invalid"
            )
        try:
            resource_values = [
                _RESOURCE_ADAPTER.validate_python(item) for item in raw_resources
            ]
            receipt_values = [
                LocalExecutionReceipt.model_validate(item) for item in raw_receipts
            ]
        except (TypeError, ValueError, ValidationError) as error:
            raise CloudAdapterUnavailableError(
                "local mock state violates typed contracts"
            ) from error
        resources = {
            (item.resource_type, item.resource_id, item.region): item
            for item in resource_values
        }
        receipts = {item.idempotency_key: item for item in receipt_values}
        if len(resources) != len(resource_values) or len(receipts) != len(
            receipt_values
        ):
            raise CloudAdapterUnavailableError(
                "local mock state contains duplicate identities"
            )
        return resources, receipts

    @staticmethod
    def _payload(resources, receipts):
        return {
            "format_version": 1,
            "receipts": [
                receipts[key].model_dump(mode="json") for key in sorted(receipts)
            ],
            "resources": [
                resources[key].model_dump(mode="json")
                for key in sorted(
                    resources, key=lambda item: (str(item[0]), item[1], item[2])
                )
            ],
        }

    @contextmanager
    def _core_write_lifetime(self, release):
        """Bind one host-issued live Core port to this thread's held guard."""
        from runtime.mission.portable_target import CorePortableWriteRelease
        if (self._managed_layout is None or type(release) is not CorePortableWriteRelease
                or getattr(self._held_lock, 'exclusive', None) is not True
                or type(getattr(self._held_lock, 'target_binding', None)) is not dict
                or getattr(self._held_lock, 'write_release', None) is not None):
            raise PortablePolicyError('managed inventory needs one live Core write port')
        release.require_store(self)
        self._held_lock.write_release = release
        try:
            yield
        finally:
            del self._held_lock.write_release

    def _write(
        self,
        resources: Mapping[tuple[object, str, str], CloudResource],
        receipts: Mapping[str, LocalExecutionReceipt],
    ) -> None:
        self._require_managed_ready()
        release = None
        before = None
        if self._managed_layout is not None:
            from runtime.mission.portable_target import CorePortableWriteRelease
            release = getattr(self._held_lock, 'write_release', None)
            if type(release) is not CorePortableWriteRelease:
                raise PortablePolicyError('managed inventory requires a current Core physical release')
            release.require_store(self)
            before = self.observe_guarded_inventory()
        payload = self._payload(resources, receipts)
        candidate = _canonical_inventory_bytes(payload) if release is not None else None
        try:
            envelope = seal_local_payload(
                payload,
                payload_type=_INVENTORY_PAYLOAD_TYPE,
            )
            if release is not None:
                # The complete payload is frozen before the fresh Core decision.
                acknowledgment = release.authorize_write(self, before, candidate)
                release.consume_write_ack(acknowledgment, self, before, candidate)
                self._require_managed_ready()
                self._check_target_guard()
            atomic_write_private_json(self._path, envelope)
        except (OSError, TypeError, ValueError) as error:
            raise CloudAdapterUnavailableError(
                "local mock state write failed"
            ) from error

    def get_resource(self, query: ResourceQuery) -> CloudResource:
        if not isinstance(query, ResourceQuery):
            raise TypeError("query must be ResourceQuery")
        with self._lock(exclusive=False):
            resources, _ = self._load()
            resource = resources.get(
                (query.resource_type, query.resource_id, query.region)
            )
        if resource is None:
            raise CloudResourceNotFoundError(
                "resource was not found in the persistent local inventory"
            )
        return resource

    def assert_ready(self) -> None:
        """Verify that the sandbox inventory is readable without applying a mutation."""

        with self._lock(exclusive=False):
            self._load()

    def get_receipt(self, idempotency_key: str) -> LocalExecutionReceipt | None:
        with self._lock(exclusive=False):
            _, receipts = self._load()
            return receipts.get(idempotency_key)

    def _released_receipts(self, query, resources, receipts):
        initial = next((item for item in self._initial_resources if (
            item.resource_type == query.resource_type
            and item.resource_id == query.resource_id and item.region == query.region
        )), None)
        key = (query.resource_type, query.resource_id, query.region)
        if initial is None or key in resources:
            return initial, ()
        return initial, tuple(receipt for receipt in receipts.values() if (
            receipt.before_resource == initial and receipt.after_resource is None
            and receipt.target_resource_type == query.resource_type
            and receipt.target_resource_id == query.resource_id
        ))

    def released_default_resource_receipts(
        self, query: ResourceQuery,
    ) -> tuple[LocalExecutionReceipt, ...]:
        """Read all releases of one absent demo target; none grant authority.

        Core must verify every consuming run, including interrupted later runs.
        Choosing only the greatest timestamp would miss a later UNKNOWN when
        the wall clock moves backwards or multiple receipts share a timestamp.
        """
        if not isinstance(query, ResourceQuery):
            raise TypeError("query must be ResourceQuery")
        with self._lock(exclusive=False):
            resources, receipts = self._load()
            _, consumed = self._released_receipts(query, resources, receipts)
            return consumed

    def rearm_verified_demo_resource(
        self, query: ResourceQuery, *, verifications: tuple[LocalVerificationEvidence, ...],
    ) -> bool:
        """Restore only initial mock state with Core-checked readback proofs.

        The existing inventory lock atomically compares the complete release
        set and preserves every receipt. This never calls a cloud provider.
        """
        if not isinstance(query, ResourceQuery):
            raise TypeError("query must be ResourceQuery")
        if not isinstance(verifications, tuple) or any(
            not isinstance(item, LocalVerificationEvidence) for item in verifications
        ):
            raise PortablePolicyError("demo rearm requires typed verification proofs")
        with self._lock(exclusive=True):
            resources, receipts = self._load()
            initial, consumed = self._released_receipts(query, resources, receipts)
            if not consumed:
                return False
            proofs = {item.receipt_hash: item for item in verifications}
            if len(proofs) != len(verifications) or set(proofs) != {
                receipt.receipt_hash for receipt in consumed
            }:
                raise PortableConflictError("demo release history changed or is unverified")
            for receipt in consumed:
                proof = proofs[receipt.receipt_hash]
                if (
                    proof.run_id != receipt.run_id or proof.proposal_id != receipt.proposal_id
                    or proof.operation_type != receipt.operation_type
                    or proof.target_resource_type != receipt.target_resource_type
                    or proof.target_resource_id != receipt.target_resource_id
                    or not proof.observed_absent or proof.observed_resource is not None
                    or proof.verified_at < receipt.executed_at
                ):
                    raise PortablePolicyError("demo verification is not release-bound")
            resources[(query.resource_type, query.resource_id, query.region)] = initial
            self._write(resources, receipts)
            return True

    def execute(
        self,
        *,
        proposal: RemediationProposal,
        evidence: ResourceEvidence,
        approval: LocalApprovalDecisionRecord,
        intent: LocalExecutionIntent,
        executed_at: datetime,
    ) -> tuple[LocalExecutionReceipt, bool]:
        """Apply and receipt one exact approved mutation in a single atomic replace."""

        self._validate_execution_binding(proposal, evidence, approval, intent)
        with self._lock(exclusive=True):
            resources, receipts = self._load()
            existing = receipts.get(intent.idempotency_key)
            if existing is not None:
                if (
                    existing.intent_hash != intent.intent_hash
                    or existing.proposal_hash != proposal.proposal_hash
                    or existing.decision_hash != approval.decision_hash
                ):
                    raise PortableConflictError(
                        "local idempotency key has conflicting ownership"
                    )
                return existing, False
            key = (
                proposal.target_resource_type,
                proposal.target_resource_id,
                evidence.resource.region,
            )
            current = resources.get(key)
            if current is None or current != evidence.resource:
                raise PortableConflictError(
                    "local target changed after evidence was approved"
                )
            after: CloudResource | None
            if proposal.operation_type is RemediationOperation.RELEASE_ELASTIC_IP:
                if (
                    not isinstance(current, ElasticIpResource)
                    or current.association_id is not None
                    or proposal.normalized_parameters
                    != {"allocation_id": proposal.target_resource_id}
                ):
                    raise PortablePolicyError(
                        "local release policy did not match exact state"
                    )
                del resources[key]
                after = None
            elif proposal.operation_type is RemediationOperation.REVOKE_PUBLIC_INGRESS:
                if not isinstance(current, SecurityGroupResource):
                    raise PortablePolicyError(
                        "local ingress target is not a Security Group"
                    )
                raw_rules = proposal.normalized_parameters.get("ingress_rules")
                if (
                    set(proposal.normalized_parameters)
                    != {
                        "ingress_rules",
                        "security_group_id",
                    }
                    or proposal.normalized_parameters.get("security_group_id")
                    != proposal.target_resource_id
                    or not isinstance(raw_rules, list)
                    or not raw_rules
                ):
                    raise PortablePolicyError("local ingress parameters are not exact")
                try:
                    approved_rules = tuple(
                        SecurityGroupRule.model_validate(rule) for rule in raw_rules
                    )
                except (TypeError, ValueError, ValidationError) as error:
                    raise PortablePolicyError(
                        "local ingress approval contains malformed rules"
                    ) from error
                if any(rule not in current.inbound_rules for rule in approved_rules):
                    raise PortableConflictError(
                        "approved ingress rule no longer exists on the target"
                    )
                remaining = tuple(
                    rule for rule in current.inbound_rules if rule not in approved_rules
                )
                if len(remaining) != len(current.inbound_rules) - len(
                    set(approved_rules)
                ):
                    raise PortablePolicyError("approved ingress rules are ambiguous")
                after = current.model_copy(update={"inbound_rules": remaining})
                resources[key] = after
            else:
                raise PortablePolicyError("local operation is NEVER_AUTONOMOUS")
            values: dict[str, object] = {
                "run_id": proposal.run_id,
                "proposal_id": proposal.proposal_id,
                "proposal_hash": proposal.proposal_hash,
                "evidence_hash": proposal.evidence_hash,
                "decision_hash": approval.decision_hash,
                "intent_hash": intent.intent_hash,
                "idempotency_key": intent.idempotency_key,
                "operation_type": proposal.operation_type,
                "target_resource_type": proposal.target_resource_type,
                "target_resource_id": proposal.target_resource_id,
                "before_resource": current,
                "after_resource": after,
                "executed_at": executed_at,
            }
            provisional = LocalExecutionReceipt.model_construct(
                **values,
                receipt_hash="0" * 64,
            )
            receipt = LocalExecutionReceipt(
                **values,
                receipt_hash=compute_evidence_digest(provisional.receipt_payload()),
            )
            receipts[intent.idempotency_key] = receipt
            self._write(resources, receipts)
            return receipt, True

    @staticmethod
    def _validate_execution_binding(
        proposal: RemediationProposal,
        evidence: ResourceEvidence,
        approval: LocalApprovalDecisionRecord,
        intent: LocalExecutionIntent,
    ) -> None:
        if (
            proposal.authority_class is not AuthorityGate.PLAN_AND_CONFIRM
            or proposal.authorizes_execution
            or approval.decision is not ApprovalDecision.APPROVED
            or proposal.run_id != evidence.run_id
            or proposal.correlation_id != evidence.correlation_id
            or proposal.evidence_hash != evidence.evidence_hash
            or proposal.evidence_fingerprint != evidence.stable_fingerprint()
            or approval.proposal_id != proposal.proposal_id
            or approval.run_id != proposal.run_id
            or approval.proposal_hash != proposal.proposal_hash
            or approval.evidence_hash != proposal.evidence_hash
            or approval.proposal_version != proposal.version
            or intent.run_id != proposal.run_id
            or intent.proposal_id != proposal.proposal_id
            or intent.proposal_hash != proposal.proposal_hash
            or intent.evidence_hash != proposal.evidence_hash
            or intent.decision_hash != approval.decision_hash
            or intent.operation_type is not proposal.operation_type
            or intent.target_resource_type is not proposal.target_resource_type
            or intent.target_resource_id != proposal.target_resource_id
            or intent.idempotency_key not in {
                f"local-exec:{proposal.run_id}:{proposal.proposal_hash}",
                f"local-exec:{proposal.proposal_hash}",
            }
        ):
            raise PortablePolicyError(
                "local executor prerequisites are not exactly approval-bound"
            )

    def verify(
        self,
        receipt: LocalExecutionReceipt,
        *,
        verified_at: datetime,
    ) -> LocalVerificationEvidence:
        """Read the persisted inventory independently and bind exact post-action proof."""

        with self._lock(exclusive=False):
            resources, receipts = self._load()
            durable_receipt = receipts.get(receipt.idempotency_key)
            if durable_receipt != receipt:
                raise PortableConflictError("local execution receipt is not durable")
            key = (
                receipt.target_resource_type,
                receipt.target_resource_id,
                receipt.before_resource.region,
            )
            observed = resources.get(key)
        if receipt.operation_type is RemediationOperation.RELEASE_ELASTIC_IP:
            if observed is not None:
                raise PortableConflictError("released local address is still present")
            observed_absent = True
        elif receipt.operation_type is RemediationOperation.REVOKE_PUBLIC_INGRESS:
            if observed != receipt.after_resource:
                raise PortableConflictError(
                    "local Security Group read-back differs from the receipt"
                )
            observed_absent = False
        else:
            raise PortablePolicyError("local verification operation is non-executable")
        values: dict[str, object] = {
            "run_id": receipt.run_id,
            "proposal_id": receipt.proposal_id,
            "receipt_hash": receipt.receipt_hash,
            "operation_type": receipt.operation_type,
            "target_resource_type": receipt.target_resource_type,
            "target_resource_id": receipt.target_resource_id,
            "observed_absent": observed_absent,
            "observed_resource": observed,
            "verified_at": verified_at,
        }
        provisional = LocalVerificationEvidence.model_construct(
            **values,
            verification_hash="0" * 64,
        )
        return LocalVerificationEvidence(
            **values,
            verification_hash=compute_evidence_digest(
                provisional.verification_payload()
            ),
        )


class PortableResourceReader:
    """Read-only CloudProvider view over the separately protected local state store."""

    def __init__(self, state: PortableStateStore) -> None:
        if not isinstance(state, PortableStateStore):
            raise TypeError("state must be PortableStateStore")
        self._state = state
        self.read_calls: list[ResourceQuery] = []
        self.network_calls = 0

    @property
    def adapter_name(self) -> str:
        return "persistent-local-mock-aws"

    def get_resource(self, query: ResourceQuery) -> CloudResource:
        if not isinstance(query, ResourceQuery):
            raise TypeError("query must be ResourceQuery")
        self.read_calls.append(query)
        return self._state.get_resource(query)


class PortableExecutor:
    """Only component allowed to call the persistent local mutation boundary."""

    def __init__(
        self,
        state: PortableStateStore,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        if not isinstance(state, PortableStateStore) or not callable(clock):
            raise TypeError("state and clock are required")
        self._state = state
        self._clock = clock
        self._counter_lock = Lock()
        self.execute_calls = 0
        self.mutation_calls = 0
        self.reconciled_calls = 0

    def execute(
        self,
        *,
        proposal: RemediationProposal,
        evidence: ResourceEvidence,
        approval: LocalApprovalDecisionRecord,
        intent: LocalExecutionIntent,
    ) -> LocalExecutionReceipt:
        with self._counter_lock:
            self.execute_calls += 1
        receipt, applied = self._state.execute(
            proposal=proposal,
            evidence=evidence,
            approval=approval,
            intent=intent,
            executed_at=self._clock(),
        )
        with self._counter_lock:
            if applied:
                self.mutation_calls += 1
            else:
                self.reconciled_calls += 1
        return receipt

    def rearm(self, query: ResourceQuery, *, verifications: tuple[LocalVerificationEvidence, ...]) -> bool:
        """One bounded fixed-demo attempt through the existing guarded Store."""
        templates = tuple(item for item in default_mock_resources() if type(item) is ElasticIpResource)
        if (type(query) is not ResourceQuery or len(templates) != 1
                or (query.resource_type, query.resource_id, query.region) != (
                    templates[0].resource_type, templates[0].resource_id, templates[0].region)
                or self._state._initial_resources != default_mock_resources()):
            raise PortablePolicyError('demo rearm requires the fixed default address template')
        with self._counter_lock:
            self.execute_calls += 1
        applied = self._state.rearm_verified_demo_resource(query, verifications=verifications)
        with self._counter_lock:
            if applied is True:
                self.mutation_calls += 1
            elif applied is False:
                self.reconciled_calls += 1
        return applied

    def counters(self) -> tuple[int, int, int]:
        """Return execution, mutation, and reconciliation counters atomically."""

        with self._counter_lock:
            return self.execute_calls, self.mutation_calls, self.reconciled_calls

    def get_receipt(self, idempotency_key: str) -> LocalExecutionReceipt | None:
        return self._state.get_receipt(idempotency_key)

    def verify(self, receipt: LocalExecutionReceipt) -> LocalVerificationEvidence:
        return self._state.verify(receipt, verified_at=self._clock())
