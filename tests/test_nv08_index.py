"""NV08 compact-index contract tests; all backends here are labeled fixtures."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from nv07_support import ChatFixture, QUESTION, RIGHT, WRONG
from runtime.core_admission import Capability, OwnerScope
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.learning.dynamics import DynamicsPolicy
from runtime.memory_patch.learning.index import CompactPheromoneIndex
from runtime.memory_patch.learning.personal_contracts import (
    ConsentMode,
    DomainSemantics,
    SemanticDeltaKind,
)
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission.contracts import MissionError
from test_memory_patch_persistence_ports import NOW


class CompactIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixtures = []

    def fixture(self, name, **kwargs):
        value = ChatFixture(self.root / name, **kwargs)
        self.fixtures.append(value)
        self.addCleanup(value.close)
        return value

    def _learn_and_index(self, fx, *, operation_id="nv08-one"):
        fx.consent()
        result = fx.ask(operation_id)
        self.assertEqual("CREATED", result["knowledge_write"], result)
        context = fx.runtime.lite_memory_retrieve(QUESTION)
        self.assertEqual("READY", context.status)
        return result, context, fx.learning.dynamics.index.snapshot

    def test_shadow_only_bounded_index_has_stable_ties_and_scan(self):
        fx = self.fixture("bounded", dynamics=True)
        _, _, _ = self._learn_and_index(fx)
        base_policy = DynamicsPolicy(fx.scope)
        changed_index_policy = replace(
            base_policy,
            maximum_index_entries=4,
            maximum_index_candidate_scan=2,
        )
        self.assertEqual(
            base_policy.scoring_digest, changed_index_policy.scoring_digest
        )
        self.assertNotEqual(base_policy.digest, changed_index_policy.digest)
        row = fx.learning.records("DELTA")[0]
        delta = fx.learning.delta(row)
        index = CompactPheromoneIndex(
            fx.scope,
            delta.task_signature,
            mode="SHADOW",
            maximum_entries=4,
            candidate_scan_limit=2,
            maximum_token_hashes=8,
        )
        admitted, identifiers = [], []
        for ordinal in range(40):
            identifier = hashlib.sha256(f"nv08-{ordinal}".encode()).hexdigest()
            identifiers.append(identifier)
            value = replace(delta, delta_id=identifier)
            stored = fx.learning.record(
                identifier, "DELTA", {"delta": value.private_payload()}
            )
            admitted.append(
                (
                    stored,
                    value,
                    None,
                    {
                        "delta_ref": identifier,
                        "tau_positive": 0.5,
                        "tau_negative": 0.5,
                    },
                )
            )
        first = index.rebuild(tuple(admitted), actor_family=delta.model.family)
        second = index.rebuild(tuple(reversed(admitted)), actor_family=delta.model.family)
        self.assertEqual(first.snapshot_digest, second.snapshot_digest)
        self.assertEqual(40, second.source_scan_count)
        self.assertEqual(4, len(second.entries))
        self.assertTrue(second.truncated)
        self.assertEqual(tuple(sorted(identifiers)[:4]),
                         tuple(entry.reference_id for entry in second.entries))
        result = index.prioritize(QUESTION, eligible_ids=frozenset(identifiers))
        self.assertEqual(2, result.candidate_scan_count)
        self.assertEqual(tuple(sorted(identifiers)[:2]), result.reference_ids)
        self.assertFalse(second.execution_authority)
        self.assertTrue(second.verification_required)
        with self.assertRaisesRegex(MissionError, "INDEX_ACTIVE_NOT_ACCEPTED"):
            CompactPheromoneIndex(
                fx.scope,
                delta.task_signature,
                mode="ACTIVE",
                maximum_entries=4,
                candidate_scan_limit=2,
                maximum_token_hashes=8,
            )

    def test_index_retains_condition_and_verification_but_changes_no_actual_order(self):
        condition = "for a unit"
        semantics = DomainSemantics(
            OwnerScope("nv03-tenant", "nv03-owner", "nv03-space", "nv03-slot"),
            "test-hat",
            "linux-systemctl-status",
            (("policy", "v1"),),
            NOW + timedelta(days=1),
            delta_kind=SemanticDeltaKind.QUALIFY,
            required_condition=condition,
        )
        fx = self.fixture("metadata", dynamics=True, semantics=semantics)
        result, context, snapshot = self._learn_and_index(fx)
        self.assertEqual(1, len(snapshot.entries))
        entry = snapshot.entries[0]
        delta = fx.learning.delta(fx.learning.records("DELTA")[0])
        self.assertEqual(SemanticDeltaKind.QUALIFY.value, entry.semantic_kind)
        self.assertEqual(condition, entry.required_condition)
        self.assertEqual(delta.evidence_refs, entry.evidence_refs)
        self.assertEqual(delta.source_versions, entry.source_versions)
        self.assertEqual(
            tuple(
                (r.verifier_ref, r.verifier_method, r.source_family, r.input_digest)
                for r in delta.verifier_set
            ),
            entry.verifier_metadata,
        )
        self.assertEqual("VERIFIED", entry.verification_status)
        self.assertEqual("CURRENT", entry.reuse_status)
        self.assertIn(condition, entry.required_condition)
        view = fx.runtime.lite_dynamics_status()["last"]
        self.assertEqual("SHADOW", view["index"]["mode"])
        self.assertFalse(view["index"]["actual_behavior_changed"])
        self.assertEqual(
            [reference.reference_id for reference in context.selected],
            view["selected"],
        )
        self.assertIn(result["delta_id"], context.prompt_json)
        self.assertIn(condition, context.prompt_json)

    def test_high_score_cannot_revive_stale_or_unknown_delta(self):
        fx = self.fixture("stale", dynamics=True)
        result, _, _ = self._learn_and_index(fx)
        identifier = result["delta_id"]

        def boost(tx):
            trail = tx.get(RecordKind.LEARNING, "trail-" + identifier)
            payload = dict(trail.payload)
            payload.update(tau_positive=1.0, tau_negative=1.0)
            tx.replace(
                fx.learning.record(
                    trail.record_id,
                    "TRAIL",
                    payload,
                    revision=trail.revision + 1,
                ),
                expected_revision=trail.revision,
            )

        fx.learning.run(boost, write=True)
        fx.change_source_version()
        context = fx.runtime.lite_memory_retrieve(QUESTION)
        self.assertNotIn(identifier, context.prompt_json)
        snapshot = fx.learning.dynamics.index.snapshot
        self.assertEqual((), snapshot.entries)
        self.assertNotIn(identifier, json.dumps(fx.runtime.lite_dynamics_status()))
        row = fx.learning.records("DELTA")[0]
        self.assertEqual("REVALIDATION_REQUIRED", row.payload["reuse_status"])

        delta = fx.learning.delta(row)
        unknown = fx.learning.record(
            delta.delta_id,
            "DELTA",
            {**dict(row.payload), "reuse_status": "UNKNOWN"},
            revision=row.revision + 1,
        )
        index = CompactPheromoneIndex(
            fx.scope,
            delta.task_signature,
            mode="SHADOW",
            maximum_entries=4,
            candidate_scan_limit=2,
            maximum_token_hashes=8,
        )
        with self.assertRaisesRegex(MissionError, "INDEX_ELIGIBILITY_MISMATCH"):
            index.rebuild(
                ((unknown, delta, None, {
                    "delta_ref": delta.delta_id,
                    "tau_positive": 1.0,
                    "tau_negative": 1.0,
                }),),
                actor_family=delta.model.family,
            )

    def test_replay_creates_no_second_delta_reward_or_index_artifact(self):
        fx = self.fixture("replay", dynamics=True)
        first, context, snapshot = self._learn_and_index(fx)
        states = ("DELTA", "EPISODE", "PHEROMONE_EVENT", "TRAIL", "DEPENDENCY")
        before = {state: len(fx.learning.records(state)) for state in states}
        before_file = fx.factory.path.read_bytes()
        replay = fx.ask("nv08-one", question="Different replay text must be inert.")
        self.assertEqual("REPLAY", replay["status"])
        self.assertEqual(before_file, fx.factory.path.read_bytes())
        after_context = fx.runtime.lite_memory_retrieve(QUESTION)
        after = {state: len(fx.learning.records(state)) for state in states}
        self.assertEqual(before, after)
        self.assertEqual(1, after["DELTA"])
        self.assertEqual(1, after["EPISODE"])
        self.assertEqual(1, after["PHEROMONE_EVENT"])
        self.assertEqual((), fx.learning.records("INDEX_EVENT"))
        self.assertEqual(snapshot.snapshot_digest,
                         fx.learning.dynamics.index.snapshot.snapshot_digest)
        self.assertEqual(context.prompt_json, after_context.prompt_json)
        self.assertEqual(first["delta_id"], snapshot.entries[0].reference_id)

    def test_concurrent_same_submission_is_one_delta_event_and_index_entry(self):
        fx = self.fixture("concurrent", dynamics=True)
        fx.consent()

        def submit():
            return fx.learning.evaluate(
                WRONG,
                RIGHT,
                trace_id="same-event",
                cpl_ref="controlled-in-process-proposal",
                critic_families=(),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(["DUPLICATE", "VERIFIED"],
                         sorted(result["status"] for result in results))
        self.assertEqual(1, len(fx.learning.records("DELTA")))
        self.assertEqual(1, len(fx.learning.records("EPISODE")))
        self.assertEqual(1, len(fx.learning.records("PHEROMONE_EVENT")))
        context = fx.memory_bindings.profile  # composition remains the existing one
        self.assertEqual("repository-durable-test", context.backend_id)
        fx.runtime.lite_memory_retrieve(fx.learning.policy.task_instruction)
        self.assertEqual(1, len(fx.learning.dynamics.index.snapshot.entries))
        self.assertEqual((), fx.learning.records("INDEX_EVENT"))

    def test_concurrent_insert_after_eligibility_read_is_not_false_revalidation(self):
        fx = self.fixture("snapshot-race", dynamics=True)
        fx.consent()
        reader = [None]
        lock = threading.Lock()
        committed, classified = threading.Event(), threading.Event()
        original_eligible = fx.learning.eligible_deltas
        original_persist = fx.learning.persist
        original_context = fx.learning.dynamics.before_context

        def eligible(*args, **kwargs):
            values = original_eligible(*args, **kwargs)
            pause = False
            with lock:
                if reader[0] is None and not values:
                    reader[0] = threading.get_ident()
                    pause = True
            if pause:
                self.assertTrue(committed.wait(10), "peer did not commit")
            return values

        def persist(*args, **kwargs):
            result = original_persist(*args, **kwargs)
            if threading.get_ident() != reader[0] and not committed.is_set():
                committed.set()
                self.assertTrue(classified.wait(10), "reader did not classify")
            return result

        def context(*args, **kwargs):
            try:
                return original_context(*args, **kwargs)
            finally:
                if threading.get_ident() == reader[0] and committed.is_set():
                    classified.set()

        def submit():
            return fx.learning.evaluate(
                WRONG, RIGHT, trace_id="snapshot-race", cpl_ref="verified-fixture",
                critic_families=(),
            )

        with (
            patch.object(fx.learning, "eligible_deltas", side_effect=eligible),
            patch.object(fx.learning, "persist", side_effect=persist),
            patch.object(fx.learning.dynamics, "before_context", side_effect=context),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            futures = [executor.submit(submit) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(["DUPLICATE", "VERIFIED"], sorted(r["status"] for r in results))
        row, = fx.learning.records("DELTA")
        self.assertEqual("CURRENT", row.payload.get("reuse_status", "CURRENT"))
        self.assertEqual((), fx.learning.records("OBLIGATION"))
        for state in ("DELTA", "EPISODE", "PHEROMONE_EVENT"):
            self.assertEqual(1, len(fx.learning.records(state)))
        self.assertEqual("READY", fx.runtime.lite_memory_retrieve(QUESTION).status)
        self.assertEqual(1, len(fx.learning.dynamics.index.snapshot.entries))
        self.assertEqual((), fx.learning.records("INDEX_EVENT"))

    def test_concurrent_stale_replay_stays_blocked_without_new_effects(self):
        fx = self.fixture("stale-replay", dynamics=True)
        fx.consent()

        def submit():
            return fx.learning.evaluate(
                WRONG, RIGHT, trace_id="same-stale-key", cpl_ref="verified-fixture",
                critic_families=(),
            )

        submit()
        fx.now += timedelta(seconds=301)
        fx.runtime.lite_memory_retrieve(QUESTION)
        row, = fx.learning.records("DELTA")
        self.assertEqual("REVALIDATION_REQUIRED", row.payload["reuse_status"])
        before = fx.factory.path.read_bytes()
        barrier = threading.Barrier(2)

        def blocked():
            barrier.wait(timeout=10)
            with self.assertRaisesRegex(MissionError, "DELTA_REVALIDATION_REQUIRED"):
                submit()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(blocked) for _ in range(2)]
            for future in futures:
                future.result(timeout=20)
        self.assertEqual(before, fx.factory.path.read_bytes())
        self.assertEqual(1, len(fx.learning.records("DELTA")))
        self.assertEqual(1, len(fx.learning.records("PHEROMONE_EVENT")))
        self.assertEqual((), fx.learning.dynamics.index.snapshot.entries)
        self.assertEqual((), fx.learning.records("INDEX_EVENT"))

    def test_source_change_before_commit_requires_new_current_verification(self):
        fx = self.fixture("source-before-commit", dynamics=True)
        fx.consent()
        original = fx.learning.native.transactions.run
        writes = []

        def change_before_write(context, callback):
            if context.purpose is Capability.MANAGE:
                writes.append(context.purpose)
                if len(writes) == 1:
                    fx.change_source_version()
            return original(context, callback)

        with patch.object(fx.learning.native.transactions, "run", side_effect=change_before_write):
            with self.assertRaises(MemoryPatchError) as failure:
                fx.learning.evaluate(WRONG, RIGHT, trace_id="old-basis",
                                     cpl_ref="verified-fixture", critic_families=())
        self.assertEqual("SOURCE_CHANGED_BEFORE_WRITE", str(failure.exception.__cause__))
        self.assertEqual(1, len(writes))
        for state in ("DELTA", "EPISODE", "PHEROMONE_EVENT", "INDEX_EVENT"):
            self.assertEqual((), fx.learning.records(state))
        # The operator's new independent rule binding is needed for v2.
        fx.learning.verifiers = tuple(
            replace(binding, verifier=replace(binding.verifier, source_versions=(("policy", "v2"),)))
            if binding.verifier_ref == "controlled-domain-rule" else binding
            for binding in fx.learning.verifiers
        )
        result = fx.learning.evaluate(WRONG, RIGHT, trace_id="new-basis",
                                      cpl_ref="verified-fixture", critic_families=())
        self.assertEqual("VERIFIED", result["status"])
        self.assertEqual((("policy", "v2"),), fx.learning.delta(fx.learning.records("DELTA")[0]).source_versions)

    def test_replay_after_explicit_revalidation_has_no_second_reward_or_index(self):
        fx = self.fixture("revalidated-replay", dynamics=True)
        fx.consent()

        def submit():
            return fx.learning.evaluate(WRONG, RIGHT, trace_id="revalidated-key",
                                        cpl_ref="verified-fixture", critic_families=())

        submit()
        fx.now += timedelta(seconds=301)
        fx.runtime.lite_memory_retrieve(QUESTION)
        obligation, = fx.learning.records("OBLIGATION")
        self.assertEqual("RESOLVED", fx.learning.dynamics.revalidate(obligation.record_id)["status"])
        context = fx.runtime.lite_memory_retrieve(QUESTION)
        snapshot = fx.learning.dynamics.index.snapshot
        before = fx.factory.path.read_bytes()
        self.assertEqual("DUPLICATE", submit()["status"])
        self.assertEqual("ALREADY_RESOLVED", fx.learning.dynamics.revalidate(obligation.record_id)["status"])
        self.assertEqual(before, fx.factory.path.read_bytes())
        self.assertEqual(context.prompt_json, fx.runtime.lite_memory_retrieve(QUESTION).prompt_json)
        self.assertEqual(snapshot.snapshot_digest, fx.learning.dynamics.index.snapshot.snapshot_digest)
        self.assertEqual(1, len(fx.learning.records("REVALIDATION_EVENT")))
        self.assertEqual(1, len(fx.learning.records("DELTA")))
        self.assertEqual((), fx.learning.records("INDEX_EVENT"))

    def test_high_tau_does_not_override_revoked_consent(self):
        fx = self.fixture("revoked", dynamics=True)
        result, _, _ = self._learn_and_index(fx)

        def boost(tx):
            row = tx.get(RecordKind.LEARNING, "trail-" + result["delta_id"])
            tx.replace(fx.learning.record(row.record_id, "TRAIL",
                       {**dict(row.payload), "tau_positive": 1.0, "tau_negative": 1.0},
                       revision=row.revision + 1), expected_revision=row.revision)

        fx.learning.run(boost, write=True)
        fx.consent(ConsentMode.OFF)
        before = fx.factory.path.read_bytes()
        context = fx.runtime.lite_memory_retrieve(QUESTION)
        self.assertNotIn(result["delta_id"], context.prompt_json)
        self.assertEqual((), fx.learning.dynamics.index.snapshot.entries)
        denied = fx.learning.evaluate(WRONG, RIGHT, trace_id="revoked-write",
                                     cpl_ref="verified-fixture", critic_families=())
        self.assertEqual("ZERO_WRITE", denied["knowledge_write"])
        self.assertEqual("CONSENT_OFF", denied["reason"])
        self.assertEqual(before, fx.factory.path.read_bytes())

    def test_two_owner_shared_store_has_no_read_score_log_or_index_leak(self):
        a = self.fixture("owner-a", dynamics=True)
        b = self.fixture(
            "owner-b",
            scope=replace(a.scope, owner_id="nv08-owner-b"),
            replies=(RIGHT,),
            dynamics=True,
        )
        shared = self.root / "shared-memory.json"
        a.factory.path = b.factory.path = shared
        a.consent()
        b.consent()
        learned = a.ask("owner-a-event")
        self.assertEqual("CREATED", learned["knowledge_write"], learned)
        other = b.ask("owner-b-event")
        self.assertEqual("ZERO_WRITE", other["knowledge_write"], other)
        a.runtime.lite_memory_retrieve(QUESTION)
        context = b.runtime.lite_memory_retrieve(QUESTION)
        observable = json.dumps(
            {
                "context": context.prompt_json,
                "dynamics": b.runtime.lite_dynamics_status(),
                "metrics": b.learning.storage_metrics(),
                "log": b.runtime._lite_scheduler.journal.evidence(),
                "index": b.learning.dynamics.index.snapshot.metrics(),
            },
            sort_keys=True,
        )
        self.assertNotIn(learned["delta_id"], observable)
        self.assertNotIn(a.scope.owner_id, observable)
        self.assertEqual((), b.learning.dynamics.index.snapshot.entries)
        self.assertEqual(0, b.learning.storage_metrics()["accepted_minimal_delta_count"])

    def test_fresh_process_rebuilds_equivalent_index_and_context(self):
        fx = self.fixture("restart", dynamics=True)
        learned, context, snapshot = self._learn_and_index(fx)
        root = fx.root
        fx.close()
        code = r'''import json,sys
from pathlib import Path
from nv07_support import ChatFixture, QUESTION, RIGHT
fx=ChatFixture(Path(sys.argv[1]), replies=(RIGHT,), dynamics=True)
context=fx.runtime.lite_memory_retrieve(QUESTION)
snapshot=fx.learning.dynamics.index.snapshot
print(json.dumps({"prompt":context.prompt_json,"digest":snapshot.snapshot_digest,
                  "entries":[e.reference_id for e in snapshot.entries],
                  "would_select":fx.runtime.lite_dynamics_status()["last"]["index"]["would_select"]}))
fx.close()
'''
        env = dict(
            os.environ,
            PYTHONPATH=str(Path(__file__).resolve().parents[1])
            + os.pathsep
            + str(Path(__file__).parent),
        )
        child = subprocess.run(
            [sys.executable, "-B", "-c", "import runtime\n" + code, str(root)],
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
        )
        observed = json.loads(child.stdout)
        self.assertEqual(context.prompt_json, observed["prompt"])
        self.assertEqual(snapshot.snapshot_digest, observed["digest"])
        self.assertEqual([learned["delta_id"]], observed["entries"])
        self.assertIn(learned["delta_id"], observed["would_select"])


if __name__ == "__main__":
    unittest.main()
