import json
import subprocess
import sys
from pathlib import Path

from scripts.run_p0_gate import (
    SourceEvidence,
    parse_junit,
    validate_node_definition,
    validate_source_evidence,
)

ROOT = Path(__file__).parents[2]


def test_p0_matrix_definition_and_static_evidence_are_all_valid() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_p0_gate.py", "--validate-only", "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["gate_count"] == 15
    assert payload["gates_pass"] == 15
    assert payload["gates_fail"] == 0


def test_p0_document_names_every_gate_and_runner_mode() -> None:
    document = (ROOT / "docs/architecture/day-13-p0-gate.md").read_text(encoding="utf-8")
    armor_document = (
        ROOT / "docs/architecture/day-13-p0-emergency-disable.md"
    ).read_text(encoding="utf-8")

    assert all(f"P0-{number:02d}" in document for number in range(1, 16))
    assert "scripts/run_p0_gate.py" in document
    assert "--json" in document
    assert "--validate-only" in document
    assert "AIOA_EMERGENCY_EXECUTION_DISABLED" in armor_document
    assert "EXECUTOR_EMERGENCY_DISABLED" in armor_document
    assert "AU-2 tamper-evident audit continuity is not implemented" in armor_document
    assert "AU-3 reviewer evidence manifest is not implemented" in armor_document
    assert "Day 14 circuit-breaker work has not started" in armor_document


def test_p0_runner_rejects_stale_source_symbol_and_pytest_node() -> None:
    source_reasons = validate_source_evidence(
        SourceEvidence(
            "src/aioa_cloudops_agent/agent/factory.py",
            symbols=("REMOVED_AUTHORITY_SYMBOL",),
        )
    )
    node_reasons = validate_node_definition(
        "tests/unit/test_strands_agent.py::test_removed_p0_proof"
    )

    assert source_reasons == (
        "SYMBOL_MISSING:src/aioa_cloudops_agent/agent/factory.py::"
        "REMOVED_AUTHORITY_SYMBOL",
    )
    assert node_reasons == (
        "PYTEST_NODE_MISSING:tests/unit/test_strands_agent.py::test_removed_p0_proof",
    )


def test_p0_runner_detects_skipped_required_proof(tmp_path: Path) -> None:
    report = tmp_path / "skipped.xml"
    report.write_text(
        '<testsuite tests="1" failures="0" errors="0" skipped="1" />',
        encoding="utf-8",
    )

    proof = parse_junit(report, 0)

    assert proof.tests == 1
    assert proof.skipped == 1
