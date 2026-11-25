"""Fail-closed adapter from the existing Core journal to RH-02 bindings.

This module is an integration seam, not a production executor integration.
The Core has no durable cross-process pre-link release contract, and its
Native CAS acknowledgement is process-local. Consequently this adapter can
derive and check the original intent, but it deliberately cannot authorize a
broker dispatch. The only settlement helper here is explicitly fixture-only
and refuses repositories that are not marked disposable.
"""

from contextlib import ExitStack
from dataclasses import dataclass, replace
import hashlib
import json
import os
import re
import subprocess
import sys

from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.outcome import Applied
from lab.archaioa.warrant import EffectWarrant
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission.intent import CoreIntentJournal, INTENT_KINDS
from runtime.mission.liability import Reconciliation


_HEX = re.compile(r"[0-9a-f]{64}\Z")
_OID = re.compile(r"[0-9a-f]{40}\Z")


class CoreAdapterError(MemoryPatchError, ValueError):
    """Fixed fail-closed adapter error; caller data is never echoed."""

    def __init__(self, reason):
        super().__init__(ErrorCode.INTEGRITY_FAILED)
        self.args = (reason,)


def _require(condition, reason):
    if not condition:
        raise CoreAdapterError(reason)


@dataclass(frozen=True, slots=True)
class CoreStartBinding:
    """A validated projection of the original durable Core START."""

    owner_scope_digest: str
    operation_id: str
    attempt_id: str
    start_digest: str
    intent_digest: str
    warrant_digest: str
    reservation_digest: str
    operation_digest: str
    core_epoch: int
    settlement_epoch: int
    authorization_not_before: int
    authorization_expires_at: int
    liability_id: str
    settled: bool
    repository: tuple | None
    ref_directory: tuple | None
    exact_ref: str | None
    old_oid: str | None
    new_oid: str | None


class CoreIntentAdapter:
    """Read and bind the One-Core START; do not grant an execution permit.

    ``capture_start`` and ``check_request`` use the existing Core journal,
    warrant ledger, governor and transaction runner. Device and broker identity
    are supplied only as trusted host configuration to ``check_request``; they
    are not accepted from operation JSON as authority.
    """

    def __init__(self, journal):
        _require(type(journal) is CoreIntentJournal, "EXISTING_CORE_REQUIRED")
        self.journal = journal

    @staticmethod
    def _initial_intent(state):
        # Settlement mutates only outcome/resolution. Reconstruct the exact
        # pessimistic START payload so cold recovery binds to the same intent.
        return {
            "schema": state["schema"],
            "warrant_digest": state["warrant_digest"],
            "operation": state["operation"],
            "reservation": state["reservation"],
            "epoch": state["epoch"],
            "outcome": {"contract_type": "Unknown", "liability_id": state["liability_id"]},
            "liability_id": state["liability_id"],
            "resolution": None,
        }

    def _read_binding(self, tx, warrant):
        journal = self.journal
        row, state = journal._load(tx, warrant)
        _require(row is not None and type(state) is dict, "CORE_START_REQUIRED")
        _require(state["schema"] in INTENT_KINDS, "CORE_INTENT_SCHEMA")
        _require(state["outcome"].get("contract_type") in ("Unknown", "Applied"),
                 "CORE_INTENT_OUTCOME")
        operation = state["operation"]
        payload = operation.get("payload", {})
        fixture_profile = payload.get("schema") == "aioa.redhat.fixture-core-publication.v1"
        native_profile = (state["schema"] == "aioa-effect-intent-local-zero-v2"
                          and operation.get("operation_class") == "GIT_COMMIT"
                          and payload.get("schema") == "aioa.local-operation.v2"
                          and payload.get("profile") == "DISPOSABLE_BARE_PATCH_V1")
        _require(fixture_profile or native_profile, "CORE_CAS_INTENT_REQUIRED")
        governor = journal.governor._load(tx)
        _require(type(governor.get("epoch")) is int and governor["epoch"] >= state["epoch"],
                 "CORE_EPOCH_ROLLBACK")
        reservation_id = (warrant.risk_reservation_id
                          if state["schema"] in ("aioa-effect-intent-local-zero-v2",
                                                  "aioa-effect-intent-github-zero-v1")
                          else warrant.money_reservation_id)
        reservation = governor["reservations"].get(reservation_id)
        _require(reservation is not None, "CORE_RESERVATION_REQUIRED")
        settled = state["resolution"] is not None
        _require(reservation["state"] == ("COMMITTED" if settled else "UNKNOWN"),
                 "CORE_RESERVATION_STATE")
        box = tx.get(RecordKind.OUTBOX, journal._key(warrant))
        _require(box is not None and
                 (box.payload["state"] in ("PENDING", "DELIVERED") if settled
                  else box.payload["state"] == "HELD"), "CORE_OUTBOX_STATE")
        owner = canonical_sha256(journal.ledger.scope)
        initial = self._initial_intent(state)
        intent_digest = canonical_sha256(initial)
        start_digest = canonical_sha256({
            "schema": "aioa.redhat.core-start-binding.v1",
            "owner_scope_digest": owner,
            "record_id": row.record_id,
            "warrant_digest": warrant.digest(),
            "operation_digest": warrant.operation_hash,
            "reservation_digest": state["reservation"],
            "intent_digest": intent_digest,
            "core_epoch": state["epoch"],
            "liability_id": state["liability_id"],
        })
        operation_id = "native69-" + hashlib.sha256(warrant.task_id.encode("utf-8")).hexdigest()[:32]
        attempt_id = "attempt-" + start_digest[:32]
        publication_fields = (
            "repository_dev", "repository_inode", "ref_directory_dev", "ref_directory_inode",
            "ref", "old_oid", "new_oid",
        )
        supplied = [name in payload for name in publication_fields]
        _require(not any(supplied) or all(supplied), "CORE_PUBLICATION_BINDING_INCOMPLETE")
        if all(supplied):
            numeric = tuple(payload[name] for name in publication_fields[:4])
            _require(all(type(value) is int and value > 0 for value in numeric),
                     "CORE_PUBLICATION_BINDING_INVALID")
            _require(type(payload["ref"]) is str and payload["ref"].startswith("refs/heads/")
                     and payload["old_oid"] == "0" * 40
                     and type(payload["new_oid"]) is str and _OID.fullmatch(payload["new_oid"]),
                     "CORE_PUBLICATION_BINDING_INVALID")
            repository = numeric[:2]
            ref_directory = numeric[2:]
            exact_ref, old_oid, new_oid = payload["ref"], payload["old_oid"], payload["new_oid"]
        else:
            repository = ref_directory = exact_ref = old_oid = new_oid = None
        return CoreStartBinding(owner, operation_id, attempt_id, start_digest, intent_digest,
                                warrant.digest().removeprefix("sha256:"), state["reservation"], warrant.operation_hash,
                                state["epoch"], governor["epoch"], int(warrant.issued_at.timestamp()),
                                int(warrant.expires_at.timestamp()),
                                state["liability_id"], settled,
                                repository, ref_directory, exact_ref, old_oid, new_oid)

    def capture_start(self, principal, warrant):
        """Read the original START, including historical starts after revocation."""
        _require(type(warrant) is EffectWarrant, "CORE_WARRANT_REQUIRED")
        return self.journal._run(principal, Capability.COMMIT,
                                 lambda tx: self._read_binding(tx, warrant))

    def capture_pre_dispatch_candidate(self, principal, warrant):
        """Check current warrant status for diagnostics; still grants no release."""
        _require(type(warrant) is EffectWarrant, "CORE_WARRANT_REQUIRED")
        def read(tx):
            binding = self._read_binding(tx, warrant)
            _require(not binding.settled, "CORE_INTENT_ALREADY_SETTLED")
            self.journal.ledger.require_active_in_transaction(tx, warrant, consumed=True)
            return binding
        return self.journal._run(principal, Capability.COMMIT, read)

    @staticmethod
    def check_request(binding, request, enrollment, *, trusted_device_id,
                      core_epoch, broker_epoch, now, historical=False):
        """Check that an RH-02 request names the durable Core intent.

        A self-consistent fixture permit digest is only a digest. This function
        validates its shape and validity but intentionally returns no authority
        to execute the request.
        """
        from runtime.red_hat.broker_protocol import BrokerRequest
        from runtime.red_hat.enrollment import ExecutorEnrollment

        _require(type(binding) is CoreStartBinding and type(request) is BrokerRequest,
                 "BROKER_REQUEST_REQUIRED")
        _require(type(historical) is bool and type(enrollment) is ExecutorEnrollment,
                 "BROKER_ENROLLMENT")
        enrollment_time = request.issued_at if historical else now
        _require(enrollment.permits(request, enrollment_time),
                 "BROKER_ENROLLMENT")
        _require(type(trusted_device_id) is str and trusted_device_id,
                 "TRUSTED_DEVICE_BINDING_REQUIRED")
        expected = (
            request.operation_id == binding.operation_id,
            request.attempt_id == binding.attempt_id,
            request.owner_id == binding.owner_scope_digest,
            request.device_id == trusted_device_id,
            request.start_digest == binding.start_digest,
            request.intent_digest == binding.intent_digest,
            request.warrant_digest == binding.warrant_digest,
            request.reservation_digest == binding.reservation_digest,
            request.core_epoch == binding.core_epoch == core_epoch,
            request.broker_epoch == broker_epoch,
            request.executor_id == enrollment.executor.executor,
            request.executor_key_id == enrollment.executor.key_id,
            request.key_epoch == enrollment.key_epoch,
            binding.authorization_not_before <= request.issued_at < request.expires_at
            <= binding.authorization_expires_at,
            binding.repository is not None and request.repository == binding.repository,
            binding.ref_directory is not None and request.ref_directory == binding.ref_directory,
            binding.exact_ref is not None and request.exact_ref == binding.exact_ref,
            binding.old_oid is not None and request.old_oid == binding.old_oid,
            binding.new_oid is not None and request.new_oid == binding.new_oid,
        )
        _require(all(expected), "BROKER_CORE_BINDING")
        try:
            # Historical readback checks the original authorization's signed
            # time in the independent verifier; current wall time may be after
            # the short request permit window. Normal diagnostics remain live.
            request.require_permit(request.issued_at if historical else now)
        except (ValueError, TypeError):
            raise CoreAdapterError("BROKER_PERMIT_INVALID") from None
        return True

    @staticmethod
    def require_production_release(_binding, _request):
        """Do not replace Native's immediate Core pre-link release check."""
        raise CoreAdapterError("BLOCKED_SECURITY_REVIEW")

    @staticmethod
    def _verify_fresh_process(root_fd, request, enrollment, *, now, core_epoch, broker_epoch):
        """Exec the fixed verifier in a fresh process over the pinned root FD."""
        code = r'''import json, os, sys
from dataclasses import asdict
from runtime.red_hat.broker_protocol import BrokerRequest
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.verifier import verify
from runtime.red_hat.witness import RegisteredExecutor
v = json.load(sys.stdin)
r = BrokerRequest.from_wire(v["request"])
e = ExecutorEnrollment(RegisteredExecutor(v["executor"], v["uid"], v["spki"]),
                       v["key_epoch"], v["valid_from"], v["valid_until"], v["revoked"])
facts = asdict(verify(v["root_fd"], r, e, now=v["now"],
                     core_epoch=v["core_epoch"], broker_epoch=v["broker_epoch"]))
sys.stdout.write(json.dumps({"pid": os.getpid(), "facts": facts}, sort_keys=True))
'''
        spec = {
            "root_fd": root_fd,
            "request": request.to_wire(),
            "executor": enrollment.executor.executor,
            "uid": enrollment.executor.uid,
            "spki": enrollment.executor.spki,
            "key_epoch": enrollment.key_epoch,
            "valid_from": enrollment.valid_from,
            "valid_until": enrollment.valid_until,
            "revoked": enrollment.revoked,
            "now": now,
            "core_epoch": core_epoch,
            "broker_epoch": broker_epoch,
        }
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            completed = subprocess.run(
                [sys.executable, "-B", "-c", code], input=json.dumps(spec),
                text=True, capture_output=True, check=True, timeout=15,
                pass_fds=(root_fd,), cwd=repo_root,
                env={"PATH": os.defpath, "PYTHONNOUSERSITE": "1"},
            )
            value = json.loads(completed.stdout)
            _require(type(value) is dict and set(value) == {"pid", "facts"}
                     and type(value["pid"]) is int and value["pid"] != os.getpid()
                     and type(value["facts"]) is dict,
                     "INDEPENDENT_VERIFIER_PROTOCOL")
            from runtime.red_hat.verifier import Verification
            facts = value["facts"]
            boolean_fields = (
                "effect_observed", "producer_effect_sync_completed",
                "witness_bytes_verified", "witness_durable_at_readback",
                "producer_witness_sync_attested", "settlement_supported",
            )
            _require(set(facts) == set(Verification.__dataclass_fields__)
                     and all(type(facts[name]) is bool for name in boolean_fields)
                     and all(facts[name] is None or type(facts[name]) is str
                             and _HEX.fullmatch(facts[name])
                             for name in ("witness_sha256", "completion_sha256"))
                     and (facts["published_inode"] is None
                          or type(facts["published_inode"]) is list
                          and len(facts["published_inode"]) == 2
                          and all(type(item) is int and item > 0
                                  for item in facts["published_inode"]))
                     and (facts["published_ctime_ns"] is None
                          or type(facts["published_ctime_ns"]) is int
                          and facts["published_ctime_ns"] > 0),
                     "INDEPENDENT_VERIFIER_PROTOCOL")
            if facts["published_inode"] is not None:
                facts["published_inode"] = tuple(facts["published_inode"])
            return Verification(**facts), value["pid"]
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
            raise CoreAdapterError("INDEPENDENT_VERIFIER_FAILED") from None

    def recover_disposable_fixture(self, principal, warrant, request, enrollment, *,
                                    root_fd, trusted_device_id, now, core_epoch,
                                    broker_epoch):
        """Verify a disposable RH-02 repository and settle its original Core intent.

        This is a test integration seam. It rejects non-fixture repositories,
        obtains the verifier result itself, and never accepts a caller supplied
        ``Reconciliation`` or success Boolean.
        """
        from runtime.red_hat.broker_protocol import digest, read_record
        from runtime.red_hat.fixture_repository import open_dir, open_repository
        from runtime.red_hat.verifier import Verification

        binding = self.capture_start(principal, warrant)
        _require(binding.repository is not None and binding.ref_directory is not None
                 and binding.exact_ref is not None and binding.old_oid is not None
                 and binding.new_oid is not None, "CORE_PUBLICATION_BINDING_REQUIRED")
        self.check_request(binding, request, enrollment, trusted_device_id=trusted_device_id,
                           core_epoch=core_epoch, broker_epoch=broker_epoch, now=now,
                           historical=True)
        _require(type(root_fd) is int and root_fd >= 0, "FIXTURE_ROOT_REQUIRED")
        with ExitStack() as stack:
            target = stack.enter_context(
                open_repository(root_fd, request, enrollment.executor.uid))
            marker = read_record(target.repo, ".redhat-disposable", enrollment.executor.uid)
            _require(marker == b"AIOA_RED_HAT_FIXTURE_V1\n", "DISPOSABLE_REPOSITORY_REQUIRED")
            report, verifier_pid = self._verify_fresh_process(
                root_fd, request, enrollment, now=now,
                core_epoch=core_epoch, broker_epoch=broker_epoch)
            _require(type(report) is Verification and report.effect_observed
                     and report.producer_effect_sync_completed and report.witness_bytes_verified
                     and report.witness_durable_at_readback and report.producer_witness_sync_attested
                     and report.settlement_supported, "WITNESS_NOT_SETTLEMENT_GRADE")
            evidence = open_dir(root_fd, "evidence", stack)
            witness_id = request.witness_binding().witness_id
            witness = read_record(evidence, witness_id, enrollment.executor.uid, sync=True)
            completion = read_record(evidence, "completion-" + witness_id,
                                     enrollment.executor.uid, sync=True)
            stamp = target.observe(request)
            _require(type(report.published_inode) is tuple
                     and len(report.published_inode) == 2
                     and stamp[:2] == report.published_inode
                     and stamp[2] == report.published_ctime_ns
                     and hashlib.sha256(witness).hexdigest() == report.witness_sha256
                     and hashlib.sha256(completion).hexdigest() == report.completion_sha256,
                     "VERIFIED_READBACK_IDENTITY_CHANGED")
            target.check(request)
            readback_bytes = canonical_json_bytes({
                "schema": "aioa.redhat.fixture-independent-readback.v1",
                "request_digest": digest(request.to_wire()),
                "ref": request.exact_ref,
                "published_inode": stamp[:2],
                "published_ctime_ns": stamp[2],
            })
            receipt_digest = hashlib.sha256(witness + completion).hexdigest()
            readback_digest = hashlib.sha256(readback_bytes).hexdigest()
        receipt = EvidenceRef("redhat-witness-" + witness_id[:32], "receipt",
                             "sha256:" + receipt_digest, "aioa.native-cas-witness.v1")
        readback = EvidenceRef("redhat-readback-" + witness_id[:32], "independent-readback",
                              "sha256:" + readback_digest, "aioa.redhat.fixture-verifier.v1")
        resolution = Reconciliation(warrant.operation_hash, Applied(receipt.evidence_id),
                                    receipt, readback)

        def settle(tx):
            # Recheck the disposable physical object and authenticated records
            # inside the Core transaction immediately before settlement. This
            # narrows, but cannot atomically close, the filesystem/Core commit
            # interval.
            from runtime.red_hat.broker_protocol import read_record
            from runtime.red_hat.fixture_repository import open_dir, open_repository

            with ExitStack() as settle_stack:
                settle_target = settle_stack.enter_context(
                    open_repository(root_fd, request, enrollment.executor.uid))
                marker_now = read_record(
                    settle_target.repo, ".redhat-disposable", enrollment.executor.uid)
                _require(marker_now == b"AIOA_RED_HAT_FIXTURE_V1\n",
                         "DISPOSABLE_REPOSITORY_REQUIRED")
                evidence_now = open_dir(root_fd, "evidence", settle_stack)
                witness_now = read_record(
                    evidence_now, witness_id, enrollment.executor.uid, sync=True)
                completion_now = read_record(
                    evidence_now, "completion-" + witness_id,
                    enrollment.executor.uid, sync=True)
                stamp_now = settle_target.observe(request)
                _require(stamp_now == stamp
                         and hashlib.sha256(witness_now).hexdigest()
                         == report.witness_sha256
                         and hashlib.sha256(completion_now).hexdigest()
                         == report.completion_sha256,
                         "VERIFIED_READBACK_IDENTITY_CHANGED")
                settle_target.check(request)
            current = self._read_binding(tx, warrant)
            same_start = replace(current, settled=binding.settled) == binding
            monotonic = not binding.settled or current.settled
            _require(same_start and monotonic, "CORE_START_CHANGED")
            return self.journal.apply_resolution_in_transaction(
                tx, warrant, binding.settlement_epoch, resolution)

        result = self.journal._run(principal, Capability.COMMIT, settle)
        return {**result, "verification_process_pid": verifier_pid}
