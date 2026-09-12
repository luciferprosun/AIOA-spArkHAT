from __future__ import annotations

import json
import socket
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.phase3.build_deployment_contract import DEFAULT_CONTRACT
from scripts.phase3.run_preflight import _exit_code, _write_private

from aioa_cloudops_agent.release.preflight import (
    CHECKS,
    CheckClass,
    CheckOutcome,
    PreflightError,
    PreflightMode,
    PreflightStatus,
    _ensure_public_safe,
    load_aws_fixture,
    run_preflight,
    sanitized_local_environment,
    validate_preflight_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "phase3" / "aws-preflight-pass.json"
HEAD = "a" * 40
NOW = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


class FakeRunner:
    def __init__(self, *, dirty: bool = False, remote: str = HEAD) -> None:
        self.dirty = dirty
        self.remote = remote
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def __call__(
        self,
        command: object,
        _cwd: Path,
        environment: object,
        _timeout_seconds: int,
    ) -> SimpleNamespace:
        assert isinstance(command, tuple)
        assert isinstance(environment, dict)
        self.calls.append((command, environment))
        if command == ("git", "rev-parse", "HEAD"):
            return SimpleNamespace(returncode=0, stdout=HEAD + "\n", stderr="")
        if command == ("git", "branch", "--show-current"):
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        if command == ("git", "status", "--porcelain"):
            output = " M unsafe.txt\n" if self.dirty else ""
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
        if command == ("git", "rev-parse", "refs/remotes/origin/main"):
            return SimpleNamespace(returncode=0, stdout=self.remote + "\n", stderr="")
        if command[-2:] == ("--validate-only", "--json"):
            return SimpleNamespace(
                returncode=0,
                stdout='{"status":"PASS"}\n',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command!r}")


def _fixture_receipt(*, runner: FakeRunner | None = None):
    return run_preflight(
        root=ROOT,
        contract_path=DEFAULT_CONTRACT,
        expected_head=HEAD,
        mode=PreflightMode.OFFLINE_AWS_FIXTURE,
        fixture_path=FIXTURE,
        clock=lambda: NOW,
        runner=runner or FakeRunner(),
        environment={
            "PATH": "/usr/bin",
            "AWS_ACCESS_KEY_ID": "must-not-cross-boundary",
            "AWS_SECRET_ACCESS_KEY": "must-not-cross-boundary",
            "AWS_SESSION_TOKEN": "must-not-cross-boundary",
            "AWS_PROFILE": "must-not-cross-boundary",
            "BEDROCK_MODEL_ID": "must-not-cross-boundary",
            "AIOA_ALLOW_LIVE_SANDBOX_STOP": "true",
            "SANDBOX_INSTANCE_ID": "must-not-cross-boundary",
        },
    )


def test_check_catalog_has_exact_classes_and_no_mutation_check_is_local() -> None:
    assert len(CHECKS) == 16
    assert [item.check_id for item in CHECKS] == [
        f"P3-PF-{index:03d}" for index in range(1, 17)
    ]
    assert {item.classification for item in CHECKS[:5]} == {CheckClass.LOCAL}
    assert {item.classification for item in CHECKS[5:15]} == {
        CheckClass.FUTURE_READ_ONLY_AWS
    }
    assert CHECKS[15].classification is CheckClass.REQUIRES_EXPLICIT_MUTATION_APPROVAL


def test_fixture_preflight_executes_local_and_mocked_reads_but_not_approval() -> None:
    receipt = _fixture_receipt()

    assert receipt.status is PreflightStatus.BLOCKED_EXTERNAL
    assert receipt.mode is PreflightMode.OFFLINE_AWS_FIXTURE
    assert receipt.repo_sha == receipt.expected_repo_sha == HEAD
    assert len(receipt.checks) == 16
    assert all(item.outcome is CheckOutcome.PASS for item in receipt.checks[:15])
    assert receipt.checks[15].outcome is CheckOutcome.NOT_RUN_EXTERNAL
    assert receipt.checks[15].executed is False
    assert receipt.checks[15].fixture is False
    assert all(item.fixture for item in receipt.checks[5:15])
    assert receipt.network_connections == receipt.aws_mutations == receipt.live_receipts == 0
    assert len(receipt.deployment_contract_external_blockers) == 8
    assert validate_preflight_receipt(receipt.model_dump(mode="json")) == receipt


def test_local_only_mode_never_promotes_unexecuted_aws_checks() -> None:
    receipt = run_preflight(
        root=ROOT,
        contract_path=DEFAULT_CONTRACT,
        expected_head=HEAD,
        mode=PreflightMode.LOCAL_ONLY,
        clock=lambda: NOW,
        runner=FakeRunner(),
        environment={"PATH": "/usr/bin"},
    )

    assert all(item.outcome is CheckOutcome.PASS for item in receipt.checks[:5])
    assert all(
        item.outcome is CheckOutcome.NOT_RUN_EXTERNAL and not item.executed
        for item in receipt.checks[5:]
    )
    assert receipt.status is PreflightStatus.BLOCKED_EXTERNAL


def test_library_requires_an_explicit_local_command_runner() -> None:
    with pytest.raises(PreflightError, match="PREFLIGHT_LOCAL_COMMAND_RUNNER_REQUIRED"):
        run_preflight(
            root=ROOT,
            contract_path=DEFAULT_CONTRACT,
            expected_head=HEAD,
            environment={"PATH": "/usr/bin"},
        )


def test_preflight_strips_all_ambient_authority_from_local_child_commands() -> None:
    runner = FakeRunner()
    _fixture_receipt(runner=runner)

    assert runner.calls
    for _command, environment in runner.calls:
        assert environment["AWS_CONFIG_FILE"] == "/dev/null"
        assert environment["AWS_SHARED_CREDENTIALS_FILE"] == "/dev/null"
        assert environment["AWS_EC2_METADATA_DISABLED"] == "true"
        assert "AWS_ACCESS_KEY_ID" not in environment
        assert "AWS_SECRET_ACCESS_KEY" not in environment
        assert "AWS_SESSION_TOKEN" not in environment
        assert "AWS_PROFILE" not in environment
        assert "BEDROCK_MODEL_ID" not in environment
        assert "AIOA_ALLOW_LIVE_SANDBOX_STOP" not in environment
        assert "SANDBOX_INSTANCE_ID" not in environment


def test_offline_fixture_path_opens_no_network_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network attempted")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    receipt = _fixture_receipt()

    assert receipt.network_connections == 0


@pytest.mark.parametrize(
    ("field", "expected_outcome", "reason"),
    (
        (
            "credential_source_present",
            CheckOutcome.BLOCKED_EXTERNAL,
            "AWS_CREDENTIAL_SOURCE_NOT_AVAILABLE",
        ),
        (
            "expected_account_match",
            CheckOutcome.FAIL,
            "ACCOUNT_OR_REGION_MISMATCH",
        ),
        (
            "read_write_roles_separate",
            CheckOutcome.FAIL,
            "ROLE_PERMISSION_EXPECTATION_MISMATCH",
        ),
        (
            "bedrock_model_access",
            CheckOutcome.BLOCKED_EXTERNAL,
            "BEDROCK_MODEL_ACCESS_NOT_PROVEN",
        ),
        (
            "resource_name_collisions_absent",
            CheckOutcome.FAIL,
            "RESOURCE_NAME_COLLISION_DETECTED",
        ),
        (
            "sandbox_tag_exact",
            CheckOutcome.FAIL,
            "SANDBOX_OR_CLOUDWATCH_EVIDENCE_MISMATCH",
        ),
        (
            "artifact_bucket_controls_match",
            CheckOutcome.FAIL,
            "BUCKET_OR_SECRET_CONTROL_MISMATCH",
        ),
        (
            "budget_owner_and_notifications_match",
            CheckOutcome.BLOCKED_EXTERNAL,
            "BUDGET_OWNER_NOTIFICATION_NOT_PROVEN",
        ),
    ),
)
def test_fixture_failures_are_typed_and_never_silently_pass(
    tmp_path: Path,
    field: str,
    expected_outcome: CheckOutcome,
    reason: str,
) -> None:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value[field] = False
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    receipt = run_preflight(
        root=ROOT,
        contract_path=DEFAULT_CONTRACT,
        expected_head=HEAD,
        mode=PreflightMode.OFFLINE_AWS_FIXTURE,
        fixture_path=fixture,
        clock=lambda: NOW,
        runner=FakeRunner(),
        environment={"PATH": "/usr/bin"},
    )

    result = next(item for item in receipt.checks if reason in item.reasons)
    assert result.outcome is expected_outcome
    assert receipt.status is (
        PreflightStatus.FAIL
        if expected_outcome is CheckOutcome.FAIL
        else PreflightStatus.BLOCKED_EXTERNAL
    )


def test_dirty_mismatched_or_unexpected_head_fails_local_preflight() -> None:
    dirty = _fixture_receipt(runner=FakeRunner(dirty=True))
    assert dirty.status is PreflightStatus.FAIL
    assert "WORKTREE_NOT_CLEAN" in dirty.checks[2].reasons

    remote = _fixture_receipt(runner=FakeRunner(remote="b" * 40))
    assert remote.status is PreflightStatus.FAIL
    assert "ORIGIN_MAIN_MISMATCH" in remote.checks[2].reasons

    expected = run_preflight(
        root=ROOT,
        contract_path=DEFAULT_CONTRACT,
        expected_head="b" * 40,
        mode=PreflightMode.LOCAL_ONLY,
        clock=lambda: NOW,
        runner=FakeRunner(),
        environment={"PATH": "/usr/bin"},
    )
    assert expected.status is PreflightStatus.FAIL
    assert "EXPECTED_HEAD_MISMATCH" in expected.checks[1].reasons


def test_fixture_parser_rejects_extra_duplicate_nonfinite_and_sensitive_values(
    tmp_path: Path,
) -> None:
    extra = json.loads(FIXTURE.read_text(encoding="utf-8"))
    extra["token"] = "not-allowed"
    path = tmp_path / "extra.json"
    path.write_text(json.dumps(extra), encoding="utf-8")
    with pytest.raises(PreflightError, match="AWS_PREFLIGHT_FIXTURE_INVALID"):
        load_aws_fixture(path)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(PreflightError, match="AWS_PREFLIGHT_FIXTURE_INVALID"):
        load_aws_fixture(duplicate)

    nonfinite = tmp_path / "nan.json"
    nonfinite.write_text('{"schema_version":NaN}', encoding="utf-8")
    with pytest.raises(PreflightError, match="AWS_PREFLIGHT_FIXTURE_INVALID"):
        load_aws_fixture(nonfinite)

    with pytest.raises(
        PreflightError,
        match="PREFLIGHT_RECEIPT_SENSITIVE_VALUE_FORBIDDEN",
    ):
        _ensure_public_safe({"value": "AKIA" + "ABCDEFGHIJKLMNOP"})
    with pytest.raises(
        PreflightError,
        match="PREFLIGHT_RECEIPT_SENSITIVE_VALUE_FORBIDDEN",
    ):
        _ensure_public_safe({"value": "123456789012"})


def test_receipt_hash_and_check_results_reject_tampering() -> None:
    receipt = _fixture_receipt()
    payload = receipt.model_dump(mode="json")
    payload["network_connections"] = 1
    with pytest.raises(PreflightError, match="PREFLIGHT_RECEIPT_INVALID"):
        validate_preflight_receipt(payload)

    payload = receipt.model_dump(mode="json")
    payload["checks"][0]["outcome"] = "FAIL"
    payload["checks"][0]["reasons"] = ["FORGED"]
    with pytest.raises(PreflightError, match="PREFLIGHT_RECEIPT_INVALID"):
        validate_preflight_receipt(payload)


def test_private_receipt_writer_is_mode_0600_and_rejects_symlink(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    _write_private(output, "{}\n")

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.read_text(encoding="utf-8") == "{}\n"

    target = tmp_path / "target.json"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(PreflightError, match="PREFLIGHT_OUTPUT_SYMLINK_FORBIDDEN"):
        _write_private(link, "changed\n")
    assert target.read_text(encoding="utf-8") == "preserve"


def test_stable_exit_codes_distinguish_pass_fail_and_external_block() -> None:
    assert _exit_code(PreflightStatus.PASS) == 0
    assert _exit_code(PreflightStatus.FAIL) == 1
    assert _exit_code(PreflightStatus.BLOCKED_EXTERNAL) == 3
    assert _exit_code("UNKNOWN") == 1


def test_sanitized_environment_ignores_endpoint_overrides_and_project_authority() -> None:
    result = sanitized_local_environment(
        {
            "PATH": "/safe",
            "AWS_ENDPOINT_URL": "https://private.invalid",
            "AWS_ENDPOINT_URL_STS": "https://private.invalid",
            "AWS_DEFAULT_REGION": "private",
            "PYTHONPATH": "/private",
            "AIOA_UNREVIEWED": "true",
            "BEDROCK_MODEL_ID": "private",
            "SANDBOX_INSTANCE_ID": "private",
        }
    )

    assert result["PATH"] == "/safe"
    assert result["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"] == "true"
    assert not any("private" in value for value in result.values())
