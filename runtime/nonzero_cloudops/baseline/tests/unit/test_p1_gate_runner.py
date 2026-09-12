import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from scripts.run_p1_gate import GATES, _validate_matrix_shape, validate_gate_definition

ROOT = Path(__file__).resolve().parents[2]


def test_p1_matrix_has_exact_six_ordered_nonempty_gates() -> None:
    assert tuple(gate.gate_id for gate in GATES) == tuple(
        f"P1-{number:02d}" for number in range(1, 7)
    )
    assert all(gate.sources and gate.pytest_nodes for gate in GATES)
    assert GATES[-1].command_proof is not None
    assert _validate_matrix_shape() == ()


def test_p1_gate_definitions_resolve_exact_sources_nodes_and_static_checks() -> None:
    assert all(validate_gate_definition(gate) == () for gate in GATES)


def test_p1_validator_fails_a_stale_exact_pytest_node() -> None:
    stale = replace(
        GATES[0],
        pytest_nodes=("tests/unit/test_safety_hardening.py::test_removed_proof",),
    )

    assert validate_gate_definition(stale) == (
        "PYTEST_NODE_MISSING:tests/unit/test_safety_hardening.py::test_removed_proof",
    )


def test_p1_validate_only_json_is_stable_and_green() -> None:
    command = [sys.executable, "scripts/run_p1_gate.py", "--validate-only", "--json"]
    first = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    second = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["status"] == "PASS"
    assert payload["gate_count"] == payload["gates_pass"] == 6
    assert payload["gates_fail"] == payload["gates_skipped"] == 0
