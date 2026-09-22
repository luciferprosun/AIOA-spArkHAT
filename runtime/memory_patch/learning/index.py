"""Compact, bounded SHADOW index derived from admitted learning records.

The index is deliberately not a truth, evidence, consent, ownership, or action
store.  It is rebuilt from the current owner-scoped DELTA/TRAIL records after
the normal eligibility and independent-verification gates.  A result may only
reorder a supplied eligible set and callers must dereference the complete
record before context assembly.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
    require_sha256_hex,
)
from runtime.memory_patch.learning.contracts import DeltaStatus, EpistemicDelta
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.contracts import MissionError, bounded_int, logical_id


INDEX_SCHEMA = "native-compact-pheromone-index-v1"
_TOKEN = re.compile(r"\w+")
_PPM = 1_000_000


def _unit_ppm(value: object) -> int:
    """Canonical fixed-point representation of a bounded pheromone value."""
    if type(value) not in (int, float) or not 0 <= value <= 1:
        raise MissionError("INVALID_BOUNDED_PHEROMONE")
    # Quantize once so sorting and serialization use integers thereafter.
    return int(round(float(value) * _PPM))


def _token_hashes(value: str, maximum: int) -> tuple[str, ...]:
    if type(value) is not str:
        raise MissionError("INVALID_INDEX_TEXT")
    bounded_int(maximum, 1, 32)
    values = {
        hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
        for token in _TOKEN.findall(value.casefold())
    }
    return tuple(sorted(values)[:maximum])


def lexical_token_units(value: str) -> int:
    """Deterministic lexical units, explicitly not provider billing tokens."""
    if type(value) is not str:
        raise MissionError("INVALID_INDEX_TEXT")
    return len(_TOKEN.findall(value))


@dataclass(frozen=True, slots=True, repr=False)
class CompactIndexEntry:
    """No claim body; enough metadata to preserve gates while prioritizing."""

    reference_id: str
    delta_revision: int
    trail_revision: int
    tau_positive_ppm: int
    tau_negative_ppm: int
    affinity_ppm: int
    token_hashes: tuple[str, ...]
    semantic_kind: str
    required_condition: str | None
    evidence_refs: tuple[str, ...]
    source_versions: tuple[tuple[str, str], ...]
    verifier_metadata: tuple[tuple[str, str, str, str], ...]
    valid_from: str
    valid_until: str
    policy_digest: str
    verification_status: str = "VERIFIED"
    reuse_status: str = "CURRENT"
    execution_authority: bool = field(default=False, init=False)
    publication_authority: bool = field(default=False, init=False)
    entry_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256_hex(self.reference_id, "index reference")
        require_sha256_hex(self.policy_digest, "index policy")
        if (
            type(self.delta_revision) is not int
            or self.delta_revision < 1
            or type(self.trail_revision) is not int
            or self.trail_revision < 0
            or self.verification_status != "VERIFIED"
            or self.reuse_status != "CURRENT"
            or not self.evidence_refs
            or not self.source_versions
            or len(self.verifier_metadata) < 2
            or any(len(row) != 4 for row in self.verifier_metadata)
            or any(not row[3] for row in self.verifier_metadata)
            or any(
                type(value) is not str
                for row in self.verifier_metadata
                for value in row
            )
            or any(
                type(value) is not str or len(value) != 24
                for value in self.token_hashes
            )
            or len(self.token_hashes) > 32
        ):
            raise MissionError("INVALID_COMPACT_INDEX_ENTRY")
        for value in (
            self.tau_positive_ppm,
            self.tau_negative_ppm,
            self.affinity_ppm,
        ):
            if type(value) is not int or not 0 <= value <= _PPM:
                raise MissionError("INVALID_COMPACT_INDEX_ENTRY")
        if self.required_condition is not None and (
            type(self.required_condition) is not str
            or not self.required_condition
            or len(self.required_condition.encode("utf-8")) > 4096
        ):
            raise MissionError("INVALID_COMPACT_INDEX_ENTRY")
        object.__setattr__(
            self,
            "entry_digest",
            canonical_sha256(self, exclude_fields=("entry_digest",)),
        )

    @property
    def byte_length(self) -> int:
        return len(canonical_json_bytes(self))


@dataclass(frozen=True, slots=True, repr=False)
class CompactIndexSnapshot:
    schema: str
    mode: str
    scope_digest: str
    task_signature: str
    entries: tuple[CompactIndexEntry, ...]
    source_scan_count: int
    maximum_entries: int
    candidate_scan_limit: int
    truncated: bool
    verification_required: bool = field(default=True, init=False)
    execution_authority: bool = field(default=False, init=False)
    publication_authority: bool = field(default=False, init=False)
    snapshot_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256_hex(self.scope_digest, "index scope")
        bounded_int(self.maximum_entries, 1, 32)
        bounded_int(self.candidate_scan_limit, 1, 16)
        if (
            self.schema != INDEX_SCHEMA
            or self.mode != "SHADOW"
            or type(self.entries) is not tuple
            or len(self.entries) > self.maximum_entries
            or type(self.source_scan_count) is not int
            or self.source_scan_count < len(self.entries)
            or type(self.truncated) is not bool
            or self.truncated != (self.source_scan_count > len(self.entries))
            or len({entry.reference_id for entry in self.entries}) != len(self.entries)
        ):
            raise MissionError("INVALID_COMPACT_INDEX")
        if self.candidate_scan_limit > self.maximum_entries:
            raise MissionError("INVALID_COMPACT_INDEX")
        object.__setattr__(
            self,
            "snapshot_digest",
            canonical_sha256(self, exclude_fields=("snapshot_digest",)),
        )

    @property
    def byte_length(self) -> int:
        return len(canonical_json_bytes(self))

    def metrics(self) -> dict[str, object]:
        entry_bytes = sum(entry.byte_length for entry in self.entries)
        return {
            "schema": self.schema,
            "mode": self.mode,
            "snapshot_digest": self.snapshot_digest,
            "entry_count": len(self.entries),
            "source_scan_count": self.source_scan_count,
            "maximum_entries": self.maximum_entries,
            "candidate_scan_limit": self.candidate_scan_limit,
            "truncated": self.truncated,
            "index_bytes": self.byte_length,
            "entry_bytes": entry_bytes,
            "bytes_per_entry": 0
            if not self.entries
            else entry_bytes / len(self.entries),
            "verification_required": True,
            "execution_authority": False,
            "publication_authority": False,
        }


@dataclass(frozen=True, slots=True, repr=False)
class CompactIndexResult:
    reference_ids: tuple[str, ...]
    scores: tuple[tuple[str, int], ...]
    candidate_scan_count: int
    query_token_count: int

    def __post_init__(self) -> None:
        if (
            type(self.reference_ids) is not tuple
            or len(set(self.reference_ids)) != len(self.reference_ids)
            or self.reference_ids != tuple(value[0] for value in self.scores)
            or type(self.candidate_scan_count) is not int
            or self.candidate_scan_count != len(self.scores)
            or type(self.query_token_count) is not int
            or self.query_token_count < 0
        ):
            raise MissionError("INVALID_COMPACT_INDEX_RESULT")


class CompactPheromoneIndex:
    """Per-composition SHADOW projection; never a second durable authority."""

    def __init__(
        self,
        scope: OwnerScope,
        task_signature: str,
        *,
        mode: str,
        maximum_entries: int,
        candidate_scan_limit: int,
        maximum_token_hashes: int,
    ) -> None:
        if type(scope) is not OwnerScope or mode != "SHADOW":
            # NV08 has no Roadmap-v2.1 acceptance condition for ACTIVE index use.
            raise MissionError("INDEX_ACTIVE_NOT_ACCEPTED")
        logical_id(task_signature)
        bounded_int(maximum_entries, 1, 32)
        bounded_int(candidate_scan_limit, 1, 16)
        bounded_int(maximum_token_hashes, 1, 32)
        if candidate_scan_limit > maximum_entries:
            raise MissionError("INVALID_COMPACT_INDEX")
        self.scope = scope
        self.task_signature = task_signature
        self.mode = mode
        self.maximum_entries = maximum_entries
        self.candidate_scan_limit = candidate_scan_limit
        self.maximum_token_hashes = maximum_token_hashes
        self.snapshot = self._empty()
        self.last_result = CompactIndexResult((), (), 0, 0)

    def _empty(self) -> CompactIndexSnapshot:
        return CompactIndexSnapshot(
            INDEX_SCHEMA,
            self.mode,
            canonical_sha256(self.scope),
            self.task_signature,
            (),
            0,
            self.maximum_entries,
            self.candidate_scan_limit,
            False,
        )

    def clear(self) -> None:
        self.snapshot = self._empty()
        self.last_result = CompactIndexResult((), (), 0, 0)

    def _entry(
        self,
        row: StoredRecord,
        delta: EpistemicDelta,
        trail_row: StoredRecord | None,
        trail: dict[str, object],
        actor_family: str,
    ) -> CompactIndexEntry:
        if type(row) is not StoredRecord:
            raise MissionError("INDEX_ELIGIBILITY_MISMATCH")
        row.verify()
        if (
            row.kind is not RecordKind.LEARNING
            or row.scope != self.scope
            or row.payload.get("state") != "DELTA"
            or row.payload.get("domain_hat") != delta.domain_hat
            or row.payload.get("privacy_scope") != "PRIVATE"
            or row.payload.get("execution_authority") is not False
            or row.payload.get("publication_authority") is not False
            or delta.scope != self.scope
            or delta.delta_id != row.record_id
            or delta.task_signature != self.task_signature
            or delta.status is not DeltaStatus.VERIFIED
            or row.payload.get("reuse_status", "CURRENT") != "CURRENT"
            or trail.get("delta_ref") != delta.delta_id
            or any(receipt.supported is not True for receipt in delta.verifier_set)
            or len({receipt.verifier_method for receipt in delta.verifier_set}) < 2
            or len({receipt.source_family for receipt in delta.verifier_set}) < 2
        ):
            raise MissionError("INDEX_ELIGIBILITY_MISMATCH")
        if trail_row is not None:
            if type(trail_row) is not StoredRecord:
                raise MissionError("INDEX_ELIGIBILITY_MISMATCH")
            trail_row.verify()
            if (
                trail_row.kind is not RecordKind.LEARNING
                or trail_row.scope != self.scope
                or trail_row.payload.get("state") != "TRAIL"
                or trail_row.payload.get("domain_hat") != delta.domain_hat
                or trail_row.payload.get("privacy_scope") != "PRIVATE"
                or trail_row.payload.get("execution_authority") is not False
                or trail_row.payload.get("publication_authority") is not False
                or trail_row.record_id != "trail-" + delta.delta_id
            ):
                raise MissionError("INDEX_ELIGIBILITY_MISMATCH")
        return CompactIndexEntry(
            delta.delta_id,
            row.revision,
            0 if trail_row is None else trail_row.revision,
            _unit_ppm(trail["tau_positive"]),
            _unit_ppm(trail["tau_negative"]),
            _PPM if delta.model.family == actor_family else _PPM // 2,
            _token_hashes(delta.verified_claim, self.maximum_token_hashes),
            delta.delta_kind.value,
            delta.required_condition,
            delta.evidence_refs,
            delta.source_versions,
            tuple(
                (
                    receipt.verifier_ref,
                    receipt.verifier_method,
                    receipt.source_family,
                    receipt.input_digest,
                )
                for receipt in delta.verifier_set
            ),
            delta.valid_from.isoformat(),
            delta.valid_until.isoformat(),
            delta.policy_digest,
        )

    def rebuild(
        self,
        admitted: tuple[
            tuple[StoredRecord, EpistemicDelta, StoredRecord | None, dict[str, object]],
            ...,
        ],
        *,
        actor_family: str,
    ) -> CompactIndexSnapshot:
        if (
            type(admitted) is not tuple
            or type(actor_family) is not str
            or not actor_family
        ):
            raise MissionError("INVALID_COMPACT_INDEX")
        entries = [self._entry(*value, actor_family) for value in admitted]
        if len({entry.reference_id for entry in entries}) != len(entries):
            raise MissionError("INVALID_COMPACT_INDEX")
        # Query-independent upper bound: strongest advisory signal first, then
        # the stable canonical identity.  Query ranking scans only the bounded
        # prefix below; this order grants no eligibility.
        entries.sort(
            key=lambda entry: (
                -(
                    (_PPM + entry.tau_positive_ppm + entry.tau_negative_ppm)
                    * entry.affinity_ppm
                ),
                entry.reference_id,
            )
        )
        kept = tuple(entries[: self.maximum_entries])
        self.snapshot = CompactIndexSnapshot(
            INDEX_SCHEMA,
            self.mode,
            canonical_sha256(self.scope),
            self.task_signature,
            kept,
            len(entries),
            self.maximum_entries,
            self.candidate_scan_limit,
            len(entries) > len(kept),
        )
        return self.snapshot

    def prioritize(
        self, query: str, *, eligible_ids: frozenset[str]
    ) -> CompactIndexResult:
        if type(query) is not str or type(eligible_ids) is not frozenset:
            raise MissionError("INVALID_COMPACT_INDEX_QUERY")
        if len(query.encode("utf-8")) > 4096:
            raise MissionError("INVALID_COMPACT_INDEX_QUERY")
        if any(entry.reference_id not in eligible_ids for entry in self.snapshot.entries):
            raise MissionError("INDEX_ELIGIBILITY_MISMATCH")
        query_tokens = _token_hashes(query, self.maximum_token_hashes)
        denominator = max(1, len(query_tokens))
        ranked = []
        for entry in self.snapshot.entries[: self.candidate_scan_limit]:
            overlap = len(set(query_tokens) & set(entry.token_hashes))
            relevance_ppm = max(750_000, overlap * _PPM // denominator)
            score = (
                relevance_ppm
                * entry.affinity_ppm
                * (_PPM + entry.tau_positive_ppm + entry.tau_negative_ppm)
                // (_PPM * _PPM)
            )
            ranked.append((entry.reference_id, score))
        ranked.sort(key=lambda value: (-value[1], value[0]))
        self.last_result = CompactIndexResult(
            tuple(value[0] for value in ranked),
            tuple(ranked),
            len(ranked),
            len(query_tokens),
        )
        return self.last_result
