#!/usr/bin/env python3
"""Deterministic AIOA spArkHAT competition vertical slice.

This source-checkout demo composes existing production runtime contracts with
controlled local test transports. It never claims TEST_FIXTURE output is LIVE.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
for value in (REPO, REPO / "runtime", TESTS):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from nv05_demo import execute as memory_episode  # noqa: E402
from nv09_support import GuardFixture, LocalTarget  # noqa: E402


def _require_fresh(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        raise RuntimeError("DEMO_ROOT_MUST_BE_FRESH")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)


def run_demo(root: Path) -> dict:
    _require_fresh(root)
    memory_root = root / "memory"
    episodes = [memory_episode(memory_root, number) for number in (1, 2, 3)]

    target = LocalTarget(root / "target", target_id="competition-disposable-service")
    try:
        effect_root = root / "effect-runtime"
        first = GuardFixture(effect_root, target.client, operation_id="competition-effect")
        try:
            approval = first.approve()
            effect = first.tick()
            measured = target.client.read()
            effect_evidence = first.inspect()
        finally:
            first.close()
        restarted = GuardFixture(effect_root, target.client, operation_id="competition-effect")
        try:
            replay = restarted.tick()
            after_replay = target.client.read()
            replay_evidence = restarted.inspect()
        finally:
            restarted.close()
    finally:
        target.close()

    if not (
        episodes[0]["runtime_class"] == "AgentRuntime"
        and episodes[0]["provider_path"] == "NVIDIA_ADAPTER_FIXTURE_AND_ORIGINAL_CPL_HTTP"
        and episodes[0]["execution_authority"] is False
        and episodes[0]["new_delta_count"] == 1
        and episodes[0]["cpl"]["knowledge_write"] == "CREATED"
        and episodes[1]["new_delta_count"] == 0
        and episodes[1]["cpl"]["status"] == "ZERO_WRITE"
        and episodes[2]["reuse_status"] == ["REVALIDATION_REQUIRED"]
        and effect["status"] == "VERIFIED"
        and effect["verified_effect"] is True
        and measured["effect_count"] == 1
        and replay["status"] == "REPLAY"
        and replay["dispatch_attempted"] is False
        and after_replay["effect_count"] == 1
        and effect_evidence["receipt"]["transport_result"] == "TARGET_DURABLY_APPLIED"
        and effect_evidence["receipt"]["reconciliation_state"] == "COMMITTED_BY_TARGET_RECEIPT"
        and effect_evidence["verified"]["measurement"]["mode"] == "MAINTENANCE"
        and effect_evidence["verified"]["measurement"]["effect_count"] == 1
        and replay_evidence["verified"] == effect_evidence["verified"]
    ):
        raise RuntimeError("COMPETITION_VERTICAL_SLICE_CONTRACT_FAILED")

    events = [
        {"stage": "observe", "status": "OBSERVED", "authority": "DATA_ONLY"},
        {"stage": "evidence_hat", "status": "READY", "authority": "ADVISORY_ONLY"},
        {"stage": "nemotron_proposal", "status": "TEST_FIXTURE", "authority": "ADVISORY_ONLY"},
        {"stage": "cpl_review", "status": episodes[0]["cpl"]["status"],
         "authority": "ADVISORY_ONLY"},
        {"stage": "verified_delta_reuse", "status": episodes[1]["cpl"]["status"],
         "authority": "ADVISORY_ONLY"},
        {"stage": "stale_source_revalidation", "status": episodes[2]["reuse_status"][0],
         "authority": "CORE_POLICY"},
        {"stage": "core_authority_gate", "status": "HUMAN_APPROVAL_REQUIRED",
         "authority": "CORE_POLICY"},
        {"stage": "scheduler_boundary", "status": "AGENT_RUNTIME_OWNED",
         "authority": "COORDINATION_ONLY"},
        {"stage": "human_approval", "status": "BOUND", "authority": "HUMAN"},
        {"stage": "service_guard_effect", "status": effect["status"], "authority": "CORE_GATE"},
        {"stage": "durable_receipt", "status": effect_evidence["receipt"]["reconciliation_state"],
         "authority": "EVIDENCE_ONLY"},
        {"stage": "independent_verification", "status": measured["mode"], "authority": "MEASUREMENT"},
        {"stage": "durable_memory_audit", "status": "PERSISTED", "authority": "EVIDENCE_ONLY"},
        {"stage": "restart_replay", "status": replay["status"], "authority": "CORE_REPLAY_BARRIER"},
    ]

    return {
        "schema": "aioa.nvidia-competition-demo.v1",
        "product_name": "AIOA spArkHAT",
        "execution_mode": "TEST_FIXTURE",
        "live_provider_claimed": False,
        "provider_status": "EXTERNAL_UNAVAILABLE_OR_NOT_USED",
        "runtime_factory": "AgentRuntime",
        "task_success_rate": 1.0,
        "scenario_count": len(events),
        "events": events,
        "mission": {
            "snapshot_state": "COMPLETE",
            "heartbeat_state": "COMPLETED_EVIDENCE_SNAPSHOT",
            "last_stage": "restart_replay",
            "restart_recovery": "VERIFIED_REPLAY",
            "runtime_factory": "AgentRuntime",
        },
        "memory": {
            "first_write": episodes[0]["new_delta_count"],
            "reuse_zero_write": episodes[1]["new_delta_count"] == 0,
            "stale_revalidation": episodes[2]["reuse_status"][0],
            "dvm_pheromone_mode": "CONTROLLED_TEST_ONLY",
        },
        "effect": {
            "status": effect["status"],
            "verified_effect": effect["verified_effect"],
            "dispatch_attempted": effect["dispatch_attempted"],
            "effect_count": measured["effect_count"],
            "replay_status": replay["status"],
            "replay_dispatch_attempted": replay["dispatch_attempted"],
            "effect_count_after_replay": after_replay["effect_count"],
            "approval_bound": bool(approval),
            "receipt_transport_result": effect_evidence["receipt"]["transport_result"],
            "receipt_reconciliation_state": effect_evidence["receipt"]["reconciliation_state"],
            "receipt_effect_count": effect_evidence["receipt"]["effect_count"],
            "receipt_digest": effect_evidence["verified"]["receipt_digest"],
            "independent_measurement_mode": effect_evidence["verified"]["measurement"]["mode"],
            "independent_measurement_effect_count": effect_evidence["verified"]["measurement"]["effect_count"],
            "measurement_digest": effect_evidence["verified"]["measurement_digest"],
            "verified_record_persisted": effect_evidence["verified"]["verified_effect"] is True,
            "replay_verified_record_persisted": replay_evidence["verified"] == effect_evidence["verified"],
        },
        "safety": {
            "provider_output_authority": False,
            "duplicate_effects": after_replay["effect_count"] - 1,
            "hidden_chain_of_thought_recorded": False,
            "human_bound_effect_authority": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    value = run_demo(args.root)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        args.output.write_text(raw, encoding="utf-8")
    print(raw, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
