#!/usr/bin/env python3
"""Prove the existing Day 15 deployment role and create its local profile alias.

This bootstrap is intentionally narrower than the G10 AWS preflight.  It selects one
already-configured source credential chain, proves the reviewed existing deployment
role with STS, and only then creates the local ``aioa-day15-deployer`` profile alias.
It never creates IAM authority, persists temporary credentials, discovers workload
resources, or emits identity-bearing values to stdout.
"""

from __future__ import annotations

import argparse
import configparser
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

from botocore.config import Config

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.day15.g10_candidate import (  # noqa: E402
    DEPLOYMENT_PROFILE,
    DEPLOYMENT_ROLE_LEAF,
    REGION,
)
from scripts.day15.validate_template import canonical_json  # noqa: E402

DEFAULT_AWS_CONFIG: Final = Path.home() / ".aws" / "config"
DEFAULT_PRIVATE_RECEIPT: Final = ROOT / ".aioa-private" / "day15-authority-bootstrap.json"
ROLE_SESSION_NAME: Final = "aioa-day15-operator-bootstrap"
ASSUME_ROLE_DURATION_SECONDS: Final = 900
CONNECT_TIMEOUT_SECONDS: Final = 3
READ_TIMEOUT_SECONDS: Final = 10
TOTAL_MAX_ATTEMPTS: Final = 1
PHASE1_TAG: Final = "phase1-foundation-green"
EXPECTED_PHASE1_TAG: Final = "ced6e2a180dd50a1f43d4037bb8db5f4dc792657"
MAX_CONFIG_BYTES: Final = 262_144
MAX_RECEIPT_BYTES: Final = 65_536

PROFILE_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}$")
ACCOUNT_PATTERN: Final = re.compile(r"^[0-9]{12}$")
IAM_ROLE_ARN_PATTERN: Final = re.compile(
    r"^arn:aws:iam::(?P<account>[0-9]{12}):role/"
    r"(?P<name>[A-Za-z0-9+=,.@_/-]{1,512})$"
)
ASSUMED_ROLE_ARN_PATTERN: Final = re.compile(
    r"^arn:aws:sts::(?P<account>[0-9]{12}):assumed-role/"
    r"(?P<name>[A-Za-z0-9+=,.@_/-]{1,512})/"
    r"(?P<session>[A-Za-z0-9+=,.@_-]{1,128})$"
)
IAM_USER_ARN_PATTERN: Final = re.compile(
    r"^arn:aws:iam::(?P<account>[0-9]{12}):user/"
    r"(?P<name>[A-Za-z0-9+=,.@_/-]{1,512})$"
)
FEDERATED_USER_ARN_PATTERN: Final = re.compile(
    r"^arn:aws:sts::(?P<account>[0-9]{12}):federated-user/"
    r"(?P<name>[A-Za-z0-9+=,.@_/-]{1,512})$"
)
ROOT_ARN_PATTERN: Final = re.compile(r"^arn:aws:iam::(?P<account>[0-9]{12}):root$")
NONCE_PATTERN: Final = re.compile(r"^[0-9a-f]{32,128}$")
REASON_PATTERN: Final = re.compile(r"^[A-Z0-9_:.-]{1,160}$")
CONFIG_KEY_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*$")
STATIC_CREDENTIAL_KEYS: Final = frozenset(
    {
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "aws_security_token",
    }
)
SAFE_EXACT_SOURCE_ALIAS_KEYS: Final = frozenset(
    {
        "credential_process",
        "credential_source",
        "duration_seconds",
        "external_id",
        "mfa_serial",
        "output",
        "region",
        "role_arn",
        "role_session_name",
        "source_profile",
        "sso_account_id",
        "sso_region",
        "sso_role_name",
        "sso_session",
        "sso_start_url",
        "web_identity_token_file",
    }
)
FORBIDDEN_PROFILE_ENDPOINT_KEYS: Final = frozenset({"endpoint_url", "services"})
SELECTION_METHODS: Final = frozenset({"EXPLICIT_ENVIRONMENT_PROFILE", "UNIQUE_LOCAL_PROFILE"})
PUBLIC_REASON_CODES: Final = frozenset(
    {
        "ASSUMED_ROLE_IDENTITY_MISMATCH",
        "ASSUME_ROLE_RESPONSE_INVALID",
        "AUTHORITY_BOOTSTRAP_INTERNAL_FAILURE",
        "AWS_CONFIG_ACTIVE_PATH_MISMATCH",
        "AWS_CONFIG_CHANGED_DURING_BOOTSTRAP",
        "AWS_ENDPOINT_OVERRIDE_FORBIDDEN",
        "AWS_CONFIG_INVALID",
        "AWS_CONFIG_PROFILE_UNSAFE",
        "AWS_CONFIG_PROTECTION_INVALID",
        "AWS_CONFIG_UNAVAILABLE",
        "BOOTSTRAP_CLOCK_INVALID",
        "BOOTSTRAP_IN_PROGRESS",
        "BOOTSTRAP_NONCE_INVALID",
        "CONFIGURED_PROFILE_NAME_INVALID",
        "DEPLOYMENT_PROFILE_ALIAS_AUTHENTICATION_REQUIRED",
        "DEPLOYMENT_PROFILE_ALIAS_IDENTITY_MISMATCH",
        "EXACT_DEPLOYMENT_ROLE_NOT_ASSUMABLE",
        "EXPLICIT_SOURCE_PROFILE_UNAVAILABLE",
        "LOCAL_PATH_INVALID",
        "LOCAL_PATH_SYMLINK_FORBIDDEN",
        "LOCAL_PROFILE_ALIAS_CONFLICT",
        "LOCAL_PROFILE_ALIAS_REVERIFY_FAILED",
        "LOCAL_PROFILE_ALIAS_ROLLBACK_CONFLICT",
        "LOCAL_PROFILE_ALIAS_ROLLBACK_FAILED",
        "PRIVATE_RECEIPT_ALREADY_EXISTS_INVALID",
        "PRIVATE_RECEIPT_BACKUP_CONFLICT",
        "PRIVATE_RECEIPT_GIT_CHECK_FAILED",
        "PRIVATE_RECEIPT_IGNORED_PATH_REQUIRED",
        "PRIVATE_RECEIPT_MODE_INVALID",
        "PRIVATE_RECEIPT_PATH_COLLISION",
        "PRIVATE_RECEIPT_PROTECTION_INVALID",
        "PRIVATE_RECEIPT_REPOSITORY_PATH_FORBIDDEN",
        "PRIVATE_RECEIPT_TOO_LARGE",
        "PRIVATE_RECEIPT_WRITE_FAILED",
        "PRIVATE_AUTHORITY_RECEIPT_SCHEMA_INVALID",
        "PRIVATE_AUTHORITY_RECEIPT_STATUS_INVALID",
        "PROFILE_AMBIGUOUS",
        "REPOSITORY_BRANCH_INVALID",
        "REPOSITORY_GIT_UNAVAILABLE",
        "REPOSITORY_MAIN_NOT_ORIGIN_MAIN",
        "REPOSITORY_PHASE1_TAG_DRIFT",
        "REPOSITORY_WORKTREE_NOT_CLEAN",
        "ROOT_SOURCE_PRINCIPAL_FORBIDDEN",
        "SANITIZED_AUTHORITY_RECEIPT_SCHEMA_INVALID",
        "SANITIZED_AUTHORITY_RECEIPT_STATUS_INVALID",
        "SOURCE_PROFILE_AUTHENTICATION_REQUIRED",
        "SOURCE_PROFILE_CONFIG_REQUIRED",
        "SOURCE_PROFILE_ALIAS_AUTHORITY_UNPROVEN",
        "SOURCE_PROFILE_REQUIRED",
        "SOURCE_SESSION_PROFILE_MISMATCH",
        "STS_IDENTITY_RESPONSE_INVALID",
        "TEMPORARY_ROLE_IDENTITY_UNAVAILABLE",
        "TEMPORARY_ROLE_SESSION_UNAVAILABLE",
    }
)
PRIVATE_RECEIPT_KEYS: Final = frozenset(
    {
        "direct_sts_operations",
        "authority",
        "aws_state_changed",
        "checks",
        "credentials_persisted",
        "iam_role_created",
        "local_profile_state_changed",
        "local_profile_write_operations",
        "observed_at",
        "receipt_nonce",
        "reasons",
        "region",
        "schema_version",
        "selection",
        "status",
    }
)
AUTHORITY_KEYS: Final = frozenset(
    {"expected_account_id", "deployment_profile", "deployment_role_arn"}
)
SELECTION_KEYS: Final = frozenset({"ambiguous", "method", "source_profile"})
CHECK_KEYS: Final = frozenset(
    {
        "alias_created",
        "alias_reverified",
        "assume_role_performed",
        "exact_deployment_role_proven",
        "source_identity_verified",
        "source_profile_selected",
        "temporary_assumed_identity_verified",
    }
)
SANITIZED_KEYS: Final = frozenset(
    {
        "aws_state_changed",
        "credentials_persisted",
        "exact_deployment_role_proven",
        "iam_role_created",
        "local_profile_alias_created",
        "local_profile_alias_reverified",
        "private_receipt_created",
        "reasons",
        "sanitized",
        "schema_version",
        "source_identity_verified",
        "source_profile_ambiguous",
        "source_profile_selected",
        "status",
        "sts_assume_role_performed",
        "temporary_assumed_identity_verified",
    }
)
PUBLIC_BOOLEAN_KEYS: Final = SANITIZED_KEYS - {"reasons", "schema_version", "status"}


class AwsSession(Protocol):
    """Narrow session surface used by the bootstrap."""

    profile_name: str | None

    def client(
        self,
        service_name: str,
        *,
        region_name: str,
        config: Config,
    ) -> Any: ...


class SessionFactory(Protocol):
    def __call__(self, profile_name: str) -> AwsSession: ...


class TemporarySessionFactory(Protocol):
    def __call__(self, credentials: Mapping[str, str]) -> AwsSession: ...


class RepositoryGuard(Protocol):
    def __call__(self, root: Path) -> None: ...


class BootstrapFailure(RuntimeError):
    """One public-safe bootstrap failure."""

    def __init__(
        self,
        reason: str,
        *,
        status: str = "BLOCKED",
        local_profile_changed: bool = False,
    ) -> None:
        self.reason = reason
        self.status = status
        self.local_profile_changed = local_profile_changed
        super().__init__(reason)


@dataclass(slots=True)
class _State:
    observed_at: str
    receipt_nonce: str
    status: str = "BLOCKED"
    reasons: list[str] = field(default_factory=list)
    selection_method: str = "NONE"
    source_profile: str | None = None
    source_profile_ambiguous: bool = False
    source_identity_verified: bool = False
    assume_role_performed: bool = False
    temporary_identity_verified: bool = False
    exact_role_proven: bool = False
    alias_created: bool = False
    alias_reverified: bool = False
    account_id: str | None = None
    role_arn: str | None = None
    api_operations: list[dict[str, object]] = field(default_factory=list)
    local_write_operations: list[str] = field(default_factory=list)

    def reason(self, value: str, *, status: str = "BLOCKED") -> None:
        if self.reasons == ["BOOTSTRAP_IN_PROGRESS"]:
            self.reasons.clear()
        if value not in self.reasons:
            self.reasons.append(value)
        if status == "FAIL":
            self.status = "FAIL"


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _normalized_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _git_value(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ("git", *arguments),
            cwd=root,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BootstrapFailure("REPOSITORY_GIT_UNAVAILABLE", status="FAIL") from error
    if result.returncode != 0:
        raise BootstrapFailure("REPOSITORY_GIT_UNAVAILABLE", status="FAIL")
    return result.stdout.strip()


def _default_repository_guard(root: Path) -> None:
    if _git_value(root, "branch", "--show-current") != "main":
        raise BootstrapFailure("REPOSITORY_BRANCH_INVALID", status="FAIL")
    if _git_value(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise BootstrapFailure("REPOSITORY_WORKTREE_NOT_CLEAN", status="FAIL")
    if _git_value(root, "rev-parse", "HEAD") != _git_value(root, "rev-parse", "origin/main"):
        raise BootstrapFailure("REPOSITORY_MAIN_NOT_ORIGIN_MAIN", status="FAIL")
    if _git_value(root, "rev-parse", f"refs/tags/{PHASE1_TAG}^{{}}") != EXPECTED_PHASE1_TAG:
        raise BootstrapFailure("REPOSITORY_PHASE1_TAG_DRIFT", status="FAIL")


def _bounded_config() -> Config:
    return Config(
        region_name=REGION,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        read_timeout=READ_TIMEOUT_SECONDS,
        ignore_configured_endpoint_urls=True,
        retries={"mode": "standard", "total_max_attempts": TOTAL_MAX_ATTEMPTS},
    )


def _available_profiles() -> tuple[str, ...]:
    """Return profile names only without authenticating or reading provider output."""

    try:
        import botocore.session

        profiles = botocore.session.get_session().available_profiles
    except Exception:
        return ()
    return tuple(sorted({item for item in profiles if isinstance(item, str) and item}))


def select_source_profile(
    *,
    environment: Mapping[str, str],
    configured_profiles: Sequence[str],
) -> tuple[str, str]:
    """Apply the PDF's deterministic explicit-or-single-source selection rule."""

    profiles = tuple(sorted({item for item in configured_profiles if isinstance(item, str)}))
    if any(PROFILE_PATTERN.fullmatch(item) is None for item in profiles):
        raise BootstrapFailure("CONFIGURED_PROFILE_NAME_INVALID", status="FAIL")
    explicit = {
        value.strip()
        for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE")
        if (value := environment.get(name)) and value.strip()
    }
    if len(explicit) > 1:
        raise BootstrapFailure("PROFILE_AMBIGUOUS")
    if explicit:
        selected = next(iter(explicit))
        if PROFILE_PATTERN.fullmatch(selected) is None or selected not in profiles:
            raise BootstrapFailure("EXPLICIT_SOURCE_PROFILE_UNAVAILABLE")
        return selected, "EXPLICIT_ENVIRONMENT_PROFILE"

    source_candidates = tuple(item for item in profiles if item != DEPLOYMENT_PROFILE)
    if len(source_candidates) == 1:
        return source_candidates[0], "UNIQUE_LOCAL_PROFILE"
    if len(profiles) == 1:
        return profiles[0], "UNIQUE_LOCAL_PROFILE"
    if not profiles:
        raise BootstrapFailure("SOURCE_PROFILE_REQUIRED")
    raise BootstrapFailure("PROFILE_AMBIGUOUS")


def _role_arn(account_id: str) -> str:
    return f"arn:aws:iam::{account_id}:role/{DEPLOYMENT_ROLE_LEAF}"


def _identity_parts(identity: object) -> tuple[str, str]:
    if not isinstance(identity, Mapping):
        raise BootstrapFailure("STS_IDENTITY_RESPONSE_INVALID")
    account_id = identity.get("Account")
    arn = identity.get("Arn")
    if (
        not isinstance(account_id, str)
        or ACCOUNT_PATTERN.fullmatch(account_id) is None
        or not isinstance(arn, str)
    ):
        raise BootstrapFailure("STS_IDENTITY_RESPONSE_INVALID")
    root_match = ROOT_ARN_PATTERN.fullmatch(arn)
    if root_match is not None and root_match.group("account") == account_id:
        raise BootstrapFailure("ROOT_SOURCE_PRINCIPAL_FORBIDDEN")
    match = (
        IAM_ROLE_ARN_PATTERN.fullmatch(arn)
        or ASSUMED_ROLE_ARN_PATTERN.fullmatch(arn)
        or IAM_USER_ARN_PATTERN.fullmatch(arn)
        or FEDERATED_USER_ARN_PATTERN.fullmatch(arn)
    )
    if match is None or match.group("account") != account_id:
        raise BootstrapFailure("STS_IDENTITY_RESPONSE_INVALID")
    return account_id, arn


def _identity_is_exact_role(identity: object, *, account_id: str, role_arn: str) -> bool:
    try:
        observed_account, observed_arn = _identity_parts(identity)
    except BootstrapFailure:
        return False
    if observed_account != account_id:
        return False
    if observed_arn == role_arn:
        return True
    observed = ASSUMED_ROLE_ARN_PATTERN.fullmatch(observed_arn)
    return (
        observed is not None
        and observed.group("account") == account_id
        and observed.group("name") == DEPLOYMENT_ROLE_LEAF
    )


def _record_call(state: _State, operation: str) -> None:
    state.api_operations.append(
        {
            "operation": operation,
            "sequence": len(state.api_operations) + 1,
            "write": False,
        }
    )


def _sts_client(session: AwsSession, *, reason: str) -> Any:
    try:
        return session.client("sts", region_name=REGION, config=_bounded_config())
    except Exception as error:
        raise BootstrapFailure(reason) from error


def _get_identity(client: Any, state: _State, *, reason: str) -> Mapping[str, object]:
    _record_call(state, "sts:GetCallerIdentity")
    try:
        identity = client.get_caller_identity()
    except Exception as error:
        raise BootstrapFailure(reason) from error
    if not isinstance(identity, Mapping):
        raise BootstrapFailure("STS_IDENTITY_RESPONSE_INVALID")
    return identity


def _temporary_credentials(response: object) -> dict[str, str]:
    credentials = response.get("Credentials") if isinstance(response, Mapping) else None
    if not isinstance(credentials, Mapping):
        raise BootstrapFailure("ASSUME_ROLE_RESPONSE_INVALID")
    expected = {
        "aws_access_key_id": credentials.get("AccessKeyId"),
        "aws_secret_access_key": credentials.get("SecretAccessKey"),
        "aws_session_token": credentials.get("SessionToken"),
    }
    if any(not isinstance(value, str) or not value for value in expected.values()):
        raise BootstrapFailure("ASSUME_ROLE_RESPONSE_INVALID")
    return {key: str(value) for key, value in expected.items()}


def _profile_section(profile_name: str) -> str:
    return "default" if profile_name == "default" else f"profile {profile_name}"


def _reject_symlink_chain(path: Path) -> None:
    lexical = Path(os.path.abspath(path))
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise BootstrapFailure("LOCAL_PATH_INVALID", status="FAIL") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise BootstrapFailure("LOCAL_PATH_SYMLINK_FORBIDDEN", status="FAIL")


def _read_aws_config(path: Path) -> tuple[bytes, configparser.RawConfigParser]:
    _reject_symlink_chain(path)
    try:
        metadata = path.lstat()
        raw = path.read_bytes()
    except OSError as error:
        raise BootstrapFailure("AWS_CONFIG_UNAVAILABLE") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > MAX_CONFIG_BYTES
    ):
        raise BootstrapFailure("AWS_CONFIG_PROTECTION_INVALID", status="FAIL")
    try:
        text = raw.decode("utf-8")
        parser = configparser.RawConfigParser(interpolation=None, strict=True)
        parser.read_string(text)
    except (UnicodeDecodeError, configparser.Error) as error:
        raise BootstrapFailure("AWS_CONFIG_INVALID", status="FAIL") from error
    return raw, parser


def _section_mapping(
    parser: configparser.RawConfigParser,
    profile_name: str,
) -> dict[str, str] | None:
    section = _profile_section(profile_name)
    if not parser.has_section(section):
        return None
    values = {str(key).lower(): str(value) for key, value in parser.items(section, raw=True)}
    if (
        any(CONFIG_KEY_PATTERN.fullmatch(key) is None for key in values)
        or STATIC_CREDENTIAL_KEYS.intersection(values)
        or FORBIDDEN_PROFILE_ENDPOINT_KEYS.intersection(values)
        or any(
            not value or "\x00" in value or "\n" in value or "\r" in value
            for value in values.values()
        )
    ):
        raise BootstrapFailure("AWS_CONFIG_PROFILE_UNSAFE", status="FAIL")
    return values


def _expected_alias_mapping(
    parser: configparser.RawConfigParser,
    *,
    source_profile: str,
    role_arn: str,
    assume_role_performed: bool,
) -> dict[str, str]:
    if assume_role_performed:
        return {
            "duration_seconds": str(ASSUME_ROLE_DURATION_SECONDS),
            "region": REGION,
            "role_arn": role_arn,
            "role_session_name": ROLE_SESSION_NAME,
            "source_profile": source_profile,
        }
    if source_profile != DEPLOYMENT_PROFILE:
        raise BootstrapFailure("SOURCE_PROFILE_ALIAS_AUTHORITY_UNPROVEN")
    source = _section_mapping(parser, source_profile)
    if source is None:
        raise BootstrapFailure("SOURCE_PROFILE_CONFIG_REQUIRED")
    if not source or not set(source).issubset(SAFE_EXACT_SOURCE_ALIAS_KEYS):
        raise BootstrapFailure("AWS_CONFIG_PROFILE_UNSAFE", status="FAIL")
    expected = dict(source)
    expected["region"] = REGION
    return expected


def _append_alias(raw: bytes, mapping: Mapping[str, str]) -> bytes:
    prefix = raw
    if prefix and not prefix.endswith(b"\n"):
        prefix += b"\n"
    if prefix and not prefix.endswith(b"\n\n"):
        prefix += b"\n"
    lines = [f"[profile {DEPLOYMENT_PROFILE}]\n"]
    lines.extend(f"{key} = {mapping[key]}\n" for key in sorted(mapping))
    return prefix + "".join(lines).encode("utf-8")


def _append_config_alias(path: Path, *, original: bytes, updated: bytes) -> None:
    """Append one reviewed profile block without replacing concurrent config bytes."""

    if (
        not updated.startswith(original)
        or len(updated) <= len(original)
        or len(updated) > MAX_CONFIG_BYTES
    ):
        raise BootstrapFailure("LOCAL_PROFILE_ALIAS_REVERIFY_FAILED", status="FAIL")
    suffix = updated[len(original) :]
    _reject_symlink_chain(path)
    flags = os.O_RDWR | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise BootstrapFailure("AWS_CONFIG_UNAVAILABLE") from error
    profile_changed = False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > MAX_CONFIG_BYTES
        ):
            raise BootstrapFailure("AWS_CONFIG_PROTECTION_INVALID", status="FAIL")
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = MAX_CONFIG_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if b"".join(chunks) != original:
            raise BootstrapFailure("AWS_CONFIG_CHANGED_DURING_BOOTSTRAP", status="FAIL")
        written = 0
        try:
            while written < len(suffix):
                count = os.write(descriptor, suffix[written:])
                if count <= 0:
                    raise OSError("short append")
                written += count
                profile_changed = True
            os.fsync(descriptor)
        except OSError as error:
            os.lseek(descriptor, 0, os.SEEK_SET)
            observed = b""
            while len(observed) <= MAX_CONFIG_BYTES:
                chunk = os.read(descriptor, 65_536)
                if not chunk:
                    break
                observed += chunk
            restored = False
            if observed == original + suffix[:written]:
                try:
                    os.ftruncate(descriptor, len(original))
                    os.fsync(descriptor)
                    restored = True
                    profile_changed = False
                except OSError:
                    restored = False
            raise BootstrapFailure(
                "LOCAL_PROFILE_ALIAS_REVERIFY_FAILED",
                status="FAIL",
                local_profile_changed=profile_changed and not restored,
            ) from error
        os.lseek(descriptor, 0, os.SEEK_SET)
        observed_after = b""
        while len(observed_after) <= MAX_CONFIG_BYTES:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            observed_after += chunk
        if observed_after != updated:
            raise BootstrapFailure(
                "AWS_CONFIG_CHANGED_DURING_BOOTSTRAP",
                status="FAIL",
                local_profile_changed=True,
            )
    except OSError as error:
        raise BootstrapFailure(
            "LOCAL_PROFILE_ALIAS_REVERIFY_FAILED",
            status="FAIL",
            local_profile_changed=profile_changed,
        ) from error
    finally:
        with suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        with suppress(OSError):
            os.close(descriptor)


def _atomic_write(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    _reject_symlink_chain(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="day15-authority-bootstrap-",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        os.fchmod(handle.fileno(), mode)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if path.is_symlink():
            raise BootstrapFailure("LOCAL_PATH_SYMLINK_FORBIDDEN", status="FAIL")
        os.replace(temporary, path)
        os.chmod(path, mode)
        try:
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            directory = -1
        if directory >= 0:
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _private_output_allowed(path: Path, *, root: Path) -> None:
    _reject_symlink_chain(path)
    lexical = Path(os.path.abspath(path))
    lexical_root = Path(os.path.abspath(root))
    try:
        relative = lexical.relative_to(lexical_root)
    except ValueError:
        raise BootstrapFailure("PRIVATE_RECEIPT_REPOSITORY_PATH_FORBIDDEN", status="FAIL") from None
    if not relative.parts or relative.parts[0] != ".aioa-private":
        raise BootstrapFailure("PRIVATE_RECEIPT_REPOSITORY_PATH_FORBIDDEN", status="FAIL")
    try:
        tracked = subprocess.run(
            ("git", "ls-files", "--error-unmatch", "--", relative.as_posix()),
            cwd=lexical_root,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        ignored = subprocess.run(
            ("git", "check-ignore", "--quiet", "--no-index", "--", relative.as_posix()),
            cwd=lexical_root,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BootstrapFailure("PRIVATE_RECEIPT_GIT_CHECK_FAILED", status="FAIL") from error
    if tracked.returncode == 0 or ignored.returncode != 0:
        raise BootstrapFailure("PRIVATE_RECEIPT_IGNORED_PATH_REQUIRED", status="FAIL")
    if path.exists():
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise BootstrapFailure("PRIVATE_RECEIPT_PROTECTION_INVALID", status="FAIL")


def _api_operation_names(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    assume_count = 0
    names: list[str] = []
    for index, item in enumerate(value, start=1):
        if (
            not isinstance(item, Mapping)
            or set(item) != {"operation", "sequence", "write"}
            or item.get("sequence") != index
            or item.get("write") is not False
            or item.get("operation") not in {"sts:GetCallerIdentity", "sts:AssumeRole"}
        ):
            return None
        operation = str(item["operation"])
        names.append(operation)
        if operation == "sts:AssumeRole":
            assume_count += 1
    if assume_count > 1:
        return None
    return tuple(names)


def _api_sequence_is_valid(operations: tuple[str, ...]) -> bool:
    direct = ("sts:GetCallerIdentity",)
    assumed = (
        "sts:GetCallerIdentity",
        "sts:AssumeRole",
        "sts:GetCallerIdentity",
    )
    return operations == direct[: len(operations)] or operations == assumed[: len(operations)]


def validate_private_authority_receipt(value: object) -> None:
    """Validate one closed private authority receipt without emitting its values."""

    if not isinstance(value, Mapping) or set(value) != PRIVATE_RECEIPT_KEYS:
        raise BootstrapFailure("PRIVATE_AUTHORITY_RECEIPT_SCHEMA_INVALID", status="FAIL")
    if value.get("schema_version") != 1 or value.get("region") != REGION:
        raise BootstrapFailure("PRIVATE_AUTHORITY_RECEIPT_SCHEMA_INVALID", status="FAIL")
    status_value = value.get("status")
    if status_value not in {"PASS", "BLOCKED", "FAIL"}:
        raise BootstrapFailure("PRIVATE_AUTHORITY_RECEIPT_SCHEMA_INVALID", status="FAIL")
    reasons = value.get("reasons")
    if (
        not isinstance(reasons, list)
        or any(
            not isinstance(reason, str) or reason not in PUBLIC_REASON_CODES for reason in reasons
        )
        or len(reasons) != len(set(reasons))
    ):
        raise BootstrapFailure("PRIVATE_AUTHORITY_RECEIPT_SCHEMA_INVALID", status="FAIL")
    selection = value.get("selection")
    authority = value.get("authority")
    checks = value.get("checks")
    if (
        not isinstance(selection, Mapping)
        or set(selection) != SELECTION_KEYS
        or not isinstance(authority, Mapping)
        or set(authority) != AUTHORITY_KEYS
        or not isinstance(checks, Mapping)
        or set(checks) != CHECK_KEYS
        or any(type(checks[key]) is not bool for key in CHECK_KEYS)
        or type(selection.get("ambiguous")) is not bool
        or value.get("aws_state_changed") is not False
        or value.get("credentials_persisted") is not False
        or value.get("iam_role_created") is not False
        or type(value.get("local_profile_state_changed")) is not bool
        or not isinstance(value.get("local_profile_write_operations"), list)
        or any(
            item != "aws-config:PutProfileAlias" for item in value["local_profile_write_operations"]
        )
        or not isinstance(value.get("observed_at"), str)
        or not isinstance(value.get("receipt_nonce"), str)
        or NONCE_PATTERN.fullmatch(str(value["receipt_nonce"])) is None
    ):
        raise BootstrapFailure("PRIVATE_AUTHORITY_RECEIPT_SCHEMA_INVALID", status="FAIL")
    try:
        observed = datetime.strptime(str(value["observed_at"]), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError as error:
        raise BootstrapFailure("PRIVATE_AUTHORITY_RECEIPT_SCHEMA_INVALID", status="FAIL") from error
    if observed.isoformat(timespec="seconds").replace("+00:00", "Z") != value["observed_at"]:
        raise BootstrapFailure("PRIVATE_AUTHORITY_RECEIPT_SCHEMA_INVALID", status="FAIL")
    passed = status_value == "PASS"
    operations = _api_operation_names(value.get("direct_sts_operations"))
    account_id = authority.get("expected_account_id")
    role_arn = authority.get("deployment_role_arn")
    source_profile = selection.get("source_profile")
    selection_method = selection.get("method")
    source_selected = checks.get("source_profile_selected") is True
    source_verified = checks.get("source_identity_verified") is True
    assume_performed = checks.get("assume_role_performed") is True
    temporary_verified = checks.get("temporary_assumed_identity_verified") is True
    exact_role = checks.get("exact_deployment_role_proven") is True
    alias_created = checks.get("alias_created") is True
    alias_reverified = checks.get("alias_reverified") is True
    local_changed = value.get("local_profile_state_changed") is True
    local_writes = value.get("local_profile_write_operations")
    semantic_invalid = (
        operations is None
        or not _api_sequence_is_valid(operations)
        or selection_method not in ({"NONE"} | set(SELECTION_METHODS))
        or source_selected != isinstance(source_profile, str)
        or (isinstance(source_profile, str) and PROFILE_PATTERN.fullmatch(source_profile) is None)
        or (source_selected != (selection_method in SELECTION_METHODS))
        or (selection.get("ambiguous") is True and source_selected)
        or (selection.get("ambiguous") is True) != ("PROFILE_AMBIGUOUS" in reasons)
        or (source_verified and (not source_selected or not operations))
        or assume_performed != ("sts:AssumeRole" in operations)
        or (
            temporary_verified
            and (
                not assume_performed
                or operations[:3]
                != (
                    "sts:GetCallerIdentity",
                    "sts:AssumeRole",
                    "sts:GetCallerIdentity",
                )
            )
        )
        or (exact_role and not source_verified)
        or (exact_role and assume_performed and not temporary_verified)
        or (
            alias_reverified
            and (
                not exact_role
                or operations
                not in {
                    ("sts:GetCallerIdentity",),
                    (
                        "sts:GetCallerIdentity",
                        "sts:AssumeRole",
                        "sts:GetCallerIdentity",
                    ),
                }
            )
        )
        or local_changed != alias_created
        or (local_writes == ["aws-config:PutProfileAlias"]) != alias_created
    )
    if semantic_invalid:
        raise BootstrapFailure("PRIVATE_AUTHORITY_RECEIPT_STATUS_INVALID", status="FAIL")
    if passed:
        if (
            reasons
            or not isinstance(account_id, str)
            or ACCOUNT_PATTERN.fullmatch(account_id) is None
            or role_arn != _role_arn(account_id)
            or authority.get("deployment_profile") != DEPLOYMENT_PROFILE
            or not source_selected
            or not source_verified
            or not exact_role
            or not alias_reverified
            or assume_performed != temporary_verified
        ):
            raise BootstrapFailure("PRIVATE_AUTHORITY_RECEIPT_STATUS_INVALID", status="FAIL")
    elif (
        not reasons
        or account_id is not None
        or role_arn is not None
        or authority.get("deployment_profile") != DEPLOYMENT_PROFILE
    ):
        raise BootstrapFailure("PRIVATE_AUTHORITY_RECEIPT_STATUS_INVALID", status="FAIL")


def _private_receipt(state: _State) -> dict[str, object]:
    passed = state.status == "PASS"
    return {
        "direct_sts_operations": list(state.api_operations),
        "authority": {
            "deployment_profile": DEPLOYMENT_PROFILE,
            "deployment_role_arn": state.role_arn if passed else None,
            "expected_account_id": state.account_id if passed else None,
        },
        "aws_state_changed": False,
        "checks": {
            "alias_created": state.alias_created,
            "alias_reverified": state.alias_reverified,
            "assume_role_performed": state.assume_role_performed,
            "exact_deployment_role_proven": state.exact_role_proven,
            "source_identity_verified": state.source_identity_verified,
            "source_profile_selected": state.source_profile is not None,
            "temporary_assumed_identity_verified": state.temporary_identity_verified,
        },
        "credentials_persisted": False,
        "iam_role_created": False,
        "local_profile_state_changed": state.alias_created,
        "local_profile_write_operations": list(state.local_write_operations),
        "observed_at": state.observed_at,
        "receipt_nonce": state.receipt_nonce,
        "reasons": list(state.reasons),
        "region": REGION,
        "schema_version": 1,
        "selection": {
            "ambiguous": state.source_profile_ambiguous,
            "method": state.selection_method,
            "source_profile": state.source_profile,
        },
        "status": state.status,
    }


def _sanitized_receipt(state: _State, *, private_receipt_created: bool) -> dict[str, object]:
    payload = {
        "aws_state_changed": False,
        "credentials_persisted": False,
        "exact_deployment_role_proven": state.exact_role_proven,
        "iam_role_created": False,
        "local_profile_alias_created": state.alias_created,
        "local_profile_alias_reverified": state.alias_reverified,
        "private_receipt_created": private_receipt_created,
        "reasons": list(state.reasons),
        "sanitized": True,
        "schema_version": 1,
        "source_identity_verified": state.source_identity_verified,
        "source_profile_ambiguous": state.source_profile_ambiguous,
        "source_profile_selected": state.source_profile is not None,
        "status": state.status,
        "sts_assume_role_performed": state.assume_role_performed,
        "temporary_assumed_identity_verified": state.temporary_identity_verified,
    }
    validate_sanitized_authority_receipt(payload)
    return payload


def validate_sanitized_authority_receipt(value: object) -> None:
    if (
        not isinstance(value, Mapping)
        or set(value) != SANITIZED_KEYS
        or value.get("schema_version") != 1
        or value.get("status") not in {"PASS", "BLOCKED", "FAIL"}
        or any(type(value.get(key)) is not bool for key in PUBLIC_BOOLEAN_KEYS)
        or value.get("sanitized") is not True
        or value.get("aws_state_changed") is not False
        or value.get("credentials_persisted") is not False
        or value.get("iam_role_created") is not False
    ):
        raise BootstrapFailure("SANITIZED_AUTHORITY_RECEIPT_SCHEMA_INVALID", status="FAIL")
    reasons = value.get("reasons")
    if (
        not isinstance(reasons, list)
        or any(
            not isinstance(reason, str) or reason not in PUBLIC_REASON_CODES for reason in reasons
        )
        or len(reasons) != len(set(reasons))
        or (value.get("status") == "PASS") is bool(reasons)
    ):
        raise BootstrapFailure("SANITIZED_AUTHORITY_RECEIPT_STATUS_INVALID", status="FAIL")
    passed = value.get("status") == "PASS"
    source_selected = value.get("source_profile_selected") is True
    source_verified = value.get("source_identity_verified") is True
    ambiguous = value.get("source_profile_ambiguous") is True
    assume_performed = value.get("sts_assume_role_performed") is True
    temporary_verified = value.get("temporary_assumed_identity_verified") is True
    exact_role = value.get("exact_deployment_role_proven") is True
    alias_created = value.get("local_profile_alias_created") is True
    alias_reverified = value.get("local_profile_alias_reverified") is True
    if (
        (ambiguous and source_selected)
        or ambiguous != ("PROFILE_AMBIGUOUS" in reasons)
        or (source_verified and not source_selected)
        or (temporary_verified and not assume_performed)
        or (exact_role and not source_verified)
        or (exact_role and assume_performed and not temporary_verified)
        or (alias_reverified and not exact_role)
        or (alias_created and not exact_role)
        or (
            passed
            and (
                not source_selected
                or not source_verified
                or not exact_role
                or not alias_reverified
                or assume_performed != temporary_verified
                or value.get("private_receipt_created") is not True
            )
        )
    ):
        raise BootstrapFailure("SANITIZED_AUTHORITY_RECEIPT_STATUS_INVALID", status="FAIL")


def _write_private_receipt(path: Path, state: _State) -> bytes:
    payload = _private_receipt(state)
    validate_private_authority_receipt(payload)
    raw = _canonical_bytes(payload)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise BootstrapFailure("PRIVATE_RECEIPT_TOO_LARGE", status="FAIL")
    _atomic_write(path, raw)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise BootstrapFailure("PRIVATE_RECEIPT_MODE_INVALID", status="FAIL")
    return raw


def _preserve_existing_private_receipt(path: Path) -> None:
    if not path.exists():
        return
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
        validate_private_authority_receipt(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, BootstrapFailure) as error:
        raise BootstrapFailure("PRIVATE_RECEIPT_ALREADY_EXISTS_INVALID", status="FAIL") from error
    if raw != _canonical_bytes(value):
        raise BootstrapFailure("PRIVATE_RECEIPT_ALREADY_EXISTS_INVALID", status="FAIL")
    backup = path.with_name(f"{path.stem}.previous-{_sha256(raw)[:16]}{path.suffix}")
    if backup.exists():
        try:
            backup_matches = (
                stat.S_IMODE(backup.lstat().st_mode) == 0o600 and backup.read_bytes() == raw
            )
        except OSError as error:
            raise BootstrapFailure("PRIVATE_RECEIPT_BACKUP_CONFLICT", status="FAIL") from error
        if not backup_matches:
            raise BootstrapFailure("PRIVATE_RECEIPT_BACKUP_CONFLICT", status="FAIL")
        return
    _atomic_write(backup, raw)


def _initial_state(
    *,
    clock: Callable[[], datetime],
    nonce_factory: Callable[[], str],
) -> _State:
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise BootstrapFailure("BOOTSTRAP_CLOCK_INVALID", status="FAIL")
    nonce = nonce_factory()
    if not isinstance(nonce, str) or NONCE_PATTERN.fullmatch(nonce) is None:
        raise BootstrapFailure("BOOTSTRAP_NONCE_INVALID", status="FAIL")
    return _State(
        observed_at=now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        receipt_nonce=nonce,
        reasons=["BOOTSTRAP_IN_PROGRESS"],
    )


def _default_session_factory(profile_name: str) -> AwsSession:
    import boto3
    import botocore.session

    core_session = botocore.session.get_session()
    core_session.set_config_variable("profile", profile_name)
    core_session.set_default_client_config(_bounded_config())
    return boto3.Session(botocore_session=core_session, region_name=REGION)


def _default_temporary_session_factory(credentials: Mapping[str, str]) -> AwsSession:
    import boto3
    import botocore.session

    core_session = botocore.session.get_session()
    core_session.set_default_client_config(_bounded_config())
    core_session.set_credentials(
        credentials["aws_access_key_id"],
        credentials["aws_secret_access_key"],
        credentials["aws_session_token"],
    )
    return boto3.Session(botocore_session=core_session, region_name=REGION)


def run_authority_bootstrap(
    *,
    aws_config_path: Path = DEFAULT_AWS_CONFIG,
    private_receipt_path: Path = DEFAULT_PRIVATE_RECEIPT,
    root: Path = ROOT,
    environment: Mapping[str, str] = os.environ,
    configured_profiles: Sequence[str] | None = None,
    session_factory: SessionFactory = _default_session_factory,
    temporary_session_factory: TemporarySessionFactory = _default_temporary_session_factory,
    repository_guard: RepositoryGuard = _default_repository_guard,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    nonce_factory: Callable[[], str] = lambda: secrets.token_hex(16),
) -> dict[str, object]:
    """Prove existing authority and return a public-safe bootstrap decision."""

    if _normalized_path(private_receipt_path) == _normalized_path(aws_config_path):
        raise BootstrapFailure("PRIVATE_RECEIPT_PATH_COLLISION", status="FAIL")
    _private_output_allowed(private_receipt_path, root=root)
    _preserve_existing_private_receipt(private_receipt_path)
    state = _initial_state(clock=clock, nonce_factory=nonce_factory)
    _write_private_receipt(private_receipt_path, state)
    original_config: bytes | None = None
    try:
        repository_guard(root)
        if any(
            value and (name == "AWS_ENDPOINT_URL" or name.startswith("AWS_ENDPOINT_URL_"))
            for name, value in environment.items()
        ):
            raise BootstrapFailure("AWS_ENDPOINT_OVERRIDE_FORBIDDEN", status="FAIL")
        configured_path = environment.get("AWS_CONFIG_FILE")
        active_config_path = Path(configured_path) if configured_path else DEFAULT_AWS_CONFIG
        if _normalized_path(active_config_path) != _normalized_path(aws_config_path):
            raise BootstrapFailure("AWS_CONFIG_ACTIVE_PATH_MISMATCH", status="FAIL")
        profiles = (
            tuple(configured_profiles) if configured_profiles is not None else _available_profiles()
        )
        try:
            source_profile, selection_method = select_source_profile(
                environment=environment,
                configured_profiles=profiles,
            )
        except BootstrapFailure as error:
            if error.reason == "PROFILE_AMBIGUOUS":
                state.source_profile_ambiguous = True
            raise
        state.source_profile = source_profile
        state.selection_method = selection_method

        original_config, parser = _read_aws_config(aws_config_path)
        _section_mapping(parser, source_profile)
        try:
            source_session = session_factory(source_profile)
        except Exception as error:
            raise BootstrapFailure("SOURCE_PROFILE_AUTHENTICATION_REQUIRED") from error
        if getattr(source_session, "profile_name", None) != source_profile:
            raise BootstrapFailure("SOURCE_SESSION_PROFILE_MISMATCH")
        source_sts = _sts_client(
            source_session,
            reason="SOURCE_PROFILE_AUTHENTICATION_REQUIRED",
        )
        source_identity = _get_identity(
            source_sts,
            state,
            reason="SOURCE_PROFILE_AUTHENTICATION_REQUIRED",
        )
        account_id, _source_arn = _identity_parts(source_identity)
        state.source_identity_verified = True
        exact_role_arn = _role_arn(account_id)

        if _identity_is_exact_role(
            source_identity,
            account_id=account_id,
            role_arn=exact_role_arn,
        ):
            state.exact_role_proven = True
        else:
            state.assume_role_performed = True
            _record_call(state, "sts:AssumeRole")
            try:
                assume_response = source_sts.assume_role(
                    RoleArn=exact_role_arn,
                    RoleSessionName=ROLE_SESSION_NAME,
                    DurationSeconds=ASSUME_ROLE_DURATION_SECONDS,
                )
            except Exception as error:
                raise BootstrapFailure("EXACT_DEPLOYMENT_ROLE_NOT_ASSUMABLE") from error
            temporary_credentials = _temporary_credentials(assume_response)
            try:
                temporary_session = temporary_session_factory(temporary_credentials)
            except Exception as error:
                raise BootstrapFailure("TEMPORARY_ROLE_SESSION_UNAVAILABLE") from error
            finally:
                temporary_credentials = {}
            temporary_sts = _sts_client(
                temporary_session,
                reason="TEMPORARY_ROLE_SESSION_UNAVAILABLE",
            )
            temporary_identity = _get_identity(
                temporary_sts,
                state,
                reason="TEMPORARY_ROLE_IDENTITY_UNAVAILABLE",
            )
            if not _identity_is_exact_role(
                temporary_identity,
                account_id=account_id,
                role_arn=exact_role_arn,
            ):
                raise BootstrapFailure("ASSUMED_ROLE_IDENTITY_MISMATCH")
            state.temporary_identity_verified = True
            state.exact_role_proven = True

        current_config, current_parser = _read_aws_config(aws_config_path)
        if current_config != original_config:
            raise BootstrapFailure("AWS_CONFIG_CHANGED_DURING_BOOTSTRAP", status="FAIL")
        parser = current_parser
        expected_alias = _expected_alias_mapping(
            parser,
            source_profile=source_profile,
            role_arn=exact_role_arn,
            assume_role_performed=state.assume_role_performed,
        )
        existing_alias = _section_mapping(parser, DEPLOYMENT_PROFILE)
        if existing_alias is not None:
            if existing_alias != expected_alias:
                raise BootstrapFailure("LOCAL_PROFILE_ALIAS_CONFLICT")
        else:
            updated = _append_alias(original_config, expected_alias)
            try:
                _append_config_alias(
                    aws_config_path,
                    original=original_config,
                    updated=updated,
                )
            except BootstrapFailure as error:
                if error.local_profile_changed:
                    state.alias_created = True
                    state.local_write_operations.append("aws-config:PutProfileAlias")
                raise
            state.alias_created = True
            state.local_write_operations.append("aws-config:PutProfileAlias")
            raw_after, parser_after = _read_aws_config(aws_config_path)
            if (
                raw_after != updated
                or _section_mapping(parser_after, DEPLOYMENT_PROFILE) != expected_alias
            ):
                raise BootstrapFailure("LOCAL_PROFILE_ALIAS_REVERIFY_FAILED", status="FAIL")
        state.alias_reverified = True

        state.account_id = account_id
        state.role_arn = exact_role_arn
        state.status = "PASS"
        state.reasons.clear()
        _write_private_receipt(private_receipt_path, state)
        return _sanitized_receipt(state, private_receipt_created=True)
    except BootstrapFailure as error:
        state.reason(error.reason, status=error.status)
    except Exception:
        state.reason("AUTHORITY_BOOTSTRAP_INTERNAL_FAILURE", status="FAIL")

    try:
        _write_private_receipt(private_receipt_path, state)
        private_created = True
    except (OSError, BootstrapFailure):
        state.reason("PRIVATE_RECEIPT_WRITE_FAILED", status="FAIL")
        private_created = False
    return _sanitized_receipt(state, private_receipt_created=private_created)


def _exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 3}.get(status, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aws-config", type=Path, default=DEFAULT_AWS_CONFIG)
    parser.add_argument("--private-receipt", type=Path, default=DEFAULT_PRIVATE_RECEIPT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        payload = run_authority_bootstrap(
            aws_config_path=args.aws_config,
            private_receipt_path=args.private_receipt,
        )
    except BootstrapFailure as error:
        state = _State(
            observed_at="1970-01-01T00:00:00Z",
            receipt_nonce="0" * 32,
            status=error.status,
            reasons=[error.reason],
        )
        payload = _sanitized_receipt(state, private_receipt_created=False)
    except Exception:
        state = _State(
            observed_at="1970-01-01T00:00:00Z",
            receipt_nonce="0" * 32,
            status="FAIL",
            reasons=["AUTHORITY_BOOTSTRAP_INTERNAL_FAILURE"],
        )
        payload = _sanitized_receipt(state, private_receipt_created=False)
    if args.json:
        print(canonical_json(payload))
    else:
        reasons = ",".join(payload["reasons"]) or "-"
        print(f"DAY15_G10_AUTHORITY_BOOTSTRAP {payload['status']} reasons={reasons}")
    return _exit_code(str(payload["status"]))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ASSUME_ROLE_DURATION_SECONDS",
    "CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_AWS_CONFIG",
    "DEFAULT_PRIVATE_RECEIPT",
    "READ_TIMEOUT_SECONDS",
    "ROLE_SESSION_NAME",
    "TOTAL_MAX_ATTEMPTS",
    "BootstrapFailure",
    "run_authority_bootstrap",
    "select_source_profile",
    "validate_private_authority_receipt",
    "validate_sanitized_authority_receipt",
]
