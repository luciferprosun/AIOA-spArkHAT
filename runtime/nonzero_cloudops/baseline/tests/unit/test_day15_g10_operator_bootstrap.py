from __future__ import annotations

import configparser
import json
import stat
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from botocore.config import Config
from scripts.day15 import g10_operator_bootstrap as bootstrap

ACCOUNT_ID = "111122223333"
SOURCE_PROFILE = "operator-source"
SOURCE_ARN = f"arn:aws:sts::{ACCOUNT_ID}:assumed-role/OperatorAccess/source"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/{bootstrap.DEPLOYMENT_ROLE_LEAF}"
ASSUMED_ROLE_ARN = (
    f"arn:aws:sts::{ACCOUNT_ID}:assumed-role/"
    f"{bootstrap.DEPLOYMENT_ROLE_LEAF}/{bootstrap.ROLE_SESSION_NAME}"
)
NOW = datetime(2026, 8, 25, 6, 30, tzinfo=UTC)
NONCE = "a" * 32


class FakeSts:
    def __init__(
        self,
        identity: Mapping[str, object],
        *,
        assume_response: Mapping[str, object] | None = None,
        assume_error: Exception | None = None,
        identity_effect: Callable[[], None] | None = None,
    ) -> None:
        self.identity = dict(identity)
        self.assume_response = assume_response
        self.assume_error = assume_error
        self.identity_effect = identity_effect
        self.identity_calls = 0
        self.assume_calls: list[dict[str, object]] = []

    def get_caller_identity(self) -> dict[str, object]:
        self.identity_calls += 1
        if self.identity_effect is not None:
            self.identity_effect()
        return dict(self.identity)

    def assume_role(self, **kwargs: object) -> dict[str, object]:
        self.assume_calls.append(dict(kwargs))
        if self.assume_error is not None:
            raise self.assume_error
        assert self.assume_response is not None
        return dict(self.assume_response)


class FakeSession:
    def __init__(self, profile_name: str | None, sts: FakeSts) -> None:
        self.profile_name = profile_name
        self.sts = sts
        self.client_configs: list[Config] = []

    def client(
        self,
        service_name: str,
        *,
        region_name: str,
        config: Config,
    ) -> FakeSts:
        assert service_name == "sts"
        assert region_name == bootstrap.REGION
        self.client_configs.append(config)
        return self.sts


def _identity(arn: str) -> dict[str, object]:
    return {"Account": ACCOUNT_ID, "Arn": arn, "UserId": "fixture"}


def _assume_response() -> dict[str, object]:
    return {
        "Credentials": {
            "AccessKeyId": "temporary-access-id",
            "SecretAccessKey": "temporary-secret",
            "SessionToken": "temporary-token",
        }
    }


def _config(
    path: Path,
    *,
    alias: Mapping[str, str] | None = None,
    source_extra: Mapping[str, str] | None = None,
) -> bytes:
    lines = [
        f"[profile {SOURCE_PROFILE}]",
        f"region = {bootstrap.REGION}",
        "output = json",
    ]
    if source_extra is not None:
        lines.extend(f"{key} = {value}" for key, value in source_extra.items())
    if alias is not None:
        lines.extend(
            [
                "",
                f"[profile {bootstrap.DEPLOYMENT_PROFILE}]",
                *(f"{key} = {value}" for key, value in alias.items()),
            ]
        )
    raw = ("\n".join(lines) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)
    return raw


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir(parents=True, exist_ok=True)
    (root / ".gitignore").write_text(".aioa-private/\n", encoding="utf-8")
    subprocess.run(
        ("git", "init", "--quiet"),
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    return root


def _private_path(tmp_path: Path) -> Path:
    return _repository(tmp_path) / ".aioa-private" / "authority.json"


def _run(
    tmp_path: Path,
    *,
    source_sts: FakeSts,
    temporary_sts: FakeSts | None,
    profiles: tuple[str, ...] = (SOURCE_PROFILE,),
    environment: Mapping[str, str] | None = None,
    alias: Mapping[str, str] | None = None,
    source_extra: Mapping[str, str] | None = None,
) -> tuple[
    dict[str, object],
    Path,
    Path,
    FakeSession,
    FakeSession | None,
]:
    config_path = tmp_path / ".aws" / "config"
    _config(config_path, alias=alias, source_extra=source_extra)
    source_session = FakeSession(SOURCE_PROFILE, source_sts)
    temporary_session = FakeSession(None, temporary_sts) if temporary_sts is not None else None

    def temporary_factory(credentials: Mapping[str, str]) -> FakeSession:
        assert credentials == {
            "aws_access_key_id": "temporary-access-id",
            "aws_secret_access_key": "temporary-secret",
            "aws_session_token": "temporary-token",
        }
        assert temporary_session is not None
        return temporary_session

    effective_environment = {"AWS_CONFIG_FILE": str(config_path)}
    if environment is not None:
        effective_environment.update(environment)

    def session_factory(profile: str) -> FakeSession:
        if profile == SOURCE_PROFILE:
            return source_session
        raise AssertionError("unexpected source profile")

    result = bootstrap.run_authority_bootstrap(
        aws_config_path=config_path,
        private_receipt_path=_private_path(tmp_path),
        root=_repository(tmp_path),
        environment=effective_environment,
        configured_profiles=profiles,
        session_factory=session_factory,
        temporary_session_factory=temporary_factory,
        repository_guard=lambda _root: None,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
    )
    return (
        result,
        config_path,
        _private_path(tmp_path),
        source_session,
        temporary_session,
    )


def _expected_alias() -> dict[str, str]:
    return {
        "duration_seconds": str(bootstrap.ASSUME_ROLE_DURATION_SECONDS),
        "region": bootstrap.REGION,
        "role_arn": ROLE_ARN,
        "role_session_name": bootstrap.ROLE_SESSION_NAME,
        "source_profile": SOURCE_PROFILE,
    }


def _read_alias(path: Path) -> dict[str, str]:
    parser = configparser.RawConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return dict(parser.items(f"profile {bootstrap.DEPLOYMENT_PROFILE}", raw=True))


def test_select_source_profile_is_explicit_or_uniquely_deterministic() -> None:
    assert bootstrap.select_source_profile(
        environment={"AWS_PROFILE": SOURCE_PROFILE},
        configured_profiles=("another", SOURCE_PROFILE),
    ) == (SOURCE_PROFILE, "EXPLICIT_ENVIRONMENT_PROFILE")
    assert bootstrap.select_source_profile(
        environment={},
        configured_profiles=(bootstrap.DEPLOYMENT_PROFILE, SOURCE_PROFILE),
    ) == (SOURCE_PROFILE, "UNIQUE_LOCAL_PROFILE")


@pytest.mark.parametrize(
    ("environment", "profiles", "reason"),
    [
        ({}, (), "SOURCE_PROFILE_REQUIRED"),
        ({}, ("one", "two"), "PROFILE_AMBIGUOUS"),
        (
            {"AWS_PROFILE": "one", "AWS_DEFAULT_PROFILE": "two"},
            ("one", "two"),
            "PROFILE_AMBIGUOUS",
        ),
        (
            {"AWS_PROFILE": "missing"},
            (SOURCE_PROFILE,),
            "EXPLICIT_SOURCE_PROFILE_UNAVAILABLE",
        ),
    ],
)
def test_select_source_profile_fails_closed(
    environment: Mapping[str, str],
    profiles: tuple[str, ...],
    reason: str,
) -> None:
    with pytest.raises(bootstrap.BootstrapFailure, match=f"^{reason}$"):
        bootstrap.select_source_profile(
            environment=environment,
            configured_profiles=profiles,
        )


def test_assumable_exact_role_creates_and_reverifies_zero_authority_alias(
    tmp_path: Path,
) -> None:
    source_sts = FakeSts(_identity(SOURCE_ARN), assume_response=_assume_response())
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    (
        result,
        config_path,
        private_path,
        source_session,
        temporary_session,
    ) = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
    )

    assert result == {
        "aws_state_changed": False,
        "credentials_persisted": False,
        "exact_deployment_role_proven": True,
        "iam_role_created": False,
        "local_profile_alias_created": True,
        "local_profile_alias_reverified": True,
        "private_receipt_created": True,
        "reasons": [],
        "sanitized": True,
        "schema_version": 1,
        "source_identity_verified": True,
        "source_profile_ambiguous": False,
        "source_profile_selected": True,
        "status": "PASS",
        "sts_assume_role_performed": True,
        "temporary_assumed_identity_verified": True,
    }
    assert _read_alias(config_path) == _expected_alias()
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(private_path.stat().st_mode) == 0o600
    assert source_sts.identity_calls == 1
    assert source_sts.assume_calls == [
        {
            "RoleArn": ROLE_ARN,
            "RoleSessionName": bootstrap.ROLE_SESSION_NAME,
            "DurationSeconds": bootstrap.ASSUME_ROLE_DURATION_SECONDS,
        }
    ]
    assert temporary_sts.identity_calls == 1
    assert temporary_session is not None
    for session in (source_session, temporary_session):
        assert len(session.client_configs) == 1
        client_config = session.client_configs[0]
        assert client_config.retries["total_max_attempts"] == 1
        assert client_config.ignore_configured_endpoint_urls is True
        assert client_config.connect_timeout == bootstrap.CONNECT_TIMEOUT_SECONDS
        assert client_config.read_timeout == bootstrap.READ_TIMEOUT_SECONDS

    receipt = json.loads(private_path.read_text(encoding="utf-8"))
    bootstrap.validate_private_authority_receipt(receipt)
    assert receipt["authority"] == {
        "deployment_profile": bootstrap.DEPLOYMENT_PROFILE,
        "deployment_role_arn": ROLE_ARN,
        "expected_account_id": ACCOUNT_ID,
    }
    assert receipt["direct_sts_operations"] == [
        {"operation": "sts:GetCallerIdentity", "sequence": 1, "write": False},
        {"operation": "sts:AssumeRole", "sequence": 2, "write": False},
        {"operation": "sts:GetCallerIdentity", "sequence": 3, "write": False},
    ]
    serialized_public = json.dumps(result, sort_keys=True)
    assert ACCOUNT_ID not in serialized_public
    assert ROLE_ARN not in serialized_public
    assert SOURCE_PROFILE not in serialized_public


def test_cross_name_source_already_exact_role_blocks_unproven_alias(tmp_path: Path) -> None:
    source_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    (
        result,
        config_path,
        private_path,
        _source_session,
        _temporary_session,
    ) = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=None,
    )

    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["SOURCE_PROFILE_ALIAS_AUTHORITY_UNPROVEN"]
    assert result["sts_assume_role_performed"] is False
    assert result["temporary_assumed_identity_verified"] is False
    assert result["exact_deployment_role_proven"] is True
    assert result["local_profile_alias_created"] is False
    assert source_sts.assume_calls == []
    assert f"[profile {bootstrap.DEPLOYMENT_PROFILE}]" not in config_path.read_text()
    receipt = json.loads(private_path.read_text(encoding="utf-8"))
    bootstrap.validate_private_authority_receipt(receipt)
    assert receipt["direct_sts_operations"] == [
        {"operation": "sts:GetCallerIdentity", "sequence": 1, "write": False}
    ]


def test_existing_named_alias_exact_role_passes_without_assume_or_write(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".aws" / "config"
    raw = (
        f"[profile {bootstrap.DEPLOYMENT_PROFILE}]\nregion = {bootstrap.REGION}\noutput = json\n"
    ).encode()
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(raw)
    config_path.chmod(0o600)
    source_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    source_session = FakeSession(bootstrap.DEPLOYMENT_PROFILE, source_sts)

    result = bootstrap.run_authority_bootstrap(
        aws_config_path=config_path,
        private_receipt_path=_private_path(tmp_path),
        root=_repository(tmp_path),
        environment={"AWS_CONFIG_FILE": str(config_path)},
        configured_profiles=(bootstrap.DEPLOYMENT_PROFILE,),
        session_factory=lambda _profile: source_session,
        repository_guard=lambda _root: None,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
    )

    assert result["status"] == "PASS"
    assert result["sts_assume_role_performed"] is False
    assert result["local_profile_alias_created"] is False
    assert result["local_profile_alias_reverified"] is True
    assert config_path.read_bytes() == raw


@pytest.mark.parametrize(
    "source_arn",
    [
        f"arn:aws:iam::{ACCOUNT_ID}:user/operator",
        f"arn:aws:sts::{ACCOUNT_ID}:federated-user/operator",
    ],
)
def test_non_root_source_principals_may_prove_the_exact_role(
    tmp_path: Path,
    source_arn: str,
) -> None:
    source_sts = FakeSts(_identity(source_arn), assume_response=_assume_response())
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    result, config_path, _private, *_sessions = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
    )

    assert result["status"] == "PASS"
    assert result["exact_deployment_role_proven"] is True
    assert _read_alias(config_path) == _expected_alias()


def test_root_source_principal_is_never_substituted_for_the_role(tmp_path: Path) -> None:
    source_sts = FakeSts(_identity(f"arn:aws:iam::{ACCOUNT_ID}:root"))
    result, config_path, private_path, *_sessions = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=None,
    )

    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["ROOT_SOURCE_PRINCIPAL_FORBIDDEN"]
    assert result["source_identity_verified"] is False
    assert result["exact_deployment_role_proven"] is False
    assert f"[profile {bootstrap.DEPLOYMENT_PROFILE}]" not in config_path.read_text()
    assert ACCOUNT_ID not in json.dumps(result)
    receipt = json.loads(private_path.read_text(encoding="utf-8"))
    bootstrap.validate_private_authority_receipt(receipt)


def test_path_qualified_same_leaf_assumed_role_is_not_exact(tmp_path: Path) -> None:
    source_sts = FakeSts(_identity(SOURCE_ARN), assume_response=_assume_response())
    near_match = (
        f"arn:aws:sts::{ACCOUNT_ID}:assumed-role/other/{bootstrap.DEPLOYMENT_ROLE_LEAF}/session"
    )
    temporary_sts = FakeSts(_identity(near_match))
    result, config_path, _private_path_value, *_sessions = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
    )

    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["ASSUMED_ROLE_IDENTITY_MISMATCH"]
    assert result["exact_deployment_role_proven"] is False
    assert f"[profile {bootstrap.DEPLOYMENT_PROFILE}]" not in config_path.read_text()


def test_unassumable_role_is_sanitized_blocked_and_never_writes_alias(
    tmp_path: Path,
) -> None:
    source_sts = FakeSts(
        _identity(SOURCE_ARN),
        assume_error=RuntimeError("provider detail must not escape"),
    )
    (
        result,
        config_path,
        private_path,
        _source_session,
        _temporary_session,
    ) = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=None,
    )

    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["EXACT_DEPLOYMENT_ROLE_NOT_ASSUMABLE"]
    assert result["source_identity_verified"] is True
    assert result["exact_deployment_role_proven"] is False
    assert result["local_profile_alias_created"] is False
    assert result["aws_state_changed"] is False
    assert not configparser.RawConfigParser().has_section(f"profile {bootstrap.DEPLOYMENT_PROFILE}")
    assert f"[profile {bootstrap.DEPLOYMENT_PROFILE}]" not in config_path.read_text()

    receipt = json.loads(private_path.read_text(encoding="utf-8"))
    bootstrap.validate_private_authority_receipt(receipt)
    assert receipt["authority"] == {
        "deployment_profile": bootstrap.DEPLOYMENT_PROFILE,
        "deployment_role_arn": None,
        "expected_account_id": None,
    }
    assert "provider detail" not in json.dumps(result)
    assert "provider detail" not in private_path.read_text(encoding="utf-8")


def test_conflicting_existing_alias_blocks_without_overwrite(tmp_path: Path) -> None:
    conflicting_alias = {
        "region": bootstrap.REGION,
        "role_arn": ROLE_ARN,
        "role_session_name": "different-session",
        "source_profile": SOURCE_PROFILE,
    }
    source_sts = FakeSts(_identity(SOURCE_ARN), assume_response=_assume_response())
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    config_path = tmp_path / ".aws" / "config"
    before = _config(config_path, alias=conflicting_alias)
    (
        result,
        config_path,
        private_path,
        _source_session,
        _temporary_session,
    ) = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
        alias=conflicting_alias,
    )

    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["LOCAL_PROFILE_ALIAS_CONFLICT"]
    assert result["exact_deployment_role_proven"] is True
    assert result["local_profile_alias_created"] is False
    assert config_path.read_bytes() == before
    receipt = json.loads(private_path.read_text(encoding="utf-8"))
    bootstrap.validate_private_authority_receipt(receipt)


def test_existing_exact_alias_is_byte_reverified_and_idempotent(tmp_path: Path) -> None:
    source_sts = FakeSts(_identity(SOURCE_ARN), assume_response=_assume_response())
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    config_path = tmp_path / ".aws" / "config"
    before = _config(config_path, alias=_expected_alias())
    result, config_path, private_path, *_sessions = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
        alias=_expected_alias(),
    )

    assert result["status"] == "PASS"
    assert result["local_profile_alias_created"] is False
    assert result["local_profile_alias_reverified"] is True
    assert config_path.read_bytes() == before
    receipt = json.loads(private_path.read_text(encoding="utf-8"))
    assert receipt["local_profile_write_operations"] == []
    bootstrap.validate_private_authority_receipt(receipt)


def test_prewrite_concurrent_config_change_blocks_without_overwrite(tmp_path: Path) -> None:
    config_path = tmp_path / ".aws" / "config"

    def concurrent_edit() -> None:
        config_path.write_bytes(config_path.read_bytes() + b"# concurrent edit\n")

    source_sts = FakeSts(
        _identity(SOURCE_ARN),
        assume_response=_assume_response(),
        identity_effect=concurrent_edit,
    )
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    result, config_path, private_path, *_sessions = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
    )

    assert result["status"] == "FAIL"
    assert result["reasons"] == ["AWS_CONFIG_CHANGED_DURING_BOOTSTRAP"]
    assert config_path.read_bytes().endswith(b"# concurrent edit\n")
    assert f"[profile {bootstrap.DEPLOYMENT_PROFILE}]" not in config_path.read_text()
    bootstrap.validate_private_authority_receipt(
        json.loads(private_path.read_text(encoding="utf-8"))
    )


def test_check_to_append_concurrent_edit_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / ".aws" / "config"
    real_write = bootstrap.os.write
    injected = False

    def write_with_concurrent_edit(descriptor: int, value: bytes) -> int:
        nonlocal injected
        if not injected and f"[profile {bootstrap.DEPLOYMENT_PROFILE}]".encode() in value:
            injected = True
            with config_path.open("ab") as handle:
                handle.write(b"# concurrent append\n")
                handle.flush()
        return real_write(descriptor, value)

    monkeypatch.setattr(bootstrap.os, "write", write_with_concurrent_edit)
    source_sts = FakeSts(_identity(SOURCE_ARN), assume_response=_assume_response())
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    result, config_path, private_path, *_sessions = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
    )

    assert injected is True
    assert result["status"] == "FAIL"
    assert result["reasons"] == ["AWS_CONFIG_CHANGED_DURING_BOOTSTRAP"]
    assert result["local_profile_alias_created"] is True
    assert b"# concurrent append\n" in config_path.read_bytes()
    assert f"[profile {bootstrap.DEPLOYMENT_PROFILE}]" in config_path.read_text()
    bootstrap.validate_private_authority_receipt(
        json.loads(private_path.read_text(encoding="utf-8"))
    )


def test_short_config_writes_are_completed_without_partial_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_write = bootstrap.os.write

    def short_write(descriptor: int, value: bytes) -> int:
        portion = max(1, len(value) // 2)
        return real_write(descriptor, value[:portion])

    monkeypatch.setattr(bootstrap.os, "write", short_write)
    source_sts = FakeSts(_identity(SOURCE_ARN), assume_response=_assume_response())
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    result, config_path, private_path, *_sessions = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
    )

    assert result["status"] == "PASS"
    assert _read_alias(config_path) == _expected_alias()
    bootstrap.validate_private_authority_receipt(
        json.loads(private_path.read_text(encoding="utf-8"))
    )


def test_failed_partial_append_restores_exact_original_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / ".aws" / "config"
    original = _config(config_path)
    real_write = bootstrap.os.write
    calls = 0

    def fail_after_partial(descriptor: int, value: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            portion = max(1, len(value) // 2)
            return real_write(descriptor, value[:portion])
        raise OSError("injected write failure")

    monkeypatch.setattr(bootstrap.os, "write", fail_after_partial)
    source_sts = FakeSts(_identity(SOURCE_ARN), assume_response=_assume_response())
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    result, config_path, private_path, *_sessions = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
    )

    assert result["status"] == "FAIL"
    assert result["reasons"] == ["LOCAL_PROFILE_ALIAS_REVERIFY_FAILED"]
    assert result["local_profile_alias_created"] is False
    assert config_path.read_bytes() == original
    bootstrap.validate_private_authority_receipt(
        json.loads(private_path.read_text(encoding="utf-8"))
    )


def test_alias_append_refuses_to_exceed_config_size_bound(tmp_path: Path) -> None:
    config_path = tmp_path / "config"
    original = b"x" * (bootstrap.MAX_CONFIG_BYTES - 4)
    config_path.write_bytes(original)
    config_path.chmod(0o600)

    with pytest.raises(
        bootstrap.BootstrapFailure,
        match=r"^LOCAL_PROFILE_ALIAS_REVERIFY_FAILED$",
    ):
        bootstrap._append_config_alias(
            config_path,
            original=original,
            updated=original + b"12345",
        )
    assert config_path.read_bytes() == original


def test_ambiguous_profiles_make_no_session_and_emit_no_profile_names(
    tmp_path: Path,
) -> None:
    private_path = _private_path(tmp_path)

    def forbidden_session(_profile: str) -> FakeSession:
        raise AssertionError("AWS session creation is forbidden")

    result = bootstrap.run_authority_bootstrap(
        private_receipt_path=private_path,
        root=tmp_path / "repository",
        environment={},
        configured_profiles=("first-source", "second-source"),
        session_factory=forbidden_session,
        repository_guard=lambda _root: None,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
    )

    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["PROFILE_AMBIGUOUS"]
    assert result["source_profile_ambiguous"] is True
    assert result["source_profile_selected"] is False
    assert "first-source" not in json.dumps(result)
    assert "second-source" not in json.dumps(result)
    receipt = json.loads(private_path.read_text(encoding="utf-8"))
    bootstrap.validate_private_authority_receipt(receipt)


def test_public_and_private_receipt_schemas_reject_unknown_fields(
    tmp_path: Path,
) -> None:
    source_sts = FakeSts(_identity(SOURCE_ARN), assume_response=_assume_response())
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    (
        result,
        _config_path,
        private_path,
        _source_session,
        _temporary_session,
    ) = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
    )
    public_with_extra = {**result, "account_id": ACCOUNT_ID}
    with pytest.raises(
        bootstrap.BootstrapFailure,
        match=r"^SANITIZED_AUTHORITY_RECEIPT_SCHEMA_INVALID$",
    ):
        bootstrap.validate_sanitized_authority_receipt(public_with_extra)

    private = json.loads(private_path.read_text(encoding="utf-8"))
    private["credential"] = "forbidden"
    with pytest.raises(
        bootstrap.BootstrapFailure,
        match=r"^PRIVATE_AUTHORITY_RECEIPT_SCHEMA_INVALID$",
    ):
        bootstrap.validate_private_authority_receipt(private)


def test_receipt_semantics_reject_fabricated_pass_evidence(tmp_path: Path) -> None:
    source_sts = FakeSts(_identity(SOURCE_ARN), assume_response=_assume_response())
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    result, _config_path, private_path, *_sessions = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
    )
    private = json.loads(private_path.read_text(encoding="utf-8"))

    for field in (
        "source_profile_selected",
        "source_identity_verified",
        "exact_deployment_role_proven",
        "alias_reverified",
    ):
        tampered = json.loads(json.dumps(private))
        tampered["checks"][field] = False
        with pytest.raises(
            bootstrap.BootstrapFailure,
            match=r"^PRIVATE_AUTHORITY_RECEIPT_STATUS_INVALID$",
        ):
            bootstrap.validate_private_authority_receipt(tampered)

    for mutation in (
        lambda value: value.update({"direct_sts_operations": []}),
        lambda value: value["selection"].update({"method": "ARBITRARY"}),
        lambda value: value.update({"local_profile_state_changed": False}),
        lambda value: value.update({"local_profile_write_operations": []}),
    ):
        tampered = json.loads(json.dumps(private))
        mutation(tampered)
        with pytest.raises(
            bootstrap.BootstrapFailure,
            match=r"^PRIVATE_AUTHORITY_RECEIPT_STATUS_INVALID$",
        ):
            bootstrap.validate_private_authority_receipt(tampered)

    for field in (
        "source_profile_selected",
        "source_identity_verified",
        "exact_deployment_role_proven",
        "local_profile_alias_reverified",
        "private_receipt_created",
    ):
        tampered_public = dict(result)
        tampered_public[field] = False
        with pytest.raises(
            bootstrap.BootstrapFailure,
            match=r"^SANITIZED_AUTHORITY_RECEIPT_STATUS_INVALID$",
        ):
            bootstrap.validate_sanitized_authority_receipt(tampered_public)

    identity_reason = dict(result)
    identity_reason["status"] = "BLOCKED"
    identity_reason["reasons"] = [ACCOUNT_ID]
    with pytest.raises(
        bootstrap.BootstrapFailure,
        match=r"^SANITIZED_AUTHORITY_RECEIPT_STATUS_INVALID$",
    ):
        bootstrap.validate_sanitized_authority_receipt(identity_reason)


def test_exact_source_alias_refuses_endpoint_override_keys(tmp_path: Path) -> None:
    config_path = tmp_path / ".aws" / "config"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f"[profile {SOURCE_PROFILE}]\n"
        f"region = {bootstrap.REGION}\n"
        "endpoint_url = https://example.invalid\n",
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    source_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    source_session = FakeSession(SOURCE_PROFILE, source_sts)

    result = bootstrap.run_authority_bootstrap(
        aws_config_path=config_path,
        private_receipt_path=_private_path(tmp_path),
        root=_repository(tmp_path),
        environment={"AWS_CONFIG_FILE": str(config_path)},
        configured_profiles=(SOURCE_PROFILE,),
        session_factory=lambda _profile: source_session,
        repository_guard=lambda _root: None,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
    )

    assert result["status"] == "FAIL"
    assert result["reasons"] == ["AWS_CONFIG_PROFILE_UNSAFE"]
    assert f"[profile {bootstrap.DEPLOYMENT_PROFILE}]" not in config_path.read_text()


def test_active_config_mismatch_blocks_before_session_creation(tmp_path: Path) -> None:
    config_path = tmp_path / ".aws" / "config"
    before = _config(config_path)

    def forbidden_session(_profile: str) -> FakeSession:
        raise AssertionError("AWS session creation is forbidden")

    result = bootstrap.run_authority_bootstrap(
        aws_config_path=config_path,
        private_receipt_path=_private_path(tmp_path),
        root=_repository(tmp_path),
        environment={"AWS_CONFIG_FILE": str(tmp_path / "different-config")},
        configured_profiles=(SOURCE_PROFILE,),
        session_factory=forbidden_session,
        repository_guard=lambda _root: None,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
    )

    assert result["status"] == "FAIL"
    assert result["reasons"] == ["AWS_CONFIG_ACTIVE_PATH_MISMATCH"]
    assert config_path.read_bytes() == before


def test_endpoint_override_environment_blocks_before_session_creation(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".aws" / "config"
    before = _config(config_path)

    def forbidden_session(_profile: str) -> FakeSession:
        raise AssertionError("AWS session creation is forbidden")

    result = bootstrap.run_authority_bootstrap(
        aws_config_path=config_path,
        private_receipt_path=_private_path(tmp_path),
        root=_repository(tmp_path),
        environment={
            "AWS_CONFIG_FILE": str(config_path),
            "AWS_ENDPOINT_URL_SSO": "https://example.invalid",
        },
        configured_profiles=(SOURCE_PROFILE,),
        session_factory=forbidden_session,
        repository_guard=lambda _root: None,
        clock=lambda: NOW,
        nonce_factory=lambda: NONCE,
    )

    assert result["status"] == "FAIL"
    assert result["reasons"] == ["AWS_ENDPOINT_OVERRIDE_FORBIDDEN"]
    assert config_path.read_bytes() == before


def test_private_receipt_must_be_ignored_in_repo_and_not_collide_with_config(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    external = tmp_path / "external.json"
    with pytest.raises(
        bootstrap.BootstrapFailure,
        match=r"^PRIVATE_RECEIPT_REPOSITORY_PATH_FORBIDDEN$",
    ):
        bootstrap.run_authority_bootstrap(
            private_receipt_path=external,
            root=repository,
            repository_guard=lambda _root: None,
        )
    assert not external.exists()

    collision = repository / ".aioa-private" / "collision.json"
    with pytest.raises(
        bootstrap.BootstrapFailure,
        match=r"^PRIVATE_RECEIPT_PATH_COLLISION$",
    ):
        bootstrap.run_authority_bootstrap(
            aws_config_path=collision,
            private_receipt_path=collision,
            root=repository,
            repository_guard=lambda _root: None,
        )
    assert not collision.exists()


def test_existing_valid_private_receipt_is_preserved_before_reuse(
    tmp_path: Path,
) -> None:
    source_sts = FakeSts(_identity(SOURCE_ARN), assume_response=_assume_response())
    temporary_sts = FakeSts(_identity(ASSUMED_ROLE_ARN))
    _result, _config_path, private_path, *_sessions = _run(
        tmp_path,
        source_sts=source_sts,
        temporary_sts=temporary_sts,
    )
    original = private_path.read_bytes()

    bootstrap._preserve_existing_private_receipt(private_path)
    backups = list(private_path.parent.glob("authority.previous-*.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    bootstrap._preserve_existing_private_receipt(private_path)
    assert list(private_path.parent.glob("authority.previous-*.json")) == backups


def test_repository_guard_requires_main_origin_clean_and_phase1_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path)
    subprocess.run(("git", "checkout", "-B", "main"), cwd=root, check=True, capture_output=True)
    subprocess.run(
        ("git", "config", "user.email", "fixture@example.invalid"),
        cwd=root,
        check=True,
    )
    subprocess.run(("git", "config", "user.name", "Fixture"), cwd=root, check=True)
    subprocess.run(("git", "add", ".gitignore"), cwd=root, check=True)
    subprocess.run(("git", "commit", "-m", "fixture"), cwd=root, check=True, capture_output=True)
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ("git", "update-ref", "refs/remotes/origin/main", head),
        cwd=root,
        check=True,
    )
    subprocess.run(
        ("git", "tag", bootstrap.PHASE1_TAG, head),
        cwd=root,
        check=True,
    )
    monkeypatch.setattr(bootstrap, "EXPECTED_PHASE1_TAG", head)

    bootstrap._default_repository_guard(root)
    (root / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(
        bootstrap.BootstrapFailure,
        match=r"^REPOSITORY_WORKTREE_NOT_CLEAN$",
    ):
        bootstrap._default_repository_guard(root)


def test_default_factories_bound_nested_credential_provider_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import boto3
    import botocore.session

    cores: list[FakeCoreSession] = []
    boto_calls: list[dict[str, object]] = []

    class FakeCoreSession:
        def __init__(self) -> None:
            self.profile: str | None = None
            self.config: Config | None = None
            self.credentials: tuple[str, str, str] | None = None

        def set_config_variable(self, name: str, value: str) -> None:
            assert name == "profile"
            self.profile = value

        def set_default_client_config(self, config: Config) -> None:
            self.config = config

        def set_credentials(self, access: str, secret: str, token: str) -> None:
            self.credentials = (access, secret, token)

    def new_core() -> FakeCoreSession:
        core = FakeCoreSession()
        cores.append(core)
        return core

    def boto_session(**kwargs: object) -> object:
        boto_calls.append(dict(kwargs))
        return object()

    monkeypatch.setattr(botocore.session, "get_session", new_core)
    monkeypatch.setattr(boto3, "Session", boto_session)

    bootstrap._default_session_factory(SOURCE_PROFILE)
    bootstrap._default_temporary_session_factory(
        {
            "aws_access_key_id": "temporary-access-id",
            "aws_secret_access_key": "temporary-secret",
            "aws_session_token": "temporary-token",
        }
    )

    assert len(cores) == 2
    assert cores[0].profile == SOURCE_PROFILE
    assert cores[0].credentials is None
    assert cores[1].credentials == (
        "temporary-access-id",
        "temporary-secret",
        "temporary-token",
    )
    for core in cores:
        assert core.config is not None
        assert core.config.region_name == bootstrap.REGION
        assert core.config.retries["total_max_attempts"] == 1
        assert core.config.ignore_configured_endpoint_urls is True
        assert core.config.connect_timeout == bootstrap.CONNECT_TIMEOUT_SECONDS
        assert core.config.read_timeout == bootstrap.READ_TIMEOUT_SECONDS
    assert boto_calls == [
        {"botocore_session": cores[0], "region_name": bootstrap.REGION},
        {"botocore_session": cores[1], "region_name": bootstrap.REGION},
    ]
