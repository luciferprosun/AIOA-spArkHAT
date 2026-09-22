"""NV07/NV08 isolation regressions on explicit file fixtures, never LIVE SQL."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
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
from runtime.memory_patch.learning.personal_contracts import ConsentMode
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission.contracts import MissionError


class SharedOwnerIsolationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.count = 0

    def fixture(self, **kwargs):
        self.count += 1
        fx = ChatFixture(self.root / str(self.count), dynamics=True, **kwargs)
        self.addCleanup(fx.close)
        return fx

    def pair(self, *, other_tenant=False):
        a = self.fixture()
        scope = replace(a.scope, owner_id="closure-owner-b")
        if other_tenant:
            scope = replace(scope, tenant_id="closure-tenant-b")
        b = self.fixture(scope=scope)
        a.factory.path = b.factory.path = self.root / f"shared-{self.count}.json"
        a.consent()
        b.consent()
        return a, b

    def learn_pair(self, a, b):
        barrier = threading.Barrier(2)

        def learn(fx):
            barrier.wait(timeout=10)
            return fx.ask("same-operation", question=QUESTION + " private:" + fx.scope.owner_id)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(learn, fx) for fx in (a, b)]
            results = [future.result(timeout=20) for future in futures]
        for result in results:
            self.assertEqual("CREATED", result["knowledge_write"], result)
        self.assertNotEqual(results[0]["delta_id"], results[1]["delta_id"])
        return tuple(result["delta_id"] for result in results)

    def observe(self, fx):
        context = fx.runtime.lite_memory_retrieve(QUESTION)
        dynamics = fx.learning.dynamics
        return {
            "prompt": context.prompt_json,
            "deltas": [row.record_id for row in fx.learning.records("DELTA")],
            "cache_keys": list(dynamics._current),
            "cache_row_keys": list(dynamics._current_rows),
            "index_refs": [entry.reference_id for entry in dynamics.index.snapshot.entries],
            "index_digest": dynamics.index.snapshot.snapshot_digest,
            "scores": fx.runtime.lite_dynamics_status(),
            "metrics": fx.learning.storage_metrics(),
            "log": fx.runtime._lite_scheduler.journal.evidence(),
            "calls": fx.transport.calls,
        }

    def assert_scoped(self, fx, other, own_id, foreign_id):
        observed = self.observe(fx)
        rendered = json.dumps(observed, sort_keys=True)
        self.assertNotIn(foreign_id, rendered)
        self.assertNotIn(other.scope.owner_id, rendered)
        self.assertEqual([own_id], observed["deltas"])
        self.assertEqual([own_id], observed["cache_keys"])
        self.assertEqual([own_id], observed["cache_row_keys"])
        self.assertEqual([own_id], observed["index_refs"])
        self.assertIn(own_id, observed["prompt"])
        for row in fx.learning.records("DELTA"):
            self.assertEqual(fx.scope, row.scope)
        return observed

    def test_two_owners_concurrently_share_physical_store_with_private_views(self):
        a, b = self.pair()
        aid, bid = self.learn_pair(a, b)
        self.assertIsNot(a.factory.state, b.factory.state)
        self.assertIsNot(a.learning.dynamics, b.learning.dynamics)
        self.assertIsNot(a.learning.dynamics.index, b.learning.dynamics.index)
        self.assert_scoped(a, b, aid, bid)
        self.assert_scoped(b, a, bid, aid)
        physical = [json.loads(raw) for raw, _ in json.loads(a.factory.path.read_text())]
        self.assertEqual({aid, bid}, {r["record_id"] for r in physical
                                     if r["payload"].get("state") == "DELTA"})

    def test_read_write_during_other_owner_revalidation_never_exposes_private_state(self):
        a, b = self.pair()
        aid, bid = self.learn_pair(a, b)
        a.now += timedelta(seconds=301)
        self.assertNotIn(aid, a.runtime.lite_memory_retrieve(QUESTION).prompt_json)
        obligation, = a.learning.records("OBLIGATION")
        verified, other_done = threading.Event(), threading.Event()
        original = a.learning.dynamics._current_delta

        def hold_verified(*args, **kwargs):
            result = original(*args, **kwargs)
            verified.set()
            self.assertTrue(other_done.wait(10), "other owner did not finish")
            return result

        def other_operation():
            self.assertTrue(verified.wait(10), "revalidation did not verify")
            try:
                result = b.ask("during-a-revalidation")
                self.assertEqual("ZERO_WRITE", result["knowledge_write"], result)
                self.assert_scoped(b, a, bid, aid)
            finally:
                other_done.set()

        with (patch.object(a.learning.dynamics, "_current_delta", side_effect=hold_verified),
              ThreadPoolExecutor(max_workers=2) as executor):
            future = executor.submit(a.learning.dynamics.revalidate, obligation.record_id)
            other = executor.submit(other_operation)
            self.assertEqual("RESOLVED", future.result(timeout=20)["status"])
            other.result(timeout=20)
        self.assert_scoped(a, b, aid, bid)
        self.assert_scoped(b, a, bid, aid)

    def test_same_owner_concurrent_replay_has_one_delta_reward_and_index(self):
        fx = self.fixture()
        fx.consent()
        barrier = threading.Barrier(2)

        def submit():
            barrier.wait(timeout=10)
            return fx.learning.evaluate(WRONG, RIGHT, trace_id="same-key",
                                        cpl_ref="controlled-proposal", critic_families=())

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(["DUPLICATE", "VERIFIED"], sorted(r["status"] for r in results))
        self.assertEqual(1, len({r["delta_id"] for r in results}))
        for state in ("DELTA", "EPISODE", "PHEROMONE_EVENT"):
            self.assertEqual(1, len(fx.learning.records(state)), state)
        fx.runtime.lite_memory_retrieve(QUESTION)
        self.assertEqual(1, len(fx.learning.dynamics.index.snapshot.entries))
        self.assertEqual((), fx.learning.records("INDEX_EVENT"))

    def test_cross_tenant_same_operation_key_replays_only_its_scoped_outcome(self):
        a, b = self.pair(other_tenant=True)
        aid, bid = self.learn_pair(a, b)
        before = a.factory.path.read_bytes()
        for fx, own, foreign in ((a, aid, bid), (b, bid, aid)):
            replay = fx.ask("same-operation", question="Replay must not execute this text.")
            self.assertEqual("REPLAY", replay["status"], replay)
            self.assertEqual(1, len(fx.learning.records("DELTA")))
            self.assertEqual(own, fx.learning.records("DELTA")[0].record_id)
            self.assertNotIn(foreign, json.dumps(replay))
            self.assertEqual(1, len(fx.learning.records("EPISODE")))
            self.assertEqual(1, len(fx.learning.records("PHEROMONE_EVENT")))
        self.assertEqual(before, a.factory.path.read_bytes())
        self.assert_scoped(a, b, aid, bid)
        self.assert_scoped(b, a, bid, aid)

    def test_close_and_reload_of_one_owner_preserves_other_active_transaction(self):
        a, b = self.pair()
        aid, bid = self.learn_pair(a, b)
        active, closed, reloading = threading.Event(), threading.Event(), threading.Event()

        def update(tx):
            row = tx.get(RecordKind.LEARNING, bid)
            self.assertIsNotNone(row)
            active.set()
            self.assertTrue(closed.wait(10), "other owner did not close")
            self.assertTrue(reloading.wait(10), "other owner did not reload")
            self.assertEqual(row, tx.get(RecordKind.LEARNING, bid))
            self.assertIsNone(tx.get(RecordKind.LEARNING, aid))
            tx.replace(b.learning.record(bid, "DELTA", dict(row.payload),
                       revision=row.revision + 1), expected_revision=row.revision)

        def reload_owner():
            restarted = ChatFixture(a.root, scope=a.scope, replies=(RIGHT,), dynamics=True)
            try:
                restarted.factory.path = b.factory.path
                reloading.set()
                return [row.record_id for row in restarted.learning.records("DELTA")]
            finally:
                restarted.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            writer = executor.submit(b.learning.run, update, write=True)
            self.assertTrue(active.wait(10), "other owner transaction did not start")
            a.close()
            closed.set()
            reader = executor.submit(reload_owner)
            writer.result(timeout=20)
            self.assertEqual([aid], reader.result(timeout=20))
        self.assert_scoped(b, a, bid, aid)
        self.assertEqual(b.factory.opens, b.factory.closes)

    def test_source_change_during_other_owner_context_invalidates_only_affected_owner(self):
        a, b = self.pair()
        aid, bid = self.learn_pair(a, b)
        cached, invalidated = threading.Event(), threading.Event()
        original = b.learning.dynamics.before_context

        def held_context(*args, **kwargs):
            result = original(*args, **kwargs)
            cached.set()
            self.assertTrue(invalidated.wait(10), "source change did not finish")
            return result

        def change():
            self.assertTrue(cached.wait(10), "other owner context did not start")
            try:
                a.change_source_version()
                self.assertNotIn(aid, a.runtime.lite_memory_retrieve(QUESTION).prompt_json)
            finally:
                invalidated.set()

        with (patch.object(b.learning.dynamics, "before_context", side_effect=held_context),
              ThreadPoolExecutor(max_workers=2) as executor):
            reader = executor.submit(b.runtime.lite_memory_retrieve, QUESTION)
            changer = executor.submit(change)
            self.assertIn(bid, reader.result(timeout=20).prompt_json)
            changer.result(timeout=20)
        self.assertEqual("REVALIDATION_REQUIRED", a.learning.records("DELTA")[0].payload["reuse_status"])
        self.assertEqual("CURRENT", b.learning.records("DELTA")[0].payload.get("reuse_status", "CURRENT"))
        with self.assertRaisesRegex(MissionError, "DELTA_REVALIDATION_REQUIRED"):
            a.learning.dynamics._current_delta(aid)
        self.assertEqual((), a.learning.dynamics.index.snapshot.entries)
        self.assert_scoped(b, a, bid, aid)

    def test_high_score_never_revives_stale_revoked_or_revalidation_required_memory(self):
        for cause in ("age", "source-version", "consent"):
            with self.subTest(cause=cause):
                a, b = self.pair()
                aid, bid = self.learn_pair(a, b)

                def boost(tx):
                    row = tx.get(RecordKind.LEARNING, "trail-" + aid)
                    tx.replace(a.learning.record(row.record_id, "TRAIL",
                               {**dict(row.payload), "tau_positive": 1.0, "tau_negative": 1.0},
                               revision=row.revision + 1), expected_revision=row.revision)

                a.learning.run(boost, write=True)
                if cause == "age":
                    a.now += timedelta(seconds=301)
                elif cause == "source-version":
                    a.change_source_version()
                else:
                    a.consent(ConsentMode.OFF)
                observed = self.observe(a)
                self.assertNotIn(aid, observed["prompt"])
                self.assertEqual([], observed["index_refs"])
                self.assertEqual([], observed["cache_keys"])
                self.assert_scoped(b, a, bid, aid)

    def test_fresh_process_reconstructs_both_scopes_without_cross_owner_artifacts(self):
        a, b = self.pair(other_tenant=True)
        aid, bid = self.learn_pair(a, b)
        expected = [self.assert_scoped(a, b, aid, bid), self.assert_scoped(b, a, bid, aid)]
        configs = [{"root": str(fx.root), "scope": asdict(fx.scope)} for fx in (a, b)]
        a.close()
        b.close()
        code = '''import json,sys
from pathlib import Path
from nv07_support import ChatFixture, QUESTION, RIGHT
from runtime.core_admission import OwnerScope
out=[]
for config in json.loads(sys.argv[1]):
    fx=ChatFixture(Path(config['root']),scope=OwnerScope(**config['scope']),replies=(RIGHT,),dynamics=True)
    try:
        fx.factory.path=Path(sys.argv[2])
        replay=fx.ask('same-operation')
        context=fx.runtime.lite_memory_retrieve(QUESTION)
        dyn=fx.learning.dynamics
        out.append(dict(replay=replay['status'],prompt=context.prompt_json,
            deltas=[r.record_id for r in fx.learning.records('DELTA')],
            cache_keys=list(dyn._current),cache_row_keys=list(dyn._current_rows),
            index_refs=[e.reference_id for e in dyn.index.snapshot.entries],
            index_digest=dyn.index.snapshot.snapshot_digest,scores=fx.runtime.lite_dynamics_status(),
            log=fx.runtime._lite_scheduler.journal.evidence(),calls=fx.transport.calls))
    finally: fx.close()
print(json.dumps(out))
'''
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(root) + os.pathsep + str(root / "tests"))
        child = subprocess.run([sys.executable, "-B", "-c", "import runtime\n" + code,
                                json.dumps(configs), str(a.factory.path)],
                               env=env, text=True, capture_output=True, timeout=30, check=True)
        observed = json.loads(child.stdout)
        self.assertEqual(2, len(observed))
        for index, (own, foreign, other) in enumerate(((aid, bid, b), (bid, aid, a))):
            result = observed[index]
            self.assertEqual("REPLAY", result["replay"])
            for field in ("deltas", "cache_keys", "cache_row_keys", "index_refs"):
                self.assertEqual([own], result[field], field)
            self.assertIn(own, result["prompt"])
            self.assertEqual(expected[index]["index_digest"], result["index_digest"])
            self.assertNotIn(foreign, json.dumps(result))
            self.assertNotIn(other.scope.owner_id, json.dumps(result))
            self.assertEqual([], result["calls"])


if __name__ == "__main__":
    unittest.main()
