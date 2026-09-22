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
from runtime.memory_patch.learning.personal import (
    PersonalDeltaAccess,
    _ObservedConsentExpiry,
)
from runtime.memory_patch.learning.personal_contracts import (
    CorrectionMode,
    SemanticDeltaKind,
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

    def __init__(self, memory, policy, verifiers, *, active, personal_policy=None):
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
        self.personal = (
            None
            if personal_policy is None
            else PersonalDeltaAccess(self, personal_policy)
        )

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
        def guarded(tx):
            if write and self.personal is not None:
                self.personal.require_write(tx)
            result = callback(tx)
            if write and self.personal is not None:
                rows = tx.scan(
                    RecordKind.LEARNING, limit=self.policy.maximum_records + 1
                )
                maximum = self.personal.policy.maximum_learning_bytes
                native_quota = self.native.dependencies.quota
                if native_quota is not None and native_quota.maximum_bytes is not None:
                    maximum = min(maximum, native_quota.maximum_bytes)
                if (
                    len(rows) > self.policy.maximum_records
                    or sum(
                        len(
                            canonical_json_bytes(
                                row, exclude_fields=("payload_digest",)
                            )
                        )
                        for row in rows
                    )
                    > maximum
                ):
                    raise MissionError("PERSONAL_DELTA_BYTE_QUOTA")
            return result

        try:
            return self.native.transactions.run(self._context(write), guarded)
        except _ObservedConsentExpiry as error:
            # The rejected transaction has rolled back. Persist only the expiry
            # observation, so moving the clock backwards cannot revive consent.
            self.personal.record_expiry(error.row, error.observed_at)
            raise

    def records(self, state):
        def read(tx):
            rows = tx.scan(
                RecordKind.LEARNING,
                limit=self.policy.maximum_records + 1,
                states=(state,),
            )
            if len(rows) > self.policy.maximum_records:
                raise MissionError("LEARNING_READ_BUDGET")
            # One Core default personal space may hold several admitted HATs.
            # Adapter scoping precedes count/limit; domain filtering never expands it.
            rows = tuple(
                row
                for row in rows
                if row.payload.get("domain_hat") == self.policy.domain_hat
            )
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

    def eligible_deltas(self, eligible, bundle, *, rows=None):
        try:
            sources = self._sources(eligible, bundle)
        except Exception:
            return ()
        versions = tuple((r[0], r[1]) for r in sources)
        refs = tuple(sorted(r[2] for r in sources))
        result = []
        for row in self.records("DELTA") if rows is None else rows:
            value = self.delta(row)
            if (
                row.payload.get("reuse_status", "CURRENT") != "CURRENT"
                or value.status is not DeltaStatus.VERIFIED
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
        if self.personal is not None and not self.personal.allowed():
            if self.dynamics is not None:
                self.dynamics._current = {}
                self.dynamics._current_rows = {}
                self.dynamics.index.clear()
                self.dynamics.last = {
                    "status": "CONSENT_HIDDEN",
                    "index_mode": self.dynamics.policy.index_mode,
                    "index": self.dynamics.index.snapshot.metrics(),
                    "execution_authority": False,
                }
            return ()
        # Eligibility and invalidation must examine the same bounded snapshot.
        # A concurrent insertion absent from this read has not been rejected;
        # it is eligible for consideration on the next retrieval.
        rows = self.records("DELTA")
        values = self.eligible_deltas(eligible, bundle, rows=rows)
        if self.dynamics is not None:
            values = self.dynamics.before_context(
                values,
                eligible,
                bundle,
                query,
                rows=rows,
                write=self.personal is None or self.personal.allowed(write=True),
            )
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

    def evaluate(
        self, original, revision, *, trace_id, cpl_ref, critic_families, used_refs=()
    ):
        original, revision = _claim(original), _claim(revision)
        # Recheck native eligibility after CPL latency, using the trusted clock.
        context = self.memory.retrieve(self.policy.task_instruction)
        if context.status != "READY":
            raise MissionError("MEMORY_DEGRADED")
        sources = self._sources(context.eligible, context.canonical_bundle)
        if self.personal is not None:
            self.personal.require_clean(original, revision)
            original = self.personal.canonical_claim(original, sources)
            revision = self.personal.canonical_claim(revision, sources)
            self.personal.require_clean(original, revision)
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
            if (
                self.dynamics is not None
                and self.active
                and (self.personal is None or self.personal.allowed(write=True))
            ):
                self.dynamics.successful_reuse(original, trace_id, context, used_refs)
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
            delta_kind=SemanticDeltaKind.REPLACE
            if self.personal is None or self.personal.policy.semantics is None
            else self.personal.policy.semantics.delta_kind,
            required_condition=None
            if self.personal is None or self.personal.policy.semantics is None
            else self.personal.policy.semantics.required_condition,
            tags=()
            if self.personal is None or self.personal.policy.semantics is None
            else self.personal.policy.semantics.tags,
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
        if self.personal is not None and not self.personal.allowed(write=True):
            self.last = {
                **common,
                "status": "ZERO_WRITE",
                "knowledge_write": "ZERO_WRITE",
                "reason": self.run(lambda tx: self.personal.reason(tx, write=True)),
                "delta_id": None,
            }
            return self.last
        result = self.persist(delta, trace_id)
        if self.dynamics is not None:
            self.dynamics.correction(delta, trace_id)
        self.last = {**common, **result}
        return self.last

    def persist(self, delta, trace_id):
        proof_context = None
        source_snapshot = None
        if self.personal is not None:
            self.personal.require_clean(delta.private_payload())
            if (
                delta.scope != self.policy.owner_scope
                or delta.domain_hat != self.policy.domain_hat
                or delta.task_signature != self.policy.task_signature
                or delta.policy_digest != self.policy.knowledge_digest
                or delta.status is not DeltaStatus.VERIFIED
                or not delta.valid_from <= self.now() < delta.valid_until
            ):
                raise MissionError("DELTA_BINDING_MISMATCH")
            proof_context = self.memory.retrieve(self.policy.task_instruction)
            sources = self._sources(
                proof_context.eligible, proof_context.canonical_bundle
            )
            if (
                delta.source_versions != tuple((r[0], r[1]) for r in sources)
                or tuple(sorted(delta.evidence_refs))
                != tuple(sorted(r[2] for r in sources))
                or not self.verify(delta.verified_claim, sources)[0]
            ):
                raise MissionError("INDEPENDENT_VERIFICATION_REQUIRED")
            source_snapshot = self._source_snapshot()
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
            if proof_context is not None:
                # Sources are Core read ports, not nested native transactions.
                # Recheck the basis and clock inside the consent-guarded write.
                if (
                    source_snapshot != self._source_snapshot()
                    or not delta.valid_from <= self.now() < delta.valid_until
                ):
                    raise MissionError("SOURCE_CHANGED_BEFORE_WRITE")
                current_sources = self._sources(
                    proof_context.eligible, proof_context.canonical_bundle
                )
                if not self.verify(delta.verified_claim, current_sources)[0]:
                    raise MissionError("INDEPENDENT_VERIFICATION_REQUIRED")
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
                if (
                    current.status is not DeltaStatus.VERIFIED
                    or previous.payload.get("reuse_status", "CURRENT") != "CURRENT"
                    or current.policy_digest != delta.policy_digest
                ):
                    raise MissionError("DELTA_REVALIDATION_REQUIRED")
                changed = replace(current, last_seen_at=self.now())
                tx.replace(
                    self.record(
                        current.delta_id,
                        "DELTA",
                        {**dict(previous.payload), "delta": changed.private_payload()},
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

    def _source_snapshot(self):
        reader = self.native.core.local_operator(Capability.READ)
        return canonical_sha256(
            self.native.retrieval.sources.scan_scope(
                reader,
                hat_id=self.policy.domain_hat,
                limit=self.memory.profile.max_read_records + 1,
            )
        )

    def review_claim(self, original, mode, *, proposal=None):
        """Core review only; no actor call, no candidate may self-certify."""
        if type(mode) is not CorrectionMode:
            raise MissionError("INVALID_CORRECTION_MODE")
        context = self.memory.retrieve(self.policy.task_instruction)
        if context.status != "READY":
            raise MissionError("MEMORY_DEGRADED")
        sources = self._sources(context.eligible, context.canonical_bundle)
        original = _claim(original)
        if self.personal is not None:
            self.personal.require_clean(original)
            original = self.personal.canonical_claim(original, sources)
            self.personal.require_clean(original)
        actor_valid, actor_receipts = self.verify(original, sources)
        base = {
            "mode": mode.value,
            "original_claim": original,
            "context": context,
            "sources": sources,
            "actor_receipts": actor_receipts,
            "execution_authority": False,
        }
        if actor_valid:
            return {
                **base,
                "status": "ZERO_WRITE",
                "verified_claim": original,
                "receipts": actor_receipts,
            }
        if mode is CorrectionMode.HAT_ONLY:
            candidates = {r[3] for r in sources if self.verify(r[3], sources)[0]}
            if len(candidates) != 1:
                return {
                    **base,
                    "status": "UNVERIFIED",
                    "reason": "NO_UNIQUE_HAT_CORRECTION",
                }
            proposal = next(iter(candidates))
        elif proposal is None:
            return {
                **base,
                "status": "NEEDS_CRITICS",
                "reason": "CPL_PROPOSAL_REQUIRED",
            }
        proposal = _claim(proposal)
        if self.personal is not None:
            self.personal.require_clean(proposal)
            proposal = self.personal.canonical_claim(proposal, sources)
            self.personal.require_clean(proposal)
        valid, receipts = self.verify(proposal, sources)
        if not valid or proposal == original:
            return {
                **base,
                "status": "UNVERIFIED",
                "reason": "INDEPENDENT_VERIFICATION_NOT_MET",
            }
        return {
            **base,
            "status": "VERIFIED_CORRECTION",
            "verified_claim": proposal,
            "receipts": receipts,
        }

    def review_nachwg(self, answer):
        """Explicitly selected bounded domain; never routes on model keywords."""
        from runtime.memory_patch.learning.nachwg import assess
        return assess(self, answer)

    def correction_packet(self, review, trace_id):
        """Canonical native packet and a small actor projection, no HMAC export."""
        from runtime.memory_patch.correction.claims import (
            ClaimAtomicity,
            NativeDraft,
            classify_claim,
            exact_text_spans,
            extract_native_claims,
        )
        from runtime.memory_patch.correction.packets import (
            CorrectionAction,
            RequiredCorrection,
        )

        if self.native.integrity is None or review["status"] != "VERIFIED_CORRECTION":
            raise MissionError("VERIFIED_PACKET_BINDING_REQUIRED")
        # The caller's review dictionary does not constitute proof. Re-read it.
        fresh = self.review_claim(
            review["original_claim"],
            CorrectionMode.CPL_ONLY,
            proposal=review["verified_claim"],
        )
        if fresh["status"] != "VERIFIED_CORRECTION":
            raise MissionError("INDEPENDENT_VERIFICATION_REQUIRED")
        bundle = fresh["context"].canonical_bundle
        # Select only complete, exact excerpts from the selected HAT sources.
        # Never split, paraphrase or synthesize a correction from compound text.
        source_texts = {r[3] for r in fresh["sources"]}
        candidates = {}
        for item in bundle.items:
            text = item.excerpt.text
            if item.excerpt.truncated or text not in source_texts:
                continue
            spans = exact_text_spans(text)
            if (
                len(spans) == 1
                and spans[0].text == text
                and classify_claim(text)[1] is ClaimAtomicity.ATOMIC
                and self.verify(text, fresh["sources"])[0]
            ):
                candidates.setdefault(text, []).append(item.item_hash)
        if set(candidates) != {fresh["verified_claim"]}:
            raise MissionError("NO_UNIQUE_EXACT_ATOMIC_CORRECTION")
        draft = NativeDraft(
            self.policy.owner_scope,
            self.policy.domain_hat,
            trace_id,
            fresh["original_claim"],
        )
        claims = extract_native_claims(draft)
        if len(claims) != 1:
            raise MissionError("MINIMAL_SINGLE_CLAIM_REQUIRED")
        correction = RequiredCorrection(
            claims[0].claim_id,
            CorrectionAction.REPLACE,
            draft.text,
            fresh["verified_claim"],
            tuple(candidates[fresh["verified_claim"]]),
        )
        principal = self.native.core.local_operator(Capability.READ)
        packet, receipt = self.native.integrity.build_required(
            principal, draft, bundle, correction
        )
        semantics = None if self.personal is None else self.personal.policy.semantics
        condition = None if semantics is None else semantics.required_condition
        if condition is not None and condition not in fresh["verified_claim"]:
            raise MissionError("SEMANTIC_CONDITION_NOT_PRESERVED")
        payload = {
            "schema": "native-personal-correction-projection-v1",
            "packet_hash": packet.packet_hash,
            "claim_id": correction.claim_id,
            "original_claim": correction.original_text,
            "verified_correction": correction.required_text,
            "required_condition": condition,
            "delta_kind": "REPLACE"
            if semantics is None
            else semantics.delta_kind.value,
            "evidence_refs": [r[2] for r in fresh["sources"]],
            "source_versions": [[r[0], r[1]] for r in fresh["sources"]],
            "valid_from": packet.issued_at.isoformat(),
            "valid_until": packet.expires_at.isoformat(),
            "reason_code": "INDEPENDENT_CURRENT_EVIDENCE",
            "verification_status": "VERIFIED",
        }
        if self.personal is not None:
            self.personal.require_clean(payload)
        encoded = canonical_json_bytes(payload)
        if len(encoded) > 4096:
            raise MissionError("CORRECTION_PACKET_BUDGET")
        return packet, receipt, bundle, payload

    def storage_metrics(self):
        """Logical canonical bytes, not database pages or compression savings."""
        metrics = {
            "delta_bytes": 0,
            "reference_tag_bytes": 0,
            "audit_event_bytes": 0,
            "model_overlay_bytes": 0,
            "pheromone_event_bytes": 0,
        }
        for row in self.records("DELTA"):
            value = dict(row.payload["delta"])
            refs = {
                k: value[k]
                for k in ("evidence_refs", "source_versions", "tags")
                if k in value
            }
            reference_bytes = len(canonical_json_bytes(refs))
            metrics["reference_tag_bytes"] += reference_bytes
            metrics["delta_bytes"] += len(canonical_json_bytes(value)) - reference_bytes
        for state, key in (
            ("EPISODE", "audit_event_bytes"),
            ("OVERLAY", "model_overlay_bytes"),
            ("PHEROMONE_EVENT", "pheromone_event_bytes"),
        ):
            metrics[key] = sum(
                len(canonical_json_bytes(r, exclude_fields=("payload_digest",)))
                for r in self.records(state)
            )
        rows = self.run(
            lambda tx: tx.scan(
                RecordKind.LEARNING, limit=self.policy.maximum_records + 1
            )
        )
        if len(rows) > self.policy.maximum_records:
            raise MissionError("LEARNING_READ_BUDGET")
        rows = tuple(
            row
            for row in rows
            if row.payload.get("domain_hat") == self.policy.domain_hat
        )
        for row in rows:
            self.validate_record(row)
        durable_states = {
            "DELTA",
            "OVERLAY",
            "EPISODE",
            "TRAIL",
            "DEPENDENCY",
            "PHEROMONE_EVENT",
            "TIER_EVENT",
            "OBLIGATION",
            "REVALIDATION_EVENT",
        }
        audit_states = {
            "EPISODE",
            "PHEROMONE_EVENT",
            "TIER_EVENT",
            "OBLIGATION",
            "REVALIDATION_EVENT",
        }
        sizes = {
            row.record_id: len(
                canonical_json_bytes(row, exclude_fields=("payload_digest",))
            )
            for row in rows
        }
        accepted = sum(row.payload.get("state") == "DELTA" for row in rows)
        durable_bytes = sum(
            sizes[row.record_id]
            for row in rows
            if row.payload.get("state") in durable_states
        )
        audit_bytes = sum(
            sizes[row.record_id]
            for row in rows
            if row.payload.get("state") in audit_states
        )
        index_metrics = (
            {
                "mode": "UNCONFIGURED",
                "entry_count": 0,
                "index_bytes": 0,
                "bytes_per_entry": 0,
            }
            if self.dynamics is None
            else self.dynamics.index.snapshot.metrics()
        )
        return {
            **metrics,
            "accepted_minimal_delta_count": accepted,
            "durable_delta_and_adjacent_bytes": durable_bytes,
            "durable_bytes_per_accepted_minimal_delta": 0
            if not accepted
            else durable_bytes / accepted,
            "audit_provenance_bytes": audit_bytes,
            "compact_index": index_metrics,
            "measurement": "CANONICAL_SERIALIZED_LOGICAL_BYTES",
            "delta_partition": "delta_bytes + reference_tag_bytes equals complete serialized delta payload",
            "live_database_storage": False,
            "compression_savings_claimed": False,
        }
