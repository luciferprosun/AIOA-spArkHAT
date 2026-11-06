"""Explicit offline kernel acceptance; accepts an operator-pinned Python manifest.

Run with a clean environment and a user systemd bus. It never reads host keys,
calls a model, contacts GitHub or uses the production Core database.
"""

# ruff: noqa: E402 -- explicit standalone acceptance path bootstrap

import importlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).parent)]
importlib.import_module("runtime")
import test_core_tool_composition as support
from test_dual_governor import MODEL
from test_hybrid_repair import DirectoryProducer

import runtime.mission.repair as repair
from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import GovernorPolicy, Limits, ReservationRequest
from runtime.mission.job_contracts import JobEnvelope
from runtime.mission.patchset import observe_source
from runtime.mission.repair_validation import (
    COMPLETE,
    TEST_RUNNER,
    CoreSandboxValidation,
    PreparedValidationStep,
    TrustedTestProfile,
    pack_workspace,
)
from runtime.mission.sandbox_linux import LinuxSandboxBroker, prepare_linux_sandbox
from runtime.mission.tools import CoreToolRoute
from runtime.mission.worker import CandidateFile, CandidatePatch, Task
from runtime.providers.nvidia import ProviderRequest


def main(manifest_path, root):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = json.loads(manifest_path.read_text())["manifest"]
    fixture = support.CoreToolCompositionTests(
        "test_real_synthetic_attempt_opens_required_g2_and_holds_exposure"
    )

    # Inject only the isolated fixture's budget configuration. Kernel execution,
    # admission, transactions, receipts and readback are real and unpatched.
    def fixture_policy(*args, **kwargs):
        return GovernorPolicy(*args, **kwargs, failure_threshold=12)

    with (
        patch("q09_support.Limits", return_value=Limits(1000, 100)),
        patch("q09_support.GovernorPolicy", side_effect=fixture_policy),
    ):
        fixture.setUp()
    fx = fixture.fx
    script = b"""import ast
tree = ast.parse(workspace['calc.py'])
allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
           ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
           ast.Name, ast.Load)
if not all(isinstance(node, allowed) for node in ast.walk(tree)):
    raise ValueError('fixture pure arithmetic only')
namespace = {}
exec(compile(tree, '<candidate>', 'exec'), {'__builtins__': {}}, namespace)
check(namespace['add'](2, 3) == 5)
check(namespace['add'](-7, 4) == -3)
check(namespace['add'](0, 8) == 8)
"""
    profile = TrustedTestProfile(
        "calculator-fixed-v1",
        tuple((s, script) for s in repair.TEST_STAGES),
        tuple((s, 3) for s in repair.TEST_STAGES),
    )
    configs = []
    validation_errors = []

    def prepare(candidate_root, patchset):
        archive = pack_workspace(candidate_root, patchset)
        recipes = {
            str(index): {
                "files": {
                    "recipe.py": TEST_RUNNER,
                    "approved-test.py": script,
                    "validation-context.json": canonical_json_bytes(
                        profile.context(stage, patchset)
                    ),
                    "workspace.json": archive,
                },
                "expected": {"test-report-complete.txt": COMPLETE},
            }
            for index, stage in enumerate(repair.TEST_STAGES)
        }
        config = prepare_linux_sandbox(
            root / ("sandbox-" + str(len(configs))),
            manifest,
            workspace="workspace-1",
            recipes=recipes,
        )
        configs.append(config)
        broker = LinuxSandboxBroker(config)
        route = CoreToolRoute(
            fx.journal,
            fixture.liability,
            workspace="workspace-1",
            policy_revision=2,
            variant="sandbox",
            sandbox_registry=config.registry,
            probe=lambda: fixture.current,
            executor=broker,
            target_guard=lambda: fixture.lifecycle,
            verifier=broker.verify,
            clock=lambda: fixture.now,
        )
        prepared = []
        for index, stage in enumerate(repair.TEST_STAGES):
            identity = "nz-" + str(len(configs)) + "-" + str(index)
            op = route.operation(
                {
                    "action": "run_recipe",
                    "recipe_id": str(index),
                    "task_id": identity,
                    "step_id": "effect",
                },
                fixture.current,
            )
            trace = FaultTrace(
                FaultKind.LOST_ACK, identity, identity, "sha256:" + canonical_sha256(op)
            )
            graph = DependencyGraph(
                identity,
                (
                    DependencyNode(
                        "effect",
                        NodeKind.OPERATION,
                        liability_ids=(classify_fault(trace).liability_id,),
                    ),
                    DependencyNode(
                        "completion", NodeKind.COMPLETION_CANDIDATE, ("effect",)
                    ),
                ),
            )
            completion = TaskCompletionBinding.for_graph(
                fx.ledger.scope, graph, "completion"
            )
            fixture.liability.initialize(fx.p(), graph)
            request = ProviderRequest(
                identity,
                identity,
                "nebius",
                MODEL,
                "offline fixture",
                "budget",
                128,
                20,
            )
            job = JobEnvelope.from_request(
                fx.ledger.scope,
                identity,
                request,
                deadline_at=160,
                money_nano=1,
                risk_units=0,
            )
            fx.gov.submit_job(fx.p(Capability.MANAGE), job, completion=completion)
            claim = fx.gov.claim_job(
                fx.p(), identity, "fixture-worker", 1, lease_seconds=30
            )
            fx.gov.begin_job(fx.p(), claim)
            grant = replace(
                fixture.grant,
                session_id=identity,
                policy_revision=2,
                capabilities=("PROJECT_WRITE", "SANDBOX_EXEC"),
                completion_digest=completion.digest,
            )
            route.create_session(fx.p(Capability.OWNER_APPROVAL), grant)
            warrant = route.authorize(
                fx.p(),
                identity,
                op,
                completion,
                graph,
                trace,
                nonce=identity,
                model_id=MODEL,
                money_nano=1,
                risk_units=5,
            )
            args = dict(
                session_id=identity,
                warrant=warrant,
                operation=op,
                completion=completion,
                reservation=ReservationRequest(
                    warrant.money_reservation_id,
                    identity,
                    "sandbox-exec",
                    MODEL,
                    canonical_sha256(op),
                    1,
                    5,
                ),
            )
            prepared.append(PreparedValidationStep(stage, route, fx.p(), args))
        return tuple(prepared)

    try:
        base = root / "base"
        base.mkdir(mode=0o700)
        (base / "calc.py").write_text("def add(a, b):\n    return a-b\n")
        (base / "calc.py").chmod(0o644)
        task = Task(
            "task-1", "run-1", "workspace-1", "repo-1", "a" * 40, "Fix addition.", 200
        )
        source = observe_source(
            base,
            repository_id="repo-1",
            workspace_id="workspace-1",
            source_base_sha="a" * 40,
        )
        candidates = tuple(
            CandidatePatch(
                (CandidateFile("calc.py", "def add(a, b):\n    return " + expr + "\n"),)
            )
            for expr in ("a*b", "a+b")
        )
        producer = DirectoryProducer(repair, base, root, task, candidates)
        validator = CoreSandboxValidation(fx.journal, prepare, profile=profile)

        class ObservedValidation:
            def open(self, candidate_root, patchset):
                try:
                    session = validator.open(candidate_root, patchset)
                    original_run = session.run

                    def observed_run(stage):
                        result = original_run(stage)
                        if session.failure_code:
                            validation_errors.append(session.failure_code)
                        return result

                    session.run = observed_run
                    return session
                except Exception as error:
                    validation_errors.append(str(error))
                    raise

        result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
            task=task,
            source=source,
            base_root=base,
            producer=producer,
            validator=ObservedValidation(),
        )
        evidence = {
            "status": "PASS"
            if result.status == "PATCH_READY" and len(result.attempts) == 2
            else "FAIL",
            "result": asdict(result),
            "models_called": 0,
            "remote_calls": 0,
            "same_core": True,
            "profile_digest": profile.digest,
            "kernel_receipts": [],
        }
        for config in configs:
            for path in config.root.glob("run-*/receipt.json"):
                receipt = json.loads(path.read_bytes())
                evidence["kernel_receipts"].append(
                    {
                        key: receipt.get(key)
                        for key in (
                            "status",
                            "project_code_started",
                            "cgroup_absent_after_cleanup",
                            "unit_terminal_observed",
                            "warrant_digest",
                        )
                    }
                )
        (root / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": evidence["status"],
                    "loop_status": result.status,
                    "attempt_statuses": [a.status for a in result.attempts],
                    "steps": [[s.status for s in a.steps] for a in result.attempts],
                    "kernel_receipts": len(evidence["kernel_receipts"]),
                    "failure": result.failure_code,
                    "validation_errors": validation_errors,
                }
            )
        )
        return evidence["status"] == "PASS"
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    raise SystemExit(0 if main(Path(sys.argv[1]), Path(sys.argv[2])) else 1)
