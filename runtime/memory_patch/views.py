"""Named transport views. Private durable DTOs never become response dictionaries."""

from __future__ import annotations

import re
from dataclasses import dataclass

from runtime.core_admission import AdmissionError, CoreAdmission, CorePrincipal
from runtime.evidence_admission import EvidenceAdmissionError
from runtime.memory_patch.contract import MODULE_ID, OPERATION_CAPABILITIES
from runtime.memory_patch.contracts.enums import PatchState
from runtime.memory_patch.correction.answers import UNKNOWN_ANSWER, NativeVerifiedAnswer
from runtime.memory_patch.errors import (
    ErrorCode,
    KernelContractError,
    MemoryPatchError,
    QuotaExceeded,
)
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.memory_patch.personal.approval import FreshOwnerChallenge
from runtime.memory_patch.personal.contracts import (
    CandidateDraft,
    instant,
    validate_patch_record,
)

_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|(?:postgres(?:ql)?|cockroach|file)://|(?:/home/|/tmp/|/var/|/run/|[a-z]:\\\\)"
    r"|(?:bearer|password|secret|session[_ -]?token|api[_ -]?key|nonce[_ -]?hash)\s*[:= ]"
    r"|(?:sk-proj-|sk-ant-|AKIA)[A-Za-z0-9_-]+|(?<![\w-])[A-Za-z0-9_-]{43,}(?![\w-]))"
)
_WITHHELD = "Content withheld by the transport privacy policy."
_VERIFICATION = frozenset(
    {
        "UNVERIFIED",
        "VERIFIED",
        "OWNER_CONTEXT_ONLY",
        "PROVENANCE_PENDING",
        "REVIEW_REQUIRED",
    }
)
_NEXT = {
    "DETECTED": ("propose",),
    "PROPOSED": ("bind-evidence",),
    "EVIDENCE_BOUND": ("validate",),
    "VALIDATED": ("await-approval",),
    "AWAITING_APPROVAL": ("challenge",),
    "APPROVED": ("commit",),
    "COMMITTED": ("activate",),
    "ACTIVE": ("revoke", "sharing"),
    "REJECTED": (),
    "REVOKED": (),
    "SUPERSEDED": (),
}


def opaque_id(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(
        re.escape(prefix) + r"_[0-9a-f]{32}", value
    ):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return value


def revision(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return value


def timestamp(value, *, nullable=False):
    if value is None and nullable:
        return None
    if instant(value) is None:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return value


@dataclass(frozen=True, slots=True, repr=False)
class ProjectionContext:
    core: CoreAdmission
    principal: CorePrincipal
    private_values: tuple[str, ...] = ()

    def require(self, record=None):
        self.core.require(
            self.principal,
            self.principal.capability,
            scope=None if record is None else record.scope,
        )
        if record is not None:
            record.verify()

    def text(self, value, maximum, *, extra=()):
        """Bound a selected text leaf; never traverse or redact a durable object."""
        self.require()
        if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        private = (
            *self.principal.scope.binding(),
            self.principal.actor_session_id,
            *self.principal.hat_ids,
            *self.principal.model_binding_ids,
            *self.private_values,
            *extra,
        )
        if _SENSITIVE_TEXT.search(value) or any(
            isinstance(item, str) and item and item.casefold() in value.casefold()
            for item in private
        ):
            return _WITHHELD, True
        if any(ord(c) < 32 and c not in "\n\t" for c in value):
            return _WITHHELD, True
        return value, False


def envelope(operation, *, result=None, error=None):
    operation = (
        operation
        if operation == "status" or operation in OPERATION_CAPABILITIES
        else "invalid"
    )
    return {
        "ok": error is None,
        "module": MODULE_ID,
        "operation": operation,
        "result": result if error is None else None,
        "error": error,
    }


def error_view(error):
    if isinstance(error, MemoryPatchError):
        code = error.code
    elif isinstance(error, AdmissionError):
        code = ErrorCode.ADMISSION_DENIED
    elif isinstance(error, EvidenceAdmissionError):
        code = ErrorCode.EVIDENCE_DENIED
    elif isinstance(error, QuotaExceeded):
        code = ErrorCode.QUOTA_EXCEEDED
    elif isinstance(
        error, (KernelContractError, ValueError, TypeError, KeyError, RecursionError)
    ):
        code = ErrorCode.INVALID_REQUEST
    else:
        code = ErrorCode.INTERNAL_ERROR
    recovery = code in {
        ErrorCode.RECOVERY_REQUIRED,
        ErrorCode.PROVENANCE_PENDING,
        ErrorCode.PROVENANCE_CORRUPT,
    }
    retry = code is ErrorCode.RETRY_EXHAUSTED
    message = (
        "Operation requires reconciliation."
        if recovery
        else (
            "Backend is not configured."
            if code is ErrorCode.BACKEND_UNCONFIGURED
            else "Request was denied."
            if code
            in {
                ErrorCode.ADMISSION_DENIED,
                ErrorCode.OWNER_DENIED,
                ErrorCode.CHALLENGE_DENIED,
                ErrorCode.MIGRATION_DENIED,
                ErrorCode.TARGET_DENIED,
            }
            else "Operation could not be completed."
        )
    )
    return {
        "code": code.value,
        "safe_message": message,
        "retryable": retry,
        "recovery_required": recovery,
    }


def error_response(operation, error):
    view = error_view(error)
    code = view["code"]
    status = (
        503
        if code
        in {
            "BACKEND_UNCONFIGURED",
            "MODULE_CLOSED",
            "INTERNAL_ERROR",
            "RETRY_EXHAUSTED",
        }
        else (
            403
            if code
            in {
                "ADMISSION_DENIED",
                "OWNER_DENIED",
                "CHALLENGE_DENIED",
                "EVIDENCE_DENIED",
                "MIGRATION_DENIED",
                "TARGET_DENIED",
                "PROVIDER_DENIED",
            }
            else 404
            if code == "NOT_FOUND"
            else 400
            if code == "INVALID_REQUEST"
            else 409
        )
    )
    return status, envelope(operation, error=view)


def patch_view(
    ctx: ProjectionContext,
    record: StoredRecord,
    *,
    sources=(),
    verification="UNVERIFIED",
):
    ctx.require(record)
    candidate = validate_patch_record(record)
    # validate_patch_record returns no transport object; reconstruct the exact
    # candidate only for the five specifically selected content/validity leaves.
    candidate = CandidateDraft.from_private(record.payload["candidate"])
    p = record.payload
    state = PatchState(p["state"]).value
    if verification not in _VERIFICATION or len(sources) > 32:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    title, tchanged = ctx.text(candidate.title, 160)
    summary, schanged = ctx.text(candidate.summary, 2048)
    changed = tchanged or schanged
    if changed:
        verification = "UNVERIFIED"
    return {
        "patch_id": opaque_id(record.record_id, "patch"),
        "revision": revision(record.revision),
        "state": state,
        "title": title,
        "summary": summary,
        "created_at": timestamp(p["created_at"]),
        "updated_at": timestamp(p["updated_at"]),
        "validity": {
            "valid_from": timestamp(p["candidate"]["valid_from"], nullable=True),
            "valid_until": timestamp(p["candidate"]["valid_until"], nullable=True),
            "expires_at": timestamp(p["candidate"]["expires_at"], nullable=True),
        },
        "source_refs": [
            {"evidence_id": opaque_id(value, "evidence")} for value in sources
        ],
        "verification_status": verification,
        "allowed_actions": []
        if p["logically_deleted"] or changed
        else list(_NEXT[state]),
    }


def _quota(number, *, nullable=False):
    if number is None and nullable:
        return None
    if type(number) is not int or not 0 <= number <= 2**63 - 1:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return number


def owner_memory_space_view(ctx, space, patches, *, active_count, bytes_used):
    ctx.require(space)
    if space.kind is not RecordKind.SPACE or len(patches) > 128:
        raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
    p = space.payload
    if p["state"] not in {
        "EMPTY",
        "CONFIGURED",
        "ACTIVE",
        "SUSPENDED",
        "ARCHIVED",
        "DELETED_PENDING",
        "DELETED",
    }:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return {
        "space_id": opaque_id(p["public_space_id"], "space"),
        "slot_id": opaque_id(p["public_slot_id"], "slot"),
        "state": p["state"],
        "quota_used": {
            "active_patches": _quota(active_count),
            "bytes": _quota(bytes_used),
        },
        "quota_limit": {
            "active_patches": _quota(
                p["quota"]["maximum_active_memory_patches"], nullable=True
            ),
            "bytes": _quota(p["quota"]["maximum_bytes"], nullable=True),
        },
        "patches": patches,
    }


def approval_challenge_view(ctx, challenge: FreshOwnerChallenge):
    if type(challenge) is not FreshOwnerChallenge:
        raise MemoryPatchError(ErrorCode.CHALLENGE_DENIED)
    ctx.require(challenge.record)
    p = challenge.record.payload
    nonce = challenge.decision_nonce
    if nonce is not None and (
        challenge.replayed
        or p["state"] != "OPEN"
        or p["actor_session_id"] != ctx.principal.actor_session_id
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce)
    ):
        raise MemoryPatchError(ErrorCode.CHALLENGE_DENIED)
    return {
        "challenge_id": opaque_id(challenge.record.record_id, "challenge"),
        "patch_id": opaque_id(p["patch_id"], "patch"),
        "revision": revision(p["patch_revision"]),
        "decision_choices": ["APPROVE", "REJECT"] if p["state"] == "OPEN" else [],
        "expires_at": timestamp(p["expires_at"]),
        "decision_nonce": nonce,
    }


def approval_decision_view(ctx, challenge, patch):
    ctx.require(challenge)
    ctx.require(patch)
    p = challenge.payload
    if p["decision"] not in {None, "APPROVE", "REJECT"}:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return {
        "challenge_id": opaque_id(challenge.record_id, "challenge"),
        "patch_id": opaque_id(patch.record_id, "patch"),
        "revision": revision(patch.revision),
        "decision": p["decision"],
        "state": PatchState(patch.payload["state"]).value,
        "decided_at": timestamp(p["decided_at"], nullable=True),
    }


def commit_activation_view(ctx, patch, *, proof_id, verification):
    ctx.require(patch)
    if verification not in _VERIFICATION:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return {
        "patch_id": opaque_id(patch.record_id, "patch"),
        "revision": revision(patch.revision),
        "state": PatchState(patch.payload["state"]).value,
        "proof_id": None if proof_id is None else opaque_id(proof_id, "proof"),
        "verification_status": verification,
    }


def review_case_view(ctx, record):
    ctx.require(record)
    p = record.payload
    sharing = record.kind is RecordKind.SHARING
    if p["state"] not in (
        {"DOMAIN_REVIEW_REQUIRED"} if sharing else {"OPEN", "CLAIMED", "DECIDED"}
    ):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    summary, changed = ctx.text(
        p["deidentified_summary"] if sharing else p["bounded_summary"], 1024
    )
    return {
        "case_id": opaque_id(record.record_id, "sharing" if sharing else "case"),
        "state": p["state"],
        "bounded_summary": summary,
        "allowed_actions": []
        if sharing or changed or p["state"] == "DECIDED"
        else ["review-claim"]
        if p["state"] == "OPEN"
        else ["review-decision"],
    }


def verified_answer_view(ctx, answer: NativeVerifiedAnswer, *, citations):
    ctx.require()
    if (
        type(answer) is not NativeVerifiedAnswer
        or answer.status not in {"VERIFIED", "UNVERIFIED"}
        or len(citations) > 40
    ):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    text, changed = ctx.text(answer.answer, 65536)
    verified = answer.status == "VERIFIED" and not changed
    return {
        "answer": UNKNOWN_ANSWER if changed else text,
        "status": "VERIFIED" if verified else "UNVERIFIED",
        "citations": [
            {"evidence_id": opaque_id(value, "evidence")} for value in citations
        ]
        if verified
        else [],
        "memory_context_used": answer.memory_context_used is True,
        "review_required": not verified or answer.review_required is True,
    }


def migration_plan_view(ctx, plan):
    ctx.require()
    label, changed = ctx.text(
        plan.target_label,
        64,
        extra=(
            plan.target.host,
            plan.target.address,
            plan.target.database,
            plan.target.migrator_role,
            plan.target.application_role,
        ),
    )
    if changed:
        label = "Disposable target"
    if not re.fullmatch(r"plan_[a-z0-9]{16,64}", plan.plan_id):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return {
        "plan_id": plan.plan_id,
        "mode": "C5_DISPOSABLE",
        "target_label": label,
        "schema_version": "1",
        "change_count": len(plan.units),
        "authorization_state": "REQUIRES_EXPLICIT_ADMISSION",
        "executable": False,
    }
