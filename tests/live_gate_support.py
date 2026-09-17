"""Shared TEST-only permit fixture; it cannot authorize HTTPTransport."""

from __future__ import annotations

from pathlib import Path

from runtime.mission.lite_contracts import MODEL
from runtime.providers.live_gate import (
    LiveCallGate,
    LocalGateResult,
    PermitUsageLedger,
    issue_test_permit,
)


TEST_GIT_SHA = "1" * 40
TEST_WORKTREE_DIGEST = "2" * 64
TEST_SUITE_DIGEST = "3" * 64


def test_live_gate(
    root: Path,
    *,
    clock=lambda: 2_000_000_000,
    max_calls: int = 100_000,
) -> LiveCallGate:
    root.mkdir(parents=True, exist_ok=True)
    decision = issue_test_permit(
        permit_id="g07-b-contract-test-permit",
        phase="G07-B-TEST",
        git_sha=TEST_GIT_SHA,
        worktree_digest=TEST_WORKTREE_DIGEST,
        local_gate=LocalGateResult("PASS", TEST_SUITE_DIGEST),
        issued_at=1,
        expires_at=4_102_444_800,
        max_live_calls=max_calls,
        provider_id="nvidia",
        model_id=MODEL,
    )
    if decision.phase_status != "PASS" or decision.permit is None:
        raise AssertionError("passing TEST gate did not issue a TEST permit")
    return LiveCallGate(
        decision.permit,
        source_reader=lambda: (
            TEST_GIT_SHA,
            TEST_WORKTREE_DIGEST,
            TEST_SUITE_DIGEST,
        ),
        usage_ledger=PermitUsageLedger((root / "test-live-permit-usage.sqlite3").resolve()),
        clock=lambda: int(clock()),
    )
