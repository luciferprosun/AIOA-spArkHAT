import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import scripts.b4_network_guard as network_guard
import scripts.run_b4_hardening_gate as gate

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "run_b4_hardening_gate.py"


def test_b4_gate_lists_exact_required_scenarios_without_running_them() -> None:
    result = subprocess.run(
        (sys.executable, str(SCRIPT), "--list"),
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    )
    scenarios = json.loads(result.stdout)

    assert set(scenarios) == {
        "APPROVAL_TAMPER_REJECTED",
        "APPROVE_NORMAL",
        "CORRUPTED_STATE_SAFE_FAILURE",
        "DENY_NORMAL",
        "EVIDENCE_TAMPER_DETECTED",
        "INVALID_INPUT_REJECTED",
        "NETWORK_EGRESS_ZERO",
        "PROVIDER_FAILURE_SAFE",
        "RECOVERY_AFTER_INTERRUPTION",
        "REPLAY_REJECTED",
        "SECRET_REDACTION_PASS",
    }
    assert all(node.startswith("tests/") and "::test_" in node for node in scenarios.values())


def test_b4_receipt_is_bound_and_declares_zero_external_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate, "_git_head", lambda: "a" * 40)
    results = (
        {
            "duration_milliseconds": 1,
            "outcome": "PASS",
            "proof_node": "tests/unit/test_example.py::test_example",
            "proof_tests": 1,
            "scenario": "EXAMPLE",
        },
    )

    receipt = gate._receipt(results)
    digest = receipt.pop("receipt_sha256")
    canonical = json.dumps(
        receipt,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert digest == hashlib.sha256(canonical).hexdigest()
    assert receipt["status"] == "PASS"
    assert receipt["aws_calls"] == receipt["aws_mutations"] == 0
    assert receipt["external_network_calls"] == 0
    assert receipt["external_deployments"] == receipt["remote_pushes"] == 0
    assert receipt["network_guard"] == "LOOPBACK_ONLY_FAIL_CLOSED"


def test_b4_receipt_output_is_private_and_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_root = tmp_path / "private"
    monkeypatch.setattr(gate, "OUTPUT_ROOT", private_root)
    output = private_root / "receipt.json"

    gate._write(output, "{}\n")

    assert output.read_text(encoding="utf-8") == "{}\n"
    assert output.stat().st_mode & 0o777 == 0o600
    assert private_root.stat().st_mode & 0o777 == 0o700
    with pytest.raises(RuntimeError, match="OUTSIDE_PRIVATE"):
        gate._write(tmp_path / "outside.json", "{}\n")


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (("127.0.0.1", 8765), True),
        (("::1", 8765, 0, 0), True),
        (("localhost", 8765), True),
        ("/tmp/aioa.sock", True),
        (("8.8.8.8", 53), False),
        (("example.invalid", 443), False),
        (object(), False),
    ],
)
def test_b4_network_guard_allows_only_loopback_or_unix(
    address: object,
    expected: bool,
) -> None:
    assert network_guard._is_loopback(address) is expected
