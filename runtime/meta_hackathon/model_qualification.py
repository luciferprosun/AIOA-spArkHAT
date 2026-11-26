"""Owner-only qualification of one fixed, paid WorkerPort advice call.

No runtime configuration enables a call on its own. The existing Native owner
reviews the entire spend proposal, then signs its exact digest in a separate
operator request. Core records a single fixed approval nonce for this campaign.
"""

import hashlib
import os
import stat
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.outcome import Applied
from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.governor import ReservationRequest
from runtime.mission.liability import Reconciliation
from runtime.mission.patchset import BoundedPatchSetPolicy, observe_source
from runtime.mission.qualified_worker import (
    MAX_COST_NANO,
    MODEL,
    QualifiedModelWorker,
    worker_lease_digest,
)
from runtime.mission.warrant import KIND as WARRANT_KIND, approval_digest, require
from runtime.mission.worker import CandidateFile, CandidatePatch, Task, WorkerResult
from runtime.mobile_gateway import wire
from runtime.mobile_gateway.service import plain
from runtime.providers.live_gate import (
    LiveCallGate,
    LocalGateResult,
    PermitUsageLedger,
    RepositorySourceStateReader,
    issue_live_permit,
)

OPS = frozenset(
    ("worker_model_prepare", "worker_model_approve", "worker_model_readback")
)
TASK = "nonzero-model-B-20261126"
NONCE = "nonce-" + TASK
RECEIPT = "verified-" + TASK
FILE = "agent-demo/qualification.txt"
CONTENT = "Qualified advice.\n"
PRICE = (
    "https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference"
)
LICENSE_DIGEST = "a039f83d1d59d97624c355653e0eab74a45b867a091d3d10d12ac1183535e14c"


def _billing(host):
    from .native_authority import _private_bytes

    directory = host.root / "worker-model"
    info = directory.lstat()
    require(
        directory.resolve() == directory
        and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and info.st_mode & 0o077 == 0,
        "WORKER_PRIVATE_DIRECTORY_REQUIRED",
    )
    data = wire.strict_json(_private_bytes(str(directory / "billing.json"), 4096))
    keys = {
        "schema",
        "provider",
        "model",
        "currency",
        "source_url",
        "input_nano_per_token",
        "output_nano_per_token",
        "additional_fees",
        "available_nano_usd",
        "reviewed_at",
        "account_evidence_sha256",
    }
    require(
        set(data) == keys
        and data["schema"] == "aioa.worker-account-review.v1"
        and data["provider"] == "nebius"
        and data["model"] == MODEL
        and data["currency"] == "USD"
        and data["source_url"] == PRICE
        and data["additional_fees"] is False
        and type(data["input_nano_per_token"]) is int
        and 0 < data["input_nano_per_token"] <= 60
        and type(data["output_nano_per_token"]) is int
        and 0 < data["output_nano_per_token"] <= 240
        and type(data["available_nano_usd"]) is int
        and data["available_nano_usd"] >= MAX_COST_NANO
        and type(data["reviewed_at"]) is int
        and 0 <= time.time() - data["reviewed_at"] <= 86400
        and data["account_evidence_sha256"]
        == hashlib.sha256(
            _private_bytes(str(directory / "account-review.bin"), 65536)
        ).hexdigest(),
        "WORKER_ACCOUNT_REVIEW_REQUIRED",
    )
    return data


def _workspace(live_source, task, session=None, candidate=None):
    """Two independent trees. Only the fixed inert qualification file can reach disk."""
    from .runtime_adapter import ROOT

    license_bytes = (ROOT / "LICENSE").read_bytes()
    require(
        hashlib.sha256(license_bytes).hexdigest() == LICENSE_DIGEST,
        "WORKER_WORKSPACE_CHANGED",
    )
    with tempfile.TemporaryDirectory(prefix="aioa-worker-qualification-") as temp:
        root = Path(temp)
        base = root / "base"
        base.mkdir(mode=0o700)
        (base / "LICENSE").write_bytes(license_bytes)
        (base / "LICENSE").chmod(0o644)
        source = observe_source(
            base,
            workspace_id=task.workspace_id,
            repository_id=task.repository_id,
            source_base_sha=live_source,
        )
        if candidate is None:
            return source.base_tree_sha256
        require(
            candidate == CandidatePatch((CandidateFile(FILE, CONTENT),)),
            "WORKER_ORACLE_DENIED",
        )
        policy = BoundedPatchSetPolicy()
        preview, _ = policy.preview(
            base,
            source=source,
            task=task,
            worker_session_id=session.session_id,
            candidate=candidate,
        )
        final = root / "observed"
        final.mkdir(mode=0o700)
        (final / "LICENSE").write_bytes(license_bytes)
        (final / "LICENSE").chmod(0o644)
        (final / "agent-demo").mkdir(mode=0o700)
        (final / FILE).write_bytes(CONTENT.encode())
        (final / FILE).chmod(0o644)
        observed = policy.evaluate(
            base, final, source=source, task=task, worker_session_id=session.session_id
        )
        require(
            observed == preview and (final / FILE).read_bytes() == CONTENT.encode(),
            "WORKER_PATCHSET_READBACK",
        )
        return observed


def _warrant(host, task, operation, epoch, evidence):
    now = host.ledger.clock()
    end = datetime.fromtimestamp(
        min(task.deadline_at, time.time() + host._auth_deadline - time.monotonic()), UTC
    )
    scope = AuthorityScope(
        (operation["operation_class"],),
        operation["target_fingerprint"],
        RiskLevel.MODERATE,
        Money(Decimal(MAX_COST_NANO) / 10**9, "USD"),
        now,
        end,
        canonical_sha256(host.missions.scope),
        task.task_id,
    )
    root = DecisionDependencyRoot(
        tuple(
            EvidenceRef(k, k, "sha256:" + v, "v1") for k, v in sorted(evidence.items())
        )
    )
    paired = "paired-" + TASK
    warrant = EffectWarrant(
        warrant_id="warrant-" + TASK,
        task_id=task.task_id,
        owner_scope=scope.owner_scope,
        operation_class=operation["operation_class"],
        operation_hash="sha256:" + canonical_sha256(operation),
        target_fingerprint=operation["target_fingerprint"],
        expected_target_revision=operation["expected_target_revision"],
        revision_policy=RevisionPolicy.REQUIRE,
        decision_dependency_root=root,
        lease_epoch=epoch,
        authority_scope=scope,
        approval_digest="sha256:" + "0" * 64,
        money_reservation_id=paired,
        risk_reservation_id=paired,
        nonce=NONCE,
        issued_at=now,
        expires_at=end,
    )
    return replace(warrant, approval_digest=approval_digest(warrant))


def _review(host):
    host.foundation.require_bindings()
    host.missions._native_execution_gate()
    principal = host.core.local_operator(Capability.COMMIT)
    require(
        MODEL in principal.model_binding_ids
        and host.foundation.spec.to_dict()["profile"] == "OWNED_WORKER_MODEL_B_V1",
        "WORKER_ENROLLED_MODEL_REQUIRED",
    )
    read = host.core.local_operator(Capability.READ)
    state = host.foundation.governor.inspect(read)
    require(
        state["epoch"] > 0
        and not state["kill"]
        and all(x["state"] != "UNKNOWN" for x in state["reservations"].values()),
        "WORKER_SCOPE_OR_BUDGET_UNAVAILABLE",
    )
    key = os.environ.get("NEBIUS_API_KEY")
    require(type(key) is str and key, "WORKER_PROVIDER_HANDLE_UNAVAILABLE")
    billing = _billing(host)
    reader = RepositorySourceStateReader()
    source, _, suite = reader()
    require(source == host.source[0], "WORKER_SOURCE_CHANGED")
    now = int(time.time())
    permit = issue_live_permit(
        permit_id=TASK,
        phase="GO_MODEL_TEST",
        local_gate=LocalGateResult("PASS", suite),
        issued_at=now,
        expires_at=now + 60,
        max_live_calls=1,
        provider_id="nebius",
        model_id=MODEL,
    ).permit
    usage_path = host.root / "worker-model" / "permit-usage.sqlite3"
    try:
        os.close(
            os.open(
                usage_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        )
    except FileExistsError:
        info = usage_path.lstat()
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and info.st_nlink == 1
            and info.st_mode & 0o077 == 0,
            "WORKER_PRIVATE_LEDGER_REQUIRED",
        )
    gate = LiveCallGate(
        permit,
        source_reader=reader,
        usage_ledger=PermitUsageLedger(usage_path),
        clock=lambda: int(time.time()),
    )
    task = Task(
        TASK,
        "run-" + TASK,
        "license-projection",
        "source-repository",
        source,
        "Propose only "
        + FILE
        + " containing exactly Qualified advice. followed by a newline.",
        now + 60,
        max_output_tokens=256,
    )
    base = _workspace(source, task)
    worker = QualifiedModelWorker.live(
        task,
        gate=gate,
        api_key=key,
        capsule_digest=host.source[1],
        lease_digest=worker_lease_digest(principal, state["epoch"]),
        price_checked_at=billing["reviewed_at"],
    )
    operation = worker.operation(principal, state["epoch"])
    evidence = {"billing": canonical_sha256(billing), "workspace": base, "suite": suite}
    warrant = _warrant(host, task, operation, state["epoch"], evidence)
    request = ReservationRequest(
        "paired-" + TASK,
        TASK,
        "nebius",
        MODEL,
        canonical_sha256(operation),
        MAX_COST_NANO,
        1,
    )
    proof = worker.approval_proof(principal, warrant, request)
    review = {
        "command": "GO_MODEL_TEST",
        "proof": proof,
        "billing": billing,
        "workspace_sha256": base,
        "max_calls": 1,
        "max_input_units": 2048,
        "max_completion_tokens": 256,
        "max_repairs": 0,
        "max_retries": 0,
        "max_wall_seconds": 60,
        "expires_at": int(warrant.expires_at.timestamp()),
    }
    return review, (task, worker, principal, warrant, request)


def _verified(host, task, worker, session, warrant, review):
    # Read the original persisted producer record independently of the mailbox.
    journal = host.intent_journal
    read = host.core.local_operator(Capability.READ)
    row = journal._run(
        read,
        Capability.READ,
        lambda tx: tx.get(
            RecordKind.RECEIPT, "worker-" + canonical_sha256(warrant.digest())
        ),
    )
    require(row is not None, "WORKER_RECEIPT_REQUIRED")
    packet = plain(row.payload)
    receipt = packet["receipt"]
    wire.verify(host.identity.spki, packet["signature"], receipt)
    result = worker.result(session)
    require(
        type(result) is WorkerResult
        and result.authority == "NONE"
        and not result.verified
        and receipt["scope"] == "LIVE"
        and receipt["warrant_digest"] == warrant.digest()
        and receipt["operation_hash"] == warrant.operation_hash
        and receipt["model"] == MODEL
        and receipt["permit_digest"] == worker.gate.permit.permit_digest
        and receipt["worker_session_id"] == session.session_id
        and receipt["task_digest"] == task.digest
        and receipt["candidate_digest"] == result.candidate.digest
        and receipt["mailbox_status"] == "SUCCEEDED",
        "WORKER_ORIGINAL_CANDIDATE_REQUIRED",
    )
    patch = _workspace(task.source_base_sha, task, session, result.candidate)
    require(
        patch.base_tree_sha256 == review["workspace_sha256"], "WORKER_PROJECT_CHANGED"
    )
    usage = receipt["usage"]
    bill = review["billing"]
    estimate = (
        usage["prompt_tokens"] * bill["input_nano_per_token"]
        + usage["completion_tokens"] * bill["output_nano_per_token"]
    )
    require(0 < estimate <= MAX_COST_NANO, "WORKER_CHARGE_BOUND")
    proof = {
        "schema": "aioa.worker-qualified-readback.v1",
        "receipt_digest": canonical_sha256(receipt),
        "warrant_digest": warrant.digest(),
        "source_sha": host.source[0],
        "patchset_digest": patch.patchset_sha256,
        "final_tree_sha256": patch.final_tree_sha256,
        "account_review_digest": canonical_sha256(bill),
        "usage": usage,
        "estimated_nano_usd": estimate,
        "governor_reserved_nano_usd": MAX_COST_NANO,
        "request_id_sha256": receipt["request_id_sha256"],
        "candidate_authority": "NONE",
        "repairs": 0,
        "redispatch": False,
    }
    signed = {"proof": proof, "signature": host.identity.sign(proof)}
    receipt_ref = EvidenceRef(
        "worker-provider-B", "receipt", "sha256:" + canonical_sha256(receipt), "v1"
    )
    readback_ref = EvidenceRef(
        "worker-patchset-B",
        "independent-readback",
        "sha256:" + canonical_sha256(proof),
        "v1",
    )
    resolution = Reconciliation(
        warrant.operation_hash,
        Applied(receipt_ref.evidence_id),
        receipt_ref,
        readback_ref,
    )
    principal = host.core.local_operator(Capability.COMMIT)

    def settle(tx):
        require(time.time() < task.deadline_at, "WORKER_QUALIFICATION_DEADLINE")
        journal.apply_resolution_in_transaction(
            tx, warrant, warrant.lease_epoch, resolution
        )
        tx.insert(
            StoredRecord(RecordKind.RECEIPT, RECEIPT, journal.ledger.scope, 1, signed)
        )

    journal._run(principal, Capability.COMMIT, settle)
    return signed


def _readback(host):
    journal = host.intent_journal
    principal = host.core.local_operator(Capability.READ)
    key = canonical_sha256((WARRANT_KIND, journal.ledger.scope, NONCE))

    def read(tx):
        approved = tx.get(RecordKind.OPERATION, key)
        if approved is None:
            return {"state": "NOT_STARTED", "redispatch": False}
        warrant = EffectWarrant.from_dict(plain(approved.payload)["active"])
        _, intent = journal._load(tx, warrant)
        if intent is None:
            return {"state": "APPROVED_NO_START", "redispatch": False}
        if intent["resolution"] is None:
            return {"state": "UNKNOWN_HELD", "redispatch": False}
        row = tx.get(RecordKind.RECEIPT, RECEIPT)
        require(row is not None, "WORKER_READBACK_REQUIRED")
        signed = plain(row.payload)
        wire.verify(host.identity.spki, signed["signature"], signed["proof"])
        ref = canonical_sha256(warrant.digest())
        original = tx.get(RecordKind.RECEIPT, "worker-" + ref)
        release = tx.get(RecordKind.RECEIPT, "worker-release-" + ref)
        require(
            original is not None and release is not None,
            "WORKER_ORIGINAL_PROOFS_REQUIRED",
        )
        packet = plain(original.payload)
        admitted = plain(release.payload)
        wire.verify(host.identity.spki, packet["signature"], packet["receipt"])
        wire.verify(host.identity.spki, admitted["signature"], admitted["proof"])
        require(
            admitted["proof"]["warrant_digest"] == warrant.digest()
            and admitted["proof"]["operation"] == intent["operation"]
            and admitted["proof"]["reservation_digest"] == intent["reservation"]
            and signed["proof"]["receipt_digest"] == canonical_sha256(packet["receipt"])
            and packet["receipt"]["warrant_digest"] == warrant.digest()
            and intent["resolution"]["receipt"]["digest"]
            == "sha256:" + canonical_sha256(packet["receipt"]),
            "WORKER_ORIGINAL_PROOF_BINDING",
        )
        require(
            signed["proof"]["warrant_digest"] == warrant.digest()
            and intent["resolution"]["readback"]["digest"]
            == "sha256:" + canonical_sha256(signed["proof"]),
            "WORKER_READBACK_BINDING",
        )
        return signed

    return journal._run(principal, Capability.READ, read)


def dispatch(host, owner, value):
    host.core.require(owner, Capability.OWNER_APPROVAL, scope=host.missions.scope)
    host._require_qualified_operator()
    require(
        host.foundation is not None
        and host._existing_profile is not None
        and host.foundation.spec.to_dict()["profile"] == "OWNED_WORKER_MODEL_B_V1",
        "WORKER_EXISTING_NATIVE_HOST_REQUIRED",
    )
    op = value["op"]
    require(
        op in OPS
        and set(value)
        == ({"op", "review_digest"} if op == "worker_model_approve" else {"op"}),
        "WORKER_OPERATOR_SCHEMA",
    )
    if op == "worker_model_readback":
        return _readback(host)
    host.missions._native_execution_gate()
    if op == "worker_model_prepare":
        saved = _readback(host)
        require(saved.get("state") == "NOT_STARTED", "WORKER_READBACK_ONLY")
        review, prepared = _review(host)
        with host.missions._lock:
            host._qualification_worker = (review, prepared)
        return {"review": review, "review_digest": canonical_sha256(review)}
    with host.missions._lock:
        saved = getattr(host, "_qualification_worker", None)
        require(
            saved is not None and canonical_sha256(saved[0]) == value["review_digest"],
            "WORKER_REVIEW_CHANGED",
        )
        host._qualification_worker = None
    review, (task, worker, principal, warrant, request) = saved
    require(
        time.time() < review["expires_at"] and _billing(host) == review["billing"],
        "WORKER_REVIEW_EXPIRED",
    )
    journal = host.intent_journal
    host.ledger.approve(owner, warrant)
    worker.bind(
        journal,
        principal,
        warrant,
        request,
        native_host=host,
        approval_signature=host.identity.sign(review["proof"]),
    )
    try:
        session = worker.start(task)
        worker.poll(session)
        return _verified(host, task, worker, session, warrant, review)
    finally:
        worker.close()
