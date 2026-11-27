"""Cold configuration built from the original durable Core journal."""

import os
import time
from dataclasses import dataclass
from pathlib import Path

from runtime.core_admission import Capability
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.red_hat.authenticated_boundary import DurableRoleRecoveryPort, read_original_warrant_in_transaction
from runtime.red_hat.broker_protocol import Peer, require
from runtime.red_hat.core_adapter import CoreIntentAdapter
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.execution_binding import capture_binding_in_transaction
from runtime.red_hat.role_storage import RoleStorage
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

    def bind(self, journal, identity, spec):
        require(type(self.storage) is RoleStorage and type(self.enrollment) is ExecutorEnrollment
                and self.storage.staging is not None and self.enrollment.executor.uid == self.storage.broker.uid
                and identity.spki == self.core_spki and spec.qualification_target is not None
                and spec.qualification_target.exact_ref is None
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

        def read(tx):
            warrant = read_original_warrant_in_transaction(
                tx, journal, capsules, self.task_id, self.storage, expected_source=spec.project_source)
            return capture_binding_in_transaction(
                tx, adapter, warrant, self.enrollment, trusted_device_id=self.device_id,
                now=int(time.time()), broker_epoch=self.broker_epoch)

        binding = journal._run(principal, Capability.READ, read)
        reader = self.storage.core_target()
        require(binding.storage_digest == self.storage.digest and binding.request.exact_ref == reader.exact_ref
                and binding.request.repository == (reader.repository.device, reader.repository.inode)
                and binding.request.ref_directory == (reader.ref_parent.device, reader.ref_parent.inode)
                and binding.repository_mount == reader.repository.mount
                and binding.ref_parent_mount == reader.ref_parent.mount
                and binding.boot_id == Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip(),
                "NATIVE_COLD_BOOTSTRAP_START")
        require_writer_closed(self.root_fd, self.storage, binding)
        return spec._with_authenticated_cold_target(reader)

    def recovery_port(self, adapter, coding_tasks, *, endpoint, peer, verifier_spki, identity):
        require(type(peer) is Peer, "NATIVE_COLD_BOOTSTRAP_VERIFIER")
        return DurableRoleRecoveryPort(
            adapter, coding_tasks, task_id=self.task_id, root_fd=self.root_fd,
            enrollment=self.enrollment, trusted_device_id=self.device_id, broker_epoch=self.broker_epoch,
            storage=self.storage, endpoint=endpoint, verifier_peer=peer, verifier_spki=verifier_spki,
            core_spki=self.core_spki, enabled=True, signer=identity,
        )
