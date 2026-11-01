"""META-MVP-01 offline mission runner (Muse-authored integration seam).

Deterministic OFFLINE research mission reusing existing contracts only:
trusted-host fixture owner scope -> Core READ admission -> validated
BrowserTaskV1 (via existing Muse plan parser) -> OfflineFixtureAdapter
observation (no live browser) -> OfflineReceiptLedger mock receipt ->
OfflineCorrelationLedger provenance -> ONE bounded JSON summary on stdout.

Stdlib only. No network, no browser, no provider calls. Later authorized
LIVE transports replace only the adapters; this seam stays.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone

from runtime.browser_agent.offline_adapter import (
    FIXTURE_TEXT,
    FIXTURE_URL,
    OfflineFixtureAdapter,
)
from runtime.core_admission import (
    AdmissionError,
    Capability,
    CoreAdmission,
    LocalOwnerAssignment,
    OwnerScope,
)
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.meta_hackathon.contracts import MetaContractError
from runtime.meta_hackathon.muse_plan import parse_muse_plan
from runtime.meta_hackathon.offline_correlation import OfflineCorrelationLedger
from runtime.meta_hackathon.offline_receipts import (
    MOCK_RESPONSE_SCHEMA,
    OfflineReceiptLedger,
    BudgetReservation,
)
from runtime.meta_hackathon.provider_offline import (
    OFFLINE_MODEL,
    build_offline_envelope,
)

SUMMARY_SCHEMA = "aioa.meta.mvp-mission-summary.v1"
DEMO_SOURCE_SHA = "9ee80c635f6cb2fea13613152188220a2fa90564"
DEMO_NOW_UTC = "2026-06-01T12:35:00Z"
DEMO_CAPTURED_AT_UTC = "2026-06-01T12:00:00Z"
DEMO_DEADLINE_UTC = "2026-06-02T12:00:00Z"
DEMO_ORIGIN = "https://docs.example.org"
DEMO_INSTRUCTION = "Summarize the fixture document in one short paragraph."


def _demo_scope() -> OwnerScope:
    return OwnerScope(
        tenant_id="demo-tenant",
        owner_id="demo-owner",
        space_id="demo-space",
        slot_id="demo-slot",
    )


def _demo_assignment(scope: OwnerScope, *, without_read: bool = False) -> LocalOwnerAssignment:
    caps = {Capability.CANDIDATE} if without_read else {Capability.READ}
    return LocalOwnerAssignment(
        scope=scope,
        allowed_capabilities=frozenset(caps),
        hat_ids=frozenset({"demo-hat"}),
        model_binding_ids=frozenset({"muse-spark-1.3"}),
        revision=1,
        operator_approved=True,
        hosted_multi_user=False,
    )


def _nonce() -> str:
    return hashlib.sha256(b"meta-mvp-01-demo-nonce").hexdigest()


def run_offline_demo(
    *,
    stopped: bool = False,
    owner_scope_digest: str | None = None,
    source_sha: str | None = None,
    without_read: bool = False,
    now_utc: str = DEMO_NOW_UTC,
) -> dict:
    """Execute the deterministic offline mission; fail closed on any drift.

    Binding (owner digest, source SHA, origins) comes only from trusted-host
    values built here. Model/page-shaped inputs never mint authority.
    Raises (AdmissionError/MetaContractError/adapter denial) on STOP,
    expiry, wrong owner, wrong SHA, or missing Core READ.
    """
    if type(stopped) is not bool or type(without_read) is not bool:
        raise MetaContractError("META_GATE_INPUT_DENIED")
    scope = _demo_scope()
    admission = CoreAdmission(_demo_assignment(scope, without_read=without_read))
    # Core READ admission executes here and fails closed without READ.
    principal = admission.local_operator(Capability.READ)
    bound_scope = admission.require(principal, Capability.READ, scope=scope)

    core_digest = canonical_sha256(bound_scope)
    core_sha = DEMO_SOURCE_SHA
    if owner_scope_digest is None:
        owner_scope_digest = core_digest
    if source_sha is None:
        source_sha = core_sha
    now = datetime.fromisoformat(now_utc[:-1] + "+00:00")
    if now.tzinfo is None:
        raise MetaContractError("META_TIME_DENIED")

    plan = {
        "tool": "browser.navigate_read",
        "task_id": "meta-mvp-01-demo",
        "target_url": FIXTURE_URL,
        "deadline_utc": DEMO_DEADLINE_UTC,
        "max_pages": 1,
        "timeout_ms": 8000,
        "max_chars": 3000,
    }
    task = parse_muse_plan(
        plan,
        core_owner_scope_digest=owner_scope_digest,
        core_source_sha=source_sha,
        allowed_origins=(DEMO_ORIGIN,),
        stopped=stopped,
        now=now,
    )
    # Independent Core gate: the task must still match this host's binding.
    if task.owner_scope_digest != core_digest or task.source_sha != core_sha:
        raise MetaContractError("META_TASK_MISMATCH")

    adapter = OfflineFixtureAdapter()
    observation = adapter.read(
        task,
        admission=admission,
        principal=principal,
        scope=bound_scope,
        core_owner_scope_digest=core_digest,
        core_source_sha=core_sha,
        stopped=stopped,
        now=now,
    )

    envelope = build_offline_envelope(task, DEMO_INSTRUCTION, budget_usd_limit=1.0)
    nonce = _nonce()
    reservation = BudgetReservation(
        task_digest=task.digest,
        owner_scope_digest=core_digest,
        source_sha=core_sha,
        model=OFFLINE_MODEL,
        attempt_id="demo-attempt-01",
        nonce=nonce,
        issued_at_utc="2026-06-01T12:30:00Z",
        expires_at_utc="2026-06-01T12:40:00Z",
        max_output_tokens=128,
        max_usd="0.10",
    )
    mock_response = json.dumps(
        {
            "schema": MOCK_RESPONSE_SCHEMA,
            "model": OFFLINE_MODEL,
            "task_digest": task.digest,
            "owner_scope_digest": core_digest,
            "source_sha": core_sha,
            "attempt_id": "demo-attempt-01",
            "nonce_sha256": reservation.nonce_sha256,
            "completion_tokens": 32,
            "status": "MOCK_DONE",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    receipt = OfflineReceiptLedger(max_total_usd="1.00").record_once(
        reservation,
        envelope,
        mock_response_json=mock_response,
        mock_cost_usd="0.02",
        now_utc=now_utc,
        stopped=stopped,
    )
    proof = OfflineCorrelationLedger().correlate_once(
        task,
        observation,
        receipt,
        observed_content=FIXTURE_TEXT,
        now_utc=now_utc,
        stopped=stopped,
    )
    if proof.status not in ("OFFLINE_LINKED_UNVERIFIED", "UNKNOWN"):
        raise MetaContractError("META_CORRELATION_EVIDENCE_DENIED")
    return {
        "schema": SUMMARY_SCHEMA,
        "task_digest": task.digest,
        "owner_scope_digest": core_digest,
        "owner_binding": list(bound_scope.binding()),
        "source_sha": core_sha,
        "source_sha_note": "demo-synthetic-value",
        "terminal_state": observation.status,
        "evidence_digest": proof.digest,
        "content_sha256": observation.content_sha256,
        "status": proof.status,
        "environment": proof.environment,
        "model": OFFLINE_MODEL,
        "verified": False,
        "dispatch_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline META MVP-01 demo mission.")
    parser.add_argument("--demo", action="store_true", required=True)
    args = parser.parse_args(argv)
    if not args.demo:
        parser.print_usage(sys.stderr)
        return 2
    try:
        summary = run_offline_demo()
    except (AdmissionError, MetaContractError, ValueError) as exc:
        fallback = {
            "schema": SUMMARY_SCHEMA,
            "status": "UNKNOWN",
            "environment": "OFFLINE_FIXTURE",
            "terminal_state": "DENIED",
            "verified": False,
            "dispatch_allowed": False,
            "error": type(exc).__name__,
        }
        print(json.dumps(fallback, sort_keys=True, separators=(",", ":")))
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
