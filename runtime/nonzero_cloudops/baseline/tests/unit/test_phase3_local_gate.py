from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import pytest
from scripts.phase3.run_local_gate import (
    ExecutedCommand,
    LocalGateError,
    _json_stdout,
    _priority_evidence,
    _private_write,
    _pytest_totals,
)


def _command(stdout: str) -> ExecutedCommand:
    return ExecutedCommand(
        command_id="TEST",
        argv=("test",),
        returncode=0,
        duration_seconds=0.1,
        output_sha256=hashlib.sha256(stdout.encode()).hexdigest(),
        log_path=".local/test.log",
        stdout=stdout,
    )


def test_priority_evidence_requires_every_gate_and_positive_proof_count() -> None:
    payload = (
        '{"status":"PASS","gate_count":15,"gates_pass":15,"gates_fail":0,'
        '"gates_skipped":0,"gates":['
        + ",".join('{"proof_tests":1}' for _ in range(15))
        + "]}"
    )

    evidence = _priority_evidence(_command(payload), expected=15)

    assert evidence.passed_gates == evidence.expected_gates == 15
    assert evidence.proof_tests == 15
    assert evidence.skipped == 0


@pytest.mark.parametrize(
    "payload",
    (
        "not-json",
        "[]",
        '{"status":"FAIL"}',
        '{"status":"PASS","gate_count":15,"gates_pass":14,"gates_fail":1,'
        '"gates_skipped":0,"gates":[]}',
    ),
)
def test_priority_evidence_fails_closed_for_ambiguous_output(payload: str) -> None:
    with pytest.raises(LocalGateError):
        _priority_evidence(_command(payload), expected=15)


def test_junit_totals_are_parsed_and_empty_or_invalid_documents_fail(tmp_path: Path) -> None:
    valid = tmp_path / "valid.xml"
    valid.write_text(
        '<testsuites><testsuite tests="4" failures="0" errors="0" skipped="0" '
        'time="1.25" /></testsuites>',
        encoding="utf-8",
    )
    assert _pytest_totals(valid) == {
        "tests": 4,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "time": 1.25,
    }

    invalid = tmp_path / "invalid.xml"
    invalid.write_text("<broken", encoding="utf-8")
    with pytest.raises(LocalGateError, match="LOCAL_GATE_JUNIT_INVALID"):
        _pytest_totals(invalid)


def test_private_output_rejects_symlink_and_json_parser_requires_object(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(LocalGateError, match="LOCAL_GATE_OUTPUT_SYMLINK_FORBIDDEN"):
        _private_write(link, "replace")
    assert target.read_text(encoding="utf-8") == "preserve"

    with pytest.raises(LocalGateError, match="INVALID"):
        _json_stdout(_command("[]"), reason="INVALID")


def test_development_environment_declares_the_offline_wheel_backend() -> None:
    root = Path(__file__).resolve().parents[2]
    document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert document["build-system"] == {
        "requires": ["setuptools>=75"],
        "build-backend": "setuptools.build_meta",
    }
    assert "setuptools>=75,<83" in document["project"]["optional-dependencies"]["dev"]
