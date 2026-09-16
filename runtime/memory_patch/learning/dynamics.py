"""Bounded advisory pheromones, reference tiers and native revalidation work."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from runtime.core_admission import Capability, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.learning.contracts import DeltaStatus
from runtime.memory_patch.lite import budget_context, lexical_relevance
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.memory_patch.retrieval.contracts import HybridRetrievalRequest
from runtime.memory_patch.retrieval.lite import retrieve_eligible
from runtime.mission.contracts import MissionError, bounded_int


def unit(value):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise MissionError("INVALID_BOUNDED_PHEROMONE")
    return float(value)


def decay(value, elapsed, rate):
    value, rate = unit(value), unit(rate)
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        raise MissionError("PHEROMONE_CLOCK_REGRESSION")
    return min(1.0, max(0.0, value * math.exp(-rate * elapsed)))


def recall_salience(
    relevance, positive, negative, *, affinity=1.0, quality=1.0, freshness=1.0
):
    return (
        unit(relevance)
        * unit(affinity)
        * unit(quality)
        * unit(freshness)
        * (1 + unit(positive) + unit(negative))
    )


def action_desirability(positive, negative, *, allowed=False):
    # An inspectable advisory number. The runtime has no effect path; callers
    # cannot turn this numeric argument into a principal or tool permission.
    if type(allowed) is not bool:
        raise MissionError("INVALID_POLICY_INDICATOR")
    return (0.1 + unit(positive)) / (1 + unit(negative)) ** 2 * int(allowed)


@dataclass(frozen=True, slots=True)
class DynamicsPolicy:
    owner_scope: OwnerScope
    mode: str = "SHADOW"
    controlled_test_corpus: bool = False
    decay_per_second: float = 0.0001
    success_deposit: float = 0.2
    error_deposit: float = 0.15
    per_event_cap: float = 0.25
    correlated_family_factor: float = 0.25
    hot_threshold: float = 0.75
    maximum_hot_refs: int = 2
    recheck_deadline_seconds: int = 300
    obligation_deadline_seconds: int = 300
    policy_version: str = "native-dual-pheromone-dvm-v1"
    index_mode: str = "SHADOW"
    maximum_index_entries: int = 32
    maximum_index_candidate_scan: int = 16
    maximum_index_token_hashes: int = 16
    index_policy_version: str = "native-compact-pheromone-index-v1"
    digest: str = field(init=False)

    def __post_init__(self):
        if (
            type(self.owner_scope) is not OwnerScope
            or self.mode not in {"SHADOW", "ACTIVE"}
            or type(self.controlled_test_corpus) is not bool
            or self.policy_version != "native-dual-pheromone-dvm-v1"
            or self.index_mode != "SHADOW"
            or self.index_policy_version != "native-compact-pheromone-index-v1"
        ):
            raise MissionError("INVALID_DYNAMICS_POLICY")
        for name in (
            "decay_per_second",
            "success_deposit",
            "error_deposit",
            "per_event_cap",
            "correlated_family_factor",
            "hot_threshold",
        ):
            unit(getattr(self, name))
        if (
            self.per_event_cap > 0.25
            or self.success_deposit > self.per_event_cap
            or self.error_deposit > self.per_event_cap
        ):
            raise MissionError("PHEROMONE_EVENT_CAP")
        bounded_int(self.maximum_hot_refs, 1, 4)
        bounded_int(self.recheck_deadline_seconds, 5, 3600)
        bounded_int(self.obligation_deadline_seconds, 5, 3600)
        bounded_int(self.maximum_index_entries, 1, 32)
        bounded_int(self.maximum_index_candidate_scan, 1, 16)
        bounded_int(self.maximum_index_token_hashes, 1, 32)
        if self.maximum_index_candidate_scan > self.maximum_index_entries:
            raise MissionError("INVALID_DYNAMICS_POLICY")
        object.__setattr__(
            self, "digest", canonical_sha256(self, exclude_fields=("digest",))
        )

    @property
    def scoring_digest(self):
        return canonical_sha256(
            self,
            exclude_fields=(
                "digest",
                "mode",
                "controlled_test_corpus",
                "index_mode",
                "maximum_index_entries",
                "maximum_index_candidate_scan",
                "maximum_index_token_hashes",
                "index_policy_version",
            ),
        )


@dataclass(frozen=True, slots=True)
class CoreDynamicsBindings:
    policy: DynamicsPolicy


class MemoryDynamics:
    """Adjacent native records; no second scheduler, graph DB or truth store."""

    def __init__(self, learning, policy, context, profile):
        if (
            type(policy) is not DynamicsPolicy
            or policy.owner_scope != learning.policy.owner_scope
            or profile.dynamics_profile_digest != policy.digest
            or profile.dvm_mode != policy.mode
            or profile.pheromone_mode != policy.mode
            or not learning.active
        ):
            raise MissionError("DYNAMICS_BINDING_MISMATCH")
        if policy.mode == "ACTIVE" and (
            context.classification != "CONTRACT_TEST"
            or not policy.controlled_test_corpus
        ):
            raise MissionError("ACTIVE_REQUIRES_CONTROLLED_TEST_CORPUS")
        self.learning, self.policy, self.watch_id = learning, policy, profile.watch_id
        self.last = None
        self._current = {}
        self._current_rows = {}
        from runtime.memory_patch.learning.index import CompactPheromoneIndex

        self.index = CompactPheromoneIndex(
            policy.owner_scope,
            learning.policy.task_signature,
            mode=policy.index_mode,
            maximum_entries=policy.maximum_index_entries,
            candidate_scan_limit=policy.maximum_index_candidate_scan,
            maximum_token_hashes=policy.maximum_index_token_hashes,
        )

    def describe(self):
        return {
            "mode": self.policy.mode,
            "index_mode": self.policy.index_mode,
            "index": self.index.snapshot.metrics(),
            "policy_digest": self.policy.digest,
            "execution_authority": False,
            "auto_mode": "DISABLED",
            "last": self.last,
        }

    def _trail_id(self, delta_id):
        return "trail-" + delta_id

    def _trail(self, tx, delta):
        row = tx.get(RecordKind.LEARNING, self._trail_id(delta.delta_id))
        if row is not None:
            self.learning.validate_record(row)
            value = dict(row.payload)
            if (
                value["delta_ref"] != delta.delta_id
                or value["policy_digest"] != self.policy.scoring_digest
            ):
                raise MissionError("TRAIL_POLICY_MISMATCH")
            unit(value["tau_positive"])
            unit(value["tau_negative"])
            return row, value
        return None, {
            "delta_ref": delta.delta_id,
            "tau_positive": 0.0,
            "tau_negative": 0.0,
            "original_path_ref": canonical_sha256(delta.original_claim),
            "correction_path_ref": canonical_sha256(delta.verified_claim),
            "tier": "DEEP",
            "family_deposits": {},
            "last_update_at": delta.created_at.isoformat(),
            "last_verified_at": delta.created_at.isoformat(),
            "next_check_at": (
                delta.created_at
                + timedelta(seconds=self.policy.recheck_deadline_seconds)
            ).isoformat(),
            "policy_digest": self.policy.scoring_digest,
            "last_event_id": None,
        }

    def _replace(self, tx, old, new):
        if old is None:
            tx.insert(new)
        else:
            tx.replace(new, expected_revision=old.revision)

    def _current_delta(self, delta_id, *, revalidation=False, with_receipts=False):
        row = self.learning.run(lambda tx: tx.get(RecordKind.LEARNING, delta_id))
        if row is None or (
            not revalidation and row.payload.get("reuse_status", "CURRENT") != "CURRENT"
        ):
            raise MissionError("DELTA_REVALIDATION_REQUIRED")
        delta = self.learning.delta(row)
        if (
            delta.status is not DeltaStatus.VERIFIED
            or delta.valid_from > self.learning.now()
            or (not revalidation and self.learning.now() >= delta.valid_until)
            or delta.task_signature != self.learning.policy.task_signature
            or delta.policy_digest != self.learning.policy.knowledge_digest
        ):
            raise MissionError("DELTA_NOT_ELIGIBLE")
        # Read only the native base lanes here to avoid recursive DVM selection.
        native, memory = self.learning.native, self.learning.memory
        principal = native.core.local_operator(Capability.READ)
        request = HybridRetrievalRequest.admitted(
            native.core,
            principal,
            hat_id=self.learning.policy.domain_hat,
            query=self.learning.policy.task_instruction,
        )
        eligible, bundle, _ = retrieve_eligible(
            native, principal, request, memory.profile.max_read_records
        )
        sources = self.learning._sources(eligible, bundle)
        if delta.source_versions != tuple((s[0], s[1]) for s in sources):
            raise MissionError("SOURCE_VERSION_MISMATCH")
        verified, receipts = self.learning.verify(delta.verified_claim, sources)
        if not verified:
            raise MissionError("INDEPENDENT_VERIFICATION_REQUIRED")
        return (delta, receipts) if with_receipts else delta

    def revalidate(self, obligation_id, *, replacement_delta_id=None):
        """Explicit Core operation, never called by model output or the heartbeat.

        The same basis must still pass current independent checks. A changed
        basis requires a separately verified replacement delta and an atomic
        supersession link. No approval or action capability is created.
        """
        obligation = self.learning.run(
            lambda tx: tx.get(RecordKind.LEARNING, obligation_id)
        )
        if obligation is None or obligation.payload.get("state") != "OBLIGATION":
            raise MissionError("OBLIGATION_NOT_FOUND")
        self.learning.validate_record(obligation)
        if obligation.payload["task_signature"] != self.learning.policy.task_signature:
            raise MissionError("OBLIGATION_TASK_MISMATCH")
        if obligation.payload["status"] == "RESOLVED":
            return {"status": "ALREADY_RESOLVED", "obligation_id": obligation_id}
        subject = obligation.payload["subject_id"]
        replacement = replacement_delta_id or subject
        verified, receipts = self._current_delta(
            replacement, revalidation=replacement == subject, with_receipts=True
        )
        now = self.learning.now()

        def update(tx):
            pending = tx.get(RecordKind.LEARNING, obligation_id)
            old = tx.get(RecordKind.LEARNING, subject)
            target = tx.get(RecordKind.LEARNING, replacement)
            if (
                pending.revision != obligation.revision
                or pending.payload["status"] != "OPEN"
            ):
                raise MissionError("OBLIGATION_REVISION_CONFLICT")
            previous = self.learning.delta(old)
            actual = self.learning.delta(target)
            if actual != verified or (
                previous.task_signature,
                previous.original_claim,
            ) != (verified.task_signature, verified.original_claim):
                raise MissionError("REVALIDATION_BASIS_CHANGED")
            event_id = "revalidation-" + canonical_sha256(
                (obligation_id, pending.revision, replacement)
            )
            self.learning._check_quota(tx, 1)
            if subject == replacement:
                current = replace(
                    verified,
                    verifier_set=receipts,
                    valid_from=now,
                    valid_until=now
                    + timedelta(seconds=self.learning.policy.validity_seconds),
                    last_seen_at=now,
                )
                payload = {
                    **dict(old.payload),
                    "delta": current.private_payload(),
                    "reuse_status": "CURRENT",
                    "obligation_ref": None,
                    "resolved_obligation_ref": obligation_id,
                }
                tx.replace(
                    self.learning.record(
                        subject, "DELTA", payload, revision=old.revision + 1
                    ),
                    expected_revision=old.revision,
                )
                trail, value = self._trail(tx, current)
                if trail is not None:
                    value.update(
                        tier="DEEP",
                        last_verified_at=now.isoformat(),
                        next_check_at=(
                            now
                            + timedelta(seconds=self.policy.recheck_deadline_seconds)
                        ).isoformat(),
                    )
                    tx.replace(
                        self.learning.record(
                            trail.record_id, "TRAIL", value, revision=trail.revision + 1
                        ),
                        expected_revision=trail.revision,
                    )
            else:
                retired = replace(
                    previous, status=DeltaStatus.SUPERSEDED, last_seen_at=now
                )
                tx.replace(
                    self.learning.record(
                        subject,
                        "DELTA",
                        {
                            **dict(old.payload),
                            "delta": retired.private_payload(),
                            "reuse_status": "SUPERSEDED",
                            "obligation_ref": None,
                            "resolved_obligation_ref": obligation_id,
                        },
                        revision=old.revision + 1,
                    ),
                    expected_revision=old.revision,
                )
                linked = replace(
                    verified,
                    supersedes=tuple(sorted(set((*verified.supersedes, subject)))),
                )
                tx.replace(
                    self.learning.record(
                        replacement,
                        "DELTA",
                        {**dict(target.payload), "delta": linked.private_payload()},
                        revision=target.revision + 1,
                    ),
                    expected_revision=target.revision,
                )
            tx.replace(
                self.learning.record(
                    obligation_id,
                    "OBLIGATION",
                    {
                        **dict(pending.payload),
                        "status": "RESOLVED",
                        "subject_status": "REVALIDATED"
                        if subject == replacement
                        else "SUPERSEDED",
                        "resolved_at": now.isoformat(),
                        "replacement_delta_ref": replacement,
                    },
                    revision=pending.revision + 1,
                ),
                expected_revision=pending.revision,
            )
            tx.insert(
                self.learning.record(
                    event_id,
                    "REVALIDATION_EVENT",
                    {
                        "obligation_ref": obligation_id,
                        "old_subject_ref": subject,
                        "verified_subject_ref": replacement,
                        "source_versions": verified.source_versions,
                        "verifier_input_digests": tuple(
                            r.input_digest for r in receipts
                        ),
                        "verifier_methods": tuple(r.verifier_method for r in receipts),
                        "reason": "EXPLICIT_CORE_INDEPENDENT_REVALIDATION",
                        "created_at": now.isoformat(),
                        "policy_digest": self.policy.scoring_digest,
                    },
                )
            )
            return {
                "status": "RESOLVED",
                "obligation_id": obligation_id,
                "delta_ref": replacement,
                "event_id": event_id,
            }

        return self.learning.run(update, write=True)

    def _update_tau(self, delta, episode, reason, *, reinforce=False):
        """One atomic score + event update; quality is derived from verification.

        No citation counts, model confidence, arbitrary reward or authority fields
        are accepted. Repeated provenance/episode/family cannot deposit twice.
        """
        if reason not in {"VERIFIED_CORRECTION", "VERIFIED_REUSE", "DECAY"}:
            raise MissionError("UNSUPPORTED_PHEROMONE_SIGNAL")
        if reinforce:
            delta = self._current_delta(delta.delta_id)
        now = self.learning.now()
        family = self.learning.policy.actor.family
        provenance_family = canonical_sha256(
            tuple(sorted(v.source_family for v in self.learning.verifiers))
        )
        event_id = "tau-" + canonical_sha256(
            (delta.delta_id, episode, family, provenance_family, reason)
        )

        def update(tx):
            duplicate = tx.get(RecordKind.LEARNING, event_id)
            if duplicate is not None:
                self.learning.validate_record(duplicate)
                if duplicate.payload["policy_digest"] != self.policy.scoring_digest:
                    raise MissionError("PHEROMONE_EVENT_CONFLICT")
                return {"status": "DUPLICATE_NO_DEPOSIT", "event_id": event_id}
            old, value = self._trail(tx, delta)
            elapsed = (
                now - datetime.fromisoformat(value["last_update_at"])
            ).total_seconds()
            if elapsed < 0:
                raise MissionError("PHEROMONE_CLOCK_REGRESSION")
            if reason == "DECAY" and (
                old is None
                or elapsed < 1
                or not (value["tau_positive"] or value["tau_negative"])
            ):
                return {"status": "NO_CHANGE"}
            before = (value["tau_positive"], value["tau_negative"])
            positive, negative = (
                decay(tau, elapsed, self.policy.decay_per_second) for tau in before
            )
            families = dict(value["family_deposits"])
            independence = (
                self.policy.correlated_family_factor
                if family in families or len(families) >= 8
                else 1.0
            )
            if reinforce:
                positive = min(
                    1.0,
                    positive
                    + min(
                        self.policy.per_event_cap,
                        self.policy.success_deposit * independence,
                    ),
                )
                if reason == "VERIFIED_CORRECTION":
                    negative = min(
                        1.0,
                        negative
                        + min(self.policy.per_event_cap, self.policy.error_deposit),
                    )
                if family in families or len(families) < 8:
                    families[family] = min(1000000, families.get(family, 0) + 1)
                value.update(
                    last_verified_at=now.isoformat(),
                    next_check_at=(
                        now + timedelta(seconds=self.policy.recheck_deadline_seconds)
                    ).isoformat(),
                )
            value.update(
                tau_positive=positive,
                tau_negative=negative,
                family_deposits=families,
                last_update_at=now.isoformat(),
                last_event_id=event_id,
            )
            dependency_id = "dependency-" + delta.delta_id
            dependency = tx.get(RecordKind.LEARNING, dependency_id)
            self.learning._check_quota(
                tx, 1 + int(old is None) + int(dependency is None)
            )
            self._replace(
                tx,
                old,
                self.learning.record(
                    self._trail_id(delta.delta_id),
                    "TRAIL",
                    value,
                    revision=1 if old is None else old.revision + 1,
                ),
            )
            tx.insert(
                self.learning.record(
                    event_id,
                    "PHEROMONE_EVENT",
                    {
                        "delta_ref": delta.delta_id,
                        "old_tau": before,
                        "new_tau": (positive, negative),
                        "reason": reason,
                        "evidence_refs": delta.evidence_refs,
                        "source_versions": delta.source_versions,
                        "actor_family": family,
                        "source_family": provenance_family,
                        "episode_ref": episode,
                        "independence_factor": independence if reinforce else 0.0,
                        "evidence_quality": 1.0 if reinforce else 0.0,
                        "elapsed_seconds": elapsed,
                        "decay_per_second": self.policy.decay_per_second,
                        "created_at": now.isoformat(),
                        "policy_digest": self.policy.scoring_digest,
                        "previous_event_ref": None
                        if old is None
                        else old.payload["last_event_id"],
                    },
                )
            )
            if dependency is None:
                tx.insert(
                    self.learning.record(
                        dependency_id,
                        "DEPENDENCY",
                        {
                            "subject_id": delta.delta_id,
                            "depends_on": delta.source_versions,
                            "evidence_refs": delta.evidence_refs,
                            "relation": "SUPPORTS_DELTA",
                            "task_signature": delta.task_signature,
                            "watch_id": self.watch_id,
                            "last_verified_at": now.isoformat(),
                            "policy_version": self.policy.policy_version,
                        },
                    )
                )
            if reason == "VERIFIED_REUSE":
                stored = tx.get(RecordKind.LEARNING, delta.delta_id)
                if stored.payload.get("reuse_status", "CURRENT") != "CURRENT":
                    raise MissionError("DELTA_REVALIDATION_REQUIRED")
                current = self.learning.delta(stored)
                changed = replace(current, last_used_at=now)
                tx.replace(
                    self.learning.record(
                        delta.delta_id,
                        "DELTA",
                        {**dict(stored.payload), "delta": changed.private_payload()},
                        revision=stored.revision + 1,
                    ),
                    expected_revision=stored.revision,
                )
            return {
                "status": "APPLIED",
                "event_id": event_id,
                "old_tau": before,
                "new_tau": (positive, negative),
            }

        return self.learning.run(update, write=True)

    def correction(self, delta, trace_id):
        return self._update_tau(delta, trace_id, "VERIFIED_CORRECTION", reinforce=True)

    def successful_reuse(self, claim, trace_id, context, used_refs):
        results = []
        for _, delta in self.learning.eligible_deltas(
            context.eligible, context.canonical_bundle
        ):
            if delta.delta_id in used_refs and delta.verified_claim == claim:
                results.append(
                    self._update_tau(delta, trace_id, "VERIFIED_REUSE", reinforce=True)
                )
        return tuple(results)

    def _obligation(self, row, delta, reason, current_versions):
        now = self.learning.now()
        identifier = "obligation-" + canonical_sha256(
            (
                delta.delta_id,
                delta.source_versions,
                current_versions,
                reason,
                delta.last_seen_at.isoformat(),
            )
        )

        def update(tx):
            prior = tx.get(RecordKind.LEARNING, identifier)
            if prior is not None:
                self.learning.validate_record(prior)
                return identifier
            stored = tx.get(RecordKind.LEARNING, row.record_id)
            self.learning.validate_record(stored)
            trail, value = self._trail(tx, delta)
            self.learning._check_quota(tx, 1 + int(trail is None))
            tx.insert(
                self.learning.record(
                    identifier,
                    "OBLIGATION",
                    {
                        "obligation_id": identifier,
                        "subject_id": delta.delta_id,
                        "depends_on": delta.source_versions,
                        "source_versions": current_versions,
                        "source_id": delta.source_versions[0][0],
                        "previous_version": delta.source_versions[0][1],
                        "reason": reason,
                        "next_check_at": now.isoformat(),
                        "deadline": (
                            now
                            + timedelta(seconds=self.policy.obligation_deadline_seconds)
                        ).isoformat(),
                        "status": "OPEN",
                        "subject_status": "REVALIDATION_REQUIRED",
                        "owner": delta.scope.owner_id,
                        "last_verified_at": value["last_verified_at"],
                        "policy_version": self.policy.policy_version,
                        "watch_id": self.watch_id,
                        "task_signature": delta.task_signature,
                        "created_at": now.isoformat(),
                        "evidence_refs": delta.evidence_refs,
                    },
                )
            )
            tx.replace(
                self.learning.record(
                    delta.delta_id,
                    "DELTA",
                    {
                        **dict(stored.payload),
                        "reuse_status": "REVALIDATION_REQUIRED",
                        "obligation_ref": identifier,
                    },
                    revision=stored.revision + 1,
                ),
                expected_revision=stored.revision,
            )
            value.update(
                tier="WORKING" if reason == "CRITICAL_RECHECK_DUE" else "ARCHIVE",
                migration_reason=reason,
            )
            self._replace(
                tx,
                trail,
                self.learning.record(
                    self._trail_id(delta.delta_id),
                    "TRAIL",
                    value,
                    revision=1 if trail is None else trail.revision + 1,
                ),
            )
            return identifier

        return self.learning.run(update, write=True)

    def before_context(self, values, eligible, bundle, query, *, write=True):
        if type(write) is not bool:
            raise MissionError("INVALID_DYNAMICS_WRITE_MODE")
        current_versions = tuple(
            sorted(
                v
                for ref in eligible
                if ref.lane == "CANONICAL_EVIDENCE"
                for v in ref.source_versions
                if v[0] in self.learning.policy.source_ids
            )
        )
        eligible_ids = {delta.delta_id for _, delta in values}
        kept, obligations = [], []
        for row in self.learning.records("DELTA"):
            delta = self.learning.delta(row)
            if delta.task_signature != self.learning.policy.task_signature:
                continue
            _, trail = self.learning.run(lambda tx: self._trail(tx, delta))
            reason = None
            if row.payload.get("reuse_status", "CURRENT") != "CURRENT":
                obligations.append(row.payload.get("obligation_ref"))
                continue
            if delta.delta_id not in eligible_ids:
                reason = (
                    "SOURCE_VERSION_CHANGED"
                    if current_versions and current_versions != delta.source_versions
                    else "EVIDENCE_OR_DELTA_INELIGIBLE"
                )
            elif self.learning.now() >= datetime.fromisoformat(trail["next_check_at"]):
                reason = "CRITICAL_RECHECK_DUE"
            if reason:
                if write:
                    obligations.append(
                        self._obligation(row, delta, reason, current_versions)
                    )
                continue
            if write:
                self._update_tau(delta, self.learning.now().isoformat(), "DECAY")
            kept.append(
                next(value for value in values if value[1].delta_id == delta.delta_id)
            )
        self._current = {delta.delta_id: delta for _, delta in kept}
        self._current_rows = {delta.delta_id: row for row, delta in kept}
        self.last = {
            "obligations": [v for v in obligations if v],
            "mode": self.policy.mode,
            "eligibility_precedes_scores": True,
            "execution_authority": False,
        }
        return tuple(kept)

    def order(self, eligible, query):
        from runtime.memory_patch.learning.index import lexical_token_units

        write = self.learning.personal is None or self.learning.personal.allowed(
            write=True
        )
        baseline = sorted(
            eligible, key=lambda r: (-lexical_relevance(query, r.text), r.reference_id)
        )
        scores = []
        for ref in eligible:
            delta = self._current.get(ref.reference_id)
            if delta is None:
                continue
            _, trail = self.learning.run(lambda tx: self._trail(tx, delta))
            affinity = (
                1.0 if delta.model.family == self.learning.policy.actor.family else 0.5
            )
            # A Core-bound recurring task is a model-risk match even if its
            # observation JSON uses different wording. No cross-task search.
            relevance = max(0.75, lexical_relevance(query, ref.text))
            salience = recall_salience(
                relevance,
                trail["tau_positive"],
                trail["tau_negative"],
                affinity=affinity,
            )
            scores.append(
                {
                    "delta_id": delta.delta_id,
                    "migration_score": salience,
                    "semantic_relevance": lexical_relevance(query, ref.text),
                    "task_match": True,
                    "model_affinity": affinity,
                    "evidence_quality": 1.0,
                    "freshness": 1.0,
                    "tau_positive": trail["tau_positive"],
                    "tau_negative": trail["tau_negative"],
                    "recall_salience": salience,
                    "bad_path_desirability_if_allowed": action_desirability(
                        0.0, trail["tau_negative"], allowed=True
                    ),
                    "actual_action_desirability": action_desirability(
                        trail["tau_positive"], trail["tau_negative"]
                    ),
                    "source_versions": delta.source_versions,
                    "verification_status": delta.status.value,
                }
            )
        scores.sort(key=lambda s: (-s["migration_score"], s["delta_id"]))
        hot = [
            s["delta_id"]
            for s in scores
            if s["migration_score"] >= self.policy.hot_threshold
        ][: self.policy.maximum_hot_refs]
        by_id = {r.reference_id: r for r in baseline}
        proposed = [by_id[i] for i in hot] + [
            r for r in baseline if r.reference_id not in hot
        ]
        actual = proposed if self.policy.mode == "ACTIVE" else baseline
        base_context = budget_context(
            eligible, query, self.learning.memory.profile, ordered=baseline
        )
        proposed_context = budget_context(
            eligible, query, self.learning.memory.profile, ordered=proposed
        )
        selected = budget_context(
            eligible, query, self.learning.memory.profile, ordered=actual
        )
        actual_hot = (
            [r.reference_id for r in selected.selected if r.reference_id in hot]
            if self.policy.mode == "ACTIVE"
            else []
        )
        for score in scores:
            identifier = score["delta_id"]
            if self.policy.mode == "ACTIVE" and write:
                self._tier(
                    self._current[identifier],
                    "HOT" if identifier in actual_hot else "DEEP",
                    score,
                )
        # Re-read accepted trail revisions after any existing NV05 tier event.
        # The derived snapshot then represents durable post-transaction state,
        # so replay and a fresh process reconstruct the same digest.
        index_sources = []
        for identifier, delta in sorted(self._current.items()):
            trail_row, trail = self.learning.run(lambda tx: self._trail(tx, delta))
            index_sources.append(
                (self._current_rows[identifier], delta, trail_row, trail)
            )
        snapshot = self.index.rebuild(
            tuple(index_sources), actor_family=self.learning.policy.actor.family
        )
        index_result = self.index.prioritize(
            query, eligible_ids=frozenset(self._current)
        )
        index_refs = set(index_result.reference_ids)
        index_proposed = [by_id[value] for value in index_result.reference_ids] + [
            ref for ref in actual if ref.reference_id not in index_refs
        ]
        index_context = budget_context(
            eligible, query, self.learning.memory.profile, ordered=index_proposed
        )
        self.last = {
            **(self.last or {}),
            "scores": scores,
            "hot_refs": actual_hot,
            "baseline_selected": [r.reference_id for r in base_context.selected],
            "would_select": [r.reference_id for r in proposed_context.selected],
            "selected": [r.reference_id for r in selected.selected],
            "context_byte_units": selected.context_byte_units,
            "index": {
                **snapshot.metrics(),
                "candidate_scan_count": index_result.candidate_scan_count,
                "query_token_count": index_result.query_token_count,
                "would_prioritize": list(index_result.reference_ids),
                "would_select": [
                    ref.reference_id for ref in index_context.selected
                ],
                "context_before_index_bytes": selected.context_byte_units,
                "context_after_index_bytes": index_context.context_byte_units,
                "context_before_index_token_units": lexical_token_units(
                    selected.prompt_json
                ),
                "context_after_index_token_units": lexical_token_units(
                    index_context.prompt_json
                ),
                "token_measurement": "DETERMINISTIC_LEXICAL_UNITS_NOT_PROVIDER_BILLING",
                "actual_behavior_changed": False,
            },
            "migration_reason": "CONTROLLED_TEST_ACTIVE"
            if self.policy.mode == "ACTIVE"
            else "SHADOW_BASELINE_UNCHANGED",
        }
        return actual

    def _tier(self, delta, tier, score):
        reason = (
            "ELIGIBLE_TASK_MATCH_WITHIN_CONTEXT_BUDGET"
            if tier == "HOT"
            else "BELOW_HOT_THRESHOLD"
            if score["migration_score"] < self.policy.hot_threshold
            else "HOT_REFERENCE_NOT_IN_BOUNDED_CONTEXT"
        )

        def update(tx):
            old, value = self._trail(tx, delta)
            if value["tier"] == tier:
                return
            event_id = "tier-" + canonical_sha256(
                (
                    delta.delta_id,
                    tier,
                    self.learning.now().isoformat(),
                    old.revision if old else 0,
                )
            )
            self.learning._check_quota(tx, 1 + int(old is None))
            tx.insert(
                self.learning.record(
                    event_id,
                    "TIER_EVENT",
                    {
                        "delta_ref": delta.delta_id,
                        "old_tier": value["tier"],
                        "new_tier": tier,
                        "reason": reason,
                        "scores": score,
                        "created_at": self.learning.now().isoformat(),
                        "policy_digest": self.policy.digest,
                    },
                )
            )
            value.update(tier=tier, migration_reason=reason)
            self._replace(
                tx,
                old,
                self.learning.record(
                    self._trail_id(delta.delta_id),
                    "TRAIL",
                    value,
                    revision=1 if old is None else old.revision + 1,
                ),
            )

        return self.learning.run(update, write=True)
