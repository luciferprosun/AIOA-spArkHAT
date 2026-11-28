"""Cold configuration built from the original durable Core journal."""

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from runtime.core_admission import Capability
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.red_hat.authenticated_boundary import DurableRoleRecoveryPort, read_original_warrant_in_transaction
from runtime.red_hat.broker_protocol import Peer, require
from runtime.red_hat.core_adapter import CoreIntentAdapter
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.execution_binding import capture_binding_in_transaction
from runtime.red_hat.role_storage import RoleStorage
from runtime.red_hat.s2_continuity import ColdSuccession
from runtime.red_hat.writer_lifecycle import require_writer_closed


@dataclass(frozen=True, slots=True)
class ColdNativeBootstrap:
    """Trusted host inputs. The durable task and START still determine the ref."""

    task_id: str
    root_fd: int
    storage: RoleStorage
    enrollment: ExecutorEnrollment
    device_id: str
    broker_epoch: int
    core_spki: str
    observe_original: Callable[[dict], None] | None = None

    succession: ColdSuccession | None = None

    def __post_init__(self):
        require(type(self.storage) is RoleStorage and (
            self.storage.persistent is None and self.succession is None
            or self.storage.persistent is not None and type(self.succession) is ColdSuccession),
            "NATIVE_COLD_STORAGE_PROFILE")

    def bind(self, journal, identity, spec):
        require(type(self.storage) is RoleStorage and type(self.enrollment) is ExecutorEnrollment
                and self.storage.staging is not None and self.enrollment.executor.uid == self.storage.broker.uid
                and identity.spki == self.core_spki and spec.qualification_target is not None
                and spec.qualification_target.exact_ref is None
                and (self.observe_original is None or callable(self.observe_original))
                and self.storage.core_target().pre_capsule() == spec.qualification_target,
                "NATIVE_COLD_BOOTSTRAP_CONFIGURATION")
        self.storage.require_role("core")
        self.storage.require_anchor(self.root_fd)
        anchor = Path(os.readlink(f"/proc/self/fd/{self.root_fd}"))
        require(anchor / "repo" == Path(spec.to_dict()["git_target_repository"]),
                "NATIVE_COLD_BOOTSTRAP_LOCATOR")
        principal = journal.ledger.core.local_operator(Capability.READ)
        capsules = CorePatchCapsules(journal, identity, source_probe=lambda: spec.project_source)
        adapter = CoreIntentAdapter(journal)

        original_storage = self.storage if self.succession is None else self.succession.original

        def read(tx):
            warrant = read_original_warrant_in_transaction(
                tx, journal, capsules, self.task_id, original_storage, expected_source=spec.project_source)
            binding = capture_binding_in_transaction(
                tx, adapter, warrant, self.enrollment, trusted_device_id=self.device_id,
                now=int(time.time()), broker_epoch=self.broker_epoch)
            epoch = journal.governor._load(tx)["epoch"] if self.succession is not None else None
            if self.observe_original is None:
                return binding, epoch, None
            from runtime.memory_patch.contracts.serialization import canonical_sha256
            from runtime.memory_patch.persistence.ports import RecordKind
            from runtime.mission.coding_tasks import KIND, decode_coding_task_row

            row, state = journal._load(tx, warrant)
            outbox = tx.get(RecordKind.OUTBOX, journal._key(warrant))
            task_key = canonical_sha256([KIND, self.task_id])
            _, coding, _ = decode_coding_task_row(tx.get(RecordKind.OPERATION, task_key), self.task_id, self.core_spki)
            reservation = journal.governor._load(tx)['reservations'][warrant.risk_reservation_id]
            return binding, epoch, {'intent_revision': row.revision, 'outbox_revision': outbox.revision,
                             'intent': state['outcome']['contract_type'], 'outbox': outbox.payload['state'],
                             'reservation': reservation['state'], 'reservation_digest': state['reservation'],
                             'task': coding['receipts'][-1]['receipt']['state']}

        binding, epoch, original = journal._run(principal, Capability.READ, read)
        reader = self.storage.core_target()
        require(binding.storage_digest == original_storage.digest and binding.request.exact_ref == reader.exact_ref
                and binding.request.repository == (reader.repository.device, reader.repository.inode)
                and binding.request.ref_directory == (reader.ref_parent.device, reader.ref_parent.inode),
                "NATIVE_COLD_BOOTSTRAP_START")
        if self.observe_original is not None:
            self.observe_original(original)
        if self.succession is None:
            require(binding.repository_mount == reader.repository.mount
                    and binding.ref_parent_mount == reader.ref_parent.mount
                    and binding.boot_id == Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip(),
                    "NATIVE_COLD_BOOTSTRAP_START")
            require_writer_closed(self.root_fd, self.storage, binding)
        else:
            self.succession.proof(self.root_fd, self.storage, binding, self.enrollment, current_epoch=epoch)
        return spec._with_authenticated_cold_target(reader)

    def recovery_port(self, adapter, coding_tasks, *, endpoint, peer, verifier_spki, identity):
        require(type(peer) is Peer, "NATIVE_COLD_BOOTSTRAP_VERIFIER")
        return DurableRoleRecoveryPort(
            adapter, coding_tasks, task_id=self.task_id, root_fd=self.root_fd,
            enrollment=self.enrollment, trusted_device_id=self.device_id, broker_epoch=self.broker_epoch,
            storage=self.storage, endpoint=endpoint, verifier_peer=peer, verifier_spki=verifier_spki,
            core_spki=self.core_spki, enabled=True, signer=identity, succession=self.succession,
        )
