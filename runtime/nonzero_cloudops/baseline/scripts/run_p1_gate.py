#!/usr/bin/env python3
"""Run the canonical Day 14 P1 resilience proof matrix without contacting AWS."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prove_clean_clone import validate_readme_contract  # noqa: E402
from scripts.run_p0_gate import (  # noqa: E402
    GateResult,
    PytestProof,
    SourceEvidence,
    _check_agent_topology,
    _check_mutation_surface,
    _check_tracked_secret_scan,
    parse_junit,
    source,
    validate_node_definition,
    validate_source_evidence,
)


@dataclass(frozen=True, slots=True)
class GateEvidence:
    gate_id: str
    name: str
    sources: tuple[SourceEvidence, ...]
    pytest_nodes: tuple[str, ...]
    static_checks: tuple[str, ...] = ()
    command_proof: tuple[str, ...] | None = None


GATES = (
    GateEvidence(
        "P1-01",
        "Injection denial",
        (
            source(
                "src/aioa_cloudops_agent/safety/policy.py",
                "_STRUCTURALLY_DENIED_TOOL",
                "DefaultDenyToolPolicy.evaluate",
                "DefaultDenyToolPolicy._durable_context",
            ),
            source(
                "src/aioa_cloudops_agent/nz/authority.py",
                "_CAPABILITY_AUTHORITY",
                "authority_for_capability",
            ),
            source(
                "src/aioa_cloudops_agent/agent/hitl.py",
                "DurableProposalHumanInTheLoop.before_tool_call",
            ),
        ),
        (
            "tests/unit/test_safety_hardening.py::"
            "test_prompt_injection_corpus_cannot_create_a_capability",
            "tests/unit/test_safety_hardening.py::"
            "test_unknown_tool_alias_defaults_to_policy_denial",
            "tests/unit/test_safety_hardening.py::"
            "test_scope_substitution_and_privileged_extra_fields_are_denied",
            "tests/unit/test_safety_hardening.py::"
            "test_fake_approval_and_stop_options_cannot_cross_native_hitl",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_denied_injection_is_linked_and_redacted_before_dispatch",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_policy_denial_closes_the_invocation_before_later_safe_looking_tools",
        ),
        ("agent_topology", "mutation_surface", "tracked_secret_scan"),
    ),
    GateEvidence(
        "P1-02",
        "Ambiguous metrics",
        (
            source(
                "src/aioa_cloudops_agent/cloudops/read_utilization.py",
                "ReadUtilizationMetricsService.read",
                "ReadUtilizationMetricsService.read_result",
                "ReadUtilizationMetricsService._normalize_datapoints",
            ),
            source(
                "src/aioa_cloudops_agent/cloudops/metrics_models.py",
                "UtilizationEvidence.validate_evidence_integrity",
                "_classification",
            ),
            source(
                "src/aioa_cloudops_agent/cloudops/build_evidence.py",
                "BuildRemediationEvidenceService.build_result",
            ),
        ),
        (
            "tests/unit/test_read_utilization_metrics.py::"
            "test_cloudwatch_ambiguity_matrix_never_guesses_zero",
            "tests/unit/test_read_utilization_metrics.py::"
            "test_empty_or_insufficient_data_remains_ambiguous",
            "tests/unit/test_build_remediation_evidence.py::"
            "test_ambiguous_utilization_cannot_form_evidence_or_proposal",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_ambiguous_cloudwatch_evidence_never_creates_idle_proposal",
        ),
    ),
    GateEvidence(
        "P1-03",
        "Circuit breaker",
        (
            source(
                "src/aioa_cloudops_agent/safety/circuit.py",
                "CircuitState",
                "CircuitDependency",
                "CircuitBreakerSettings",
                "CircuitOpenError",
                "CircuitStateUnavailableError",
                "DependencyCircuitBreaker.acquire",
                "DependencyCircuitBreaker.record_success",
                "DependencyCircuitBreaker.record_transient_failure",
            ),
            source(
                "src/aioa_cloudops_agent/safety/retry.py",
                "RetryOperationClass",
                "AUTOMATIC_RETRY_ALLOWED",
                "ReadRetryStateUnavailableError",
                "is_known_transient_read_error",
                "BoundedReadRetry.run",
            ),
            source(
                "src/aioa_cloudops_agent/agent/factory.py",
                "PrimaryAgentRuntime",
                "create_primary_agent",
            ),
        ),
        (
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_terminal_transient_read_below_threshold_stays_closed_after_existing_retry_cap",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_threshold_transient_failure_opens_with_dependency_unavailable_result",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_open_circuit_suppresses_provider_calls_during_cooldown",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_cooldown_allows_exactly_one_single_call_half_open_probe",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_successful_half_open_probe_closes_and_resets_counter",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_failed_half_open_probe_reopens_with_fresh_bounded_cooldown",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_retry_sleeper_failure_is_redacted_and_opens_without_repeat_call",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_access_denied_validation_and_policy_outcomes_do_not_increment_transient_counter",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_permanent_provider_code_wins_over_transient_http_status",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_allowlisted_botocore_transport_errors_count_as_transient",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_mutation_and_ambiguous_ack_classes_cannot_enter_retry_or_circuit",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_unavailable_clock_or_breaker_state_fails_closed_before_dependency_call",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_two_concurrent_half_open_attempts_allow_only_one_probe",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_circuit_reason_is_redacted_and_trace_linked",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_circuit_adds_no_tool_iam_network_or_mutation_surface",
            "tests/unit/test_dependency_circuit_breaker.py::"
            "test_circuit_limits_are_finite_validated_and_dependency_specific",
            "tests/unit/test_safety_hardening.py::"
            "test_transient_read_retries_only_to_the_configured_cap",
            "tests/unit/test_safety_hardening.py::"
            "test_access_denied_read_is_permanent_and_not_retried",
            "tests/unit/test_safety_hardening.py::"
            "test_ambiguous_mutation_is_structurally_excluded_from_automatic_retry",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_ambiguous_stop_acknowledgement_is_not_retried",
        ),
        ("circuit_boundary", "agent_topology", "mutation_surface"),
    ),
    GateEvidence(
        "P1-04",
        "Permission separation",
        (
            source(
                "infra/iam/cloudops-orchestrator-policy.json",
                anchors=("lambda:InvokeFunction",),
            ),
            source(
                "infra/iam/cloudops-remediation-policy.json",
                anchors=("ec2:StopInstances",),
            ),
            source(
                "infra/sam/template.yaml",
                anchors=("OrchestratorRole", "RemediationExecutorRole"),
            ),
        ),
        (
            "tests/unit/test_iam_policies.py::"
            "test_orchestrator_policy_is_exact_read_model_state_secret_and_alias_authority",
            "tests/unit/test_infrastructure_contract.py::"
            "test_orchestrator_iam_has_exact_bedrock_profile_models_and_no_ec2_write",
            "tests/unit/test_infrastructure_contract.py::"
            "test_private_executor_has_fresh_read_plus_separate_exact_scoped_stop",
            "tests/unit/test_iam_policies.py::"
            "test_no_generalized_write_permission_agentcore_or_account_literal_exists",
            "tests/unit/test_cloudops_security.py::"
            "test_executable_source_contains_no_ec2_mutation_calls",
            "tests/unit/test_cloudops_security.py::"
            "test_infrastructure_isolates_the_only_stop_authority_from_read_only_policy",
        ),
        ("iam_separation", "mutation_surface"),
    ),
    GateEvidence(
        "P1-05",
        "Trace continuity",
        (
            source(
                "src/aioa_cloudops_agent/cloudops/models.py",
                "InvestigationIdentity",
            ),
            source(
                "src/aioa_cloudops_agent/agent/tracing.py",
                "build_agent_trace_attributes",
            ),
            source(
                "src/aioa_cloudops_agent/remediation/command.py",
                "build_stop_execution_command",
            ),
            source(
                "src/aioa_cloudops_agent/verification/coordinator.py",
                "BoundedVerificationCoordinator._persist_success",
                "BoundedVerificationCoordinator._append_event",
            ),
        ),
        (
            "tests/integration/test_human_approved_remediation_e2e.py::"
            "test_full_workflow_preserves_trace_lineage_across_agent_tools_store_execution_and_verification",
            "tests/integration/test_human_approved_remediation_e2e.py::"
            "test_substituted_workflow_identity_fails_closed_without_execution",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_trace_identity_and_evidence_hash_propagate_through_audit_and_checkpoint",
            "tests/integration/test_durable_hitl_approval_flow.py::"
            "test_positive_native_resume_persists_approval_before_safe_tool_boundary",
            "tests/unit/test_recovery_reconciliation.py::"
            "test_recovery_audit_event_links_run_trace_correlation_and_proposal",
            "tests/unit/test_recovery_reconciliation.py::"
            "test_cross_run_proposal_reference_is_rejected_before_reconciliation",
        ),
        ("trace_contract",),
    ),
    GateEvidence(
        "P1-06",
        "Clean clone",
        (
            source(
                "README.md",
                anchors=(
                    "python3.12 -m venv .venv",
                    '.venv/bin/python -m pip install ".[dev]"',
                    ".venv/bin/python scripts/run_p0_gate.py",
                    ".venv/bin/python scripts/run_p1_gate.py",
                ),
            ),
            source(
                "scripts/prove_clean_clone.py",
                "validate_readme_contract",
                "prove_clean_clone",
                "main",
            ),
            source("pyproject.toml", anchors=('dev = [', 'requires-python = ">=3.12"')),
        ),
        (
            "tests/unit/test_clean_clone_reproducibility.py::"
            "test_readme_contains_exact_public_install_and_verification_contract",
            "tests/unit/test_clean_clone_reproducibility.py::"
            "test_readme_contract_fails_when_a_harness_setup_step_is_missing",
            "tests/unit/test_clean_clone_reproducibility.py::"
            "test_harness_plan_uses_full_no_local_clone_and_fresh_noneditable_install",
            "tests/unit/test_clean_clone_reproducibility.py::"
            "test_missing_bootstrap_executable_is_a_fixed_failure_without_traceback",
            "tests/unit/test_clean_clone_reproducibility.py::"
            "test_harness_scrubs_aws_credentials_and_runs_only_public_safe_smoke",
            "tests/unit/test_clean_clone_reproducibility.py::"
            "test_validate_only_is_deterministic_and_exposes_no_local_paths",
        ),
        ("clean_clone_contract",),
        (
            sys.executable,
            "scripts/prove_clean_clone.py",
            "--mode",
            "auto",
            "--json",
        ),
    ),
)


def _check_circuit_boundary() -> tuple[str, ...]:
    reasons: list[str] = []
    forbidden_symbols = {
        "BoundedReadRetry",
        "DependencyCircuitBreaker",
        "ReadRetryStateUnavailableError",
        "RetryOperationClass",
    }

    def forbidden_symbol(name: str) -> bool:
        return name in forbidden_symbols or name.startswith("Circuit")

    forbidden_roots = (
        ROOT / "src/aioa_cloudops_agent/remediation",
        ROOT / "src/aioa_cloudops_agent/recovery",
    )
    for package in forbidden_roots:
        for path in sorted(package.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            boundary_crossed = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module.endswith((".safety.retry", ".safety.circuit")) or (
                        module.endswith(".safety")
                        and any(forbidden_symbol(alias.name) for alias in node.names)
                    ):
                        boundary_crossed = True
                elif isinstance(node, ast.Import):
                    if any(
                        alias.name.endswith((".safety.retry", ".safety.circuit"))
                        for alias in node.names
                    ):
                        boundary_crossed = True
                elif isinstance(node, (ast.Name, ast.Attribute)):
                    identifier = node.id if isinstance(node, ast.Name) else node.attr
                    if forbidden_symbol(identifier):
                        boundary_crossed = True
            if boundary_crossed:
                reasons.append(f"CIRCUIT_MUTATION_IMPORT:{path.relative_to(ROOT)}")
    retry_source = (ROOT / "src/aioa_cloudops_agent/safety/retry.py").read_text(
        encoding="utf-8"
    )
    if "automatic retry is restricted to read-only operations" not in retry_source:
        reasons.append("READ_ONLY_RETRY_GUARD_DRIFT")
    return tuple(reasons)


def _actions(path: Path) -> set[str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    actions: set[str] = set()
    for statement in document.get("Statement", []):
        raw = statement.get("Action", [])
        actions.update((raw,) if isinstance(raw, str) else raw)
    return actions


def _check_iam_separation() -> tuple[str, ...]:
    orchestrator = _actions(ROOT / "infra/iam/cloudops-orchestrator-policy.json")
    remediation = _actions(ROOT / "infra/iam/cloudops-remediation-policy.json")
    reasons: list[str] = []
    if orchestrator != {
        "bedrock:InvokeModelWithResponseStream",
        "cloudwatch:GetMetricStatistics",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "ec2:DescribeInstances",
        "lambda:InvokeFunction",
        "secretsmanager:GetSecretValue",
        "xray:PutTelemetryRecords",
        "xray:PutTraceSegments",
    }:
        reasons.append("ORCHESTRATOR_AUTHORITY_DRIFT")
    if remediation != {
        "ec2:DescribeInstances",
        "ec2:StopInstances",
        "xray:PutTelemetryRecords",
        "xray:PutTraceSegments",
    }:
        reasons.append("REMEDIATION_AUTHORITY_DRIFT")
    return tuple(reasons)


def _check_trace_contract() -> tuple[str, ...]:
    required = ('"aioa.run_id"', '"aioa.trace_id"', '"aioa.correlation_id"')
    paths = (
        ROOT / "src/aioa_cloudops_agent/agent/tracing.py",
        ROOT / "src/aioa_cloudops_agent/remediation/tool.py",
        ROOT / "src/aioa_cloudops_agent/verification/tool.py",
    )
    reasons: list[str] = []
    for path in paths:
        content = path.read_text(encoding="utf-8")
        if any(anchor not in content for anchor in required):
            reasons.append(f"TRACE_IDENTITY_DRIFT:{path.relative_to(ROOT)}")
    return tuple(reasons)


def _check_clean_clone_contract() -> tuple[str, ...]:
    reasons = list(validate_readme_contract(ROOT))
    harness = ROOT / "scripts/prove_clean_clone.py"
    if not harness.is_file():
        reasons.append("CLEAN_CLONE_HARNESS_MISSING")
    return tuple(reasons)


STATIC_CHECKS = {
    "agent_topology": _check_agent_topology,
    "circuit_boundary": _check_circuit_boundary,
    "clean_clone_contract": _check_clean_clone_contract,
    "iam_separation": _check_iam_separation,
    "mutation_surface": _check_mutation_surface,
    "trace_contract": _check_trace_contract,
    "tracked_secret_scan": _check_tracked_secret_scan,
}


def validate_gate_definition(gate: GateEvidence) -> tuple[str, ...]:
    reasons: list[str] = []
    for evidence in gate.sources:
        reasons.extend(validate_source_evidence(evidence))
    for node_id in gate.pytest_nodes:
        reasons.extend(validate_node_definition(node_id))
    for name in gate.static_checks:
        check = STATIC_CHECKS.get(name)
        if check is None:
            reasons.append(f"STATIC_CHECK_MISSING:{name}")
        else:
            try:
                reasons.extend(check())
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError, TypeError):
                reasons.append(f"STATIC_CHECK_ERROR:{name}")
    if gate.command_proof is not None:
        if len(gate.command_proof) < 2:
            reasons.append("COMMAND_PROOF_MISSING")
        else:
            command_path = ROOT / gate.command_proof[1]
            if not command_path.is_file():
                reasons.append("COMMAND_PROOF_MISSING")
    return tuple(sorted(set(reasons)))


def _run_pytest(gate: GateEvidence, report_path: Path) -> PytestProof:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--disable-warnings",
            f"--junitxml={report_path}",
            *gate.pytest_nodes,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return parse_junit(report_path, result.returncode)


def run_gate(gate: GateEvidence, report_path: Path, *, validate_only: bool) -> GateResult:
    reasons = list(validate_gate_definition(gate))
    proof = PytestProof(0, 0, 0, 0, 0)
    command_cases = 0
    if not reasons and not validate_only:
        proof = _run_pytest(gate, report_path)
        if proof.exit_code != 0:
            reasons.append(f"PYTEST_EXIT_{proof.exit_code}")
        if proof.tests == 0:
            reasons.append("NO_REQUIRED_PROOF_EXECUTED")
        if proof.failures:
            reasons.append("REQUIRED_PROOF_FAILED")
        if proof.errors:
            reasons.append("REQUIRED_PROOF_ERRORED")
        if proof.skipped:
            reasons.append("REQUIRED_PROOF_SKIPPED")
        if not reasons and gate.command_proof is not None:
            command = subprocess.run(
                gate.command_proof,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if command.returncode != 0:
                reasons.append(f"COMMAND_PROOF_EXIT_{command.returncode}")
            else:
                command_cases = 1
    return GateResult(
        gate_id=gate.gate_id,
        name=gate.name,
        status="PASS" if not reasons else "FAIL",
        proof_tests=proof.tests + command_cases,
        skipped=proof.skipped,
        reasons=tuple(sorted(set(reasons))),
    )


def _validate_matrix_shape() -> tuple[str, ...]:
    expected_ids = tuple(f"P1-{number:02d}" for number in range(1, 7))
    actual_ids = tuple(gate.gate_id for gate in GATES)
    reasons: list[str] = []
    if actual_ids != expected_ids:
        reasons.append("P1_GATE_IDS_DRIFT")
    if any(not gate.sources or not gate.pytest_nodes for gate in GATES):
        reasons.append("P1_GATE_EVIDENCE_EMPTY")
    if GATES[-1].command_proof is None:
        reasons.append("CLEAN_CLONE_COMMAND_PROOF_MISSING")
    return tuple(reasons)


def _payload(
    results: tuple[GateResult, ...],
    matrix_reasons: tuple[str, ...],
) -> dict[str, object]:
    failures = sum(result.status == "FAIL" for result in results) + bool(matrix_reasons)
    return {
        "status": "PASS" if failures == 0 else "FAIL",
        "gate_count": len(results),
        "gates_pass": sum(result.status == "PASS" for result in results),
        "gates_fail": failures,
        "gates_skipped": sum(result.skipped for result in results),
        "matrix_reasons": list(matrix_reasons),
        "gates": [asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    matrix_reasons = _validate_matrix_shape()
    with tempfile.TemporaryDirectory(prefix="aioa-p1-") as temporary:
        reports = Path(temporary)
        results = tuple(
            run_gate(
                gate,
                reports / f"{gate.gate_id}.xml",
                validate_only=args.validate_only,
            )
            for gate in GATES
        )
    payload = _payload(results, matrix_reasons)
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for result in results:
            details = ",".join(result.reasons) if result.reasons else "-"
            print(
                f"{result.gate_id} {result.status} proof_tests={result.proof_tests} "
                f"skipped={result.skipped} reasons={details}"
            )
        print(
            f"P1_SUMMARY {payload['status']} pass={payload['gates_pass']} "
            f"fail={payload['gates_fail']} skipped={payload['gates_skipped']}"
        )
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
