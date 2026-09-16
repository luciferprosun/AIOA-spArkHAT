"""Consent in the existing native learning store; no independent writer/store."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta

from runtime.core_admission import Capability
from runtime.critical_loop.redaction import redact_secret_text
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    ensure_utc,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.learning.personal_contracts import (
    ConsentMode,
    PersonalDeltaPolicy,
)
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
)
from runtime.mission.contracts import MissionError


class PersonalDeltaAccess:
    def __init__(self, learning, policy):
        if (
            type(policy) is not PersonalDeltaPolicy
            or policy.scope != learning.policy.owner_scope
        ):
            raise MissionError("PERSONAL_DELTA_SCOPE_MISMATCH")
        reader = learning.native.core.local_operator(Capability.READ)
        if (
            not set(policy.allowed_domain_hats) <= reader.hat_ids
            or learning.policy.domain_hat not in policy.allowed_domain_hats
            or policy.semantics is not None
            and (
                policy.semantics.domain_hat != learning.policy.domain_hat
                or policy.semantics.task_signature != learning.policy.task_signature
            )
        ):
            raise MissionError("PERSONAL_DELTA_HAT_MISMATCH")
        self.learning, self.policy = learning, policy

    def _read(self, tx):
        row = tx.get(RecordKind.LEARNING, self.policy.consent_ref)
        if row is not None:
            row.verify()
            if (
                row.scope != self.policy.scope
                or row.payload.get("state") != "CONSENT"
                or row.payload.get("domain_hat") != self.policy.consent_anchor_hat
                or row.payload.get("personal_space_ref")
                != self.policy.personal_space_ref
                or row.payload.get("execution_authority") is not False
                or row.payload.get("publication_authority") is not False
                or row.payload.get("privacy_scope") != "PRIVATE"
                or row.payload.get("history_policy") != self.policy.history_policy
            ):
                raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        return row

    def reason(self, tx, *, write=False):
        row = self._read(tx)
        if row is None:
            return "CONSENT_OFF"
        p = row.payload
        if p["mode"] == ConsentMode.OFF.value:
            return "CONSENT_OFF"
        now = self.learning.now()
        if (
            not datetime.fromisoformat(p["granted_at"])
            <= now
            < datetime.fromisoformat(p["expires_at"])
        ):
            return "CONSENT_EXPIRED"
        if self.learning.policy.domain_hat not in p["allowed_domain_hats"]:
            return "CONSENT_HAT_DENIED"
        if p["mode"] == ConsentMode.MANUAL.value:
            return "MANUAL_OWNER_APPROVAL_REQUIRED" if write else None
        if p["mode"] != ConsentMode.AUTO_VERIFIED_SCOPED.value:
            return "CONSENT_INVALID"
        return None

    def allowed(self, *, write=False):
        return self.learning.run(lambda tx: self.reason(tx, write=write)) is None

    def require_write(self, tx):
        if self.reason(tx, write=True) is not None:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)

    def describe(self):
        row = self.learning.run(self._read)
        return {
            "personal_space_ref": self.policy.personal_space_ref,
            "mode": "OFF" if row is None else row.payload["mode"],
            "revision": 0 if row is None else row.revision,
            "automatic_write_allowed": self.allowed(write=True),
            "history_policy": self.policy.history_policy,
            "execution_authority": False,
        }

    def set_consent(
        self, principal, mode, *, expected_revision, allowed_hats=(), expires_at=None
    ):
        """Explicit admitted owner operation. Never called from an actor path.

        This grants only future independently verified advisory delta writes.
        MANUAL patch approval/commit/activation continues through NativeOwnerApproval.
        Revocation replaces one record even when the learning quota is full.
        """
        core = self.learning.native.core
        core.require(principal, Capability.OWNER_APPROVAL, scope=self.policy.scope)
        if (
            type(mode) is not ConsentMode
            or type(expected_revision) is not int
            or expected_revision < 0
        ):
            raise MissionError("INVALID_CONSENT_DECISION")
        if (
            type(allowed_hats) is not tuple
            or len(set(allowed_hats)) != len(allowed_hats)
            or not set(allowed_hats) <= set(self.policy.allowed_domain_hats)
        ):
            raise MissionError("CONSENT_HAT_DENIED")
        now = self.learning.now()
        if mode is not ConsentMode.OFF:
            if not allowed_hats or expires_at is None:
                raise MissionError("BOUNDED_CONSENT_REQUIRED")
            expires_at = ensure_utc(expires_at)
            if not now < expires_at <= now + timedelta(days=365):
                raise MissionError("BOUNDED_CONSENT_REQUIRED")
        else:
            allowed_hats, expires_at = (), now
        manager = core.local_operator(Capability.MANAGE)

        def update(tx):
            core.require(principal, Capability.OWNER_APPROVAL, scope=self.policy.scope)
            prior = self._read(tx)
            if (0 if prior is None else prior.revision) != expected_revision:
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            if prior is None and mode is not ConsentMode.OFF:
                self.learning._check_quota(tx, 1)
            payload = {
                "state": "CONSENT",
                "mode": mode.value,
                "domain_hat": self.policy.consent_anchor_hat,
                "personal_space_ref": self.policy.personal_space_ref,
                "allowed_domain_hats": tuple(sorted(allowed_hats)),
                "granted_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "history_policy": self.policy.history_policy,
                "previous_digest": None if prior is None else prior.payload_digest,
                "owner_decision_ref": canonical_sha256(
                    (principal.scope, expected_revision + 1, now, mode)
                ),
                "privacy_scope": "PRIVATE",
                "execution_authority": False,
                "publication_authority": False,
            }
            record = StoredRecord(
                RecordKind.LEARNING,
                self.policy.consent_ref,
                self.policy.scope,
                expected_revision + 1,
                payload,
            )
            if prior is None:
                tx.insert(record)
            else:
                tx.replace(record, expected_revision=expected_revision)
            return {
                "mode": mode.value,
                "revision": record.revision,
                "decision_ref": payload["owner_decision_ref"],
            }

        return self.learning.native.transactions.run(
            TransactionContext(manager, Capability.MANAGE), update
        )

    def canonical_claim(self, claim, sources):
        rule = self.policy.semantics
        if rule is None:
            return claim
        return rule.canonical_claim(
            claim,
            scope=self.policy.scope,
            hat=self.learning.policy.domain_hat,
            task=self.learning.policy.task_signature,
            versions=tuple((r[0], r[1]) for r in sources),
            at=self.learning.now(),
        )

    def require_clean(self, *values):
        secrets = self.learning.native.dependencies.private_values

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, Mapping):
                for key, child in value.items():
                    yield str(key)
                    yield from strings(child)
            elif isinstance(value, (tuple, list)):
                for child in value:
                    yield from strings(child)

        for text in strings(values):
            if redact_secret_text(text, known_secrets=secrets) != text:
                raise MissionError("FORBIDDEN_SECRET_MATERIAL")
