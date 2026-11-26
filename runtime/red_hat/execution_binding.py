"""RH-06 immutable authorization binding for disposable fixtures."""

import re
from contextlib import ExitStack
from dataclasses import dataclass, fields
from pathlib import Path

from lab.archaioa.warrant import EffectWarrant
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission.intent import LOCAL_ZERO_KIND
from runtime.mission.sandbox_linux import mountid
from runtime.red_hat.broker_protocol import BrokerRequest, digest, require
from runtime.red_hat.core_adapter import CoreIntentAdapter
from runtime.red_hat.fixture_repository import open_dir


SCHEMA = "aioa.redhat.native-execution-binding.v1"
HEX = re.compile(r"[0-9a-f]{64}")
BOOT_ID = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")
CONFIG_FIELDS = {
    "nonce", "boot_id", "repository_mount", "ref_parent_mount", "executor_id",
    "executor_key_id", "key_epoch", "broker_epoch", "issued_at", "expires_at",
}


def digest_string(value):
    return type(value) is str and HEX.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class NativeExecutionBindingV1:
    request: BrokerRequest
    operation_digest: str
    capsule_digest: str
    plan_digest: str
    source_digest: str
    policy_digest: str
    reservation_id_digest: str
    outbox_id_digest: str
    boot_id: str
    repository_mount: int
    ref_parent_mount: int

    def __post_init__(self):
        metadata = self.metadata()
        require(type(self.request) is BrokerRequest
                and all(digest_string(value) for key, value in metadata.items()
                        if key.endswith("_digest"))
                and type(self.boot_id) is str and BOOT_ID.fullmatch(self.boot_id)
                and all(type(value) is int and 0 < value < 2**63 for value in (
                    self.repository_mount, self.ref_parent_mount)),
                "RH06_BINDING_SCHEMA")
        # The fixture executor holds refs/heads and links a single leaf there.
        require(self.request.exact_ref.count("/") == 2, "RH06_REF_NOT_DIRECT")
        # Existing v1 witness and completion bind the full BrokerRequest.
        require(self.request.challenge == digest(metadata), "RH06_METADATA_BINDING")

    def metadata(self):
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "request"}

    def to_wire(self):
        return {"schema": SCHEMA, "request": self.request.to_wire(), **self.metadata()}

    @classmethod
    def from_wire(cls, value):
        require(type(value) is dict and set(value) == {"schema", *(f.name for f in fields(cls))}
                and value["schema"] == SCHEMA, "RH06_BINDING_SCHEMA")
        return cls(BrokerRequest.from_wire(value["request"]), **{
            f.name: value[f.name] for f in fields(cls) if f.name != "request"
        })


def _physical_context(repo, heads):
    return {
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip(),
        "repository_mount": mountid(repo),
        "ref_parent_mount": mountid(heads),
    }


def physical_context(root_fd):
    """Observe boot-local mount IDs when preparing the disposable START."""
    with ExitStack() as stack:
        repo = open_dir(root_fd, "repo", stack)
        refs = open_dir(repo, "refs", stack)
        heads = open_dir(refs, "heads", stack)
        return _physical_context(repo, heads)


def require_physical_context(target, binding):
    """Check the actual pinned FDs used for link or readback."""
    observed = _physical_context(target.repo, target.heads)
    require(all(value == getattr(binding, name) for name, value in observed.items()),
            "RH06_MOUNT_OR_BOOT_CHANGED")


def capture_binding(adapter, principal, warrant, enrollment, *, trusted_device_id,
                    now, broker_epoch, for_grant_export=False):
    """Project fixture binding only from the original Core transaction records."""
    require(type(adapter) is CoreIntentAdapter and type(warrant) is EffectWarrant
            and type(for_grant_export) is bool, "RH06_CORE_REQUIRED")
    journal = adapter.journal

    def capture(tx):
        binding = adapter._read_binding(tx, warrant)
        _, state = journal._load(tx, warrant)
        payload = state["operation"]["payload"]
        config = payload.get("rh06_fixture")
        require(state["schema"] == LOCAL_ZERO_KIND and payload.get("schema") == "aioa.local-operation.v3"
                and type(config) is dict and set(config) == CONFIG_FIELDS
                and binding.repository is not None and binding.device_id == trusted_device_id,
                "RH06_ORIGINAL_START_REQUIRED")
        if for_grant_export:
            governor = journal.governor._load(tx)
            require(not binding.settled and governor["kill"] is False
                    and binding.core_epoch == binding.settlement_epoch,
                    "RH06_CORE_FENCED")
            journal.ledger.require_active_in_transaction(tx, warrant, consumed=True)
        box = tx.get(RecordKind.OUTBOX, journal._key(warrant))
        metadata = {
            "operation_digest": binding.operation_digest.removeprefix("sha256:"),
            "capsule_digest": payload["capsule_digest"],
            "plan_digest": payload["plan_digest"],
            "source_digest": digest({name: payload[name] for name in (
                "source_base_sha", "patchset_sha256", "tree_sha",
            )}),
            "policy_digest": digest({
                "approval": warrant.approval_digest, "scope": warrant.owner_scope,
                "epoch": warrant.lease_epoch,
            }),
            "reservation_id_digest": digest([warrant.owner_scope, warrant.risk_reservation_id]),
            "outbox_id_digest": digest([binding.owner_scope_digest, box.record_id]),
            **{name: config[name] for name in ("boot_id", "repository_mount", "ref_parent_mount")},
        }
        request = BrokerRequest.for_fixture(
            operation_id=binding.operation_id, attempt_id=binding.attempt_id,
            owner_id=binding.owner_scope_digest, device_id=binding.device_id,
            start_digest=binding.start_digest, intent_digest=binding.intent_digest,
            warrant_digest=binding.warrant_digest, reservation_digest=binding.reservation_digest,
            core_epoch=binding.core_epoch, challenge=digest(metadata),
            repository_dev=binding.repository[0], repository_inode=binding.repository[1],
            ref_directory_dev=binding.ref_directory[0], ref_directory_inode=binding.ref_directory[1],
            exact_ref=binding.exact_ref, old_oid=binding.old_oid, new_oid=binding.new_oid,
            **{name: config[name] for name in CONFIG_FIELDS - metadata.keys()},
        )
        adapter.check_request(binding, request, enrollment, trusted_device_id=trusted_device_id,
                              core_epoch=binding.core_epoch, broker_epoch=broker_epoch,
                              now=now, historical=not for_grant_export)
        return NativeExecutionBindingV1(request, **metadata)

    return journal._run(principal, Capability.COMMIT, capture)
