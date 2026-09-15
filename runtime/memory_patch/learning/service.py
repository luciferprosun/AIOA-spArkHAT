"""Native transactional advisory deltas; no owner approval or action promotion."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.enums import (
    ActorType,
    CorrectionCandidateState,
    ModelExperienceOutcome,
)
from runtime.memory_patch.contracts.records import (
    ClaimCandidate,
    CorrectionCandidate,
    ModelExperienceEvent,
)
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.learning.contracts import (
    CoreVerifierBinding,
    DeltaStatus,
    EpistemicDelta,
    LearningPolicy,
    PrivacyScope,
    VerificationInput,
    VerificationVerdict,
    VerifierReceipt,
)
from runtime.memory_patch.lite import ContextReference
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
)
from runtime.mission.advisory import CorrectionDeltaLink, _claim
from runtime.mission.contracts import MissionError, MissionTrace


class NativeLearning:
    """Owned by the composed MemoryPatchService and using its transaction runner.

    SHADOW performs all checks but writes no delta. ACTIVE requires an explicit
    host binding and the existing Core MANAGE capability. All records remain
    private advisory references, outside canonical evidence/approval lanes.
    """

    def __init__(self, memory, policy, verifiers, *, active):
        if (
            type(policy) is not LearningPolicy
            or type(verifiers) is not tuple
            or type(active) is not bool
        ):
            raise MissionError("INVALID_LEARNING_BINDINGS")
        if any(type(v) is not CoreVerifierBinding for v in verifiers):
            raise MissionError("INVALID_LEARNING_BINDINGS")
        if tuple(sorted(v.verifier_ref for v in verifiers)) != policy.verifier_refs:
            raise MissionError("VERIFIER_REGISTRY_MISMATCH")
        if len({v.verifier_ref for v in verifiers}) != len(verifiers):
            raise MissionError("VERIFIER_REGISTRY_MISMATCH")
        self.memory, self.native, self.policy = memory, memory.service, policy
        self.verifiers, self.active = verifiers, active
        reader = self.native.core.local_operator(Capability.READ)
        self.native.core.require(reader, Capability.READ, scope=policy.owner_scope)
        if (
            policy.domain_hat != memory.profile.hat_id
            or policy.domain_hat not in reader.hat_ids
        ):
            raise MissionError("LEARNING_SCOPE_MISMATCH")
        if active:
            if (
                memory.profile.memory_mode != "ACTIVE"
                or memory.profile.write_policy_ref != "native-owner-explicit-v1"
            ):
                raise MissionError("LEARNING_WRITE_POLICY_REQUIRED")
            self.native.core.local_operator(Capability.MANAGE)
        self.last = None
        self.dynamics = None

    def now(self):
        return self.native.retrieval.clock()

    def _context(self, write=False):
        cap = Capability.MANAGE if write else Capability.READ
        if write and not self.active:
            raise MissionError("SHADOW_NO_KNOWLEDGE_WRITE")
        principal = self.native.core.local_operator(cap)
        self.native.core.require(principal, cap, scope=self.policy.owner_scope)
        return TransactionContext(principal, cap)

    def run(self, callback, *, write=False):
        return self.native.transactions.run(self._context(write), callback)

    def records(self, state):
        def read(tx):
            rows = tx.scan(
                RecordKind.LEARNING,
                limit=self.policy.maximum_records + 1,
                states=(state,),
            )
            if len(rows) > self.policy.maximum_records:
                raise MissionError("LEARNING_READ_BUDGET")
            for row in rows:
                self.validate_record(row)
            return rows

        return self.run(read)

    def validate_record(self, row):
        row.verify()
        if (
            row.scope != self.policy.owner_scope
            or row.payload.get("domain_hat") != self.policy.domain_hat
            or row.payload.get("privacy_scope") != "PRIVATE"
            or row.payload.get("execution_authority") is not False
            or row.payload.get("publication_authority") is not False
        ):
            raise MissionError("LEARNING_SCOPE_OR_AUTHORITY_DENIED")

    def record(self, identifier, state, payload, *, revision=1):
        return StoredRecord(
            RecordKind.LEARNING,
            identifier,
            self.policy.owner_scope,
            revision,
            {
                **payload,
                "state": state,
                "domain_hat": self.policy.domain_hat,
                "privacy_scope": "PRIVATE",
                "execution_authority": False,
                "publication_authority": False,
            },
        )

    def _check_quota(self, tx, additional):
        rows = tx.scan(RecordKind.LEARNING, limit=self.policy.maximum_records + 1)
        if len(rows) + additional > self.policy.maximum_records:
            raise MissionError("LEARNING_STORAGE_BUDGET")

    def _sources(self, eligible, bundle):
        reader = self.native.core.local_operator(Capability.READ)
        self.native.retrieval.require_bundle(reader, bundle)
        sources = []
        for item in eligible:
            if item.lane != "CANONICAL_EVIDENCE":
                continue
            source, version = item.source_versions[0]
            if source in self.policy.source_ids:
                evidence = self.native.evidence.require_evidence(
                    reader, item.evidence_refs[0]
                )
                if evidence.source.source_version_id != version:
                    raise MissionError("SOURCE_VERSION_MISMATCH")
                sources.append((source, version, item.evidence_refs[0], item.text))
        if (
            tuple(sorted(s[0] for s in sources)) != self.policy.source_ids
            or sum(len(s[3].encode()) for s in sources) > 8192
        ):
            raise MissionError("CURRENT_AUTHORITATIVE_EVIDENCE_REQUIRED")
        return tuple(sorted(sources))

    def verify(self, claim, sources):
        request = VerificationInput(
            self.policy.owner_scope,
            self.policy.domain_hat,
            self.policy.task_signature,
            _claim(claim),
            sources,
            self.now(),
        )
        receipts = []
        for binding in self.verifiers:
            verdict = binding.verifier.verify(request)
            if (
                type(verdict) is not VerificationVerdict
                or verdict.input_digest != request.digest
            ):
                raise MissionError("INVALID_VERIFIER_RESULT")
            receipts.append(
                VerifierReceipt(
                    binding.verifier_ref,
                    binding.verifier_method,
                    binding.source_family,
                    request.digest,
                    verdict.supported,
                )
            )
        # All required deterministic methods must support; at least two source
        # families and methods. CPL opinions are never added to this proof set.
        supported = all(r.supported for r in receipts)
        independent = (
            len({r.source_family for r in receipts}) >= 2
            and len({r.verifier_method for r in receipts}) >= 2
        )
        return supported and independent, tuple(receipts)

    def delta(self, row):
        self.validate_record(row)
        value = EpistemicDelta.restore(row.payload["delta"])
        if (
            value.scope != row.scope
            or value.delta_id != row.record_id
            or value.domain_hat != self.policy.domain_hat
            or value.privacy_scope is not PrivacyScope.PRIVATE
        ):
            raise MissionError("DELTA_BINDING_MISMATCH")
        return value

    def eligible_deltas(self, eligible, bundle):
        try:
            sources = self._sources(eligible, bundle)
        except Exception:
            return ()
        versions = tuple((r[0], r[1]) for r in sources)
        refs = tuple(sorted(r[2] for r in sources))
        result = []
        for row in self.records("DELTA"):
            value = self.delta(row)
            if (
                value.status is not DeltaStatus.VERIFIED
                or value.task_signature != self.policy.task_signature
                or value.source_versions != versions
                or tuple(sorted(value.evidence_refs)) != refs
                or not value.valid_from <= self.now() < value.valid_until
                or value.policy_digest != self.policy.knowledge_digest
            ):
                continue
            verified, _ = self.verify(value.verified_claim, sources)
            if verified:
                result.append((row, value))
        return tuple(result)

    def context(self, eligible, bundle, query):
        values = self.eligible_deltas(eligible, bundle)
        if self.dynamics is not None:
            values = self.dynamics.before_context(values, eligible, bundle, query)
        return tuple(
            ContextReference(
                value.delta_id,
                "VERIFIED_DELTA_ADVISORY",
                value.verified_claim,
                value.evidence_refs,
                value.source_versions,
                row.revision,
                value.valid_from.isoformat(),
                value.valid_until.isoformat(),
            )
            for row, value in values
        )

    def _candidate(self, original, corrected, trace_id, cpl_ref, refs):
        trace = MissionTrace(
            trace_id,
            self.policy.task_signature,
            trace_id,
            trace_id,
            self.policy.actor.fingerprint,
            1,
            evidence_refs=tuple(sorted(refs)),
        )
        candidate = CorrectionCandidate(
            trace_id,
            self.policy.owner_scope.tenant_id,
            self.policy.owner_scope.owner_id,
            self.policy.owner_scope.space_id,
            ActorType.CRITIC_PROMPT_LOOP,
            trace_id,
            trace.model_profile_ref,
            cpl_ref,
            (ClaimCandidate("atomic-claim", cpl_ref, original, "factual"),),
            corrected,
            trace.evidence_refs,
            0.5,
            self.now(),
            CorrectionCandidateState.PROPOSED,
        )
        link = CorrectionDeltaLink(
            candidate, self.policy.owner_scope, trace, "current-source-set"
        )
        if link.audit_decision()["status"] != "CANDIDATE_ONLY":
            raise MissionError("NO_CHANGE")
        return candidate

    def evaluate(self, original, revision, *, trace_id, cpl_ref, critic_families):
        original, revision = _claim(original), _claim(revision)
        # Recheck native eligibility after CPL latency, using the trusted clock.
        context = self.memory.retrieve(self.policy.task_instruction)
        if context.status != "READY":
            raise MissionError("MEMORY_DEGRADED")
        sources = self._sources(context.eligible, context.canonical_bundle)
        actor_valid, _ = self.verify(original, sources)
        revision_valid, receipts = self.verify(revision, sources)
        common = {
            "execution_authority": False,
            "critic_independent_proofs": 0,
            "critic_source_families": sorted(set(critic_families)),
            "task_signature": self.policy.task_signature,
            "cpl_trace_ref": cpl_ref,
        }
        if actor_valid:
            result = {
                **common,
                "status": "ZERO_WRITE",
                "knowledge_write": "ZERO_WRITE",
                "reason": "ACTOR_ALREADY_VERIFIED",
                "delta_id": None,
                "revision_supported": revision_valid,
            }
            if self.dynamics is not None and self.active:
                self.dynamics.successful_reuse(original, trace_id, context)
            self.last = result
            return result
        if original == revision or not revision_valid:
            self.last = {
                **common,
                "status": "CONTESTED",
                "knowledge_write": "ZERO_WRITE",
                "reason": "INDEPENDENT_VERIFICATION_NOT_MET",
                "delta_id": None,
            }
            return self.last
        refs = tuple(sorted(row[2] for row in sources))
        versions = tuple((row[0], row[1]) for row in sources)
        candidate = self._candidate(original, revision, trace_id, cpl_ref, refs)
        # Identity excludes model: overlays reference this one canonical delta.
        identifier = canonical_sha256(
            {
                "scope": self.policy.owner_scope,
                "hat": self.policy.domain_hat,
                "task": self.policy.task_signature,
                "old": original,
                "new": revision,
                "versions": versions,
            }
        )
        now = self.now()
        delta = EpistemicDelta(
            identifier,
            self.policy.owner_scope,
            self.policy.domain_hat,
            self.policy.actor,
            self.policy.task_signature,
            original,
            revision,
            (original, revision),
            "FACTUAL",
            refs,
            versions,
            receipts,
            1.0,
            DeltaStatus.VERIFIED,
            PrivacyScope.PRIVATE,
            now,
            now + timedelta(seconds=self.policy.validity_seconds),
            (),
            now,
            now,
            None,
            candidate.content_hash,
            cpl_ref,
            self.policy.knowledge_digest,
        )
        if not self.active:
            self.last = {
                **common,
                "status": "SHADOW_VERIFIED",
                "knowledge_write": "ZERO_WRITE",
                "reason": "SHADOW_POLICY",
                "delta_id": identifier,
            }
            return self.last
        result = self.persist(delta, trace_id)
        if self.dynamics is not None:
            self.dynamics.correction(delta, trace_id)
        self.last = {**common, **result}
        return self.last

    def persist(self, delta, trace_id):
        overlay_id = "overlay-" + canonical_sha256(
            (self.policy.actor.fingerprint, delta.delta_id)
        )
        event_id = "episode-" + canonical_sha256((trace_id, delta.delta_id))
        experience = ModelExperienceEvent(
            trace_id,
            delta.scope.tenant_id,
            delta.scope.owner_id,
            delta.scope.space_id,
            self.policy.actor.provider,
            self.policy.actor.family,
            self.policy.actor.version,
            delta.error_type,
            trace_id,
            delta.task_signature,
            ModelExperienceOutcome.CORRECTED,
            "INDEPENDENT_METHODS_SUPPORTED",
            self.now(),
            delta.valid_until,
            "native-learning-v1",
        )

        def write(tx):
            previous = tx.get(RecordKind.LEARNING, delta.delta_id)
            event = tx.get(RecordKind.LEARNING, event_id)
            if event is not None:
                self.validate_record(event)
                return {
                    "status": "DUPLICATE",
                    "knowledge_write": "ZERO_WRITE",
                    "delta_id": delta.delta_id,
                }
            overlay = tx.get(RecordKind.LEARNING, overlay_id)
            self._check_quota(tx, 1 + int(previous is None) + int(overlay is None))
            if previous is None:
                tx.insert(
                    self.record(
                        delta.delta_id, "DELTA", {"delta": delta.private_payload()}
                    )
                )
            else:
                current = self.delta(previous)
                if (
                    current.original_claim,
                    current.verified_claim,
                    current.source_versions,
                ) != (
                    delta.original_claim,
                    delta.verified_claim,
                    delta.source_versions,
                ):
                    raise MissionError("DELTA_IDENTITY_CONFLICT")
                # Evidence revalidation does not revive deprecated/superseded records.
                if current.status is not DeltaStatus.VERIFIED:
                    raise MissionError("DELTA_REVALIDATION_REQUIRED")
                changed = replace(current, last_seen_at=self.now())
                tx.replace(
                    self.record(
                        current.delta_id,
                        "DELTA",
                        {"delta": changed.private_payload()},
                        revision=previous.revision + 1,
                    ),
                    expected_revision=previous.revision,
                )
            count = 1
            if overlay is not None:
                self.validate_record(overlay)
                count += overlay.payload["recurrence_count"]
            payload = {
                "delta_ref": delta.delta_id,
                "model": json.loads(canonical_json_bytes(self.policy.actor)),
                "failure_pattern": delta.error_type,
                "task_signature": delta.task_signature,
                "recurrence_count": min(1000000, count),
                "last_seen_at": self.now().isoformat(),
                "confidence": "INDEPENDENT_METHODS_SUPPORTED",
                "verification_status": "VERIFIED",
                "experience": json.loads(canonical_json_bytes(experience)),
                "pheromone_ref": None,
            }
            row = self.record(
                overlay_id,
                "OVERLAY",
                payload,
                revision=1 if overlay is None else overlay.revision + 1,
            )
            if overlay is None:
                tx.insert(row)
            else:
                tx.replace(row, expected_revision=overlay.revision)
            tx.insert(
                self.record(
                    event_id,
                    "EPISODE",
                    {
                        "delta_ref": delta.delta_id,
                        "trace_ref": trace_id,
                        "candidate_hash": delta.native_candidate_hash,
                        "created_at": self.now().isoformat(),
                    },
                )
            )
            return {
                "status": "VERIFIED" if previous is None else "DUPLICATE",
                "knowledge_write": "CREATED" if previous is None else "ZERO_WRITE",
                "delta_id": delta.delta_id,
                "overlay_id": overlay_id,
            }

        return self.run(write, write=True)
