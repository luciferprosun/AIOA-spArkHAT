"""Explicit local demo fixtures over existing native ports; never a LIVE backend.

One runtime, one memory engine. File transactions are owner scoped and private.
Synthetic source publication grants no claim about real world truth.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import asdict, replace
from datetime import datetime, timezone
import threading
from pathlib import Path
from types import SimpleNamespace

from main import create_runtime







from runtime.core_admission import (
    Capability,
    CoreAdmission,
    LocalOwnerAssignment,
    OwnerScope,
)
from runtime.evidence_admission import (
    CapturedEvidence,
    CoreEvidenceAdmission,
    InputOrigin,
    SourceCaptureSpec,
)
from runtime.memory_patch.adapters.cockroach.repositories import (
    canonical_record,
    restore_record,
)
from runtime.memory_patch.contract import MemoryPatchConfig
from runtime.memory_patch.contracts.enums import MemoryTargetScope
from runtime.memory_patch.contracts.records import (
    HybridModality,
    PersonalHatQuotaPolicy,
)
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.lite import CoreLiteMemoryBindings, LiteMemoryProfile
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.memory_patch.retrieval.contracts import (
    HybridRetrievalRequest,
    RetrievalCandidate,
    RetrievalMode,
    trusted_dimensions,
)
from runtime.memory_patch.retrieval.ranking import RankedCandidateInput
from runtime.memory_patch.retrieval.service import NativeRetrieval
from runtime.memory_patch.retrieval.temporal import FreshnessPolicy
from runtime.memory_patch.service import CoreMemoryPatchDependencies
from runtime.memory_patch.source_lineage import (
    SourceAccessClass,
    SourceAuthorityLevel,
    SourcePublicationState,
)
from runtime.mission.contracts import MissionContext
from runtime.mission.lite_contracts import LiteCadence, LiteProfile
MODEL = "nvidia/Nemotron-3_5-Lightning"
from runtime.mission.lite_runtime import FileObservationProbe, LiteBindings
from runtime.providers.nvidia import NvidiaProvider
from runtime.tools.provenance import AppendOnlyProvenanceStore
from runtime.memory_patch.errors import MemoryPatchError, ErrorCode, CommitOutcomeUnknown
from runtime.evidence_admission import EvidenceAdmissionError
from runtime.memory_patch.retrieval.contracts import EvidenceBundleItem
from runtime.memory_patch.contracts.records import HatManifest, HatSecurityPolicy
NOW = datetime(2030, 1, 2, 12, tzinfo=timezone.utc)



class StructuredFailure(Exception):
    def __init__(self, sqlstate):
        self.sqlstate = sqlstate
        super().__init__("synthetic database fault")

class FakeFactory:
    """A locked copy-on-write transaction, never an implicit runtime backend."""

    def __init__(self, *, state=None, commit_faults=()):
        self.state = {} if state is None else state
        self.commit_faults = list(commit_faults)
        self.contexts = []
        self.attempts = []
        self.lock = threading.RLock()
        self.opens = self.closes = self.commits = self.rollbacks = 0
        self.closed = False

    def begin(self, context, *, attempt):
        self.lock.acquire()
        self.opens += 1
        self.contexts.append(context)
        self.attempts.append(attempt)
        return FakeTransaction(self, context)

    def close(self):
        self.closed = True

class FakeTransaction:
    def __init__(self, factory, context):
        self.factory = factory
        self.context = context
        self.snapshot = factory.state.copy()
        self.closed = False

    def _key(self, kind, identity):
        return self.context.scope.binding(), kind, identity

    def get(self, kind, record_id):
        return self.snapshot.get(self._key(kind, record_id))

    def scan(self, kind, *, limit, states):
        records = [
            record
            for (scope, record_kind, _), record in self.snapshot.items()
            if scope == self.context.scope.binding()
            and record_kind is kind
            and (not states or record.payload.get("state") in states)
        ]
        return tuple(sorted(records, key=lambda item: item.record_id)[:limit])

    def insert(self, record):
        key = self._key(record.kind, record.record_id)
        if key in self.snapshot:
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        self.snapshot[key] = record

    def replace(self, record, *, expected_revision):
        key = self._key(record.kind, record.record_id)
        prior = self.snapshot.get(key)
        if prior is None or prior.revision != expected_revision:
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        self.snapshot[key] = record

    def commit(self):
        fault = (
            self.factory.commit_faults.pop(0) if self.factory.commit_faults else None
        )
        if fault == "40001":
            raise StructuredFailure(fault)
        if fault not in (None, "unknown_after_commit"):
            raise StructuredFailure(fault)
        self.factory.state.clear()
        self.factory.state.update(self.snapshot)
        self.factory.commits += 1
        if fault == "unknown_after_commit":
            raise CommitOutcomeUnknown()

    def rollback(self):
        self.factory.rollbacks += 1

    def close(self):
        if not self.closed:
            self.closed = True
            self.factory.closes += 1
            self.factory.lock.release()

class FakeCoreEvidenceCatalog:
    """Explicit Core catalog double with a separate publication receipt set."""

    def __init__(self):
        self.records = {}
        self.receipts = {}
        self.admissions = 0
        self.publish = True

    def admit(self, record):
        self.admissions += 1
        self.records[record.evidence_id] = record
        if self.publish:
            self.receipts[record.evidence_id] = record.record_digest
        return record

    def get(self, scope, evidence_id):
        record = self.records.get(evidence_id)
        return record if record is not None and record.scope == scope else None

    def require_published(self, record):
        if self.receipts.get(record.evidence_id) != record.record_digest:
            raise EvidenceAdmissionError()

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

def memory_hat_manifest():
    return HatManifest(
        "1.0.0",
        "test-hat",
        "1.0.0",
        "Reviewed fixture",
        ("fixture",),
        "1",
        ("en",),
        (),
        ("deterministic-retrieval",),
        {},
        {},
        {},
        {},
        {},
        HatSecurityPolicy(),
        {},
    )

def atomic_json(path, value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if path.exists() and path.read_bytes() == data:
        return
    temporary = path.with_name(path.name + ".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class DurableFactory(FakeFactory):
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    def begin(self, context, *, attempt):
        self.lock.acquire()
        lockfile = os.fdopen(os.open(self.path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), "a")
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            self.state.clear()
            if self.path.exists():
                if self.path.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError("FIXTURE_STATE_LIMIT")
                rows = json.loads(self.path.read_text())
                if type(rows) is not list or len(rows) > 4096:
                    raise ValueError("FIXTURE_STATE_LIMIT")
                for raw, digest in rows:
                    data = json.loads(raw)
                    scope = OwnerScope(**data["scope"])
                    record = restore_record(
                        raw, digest, kind=RecordKind(data["kind"]), scope=scope
                    )
                    self.state[(scope.binding(), record.kind, record.record_id)] = (
                        record
                    )
            self.opens += 1
            self.contexts.append(context)
            self.attempts.append(attempt)
            return DurableTransaction(self, context, lockfile)
        except BaseException:
            lockfile.close()
            self.lock.release()
            raise


class DurableTransaction(FakeTransaction):
    def __init__(self, factory, context, lockfile):
        super().__init__(factory, context)
        self.lockfile = lockfile

    def commit(self):
        rows = [
            [canonical_record(r), r.payload_digest]
            for _, r in sorted(self.snapshot.items())
        ]
        atomic_json(self.factory.path, rows)
        self.factory.state.clear()
        self.factory.state.update(self.snapshot)
        self.factory.commits += 1

    def close(self):
        if not self.closed:
            self.lockfile.close()
        super().close()


class Sources(FakeAuthorizedSources):
    def scan_scope(self, principal, *, hat_id, limit):
        self.calls.append((principal.scope, "UNRANKED", limit))
        values = [
            r
            for _, r in sorted(self.reviewed.items())
            if r.scope == principal.scope and r.hat_scope_id == hat_id
        ]
        return tuple(values[:limit])

    def candidates(self, principal, request):
        return tuple(
            RankedCandidateInput(
                HybridModality.KEYWORD, request.request_hash, "2" * 64, n + 1, value
            )
            for n, value in enumerate(
                self.scan_scope(principal, hat_id=request.hat_scope_id, limit=40)
            )
        )


class PrivateFixtureMemory:
    def __init__(
        self,
        root,
        *,
        runtime_builder,
        mode="ACTIVE",
        initialize=True,
        profile_changes=None,
        scope=None,
        revision=1,
        transport=None,
        hat_id="test-hat",
        factory_builder=None,
        backend_id="repository-durable-test",
    ):
        self.root = Path(root)
        self.hat_id = hat_id
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.now = NOW
        self.scope = scope or OwnerScope(
            "nv03-tenant", "nv03-owner", "nv03-space", "nv03-slot"
        )
        assignment = LocalOwnerAssignment(
            self.scope,
            frozenset(Capability),
            frozenset({self.hat_id}),
            frozenset({MODEL}),
            operator_approved=True,
        )
        self.core = CoreAdmission(assignment, clock=lambda: self.now)
        self.catalog = FakeCoreEvidenceCatalog()
        self.evidence = CoreEvidenceAdmission(
            self.core, self.catalog, clock=lambda: self.now
        )
        self.sources = Sources()
        self.metadata = {}
        self.freshness = FreshnessPolicy("nv03-freshness", "1", {"law": 86400})
        corpus = self.root / "corpus.json"
        if corpus.exists():
            for row in json.loads(corpus.read_text()):
                source = row["source"]
                source["origin"] = InputOrigin(source["origin"])
                source["transform_fingerprints"] = tuple(
                    source["transform_fingerprints"]
                )
                record = CapturedEvidence(
                    row["id"],
                    OwnerScope(**row["scope"]),
                    SourceCaptureSpec(**source),
                    row["text"].encode(),
                    row["text"].encode(),
                    datetime.fromisoformat(row["at"]),
                    row["intent"],
                    row["digest"],
                    row["withdrawn"],
                )
                self.catalog.records[record.evidence_id] = record
                self.catalog.receipts[record.evidence_id] = row["receipt"]
                self.metadata[record.evidence_id] = row["metadata"]
                self._source(record)
        else:
            self.add_source("policy", "v1", "The reviewed policy applies.")
        self.factory = (
            factory_builder(self.core)
            if factory_builder is not None
            else DurableFactory(self.root / "memory.json")
        )
        (self.root / "provenance").mkdir(mode=0o700, exist_ok=True)
        self.store = AppendOnlyProvenanceStore(self.root, clock=lambda: self.now)
        fixture = self

        class Resolver:
            def resolve(self, principal, references):
                chosen = Sources()
                for value in fixture.sources.reviewed.values():
                    if value.core_evidence_id in references:
                        chosen.approve(value)
                reader = fixture.core.local_operator(Capability.READ)
                request = HybridRetrievalRequest.admitted(
                    fixture.core, reader, hat_id=fixture.hat_id, query="reviewed policy"
                )
                service = NativeRetrieval(
                    fixture.core,
                    fixture.evidence,
                    chosen,
                    freshness=fixture.freshness,
                    clock=lambda: fixture.now,
                )
                return service.retrieve(
                    reader, request, include_personal=False
                ).canonical_evidence

        self.dependencies = CoreMemoryPatchDependencies(
            transaction_factory=self.factory,
            evidence_catalog=self.catalog,
            sources=self.sources,
            bundle_resolver=Resolver(),
            provenance_store=self.store,
            hat_manifests=(replace(memory_hat_manifest(), hat_id=self.hat_id),),
            quota=PersonalHatQuotaPolicy(
                maximum_total_spaces=1,
                maximum_active_spaces=1,
                maximum_active_memory_patches=32,
                maximum_bytes=262144,
                maximum_personal_sources=32,
            ),
            freshness=self.freshness,
            clock=lambda: self.now,
        )
        self.memory_profile = LiteMemoryProfile(
            self.scope,
            self.hat_id,
            memory_mode=mode,
            backend_id=backend_id,
            freshness_policy_ref="nv03-freshness.1",
            write_policy_ref="native-owner-explicit-v1",
            **(profile_changes or {}),
        )
        self.memory_bindings = CoreLiteMemoryBindings(
            self.memory_profile,
            self.core,
            MemoryPatchConfig(True, assignment),
            self.dependencies,
            SimpleNamespace(active_hat=lambda: SimpleNamespace(name=self.hat_id)),
            backend_id=backend_id,
        )
        self.runtime = runtime_builder(self)
        storage_path = getattr(self.factory, "path", None)
        if initialize and mode == "ACTIVE" and (
            storage_path is None or not storage_path.exists()
        ):
            self.op("initialize-publication")
            self.op("slot-create", operation_key="create")
            self.op(
                "slot-configure",
                hat_id=self.hat_id,
                expected_revision=1,
                operation_key="configure",
            )
            self.op(
                "slot-state", state="ACTIVE", expected_revision=2, operation_key="state"
            )

    def _source(self, record):
        scope = record.scope
        dimensions = trusted_dimensions(scope, self.hat_id)
        value = RetrievalCandidate(
            scope=scope,
            core_evidence_id=record.evidence_id,
            tenant_id=scope.tenant_id,
            hat_scope_id=self.hat_id,
            source_id=record.source.source_id,
            knowledge_version_id=record.source.source_version_id,
            chunk_id="chunk-" + record.source.source_version_id,
            chunk_ordinal=1,
            content_sha256=record.source.artifact_fingerprint,
            content=record.artifact_bytes.decode(),
            language_tag="en",
            authority_level=SourceAuthorityLevel.OFFICIAL_PRIMARY,
            authority_basis={"review": "synthetic-fixture"},
            source_kind="law",
            source_reference="reviewed-fixture",
            publication_state=SourcePublicationState.PUBLISHED,
            access_class=SourceAccessClass.USER_PRIVATE,
            target_scope=MemoryTargetScope.USER_PERSONAL_HAT,
            owner_user_id=scope.owner_id,
            personal_memory_space_id=scope.space_id,
            scope_digest=canonical_sha256(dimensions),
            registry_digest="1" * 64,
            artifact_digest=record.source.artifact_fingerprint,
            snapshot_id="snapshot-" + record.source.source_version_id,
            structured_metadata=self.metadata[record.evidence_id],
            effective_scope=dimensions,
            retrieval_mode=RetrievalMode.KEYWORD,
        )
        self.sources.approve(value)
        return value

    def add_source(self, source_id, version, text, *, metadata=None):
        digest = hashlib.sha256(text.encode()).hexdigest()
        source = SourceCaptureSpec(
            source_id,
            version,
            digest,
            digest,
            (),
            InputOrigin.SOURCE_BYTES,
            "MIT",
            True,
            False,
            self.hat_id,
        )
        principal = self.core.local_operator(Capability.EVIDENCE_CAPTURE)
        intent = self.evidence.approve_capture(principal, source)
        record = self.evidence.capture(
            principal, intent, source_bytes=text.encode(), artifact_bytes=text.encode()
        )
        self.metadata[record.evidence_id] = metadata or {
            "effective_from": "2020-01-01",
            "verified_at": self.now.isoformat(),
        }
        value = self._source(record)
        self.save_corpus()
        return value

    def save_corpus(self):
        rows = []
        for key, r in sorted(self.catalog.records.items()):
            rows.append(
                {
                    "id": key,
                    "scope": asdict(r.scope),
                    "source": asdict(r.source),
                    "text": r.artifact_bytes.decode(),
                    "at": r.captured_at.isoformat(),
                    "intent": r.capture_intent_id,
                    "digest": r.record_digest,
                    "withdrawn": r.withdrawn,
                    "receipt": self.catalog.receipts.get(key),
                    "metadata": self.metadata[key],
                }
            )
        atomic_json(self.root / "corpus.json", rows)

    def op(self, operation, **payload):
        status, result = self.runtime.lite_memory_operator_request(operation, payload)
        if status >= 400:
            raise ValueError("FIXTURE_MEMORY_" + str(result.get("error", "UNAVAILABLE")))
        return result.get("result", result)

    def raw_patch(self, patch_id):
        return self.runtime._lite_memory.service.lifecycle.read(
            self.core.local_operator(Capability.READ), patch_id
        )

    def activate(
        self,
        *,
        text="The reviewed policy applies.",
        key="memory",
        content_kind="FACTUAL",
    ):
        references = [
            r.evidence_id
            for r in self.catalog.records.values()
            if r.scope == self.scope
        ]
        patch = self.op(
            "candidate",
            title="Verified fixture",
            summary="Small owner-scoped record.",
            body=text,
            content_kind=content_kind,
            hat_id=self.hat_id,
            operation_key=key + "-candidate",
            evidence_references=references,
            valid_from="2030-01-02T12:00:00.000000Z",
            valid_until="2030-01-03T12:00:00.000000Z",
        )
        identifier = patch["patch_id"]
        for operation in ("propose", "bind-evidence", "validate", "await-approval"):
            self.op(
                operation,
                patch_id=identifier,
                expected_revision=self.raw_patch(identifier).revision,
                operation_key=key + "-" + operation,
            )
        revision = self.raw_patch(identifier).revision
        challenge = self.op(
            "challenge",
            patch_id=identifier,
            expected_revision=revision,
            operation_key=key + "-challenge",
        )
        self.op(
            "decision",
            challenge_id=challenge["challenge_id"],
            expected_revision=revision,
            decision="APPROVE",
            decision_nonce=challenge["decision_nonce"],
            operation_key=key + "-decision",
        )
        self.op(
            "commit",
            patch_id=identifier,
            expected_revision=6,
            operation_key=key + "-commit",
        )
        self.op(
            "activate",
            patch_id=identifier,
            expected_revision=7,
            operation_key=key + "-activate",
        )
        return identifier

    def observe(self, value, *, health="OK"):
        self.observation_path.write_text(
            json.dumps({"value": value, "health": health, "source_revision": "v1"})
        )

    def close(self):
        self.runtime.close()
        self.factory.close()
        self.core.close()
