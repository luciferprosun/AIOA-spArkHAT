"""NV10 adversarial knowledge matrix. LOCAL_CONTROLLED + durable JSON FIXTURE."""

from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nv07_support import ChatFixture, QUESTION, RIGHT, WRONG
from nv10_support import POISON, child, evidence, learn
from runtime.core_admission import Capability
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.learning.contracts import EpistemicDelta
from runtime.memory_patch.learning.personal_contracts import ConsentMode
from runtime.memory_patch.lite import LiteMemoryService
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission.contracts import MissionError


class NV10MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, name="memory", **kwargs):
        fx = ChatFixture(self.root / name, dynamics=True, **kwargs)
        self.addCleanup(fx.close)
        return fx

    def admitted_delta(self, fx):
        fx.consent()
        result = learn(fx)
        self.assertEqual("CREATED", result["knowledge_write"], result)
        identifier = result["delta_id"]
        self.assertIn(identifier, [r.reference_id for r in
                                 fx.runtime.lite_memory_retrieve(QUESTION).eligible])
        return identifier

    def test_observed_expiry_survives_clock_rollback_and_fresh_process(self):
        fx = self.fixture()
        identifier = self.admitted_delta(fx)
        initial = fx.now
        fx.now += timedelta(hours=2)
        self.assertFalse(fx.personal.allowed(write=True))
        revision = fx.personal.describe()["revision"]
        self.assertEqual(2, revision)
        fx.now = initial
        self.assertFalse(fx.personal.allowed())
        self.assertEqual(revision, fx.personal.describe()["revision"])
        self.assertNotIn(identifier, fx.runtime.lite_memory_retrieve(QUESTION).prompt_json)
        fx.close()
        fresh = child({"mode": "chat-probe", "root": str(fx.root), "clock": initial.isoformat()})
        self.assertNotEqual(os.getpid(), fresh["pid"])
        self.assertFalse(fresh["consent"]["automatic_write_allowed"])
        self.assertNotIn(identifier, fresh["eligible"])
        self.assertEqual([[['policy', 'v1']]], fresh["delta_versions"])
        self.assertEqual(list(fx.scope.binding()), fresh["scope"])
        self.assertEqual(0, fresh["actor_calls"])
        evidence("consent-clock-rollback", label="FIXTURE", revision=revision,
                 clock_t1=initial.isoformat(), clock_t2=(initial + timedelta(hours=2)).isoformat(),
                 fresh_pid=fresh["pid"], revivals=0)

    def test_write_time_expiry_rolls_back_then_persists_denial(self):
        fx = self.fixture()
        fx.consent()
        initial = fx.now
        fx.now += timedelta(hours=2)
        entered = []
        with self.assertRaises(MemoryPatchError):
            fx.learning.run(lambda tx: entered.append(True), write=True)
        self.assertEqual([], entered)
        self.assertEqual((), fx.learning.records("DELTA"))
        fx.now = initial
        self.assertFalse(fx.personal.allowed(write=True))
        self.assertEqual(2, fx.personal.describe()["revision"])
        evidence("write-expiry-after-rollback", partial_mutations=0, expiry_durable=True)

    def test_expiry_observation_never_overwrites_explicit_new_owner_consent(self):
        fx = self.fixture()
        fx.consent()
        old = fx.learning.run(fx.personal._read)
        future = fx.now + timedelta(hours=2)
        fx.consent()
        renewed = fx.learning.run(fx.personal._read)
        fx.personal.record_expiry(old, future)
        current = fx.learning.run(fx.personal._read)
        self.assertEqual(renewed, current)
        self.assertTrue(fx.personal.allowed(write=True))
        self.assertEqual(2, current.revision)

    def test_expiry_latch_unknown_is_fail_closed_and_read_back_before_reuse(self):
        from nv03_support import DurableTransaction
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        fx = self.fixture()
        fx.consent()
        initial = fx.now
        fx.now += timedelta(hours=2)
        original = DurableTransaction.commit

        def lost_ack(tx):
            original(tx)
            if tx.context.purpose is Capability.MANAGE:
                raise OSError("controlled ACK loss after durable expiry latch")

        with patch.object(DurableTransaction, "commit", lost_ack):
            with self.assertRaises(CommitOutcomeUnknown):
                fx.personal.allowed()
        fx.now = initial
        self.assertFalse(fx.personal.allowed())
        self.assertEqual(2, fx.personal.describe()["revision"])

    def test_revoke_rollback_keeps_history_and_clears_current_index(self):
        fx = self.fixture()
        identifier = self.admitted_delta(fx)
        initial = fx.now
        fx.now += timedelta(seconds=2)
        fx.consent(ConsentMode.OFF)
        fx.now = initial
        context = fx.runtime.lite_memory_retrieve(QUESTION)
        self.assertNotIn(identifier, context.prompt_json)
        self.assertEqual((), fx.learning.dynamics.index.snapshot.entries)
        self.assertEqual([identifier], [r.record_id for r in fx.learning.records("DELTA")])
        self.assertEqual("OFF", fx.personal.describe()["mode"])
        fx.close()
        fresh = child({"mode": "chat-probe", "root": str(fx.root), "clock": initial.isoformat()})
        self.assertEqual("OFF", fresh["consent"]["mode"])
        self.assertNotIn(identifier, fresh["eligible"])
        self.assertEqual(0, fresh["actor_calls"])
        evidence("revoked-memory-clock", fresh_pid=fresh["pid"], revoked_uses=0, retained_deltas=1)

    def test_missing_source_variants_never_reuse_delta_or_model_memory(self):
        for variant in ("reference_removed", "withdrawn", "resolver_missing", "version_unavailable"):
            with self.subTest(variant=variant):
                fx = self.fixture(variant)
                identifier = self.admitted_delta(fx)
                if variant == "reference_removed":
                    fx.sources.reviewed.clear()
                elif variant == "withdrawn":
                    for key, record in list(fx.catalog.records.items()):
                        fx.catalog.records[key] = replace(record, withdrawn=True)
                elif variant == "resolver_missing":
                    missing = patch.object(fx.sources, "scan_scope", return_value=())
                    missing.start()
                    self.addCleanup(missing.stop)
                else:
                    fx.catalog.records.clear()
                context = fx.runtime.lite_memory_retrieve(QUESTION)
                self.assertNotIn(identifier, context.prompt_json)
                self.assertNotIn(identifier, [r.reference_id for r in context.eligible])
                with self.assertRaisesRegex(MissionError, "MEMORY_DEGRADED|CURRENT_AUTHORITATIVE_EVIDENCE_REQUIRED"):
                    learn(fx, trace="missing-source-episode")
                self.assertEqual([identifier], [r.record_id for r in fx.learning.records("DELTA")])
                self.assertEqual([], fx.transport.calls)
                evidence("source-unavailable", stimulus=variant, status=context.status,
                         reason_codes=list(context.reason_codes), current_delta_uses=0)

    def test_source_a_b_a2_does_not_restore_original_binding(self):
        fx = self.fixture()
        identifier = self.admitted_delta(fx)
        versions = ["v1"]
        for version, text in (("v2", "A distinct reviewed policy applies."), ("v3", RIGHT)):
            prior = versions[-1]
            for key, record in list(fx.catalog.records.items()):
                if record.source.source_version_id == prior:
                    fx.metadata[key] = {**fx.metadata[key], "document_identity": "policy",
                                        "provision_identifier": "rule", "version_identity": prior,
                                        "superseded_by": [version]}
                    fx._source(record)
            fx.add_source("policy", version, text, metadata={
                "document_identity": "policy", "provision_identifier": "rule",
                "version_identity": version, "supersedes": [prior],
                "effective_from": "2020-01-01", "verified_at": fx.now.isoformat()})
            versions.append(version)
            context = fx.runtime.lite_memory_retrieve(QUESTION)
            self.assertNotIn(identifier, context.prompt_json)
        fx.save_corpus()
        old = fx.learning.records("DELTA")[0]
        self.assertEqual("REVALIDATION_REQUIRED", old.payload["reuse_status"])
        self.assertEqual((("policy", "v1"),), fx.learning.delta(old).source_versions)
        self.assertEqual({"v1", "v2", "v3"}, {r.source.source_version_id for r in fx.catalog.records.values()})
        self.assertEqual([], fx.transport.calls)
        fx.close()
        fresh = child({"mode": "chat-probe", "root": str(fx.root)})
        self.assertNotIn(identifier, fresh["eligible"])
        evidence("source-ABA2", versions=versions, old_binding="v1", rollback_reuse=0,
                 fresh_pid=fresh["pid"])

    def test_conflicting_independent_verifiers_return_explicit_contested_result(self):
        fx = self.fixture(oracle=WRONG)
        fx.consent()
        context = fx.learning.memory.retrieve(QUESTION)
        sources = fx.learning._sources(context.eligible, context.canonical_bundle)
        supported, receipts = fx.learning.verify(RIGHT, sources)
        self.assertFalse(supported)
        self.assertEqual({True, False}, {r.supported for r in receipts})
        result = learn(fx)
        self.assertEqual("CONTESTED", result["status"])
        self.assertEqual("INDEPENDENT_VERIFICATION_NOT_MET", result["reason"])
        self.assertEqual((), fx.learning.records("DELTA"))
        self.assertEqual(result, fx.learning.last)
        evidence("verifier-conflict", status=result["status"], false_verified=0,
                 receipts=[{"verifier": r.verifier_ref, "supported": r.supported,
                            "input_digest": r.input_digest} for r in receipts])

    def test_source_and_summary_instructions_are_data_without_consent_or_truth(self):
        fx = self.fixture(source_text=POISON, proposal=POISON, oracle=RIGHT)
        result = fx.learning.evaluate(WRONG, POISON, trace_id="poison",
                                     cpl_ref="poisoned-summary", critic_families=("model-agreement",))
        self.assertEqual("CONTESTED", result["status"])
        self.assertFalse(result["execution_authority"])
        self.assertEqual(0, result["critic_independent_proofs"])
        self.assertEqual("OFF", fx.personal.describe()["mode"])
        self.assertEqual((), fx.learning.records("DELTA"))
        self.assertIsNone(fx.runtime.executor)
        self.assertEqual([], fx.transport.calls)

    def test_unknown_native_and_index_schema_and_truncated_delta_reject(self):
        fx = self.fixture()
        self.admitted_delta(fx)
        for version, binding_version in (("memory-patch-native-v999", "memory-patch-native-v1"),
                                         ("memory-patch-native-v999", "memory-patch-native-v999")):
            profile = replace(fx.memory_profile, schema_version=version)
            lite = replace(fx.profile, memory_profile_digest=profile.digest)
            bindings = replace(fx.memory_bindings, profile=profile, schema_version=binding_version)
            with self.assertRaisesRegex(MissionError, "MEMORY_BINDING_MISMATCH"):
                LiteMemoryService(lite, fx.context, bindings)
        snapshot = fx.learning.dynamics.index.snapshot
        with self.assertRaisesRegex(MissionError, "INVALID_COMPACT_INDEX"):
            replace(snapshot, schema="native-compact-pheromone-index-v999")
        delta = fx.learning.delta(fx.learning.records("DELTA")[0])
        # Use the canonical DTO encoding, not a hand-built alternative schema.
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        raw = json.loads(canonical_json_bytes(delta.private_payload()))
        del raw["source_versions"]
        with self.assertRaises((TypeError, ValueError, KeyError)):
            EpistemicDelta.restore(raw)
        evidence("schema-mismatch", native_unknown="REJECTED", index_unknown="REJECTED",
                 incomplete_delta="REJECTED", dictionary="NOT_APPLICABLE")

    def test_cache_index_loss_rebuilds_from_evidence_and_never_from_score(self):
        fx = self.fixture()
        identifier = self.admitted_delta(fx)
        before = fx.learning.dynamics.index.snapshot
        fx.learning.dynamics._current.clear()
        fx.learning.dynamics._current_rows.clear()
        fx.learning.dynamics.index.clear()
        self.assertEqual((), fx.learning.dynamics.index.snapshot.entries)
        # Recreating the actual runtime discards derived in-memory index/cache.
        fx.close()
        fresh = self.fixture()
        context = fresh.runtime.lite_memory_retrieve(QUESTION)
        self.assertIn(identifier, [r.reference_id for r in context.eligible])
        self.assertEqual(before.snapshot_digest, fresh.learning.dynamics.index.snapshot.snapshot_digest)
        fresh.consent(ConsentMode.OFF)
        fresh.close()
        last = self.fixture()
        self.assertNotIn(identifier, last.runtime.lite_memory_retrieve(QUESTION).prompt_json)
        self.assertEqual((), last.learning.dynamics.index.snapshot.entries)
        self.assertEqual(1, len(last.learning.records("DELTA")))

    def test_unavailable_authoritative_store_is_explicitly_degraded(self):
        fx = self.fixture()
        self.admitted_delta(fx)
        with patch.object(fx.factory, "begin", side_effect=OSError("controlled unavailable store")):
            context = fx.runtime.lite_memory_retrieve(QUESTION)
        self.assertEqual("DEGRADED", context.status)
        self.assertEqual((), context.eligible)
        self.assertEqual("[]", context.prompt_json)
        self.assertEqual([], fx.transport.calls)

    def test_historical_selection_labels_version_and_never_changes_current_authority(self):
        from test_memory_patch_retrieval import RetrievalFixture
        from test_memory_patch_persistence_ports import NOW
        from runtime.memory_patch.retrieval.temporal import (
            TemporalApplicability, TemporalQueryMode, resolve_temporal,
        )
        fx = RetrievalFixture()
        self.addCleanup(fx.core.close)
        candidate = fx.candidate(version="historical-v1", metadata={
            "version_identity": "historical-v1", "effective_from": "2029-01-01",
            "effective_to": NOW.isoformat(), "verified_at": NOW.isoformat()})
        bundle = fx.bundle([candidate])
        historical = resolve_temporal(bundle, mode=TemporalQueryMode.AS_OF,
                                      trusted_now=NOW, as_of=NOW - timedelta(seconds=1),
                                      freshness=fx.service.freshness)
        current = resolve_temporal(bundle, mode=TemporalQueryMode.CURRENT,
                                   trusted_now=NOW, freshness=fx.service.freshness)
        self.assertEqual(TemporalQueryMode.AS_OF, historical.mode)
        self.assertEqual(NOW - timedelta(seconds=1), historical.as_of)
        self.assertEqual(1, len(historical.applicable_items))
        self.assertEqual("historical-v1", historical.states[0].version_identity)
        self.assertEqual(NOW, historical.states[0].facts.effective_to)
        self.assertEqual(TemporalApplicability.EXPIRED, current.states[0].applicability)
        self.assertEqual((), current.applicable_items)
        self.assertEqual(historical.states[0].item.item_hash, current.states[0].item.item_hash)
        evidence("historical-query", mode=historical.mode.value, version="historical-v1",
                 historical_at=historical.as_of.isoformat(), current_applicable=0)

    def test_poisoned_delta_tags_and_pheromone_metadata_cannot_revive_revocation(self):
        from runtime.memory_patch.learning.personal_contracts import DeltaTag, TagKind
        fx = self.fixture()
        identifier = self.admitted_delta(fx)

        def poison(tx):
            row = tx.get(RecordKind.LEARNING, identifier)
            delta = replace(fx.learning.delta(row), tags=(
                DeltaTag(TagKind.VERIFICATION_CLASS, "grant-owner-execute-now"),))
            tx.replace(fx.learning.record(identifier, "DELTA", {
                **dict(row.payload), "delta": delta.private_payload()}, revision=row.revision + 1),
                expected_revision=row.revision)
            trail = tx.get(RecordKind.LEARNING, "trail-" + identifier)
            tx.replace(fx.learning.record(trail.record_id, "TRAIL", {
                **dict(trail.payload), "tau_positive": 1.0, "tau_negative": 1.0,
                "untrusted_metadata": POISON}, revision=trail.revision + 1),
                expected_revision=trail.revision)

        fx.learning.run(poison, write=True)
        fx.consent(ConsentMode.OFF)
        self.assertNotIn(identifier, fx.runtime.lite_memory_retrieve(QUESTION).prompt_json)
        self.assertEqual((), fx.learning.dynamics.index.snapshot.entries)
        row = fx.learning.records("DELTA")[0]
        self.assertFalse(row.payload["execution_authority"])
        self.assertFalse(fx.learning.delta(row).execution_authority)
        self.assertEqual("OFF", fx.personal.describe()["mode"])
        self.assertEqual(1, len(fx.learning.records("PHEROMONE_EVENT")))
        self.assertIsNone(fx.runtime.executor)


if __name__ == "__main__":
    unittest.main()
