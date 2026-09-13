"""Pure target/plan/admission contracts. The C4 executor always denies DDL.

No environment reading, driver loading, name resolution or connection belongs
here. A future controller must connect to precisely the admitted identity.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import unquote, urlsplit

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    require_sha256_hex,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError

COCKROACH_COMPAT_VERSION = "v26.2.5"
MIGRATION_MODE = "C5_DISPOSABLE"
CANARY_CATEGORIES = frozenset(
    {"hostname", "database", "cluster_marker", "account_id", "resource_arn"}
)
_ROLE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_DATABASE = re.compile(r"^aioa_disposable_[a-z0-9_]{1,46}$")


def _deny() -> None:
    raise MemoryPatchError(ErrorCode.TARGET_DENIED)


def canonical_host(value: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(c in value for c in "/\\@%,?#\x00")
    ):
        _deny()
    if value.endswith("."):
        value = value[:-1]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        try:
            host = value.lower().encode("idna").decode("ascii")
        except UnicodeError:
            _deny()
        if len(host) > 253 or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        ):
            _deny()
        return host


def canary_fingerprint(category: str, value: str) -> str:
    if category not in CANARY_CATEGORIES or type(value) is not str or not value:
        _deny()
    if category == "hostname":
        value = canonical_host(value)
    elif category in {"database", "cluster_marker"}:
        value = value.strip().lower()
    elif category == "account_id":
        if not re.fullmatch(r"[0-9]{12}", value):
            _deny()
    elif category == "resource_arn":
        value = value.strip().strip("\"'")
        if not value.startswith("arn:") or len(value) > 2048:
            _deny()
    return hashlib.sha256(
        ("jury-canary-v1\0" + category + "\0" + value).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class JuryDenylist:
    fingerprints: frozenset[tuple[str, str]]

    def __post_init__(self) -> None:
        if (
            type(self.fingerprints) is not frozenset
            or {category for category, _ in self.fingerprints} != CANARY_CATEGORIES
        ):
            _deny()
        for _, digest in self.fingerprints:
            require_sha256_hex(digest, "canary fingerprint")

    @classmethod
    def from_manifest(cls, manifest: Mapping) -> JuryDenylist:
        if (
            manifest.get("schema") != "jury-canary-v1"
            or type(manifest.get("fingerprints")) is not list
        ):
            _deny()
        try:
            return cls(
                frozenset(
                    (item["category"], item["sha256"])
                    for item in manifest["fingerprints"]
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise MemoryPatchError(ErrorCode.TARGET_DENIED) from error

    def require_clear(self, target: TargetIdentity) -> None:
        values = [
            ("hostname", target.host),
            ("hostname", target.address),
            ("database", target.database),
            ("cluster_marker", target.cluster_marker),
        ]
        values += [("account_id", value) for value in target.account_ids]
        values += [("resource_arn", value) for value in target.resource_arns]
        # Test complete hostname-label prefixes, never a substring of a digest.
        labels = target.host.split(".")[0].split("-")
        values += [
            ("cluster_marker", "-".join(labels[:end]))
            for end in range(1, len(labels) + 1)
        ]
        if any(
            (category, canary_fingerprint(category, value)) in self.fingerprints
            for category, value in values
        ):
            _deny()


@dataclass(frozen=True, slots=True, repr=False)
class TargetIdentity:
    host: str
    address: str
    port: int
    database: str
    cluster_marker: str
    application_role: str
    migrator_role: str
    certificate_fingerprint: str
    account_ids: tuple[str, ...] = ()
    resource_arns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "host", canonical_host(self.host))
        try:
            address = str(ipaddress.ip_address(self.address))
        except ValueError as error:
            raise MemoryPatchError(ErrorCode.TARGET_DENIED) from error
        object.__setattr__(self, "address", address)
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            _deny()
        if type(self.database) is not str or not _DATABASE.fullmatch(self.database):
            _deny()
        if type(self.cluster_marker) is not str or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,127}", self.cluster_marker
        ):
            _deny()
        for role in (self.application_role, self.migrator_role):
            if (
                type(role) is not str
                or not _ROLE.fullmatch(role)
                or role in {"root", "admin", "node", "public"}
            ):
                _deny()
        if self.application_role == self.migrator_role:
            _deny()
        require_sha256_hex(self.certificate_fingerprint, "certificate identity")
        if (
            type(self.account_ids) is not tuple
            or type(self.resource_arns) is not tuple
            or len(self.account_ids) > 8
            or len(self.resource_arns) > 8
        ):
            _deny()
        for value in self.account_ids:
            canary_fingerprint("account_id", value)
        for value in self.resource_arns:
            canary_fingerprint("resource_arn", value)
        if self.host in {"localhost", "127.0.0.1", "::1"}:
            if address not in {"127.0.0.1", "::1"} or (
                self.host != "localhost" and self.host != address
            ):
                _deny()

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self)


def parse_target_uri(uri: str, **identity_metadata) -> TargetIdentity:
    """Metadata URI only: passwords/userinfo and all connection options are denied.

    The actual future connection uses TargetIdentity plus a Core-owned opaque
    credential handle, never this URI or an ambient service/connection string.
    """
    try:
        if type(uri) is not str or len(uri) > 4096 or any(ord(c) < 33 for c in uri):
            _deny()
        parsed = urlsplit(uri)
        if (
            parsed.scheme not in {"postgresql", "postgres"}
            or not parsed.hostname
            or parsed.port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(c in parsed.netloc for c in "%@,\\")
            or not parsed.path.startswith("/")
            or parsed.path.count("/") != 1
        ):
            _deny()
        database = unquote(parsed.path[1:], errors="strict")
        if any(c in database for c in "%/\\@,;?=#\x00"):
            _deny()
        return TargetIdentity(
            host=parsed.hostname,
            port=parsed.port,
            database=database,
            **identity_metadata,
        )
    except (TypeError, ValueError, UnicodeError) as error:
        raise MemoryPatchError(ErrorCode.TARGET_DENIED) from error


@dataclass(frozen=True, slots=True, repr=False)
class TargetAllowlist:
    target_fingerprints: frozenset[str]
    approved_disposable_hosts: frozenset[tuple[str, str]] = frozenset()

    def require_allowed(self, target: TargetIdentity) -> None:
        if target.fingerprint not in self.target_fingerprints:
            _deny()
        if (
            target.host not in {"localhost", "127.0.0.1", "::1"}
            and (target.host, target.address) not in self.approved_disposable_hosts
        ):
            _deny()


@dataclass(frozen=True, slots=True)
class MigrationUnit:
    ordinal: int
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= 18:
            _deny()
        if (
            type(self.path) is not str
            or not re.fullmatch(r"[0-9]{4}_[a-z0-9_]+\.sql", self.path)
            or not self.path.startswith(f"{self.ordinal:04d}_")
        ):
            _deny()
        require_sha256_hex(self.sha256, "migration identity")


@dataclass(frozen=True, slots=True, repr=False)
class MigrationPlan:
    plan_id: str
    target: TargetIdentity
    target_label: str
    before_schema_fingerprint: str
    expected_schema_fingerprint: str
    units: tuple[MigrationUnit, ...]
    schema_version: str = "1"
    mode: str = MIGRATION_MODE
    compatibility_version: str = COCKROACH_COMPAT_VERSION

    def __post_init__(self) -> None:
        if not re.fullmatch(r"plan_[a-z0-9]{16,64}", self.plan_id):
            _deny()
        if type(self.target) is not TargetIdentity or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9 _-]{0,63}", self.target_label
        ):
            _deny()
        for digest in (
            self.before_schema_fingerprint,
            self.expected_schema_fingerprint,
        ):
            require_sha256_hex(digest, "schema identity")
        if type(self.units) is not tuple or not 1 <= len(self.units) <= 18:
            _deny()
        if any(type(unit) is not MigrationUnit for unit in self.units) or tuple(
            unit.ordinal for unit in self.units
        ) != tuple(range(1, len(self.units) + 1)):
            _deny()
        if (
            self.mode != MIGRATION_MODE
            or self.compatibility_version != COCKROACH_COMPAT_VERSION
            or self.schema_version != "1"
        ):
            _deny()

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True, repr=False)
class MigrationAuthorization:
    authorization_id: str
    plan_fingerprint: str
    target_fingerprint: str
    schema_fingerprint: str
    actor_session_id: str
    scope_binding: tuple[str, str, str, str]
    disposable_ownership_confirmed: bool
    expires_at: datetime
    _seal: bytes = field(default=b"", repr=False)


class MigrationAdmission:
    """An explicit operator can approve a pure plan. Approval does not execute it."""

    def __init__(
        self,
        core: CoreAdmission,
        allowlist: TargetAllowlist,
        denylist: JuryDenylist,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._core = core
        self._allowlist = allowlist
        self._denylist = denylist
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._key = secrets.token_bytes(32)
        self._consumed: set[str] = set()
        self._authorization_lock = threading.Lock()

    def check_target(self, target: TargetIdentity) -> None:
        self._allowlist.require_allowed(target)
        self._denylist.require_clear(target)

    def _signature(self, authorization: MigrationAuthorization) -> bytes:
        digest = canonical_sha256(authorization, exclude_fields=("_seal",))
        return hmac.digest(self._key, digest.encode(), "sha256")

    def admit(
        self,
        principal: CorePrincipal,
        plan: MigrationPlan,
        *,
        disposable_ownership_confirmed: bool,
    ) -> MigrationAuthorization:
        scope = self._core.require(principal, Capability.MIGRATE)
        self.check_target(plan.target)
        if disposable_ownership_confirmed is not True:
            raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
        authorization = MigrationAuthorization(
            "migration_" + secrets.token_hex(16),
            plan.fingerprint,
            plan.target.fingerprint,
            plan.before_schema_fingerprint,
            principal.actor_session_id,
            scope.binding(),
            True,
            self._clock() + timedelta(minutes=5),
        )
        return replace(authorization, _seal=self._signature(authorization))

    def consume(
        self,
        principal: CorePrincipal,
        plan: MigrationPlan,
        authorization: MigrationAuthorization,
        *,
        observed_schema_fingerprint: str,
    ) -> None:
        scope = self._core.require(principal, Capability.MIGRATE)
        self.check_target(plan.target)
        if (
            type(authorization) is not MigrationAuthorization
            or authorization.authorization_id in self._consumed
            or authorization.plan_fingerprint != plan.fingerprint
            or authorization.target_fingerprint != plan.target.fingerprint
            or authorization.schema_fingerprint != observed_schema_fingerprint
            or observed_schema_fingerprint != plan.before_schema_fingerprint
            or authorization.scope_binding != scope.binding()
            or authorization.actor_session_id != principal.actor_session_id
            or authorization.disposable_ownership_confirmed is not True
            or self._clock() >= authorization.expires_at
            or not hmac.compare_digest(
                authorization._seal, self._signature(authorization)
            )
        ):
            raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
        with self._authorization_lock:
            if authorization.authorization_id in self._consumed:
                raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
            self._consumed.add(authorization.authorization_id)


class DenyOnlyMigrationExecutor:
    """C4 has no driver or DDL implementation, even after valid plan admission."""

    def execute(self, *args, **kwargs) -> None:
        raise MemoryPatchError(ErrorCode.MIGRATION_DENIED)
