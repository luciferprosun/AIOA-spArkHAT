"""Core-owned local authority normalization; no login, environment or credentials.

Only the admitted Core CLI/HTTP composition calls ``local_operator``. Domain
services receive its sealed, single-purpose principal, never an operator flag.
The seal is process-local: it authenticates this boundary's immutable decision,
and is neither a reusable session token nor a new credential store.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable


class AdmissionError(ValueError):
    """A fixed, transport-safe denial with no caller data."""

    def __init__(self) -> None:
        super().__init__("CORE_ADMISSION_DENIED")


class Capability(str, Enum):
    READ = "read"
    CANDIDATE = "candidate"
    PROPOSE = "propose"
    VALIDATE = "validate"
    OWNER_APPROVAL = "owner_approval"
    COMMIT = "commit"
    ACTIVATE = "activate"
    MANAGE = "manage"
    REVIEW = "review"
    EVIDENCE_CAPTURE = "evidence_capture"
    MIGRATE = "migrate"


class CoreActor(str, Enum):
    OWNER_HUMAN = "owner_human"
    HUMAN_REVIEWER = "human_reviewer"
    COMMIT_SERVICE = "commit_service"
    CRITIC = "critic"


def _identity(value: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 256
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise AdmissionError()


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AdmissionError()
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True, repr=False)
class OwnerScope:
    tenant_id: str
    owner_id: str
    space_id: str
    slot_id: str

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.owner_id, self.space_id, self.slot_id):
            _identity(value)

    def binding(self) -> tuple[str, str, str, str]:
        return self.tenant_id, self.owner_id, self.space_id, self.slot_id


@dataclass(frozen=True, slots=True, repr=False)
class LocalOwnerAssignment:
    """Explicit Core configuration, supplied by its operator, never from JSON/env."""

    scope: OwnerScope
    allowed_capabilities: frozenset[Capability]
    hat_ids: frozenset[str]
    model_binding_ids: frozenset[str]
    revision: int = 1
    operator_approved: bool = False
    hosted_multi_user: bool = False

    def __post_init__(self) -> None:
        if type(self.scope) is not OwnerScope:
            raise AdmissionError()
        if self.operator_approved is not True or self.hosted_multi_user is not False:
            raise AdmissionError()
        if type(self.revision) is not int or self.revision < 1:
            raise AdmissionError()
        for name in ("allowed_capabilities", "hat_ids", "model_binding_ids"):
            values = getattr(self, name)
            if (
                not isinstance(values, (set, frozenset, tuple))
                or not 1 <= len(values) <= 128
            ):
                raise AdmissionError()
            object.__setattr__(self, name, frozenset(values))
        if any(type(value) is not Capability for value in self.allowed_capabilities):
            raise AdmissionError()
        for value in (*self.hat_ids, *self.model_binding_ids):
            _identity(value)


@dataclass(frozen=True, slots=True, repr=False)
class CorePrincipal:
    scope: OwnerScope
    capability: Capability
    actor: CoreActor
    actor_session_id: str
    assignment_revision: int
    hat_ids: frozenset[str]
    model_binding_ids: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    _seal: bytes = field(default=b"", repr=False, compare=False)


class CoreAdmission:
    """One Core composition owns this boundary and every principal it admits."""

    def __init__(
        self,
        assignment: LocalOwnerAssignment | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if assignment is not None and type(assignment) is not LocalOwnerAssignment:
            raise AdmissionError()
        self._assignment = assignment
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._seal_key = secrets.token_bytes(32)
        self._session = secrets.token_hex(32)
        self._closed = False

    @property
    def configured(self) -> bool:
        return self._assignment is not None and not self._closed

    def _signature(self, principal: CorePrincipal) -> bytes:
        body = [
            list(principal.scope.binding()),
            principal.capability.value,
            principal.actor.value,
            principal.actor_session_id,
            principal.assignment_revision,
            sorted(principal.hat_ids),
            sorted(principal.model_binding_ids),
            principal.issued_at.isoformat(),
            principal.expires_at.isoformat(),
        ]
        return hmac.digest(
            self._seal_key,
            json.dumps(body, separators=(",", ":")).encode(),
            hashlib.sha256,
        )

    def local_operator(self, capability: Capability) -> CorePrincipal:
        """Called after the existing Core transport has admitted its local operator."""
        actor = CoreActor.OWNER_HUMAN
        if capability in (Capability.COMMIT, Capability.ACTIVATE):
            actor = CoreActor.COMMIT_SERVICE
        elif capability is Capability.REVIEW:
            actor = CoreActor.HUMAN_REVIEWER
        return self._issue(capability, actor)

    def critic_candidate(self) -> CorePrincipal:
        """Core's Critic adapter obtains candidate purpose only, never owner approval."""
        return self._issue(Capability.CANDIDATE, CoreActor.CRITIC)

    def _issue(self, capability: Capability, actor: CoreActor) -> CorePrincipal:
        assignment = self._assignment
        if (
            self._closed
            or assignment is None
            or type(capability) is not Capability
            or capability not in assignment.allowed_capabilities
        ):
            raise AdmissionError()
        stamp = _utc(self._clock())
        principal = CorePrincipal(
            assignment.scope,
            capability,
            actor,
            self._session,
            assignment.revision,
            assignment.hat_ids,
            assignment.model_binding_ids,
            stamp,
            stamp + timedelta(minutes=5),
        )
        object.__setattr__(principal, "_seal", self._signature(principal))
        return principal

    def require(
        self,
        principal: CorePrincipal,
        capability: Capability,
        *,
        scope: OwnerScope | None = None,
    ) -> OwnerScope:
        try:
            assignment = self._assignment
            if (
                self._closed
                or assignment is None
                or type(principal) is not CorePrincipal
                or type(capability) is not Capability
                or principal.capability is not capability
                or principal.scope != assignment.scope
                or (scope is not None and principal.scope != scope)
                or principal.assignment_revision != assignment.revision
                or principal.actor_session_id != self._session
                or principal.hat_ids != assignment.hat_ids
                or principal.model_binding_ids != assignment.model_binding_ids
                or capability not in assignment.allowed_capabilities
                or not principal.issued_at <= _utc(self._clock()) < principal.expires_at
                or not hmac.compare_digest(principal._seal, self._signature(principal))
            ):
                raise AdmissionError()
            if (
                capability is Capability.OWNER_APPROVAL
                and principal.actor is not CoreActor.OWNER_HUMAN
            ):
                raise AdmissionError()
            if (
                principal.actor is CoreActor.CRITIC
                and capability is not Capability.CANDIDATE
            ):
                raise AdmissionError()
            return principal.scope
        except (AttributeError, TypeError, ValueError, OverflowError) as error:
            raise AdmissionError() from error

    def close(self) -> None:
        self._closed = True
        self._seal_key = b""
