"""Explicit offline Python repository/Core/kernel acceptance (no inference)."""

import json
import sys
import threading
from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from nz11_support import BareRepository

from lab.archaioa.authority import Money
from runtime.mission.git_publish import (
    CoreRemoteGitRoute,
    _git_target_identity,
)
from runtime.mission.sandbox_contracts import SandboxRegistry
from runtime.providers.exact import CancellationToken

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).parent)]
import hybrid_kernel_acceptance as support
import test_nz11_general_recipe as recipe_support

from runtime.mission import repair
from runtime.mission.coding_tasks import CodingRun
from runtime.mission.git_recipe import canonical, sha256
from runtime.mission.patchset import BoundedPatchSetPolicy, observe_source
from runtime.mission.repair_validation import (
    CoreRepositoryMaterializer,
    CoreSandboxValidation,
    pack_workspace,
)
from runtime.mission.worker import CandidateFile, CandidatePatch, SyntheticWorker


def fixture_core():
    fixture = support.support.CoreToolCompositionTests(
        "test_real_synthetic_attempt_opens_required_g2_and_holds_exposure"
    )

    def policy(*args, **kwargs):
        return support.GovernorPolicy(*args, **kwargs, failure_threshold=24)

    with (
        patch("q09_support.Limits", return_value=support.Limits(1000, 200)),
        patch("q09_support.GovernorPolicy", side_effect=policy),
    ):
        fixture.setUp()
    return fixture


class SandboxPreparer:
    """Operator fixture: all jobs still traverse the real Core START and broker."""

    def __init__(self, fixture, manifest, root):
        self.fixture, self.manifest, self.root = fixture, manifest, root
        self.configs = []

    def steps(self, specs):
        f, fx = self.fixture, self.fixture.fx
        config = support.prepare_linux_sandbox(
            self.root / ("sandbox-" + str(len(self.configs))),
            self.manifest,
            workspace="workspace-1",
            recipes={str(i): spec for i, (_, spec) in enumerate(specs)},
        )
        # The existing hard ceiling includes namespace setup and the final
        # trusted Core release check. Full-history release alone takes 3.5s on
        # this small host; the default 5s recipe is not this profile's budget.
        # Pin the operator fixture to the existing 20s ceiling before authority
        # is constructed. Neither the model nor candidate chooses this limit.
        config = replace(
            config,
            registry=SandboxRegistry(
                config.registry.workspace,
                tuple(
                    replace(recipe, timeout_ms=20000)
                    for recipe in config.registry.recipes
                ),
            ),
        )
        self.configs.append(config)
        broker = support.LinuxSandboxBroker(config)
        route = support.CoreToolRoute(
            fx.journal,
            f.liability,
            workspace="workspace-1",
            policy_revision=2,
            variant="sandbox",
            sandbox_registry=config.registry,
            probe=lambda: f.current,
            executor=broker,
            target_guard=lambda: f.lifecycle,
            verifier=broker.verify,
            clock=lambda: f.now,
        )
        steps = []
        for index, (stage, _) in enumerate(specs):
            identity = "general-" + str(len(self.configs)) + "-" + str(index)
            op = route.operation(
                {
                    "action": "run_recipe",
                    "recipe_id": str(index),
                    "task_id": identity,
                    "step_id": "effect",
                },
                f.current,
            )
            trace = support.FaultTrace(
                support.FaultKind.LOST_ACK,
                identity,
                identity,
                "sha256:" + support.canonical_sha256(op),
            )
            graph = support.DependencyGraph(
                identity,
                (
                    support.DependencyNode(
                        "effect",
                        support.NodeKind.OPERATION,
                        liability_ids=(support.classify_fault(trace).liability_id,),
                    ),
                    support.DependencyNode(
                        "completion", support.NodeKind.COMPLETION_CANDIDATE, ("effect",)
                    ),
                ),
            )
            completion = support.TaskCompletionBinding.for_graph(
                fx.ledger.scope, graph, "completion"
            )
            f.liability.initialize(fx.p(), graph)
            request = support.ProviderRequest(
                identity,
                identity,
                "nebius",
                support.MODEL,
                "offline fixture",
                "budget",
                128,
                20,
            )
            job = support.JobEnvelope.from_request(
                fx.ledger.scope,
                identity,
                request,
                deadline_at=160,
                money_nano=1,
                risk_units=0,
            )
            fx.gov.submit_job(
                fx.p(support.Capability.MANAGE), job, completion=completion
            )
            claim = fx.gov.claim_job(
                fx.p(), identity, "fixture-worker", 1, lease_seconds=30
            )
            fx.gov.begin_job(fx.p(), claim)
            grant = replace(
                f.grant,
                session_id=identity,
                policy_revision=2,
                capabilities=("PROJECT_WRITE", "SANDBOX_EXEC"),
                completion_digest=completion.digest,
            )
            route.create_session(fx.p(support.Capability.OWNER_APPROVAL), grant)
            warrant = route.authorize(
                fx.p(),
                identity,
                op,
                completion,
                graph,
                trace,
                nonce=identity,
                model_id=support.MODEL,
                money_nano=1,
                risk_units=5,
            )
            args = {
                "session_id": identity,
                "warrant": warrant,
                "operation": op,
                "completion": completion,
                "reservation": support.ReservationRequest(
                    warrant.money_reservation_id,
                    identity,
                    "sandbox-exec",
                    support.MODEL,
                    support.canonical_sha256(op),
                    1,
                    5,
                ),
            }
            steps.append(support.PreparedValidationStep(stage, route, fx.p(), args))
        return tuple(steps)

    def materialize(self, spec, _patch):
        return self.steps((("MATERIALIZE", spec),))[0]

    def validation(self, profile, candidate, patchset):
        archive = pack_workspace(candidate, patchset)
        return self.steps(
            tuple(
                (stage, profile.observation_spec(stage, archive, patchset))
                for stage in repair.TEST_STAGES
            )
        )


def exercise_active_stop(
    intake,
    fx,
    fixture,
    preparer,
    profile,
    snapshot,
    source_repository,
    base,
    source,
    task,
    root,
    target_fp,
):
    """One actual active guest plus an independent waiting WorkerPort, one Core."""
    from test_nz11_controller import WaitingWorker

    import runtime.mission.sandbox_linux as linux

    armed = threading.Event()
    guest_active = threading.Event()
    workers = {}
    original_line = linux.bounded_line

    def observe_line(stream, *args, **kwargs):
        if args == (24,) and armed.is_set():
            guest_active.set()
        return original_line(stream, *args, **kwargs)

    blocked_task = replace(task, task_id="stop-sandbox-task", run_id="stop-sandbox-run")
    worker_tasks = tuple(
        replace(
            task, task_id="stop-worker-" + suffix, run_id="stop-worker-run-" + suffix
        )
        for suffix in ("one", "two")
    )
    waiting_workers = {item.task_id: WaitingWorker() for item in worker_tasks}

    def factory(admitted, cancel):
        assert admitted in (blocked_task, *worker_tasks)
        materializer = CoreRepositoryMaterializer(
            fx.journal,
            preparer.materialize,
            profile=profile,
            source_snapshot=snapshot,
            source_repository=source_repository,
            base_root=base,
            output_root=root / "stop-mirrors",
            cancel=cancel,
        )
        if admitted == blocked_task:
            candidate = CandidatePatch(
                (
                    CandidateFile(
                        "src/textutil.py",
                        "def slug(text):\n    while True:\n        pass\n",
                    ),
                )
            )
            worker = SyntheticWorker((candidate,), clock=lambda: fixture.now)
        else:
            worker = waiting_workers[admitted.task_id]
        workers[admitted.task_id] = worker
        producer = repair.SandboxedCandidateProducer(
            admitted, worker, materializer, cancel=cancel, clock=lambda: fixture.now
        )

        def validation(candidate, patchset):
            steps = preparer.validation(profile, candidate, patchset)
            armed.set()
            return steps

        validator = CoreSandboxValidation(
            fx.journal, validation, profile=profile, cancel=cancel
        )
        return CodingRun(
            producer,
            validator,
            base,
            source,
            target_fp,
            "git-" + snapshot.source_base_sha,
            fixture.now + 120,
        )

    intake.run_factory = factory  # Trusted isolated host registration, never JSON.
    before = len(preparer.configs)
    with patch.object(linux, "bounded_line", side_effect=observe_line):

        def start(admitted):
            intake.request(
                fx.p(support.Capability.MANAGE),
                "create_task",
                {"task": asdict(admitted)},
            )
            intake.request(
                fx.p(support.Capability.MANAGE), "start", {"task_id": admitted.task_id}
            )

        # Gate 1: simultaneous real WorkerPorts on this Core's full history.
        for item in worker_tasks:
            start(item)
        for item in worker_tasks:
            assert waiting_workers[item.task_id].started.wait(10), (
                "worker startup did not complete"
            )
            assert not waiting_workers[item.task_id].closed
        intake.request(
            fx.p(support.Capability.MANAGE),
            "stop",
            {"task_id": worker_tasks[0].task_id},
        )
        assert not waiting_workers[worker_tasks[1].task_id].closed, (
            "STOP crossed worker identities"
        )
        intake.request(
            fx.p(support.Capability.MANAGE),
            "stop",
            {"task_id": worker_tasks[1].task_id},
        )
        for item in worker_tasks:
            assert intake.wait(item.task_id, 10)
        worker_states = {
            item.task_id: intake.request(
                fx.p(support.Capability.READ), "read_status", {"task_id": item.task_id}
            )["state"]
            for item in worker_tasks
        }
        assert set(worker_states.values()) == {"CANCELLED"}, worker_states
        # Gate 2: real post-ACK Linux guest STOP, without an unrelated 2s startup
        # requirement inside its fixed 20s sandbox lifetime.
        start(blocked_task)
        assert guest_active.wait(180), (
            "guest did not reach actual post-ACK active stage"
        )
        intake.request(
            fx.p(support.Capability.MANAGE), "stop", {"task_id": blocked_task.task_id}
        )
        for _ in range(6):
            if intake.wait(blocked_task.task_id, 30):
                break
        else:
            raise AssertionError("sandbox STOP did not clean up")
    states = {
        **worker_states,
        blocked_task.task_id: intake.request(
            fx.p(support.Capability.READ),
            "read_status",
            {"task_id": blocked_task.task_id},
        )["state"],
    }
    assert states[blocked_task.task_id] == "UNKNOWN", states
    receipts = []
    for config in preparer.configs[before:]:
        for path in config.root.glob("run-*/receipt.json"):
            receipt = json.loads(path.read_bytes())
            assert receipt["cgroup_absent_after_cleanup"] is True
            assert receipt["unit_terminal_observed"] is True
            receipts.append(
                {
                    k: receipt[k]
                    for k in (
                        "status",
                        "project_code_started",
                        "cgroup_absent_after_cleanup",
                        "unit_terminal_observed",
                    )
                }
            )
    assert len(receipts) == 2 and receipts[-1]["status"] == "UNKNOWN", receipts
    return {
        "status": "PASS",
        "states": states,
        "kernel_receipts": receipts,
        "other_worker_unaffected": True,
        "two_concurrent_worker_runs": "PASS_ON_SAME_CORE_HISTORY",
        "active_linux_sandbox_stop": "PASS_SEPARATE_PHASE_SAME_CORE",
        "unknown_intent_settled": False,
        "replay": False,
    }


def main(manifest_path, root):
    producer_class = getattr(repair, "SandboxedCandidateProducer", None)
    assert callable(producer_class), (
        "neutral WorkerPort to sandbox materializer producer is missing"
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    case = recipe_support.GeneralRecipeTests(
        "test_source_is_actual_git_commit_tree_and_independently_exported_bytes"
    )
    case.setUp()
    fixture = fixture_core()
    try:
        fx = fixture.fx
        snapshot = case.source()
        base = root / "base"
        source = snapshot.export(base)
        task = support.Task(
            "general-task",
            "general-run",
            "workspace-1",
            "text-repository",
            case.repo.base,
            "Normalize whitespace and casing.",
            fixture.now + 200,
        )
        original_profile = case.profile()
        manifest_file = root / "operator-recipe.json"
        manifest_file.write_bytes(original_profile.manifest_bytes())
        manifest_file.chmod(0o600)
        profile = type(original_profile).load_file(manifest_file)
        preparer = SandboxPreparer(
            fixture, json.loads(manifest_path.read_text())["manifest"], root
        )
        candidates = tuple(
            CandidatePatch(
                (
                    CandidateFile("src/textutil.py", text),
                    CandidateFile(
                        "src/extra.py", "def title(text):\n    return text.title()\n"
                    ),
                )
            )
            for text in (
                "def slug(text):\n    return text.lower().strip()\n",
                'def slug(text):\n    return "-".join(text.lower().split())\n',
            )
        )
        target = BareRepository(root / "target.git", case.repo.files)
        target.mark_disposable()
        assert target.base == snapshot.source_base_sha
        identity = support.Identity(
            support.ec.generate_private_key(support.ec.SECP256R1())
        )
        capsules = support.CorePatchCapsules(
            fx.journal,
            identity,
            source_probe=lambda: observe_source(
                base,
                repository_id=task.repository_id,
                workspace_id=task.workspace_id,
                source_base_sha=task.source_base_sha,
            ),
        )
        runs = {}
        target_fp = "sha256:" + sha256(
            canonical(
                {
                    "repository_id": snapshot.repository_id,
                    "target_identity": _git_target_identity(target.path),
                    "profile": "DISPOSABLE_BARE_PATCH_V1",
                }
            )
        )

        def run_factory(admitted, cancel):
            assert admitted == task
            materializer = CoreRepositoryMaterializer(
                fx.journal,
                preparer.materialize,
                profile=profile,
                source_snapshot=snapshot,
                source_repository=case.repo.path,
                base_root=base,
                output_root=root / "mirrors",
                cancel=cancel,
            )
            worker = SyntheticWorker(candidates, clock=lambda: fixture.now)
            producer = producer_class(
                task, worker, materializer, cancel=cancel, clock=lambda: fixture.now
            )
            validator = CoreSandboxValidation(
                fx.journal,
                lambda candidate, patchset: preparer.validation(
                    profile, candidate, patchset
                ),
                profile=profile,
                cancel=cancel,
            )
            runs["producer"] = producer
            return CodingRun(
                producer,
                validator,
                base,
                source,
                target_fp,
                "git-" + snapshot.source_base_sha,
                fixture.now + 120,
            )

        intake = support.CoreCodingTasks(
            fx.journal,
            capsules,
            run_factory=run_factory,
            run_principal=fx.p(),
            clock=lambda: fixture.now,
            effect_factory=lambda task_id, capsule_id: (route, warrant, reservation),
        )
        runtime = support.AgentRuntime(
            None, "", root, inspection_only=True, coding_tasks=intake
        )
        assert (
            support.coding_cli_request(
                runtime,
                fx.p(support.Capability.MANAGE),
                "create_task",
                {"task": asdict(task)},
            )["state"]
            == "QUEUED"
        )
        runtime.coding_request(
            "start",
            {"task_id": task.task_id},
            principal=fx.p(support.Capability.MANAGE),
        )
        for _ in range(20):
            if intake.wait(task.task_id, 30):
                break
        else:
            raise AssertionError("controller did not terminate within 600 seconds")
        reviewed = runtime.coding_request(
            "get_receipts",
            {"task_id": task.task_id},
            principal=fx.p(support.Capability.READ),
        )
        assert reviewed["state"] == "REVIEW_REQUIRED", reviewed
        loop = reviewed["run_result"]
        # The canonical loop is used only for assertions/evidence below. The
        # real capsule was produced inside the controller, not reconstructed.
        producer = runs["producer"]
        result_patch = BoundedPatchSetPolicy().evaluate(
            base,
            producer.last_root,
            source=source,
            task=task,
            worker_session_id=loop["attempts"][-1]["worker_session_id"],
        )
        assert loop["status"] == "PATCH_READY", loop
        assert tuple(a["status"] for a in loop["attempts"]) == ("FAIL", "PASS"), loop
        assert all(a["cleanup_orphans"] == 0 for a in loop["attempts"])
        assert (base / "src/textutil.py").read_bytes() == case.repo.files[
            "src/textutil.py"
        ]
        assert [f.operation for f in result_patch.files] == ["ADD", "MODIFY"]
        observed = []
        for config in preparer.configs:
            for path in config.root.glob("run-*/receipt.json"):
                receipt = json.loads(path.read_bytes())
                assert receipt["status"] == "READBACK_VERIFIED"
                assert receipt["cgroup_absent_after_cleanup"] is True
                observed.append(
                    {
                        k: receipt[k]
                        for k in (
                            "status",
                            "project_code_started",
                            "cgroup_absent_after_cleanup",
                            "unit_terminal_observed",
                            "warrant_digest",
                        )
                    }
                )
        assert len(observed) == 6, len(observed)
        cap = reviewed["capsule_digest"]
        preparation = CoreRemoteGitRoute.prepare_patchset(
            base,
            producer.last_root,
            source=source,
            task=task,
            worker_session_id=result_patch.worker_session_id,
            capsule_digest=cap,
        )
        route = CoreRemoteGitRoute.for_local_patch(
            fx.p(),
            fx.journal,
            capsules=capsules,
            preparation=preparation,
            profile=profile,
            source_snapshot=snapshot,
            source_repository=case.repo.path,
            target_repository=target.path,
            check=lambda: None,
            target_guard=nullcontext,
        )
        operation = route.operation(fx.p().actor_session_id, 1)
        scope = replace(
            fx.warrant.authority_scope,
            operation_classes=("GIT_COMMIT",),
            target_scope=operation["target_fingerprint"],
            task_scope=task.task_id,
            monetary_ceiling=Money(Decimal(0), "USD"),
            expires_at=fx.warrant.issued_at + timedelta(seconds=120),
        )
        warrant = replace(
            fx.warrant,
            warrant_id="general-git-owner",
            nonce="general-git-owner",
            task_id=task.task_id,
            operation_class="GIT_COMMIT",
            authority_scope=scope,
            target_fingerprint=operation["target_fingerprint"],
            expected_target_revision=operation["expected_target_revision"],
            decision_dependency_root=route.dependency_root,
            money_reservation_id="NONE",
            risk_reservation_id="general-git-risk",
            operation_hash="sha256:" + support.canonical_sha256(operation),
            expires_at=scope.expires_at,
        )
        warrant = replace(warrant, approval_digest=support.approval_digest(warrant))
        reservation = support.ReservationRequest(
            "general-git-risk",
            task.task_id,
            "fixture",
            support.MODEL,
            support.canonical_sha256(operation),
            0,
            1,
        )
        cancel = CancellationToken()
        try:
            route.dispatch(fx.p(), warrant, operation, reservation, cancel=cancel)
        except ValueError:
            pass
        else:
            raise AssertionError("unapproved Git effect executed")
        assert (
            target.git("rev-parse", "main").decode().strip() == snapshot.source_base_sha
        )
        owner_preview = intake.request(
            fx.p(support.Capability.READ), "review_effect", {"task_id": task.task_id}
        )["effect_preview"]
        assert owner_preview["operation_digest"] == support.canonical_sha256(operation)
        exact = {
            k: owner_preview[k]
            for k in ("task_id", "capsule_digest", "operation_digest")
        }
        try:
            intake.request(
                fx.p(support.Capability.OWNER_APPROVAL),
                "approve",
                {**exact, "operation_digest": "0" * 64},
            )
        except ValueError:
            pass
        else:
            raise AssertionError("swapped exact approval accepted")
        approved = intake.request(
            fx.p(support.Capability.OWNER_APPROVAL), "approve", exact
        )
        assert approved["state"] == "APPROVED"
        # Lose only the acknowledgement AFTER the actual Git CAS completed.
        # START and Git writes are real, and recovery must be read-only.
        import runtime.mission.git_publish as git_module

        original_git = git_module._bounded_git
        writes = []

        def lost_ack(repository, arguments, *, data=None):
            value = original_git(repository, arguments, data=data)
            if arguments[0] == "update-ref":
                writes.append(arguments)
                raise ValueError("GIT_ACK_LOST_FIXTURE")
            return value

        with patch.object(git_module, "_bounded_git", side_effect=lost_ack):
            applied = intake.request(fx.p(), "apply", exact)
            assert applied["state"] == "UNKNOWN", applied
        assert (
            fx.journal.inspect(fx.p(support.Capability.READ), warrant)["outcome"][
                "contract_type"
            ]
            == "Unknown"
        )
        assert (
            route.dispatch(fx.p(), warrant, operation, reservation, cancel=cancel)[
                "local_step_now"
            ]
            is False
        )
        assert len(writes) == 1
        recovered = intake.request(fx.p(), "reconcile", {"task_id": task.task_id})
        assert recovered["state"] == "VERIFIED", recovered
        stored = route.result(fx.p(support.Capability.READ))
        support.verify(identity.spki, stored["signature"], stored["receipt"])
        assert (
            target.git("show", route.plan.ref + ":src/textutil.py")
            == dict(preparation.postimages)["src/textutil.py"]
        )
        assert (
            target.git("show", route.plan.ref + ":src/extra.py")
            == dict(preparation.postimages)["src/extra.py"]
        )
        assert (
            target.git("rev-parse", "main").decode().strip() == snapshot.source_base_sha
        )
        assert (
            route.dispatch(fx.p(), warrant, operation, reservation, cancel=cancel)[
                "local_step_now"
            ]
            is False
        )
        assert (
            fx.journal.delivery(fx.p(support.Capability.READ), warrant)["grants_replay"]
            is False
        )
        evidence = {
            "status": "PASS",
            "loop": loop,
            "profile_digest": profile.digest,
            "base_sha": snapshot.source_base_sha,
            "source_readback_digest": snapshot.digest,
            "kernel_receipts": observed,
            "same_core": True,
            "paid_calls": 0,
            "remote_calls": 0,
            "git_result": stored,
            "controller_receipts": intake.request(
                fx.p(support.Capability.READ), "get_receipts", {"task_id": task.task_id}
            )["receipts"],
        }
        evidence["active_stop"] = exercise_active_stop(
            intake,
            fx,
            fixture,
            preparer,
            profile,
            snapshot,
            case.repo.path,
            base,
            source,
            task,
            root,
            target_fp,
        )
        (root / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(
            json.dumps(
                {
                    k: evidence[k]
                    for k in (
                        "status",
                        "profile_digest",
                        "base_sha",
                        "same_core",
                        "paid_calls",
                        "remote_calls",
                    )
                }
            )
        )
        return True
    finally:
        if "intake" in locals():
            intake.close()
        fixture.doCleanups()
        case.doCleanups()


if __name__ == "__main__":
    raise SystemExit(0 if main(Path(sys.argv[1]), Path(sys.argv[2])) else 1)
