from __future__ import annotations

import hashlib
import itertools
import math
import unittest
from dataclasses import fields, replace
from datetime import timedelta

from test_memory_patch_evidence_promotion import FakeCoreEvidenceCatalog, source_spec
from test_memory_patch_persistence_ports import NOW, make_admission

from runtime.core_admission import AdmissionError, Capability
from runtime.evidence_admission import CoreEvidenceAdmission, EvidenceAdmissionError
from runtime.memory_patch.contracts.enums import MemoryTargetScope
from runtime.memory_patch.contracts.records import (
    RRF_SCALE,
    EvidenceBundleItem,
    HybridModality,
    Step20BoundaryError,
    canonical_sha256,
)
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.retrieval.contracts import (
    HybridRetrievalRequest,
    RetrievalCandidate,
    RetrievalMode,
    VectorRetrievalCandidate,
)
from runtime.memory_patch.retrieval.embeddings import (
    EmbeddingBoundaryError,
    EmbeddingVector,
    NativeEmbeddingCache,
    ScopedVector,
    VectorCacheIdentity,
    exact_l2,
    exact_top_k,
    load_approved_model_spec,
    normalize_embedding_vector,
    vector_from_float32_bytes,
)
from runtime.memory_patch.retrieval.ranking import (
    RankedCandidateInput,
    assemble_budgeted_items,
    merge_and_rank_candidates,
    select_diverse_candidates,
    utf8_safe_prefix,
)
from runtime.memory_patch.retrieval.service import NativeRetrieval
from runtime.memory_patch.retrieval.temporal import (
    FreshnessPolicy,
    FreshnessStatus,
    SupersessionStatus,
    TemporalApplicability,
    TemporalQueryMode,
    resolve_temporal,
)
from runtime.memory_patch.source_lineage import (
    SourceAccessClass,
    SourceAuthorityLevel,
    SourcePublicationState,
)


class FakeAuthorizedSources:
    """Reviewed registry double, independent from a returned ranking result."""

    def __init__(self):
        self.values = ()
        self.reviewed = {}
        self.calls = []

    @staticmethod
    def key(value):
        identity = value.identity if isinstance(value, EvidenceBundleItem) else value
        return identity.source_id, identity.knowledge_version_id, identity.chunk_id

    def approve(self, value):
        key = self.key(value)
        self.reviewed[key] = value

    def candidates(self, principal, request):
        self.calls.append(request.scope)
        return self.values

    def require_binding(self, principal, value, evidence_id):
        approved = self.reviewed.get(self.key(value))
        if (
            approved is None
            or approved.scope != principal.scope
            or approved.core_evidence_id != evidence_id
        ):
            raise MemoryPatchError(
                __import__(
                    "runtime.memory_patch.errors", fromlist=["ErrorCode"]
                ).ErrorCode.EVIDENCE_DENIED
            )
        for name in (
            "authority_level",
            "authority_basis",
            "source_kind",
            "source_reference",
            "publication_state",
            "access_class",
            "target_scope",
            "owner_user_id",
            "personal_memory_space_id",
            "scope_digest",
            "registry_digest",
            "artifact_digest",
            "snapshot_id",
            "structured_metadata",
            "effective_scope",
        ):
            if getattr(approved, name) != getattr(value, name):
                raise EvidenceAdmissionError()


class RetrievalFixture:
    def __init__(self):
        self.core = make_admission()
        self.reader = self.core.local_operator(Capability.READ)
        self.capture_actor = self.core.local_operator(Capability.EVIDENCE_CAPTURE)
        self.catalog = FakeCoreEvidenceCatalog()
        self.evidence = CoreEvidenceAdmission(
            self.core, self.catalog, clock=lambda: NOW
        )
        self.request = HybridRetrievalRequest.admitted(
            self.core, self.reader, hat_id="test-hat", query="reviewed rule"
        )
        self.sources = FakeAuthorizedSources()
        self.service = NativeRetrieval(
            self.core,
            self.evidence,
            self.sources,
            freshness=FreshnessPolicy("test-reviewed-policy", "1", {"law": 86400}),
            clock=lambda: NOW,
        )
        self.source_counter = 0

    def candidate(
        self,
        *,
        source_id=None,
        chunk_id="chunk-one",
        content="Article 1: The reviewed rule applies.",
        metadata=None,
        mode=RetrievalMode.FULL_TEXT,
        ordinal=1,
        version=None,
    ):
        self.source_counter += 1
        source_id = source_id or f"source-{self.source_counter}"
        version = version or source_id + "-version"
        digest = hashlib.sha256(content.encode()).hexdigest()
        spec, _ = source_spec(
            source_id=source_id,
            source_version_id=version,
            source_fingerprint=digest,
            artifact_fingerprint=digest,
        )
        intent = self.evidence.approve_capture(self.capture_actor, spec)
        capture = self.evidence.capture(
            self.capture_actor,
            intent,
            source_bytes=content.encode(),
            artifact_bytes=content.encode(),
        )
        metadata = (
            metadata
            if metadata is not None
            else {"effective_from": "2020-01-01", "verified_at": NOW.isoformat()}
        )
        candidate = RetrievalCandidate(
            scope=self.reader.scope,
            core_evidence_id=capture.evidence_id,
            tenant_id=self.reader.scope.tenant_id,
            hat_scope_id="test-hat",
            source_id=source_id,
            knowledge_version_id=version,
            chunk_id=chunk_id,
            chunk_ordinal=ordinal,
            content_sha256=digest,
            content=content,
            language_tag="en",
            authority_level=SourceAuthorityLevel.OFFICIAL_PRIMARY,
            authority_basis={"review": "fixture-reviewed"},
            source_kind="law",
            source_reference="reviewed-fixture",
            publication_state=SourcePublicationState.PUBLISHED,
            access_class=SourceAccessClass.USER_PRIVATE,
            target_scope=MemoryTargetScope.USER_PERSONAL_HAT,
            owner_user_id=self.reader.scope.owner_id,
            personal_memory_space_id=self.reader.scope.space_id,
            scope_digest=canonical_sha256(self.request.effective_scope),
            registry_digest="1" * 64,
            artifact_digest=digest,
            snapshot_id=source_id + "-snapshot",
            structured_metadata=metadata,
            effective_scope=self.request.effective_scope,
            retrieval_mode=mode,
            retrieval_score="1",
        )
        self.sources.approve(candidate)
        return candidate

    def ranked_input(self, candidate, *, rank=1, modality=None):
        modality = modality or HybridModality(candidate.retrieval_mode.value)
        return RankedCandidateInput(
            modality, self.request.request_hash, "2" * 64, rank, candidate
        )

    def bundle(self, candidates):
        self.sources.values = tuple(
            self.ranked_input(c, rank=i + 1) for i, c in enumerate(candidates)
        )
        return self.service.retrieve(self.reader, self.request).canonical_evidence


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.fx = RetrievalFixture()

    def test_fixed_integer_fusion_dedup_and_permutation_stability(self):
        a = self.fx.candidate(source_id="source-a", mode=RetrievalMode.KEYWORD)
        b = self.fx.candidate(source_id="source-b", mode=RetrievalMode.EXACT_IDENTIFIER)
        a_text = replace(a, retrieval_mode=RetrievalMode.FULL_TEXT)
        values = (
            self.fx.ranked_input(a, rank=1),
            self.fx.ranked_input(a_text, rank=2),
            self.fx.ranked_input(b, rank=4),
        )
        outputs = [
            merge_and_rank_candidates(self.fx.request, p)
            for p in itertools.permutations(values)
        ]
        self.assertTrue(all(x == outputs[0] for x in outputs))
        self.assertEqual(
            ["source-b", "source-a"], [v.identity.source_id for v in outputs[0]]
        )
        a_result = outputs[0][1]
        self.assertEqual(2, a_result.modality_count)
        self.assertEqual(
            RRF_SCALE * 2 // 61 + RRF_SCALE * 4 // 62, a_result.fused_score
        )
        self.assertEqual(
            outputs[0],
            merge_and_rank_candidates(self.fx.request, values + (values[0],)),
        )

    def test_duplicate_identity_conflicting_metadata_or_rank_is_denied(self):
        a = self.fx.candidate()
        for changed in (
            replace(a, structured_metadata={"effective_from": "2001-01-01"}),
            a,
        ):
            with (
                self.subTest(changed=changed is a),
                self.assertRaises(Step20BoundaryError),
            ):
                merge_and_rank_candidates(
                    self.fx.request,
                    (self.fx.ranked_input(a), self.fx.ranked_input(changed, rank=2)),
                )

    def test_diversity_source_and_version_caps_and_stable_round_robin(self):
        candidates = []
        for source in ("source-a", "source-b", "source-c"):
            for i in range(5):
                candidates.append(
                    self.fx.candidate(
                        source_id=source, chunk_id=f"chunk-{i}", ordinal=i + 1
                    )
                )
        inputs = tuple(
            self.fx.ranked_input(c, rank=i + 1) for i, c in enumerate(candidates)
        )
        ranked = merge_and_rank_candidates(self.fx.request, inputs)
        result = select_diverse_candidates(ranked)
        self.assertEqual(9, len(result.selected))
        self.assertEqual(
            ["source-a", "source-b", "source-c"] * 3,
            [c.identity.source_id for c in result.selected],
        )
        self.assertTrue(result.truncated)
        exact = tuple(
            self.fx.ranked_input(
                replace(c, retrieval_mode=RetrievalMode.EXACT_IDENTIFIER), rank=i + 1
            )
            for i, c in enumerate(candidates)
        )
        exact_result = select_diverse_candidates(
            merge_and_rank_candidates(self.fx.request, exact)
        )
        # Reviewed source diversity.py applies its eight-position priority window
        # before the source cap: 3 of the first 5 from A, then 3 from B.
        self.assertEqual(
            ["source-a"] * 3 + ["source-b"] * 3,
            [c.identity.source_id for c in exact_result.selected],
        )
        self.assertEqual(7, exact_result.excluded_counts["DIVERSITY_EXACT_CAP"])

    def test_utf8_budget_minimum_and_excerpt_hash(self):
        c = self.fx.candidate(content="é" * 1000)
        ranked = merge_and_rank_candidates(self.fx.request, (self.fx.ranked_input(c),))
        result = assemble_budgeted_items(ranked, context_budget_bytes=257)
        self.assertEqual(256, result.context_bytes_used)
        self.assertEqual("é" * 128, result.items[0].excerpt.text)
        self.assertTrue(result.truncated)
        self.assertEqual(
            hashlib.sha256(("é" * 128).encode()).hexdigest(),
            result.items[0].excerpt.excerpt_sha256,
        )
        self.assertEqual(
            (), assemble_budgeted_items(ranked, context_budget_bytes=255).items
        )
        self.assertEqual("a", utf8_safe_prefix("a😀b", 4))

    def test_scope_is_checked_before_ranking_and_core_evidence_required(self):
        c = self.fx.candidate()
        self.fx.sources.values = (self.fx.ranked_input(c),)
        result = self.fx.service.retrieve(self.fx.reader, self.fx.request)
        self.assertEqual(1, len(result.canonical_evidence.items))
        self.assertEqual((), result.personal_context)
        self.assertEqual([self.fx.reader.scope], self.fx.sources.calls)
        self.fx.catalog.receipts.clear()
        with self.assertRaises(EvidenceAdmissionError):
            self.fx.service.retrieve(self.fx.reader, self.fx.request)
        foreign = make_admission(owner="another-owner")
        with self.assertRaises(AdmissionError):
            self.fx.service.retrieve(
                foreign.local_operator(Capability.READ), self.fx.request
            )

    def test_unreviewed_metadata_cannot_become_temporal_authority(self):
        c = self.fx.candidate()
        forged = replace(
            c,
            structured_metadata={
                "effective_from": "1900-01-01",
                "verified_at": NOW.isoformat(),
            },
        )
        self.fx.sources.values = (self.fx.ranked_input(forged),)
        with self.assertRaises(EvidenceAdmissionError):
            self.fx.service.retrieve(self.fx.reader, self.fx.request)

    def test_unconfigured_source_port_denies_without_side_effects(self):
        with self.assertRaises(MemoryPatchError):
            NativeRetrieval(self.fx.core, self.fx.evidence).retrieve(
                self.fx.reader, self.fx.request
            )


class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.fx = RetrievalFixture()

    def resolve(self, metadata, *, mode=TemporalQueryMode.CURRENT, as_of=None):
        c = self.fx.candidate(metadata=metadata)
        bundle = self.fx.bundle([c])
        return resolve_temporal(
            bundle,
            mode=mode,
            trusted_now=NOW,
            as_of=as_of,
            freshness=self.fx.service.freshness,
        )

    def test_exclusive_end_and_current_historical_future(self):
        metadata = {
            "effective_from": "2029-01-01",
            "effective_to": "2030-01-02T12:00:00Z",
            "verified_at": NOW.isoformat(),
        }
        self.assertEqual(
            TemporalApplicability.EXPIRED,
            self.resolve(metadata).states[0].applicability,
        )
        old = self.resolve(
            metadata, mode=TemporalQueryMode.AS_OF, as_of=NOW - timedelta(seconds=1)
        )
        self.assertEqual(TemporalApplicability.APPLICABLE, old.states[0].applicability)
        future = {"effective_from": "2031-01-01", "verified_at": NOW.isoformat()}
        self.assertEqual(
            TemporalApplicability.NOT_YET_APPLICABLE,
            self.resolve(future).states[0].applicability,
        )
        self.assertEqual(
            TemporalApplicability.APPLICABLE,
            self.resolve(
                future, mode=TemporalQueryMode.FUTURE, as_of=NOW + timedelta(days=366)
            )
            .states[0]
            .applicability,
        )
        with self.assertRaises(MemoryPatchError):
            self.resolve(future, mode=TemporalQueryMode.FUTURE, as_of=NOW)

    def test_staleness_unknown_missing_future_observation_never_silently_pass(self):
        for observed, expected in (
            (NOW - timedelta(days=2), FreshnessStatus.STALE),
            (None, FreshnessStatus.UNKNOWN),
            (NOW + timedelta(seconds=1), FreshnessStatus.UNKNOWN),
        ):
            with self.subTest(expected=expected):
                metadata = {"effective_from": "2020-01-01"}
                if observed:
                    metadata["verified_at"] = observed.isoformat()
                result = self.resolve(metadata)
                self.assertEqual(expected, result.states[0].freshness_status)
                self.assertEqual((), result.applicable_items)
                self.assertTrue(result.review_required)
        result = self.resolve({"verified_at": NOW.isoformat()})
        self.assertEqual(TemporalApplicability.UNKNOWN, result.states[0].applicability)
        unspecified = self.resolve(
            {"effective_from": "2020-01-01", "verified_at": NOW.isoformat()},
            mode=TemporalQueryMode.UNSPECIFIED,
        )
        self.assertEqual((), unspecified.applicable_items)

    def test_material_conflict_and_explicit_supersession_and_cycle(self):
        common = {
            "effective_from": "2020-01-01",
            "verified_at": NOW.isoformat(),
            "document_identity": "doc-one",
            "provision_identifier": "section-one",
        }
        a = self.fx.candidate(
            source_id="source-old",
            content="An older rule.",
            metadata={**common, "version_identity": "version-old"},
        )
        b = self.fx.candidate(
            source_id="source-new",
            content="A different rule.",
            metadata={**common, "version_identity": "version-new"},
        )
        bundle = self.fx.bundle([a, b])
        result = resolve_temporal(
            bundle,
            mode=TemporalQueryMode.CURRENT,
            trusted_now=NOW,
            freshness=self.fx.service.freshness,
        )
        self.assertTrue(result.conflicts)
        self.assertEqual((), result.applicable_items)
        for cyclic in (False, True):
            a = replace(
                a,
                structured_metadata={
                    **common,
                    "version_identity": "version-old",
                    "superseded_by": ["version-new"],
                },
            )
            b = replace(
                b,
                structured_metadata={
                    **common,
                    "version_identity": "version-new",
                    **({"superseded_by": ["version-old"]} if cyclic else {}),
                },
            )
            self.fx.sources.approve(a)
            self.fx.sources.approve(b)
            bundle = self.fx.bundle([a, b])
            result = resolve_temporal(
                bundle,
                mode=TemporalQueryMode.CURRENT,
                trusted_now=NOW,
                freshness=self.fx.service.freshness,
            )
            if cyclic:
                self.assertTrue(
                    all(
                        s.supersession_status is SupersessionStatus.CYCLIC
                        for s in result.states
                    )
                )
                self.assertEqual((), result.applicable_items)
            else:
                self.assertEqual(1, len(result.applicable_items))
                self.assertEqual(
                    "source-new", result.applicable_items[0].identity.source_id
                )


class VectorTests(unittest.TestCase):
    def test_vector_candidate_model_and_modality_are_bound(self):
        fx = RetrievalFixture()
        text = fx.candidate()
        values = {
            f.name: getattr(text, f.name)
            for f in fields(text)
            if f.init and f.name not in {"retrieval_mode", "retrieval_score"}
        }
        vector = VectorRetrievalCandidate(
            **values,
            model_digest=load_approved_model_spec().model_digest,
            embedding_bytes_sha256="0" * 64,
            vector_distance="0.5",
        )
        result = merge_and_rank_candidates(
            fx.request,
            (
                fx.ranked_input(text),
                fx.ranked_input(vector, modality=HybridModality.VECTOR),
            ),
        )
        self.assertEqual(1, len(result))
        self.assertEqual(2, result[0].modality_count)
        with self.assertRaises(MemoryPatchError):
            replace(vector, model_digest="1" * 64)
        with self.assertRaises(Step20BoundaryError):
            merge_and_rank_candidates(
                fx.request, (fx.ranked_input(text, modality=HybridModality.VECTOR),)
            )

    def test_384_float32_identity_exact_l2_and_invalid_values(self):
        a = EmbeddingVector((1.0,) + (0.0,) * 383)
        b = EmbeddingVector((0.0, 1.0) + (0.0,) * 382)
        self.assertEqual(1536, len(a.float32_bytes))
        self.assertEqual(a, vector_from_float32_bytes(a.float32_bytes))
        self.assertEqual(math.sqrt(2), exact_l2(a, b))
        self.assertEqual(a, normalize_embedding_vector((2.0,) + (0.0,) * 383))
        for values in (
            (0.0,) * 384,
            (1.0,) * 383,
            (True,) + (0.0,) * 383,
            (float("nan"),) + (0.0,) * 383,
            (float("inf"),) + (0.0,) * 383,
        ):
            with (
                self.subTest(length=len(values)),
                self.assertRaises(EmbeddingBoundaryError),
            ):
                EmbeddingVector(values)
        self.assertEqual(
            "aa68fc625f243f0e9c5f97aa9a7d3b7963c7dfdd10ca645d0782f3d8e8c77070",
            load_approved_model_spec().model_digest,
        )

    def test_exact_top_k_scope_before_limits_and_stable_tie(self):
        core = make_admission()
        p = core.local_operator(Capability.READ)
        other = make_admission(owner="another-owner").local_operator(Capability.READ)
        a = EmbeddingVector((1.0,) + (0.0,) * 383)
        b = EmbeddingVector((0.0, 1.0) + (0.0,) * 382)
        model = load_approved_model_spec().model_digest
        rows = (
            ScopedVector("z", p.scope, "test-hat", model, b),
            ScopedVector("a", p.scope, "test-hat", model, b),
            ScopedVector("hidden", other.scope, "test-hat", model, a),
        )
        self.assertEqual(
            ("a", math.sqrt(2)),
            exact_top_k(core, p, a, rows, hat_id="test-hat", limit=1)[0],
        )
        with self.assertRaises(MemoryPatchError):
            exact_top_k(
                core,
                p,
                a,
                (replace(rows[0], model_digest="0" * 64),),
                hat_id="test-hat",
            )

    def test_cache_is_explicit_and_owner_bound(self):
        core = make_admission()
        reader = core.local_operator(Capability.READ)
        identity = VectorCacheIdentity(
            reader.scope,
            "test-hat",
            load_approved_model_spec().model_digest,
            "0" * 64,
            "QUERY",
        )
        cache = NativeEmbeddingCache(core)
        with self.assertRaises(MemoryPatchError):
            cache.read(reader, identity)

        class Port:
            def get(self, identity):
                return b"invalid derived cache bytes"

        cache = NativeEmbeddingCache(core, Port())
        with self.assertRaises(EmbeddingBoundaryError):
            cache.read(reader, identity)
        self.assertNotEqual(
            identity.identity_digest,
            replace(identity, input_kind="PASSAGE").identity_digest,
        )


class SQLVectorCapabilityTests(unittest.TestCase):
    """Capability requests cannot turn a denied ANN operation into exact SQL."""

    def setUp(self):
        from unittest.mock import MagicMock

        from runtime.memory_patch.adapters.cockroach.repositories import (
            ScopedVectorRepository,
        )
        from runtime.memory_patch.persistence.ports import TransactionContext

        self.core = make_admission()
        self.principal = self.core.local_operator(Capability.READ)
        self.context = TransactionContext(self.principal, Capability.READ)
        self.connection = MagicMock()
        self.connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        self.repository = ScopedVectorRepository(
            self.connection,
            self.context,
            lambda: self.core.require(self.principal, Capability.READ),
        )
        self.query = normalize_embedding_vector([1] + [0] * 383)
        self.arguments = {
            "hat_id": "test-hat",
            "model_digest": load_approved_model_spec().model_digest,
        }
        self.addCleanup(self.core.close)

    def test_descriptor_is_immutable_truthful_and_does_not_query(self):
        from dataclasses import FrozenInstanceError

        profile = self.repository.capabilities()
        self.assertEqual(profile.default_mode, "EXACT")
        self.assertTrue(profile.exact)
        self.assertEqual(profile.ann.value, "UNAVAILABLE_SECURELY_ON_CRDB_26_2_5")
        self.assertEqual(
            profile.descriptor()["ann_required_failure_code"], "ANN_UNAVAILABLE"
        )
        with self.assertRaises(FrozenInstanceError):
            profile.default_mode = "ANN"
        self.connection.cursor.assert_not_called()

    def test_ann_required_and_legacy_approximate_fail_before_query(self):
        from runtime.memory_patch.errors import ErrorCode
        from runtime.memory_patch.views import error_view

        for options in (
            {"ann_required": True},
            {"approximate": True},
            {"ann_required": True, "approximate": True},
        ):
            for method in (self.repository.search, self.repository.search_with_status):
                with self.assertRaises(MemoryPatchError) as caught:
                    method(self.query, **self.arguments, **options)
                self.assertIs(caught.exception.code, ErrorCode.ANN_UNAVAILABLE)
                public = error_view(caught.exception)
                self.assertEqual(public["code"], "ANN_UNAVAILABLE")
                self.assertFalse(public["retryable"])
                self.assertFalse(public["recovery_required"])
        self.connection.cursor.assert_not_called()

    def test_exact_status_cannot_claim_ann_or_disclose_private_hits(self):
        from dataclasses import FrozenInstanceError

        result = self.repository.search_with_status(self.query, **self.arguments)
        self.assertEqual(result.hits, ())
        self.assertEqual(
            result.metadata(),
            {"mode": "EXACT", "ann_capability": "UNAVAILABLE_SECURELY_ON_CRDB_26_2_5"},
        )
        self.connection.cursor.assert_called_once()
        with self.assertRaises(FrozenInstanceError):
            result.mode = "ANN"
        self.assertNotIn("hits", result.metadata())
        self.assertEqual(
            self.repository.search(self.query, **self.arguments), result.hits
        )

    def test_nonboolean_mode_requests_are_not_coerced(self):
        from runtime.memory_patch.errors import ErrorCode

        for field in ("ann_required", "approximate"):
            for value in (0, 1, "false", "true", None, [], {}):
                with self.assertRaises(MemoryPatchError) as caught:
                    self.repository.search(
                        self.query, **self.arguments, **{field: value}
                    )
                self.assertIs(caught.exception.code, ErrorCode.INVALID_REQUEST)
        self.connection.cursor.assert_not_called()

    def test_scope_model_and_input_validation_precede_unavailable_capability(self):
        from runtime.memory_patch.errors import ErrorCode

        for arguments in (
            {**self.arguments, "hat_id": "other-hat"},
            {**self.arguments, "model_digest": "0" * 64},
            {**self.arguments, "limit": True},
        ):
            with self.assertRaises(MemoryPatchError) as caught:
                self.repository.search(self.query, ann_required=True, **arguments)
            self.assertIs(caught.exception.code, ErrorCode.INVALID_REQUEST)
        self.connection.cursor.assert_not_called()

    def test_closed_authority_denies_descriptor_and_both_search_paths(self):
        self.core.close()
        for action in (
            self.repository.capabilities,
            lambda: self.repository.search(self.query, **self.arguments),
            lambda: self.repository.search_with_status(
                self.query, ann_required=True, **self.arguments
            ),
        ):
            with self.assertRaises(AdmissionError):
                action()
        self.connection.cursor.assert_not_called()
