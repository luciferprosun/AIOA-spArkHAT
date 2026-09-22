"""Explicit LITE composition of the native Memory Patch, with inert context.

The Core supplies these Python bindings. A manifest/model cannot construct a
principal, resolve credentials, start a migration or select a different owner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from runtime.core_admission import Capability, CoreAdmission, OwnerScope
from runtime.memory_patch.contract import MemoryPatchConfig, operation_capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.retrieval.contracts import (
    HybridRetrievalRequest,
    bounded_text,
)
from runtime.memory_patch.retrieval.temporal import FreshnessPolicy
from runtime.memory_patch.service import CoreMemoryPatchDependencies, MemoryPatchService
from runtime.mission.contracts import MissionError, bounded_int, logical_id


@dataclass(frozen=True, slots=True, repr=False)
class LiteMemoryProfile:
    owner_scope: OwnerScope
    hat_id: str
    memory_mode: str = "OFF"
    backend_id: str = "cockroachdb"
    schema_version: str = "memory-patch-native-v1"
    evidence_policy_ref: str = "core-source-publication-v1"
    temporal_policy_ref: str = "temporal-resolution-policy-1a"
    freshness_policy_ref: str = "unconfigured"
    write_policy_ref: str = "read-only"
    max_read_records: int = 40
    max_context_records: int = 8
    max_context_tokens: int = 1024
    digest: str = field(init=False)

    def __post_init__(self):
        if (
            type(self.owner_scope) is not OwnerScope
            or type(self.memory_mode) is not str
            or self.memory_mode not in {"OFF", "SHADOW", "ACTIVE"}
        ):
            raise MissionError("INVALID_MEMORY_PROFILE")
        for name in ("hat_id", "backend_id", "schema_version", "freshness_policy_ref"):
            logical_id(getattr(self, name))
        if (
            self.evidence_policy_ref != "core-source-publication-v1"
            or self.temporal_policy_ref != "temporal-resolution-policy-1a"
            or self.write_policy_ref not in {"read-only", "native-owner-explicit-v1"}
        ):
            raise MissionError("INVALID_MEMORY_POLICY")
        bounded_int(self.max_read_records, 1, 40)
        bounded_int(self.max_context_records, 1, 16)
        bounded_int(self.max_context_tokens, 64, 8192)
        object.__setattr__(
            self, "digest", canonical_sha256(self, exclude_fields=("digest",))
        )


@dataclass(frozen=True, slots=True, repr=False)
class CoreLiteMemoryBindings:
    profile: LiteMemoryProfile
    core: CoreAdmission
    config: MemoryPatchConfig
    dependencies: CoreMemoryPatchDependencies
    hat_selection: object = None
    backend_id: str = "cockroachdb"
    schema_version: str = "memory-patch-native-v1"


@dataclass(frozen=True, slots=True, repr=False)
class ContextReference:
    reference_id: str
    lane: str
    text: str
    evidence_refs: tuple[str, ...]
    source_versions: tuple[tuple[str, str], ...]
    revision: int
    valid_from: str | None = None
    valid_until: str | None = None
    execution_authority: bool = field(default=False, init=False)

    def prompt_value(self):
        return {
            "ref": self.reference_id,
            "lane": self.lane,
            "text": self.text,
            "evidence": self.evidence_refs,
            "versions": self.source_versions,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True, repr=False)
class MemoryContext:
    status: str
    reason_codes: tuple[str, ...]
    selected: tuple[ContextReference, ...]
    eligible: tuple[ContextReference, ...]
    prompt_json: str
    context_byte_units: int
    truncated: bool
    canonical_bundle: object = None

    def describe(self):
        return {
            "status": self.status,
            "reason_codes": self.reason_codes,
            "selected_refs": [r.reference_id for r in self.selected],
            "eligible_count": len(self.eligible),
            "context_byte_units": self.context_byte_units,
            "truncated": self.truncated,
            "execution_authority": False,
        }


def lexical_relevance(query, text):
    # Local deterministic ranking is called only after eligibility. No vectors,
    # provider calls or similarity across an unauthorized candidate pool.
    import re

    tokens = set(re.findall(r"\w+", query.casefold()))
    return len(tokens & set(re.findall(r"\w+", text.casefold()))) / max(1, len(tokens))


def budget_context(eligible, query, profile, *, ordered=None, reasons=(), bundle=None):
    if ordered is not None and (
        len(ordered) != len(eligible)
        or {r.reference_id for r in ordered} != {r.reference_id for r in eligible}
        or any(r not in eligible for r in ordered)
    ):
        raise MissionError("INELIGIBLE_CONTEXT_ORDER")
    ordered = (
        ordered
        if ordered is not None
        else sorted(
            eligible, key=lambda r: (-lexical_relevance(query, r.text), r.reference_id)
        )
    )
    selected = []
    # UTF-8 byte units bound the entire serialized context, including framing
    # and references, conservatively; they are not measured provider tokens.
    for record in ordered:
        if len(selected) >= profile.max_context_records:
            break
        candidate = json.dumps(
            [r.prompt_value() for r in [*selected, record]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(candidate.encode()) <= profile.max_context_tokens:
            selected.append(record)
    payload = json.dumps(
        [r.prompt_value() for r in selected], ensure_ascii=False, separators=(",", ":")
    )
    truncated = len(selected) < len(eligible)
    codes = tuple(
        sorted(
            set(
                (
                    *reasons,
                    *(("CONTEXT_BUDGET_TRUNCATED",) if truncated else ()),
                    "ELIGIBLE_BEFORE_RELEVANCE",
                )
            )
        )
    )
    return MemoryContext(
        "READY",
        codes,
        tuple(selected),
        tuple(eligible),
        payload,
        len(payload.encode()),
        truncated,
        bundle,
    )


class LiteMemoryService:
    """Owned by AgentRuntime; borrows Core ports and never auto-writes knowledge."""

    def __init__(self, lite_profile, context, bindings):
        if (
            type(bindings) is not CoreLiteMemoryBindings
            or type(bindings.profile) is not LiteMemoryProfile
        ):
            raise MissionError("MEMORY_BINDINGS_REQUIRED")
        profile = bindings.profile
        if (
            type(bindings.core) is not CoreAdmission
            or type(bindings.config) is not MemoryPatchConfig
            or type(bindings.dependencies) is not CoreMemoryPatchDependencies
        ):
            raise MissionError("INVALID_MEMORY_BINDINGS")
        if (
            profile.owner_scope != context.owner_scope
            or profile.owner_scope != lite_profile.owner_scope
            or profile.memory_mode != lite_profile.memory_mode
            or profile.digest != lite_profile.memory_profile_digest
            or profile.backend_id != bindings.backend_id
            or profile.schema_version != bindings.schema_version
            or bindings.schema_version != "memory-patch-native-v1"
        ):
            raise MissionError("MEMORY_BINDING_MISMATCH")
        principal = bindings.core.local_operator(Capability.READ)
        bindings.core.require(principal, Capability.READ, scope=profile.owner_scope)
        if (
            profile.hat_id not in principal.hat_ids
            or not bindings.config.enabled
            or bindings.config.assignment is None
            or bindings.config.assignment.scope != profile.owner_scope
        ):
            raise MissionError("MEMORY_OWNER_DENIED")
        if (
            profile.backend_id == "repository-durable-test"
            and context.classification != "CONTRACT_TEST"
        ):
            raise MissionError("TEST_BACKEND_REQUIRES_TEST_CONTEXT")
        freshness = bindings.dependencies.freshness
        if (
            type(freshness) is not FreshnessPolicy
            or not freshness.maximum_age_seconds_by_source_kind
            or profile.freshness_policy_ref
            != freshness.policy_id + "." + freshness.policy_version
        ):
            raise MissionError("MEMORY_FRESHNESS_POLICY_REQUIRED")
        self.profile, self.bindings = profile, bindings
        self.service = MemoryPatchService(
            bindings.core,
            config=bindings.config,
            dependencies=bindings.dependencies,
            existing_hat_selection=bindings.hat_selection,
        )
        self.last = None
        self.learning = None
        self.closed = False

    def describe(self):
        d = self.bindings.dependencies
        ready = (
            self.service.transactions.configured
            and d.evidence_catalog is not None
            and callable(getattr(d.sources, "scan_scope", None))
            and d.provenance_store is not None
            and d.bundle_resolver is not None
            and self.service.hats is not None
        )
        return {
            "memory_mode": self.profile.memory_mode,
            "backend_id": self.profile.backend_id,
            "schema_version": self.profile.schema_version,
            "profile_digest": self.profile.digest,
            "readiness": "CLOSED"
            if self.closed
            else self.last.status
            if self.last
            else "CONFIGURED_UNPROBED"
            if ready
            else "DEGRADED",
            "reason_code": "MODULE_CLOSED"
            if self.closed
            else "MEMORY_DEPENDENCY_MISSING"
            if not ready
            else "EXPLICIT_COMPOSITION",
            "last_read": None if self.last is None else self.last.describe(),
            "max_read_records": self.profile.max_read_records,
            "max_context_records": self.profile.max_context_records,
            "max_context_tokens": self.profile.max_context_tokens,
            "token_accounting": "CONSERVATIVE_UTF8_BYTES_WITH_FRAMING",
            "execution_authority": False,
        }

    def retrieve(self, query):
        if self.closed:
            raise MissionError("MEMORY_CLOSED")
        bounded_text(query, 4096)
        try:
            if self.describe()["reason_code"] == "MEMORY_DEPENDENCY_MISSING":
                raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
            principal = self.bindings.core.local_operator(Capability.READ)
            request = HybridRetrievalRequest.admitted(
                self.bindings.core,
                principal,
                hat_id=self.profile.hat_id,
                query=query,
                limit=min(40, self.profile.max_read_records),
                context_budget_bytes=262144,
            )
            from runtime.memory_patch.retrieval.lite import retrieve_eligible

            eligible, bundle, reasons = retrieve_eligible(
                self.service, principal, request, self.profile.max_read_records
            )
            if self.learning is not None:
                eligible = (*eligible, *self.learning.context(eligible, bundle, query))
            ordered = None
            if self.learning is not None and self.learning.dynamics is not None:
                ordered = self.learning.dynamics.order(eligible, query)
            self.last = budget_context(
                eligible, query, self.profile, ordered=ordered, reasons=reasons, bundle=bundle
            )
        except Exception as error:
            code = (
                error.code.value
                if isinstance(error, MemoryPatchError)
                else "MEMORY_READ_DENIED"
            )
            self.last = MemoryContext("DEGRADED", (code,), (), (), "[]", 2, False)
        return self.last

    def operator_request(self, operation, payload):
        # This explicit Core API is never called with actor/critic output.
        allowed = {
            "status",
            "read",
            "list",
            "trace",
            "recover",
            "initialize-publication",
            "publish",
            "slot-create",
            "slot-configure",
            "slot-state",
            "candidate",
            "propose",
            "bind-evidence",
            "validate",
            "await-approval",
            "challenge",
            "decision",
            "commit",
            "activate",
            "revoke",
            "supersede",
        }
        if operation not in allowed or self.closed:
            raise MissionError("MEMORY_OPERATION_DENIED")
        if operation == "status":
            return 200, self.describe()
        capability = operation_capability(operation)
        if capability is not Capability.READ and (
            self.profile.memory_mode != "ACTIVE"
            or self.profile.write_policy_ref != "native-owner-explicit-v1"
        ):
            raise MissionError("MEMORY_WRITE_POLICY_DENIED")
        principal = self.bindings.core.local_operator(capability)
        self.bindings.core.require(
            principal, capability, scope=self.profile.owner_scope
        )
        return self.service.request(principal, operation, payload)

    def close(self):
        if not self.closed:
            self.closed = True
            self.service.close()
