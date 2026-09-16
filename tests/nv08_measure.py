"""Produce bounded, reproducible NV08 fixture measurements as JSON.

This runner never labels its file-backed test adapter as Cockroach/live.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

from nv07_support import ChatFixture, QUESTION, RIGHT


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def fresh(root):
    fixture = ChatFixture(root, replies=(RIGHT,), dynamics=True)
    try:
        context = fixture.runtime.lite_memory_retrieve(QUESTION)
        snapshot = fixture.learning.dynamics.index.snapshot
        return {
            "prompt_json": context.prompt_json,
            "selected_refs": [value.reference_id for value in context.selected],
            "index_digest": snapshot.snapshot_digest,
            "index_refs": [value.reference_id for value in snapshot.entries],
        }
    finally:
        fixture.close()


def measure(root):
    root.mkdir(parents=True, exist_ok=False)
    fixture = ChatFixture(root / "owner-a", dynamics=True)
    fixture.consent()
    first = fixture.ask("nv08-measure-event")
    if first["knowledge_write"] != "CREATED":
        raise RuntimeError("measurement delta was not created")
    queries = tuple(
        QUESTION if ordinal % 2 == 0 else "Explain systemctl unit status."
        for ordinal in range(32)
    )
    latencies = []
    contexts = []
    for query in queries:
        started = time.perf_counter_ns()
        contexts.append(fixture.runtime.lite_memory_retrieve(query))
        latencies.append(time.perf_counter_ns() - started)
    baseline = contexts[0]
    view = fixture.runtime.lite_dynamics_status()["last"]
    snapshot = fixture.learning.dynamics.index.snapshot
    metrics = fixture.learning.storage_metrics()
    counts_before = {
        state: len(fixture.learning.records(state))
        for state in ("DELTA", "EPISODE", "PHEROMONE_EVENT", "TRAIL", "DEPENDENCY")
    }
    replay = fixture.ask(
        "nv08-measure-event", question="Replay text must not create a new effect."
    )
    counts_after = {
        state: len(fixture.learning.records(state))
        for state in counts_before
    }
    duplicate_count = sum(
        max(0, counts_after[state] - counts_before[state]) for state in counts_before
    )
    memory_path = fixture.factory.path
    fixture_file_bytes = memory_path.stat().st_size
    expected = {
        "prompt_json": baseline.prompt_json,
        "selected_refs": [value.reference_id for value in baseline.selected],
        "index_digest": snapshot.snapshot_digest,
        "index_refs": [value.reference_id for value in snapshot.entries],
    }
    fixture.close()

    code = r'''import json,sys
from pathlib import Path
from nv08_measure import fresh
print(json.dumps(fresh(Path(sys.argv[1])),sort_keys=True))
'''
    env = dict(
        os.environ,
        PYTHONPATH=str(Path(__file__).resolve().parents[1])
        + os.pathsep
        + str(Path(__file__).parent),
    )
    child = subprocess.run(
        [sys.executable, "-B", "-c", "import runtime\n" + code, str(root / "owner-a")],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    restarted = json.loads(child.stdout)

    foreign = ChatFixture(
        root / "owner-b",
        scope=replace(fixture.scope, owner_id="nv08-measure-owner-b"),
        replies=(RIGHT,),
        dynamics=True,
    )
    foreign.factory.path = memory_path
    foreign.consent()
    foreign_context = foreign.runtime.lite_memory_retrieve(QUESTION)
    foreign_observable = json.dumps(
        {
            "prompt": foreign_context.prompt_json,
            "dynamics": foreign.runtime.lite_dynamics_status(),
            "metrics": foreign.learning.storage_metrics(),
            "log": foreign.runtime._lite_scheduler.journal.evidence(),
        },
        sort_keys=True,
    )
    cross_user_leaks = int(first["delta_id"] in foreign_observable)
    foreign.close()

    latency_ms = [value / 1_000_000 for value in latencies]
    index = view["index"]
    return {
        "schema": "nv08-local-measurements-v1",
        "profile": "FILE_BACKED_CONTRACT_FIXTURE_NOT_COCKROACH",
        "live_database_storage": False,
        "test_set": {
            "query_count": len(queries),
            "eligible_learning_candidates": snapshot.source_scan_count,
            "maximum_index_entries": snapshot.maximum_entries,
            "candidate_scan_limit": snapshot.candidate_scan_limit,
            "candidate_scan_count": index["candidate_scan_count"],
        },
        "storage": {
            "accepted_minimal_delta_count": metrics["accepted_minimal_delta_count"],
            "durable_logical_bytes_per_accepted_minimal_delta": metrics[
                "durable_bytes_per_accepted_minimal_delta"
            ],
            "fixture_file_bytes_after_one_delta": fixture_file_bytes,
            "index_bytes": snapshot.byte_length,
            "index_entry_bytes": sum(value.byte_length for value in snapshot.entries),
            "bytes_per_index_entry": snapshot.metrics()["bytes_per_entry"],
            "audit_provenance_bytes": metrics["audit_provenance_bytes"],
            "measurement_note": "canonical logical bytes; fixture file bytes are not Cockroach pages",
        },
        "context": {
            "before_index_bytes": index["context_before_index_bytes"],
            "after_shadow_index_bytes": index["context_after_index_bytes"],
            "before_index_token_units": index["context_before_index_token_units"],
            "after_shadow_index_token_units": index["context_after_index_token_units"],
            "token_measurement": index["token_measurement"],
            "actual_behavior_changed": index["actual_behavior_changed"],
        },
        "latency_ms": {
            "minimum": min(latency_ms),
            "p50": statistics.median(latency_ms),
            "p95_nearest_rank": percentile(latency_ms, 0.95),
            "maximum": max(latency_ms),
        },
        "fresh_process": {
            "equivalent": restarted == expected,
            "expected_digest": expected["index_digest"],
            "observed_digest": restarted["index_digest"],
        },
        "replay": {
            "status": replay["status"],
            "duplicate_delta_reward_index_count": duplicate_count,
            "counts_before": counts_before,
            "counts_after": counts_after,
            "durable_index_events": 0,
            "index_rebuild_kind": "DERIVED_FROM_DURABLE_ACCEPTED_RECORDS",
        },
        "isolation": {"cross_user_leak_count": cross_user_leaks},
        "claims": {
            "quality_savings_claimed": False,
            "storage_savings_claimed": False,
            "cockroach_live_claimed": False,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = measure(args.root)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
