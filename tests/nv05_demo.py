"""CLI for the controlled three-process demo. No external provider or actions.

Run with a fresh explicit test directory: --run 1, then 2, then 3. Each command
composes actual AgentRuntime/native memory/NVIDIA adapter/original HTTP CPL.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import runtime  # noqa: F401 - legacy module bootstrap

# isort: split
from nv05_support import ContextDependentActor, DynamicsFixture

from runtime.memory_patch.contracts.serialization import canonical_json_bytes


def execute(
    root,
    number,
    *,
    factory_builder=None,
    backend_id="repository-durable-test",
    scope=None,
):
    fx = DynamicsFixture(
        root,
        mode="ACTIVE",
        factory_builder=factory_builder,
        backend_id=backend_id,
        scope=scope,
    )
    try:
        if number == 1:
            assert not fx.learning.records("DELTA"), "fresh corpus required"
        else:
            assert len(fx.learning.records("DELTA")) == 1, "prior run required"
            actor = ContextDependentActor()
            fx.provider._transport = actor
        if number == 3:
            fx.change_evidence_version()
        before = len(fx.learning.records("DELTA"))
        state = fx.changed("demo-run-" + str(number))
        after = fx.learning.records("DELTA")
        rows = lambda kind: [
            json.loads(canonical_json_bytes(r.payload))
            for r in fx.learning.records(kind)
        ]
        value = {
            "run": number,
            "pid": os.getpid(),
            "runtime_class": type(fx.runtime).__name__,
            "backend": fx.memory_profile.backend_id,
            "provider_path": "NVIDIA_ADAPTER_FIXTURE_AND_ORIGINAL_CPL_HTTP",
            "delta_ids": [r.record_id for r in after],
            "new_delta_count": len(after) - before,
            "cpl": fx.runtime.lite_cpl_status()["last"],
            "dvm": fx.runtime.lite_dynamics_status()["last"],
            "trails": rows("TRAIL"),
            "tau_events": rows("PHEROMONE_EVENT"),
            "tier_events": rows("TIER_EVENT"),
            "dependencies": rows("DEPENDENCY"),
            "obligations": rows("OBLIGATION"),
            "reuse_status": [r.payload.get("reuse_status", "CURRENT") for r in after],
            "injected_delta_refs": [] if number == 1 else actor.injected_delta_refs,
            "context_byte_units": fx.runtime._lite_memory.last.context_byte_units,
            "model_calls_total": state["model_calls"],
            "cpl_calls_this_process": len(fx.http.requests),
            "domain_mutations": state["domain_mutations"],
            "execution_authority": False,
            "auto_mode": state["auto_mode"],
        }
        if number == 1:
            assert (
                value["new_delta_count"] == 1 and value["cpl"]["status"] == "VERIFIED"
            ), value
            assert value["trails"][0]["tier"] == "DEEP", value
        elif number == 2:
            assert (
                value["new_delta_count"] == 0 and value["cpl"]["status"] == "ZERO_WRITE"
            ), value
            assert value["delta_ids"][0] in value["injected_delta_refs"], value
            assert value["trails"][0]["tier"] == "HOT", value
            assert any(e["reason"] == "VERIFIED_REUSE" for e in value["tau_events"]), (
                value
            )
        else:
            assert value["new_delta_count"] == 0 and value["obligations"], value
            assert value["reuse_status"] == ["REVALIDATION_REQUIRED"], value
            assert value["injected_delta_refs"] == [], value
        return value
    finally:
        fx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run", type=int, choices=(1, 2, 3), required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.root, args.run), sort_keys=True))
