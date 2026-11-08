"""Explicit offline kernel acceptance; accepts an operator-pinned Python manifest.

Run with a clean environment and a user systemd bus. It never reads host keys,
calls a model, contacts GitHub or uses the production Core database.
"""

import importlib
import json
import sys
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).parent)]
importlib.import_module("runtime")
import test_core_tool_composition as support
from cryptography.hazmat.primitives.asymmetric import ec
from test_dual_governor import MODEL
from test_hybrid_repair import DirectoryProducer

from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import Capability
from runtime.main import AgentRuntime
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.mission import repair
from runtime.mission.coding_tasks import CoreCodingTasks, coding_cli_request
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import GovernorPolicy, Limits, ReservationRequest
from runtime.mission.job_contracts import JobEnvelope
from runtime.mission.patch_capsule import (
    CorePatchCapsules,
    ExecutionCapsule,
    capsule_dependencies,
    capsule_operation,
)
from runtime.mission.patchset import observe_source
from runtime.mission.repair_validation import (
    CALCULATOR_TEST,
    COMPLETE,
    TEST_RUNNER,
    CoreSandboxValidation,
    PreparedValidationStep,
    TrustedTestProfile,
    pack_workspace,
)
from runtime.mission.sandbox_linux import LinuxSandboxBroker, prepare_linux_sandbox
from runtime.mission.tools import CoreToolRoute
from runtime.mission.warrant import approval_digest
from runtime.mission.worker import CandidateFile, CandidatePatch, Task
from runtime.mobile_gateway.wire import Identity, verify
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
    script = CALCULATOR_TEST
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
            args = {
                "session_id": identity,
                "warrant": warrant,
                "operation": op,
                "completion": completion,
                "reservation": ReservationRequest(
                    warrant.money_reservation_id,
                    identity,
                    "sandbox-exec",
                    MODEL,
                    canonical_sha256(op),
                    1,
                    5,
                ),
            }
            prepared.append(PreparedValidationStep(stage, route, fx.p(), args))
        return tuple(prepared)

    try:
        base = root / "base"
        base.mkdir(mode=0o700)
        (base / "calc.py").write_text("def add(a, b):\n    return a-b\n")
        (base / "calc.py").chmod(0o644)
        task = Task(
            "task-1",
            "run-1",
            "workspace-1",
            "repo-1",
            "a" * 40,
            "Fix addition.",
            fixture.now + 200,
        )
        source = observe_source(
            base,
            repository_id="repo-1",
            workspace_id="workspace-1",
            source_base_sha="a" * 40,
        )
        identity = Identity(ec.generate_private_key(ec.SECP256R1()))
        capsules = CorePatchCapsules(
            fx.journal,
            identity,
            source_probe=lambda: source,
            target_guard=lambda: fixture.lifecycle,
        )
        intake = CoreCodingTasks(fx.journal, capsules)
        runtime = AgentRuntime(
            None, "", root, inspection_only=True, coding_tasks=intake
        )
        created = coding_cli_request(
            runtime, fx.p(Capability.MANAGE), "create_task", {"task": asdict(task)}
        )
        assert created["state"] == "QUEUED"
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
        if result.status == "PATCH_READY":
            signed = capsules.prepare(
                fx.p(),
                task=task,
                source=source,
                base_root=base,
                final_root=root / "attempt-1",
                result=result,
                target_fingerprint=fixture.current.fingerprint,
                target_revision=fixture.current.revision,
                expires_at=fixture.now + 120,
            )
            verify(identity.spki, signed["signature"], signed["receipt"])
            payload = dict(signed["receipt"]["capsule"])
            payload.pop("schema")
            payload["validation_warrants"] = tuple(payload["validation_warrants"])
            payload["validation_receipts"] = tuple(payload["validation_receipts"])
            capsule = ExecutionCapsule(**payload)
            attached = intake.attach_review(fx.p(), task.task_id, capsule.digest)
            assert attached["state"] == "REVIEW_REQUIRED"
            status = coding_cli_request(
                runtime, fx.p(Capability.READ), "read_status", {"task_id": task.task_id}
            )
            assert status == attached
            evidence["intake"] = {
                "status": "PASS",
                "created": created,
                "review": status,
                "same_core": intake.journal is fx.journal,
            }
            op = capsule_operation(capsule)
            scope = replace(
                fx.warrant.authority_scope,
                operation_classes=(op["operation_class"],),
                target_scope=op["target_fingerprint"],
                task_scope=task.task_id,
                expires_at=fx.warrant.issued_at + timedelta(seconds=120),
            )
            warrant = replace(
                fx.warrant,
                warrant_id="patch-owner-1",
                nonce="patch-owner-1",
                task_id=task.task_id,
                operation_class=op["operation_class"],
                authority_scope=scope,
                operation_hash="sha256:" + canonical_sha256(op),
                target_fingerprint=op["target_fingerprint"],
                expected_target_revision=op["expected_target_revision"],
                decision_dependency_root=capsule_dependencies(capsule),
                expires_at=scope.expires_at,
            )
            warrant = replace(warrant, approval_digest=approval_digest(warrant))
            capsules.approve(fx.p(Capability.OWNER_APPROVAL), capsule.digest, warrant)
            approved = capsules.require_approved(fx.p(), capsule.digest, warrant)
            assert (
                approved["status"] == "APPROVED"
                and approved["dispatch_registered"] is False
            )
            assert capsules.read(fx.p(Capability.READ), capsule.digest) == signed
            try:
                capsules.approve(
                    fx.p(Capability.OWNER_APPROVAL),
                    capsule.digest,
                    replace(warrant, operation_hash="sha256:" + "0" * 64),
                )
            except ValueError:
                pass
            else:
                raise AssertionError("approval swap unexpectedly accepted")
            evidence["capsule"] = {
                "status": "PASS",
                "signed_receipt": signed,
                "exact_owner_warrant": warrant.digest(),
                "effect_executed": False,
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
