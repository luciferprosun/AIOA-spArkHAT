"""C5-09/10: exact vector oracle, independent ANN and private temporal lanes."""

from __future__ import annotations

import hashlib
import math
import unittest
from datetime import datetime, timedelta, timezone

from support.certification_manifest import inputs, make_core, memory_fixture

from runtime.core_admission import Capability
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.memory_patch.retrieval.embeddings import (
    load_approved_model_spec,
    normalize_embedding_vector,
)
from runtime.memory_patch.retrieval.temporal import (
    TemporalApplicability,
    TemporalQueryMode,
    resolve_temporal,
)


class VectorTemporalTests(unittest.TestCase):
    def setUp(self):
        self.cfg = inputs()
        self.core = make_core()
        self.factory = self.cfg.factory(self.core)
        self.addCleanup(self.factory.close)
        self.spec = load_approved_model_spec()

    def begin(self, cap=Capability.READ, *, core=None, factory=None):
        core = core or self.core
        factory = factory or self.factory
        return factory.begin(
            TransactionContext(core.local_operator(cap), cap), attempt=1
        )

    def parents(self, connection, scope, chunk, hat_id="test-hat"):
        content = "Reviewed deterministic fixture " + chunk
        digest = hashlib.sha256(content.encode()).hexdigest()
        b = scope.binding()
        source = "source-" + chunk
        connection.execute(
            "INSERT INTO aioa_memory_patch.source_lineage VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (*b, source, "v1", digest, "{}"),
        )
        connection.execute(
            "INSERT INTO aioa_memory_patch.source_publications VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                *b,
                source,
                "v1",
                digest,
                "PUBLISHED",
                True,
                "core-fixture-proof",
                datetime(2020, 1, 1, tzinfo=timezone.utc),
                None,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                [],
                None,
            ),
        )
        connection.execute(
            "INSERT INTO aioa_memory_patch.parsed_chunks VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (*b, chunk, source, "v1", digest, content, digest),
        )
        connection.execute(
            "INSERT INTO aioa_memory_patch.source_hat_links VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (*b, source, "v1", hat_id, "2" * 64),
        )

    def insert_vector(
        self, c, scope, chunk, vector, *, model=None, digest=None, hat_id="test-hat"
    ):
        literal = (
            vector
            if isinstance(vector, str)
            else "[" + ",".join(repr(value) for value in vector.values) + "]"
        )
        return c.execute(
            "INSERT INTO aioa_memory_patch.chunk_vectors VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::VECTOR(384))",
            (
                *scope.binding(),
                chunk,
                "source-" + chunk,
                "v1",
                hat_id,
                self.spec.model_id,
                self.spec.model_revision,
                model or self.spec.model_digest,
                digest
                or (vector.bytes_sha256 if not isinstance(vector, str) else "3" * 64),
                literal,
            ),
        )

    def seed(self, core, factory, values, *, hat_id="test-hat"):
        tx = self.begin(Capability.EVIDENCE_CAPTURE, core=core, factory=factory)
        try:
            for chunk, vector in values:
                self.parents(tx._lease.connection, tx._context.scope, chunk, hat_id)
                self.insert_vector(
                    tx._lease.connection,
                    tx._context.scope,
                    chunk,
                    vector,
                    hat_id=hat_id,
                )
            tx.commit()
        finally:
            tx.close()

    def test_09_dimension_nonfinite_model_and_byte_identity(self):
        valid = normalize_embedding_vector([1] + [0] * 383)
        bad = (
            ("[1,0]", "dimension"),
            ("[NaN," + ",".join(["0"] * 383) + "]", "nan"),
            ("[Infinity," + ",".join(["0"] * 383) + "]", "infinity"),
            (valid, "wrong-model"),
        )
        rows = []
        for vector, case in bad:
            tx = self.begin(Capability.EVIDENCE_CAPTURE)
            c = tx._lease.connection
            chunk = "invalid-" + case
            try:
                self.parents(c, tx._context.scope, chunk)
                try:
                    self.insert_vector(
                        c,
                        tx._context.scope,
                        chunk,
                        vector,
                        model="0" * 64 if case == "wrong-model" else None,
                    )
                except Exception as error:
                    self.assertIn(
                        getattr(error, "sqlstate", None),
                        {"22000", "22023", "22P02", "23514"},
                    )
                    rows.append(
                        {"case": case, "sqlstate": error.sqlstate, "STATUS": "DENIED"}
                    )
                else:
                    self.fail("Invalid vector admitted")
            finally:
                tx.rollback()
                tx.close()
        self.seed(self.core, self.factory, [("valid-384", valid)])
        tx = self.begin()
        try:
            self.assertEqual(
                tx.vectors.search(
                    valid, hat_id="test-hat", model_digest=self.spec.model_digest
                )[0][0],
                "valid-384",
            )
        finally:
            tx.rollback()
            tx.close()
        # A syntactically valid but false byte hash is detected by native reads.
        tx = self.begin(Capability.EVIDENCE_CAPTURE)
        try:
            self.parents(tx._lease.connection, tx._context.scope, "tampered-bytes")
            self.insert_vector(
                tx._lease.connection,
                tx._context.scope,
                "tampered-bytes",
                valid,
                digest="0" * 64,
            )
            tx.commit()
        finally:
            tx.close()
        tx = self.begin()
        try:
            with self.assertRaises(MemoryPatchError):
                tx.vectors.search(
                    valid, hat_id="test-hat", model_digest=self.spec.model_digest
                )
        finally:
            tx.rollback()
            tx.close()
        self.cfg.save(
            "C5_VECTOR_STORAGE.json",
            {
                "STATUS": "PASS",
                "dimension": 384,
                "negative_storage_cases": rows,
                "byte_identity_checked_by_native_read": True,
            },
        )

    def test_09_exact_top_k_stable_ties_scope(self):
        query = normalize_embedding_vector([1] + [0] * 383)
        close = normalize_embedding_vector([0.9, 0.1] + [0] * 382)
        far = normalize_embedding_vector([0, 1] + [0] * 382)
        values = (("tie-a", close), ("tie-b", close), ("far", far))
        self.seed(self.core, self.factory, values)
        scope = self.core.local_operator(Capability.READ).scope
        for tenant, owner in (
            (scope.tenant_id, "another-owner"),
            ("another-tenant", scope.owner_id),
        ):
            foreign = make_core(tenant=tenant, owner=owner, space=scope.space_id)
            factory = self.cfg.factory(foreign)
            try:
                self.seed(foreign, factory, [("unauthorized-best", query)])
            finally:
                factory.close()
        foreign_hat = make_core(
            tenant=scope.tenant_id,
            owner=scope.owner_id,
            space=scope.space_id,
            hat_ids={"private-hat"},
        )
        factory = self.cfg.factory(foreign_hat)
        try:
            self.seed(
                foreign_hat,
                factory,
                [("unauthorized-hat-best", query)],
                hat_id="private-hat",
            )
        finally:
            factory.close()
        self.seed(self.core, self.factory, [("revoked-best", query)])
        with self.cfg.connect("root") as admin:
            admin.execute(
                "UPDATE aioa_memory_patch.source_publications SET source_status='WITHDRAWN' WHERE tenant_id=%s AND owner_id=%s AND space_id=%s AND slot_id=%s AND source_id='source-revoked-best'",
                scope.binding(),
            )
        tx = self.begin()
        try:
            exact = tx.vectors.search(
                query, hat_id="test-hat", model_digest=self.spec.model_digest, limit=2
            )
            expected = sorted(
                (
                    (
                        chunk,
                        math.sqrt(
                            math.fsum(
                                (a - b) ** 2
                                for a, b in zip(
                                    query.values, vector.values, strict=True
                                )
                            )
                        ),
                    )
                    for chunk, vector in values
                ),
                key=lambda row: (row[1], row[0]),
            )[:2]
            self.assertEqual([row[0] for row in exact], [row[0] for row in expected])
            for actual, wanted in zip(exact, expected, strict=True):
                self.assertAlmostEqual(actual[4], wanted[1], places=6)
            for kwargs in (
                {"hat_id": "unapproved", "model_digest": self.spec.model_digest},
                {"hat_id": "test-hat", "model_digest": "0" * 64},
            ):
                with self.assertRaises(MemoryPatchError):
                    tx.vectors.search(query, **kwargs)
        finally:
            tx.rollback()
            tx.close()
        self.cfg.save(
            "C5_VECTOR_RETRIEVAL_EXACT.json",
            {
                "STATUS": "PASS",
                "exact_top_k": [
                    {"fixture_id": row[0], "distance": row[4]} for row in exact
                ],
                "tie_order": "chunk_id",
                "unauthorized_higher_score_rows_returned": 0,
                "scope_filter_before_ranking": True,
                "unauthorized_categories": ["tenant", "owner", "hat"],
                "revoked_source_returned": False,
            },
        )

    def test_09_required_application_ann_scope_and_quality(self):
        # This required criterion remains a failing test until a scoped ANN
        # implementation passes. It is never converted to a skip or admin test.
        query = normalize_embedding_vector([1] + [0] * 383)
        close = normalize_embedding_vector([0.9, 0.1] + [0] * 382)
        values = (("ann-a", query), ("ann-b", close))
        self.seed(self.core, self.factory, values)
        scope = self.core.local_operator(Capability.READ).scope
        foreign = make_core(
            tenant="foreign-ann-tenant", owner=scope.owner_id, space=scope.space_id
        )
        factory = self.cfg.factory(foreign)
        try:
            self.seed(foreign, factory, [("foreign-ann-best", query)])
        finally:
            factory.close()
        tx = self.begin()
        try:
            try:
                ann = tx.vectors.search(
                    query,
                    hat_id="test-hat",
                    model_digest=self.spec.model_digest,
                    limit=2,
                    approximate=True,
                )
            except MemoryPatchError as error:
                self.cfg.save(
                    "C5_VECTOR_ANN_REQUIRED_CRITERION.json",
                    {
                        "STATUS": "FAIL",
                        "contract_id": "C5-09",
                        "code": error.code.value,
                        "reason": "Pinned v26.2.5 rejected ANN with required request-context RLS (42809); ordinary ANN remains unverified and disabled.",
                        "RLS_weakened": False,
                        "admin_substitution": False,
                        "exact_fallback_presented_as_ANN": False,
                        "required_recall": 0.8,
                        "actual_recall": None,
                        "reference": "https://docs.cockroachlabs.com/docs/v26.2/vector-indexes",
                    },
                )
                self.fail(
                    "C5-09 required application ANN is not certified; C5 must remain FAIL"
                )
            self.assertTrue(
                set(row[0] for row in ann) <= {chunk for chunk, _ in values}
            )
            recall = len(
                {row[0] for row in ann} & {chunk for chunk, _ in values}
            ) / len(values)
            self.assertGreaterEqual(recall, 0.8)
        finally:
            tx.rollback()
            tx.close()

    def test_10_sql_personal_temporal_revocation_supersession_and_conflict(self):
        from test_memory_patch_persistence_ports import NOW

        fixture = memory_fixture()
        self.addCleanup(fixture.close)
        admissions = fixture.rf.catalog.admissions
        active = fixture.activate(
            fixture.draft(
                valid_from=NOW - timedelta(days=1), valid_until=NOW + timedelta(hours=1)
            )
        )
        self.assertEqual([value.patch_id for value in fixture.retrieve()], [active])
        self.assertFalse(fixture.retrieve()[0].canonical_evidence)
        self.assertFalse(fixture.retrieve()[0].execution_authority)
        conflict = fixture.rf.candidate(content="The reviewed policy not applies.")
        conflict_bundle = fixture.rf.bundle([conflict])
        self.assertEqual(fixture.retrieve(conflict_bundle), ())
        fixture.now = NOW + timedelta(hours=2)
        self.assertEqual(fixture.retrieve(fixture.bundle), ())
        # Client-supplied historical time cannot revive current expired memory.
        self.assertEqual(
            fixture.retrieval.retrieve(
                fixture.p(Capability.READ),
                hat_id="test-hat",
                at=NOW,
                canonical_bundle=fixture.bundle,
            ),
            (),
        )
        fixture.now = NOW
        fixture.management.revoke(
            fixture.p(Capability.MANAGE),
            active,
            expected_revision=8,
            operation_key="revoke",
        )
        self.assertEqual(fixture.retrieve(fixture.bundle), ())
        self.assertEqual(fixture.rf.catalog.admissions, admissions + 1)
        other = memory_fixture()
        self.addCleanup(other.close)
        old = other.activate()
        new = other.activate(other.draft(supersedes_patch_id=old), key="replacement")
        other.management.supersede(
            other.p(Capability.MANAGE),
            old,
            new,
            expected_revision=8,
            operation_key="supersede",
        )
        self.assertEqual([value.patch_id for value in other.retrieve()], [new])
        self.assertEqual(len(other.rows(RecordKind.PATCH)), 2)
        # Canonical temporal resolution is Core-owned; SQL personal records
        # remain in the separate private lane at all query times.
        candidate = fixture.rf.candidate(
            metadata={
                "effective_from": "2029-01-01",
                "effective_to": NOW.isoformat(),
                "verified_at": NOW.isoformat(),
            }
        )
        bundle = fixture.rf.bundle([candidate])
        freshness = fixture.rf.service.freshness
        current = resolve_temporal(
            bundle,
            mode=TemporalQueryMode.CURRENT,
            trusted_now=NOW,
            as_of=None,
            freshness=freshness,
        )
        historical = resolve_temporal(
            bundle,
            mode=TemporalQueryMode.AS_OF,
            trusted_now=NOW,
            as_of=NOW - timedelta(seconds=1),
            freshness=freshness,
        )
        future_candidate = fixture.rf.candidate(
            metadata={"effective_from": "2031-01-01", "verified_at": NOW.isoformat()}
        )
        future_bundle = fixture.rf.bundle([future_candidate])
        future = resolve_temporal(
            future_bundle,
            mode=TemporalQueryMode.FUTURE,
            trusted_now=NOW,
            as_of=NOW + timedelta(days=366),
            freshness=freshness,
        )
        self.assertIs(current.states[0].applicability, TemporalApplicability.EXPIRED)
        self.assertIs(
            historical.states[0].applicability, TemporalApplicability.APPLICABLE
        )
        self.assertIs(future.states[0].applicability, TemporalApplicability.APPLICABLE)
        self.cfg.save(
            "C5_TEMPORAL_AUTHORITY.json",
            {
                "STATUS": "PASS",
                "current_expired": True,
                "historical_canonical": True,
                "future_canonical": True,
                "client_time_cannot_revive_private_memory": True,
                "revoked_suppressed": True,
                "superseded_suppressed": True,
                "canonical_conflict_suppressed": True,
                "personal_memory_promotions": 0,
            },
        )
