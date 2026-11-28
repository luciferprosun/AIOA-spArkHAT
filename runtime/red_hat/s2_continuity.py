"""Cross-boot read authority for one previously authorized disposable operation."""

import hashlib
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from runtime.mobile_gateway.wire import strict_json, unbase64
from runtime.red_hat.broker_protocol import digest, read_record, require
from runtime.red_hat.fixture_repository import open_dir, require_named_directory
from runtime.red_hat.role_storage import RoleStorage
from runtime.red_hat.s2_receipt import ManagementEvidence
from runtime.red_hat.writer_lifecycle import COMPLETION_STAGE, _closed_records, _read


def boot_hash():
    return hashlib.sha256(Path("/proc/sys/kernel/random/boot_id").read_bytes().strip()).hexdigest()


def require_successor(original, current):
    require(type(original) is RoleStorage and type(current) is RoleStorage
            and original.persistent is not None and current.persistent is not None, "NATIVE_S2_PROFILE")
    before, after = original.persistent, current.persistent
    require(before.volume_sha256 == after.volume_sha256 and before.filesystem_uuid == after.filesystem_uuid
            and before.authority_spki_sha256 == after.authority_spki_sha256
            and after.generation > before.generation, "NATIVE_S2_VOLUME_SUCCESSION")
    require(original.exact_ref == current.exact_ref and original.reader_gid == current.reader_gid
            and original.policy_sha256 == current.policy_sha256, "NATIVE_S2_OPERATION_SCOPE")
    for role in ("core", "broker", "verifier"):
        a, b = getattr(original, role), getattr(current, role)
        require((a.uid, a.gid, a.apparmor) == (b.uid, b.gid, b.apparmor), "NATIVE_S2_ROLE_CHANGED")
    # The v1 producer signatures include st_dev/st_ino. A device renumbering
    # that cannot be authenticated with this format must keep the intent held.
    for name in ("anchor", "repository", "ref_parent", "evidence", "staging", "state"):
        a, b = getattr(original, name), getattr(current, name)
        require((a.device, a.inode) == (b.device, b.inode), "NATIVE_S2_DURABLE_DIRECTORY")


@dataclass(frozen=True, slots=True)
class ColdSuccession:
    original: RoleStorage
    evidence: ManagementEvidence
    verifier_spki: str

    def proof(self, root_fd, current, binding, enrollment, *, current_epoch=None):
        """Derive every immutable receipt field from the original START and the opened disk."""
        require_successor(self.original, current)
        require(type(self.evidence) is ManagementEvidence
                and self.evidence.spki_sha256 == self.original.persistent.authority_spki_sha256
                and binding.storage_digest == self.original.digest
                and binding.request.exact_ref == current.exact_ref
                and binding.request.executor_key_id == enrollment.executor.key_id,
                "NATIVE_S2_ORIGINAL_BINDING")
        current.require_anchor(root_fd)
        closed = _closed_records(root_fd, self.original, binding, boot=binding.boot_id)
        from runtime.red_hat.authenticated_boundary import _open_seal

        stage = _open_seal(_read(root_fd, "writer-completion-stage", self.original),
                           enrollment.executor.spki, COMPLETION_STAGE)
        require(stage == {"schema": COMPLETION_STAGE, "binding": digest(binding.to_wire()),
                          "completion_sha256": closed["completion_sha256"]}, "NATIVE_S2_TERMINAL_SIGNATURE")
        request = binding.request
        with ExitStack() as stack:
            evidence = open_dir(root_fd, "evidence", stack)
            current.require_evidence(evidence)
            witness_id = request.witness_binding().witness_id
            def record_hash(name):
                raw = read_record(evidence, name, current.broker.uid, reader_gid=current.reader_gid)
                return hashlib.sha256(raw).hexdigest()
            witness, completion = record_hash(witness_id), record_hash("completion-" + witness_id)
            require_named_directory(root_fd, "evidence", evidence)
        require(closed["completion_sha256"] == completion, "NATIVE_S2_TERMINAL_COMPLETION")
        # The controller supplies the fresh challenge. Core independently binds
        # its current policy epoch, and the role signs an additional per-read nonce.
        expected = strict_json(self.evidence.expected_bytes)
        require(type(expected) is dict and "challenge" in expected and "current_policy_epoch" in expected,
                "NATIVE_S2_MANAGEMENT_EXPECTED")
        projection = {
            "start_sha256": request.start_digest, "intent_sha256": request.intent_digest,
            "reservation_sha256": request.reservation_digest, "original_policy_epoch": request.core_epoch,
            "volume_sha256": current.persistent.volume_sha256,
            "predecessor_boot_sha256": hashlib.sha256(binding.boot_id.encode("ascii")).hexdigest(),
            "predecessor_generation": self.original.persistent.generation,
            "predecessor_spki_sha256": enrollment.executor.key_id,
            "witness_sha256": witness, "completion_sha256": completion, "writer_closed_sha256": digest(closed),
            "current_boot_sha256": boot_hash(), "current_generation": current.persistent.generation,
            "current_policy_epoch": expected["current_policy_epoch"] if current_epoch is None else current_epoch,
            "reader_identity_sha256": hashlib.sha256(unbase64(self.verifier_spki)).hexdigest(),
            "challenge": expected["challenge"],
        }
        receipt = self.evidence.verify(now=int(time.time()), derived=projection)
        return receipt, completion

    def check_target(self, target, binding):
        current = target.storage
        require_successor(self.original, current)
        require(not target.writer and binding.storage_digest == self.original.digest
                and binding.request.exact_ref == current.exact_ref, "NATIVE_S2_READ_ONLY")
        current.require_anchor(target.root)
        current.repository.require_fd(target.repo)
        current.ref_parent.require_fd(target.ref_parent)
