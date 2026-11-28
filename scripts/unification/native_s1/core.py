"""Owned disposable task preparation and ordinary Core admission/effect calls."""

import base64
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from runtime.core_admission import Capability, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition, current_source
from runtime.mission.git_publish import GitSourceSnapshot
from runtime.mission.governor import GovernorPolicy, Limits
from runtime.mission.project_recipe import PythonFunctionCase, PythonRepositoryRecipe
from runtime.mission.sandbox_contracts import PYTHON_ARGV
from runtime.mission.sandbox_linux import prepare_linux_sandbox, save_host_config
from runtime.mission.target_projection import CoreTargetProjection
from runtime.mission.worker import CandidateFile, CandidatePatch, Task, WorkerSession
from runtime.red_hat.broker_protocol import require

_TASK = "native69-s1"
_TARGET = "n69-s1-inert-portable"
_SOURCE = "native69-s1-repo"
_SPACE = "native69-s1-workspace"


def prepare(root, target, base, runtime_files, reader):
    """Build a fixed, inert workload with the accepted real sandbox backend."""
    from nonzero_cloudops.adapters.portable import PortableStateStore
    from nonzero_cloudops.adapters.resources import default_mock_resources

    for name in ("candidates", "cache", "managed", "tmp"):
        (root / name).mkdir(mode=0o700, exist_ok=True)
    snapshot = GitSourceSnapshot.capture(root / "source.git", expected_sha=base,
                                         repository_id=_SOURCE, workspace_id=_SPACE)
    source = snapshot.export(root / "base")
    candidate = CandidatePatch((CandidateFile("src/textutil.py",
        'def slug(text):\n    return "-".join(text.lower().split())\n'),))
    task = Task(_TASK, "native69-s1-run", _SPACE, _SOURCE, base,
                "Normalize whitespace and casing in the isolated text example.", int(time.time()) + 1800)
    oracle = PythonFunctionCase("normalized", "textutil", "slug", b'[" Hello World "]', b'"hello-world"')
    recipe = PythonRepositoryRecipe(_SOURCE, base, ("src/textutil.py",), ("src",),
        tuple((stage, (oracle,)) for stage in ("FAST_TESTS", "TARGETED_TESTS", "FINAL_TESTS")), PYTHON_ARGV)

    local_runtime = root / "cache/runtime"
    local_runtime.mkdir(mode=0o700)
    runtime = {}
    for index, (name, entry) in enumerate(sorted(runtime_files.items())):
        src = entry["snapshot"]
        data = Path(src).read_bytes()
        require(len(data) == entry["bytes"] and hashlib.sha256(data).hexdigest() == entry["sha256"],
                "NATIVE_S1_RUNTIME_DRIFT")
        path = local_runtime / str(index)
        path.write_bytes(data)
        path.chmod(entry["mode"] & 0o700)
        runtime[name] = {**entry, "snapshot": str(path)}
    session = WorkerSession("seed-session", task.task_id, task.run_id, task.digest, "offline-seed")
    fixed = recipe.materialization_spec(root / "base", source=source, task=task,
                                        worker_session_id=session.session_id, candidate=candidate)[2]
    seed = prepare_linux_sandbox(root / "cache/seed", runtime, workspace=_SPACE, recipes={"0": fixed})
    # The loader requires all snapshots under the seed, independent of the
    # originally measured and copied runtime inputs.
    retained = seed.root / "runtime"
    runtime_directory = seed.runtime()
    if not retained.exists():
        retained.mkdir(mode=0o700)
    local = {}
    for index, (name, entry) in enumerate(runtime_directory.items()):
        previous = Path(entry["snapshot"])
        path = retained / str(index)
        if previous != path:
            path.write_bytes(previous.read_bytes())
            path.chmod(entry["mode"])
        local[name] = {**entry, "snapshot": str(path)}
    seed = replace(seed, runtime_bytes=json.dumps(local, sort_keys=True, separators=(",", ":")).encode())
    save_host_config(seed)

    scope = OwnerScope("local-linux", f"uid-{os.getuid()}", "aioa-main", "mobile-status")
    limits = Limits(50000000, 20)
    policy = GovernorPolicy(scope, "native-mobile-chat-v1", limits, limits, limits, max_clock_step_seconds=3600)
    head = canonical_sha256(("aioa-core-target-head.v1", scope, _SPACE, _TARGET))
    registration = canonical_sha256(("aioa-core-target-registration.v1", head))
    inventory = root / "managed/.aioa-core-managed-v1" / canonical_sha256(scope) / registration / "inventory.json"
    inventory.parent.mkdir(mode=0o700, parents=True)
    store = PortableStateStore(inventory)
    with store._lock(exclusive=True):
        resources, receipts = store._initial_snapshot()
        store._write(resources, receipts)
    item = next(resource for resource in default_mock_resources()
                if resource.resource_type.value == "AWS::EC2::EIP")
    body = {
        "schema": "aioa.native-host-composition.v1",
        "profile": "OWNED_OFFLINE_PROOF_V1",
        "host_source": dict(zip(("source_sha", "capsule_digest"), current_source(), strict=True)),
        "bootstrap_policy_digest": policy.digest,
        "base_root": str(root / "base"),
        "candidate_root": str(root / "candidates"),
        "source_repository": str(root / "source.git"),
        "git_target_repository": str(target),
        "sandbox_cache_root": str(seed.root),
        "project_source": asdict(source),
        "source_snapshot": {"repository_id": _SOURCE, "workspace_id": _SPACE,
            "source_base_sha": snapshot.source_base_sha, "git_tree_sha": snapshot.git_tree_sha,
            "ref": snapshot.ref,
            "files": [[name, base64.b64encode(data).decode("ascii")] for name, data in snapshot.files]},
        "recipe": json.loads(recipe.manifest_bytes()),
        "sandbox_seed": {"descriptor_path": str(seed.root / "host-config.json"),
                         "descriptor_sha256": hashlib.sha256((seed.root / "host-config.json").read_bytes()).hexdigest()},
        "retained_sandbox_task_ids": [],
        "accounting": {"job_model_id": "aioa/offline-host-worker-v1", "job_provider_id": "offline-host",
                       "effect_model_binding_id": "aioa/offline-host-worker-v1"},
        "operations": ["GIT_COMMIT", "PORTABLE_REARM_DEMO_V1", "PORTABLE_RELEASE_ELASTIC_IP", "SANDBOX_EXEC"],
        "limits_plan": {"sandbox_effects": 8, "local_git_effects": 1, "portable_effects": 0,
                        "max_duration_seconds": 1800,
                        "proposed_capacity": {"risk_limits": {"task_limit": 80, "owner_provider_limit": 80,
                                                               "global_limit": 80},
                                              "sandbox_exec_failure_threshold": 12}},
        "portable": {"binding": {"scope": list(scope.binding()), "workspace": _SPACE, "target_id": _TARGET,
                                 "incarnation": "before-adoption", "guard_fingerprint": "f" * 64},
                     "inventory_path": str(inventory), "registration_digest": "1" * 64,
                     "adoption_digest": "2" * 64, "expected_head_revision": 1,
                     "generation": 0, "history_digest": "3" * 64,
                     "resource_query": {"resource_type": item.resource_type.value,
                                        "resource_id": item.resource_id, "region": item.region}},
    }
    NativeHostCompositionConfig.from_dict(body).with_qualification_target(reader)
    return body, task, candidate, store


@contextmanager
def tls_core(core_files, body, reader, *, gate, candidates=None, existing_profile=False):
    """A real loopback TLS challenge on the ordinary, system-admitted Core."""
    from runtime.webapp import WebRuntimeService, make_server

    spec = NativeHostCompositionConfig.from_dict(body).with_qualification_target(reader)
    with make_server("127.0.0.1", 0) as reserved:
        port = reserved.server_address[1]
        host = NativeMobileComposition(core_files / "profile", origin=f"https://localhost:{port}",
            host_composition=spec, offline_candidates=candidates, qualification_gate=gate,
            existing_profile=existing_profile)
        try:
            service = WebRuntimeService(runtime=host.runtime, meta_missions=host.missions, meta_owner=host,
                mobile_gateway=host.mobile, native_access=host.foundation.access)
            server = make_server("127.0.0.1", port, service, reserved_server=reserved,
                                 tls_certificate=core_files / "server.pem", tls_key=core_files / "server.key")
            reader_thread = threading.Thread(target=server.serve_forever, name="native-s1-tls")
            reader_thread.start()
            try:
                host.qualify_tls(port)
            finally:
                server.shutdown()
                reader_thread.join()
                server.server_close()
            # Control is private and originally admitted. The TLS socket has
            # closed by the time it receives a task or publication command.
            yield host
        finally:
            host.close()


def authorize_adoption(host, body, store):
    """One ordinary target adoption of inert state in the original Core."""
    from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
    from lab.archaioa.decision_root import DecisionDependencyRoot
    from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
    from runtime.mission.warrant import approval_digest

    f = host.foundation
    host.operator_request(os.getuid(), {"op": "governor_initialize", "request_id": "0" * 32,
        "expected_version": 0, "expected_epoch": 0, "bootstrap_policy_digest": f.governor.policy.digest,
        "composition_digest": f.spec.digest, "source_sha": host.source[0], "capsule_digest": host.source[1]})
    commit = host.core.local_operator(Capability.COMMIT)
    with store.target_guard():
        observed = store.observe_guarded_inventory()
        projection, request = CoreTargetProjection.prepare_existing_adoption(f.intent_journal, f.liability,
            commit, workspace=_SPACE, target_id=_TARGET, state_root=observed.state_root,
            resources_root=observed.resources_root, receipts_root=observed.receipts_root,
            guard_fingerprint=observed.guard_fingerprint)
        operation = request.operation()
        now = datetime.now(UTC)
        expires = now + timedelta(minutes=1)
        owner_scope = canonical_sha256(host.ledger.scope)
        authority = AuthorityScope(operation_classes=("TARGET_ADOPT_EXISTING",),
            target_scope=operation["target_fingerprint"], risk_ceiling=RiskLevel.LOW,
            monetary_ceiling=Money(Decimal(0), "USD"), not_before=now, expires_at=expires,
            owner_scope=owner_scope, task_scope="s1-owned-adoption")
        warrant = EffectWarrant(warrant_id="s1-owned-adoption", task_id="s1-owned-adoption",
            owner_scope=owner_scope, operation_class=operation["operation_class"],
            operation_hash="sha256:" + canonical_sha256(operation), target_fingerprint=operation["target_fingerprint"],
            expected_target_revision=operation["expected_target_revision"], revision_policy=RevisionPolicy.REQUIRE,
            decision_dependency_root=DecisionDependencyRoot((request.binding.evidence(), request.evidence())),
            lease_epoch=request.epoch, authority_scope=authority, approval_digest="sha256:" + "0" * 64,
            money_reservation_id="NONE", risk_reservation_id="NONE", nonce="s1-owned-adoption",
            issued_at=now, expires_at=expires)
        warrant = replace(warrant, approval_digest=approval_digest(warrant))
        f.ledger.approve(host.core.local_operator(Capability.OWNER_APPROVAL), warrant)
        receipt = host.runner.run(TransactionContext(commit, Capability.COMMIT),
            lambda tx: projection.adopt_existing_in_transaction(tx, warrant, request))

        def read(tx):
            row, state = projection.load(tx)
            register = tx.get(RecordKind.OPERATION, projection.registration_key)
            return row.revision, state, register.payload_digest

        revision, state, digest = host.runner.run(TransactionContext(host.core.local_operator(Capability.READ),
                                                                    Capability.READ), read)
    body["portable"].update(binding={**asdict(request.binding), "scope": list(host.ledger.scope.binding())},
        registration_digest=digest, adoption_digest=receipt["adoption_digest"], expected_head_revision=revision,
        generation=state["generation"], history_digest=state["history_digest"])


def prepare_review(host, body, task):
    """Use the normal owner activation and wait for the signed capsule."""
    uid = os.getuid()
    review = host.operator_request(uid, {"op": "execution_capacity_review", "request_id": "1" * 32,
                                         "proposed": body["limits_plan"]["proposed_capacity"]})
    fields = {key: review["review"][key] for key in ("request_id", "review_digest")}
    host.operator_request(uid, {"op": "execution_capacity_approve", **fields})
    host.operator_request(uid, {"op": "execution_capacity_apply", **fields, "warrant_digest": review["warrant_digest"]})
    task_request(host, "create_task", {"task": task.to_dict()})
    task_request(host, "start", {"task_id": task.task_id})
    deadline = time.monotonic() + 200
    while time.monotonic() < deadline:
        status = task_request(host, "read_status", {"task_id": task.task_id})
        if status["state"] == "REVIEW_REQUIRED":
            return status["capsule_digest"]
        require(status["state"] in ("QUEUED", "RUNNING", "VALIDATING", "REPAIRING"), "NATIVE_S1_TASK_NO_REVIEW")
        time.sleep(0.25)
    raise ValueError("NATIVE_S1_TASK_REVIEW_TIMEOUT")


def task_request(host, action, payload):
    purpose = {"create_task": Capability.MANAGE, "start": Capability.MANAGE, "stop": Capability.MANAGE,
               "review_effect": Capability.READ, "read_status": Capability.READ,
               "approve": Capability.OWNER_APPROVAL, "apply": Capability.COMMIT}[action]
    with host._native_coding.authority(purpose) as principal:
        return host.coding_tasks.request(principal, action, payload)
