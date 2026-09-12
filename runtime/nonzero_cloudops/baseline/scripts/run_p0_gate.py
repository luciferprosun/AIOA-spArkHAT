#!/usr/bin/env python3
"""Run the canonical Day 13 P0 proof matrix without contacting AWS."""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PRE_ARMOR_HEAD = "a3a5ec425f34123461b4947cff6a76753847e6d1"
EXPECTED_PHASE1_TAG = "ced6e2a180dd50a1f43d4037bb8db5f4dc792657"
PHASE1_TAG = "phase1-foundation-green"
EXPECTED_TOOLS = (
    "inspect_instance",
    "read_utilization_metrics",
    "build_remediation_evidence",
    "stop_sandbox_instance",
    "verify_instance_state",
)
PRIOR_ART_BLOBS = {
    "PRIOR-ART.md": "b049876c0f2a08c41ff50cbb58184d0c3ee1966e",
    "docs/audit/prior-art-june1-forensic-baseline.md": (
        "6a0caf122d7b1a80242f6911ca5228d1062758e3"
    ),
    "docs/audit/prior-art-capability-evolution-matrix.md": (
        "898c668b778a02cdf0d49229654bd51f51f56adf"
    ),
    "docs/architecture/skeleton-to-armor-plan.md": (
        "19af3565b25e477ee09704870a228d10c6907eda"
    ),
}


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    path: str
    symbols: tuple[str, ...] = ()
    anchors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GateEvidence:
    gate_id: str
    name: str
    sources: tuple[SourceEvidence, ...]
    pytest_nodes: tuple[str, ...]
    static_checks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PytestProof:
    tests: int
    failures: int
    errors: int
    skipped: int
    exit_code: int


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    name: str
    status: str
    proof_tests: int
    skipped: int
    reasons: tuple[str, ...]


def source(
    path: str,
    *symbols: str,
    anchors: tuple[str, ...] = (),
) -> SourceEvidence:
    return SourceEvidence(path=path, symbols=tuple(symbols), anchors=anchors)


GATES = (
    GateEvidence(
        "P0-01",
        "Agent topology",
        (
            source(
                "src/aioa_cloudops_agent/agent/factory.py",
                "PRIMARY_AGENT_COUNT",
                "CURRENT_REGISTERED_TOOL_COUNT",
                "FINAL_TOOL_CAP",
                "CURRENT_TOOL_NAMES",
                "create_primary_agent",
            ),
        ),
        (
            "tests/unit/test_strands_agent.py::"
            "test_factory_creates_exactly_one_primary_agent_and_five_canonical_tools",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_flow_exposes_canonical_tools_without_mutation_clients",
            "tests/unit/test_cloudops_security.py::"
            "test_no_multi_agent_agentcore_or_dynamic_tool_loading_is_active",
        ),
        ("agent_topology",),
    ),
    GateEvidence(
        "P0-02",
        "Model boundary",
        (
            source(
                "src/aioa_cloudops_agent/safety/policy.py",
                "DefaultDenyToolPolicy.evaluate",
                "DefaultDenyToolPolicy._durable_context",
            ),
            source(
                "src/aioa_cloudops_agent/agent/hitl.py",
                "DurableProposalHumanInTheLoop.before_tool_call",
            ),
            source(
                "src/aioa_cloudops_agent/remediation/models.py",
                "StopExecutionCommand",
            ),
        ),
        (
            "tests/unit/test_safety_hardening.py::"
            "test_fake_approval_and_stop_options_cannot_cross_native_hitl",
            "tests/unit/test_safety_hardening.py::"
            "test_cross_run_proposal_replay_is_denied_before_dispatch",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_model_like_payload_cannot_construct_privileged_execution_command",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_model_and_tool_payload_cannot_set_emergency_state",
            "tests/integration/test_durable_hitl_approval_flow.py::"
            "test_malformed_or_model_like_approval_cannot_become_a_decision",
            "tests/unit/test_strands_agent.py::"
            "test_system_prompt_keeps_model_subordinate_to_tools_and_authority",
        ),
    ),
    GateEvidence(
        "P0-03",
        "Read scope",
        (
            source("src/aioa_cloudops_agent/cloudops/models.py", "SandboxTarget"),
            source(
                "src/aioa_cloudops_agent/cloudops/inspect_instance.py",
                "InspectInstanceService.inspect",
            ),
            source(
                "src/aioa_cloudops_agent/cloudops/read_utilization.py",
                "ReadUtilizationMetricsService.read",
            ),
        ),
        (
            "tests/unit/test_inspect_instance.py::"
            "test_request_for_nonconfigured_instance_fails_before_provider_call",
            "tests/unit/test_inspect_instance.py::"
            "test_missing_ambiguous_or_wrong_sandbox_tag_fails_closed",
            "tests/unit/test_read_utilization_metrics.py::"
            "test_target_or_identity_mismatch_fails_before_cloudwatch",
            "tests/unit/test_read_utilization_metrics.py::"
            "test_cloudwatch_client_surface_has_no_write_capability",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_sandbox_tag_failure_stops_cloudwatch_and_denies_policy",
        ),
    ),
    GateEvidence(
        "P0-04",
        "Evidence proposal",
        (
            source(
                "src/aioa_cloudops_agent/cloudops/build_evidence.py",
                "BuildRemediationEvidenceService.build",
            ),
            source(
                "src/aioa_cloudops_agent/agent/investigation_flow.py",
                "BoundedInvestigationFlow.execute",
            ),
            source(
                "src/aioa_cloudops_agent/persistence/nz_dynamodb.py",
                "DynamoDbDurableTruthRepository.create_proposal",
            ),
            source(
                "src/aioa_cloudops_agent/persistence/prerequisites.py",
                "load_execution_prerequisites",
            ),
        ),
        (
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_strands_happy_path_persists_evidence_backed_non_authorizing_proposal",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_trace_identity_and_evidence_hash_propagate_through_audit_and_checkpoint",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_durable_proposal_failure_fails_closed_without_claiming_completion",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_missing_durable_proposal_blocks_executor_before_any_command",
            "tests/unit/test_durable_memory_repository.py::"
            "test_missing_or_mismatched_checkpoint_evidence_blocks_execution",
        ),
    ),
    GateEvidence(
        "P0-05",
        "Human authority",
        (
            source(
                "src/aioa_cloudops_agent/agent/hitl.py",
                "ApprovalPayload",
                "ApprovalResumeRequest",
                "DurableProposalHumanInTheLoop.before_tool_call",
            ),
            source(
                "src/aioa_cloudops_agent/agent/approval_flow.py",
                "DurableApprovalFlow.request",
                "DurableApprovalFlow.resume",
            ),
            source(
                "src/aioa_cloudops_agent/persistence/durable_logic.py",
                "validate_approval_binding",
            ),
        ),
        (
            "tests/integration/test_durable_hitl_approval_flow.py::"
            "test_native_interrupt_is_durable_and_payload_comes_from_proposal",
            "tests/integration/test_durable_hitl_approval_flow.py::"
            "test_positive_native_resume_persists_approval_before_safe_tool_boundary",
            "tests/integration/test_durable_hitl_approval_flow.py::"
            "test_tampered_resume_fails_closed_without_decision_or_tool_call",
            "tests/integration/test_durable_hitl_approval_flow.py::"
            "test_changed_decision_nonce_replay_is_rejected_without_second_tool_call",
            "tests/unit/test_durable_memory_repository.py::"
            "test_approval_from_another_run_or_proposal_cannot_authorize_execution",
            "tests/integration/test_durable_hitl_approval_flow.py::"
            "test_malformed_or_model_like_approval_cannot_become_a_decision",
        ),
    ),
    GateEvidence(
        "P0-06",
        "Mutation prerequisites",
        (
            source(
                "src/aioa_cloudops_agent/persistence/prerequisites.py",
                "register_approved_action",
                "load_execution_prerequisites",
            ),
            source(
                "src/aioa_cloudops_agent/config/remediation.py",
                "SandboxRemediationSettings.live_execution_enabled",
            ),
            source(
                "src/aioa_cloudops_agent/remediation/executor.py",
                "Ec2SandboxStopExecutor.execute",
            ),
            source(
                "src/aioa_cloudops_agent/remediation/emergency.py",
                "EmergencyExecutionControl.assert_writes_enabled",
                "EnvironmentEmergencyExecutionControl.assert_writes_enabled",
            ),
            source(
                "src/aioa_cloudops_agent/remediation/coordinator.py",
                "StopSandboxInstanceCoordinator.execute",
            ),
        ),
        (
            "tests/unit/test_durable_memory_repository.py::"
            "test_durable_prerequisites_require_separate_approval_and_checkpoint",
            "tests/unit/test_durable_memory_repository.py::"
            "test_proposal_alone_never_satisfies_approval_prerequisite",
            "tests/unit/test_durable_memory_repository.py::"
            "test_missing_or_mismatched_checkpoint_evidence_blocks_execution",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_missing_or_denied_approval_never_invokes_executor",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_private_executor_requires_both_live_flags_before_any_aws_call",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_private_executor_fails_closed_for_non_sandbox_or_stale_target",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_emergency_setting_missing_defaults_to_disabled_before_dryrun",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_malformed_emergency_setting_fails_closed_with_zero_stop_calls",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_valid_human_approval_cannot_override_audited_emergency_disable",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_emergency_control_is_checked_immediately_before_each_stop_boundary",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_emergency_flip_after_dryrun_blocks_live_stop_call",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_emergency_state_unavailable_at_final_check_blocks_live_stop_call",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_emergency_false_without_durable_proposal_does_not_grant_authority",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_emergency_false_without_approval_does_not_grant_authority",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_emergency_false_cannot_bypass_in_progress_idempotency",
        ),
    ),
    GateEvidence(
        "P0-07",
        "IAM separation",
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
        ),
    ),
    GateEvidence(
        "P0-08",
        "Idempotency",
        (
            source(
                "src/aioa_cloudops_agent/persistence/semantic_idempotency.py",
                "derive_action_fingerprint",
                "derive_idempotency_key",
            ),
            source(
                "src/aioa_cloudops_agent/persistence/nz_dynamodb.py",
                "DynamoDbDurableTruthRepository.register_idempotency",
            ),
            source(
                "src/aioa_cloudops_agent/remediation/coordinator.py",
                "StopSandboxInstanceCoordinator.execute",
            ),
        ),
        (
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_duplicate_acknowledged_action_never_invokes_executor_twice",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_unresolved_in_progress_action_requires_recovery_without_replay",
            "tests/unit/test_durable_dynamodb_truth.py::"
            "test_idempotency_collision_with_inconsistent_payload_fails",
        ),
    ),
    GateEvidence(
        "P0-09",
        "Verification",
        (
            source(
                "src/aioa_cloudops_agent/verification/service.py",
                "VerifyInstanceStateService.observe",
            ),
            source(
                "src/aioa_cloudops_agent/verification/coordinator.py",
                "BoundedVerificationCoordinator.verify",
                "BoundedVerificationCoordinator._persist_success",
            ),
            source(
                "src/aioa_cloudops_agent/persistence/nz_dynamodb.py",
                "DynamoDbDurableTruthRepository.create_verification_evidence",
            ),
        ),
        (
            "tests/integration/test_human_approved_remediation_e2e.py::"
            "test_full_mocked_approved_e2e_closes_only_with_independent_durable_evidence",
            "tests/unit/test_verification_closure.py::"
            "test_stopped_target_persists_proof_then_reaches_success_with_evidence",
            "tests/unit/test_verification_closure.py::"
            "test_success_transition_without_durable_verification_evidence_is_rejected",
            "tests/unit/test_verification_closure.py::"
            "test_transitional_state_timeout_is_explicit_verification_failure",
            "tests/unit/test_verification_closure.py::"
            "test_final_evidence_storage_failure_never_claims_success",
        ),
    ),
    GateEvidence(
        "P0-10",
        "Recovery",
        (
            source(
                "src/aioa_cloudops_agent/recovery/coordinator.py",
                "RecoveryCoordinator.recover",
                "RecoveryCoordinator._validate_snapshot",
                "RecoveryCoordinator._reconcile_missing_ack",
            ),
            source(
                "src/aioa_cloudops_agent/persistence/recovery.py",
                "classify_recovery",
            ),
        ),
        (
            "tests/unit/test_recovery_reconciliation.py::"
            "test_restart_at_awaiting_approval_reconstructs_exact_interrupt_without_execution",
            "tests/unit/test_recovery_reconciliation.py::"
            "test_lost_executor_ack_observed_running_requires_operator_and_never_replays",
            "tests/unit/test_recovery_reconciliation.py::"
            "test_durable_store_outage_never_falls_back_to_in_memory_authority",
            "tests/unit/test_recovery_reconciliation.py::"
            "test_recovery_package_contains_no_executor_or_ec2_write_call",
        ),
    ),
    GateEvidence(
        "P0-11",
        "Default deny",
        (
            source(
                "src/aioa_cloudops_agent/safety/policy.py",
                "_TOOL_CAPABILITY",
                "_STRUCTURALLY_DENIED_TOOL",
                "DefaultDenyToolPolicy.evaluate",
            ),
            source("src/aioa_cloudops_agent/nz/authority.py", "authority_for_capability"),
        ),
        (
            "tests/unit/test_safety_hardening.py::"
            "test_prompt_injection_corpus_cannot_create_a_capability",
            "tests/unit/test_safety_hardening.py::"
            "test_unknown_tool_alias_defaults_to_policy_denial",
            "tests/unit/test_safety_hardening.py::"
            "test_scope_substitution_and_privileged_extra_fields_are_denied",
            "tests/unit/test_safety_hardening.py::"
            "test_cross_run_proposal_replay_is_denied_before_dispatch",
            "tests/unit/test_safety_hardening.py::"
            "test_dangerous_catalog_entries_are_policy_only_and_never_autonomous",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_denied_injection_is_linked_and_redacted_before_dispatch",
            "tests/unit/test_iam_policies.py::"
            "test_no_generalized_write_permission_agentcore_or_account_literal_exists",
        ),
        ("mutation_surface",),
    ),
    GateEvidence(
        "P0-12",
        "Failure taxonomy",
        (
            source("src/aioa_cloudops_agent/nz/enums.py", "FailureKind"),
            source(
                "src/aioa_cloudops_agent/safety/failures.py",
                "FAILURE_WORKFLOW_STATE",
                "BoundaryRisk",
                "workflow_state_for_failure",
                "redacted_unknown_failure",
            ),
        ),
        (
            "tests/unit/test_safety_hardening.py::"
            "test_failure_taxonomy_has_one_consistent_durable_state",
            "tests/unit/test_safety_hardening.py::"
            "test_unknown_mutation_exception_requires_recovery_without_secret_leakage",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_executor_failure_never_becomes_success",
        ),
    ),
    GateEvidence(
        "P0-13",
        "Boundedness",
        (
            source(
                "src/aioa_cloudops_agent/nz/contracts.py",
                "BudgetCounters.validate_consumption",
            ),
            source(
                "src/aioa_cloudops_agent/agent/investigation_flow.py",
                "BoundedInvestigationFlow._record_budget",
                "BoundedInvestigationFlow._budget_exhausted",
            ),
            source(
                "src/aioa_cloudops_agent/safety/schema.py",
                "SchemaCorrectionBudget",
                "BoundedSchemaCorrection",
            ),
            source(
                "src/aioa_cloudops_agent/safety/retry.py",
                "BoundedReadRetry.run",
            ),
            source(
                "src/aioa_cloudops_agent/verification/coordinator.py",
                "BoundedVerificationCoordinator.verify",
            ),
        ),
        (
            "tests/unit/test_safety_hardening.py::"
            "test_schema_correction_is_bounded_and_never_relaxes_strict_model",
            "tests/unit/test_safety_hardening.py::"
            "test_transient_read_retries_only_to_the_configured_cap",
            "tests/unit/test_safety_hardening.py::"
            "test_time_budget_and_persisted_counters_are_finite_and_monotonic",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_agent_turn_budget_exhaustion_persists_failure_and_no_proposal",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_agent_token_budget_exhaustion_persists_failure_and_no_proposal",
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_elapsed_time_budget_is_persisted_and_audited_before_any_proposal",
            "tests/unit/test_verification_closure.py::"
            "test_transitional_state_timeout_is_explicit_verification_failure",
        ),
    ),
    GateEvidence(
        "P0-14",
        "Secrets and audit",
        (
            source(
                "src/aioa_cloudops_agent/nz/contracts.py",
                "AuditEvent.prohibit_sensitive_metadata",
            ),
            source(
                "src/aioa_cloudops_agent/agent/hitl.py",
                "DurableProposalHumanInTheLoop._append_denial_audit",
            ),
            source(
                "src/aioa_cloudops_agent/persistence/nz_dynamodb.py",
                "DynamoDbDurableTruthRepository.append_audit_event",
            ),
            source(
                "src/aioa_cloudops_agent/safety/failures.py",
                "redacted_unknown_failure",
            ),
        ),
        (
            "tests/integration/test_read_only_investigation_flow.py::"
            "test_denied_injection_is_linked_and_redacted_before_dispatch",
            "tests/unit/test_nz_contracts.py::"
            "test_audit_event_rejects_sensitive_metadata_key",
            "tests/unit/test_safety_hardening.py::"
            "test_unknown_policy_boundary_exception_is_typed_and_redacted",
            "tests/unit/test_safety_hardening.py::"
            "test_unknown_mutation_exception_requires_recovery_without_secret_leakage",
            "tests/unit/test_durable_memory_repository.py::"
            "test_audit_event_is_append_only_and_round_trips",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_valid_human_approval_cannot_override_audited_emergency_disable",
            "tests/unit/test_private_sandbox_remediation.py::"
            "test_emergency_denial_audit_outage_never_permits_stop",
        ),
        ("tracked_secret_scan",),
    ),
    GateEvidence(
        "P0-15",
        "Prior-art integrity",
        (
            source("PRIOR-ART.md"),
            source("docs/audit/prior-art-june1-forensic-baseline.md"),
            source("docs/audit/prior-art-capability-evolution-matrix.md"),
            source("docs/architecture/skeleton-to-armor-plan.md"),
        ),
        (
            "tests/unit/test_strands_agent.py::test_phase_1_tag_remains_at_frozen_commit",
        ),
        ("prior_art_integrity",),
    ),
)


def _python_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols: set[str] = set()

    def visit(body: list[ast.stmt], prefix: str = "") -> None:
        for item in body:
            if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{prefix}.{item.name}" if prefix else item.name
                symbols.add(qualified)
                visit(item.body, qualified)
            elif not prefix and isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        symbols.add(target.id)

    visit(tree.body)
    return symbols


def validate_source_evidence(evidence: SourceEvidence) -> tuple[str, ...]:
    path = ROOT / evidence.path
    if not path.is_file():
        return (f"SOURCE_MISSING:{evidence.path}",)
    reasons: list[str] = []
    if evidence.symbols:
        if path.suffix != ".py":
            reasons.append(f"SYMBOL_SOURCE_NOT_PYTHON:{evidence.path}")
        else:
            try:
                actual = _python_symbols(path)
            except (OSError, SyntaxError, UnicodeDecodeError):
                reasons.append(f"SOURCE_UNREADABLE:{evidence.path}")
            else:
                reasons.extend(
                    f"SYMBOL_MISSING:{evidence.path}::{symbol}"
                    for symbol in evidence.symbols
                    if symbol not in actual
                )
    if evidence.anchors:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            reasons.append(f"SOURCE_UNREADABLE:{evidence.path}")
        else:
            reasons.extend(
                f"ANCHOR_MISSING:{evidence.path}::{anchor}"
                for anchor in evidence.anchors
                if anchor not in content
            )
    return tuple(reasons)


def validate_node_definition(node_id: str) -> tuple[str, ...]:
    parts = node_id.split("::")
    if len(parts) != 2:
        return (f"NODE_ID_UNSUPPORTED:{node_id}",)
    relative_path, test_name = parts
    test_name = test_name.split("[", maxsplit=1)[0]
    path = ROOT / relative_path
    if not path.is_file():
        return (f"TEST_FILE_MISSING:{relative_path}",)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return (f"TEST_FILE_UNREADABLE:{relative_path}",)
    names = {
        item.name
        for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if test_name not in names:
        return (f"PYTEST_NODE_MISSING:{node_id}",)
    return ()


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _check_agent_topology() -> tuple[str, ...]:
    constructors = 0
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for item in ast.walk(tree):
            if isinstance(item, ast.Call):
                name = item.func.id if isinstance(item.func, ast.Name) else None
                attribute = item.func.attr if isinstance(item.func, ast.Attribute) else None
                if name == "Agent" or attribute == "Agent":
                    constructors += 1
    source_root = str(ROOT / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    factory = importlib.import_module("aioa_cloudops_agent.agent.factory")
    reasons: list[str] = []
    if factory.PRIMARY_AGENT_COUNT != 1 or constructors != 1:
        reasons.append("AGENT_TOPOLOGY_DRIFT")
    if factory.CURRENT_TOOL_NAMES != EXPECTED_TOOLS:
        reasons.append("CANONICAL_TOOL_NAMES_DRIFT")
    if len(EXPECTED_TOOLS) != factory.CURRENT_REGISTERED_TOOL_COUNT:
        reasons.append("REGISTERED_TOOL_COUNT_DRIFT")
    if len(EXPECTED_TOOLS) != factory.FINAL_TOOL_CAP:
        reasons.append("FINAL_TOOL_CAP_DRIFT")
    return tuple(reasons)


def _check_mutation_surface() -> tuple[str, ...]:
    calls: list[tuple[str, str]] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for item in ast.walk(tree):
            if (
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and item.func.attr
                in {
                    "stop_instances",
                    "start_instances",
                    "terminate_instances",
                    "reboot_instances",
                }
            ):
                calls.append((str(path.relative_to(ROOT)), item.func.attr))
    expected = [
        ("src/aioa_cloudops_agent/remediation/executor.py", "stop_instances"),
        ("src/aioa_cloudops_agent/remediation/executor.py", "stop_instances"),
    ]
    return () if calls == expected else ("MUTATION_SURFACE_DRIFT",)


def _tracked_paths() -> tuple[Path, ...]:
    result = _git("ls-files", "-z")
    if result.returncode != 0:
        return ()
    return tuple(ROOT / name for name in result.stdout.split("\0") if name)


def _check_tracked_secret_scan() -> tuple[str, ...]:
    patterns = (
        re.compile(r"(?:AK" + r"IA|AS" + r"IA)[A-Z0-9]{16}"),
        re.compile(r"-{5}BEGIN [A-Z0-9 ]*" + r"PRIVATE KEY-{5}"),
        re.compile(r"gh" + r"[pousr]_[A-Za-z0-9]{20,}"),
        re.compile(r"sk" + r"-[A-Za-z0-9]{20,}"),
        re.compile(
            r"(?i)(?:aws_secret_access_key|secret_access_key)\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9/+=]{40}"
        ),
    )
    findings: list[str] = []
    paths = _tracked_paths()
    if not paths:
        return ("TRACKED_FILE_ENUMERATION_FAILED",)
    for path in paths:
        try:
            raw = path.read_bytes()
        except OSError:
            findings.append(f"TRACKED_FILE_UNREADABLE:{path.relative_to(ROOT)}")
            continue
        if b"\0" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        if any(pattern.search(text) for pattern in patterns):
            findings.append(f"POTENTIAL_SECRET:{path.relative_to(ROOT)}")
    return tuple(findings)


def _check_prior_art_integrity() -> tuple[str, ...]:
    reasons: list[str] = []
    tag = _git("rev-parse", f"{PHASE1_TAG}^{{}}")
    if tag.returncode != 0 or tag.stdout.strip() != EXPECTED_PHASE1_TAG:
        reasons.append("PHASE1_TAG_DRIFT")
    ancestor = _git("merge-base", "--is-ancestor", EXPECTED_PRE_ARMOR_HEAD, "HEAD")
    if ancestor.returncode != 0:
        reasons.append("PRE_ARMOR_HEAD_NOT_ANCESTOR")
    for relative_path, expected_blob in PRIOR_ART_BLOBS.items():
        result = _git("hash-object", "--", relative_path)
        if result.returncode != 0 or result.stdout.strip() != expected_blob:
            reasons.append(f"PRIOR_ART_BLOB_DRIFT:{relative_path}")
    if (ROOT / ".gitmodules").exists():
        reasons.append("GITMODULES_PRESENT")
    index = _git("ls-files", "-s")
    if index.returncode != 0:
        reasons.append("GIT_INDEX_UNAVAILABLE")
    else:
        for line in index.stdout.splitlines():
            mode = line.split(maxsplit=1)[0]
            if mode in {"120000", "160000"}:
                reasons.append("LINKED_OR_SUBMODULE_CONTENT_PRESENT")
                break
    forbidden_roots = {"aoia", "aioa_core", "hackverse"}
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for item in ast.walk(tree):
            modules: tuple[str, ...] = ()
            if isinstance(item, ast.Import):
                modules = tuple(alias.name for alias in item.names)
            elif isinstance(item, ast.ImportFrom) and item.module:
                modules = (item.module,)
            if any(module.split(".", maxsplit=1)[0].lower() in forbidden_roots for module in modules):
                reasons.append(f"LEGACY_RUNTIME_IMPORT:{path.relative_to(ROOT)}")
                break
    return tuple(reasons)


STATIC_CHECKS = {
    "agent_topology": _check_agent_topology,
    "mutation_surface": _check_mutation_surface,
    "tracked_secret_scan": _check_tracked_secret_scan,
    "prior_art_integrity": _check_prior_art_integrity,
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
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                reasons.append(f"STATIC_CHECK_ERROR:{name}")
    return tuple(sorted(set(reasons)))


def parse_junit(path: Path, exit_code: int) -> PytestProof:
    if not path.is_file():
        return PytestProof(0, 0, 1, 0, exit_code)
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError):
        return PytestProof(0, 0, 1, 0, exit_code)
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    totals = {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    return PytestProof(exit_code=exit_code, **totals)


def run_pytest_proof(gate: GateEvidence, report_path: Path) -> PytestProof:
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
    if not reasons and not validate_only:
        proof = run_pytest_proof(gate, report_path)
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
    return GateResult(
        gate_id=gate.gate_id,
        name=gate.name,
        status="PASS" if not reasons else "FAIL",
        proof_tests=proof.tests,
        skipped=proof.skipped,
        reasons=tuple(sorted(set(reasons))),
    )


def _validate_matrix_shape() -> tuple[str, ...]:
    expected_ids = tuple(f"P0-{number:02d}" for number in range(1, 16))
    actual_ids = tuple(gate.gate_id for gate in GATES)
    reasons: list[str] = []
    if actual_ids != expected_ids:
        reasons.append("P0_GATE_IDS_DRIFT")
    if any(not gate.sources or not gate.pytest_nodes for gate in GATES):
        reasons.append("P0_GATE_EVIDENCE_EMPTY")
    return tuple(reasons)


def _payload(results: tuple[GateResult, ...], matrix_reasons: tuple[str, ...]) -> dict[str, object]:
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
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate exact definitions and static checks without executing pytest proofs.",
    )
    parser.add_argument("--json", action="store_true", help="Emit deterministic JSON only.")
    args = parser.parse_args()
    matrix_reasons = _validate_matrix_shape()
    with tempfile.TemporaryDirectory(prefix="aioa-p0-") as temporary_directory:
        reports = Path(temporary_directory)
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
                f"{result.gate_id} {result.status} "
                f"proof_tests={result.proof_tests} skipped={result.skipped} reasons={details}"
            )
        print(
            f"P0_SUMMARY {payload['status']} pass={payload['gates_pass']} "
            f"fail={payload['gates_fail']} skipped={payload['gates_skipped']}"
        )
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
