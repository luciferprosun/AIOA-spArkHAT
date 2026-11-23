"""Real Native SQLite and descriptor ref publication with fixture-only admission."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

# The child uses isolated Python and imports only the checkout under test.
if __name__ == "__main__":
    checkout = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(checkout / "tests"), str(checkout)]

import nz13_native_foundation_support as fixture
from test_nz25_intent_cold_read import git

from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
from runtime.core_admission import AdmissionError, Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
from runtime.mission.coding_tasks import CoreCodingTasks
from runtime.mission.governor import ReservationRequest
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.sandbox_linux import LinuxSandboxBroker
from runtime.mission.warrant import WarrantError, approval_digest
from runtime.mission.worker import Task

TASK_ID = "held-git-task"
REF = "refs/heads/private-fixture"
RESERVATION = "held-risk"


def seed_held_git_intent(host, tasks, repository):
    fixture.initialize(host)
    git(repository, "init", "--bare", "--object-format=sha1")
    tree = git(repository, "mktree", input="")
    commit = git(repository, "commit-tree", tree, "-m", "Cold controller fixture")
    operator = host.core.local_operator
    foundation = host.foundation
    task = Task(TASK_ID, "held-git-run", "fixture-workspace", "fixture-repo", "c" * 40,
                "Fixture restart", int(datetime.now(UTC).timestamp()) + 300)
    tasks.request(operator(Capability.MANAGE), "create_task", {"task": task.to_dict()})
    target = "sha256:" + "a" * 64
    operation = {
        "operation_class": "GIT_COMMIT",
        "target_fingerprint": target,
        "expected_target_revision": "fixture-base",
        "payload": {
            "schema": "aioa.local-operation.v2", "principal_session_id": host.instance_id,
            "policy_epoch": 1, "ref": REF, "commit_sha": commit, "expected_old_sha": "0" * 40,
        },
    }
    digest = canonical_sha256(operation)
    owner = canonical_sha256(foundation.ledger.scope)
    issued = foundation.ledger.clock()
    expires = issued + timedelta(minutes=2)
    scope = AuthorityScope(("GIT_COMMIT",), target, RiskLevel.MODERATE, Money(Decimal(0), "USD"),
                           issued, expires, owner, TASK_ID)
    warrant = EffectWarrant(
        warrant_id="held-warrant", task_id=TASK_ID, owner_scope=owner,
        operation_class="GIT_COMMIT", operation_hash="sha256:" + digest, target_fingerprint=target,
        expected_target_revision="fixture-base", revision_policy=RevisionPolicy.REQUIRE,
        decision_dependency_root=DecisionDependencyRoot(()), lease_epoch=1, authority_scope=scope,
        approval_digest="sha256:" + "0" * 64, money_reservation_id="NONE", risk_reservation_id=RESERVATION,
        nonce="held-nonce", issued_at=issued, expires_at=expires,
    )
    warrant = replace(warrant, approval_digest=approval_digest(warrant))
    foundation.ledger.approve(operator(Capability.OWNER_APPROVAL), warrant)
    reservation = ReservationRequest(RESERVATION, TASK_ID, "local-git", "aioa/offline-host-worker-v1", digest, 0, 1)
    outcome = foundation.intent_journal.start_local_zero(operator(Capability.COMMIT), warrant, operation, reservation)
    assert outcome["local_step_now"]
    # Fixture setup only, since the cold Native controller must have no execution grant.
    tasks._transition(operator(Capability.COMMIT), TASK_ID, ("QUEUED",), "UNKNOWN")
    parent = os.open(repository / "refs/heads", os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        assert LinuxSandboxBroker._git_publish_new(parent, REF.rsplit("/", 1)[1], commit.encode() + b"\n", cancel=None)
    finally:
        os.close(parent)
    return {"warrant": warrant.to_dict(), "commit": commit, "instance": host.instance_id,
            "spki": host.identity.spki, "pid": os.getpid()}


def check_cold_controller(host, tasks, repository, handoff):
    assert host.instance_id != handoff["instance"] and os.getpid() != handoff["pid"]
    assert host.identity.spki == handoff["spki"]
    assert host.foundation.lifecycle.phase.value == "CAPACITY_ADMIN"
    foundation = host.foundation
    warrant = EffectWarrant.from_dict(handoff["warrant"])
    reader = host.core.local_operator(Capability.READ)

    def state():
        journal = foundation.intent_journal
        outbox = host.runner.run(
            TransactionContext(reader, Capability.READ),
            lambda tx: tx.get(RecordKind.OUTBOX, journal._key(warrant)),
        )
        return (
            journal.inspect(reader, warrant), foundation.governor.inspect(reader), outbox.payload["state"],
            tasks.request(reader, "get_receipts", {"task_id": TASK_ID}),
            git(repository, "rev-parse", "--verify", REF),
        )

    before = state()
    assert before[0]["outcome"]["contract_type"] == "Unknown" and before[0]["grants_replay"] is False
    assert before[1]["reservations"][RESERVATION]["state"] == "UNKNOWN"
    assert before[2] == "HELD" and before[3]["state"] == "UNKNOWN"
    assert before[4] == handoff["commit"]
    assertion = unittest.TestCase()
    with patch("runtime.mission.git_publish._bounded_git") as broker:
        with assertion.assertRaisesRegex(WarrantError, "^CODING_NATIVE_RECONCILIATION_BINDING$"):
            tasks.request(None, "reconcile", {"task_id": TASK_ID})
        with assertion.assertRaisesRegex(AdmissionError, "^CORE_ADMISSION_DENIED$"):
            tasks.request(None, "apply", {"task_id": TASK_ID, "capsule_digest": "0" * 64,
                                          "operation_digest": "0" * 64})
        broker.assert_not_called()
    assert before == state()


def run_phase(phase, root):
    produce = phase == "produce"
    config_path = root / "fixture.json"
    handoff_path = root / "handoff.json"
    config = fixture.config_data(root) if produce else json.loads(config_path.read_text())
    spec = NativeHostCompositionConfig.from_dict(config)
    with patch("runtime.meta_hackathon.runtime_adapter._desktop_operator_uid",
               return_value=(os.getuid(), {"uid": os.getuid(), "method": "SYNTHETIC_TEST_ONLY"})):
        host = NativeMobileComposition(root / "native", origin="https://fixture.example.org",
                                       source_probe=lambda: ("a" * 40, "b" * 64), host_composition=spec,
                                       existing_profile=not produce)
    try:
        fixture.fixture_tls(host)
        capsules = CorePatchCapsules(host.foundation.intent_journal, host.identity,
                                     source_probe=lambda: spec.project_source)
        tasks = CoreCodingTasks(host.foundation.intent_journal, capsules,
                                native_access=None if produce else host.foundation.access)
        try:
            repository = root / "git-target"
            if produce:
                config_path.write_text(json.dumps(config))
                with handoff_path.open("x") as stream:
                    json.dump(seed_held_git_intent(host, tasks, repository), stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Simulate losing the process after publication and before settlement.
                os._exit(75)
            else:
                check_cold_controller(host, tasks, repository, json.loads(handoff_path.read_text()))
        finally:
            tasks.close()
    finally:
        assert host.close()["closed"]


class NativeGitColdControllerTests(unittest.TestCase):
    def test_matching_git_ref_never_grants_cold_controller_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            for phase, expected_exit in (("produce", 75), ("reopen", 0)):
                with self.subTest(phase=phase):
                    result = subprocess.run(
                        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), phase, directory],
                        capture_output=True, text=True, timeout=30, check=False,
                    )
                    self.assertEqual(expected_exit, result.returncode, result.stderr)


if __name__ == "__main__":
    run_phase(sys.argv[1], Path(sys.argv[2]))
