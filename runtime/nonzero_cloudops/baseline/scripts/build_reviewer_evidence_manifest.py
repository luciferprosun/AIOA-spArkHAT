#!/usr/bin/env python3
"""Build the deterministic, judge-facing AU-3 reviewer evidence manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
from contextlib import suppress
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aioa_cloudops_agent.agent import (  # noqa: E402
    CURRENT_REGISTERED_TOOL_COUNT,
    CURRENT_TOOL_NAMES,
    FINAL_TOOL_CAP,
    PRIMARY_AGENT_COUNT,
)
from aioa_cloudops_agent.config import (  # noqa: E402
    DEFAULT_BEDROCK_MODEL_ID,
    DEFAULT_BEDROCK_REGION,
)
from scripts.day15.run_day15_gate import GATES as DAY15_GATES  # noqa: E402
from scripts.run_p0_gate import (  # noqa: E402
    EXPECTED_PHASE1_TAG,
    PHASE1_TAG,
    PRIOR_ART_BLOBS,
)
from scripts.run_p0_gate import GATES as P0_GATES  # noqa: E402
from scripts.run_p1_gate import GATES as P1_GATES  # noqa: E402

SCHEMA_VERSION = "2.0"
EVIDENCE_SNAPSHOT_COMMIT = "fbb536400594306f2bb3abd31c7064a66735c82d"
DAY15_START_COMMIT = "aa941a989a8b8cd0e40367bb130472e9f3c082a7"
DAY15_ORIGINAL_M1_COMMIT = "17d5f4637dbd69a33eff1cbb46282c36b19ce6ad"
DAY15_ORIGINAL_M2_COMMIT = "8e4583ac9341cb7b66de47cf0e7b2a442ac67b32"
DAY15_ORIGINAL_M3_COMMIT = "30c2a30cda0ac6d6e2003166daf6c29bf2c764f0"
DAY15_M1_COMMIT = "f2ee79c09ba174ba72cb527b70c095f412151758"
DAY15_M2_COMMIT = "36fd17df981dfa593d4e63f6a143410317410763"
DAY15_FINAL_BLOCKER_COMMIT = "ce35a67f6491ea92aeef534d0dc4f5dc4a8da7ff"
DAY15_SECRET_FIX_COMMIT = "5a6127f43a9251a72203c0eb6c7a903d817599f7"
DAY15_G10_IMPLEMENTATION_COMMIT = "3464bc869e7a11acb5aab61ae279cf196a1ebd0f"
DAY15_G10_EVIDENCE_COMMIT = "41ba5586180e9aa3a25fc5469d42815073a0bbf8"
DAY15_G10_BLOCKER_COMMIT = "858770d5e5c7b59fa883cc56e06f4a9e915d70c1"
DAY15_NOVA_PROBE_FIX_COMMIT = "5e1904408d402c1e6492d6b2e153a7f1a5c56b58"
DAY15_G10_REANCHOR_COMMIT = "99f70c43a26ce9715e9b57fde81ca265382dd5f2"
DAY15_G10_COMMIT = "197db56f828b8ab0b9139a1d3708fb8a58ca336a"
LOCAL_FIRST_PHASE1_COMMIT = "b5dba16a9af1bc979b2b96a50ddbf0e590e829a5"
LOCAL_FIRST_PHASE2_COMMIT = "7ffe0cf7c9ca4a5c7c311fd5394a245e80bb78e0"
PHASE3_IAC_COMMIT = "c16f6829e8b258af86523b0b1d61e34586702b63"
PHASE3_RC_COMMIT = "5ac15d30a604434713490d77edb573d14a8f1dcd"
PORTABLE_B1_COMMIT = "a2e16d0f1d625b34916440d6740a486f73cf2bb1"
PORTABLE_B3_COMMIT = "1882089fbb41a3f7f3cbad821ed9d6d8c6c2e9a5"
PORTABLE_B4_COMMIT = "a455379eb3de73bf6c1780b3c4726b0778873dd4"
PORTABLE_B5_CONTAINER_COMMIT = "d18f945a1484a1255339a3b4bcb1560c58d06d9b"
DAY15_RECOVERY_LINEAGE = (
    DAY15_START_COMMIT,
    DAY15_ORIGINAL_M1_COMMIT,
    DAY15_ORIGINAL_M2_COMMIT,
    DAY15_ORIGINAL_M3_COMMIT,
    DAY15_M1_COMMIT,
    DAY15_M2_COMMIT,
    DAY15_FINAL_BLOCKER_COMMIT,
    DAY15_SECRET_FIX_COMMIT,
    DAY15_G10_IMPLEMENTATION_COMMIT,
    DAY15_G10_EVIDENCE_COMMIT,
    DAY15_G10_BLOCKER_COMMIT,
    DAY15_NOVA_PROBE_FIX_COMMIT,
    DAY15_G10_REANCHOR_COMMIT,
    DAY15_G10_COMMIT,
)
DAY15_CANDIDATE_STATUS = "LOCAL_IMPLEMENTATION_CANDIDATE"
EXPECTED_BEDROCK_REGION = "eu-central-1"
EXPECTED_MODEL_ID = "eu.amazon.nova-2-lite-v1:0"
EXPECTED_STRANDS_VERSION = "1.53.0"
EXPECTED_STRANDS_REQUIREMENT = "strands-agents[otel]==1.53.0"
P0_PROOF_CASES = 136
P1_PROOF_CASES = 93
PRIOR_ARMOR_COMMITS = (
    "bcc3b478612ec1994e2846657d27d12326302d6c",
    "4d84d207d900b88d2cae6017640d615f3621c8f4",
    "1fbf019cb7da82fa74feab16b7f19ac42febc6d6",
)
LIVE_EC2_NOT_PROVEN_CLAIM = (
    "A live EC2 StopInstances event is not yet proven by this repository."
)
JSON_PATH = ROOT / "docs/evidence/reviewer-evidence-manifest.json"
MARKDOWN_PATH = ROOT / "docs/evidence/reviewer-evidence-manifest.md"
README_PATH = ROOT / "docs/evidence/README.md"
_STRANDS_DEPENDENCY = re.compile(r"strands[-_]agents(?:\[[^]]+\])?", re.IGNORECASE)


def project_strands_requirement(root: Path = ROOT) -> str:
    """Require the one reviewed Strands requirement, including the OTel extra and exact pin."""

    document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = document.get("project", {}).get("dependencies", [])
    requirements: list[str] = []
    for dependency in dependencies:
        if not isinstance(dependency, str):
            continue
        normalized = dependency.strip()
        if _STRANDS_DEPENDENCY.match(normalized):
            requirements.append(normalized)
    if requirements != [EXPECTED_STRANDS_REQUIREMENT]:
        raise ValueError("pyproject must contain only the reviewed exact Strands OTel pin")
    return requirements[0]


def project_strands_version(root: Path = ROOT) -> str:
    project_strands_requirement(root)
    return EXPECTED_STRANDS_VERSION


def canonical_claim_material(claim: dict[str, Any]) -> bytes:
    """Return canonical bytes for every claim field except its derived hash."""

    material = {key: deepcopy(value) for key, value in claim.items() if key != "hash"}
    for field in ("authority_source", "proof_nodes"):
        values = material.get(field)
        if isinstance(values, list) and all(isinstance(value, str) for value in values):
            material[field] = sorted(values)
    return json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def claim_hash(claim: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_claim_material(claim)).hexdigest()


def _claim(
    claim_id: str,
    claim: str,
    evidence_kind: str,
    authority_source: tuple[str, ...],
    proof_nodes: tuple[str, ...],
    *,
    status: str = "PROVEN",
    scope: str = "Local deterministic",
    limitations: str,
    commit_anchor: str = EVIDENCE_SNAPSHOT_COMMIT,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "claim_id": claim_id,
        "claim": claim,
        "evidence_kind": evidence_kind,
        "authority_source": sorted(authority_source),
        "proof_nodes": sorted(proof_nodes),
        "commit_anchor": commit_anchor,
        "status": status,
        "scope": scope,
        "limitations": limitations,
    }
    result["hash"] = claim_hash(result)
    return result


def build_claims() -> list[dict[str, Any]]:
    """Build conservative claims; tests and source prove behavior, never a live event."""

    claims = [
        _claim(
            "AGENT-TOPOLOGY-01",
            "The runtime factory creates one primary Strands Agent.",
            "TEST",
            ("src/aioa_cloudops_agent/agent/factory.py::PRIMARY_AGENT_COUNT",),
            (
                "P0-01",
                "tests/unit/test_strands_agent.py::"
                "test_factory_creates_exactly_one_primary_agent_and_five_canonical_tools",
            ),
            commit_anchor=PORTABLE_B1_COMMIT,
            limitations="Proves the repository runtime factory, not the topology of an undeployed AWS stack.",
        ),
        _claim(
            "APPROVAL-BINDING-01",
            "Human approval is explicit and bound to the proposal, request, actor session, and decision nonce.",
            "TEST",
            (
                "src/aioa_cloudops_agent/agent/approval_flow.py::DurableApprovalFlow.resume",
                "src/aioa_cloudops_agent/nz/contracts.py::Approval.validate_action_binding",
                "src/aioa_cloudops_agent/persistence/durable_logic.py::validate_approval_binding",
            ),
            (
                "P0-05",
                "tests/integration/test_durable_hitl_approval_flow.py::"
                "test_changed_decision_nonce_replay_is_rejected_without_second_tool_call",
                "tests/unit/test_durable_memory_repository.py::"
                "test_approval_from_another_run_or_proposal_cannot_authorize_execution",
            ),
            commit_anchor=PORTABLE_B4_COMMIT,
            scope="mocked AWS",
            limitations="Does not attest to a real operator approval or a deployed identity provider.",
        ),
        _claim(
            "BOUNDED-FAILURES-01",
            "Schema correction, dependency retry, circuit suppression, and workflow budgets are finite and typed.",
            "TEST",
            (
                "src/aioa_cloudops_agent/safety/circuit.py::DependencyCircuitBreaker.acquire",
                "src/aioa_cloudops_agent/safety/retry.py::BoundedReadRetry.run",
                "src/aioa_cloudops_agent/safety/schema.py::SchemaCorrectionBudget",
            ),
            (
                "P0-12",
                "P0-13",
                "P1-03",
                "tests/unit/test_dependency_circuit_breaker.py::"
                "test_open_circuit_suppresses_provider_calls_during_cooldown",
            ),
            commit_anchor=DAY15_ORIGINAL_M1_COMMIT,
            limitations="Process-local circuit state does not suppress failures across separate cold runtimes.",
        ),
        _claim(
            "DEFAULT-DENY-01",
            "Unknown and NEVER_AUTONOMOUS capabilities are denied by deterministic policy.",
            "TEST",
            (
                "src/aioa_cloudops_agent/nz/authority.py::authority_for_capability",
                "src/aioa_cloudops_agent/safety/policy.py::DefaultDenyToolPolicy.evaluate",
            ),
            (
                "P0-11",
                "P1-01",
                "tests/unit/test_safety_hardening.py::"
                "test_unknown_tool_alias_defaults_to_policy_denial",
            ),
            commit_anchor=LOCAL_FIRST_PHASE1_COMMIT,
            limitations="Proves the registered policy boundary, not protection from every future code change.",
        ),
        _claim(
            "EXECUTOR-GATES-01",
            "The private stop executor requires durable prerequisites, exact sandbox scope, both live opt-ins, and an emergency-veto release immediately before write boundaries.",
            "TEST",
            (
                "src/aioa_cloudops_agent/persistence/prerequisites.py::load_execution_prerequisites",
                "src/aioa_cloudops_agent/remediation/emergency.py::EnvironmentEmergencyExecutionControl.assert_writes_enabled",
                "src/aioa_cloudops_agent/remediation/executor.py::Ec2SandboxStopExecutor.execute",
            ),
            (
                "P0-06",
                "tests/unit/test_private_sandbox_remediation.py::"
                "test_private_executor_requires_both_live_flags_before_any_aws_call",
                "tests/unit/test_private_sandbox_remediation.py::"
                "test_emergency_flip_after_dryrun_blocks_live_stop_call",
            ),
            commit_anchor=DAY15_ORIGINAL_M1_COMMIT,
            scope="mocked AWS",
            limitations="Proves fail-closed code paths with fakes; it does not prove a deployed role or a live stop.",
        ),
        _claim(
            "IAM-SEPARATION-01",
            "The checked-in orchestrator policy can invoke only the private executor and has no direct EC2 StopInstances action.",
            "STATIC",
            ("infra/iam/cloudops-orchestrator-policy.json#lambda:InvokeFunction",),
            (
                "P0-07",
                "P1-04",
                "tests/unit/test_iam_policies.py::"
                "test_orchestrator_policy_is_exact_read_model_state_secret_and_alias_authority",
            ),
            commit_anchor=DAY15_ORIGINAL_M1_COMMIT,
            limitations="Validates repository policy documents, not the effective policy of an undeployed AWS role.",
        ),
        _claim(
            "IDEMPOTENCY-01",
            "A duplicate logical action cannot silently execute twice while durable idempotency state is acknowledged or unresolved.",
            "TEST",
            (
                "src/aioa_cloudops_agent/persistence/prerequisites.py::register_approved_action",
                "src/aioa_cloudops_agent/persistence/semantic_idempotency.py::derive_action_fingerprint",
            ),
            (
                "P0-08",
                "tests/unit/test_private_sandbox_remediation.py::"
                "test_duplicate_acknowledged_action_never_invokes_executor_twice",
            ),
            commit_anchor=DAY15_ORIGINAL_M1_COMMIT,
            scope="mocked AWS",
            limitations="Does not prove production DynamoDB availability or a live concurrency event.",
        ),
        _claim(
            "LIVE-EC2-01",
            LIVE_EC2_NOT_PROVEN_CLAIM,
            "DOC",
            (
                "docs/architecture/day-14-p1-resilience.md#"
                "Deployment remains deferred to Day 15.",
            ),
            (),
            status="NOT_YET_PROVEN",
            scope="live AWS",
            limitations="No sanitized live receipt is present; source and mocked tests prove only bounded capability behavior.",
        ),
        _claim(
            "LOCAL2-HITL-EXECUTION-01",
            "Local mock execution requires an exact authenticated approval, durable idempotency ownership, one atomic receipt, and independent verification before evidenced success.",
            "TEST",
            (
                "src/aioa_cloudops_agent/agent/local_hitl.py::LocalHitlExecutionFlow.resume",
                "src/aioa_cloudops_agent/cloudops/local_mock.py::LocalMockStateStore.execute",
                "src/aioa_cloudops_agent/nz/contracts.py::Checkpoint.validate_last_safe_state",
            ),
            (
                "tests/integration/test_local_hitl_execution.py::"
                "test_approved_eip_executes_once_verifies_and_reconciles_after_restart",
                "tests/integration/test_local_hitl_execution.py::"
                "test_identical_decision_reconciles_after_verified_execution",
                "tests/integration/test_local_hitl_execution.py::"
                "test_restart_reconciles_success_transition_before_final_checkpoint",
                "tests/integration/test_local_hitl_execution.py::"
                "test_receipt_and_verification_reconstruction_reject_semantic_substitution",
            ),
            commit_anchor=PORTABLE_B4_COMMIT,
            limitations="Bounded to deterministic state files; it provides no provider receipt or account observation.",
        ),
        _claim(
            "LOCAL2-LOOPBACK-API-01",
            "The Local-2 judge surface defaults to loopback and rejects non-loopback binding unless the canonical container entrypoint supplies explicit container intent; it remains bearer-bootstrapped into an HttpOnly same-site session, schema-bounded, non-cacheable, and exposes only a sanitized durable evidence timeline.",
            "TEST",
            (
                "src/aioa_cloudops_agent/config/portable_server.py::PortableServerSettings",
                "src/aioa_cloudops_agent/local_api/application.py::LocalApiApplication",
                "src/aioa_cloudops_agent/local_api/auth.py::LocalApiTokenAuthorizer.authorize",
                "src/aioa_cloudops_agent/local_api/judge_ui.py::judge_ui_headers",
                "src/aioa_cloudops_agent/local_api/server.py::create_local_http_server",
                "src/aioa_cloudops_agent/local_api/server.py::load_or_create_local_token",
                "src/aioa_cloudops_agent/local_api/views.py::run_view",
                "src/aioa_cloudops_agent/portable_server.py::main",
            ),
            (
                "tests/integration/test_local_hitl_http_server.py::"
                "test_real_loopback_server_exposes_health_and_authenticated_start",
                "tests/integration/test_local_hitl_http_server.py::"
                "test_server_refuses_non_loopback_bind",
                "tests/integration/test_local_hitl_http_server.py::"
                "test_token_file_is_created_once_with_owner_only_permissions",
                "tests/integration/test_portable_judge_experience.py::"
                "test_judge_http_experience_survives_stale_tab_duplicate_click_and_restart",
                "tests/unit/test_judge_console_launcher.py::"
                "test_browser_bootstrap_keeps_session_credential_in_fragment_only",
                "tests/unit/test_local_hitl_api.py::"
                "test_full_approved_http_flow_executes_verifies_and_reconciles",
                "tests/unit/test_local_hitl_api.py::"
                "test_public_console_has_strict_csp_and_no_browser_secret_storage",
                "tests/unit/test_local_hitl_api.py::"
                "test_run_view_is_sanitized_and_exposes_bounded_audit_evidence",
                "tests/unit/test_portable_container_runtime.py::"
                "test_container_binding_requires_explicit_intent",
            ),
            commit_anchor=PORTABLE_B5_CONTAINER_COMMIT,
            limitations="Proves a local single-operator demo boundary and deterministic sandbox behavior. The container binds internally to all interfaces, so safe host publication still depends on the documented loopback or isolated-network launch command. It does not attest to a deployed identity provider, public endpoint, production authorization service, or provider-backed operation.",
        ),
        _claim(
            "MODEL-AUTHORITY-01",
            "Model output cannot itself authorize mutation; execution requires deterministic policy and durable human authority.",
            "TEST",
            (
                "src/aioa_cloudops_agent/agent/hitl.py::DurableProposalHumanInTheLoop",
                "src/aioa_cloudops_agent/nz/contracts.py::ActionProposal.authorizes_execution",
                "src/aioa_cloudops_agent/safety/policy.py::DefaultDenyToolPolicy.evaluate",
            ),
            (
                "P0-02",
                "tests/unit/test_private_sandbox_remediation.py::"
                "test_model_like_payload_cannot_construct_privileged_execution_command",
            ),
            commit_anchor=PORTABLE_B4_COMMIT,
            limitations="Does not claim the model is intrinsically safe; authority remains outside the model.",
        ),
        _claim(
            "MODEL-PIN-01",
            "The default Bedrock model configuration selects Amazon Nova 2 Lite in eu-central-1.",
            "STATIC",
            (
                "src/aioa_cloudops_agent/config/agent.py::DEFAULT_BEDROCK_MODEL_ID",
                "src/aioa_cloudops_agent/config/agent.py::BedrockSettings",
            ),
            (
                "P0-02",
                "tests/unit/test_strands_agent.py::"
                "test_bedrock_provider_uses_explicit_region_model_and_bounds",
            ),
            commit_anchor=DAY15_ORIGINAL_M1_COMMIT,
            limitations="Proves configuration and request construction, not a live Bedrock invocation.",
        ),
        _claim(
            "P0-GATE-01",
            "The canonical P0 matrix passed all 15 gates with 136 proof cases at its reviewed commit anchor.",
            "TEST",
            ("scripts/run_p0_gate.py::GATES",),
            tuple(gate.gate_id for gate in P0_GATES),
            commit_anchor=DAY15_ORIGINAL_M1_COMMIT,
            limitations="Records deterministic repository proof; it is not a live AWS deployment test.",
        ),
        _claim(
            "P1-GATE-01",
            "The canonical P1 matrix passed all 6 gates with 93 proof cases at its reviewed commit anchor.",
            "TEST",
            ("scripts/run_p1_gate.py::GATES",),
            tuple(gate.gate_id for gate in P1_GATES),
            commit_anchor=DAY15_ORIGINAL_M1_COMMIT,
            limitations="Records deterministic failure-engineering proof; clean-clone remote mode depends on public-origin reachability.",
        ),
        _claim(
            "PRIOR-ART-ATTESTATION-01",
            "The project disclosure states that no prior-project implementation assets were imported.",
            "OPERATOR_ATTESTATION",
            (
                "PRIOR-ART.md#No implementation code, commits, migrations, deployment definitions, or generated assets from prior projects were imported into this repository.",
            ),
            ("P0-15",),
            status="ATTESTED_ONLY",
            scope="documentation",
            limitations="Repository scans and disclosure support this statement but cannot prove facts outside the inspected repositories.",
        ),
        _claim(
            "PRIOR-ART-HISTORY-01",
            "The frozen Phase 1 tag, pre-armor ancestry, and prior-art document blobs remain at their recorded immutable anchors.",
            "GIT",
            ("docs/audit/prior-art-june1-forensic-baseline.md",),
            (
                "P0-15",
            ),
            limitations="Proves this repository's anchors and frozen forensic documents; external history claims retain their documented evidence limits.",
        ),
        _claim(
            "PROPOSAL-DURABILITY-01",
            "An ActionProposal is persisted before approval and never authorizes execution by itself.",
            "TEST",
            (
                "src/aioa_cloudops_agent/nz/contracts.py::ActionProposal.authorizes_execution",
                "src/aioa_cloudops_agent/persistence/nz_dynamodb.py::DynamoDbDurableTruthRepository.create_proposal",
            ),
            (
                "P0-04",
                "tests/integration/test_read_only_investigation_flow.py::"
                "test_strands_happy_path_persists_evidence_backed_non_authorizing_proposal",
            ),
            commit_anchor=PORTABLE_B4_COMMIT,
            scope="mocked AWS",
            limitations="Proves persistence contracts and mocked repository behavior, not a live DynamoDB write.",
        ),
        _claim(
            "RECOVERY-NO-REPLAY-01",
            "Restart and lost acknowledgement paths reconcile durable evidence and do not blindly replay mutation.",
            "TEST",
            ("src/aioa_cloudops_agent/recovery/coordinator.py::RecoveryCoordinator.recover",),
            (
                "P0-10",
                "tests/unit/test_recovery_reconciliation.py::"
                "test_lost_executor_ack_observed_running_requires_operator_and_never_replays",
            ),
            scope="mocked AWS",
            limitations="Proves deterministic recovery behavior with fakes, not a live process interruption.",
        ),
        _claim(
            "SDK-PIN-01",
            "The project dependency declares an exact Strands Agents SDK pin at 1.53.0.",
            "STATIC",
            ("pyproject.toml#strands-agents[otel]==1.53.0",),
            ("P0-01", "P1-06"),
            commit_anchor=PHASE3_RC_COMMIT,
            limitations="Proves the declared pin and clean install contract, not future package-index availability.",
        ),
        _claim(
            "TOOL-SURFACE-01",
            "The primary agent exposes exactly the five canonical principal tools derived from the runtime factory.",
            "TEST",
            (
                "src/aioa_cloudops_agent/agent/factory.py::CURRENT_TOOL_NAMES",
                "src/aioa_cloudops_agent/agent/factory.py::FINAL_TOOL_CAP",
            ),
            (
                "P0-01",
                "tests/unit/test_strands_agent.py::"
                "test_factory_creates_exactly_one_primary_agent_and_five_canonical_tools",
            ),
            commit_anchor=PORTABLE_B1_COMMIT,
            limitations="Counts principal Strands tools in this repository, not infrastructure endpoints.",
        ),
        _claim(
            "DAY15-AWS-CLIENT-BOUNDS-01",
            "Critical AWS clients own explicit one-attempt transport configuration, and the bounded model wrapper suppresses repeated warm-runtime failures without a hidden retry.",
            "TEST",
            (
                "src/aioa_cloudops_agent/aws_clients.py::_bounded_config",
                "src/aioa_cloudops_agent/safety/model_circuit.py::CircuitBoundedModel",
            ),
            (
                "tests/unit/test_day15_aws_clients.py::"
                "test_configured_endpoint_environment_cannot_redirect_real_client",
                "tests/unit/test_day15_aws_clients.py::"
                "test_critical_client_factories_own_region_timeouts_and_retry_count",
                "tests/unit/test_day15_model_circuit.py::"
                "test_model_circuit_suppresses_third_warm_call_without_hidden_retry",
            ),
            commit_anchor=DAY15_ORIGINAL_M1_COMMIT,
            limitations="Tests inspect client construction and deterministic fakes; they do not attest to provider latency or availability.",
        ),
        _claim(
            "DAY15-COLD-RESUME-01",
            "A fresh Agent runtime can restore a durable native interrupt using trusted principal identity and a server-issued one-time challenge, while no approval or resume route is public.",
            "TEST",
            (
                "src/aioa_cloudops_agent/agent/factory.py::create_primary_agent",
                "src/aioa_cloudops_agent/deployment/resume.py::AuthenticatedApprovalResumeService",
            ),
            (
                "tests/integration/test_durable_hitl_approval_flow.py::"
                "test_fresh_process_restores_native_interrupt_with_trusted_one_time_freshness",
                "tests/unit/test_day15_judge_http.py::"
                "test_unknown_approval_mutation_and_wrong_method_routes_fail_before_services",
            ),
            commit_anchor=PORTABLE_B1_COMMIT,
            scope="mocked AWS",
            limitations="Proves deterministic restoration and duplicate rejection with local durable fakes; the capability remains absent from the public route table.",
        ),
        _claim(
            "DAY15-DEPLOYMENT-GATE-01",
            "The Day 15 controller implements candidate-bound G10 closure and a protected exact-role authority bootstrap with deterministic source selection, bounded identity and one-role-assumption verification, append-only alias construction, closed private and sanitized receipts, a fixed read-only preflight allowlist, and ten fail-closed local gates that never authorize deployment.",
            "TEST",
            (
                "scripts/day15/g10_aws_preflight.py::observe_aws_preflight",
                "scripts/day15/g10_aws_preflight.py::validate_private_observation_receipt",
                "scripts/day15/g10_candidate.py::build_candidate_descriptor",
                "scripts/day15/g10_operator_bootstrap.py::run_authority_bootstrap",
                "scripts/day15/g10_operator_bootstrap.py::select_source_profile",
                "scripts/day15/g10_operator_bootstrap.py::validate_private_authority_receipt",
                "scripts/day15/g10_operator_bootstrap.py::validate_sanitized_authority_receipt",
                "scripts/day15/run_g10_closure.py::run_closure",
                "scripts/day15/run_g10_closure.py::validate_sanitized_receipt",
                "scripts/day15/run_day15_gate.py::GATES",
                "scripts/day15/run_day15_gate.py::_g10_candidate_receipt_result",
                "scripts/day15/run_day15_gate.py::run_gate",
            ),
            (
                *(gate.gate_id for gate in DAY15_GATES),
                "tests/unit/test_day15_g10_aws_preflight.py::"
                "test_every_client_is_region_pinned_endpoint_hardened_and_single_attempt",
                "tests/unit/test_day15_g10_aws_preflight.py::"
                "test_happy_path_has_exact_read_ledger_zero_writes_and_redacted_repr",
                "tests/unit/test_day15_g10_candidate.py::"
                "test_candidate_descriptor_is_stable_closed_and_binds_actual_reviewer_manifest",
                "tests/unit/test_day15_g10_closure.py::"
                "test_day15_g10_accepts_only_candidate_bound_private_and_sanitized_pair",
                "tests/unit/test_day15_g10_closure.py::"
                "test_day15_g10_rejects_stale_authenticated_receipt",
                "tests/unit/test_day15_g10_closure.py::"
                "test_no_private_binding_is_blocked_and_performs_no_aws_call",
                "tests/unit/test_day15_g10_operator_bootstrap.py::"
                "test_select_source_profile_is_explicit_or_uniquely_deterministic",
                "tests/unit/test_day15_g10_operator_bootstrap.py::"
                "test_assumable_exact_role_creates_and_reverifies_zero_authority_alias",
                "tests/unit/test_day15_g10_operator_bootstrap.py::"
                "test_root_source_principal_is_never_substituted_for_the_role",
                "tests/unit/test_day15_g10_operator_bootstrap.py::"
                "test_unassumable_role_is_sanitized_blocked_and_never_writes_alias",
                "tests/unit/test_day15_g10_operator_bootstrap.py::"
                "test_public_and_private_receipt_schemas_reject_unknown_fields",
                "tests/unit/test_day15_g10_operator_bootstrap.py::"
                "test_endpoint_override_environment_blocks_before_session_creation",
                "tests/unit/test_day15_g10_operator_bootstrap.py::"
                "test_repository_guard_requires_main_origin_clean_and_phase1_tag",
                "tests/unit/test_day15_g10_operator_bootstrap.py::"
                "test_default_factories_bound_nested_credential_provider_clients",
                "tests/unit/test_day15_gate.py::"
                "test_gate_matrix_has_exact_stable_ids_status_vocabulary_and_validate_only_output",
            ),
            commit_anchor=PHASE3_IAC_COMMIT,
            limitations="Proves candidate and receipt binding plus protected bootstrap and bounded adapter behavior with local fakes. No AWS API call, exact-role success, external-prerequisite success, change set, or deployment is attested.",
        ),
        _claim(
            "DAY15-JUDGE-SURFACE-01",
            "The Day 15 application exposes health, readiness, same-origin UI, and token-protected read-only investigation and status routes; approval and mutation routes fail before services.",
            "TEST",
            (
                "src/aioa_cloudops_agent/deployment/auth.py::JudgeTokenAuthorizer",
                "src/aioa_cloudops_agent/judge/application.py::JudgeFunctionUrlApplication",
                "src/aioa_cloudops_agent/judge/lambda_handler.py::lambda_handler",
            ),
            (
                "tests/unit/test_day15_judge_http.py::"
                "test_health_and_root_create_no_clients_and_expose_hardened_same_origin_ui",
                "tests/unit/test_day15_judge_http.py::"
                "test_status_requires_auth_and_global_quota_before_one_bounded_status_read",
                "tests/unit/test_day15_judge_http.py::"
                "test_unknown_approval_mutation_and_wrong_method_routes_fail_before_services",
                "tests/unit/test_day15_judge_http.py::"
                "test_wrong_token_denies_before_quota_agent_and_status",
            ),
            commit_anchor=DAY15_ORIGINAL_M1_COMMIT,
            limitations="Proves the checked-in router and local service boundaries, not a deployed Function URL or operator identity system.",
        ),
        _claim(
            "DAY15-RELEASE-SAFETY-01",
            "The Phase 3 IaC anchor preserves the reviewed Day 15 release controls and adds exact ownership tags plus a deterministic expected-resource manifest without widening runtime authority.",
            "TEST",
            (
                "infra/sam/template.yaml",
                "requirements/day15-toolchain.json",
                "requirements/lambda-runtime.txt",
                "scripts/day15/alias_rollback.py::build_plan",
                "scripts/day15/build_lambda_artifact.py::build_artifact",
                "scripts/day15/build_lambda_artifact.py::revalidate_artifact",
                "scripts/day15/preflight_region.py::validate_region",
                "scripts/day15/render_template.py::render_template",
                "scripts/day15/validate_template.py::validate_template_toolchain",
            ),
            (
                "tests/unit/test_day15_artifact.py::"
                "test_container_validation_binds_engine_version_platform_and_manifest_digest",
                "tests/unit/test_day15_artifact.py::"
                "test_repository_provenance_binds_clean_head_index_worktree_and_source_tree",
                "tests/unit/test_day15_artifact.py::"
                "test_dependency_scan_pass_requires_exact_complete_locked_inventory",
                "tests/unit/test_day15_artifact.py::"
                "test_dependency_scan_rejects_installed_scanner_version_drift",
                "tests/unit/test_day15_artifact.py::"
                "test_runtime_rebuild_uses_two_distinct_clean_installs",
                "tests/unit/test_day15_artifact.py::"
                "test_runtime_lock_is_complete_exact_and_hash_locked",
                "tests/unit/test_day15_render_template.py::"
                "test_renderer_is_byte_deterministic_and_verifies_source_tools_and_commit",
                "tests/unit/test_day15_render_template.py::"
                "test_template_validator_requires_exact_sam_lint_and_translator_versions",
                "tests/unit/test_infrastructure_contract.py::"
                "test_function_url_targets_live_alias_and_has_exact_two_conditioned_permissions",
                "tests/unit/test_infrastructure_contract.py::"
                "test_immutable_versions_and_live_aliases_are_retained_for_rollback",
                "tests/unit/test_infrastructure_contract.py::"
                "test_region_is_explicit_and_public_ingress_preserves_all_mutation_vetoes",
                "tests/unit/test_infrastructure_contract.py::"
                "test_state_table_is_retained_recoverable_encrypted_and_deletion_protected",
            ),
            commit_anchor=PHASE3_IAC_COMMIT,
            limitations="Phase 3 repository evidence only; it proves static artifact, template, tag, and manifest contracts, not effective IAM, a built release installed in an account, or any deployment.",
        ),
        _claim(
            "DAY15-RUNTIME-GUARDS-01",
            "Judge inputs cannot set authority or budgets; fresh investigations use exact server budgets, atomic daily quota reservations, and finite read-only status observations.",
            "TEST",
            (
                "src/aioa_cloudops_agent/deployment/config.py::JudgeInvestigationRequest",
                "src/aioa_cloudops_agent/deployment/config.py::new_judge_budget",
                "src/aioa_cloudops_agent/deployment/quota.py::DynamoDbJudgeQuotaRepository",
                "src/aioa_cloudops_agent/deployment/status.py::ReadOnlyRunStatusService",
                "src/aioa_cloudops_agent/judge/runtime.py::JudgeInvestigationRuntime",
            ),
            (
                "tests/unit/test_day15_judge_runtime.py::"
                "test_each_investigation_builds_fresh_snapshot_session_agent_and_server_budget",
                "tests/unit/test_day15_runtime_contracts.py::"
                "test_dynamodb_quota_uses_one_conditional_update_for_all_caps",
                "tests/unit/test_day15_runtime_contracts.py::"
                "test_judge_schema_rejects_caller_authority_and_budget_fields",
                "tests/unit/test_day15_runtime_contracts.py::"
                "test_server_owned_judge_budget_is_exact_and_fresh",
                "tests/unit/test_day15_runtime_contracts.py::"
                "test_status_observation_cap_is_server_enforced_for_every_nonterminal_state",
            ),
            commit_anchor=DAY15_M1_COMMIT,
            scope="mocked AWS",
            limitations="Proves server-owned bounds with deterministic repositories and clients, not production quota-service availability.",
        ),
        _claim(
            "DAY15-TELEMETRY-01",
            "Judge telemetry exports only allowlisted identifiers and bounded classifications while structured logging discards prompts, secrets, and tool arguments.",
            "TEST",
            (
                "src/aioa_cloudops_agent/judge/logging.py::StructuredJudgeLogger",
                "src/aioa_cloudops_agent/judge/telemetry.py::SanitizedXRaySpanExporter",
                "src/aioa_cloudops_agent/judge/telemetry.py::initialize_judge_telemetry",
            ),
            (
                "tests/unit/test_day15_judge_http.py::"
                "test_structured_logger_discards_secrets_prompts_and_tool_arguments",
                "tests/unit/test_day15_judge_runtime.py::"
                "test_runtime_emits_real_allowlisted_operation_span_without_sensitive_values",
                "tests/unit/test_day15_judge_telemetry.py::"
                "test_process_telemetry_uses_exact_sampled_provider_and_empty_unredacted_opt_in",
                "tests/unit/test_day15_judge_telemetry.py::"
                "test_xray_exporter_emits_only_allowlisted_ids_route_outcome_and_dependency",
            ),
            commit_anchor=DAY15_M1_COMMIT,
            limitations="Proves filtering and exporter construction with local fakes; no provider trace delivery is attested.",
        ),
        _claim(
            "VERIFIED-SUCCESS-01",
            "SUCCESS_WITH_EVIDENCE is reached only after independent verification evidence is durably recorded.",
            "TEST",
            (
                "src/aioa_cloudops_agent/nz/enums.py::WorkflowState.SUCCESS_WITH_EVIDENCE",
                "src/aioa_cloudops_agent/verification/coordinator.py::BoundedVerificationCoordinator.verify",
            ),
            (
                "P0-09",
                "tests/unit/test_verification_closure.py::"
                "test_success_transition_without_durable_verification_evidence_is_rejected",
            ),
            commit_anchor=LOCAL_FIRST_PHASE1_COMMIT,
            scope="mocked AWS",
            limitations="Proves mocked verification and durable ordering, not a live EC2 observation.",
        ),
    ]
    return sorted(claims, key=lambda item: item["claim_id"])


def build_manifest(root: Path = ROOT) -> dict[str, Any]:
    """Build solely from reviewed constants and current canonical runtime definitions."""

    strands_version = project_strands_version(root)
    strands_requirement = project_strands_requirement(root)
    snapshot = {
        "commit": EVIDENCE_SNAPSHOT_COMMIT,
        "primary_agent_count": PRIMARY_AGENT_COUNT,
        "registered_tool_count": CURRENT_REGISTERED_TOOL_COUNT,
        "canonical_tools": list(CURRENT_TOOL_NAMES),
        "final_tool_cap": FINAL_TOOL_CAP,
        "bedrock_model_id": DEFAULT_BEDROCK_MODEL_ID,
        "bedrock_region": DEFAULT_BEDROCK_REGION,
        "strands_version": strands_version,
        "strands_requirement": strands_requirement,
        "phase1_tag": {"name": PHASE1_TAG, "commit": EXPECTED_PHASE1_TAG},
        "prior_armor_commits": list(PRIOR_ARMOR_COMMITS),
        "prior_art_blobs": dict(sorted(PRIOR_ART_BLOBS.items())),
        "p0": {
            "status": "PASS",
            "gate_count": len(P0_GATES),
            "proof_cases": P0_PROOF_CASES,
        },
        "p1": {
            "status": "PASS",
            "gate_count": len(P1_GATES),
            "proof_cases": P1_PROOF_CASES,
        },
    }
    day15_candidate_snapshot = {
        "status": DAY15_CANDIDATE_STATUS,
        "start_commit": DAY15_START_COMMIT,
        "m1_commit": DAY15_M1_COMMIT,
        "commit": DAY15_G10_COMMIT,
        "primary_agent_count": PRIMARY_AGENT_COUNT,
        "registered_tool_count": CURRENT_REGISTERED_TOOL_COUNT,
        "canonical_tools": list(CURRENT_TOOL_NAMES),
        "final_tool_cap": FINAL_TOOL_CAP,
        "bedrock_model_id": DEFAULT_BEDROCK_MODEL_ID,
        "bedrock_region": DEFAULT_BEDROCK_REGION,
        "strands_version": strands_version,
        "strands_requirement": strands_requirement,
        "day15_gate_ids": [gate.gate_id for gate in DAY15_GATES],
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "evidence_snapshot": snapshot,
        "day15_candidate_snapshot": day15_candidate_snapshot,
        "claims": build_claims(),
        "live_receipts": [],
    }
    manifest["manifest_hash"] = manifest_hash(manifest)
    return manifest


def normalize_manifest(document: dict[str, Any]) -> dict[str, Any]:
    """Normalize semantic sets while preserving authoritative tool and history ordering."""

    normalized = deepcopy(document)
    claims = normalized.get("claims")
    if isinstance(claims, list):
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            for field in ("authority_source", "proof_nodes"):
                values = claim.get(field)
                if isinstance(values, list) and all(isinstance(value, str) for value in values):
                    claim[field] = sorted(values)
        normalized["claims"] = sorted(
            claims,
            key=lambda item: item.get("claim_id", "") if isinstance(item, dict) else "",
        )
    receipts = normalized.get("live_receipts")
    if isinstance(receipts, list):
        normalized["live_receipts"] = sorted(
            receipts,
            key=lambda item: (
                str(item.get("claim_id", "")),
                str(item.get("path", "")),
                str(item.get("sha256", "")),
            )
            if isinstance(item, dict)
            else ("", "", ""),
        )
    return normalized


def canonical_manifest_bytes(document: dict[str, Any]) -> bytes:
    """Return normalized reviewer JSON with stable key and claim ordering."""

    return (
        json.dumps(
            normalize_manifest(document),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def manifest_hash(document: dict[str, Any]) -> str:
    """Hash the whole normalized manifest except the derived top-level hash itself."""

    material = normalize_manifest(document)
    material.pop("manifest_hash", None)
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(document: dict[str, Any]) -> str:
    """Render the Markdown view from the same normalized claim model as JSON."""

    manifest = normalize_manifest(document)
    snapshot = manifest["evidence_snapshot"]
    candidate = manifest["day15_candidate_snapshot"]
    claims = manifest["claims"]
    lines = [
        "# Reviewer Evidence Manifest",
        "",
        "This judge-facing view is generated from the canonical JSON. It is reviewer proof, not runtime authority.",
        "",
        f"- Frozen Phase 1 / Day 14 snapshot: `{snapshot['commit']}`",
        f"- Day 15 local candidate snapshot: `{candidate['commit']}` (`{candidate['status']}`)",
        "- Day 15 additive recovery lineage: "
        + " -> ".join(f"`{commit}`" for commit in DAY15_RECOVERY_LINEAGE),
        f"- Day 15 gates: `{', '.join(candidate['day15_gate_ids'])}`",
        f"- Manifest SHA-256: `{manifest['manifest_hash']}`",
        f"- Primary agents: `{snapshot['primary_agent_count']}`",
        f"- Canonical tools: `{', '.join(snapshot['canonical_tools'])}`",
        f"- Bedrock model: `{snapshot['bedrock_model_id']}` in `{snapshot['bedrock_region']}`",
        f"- Strands Agents: `{snapshot['strands_version']}`",
        f"- P0: `{snapshot['p0']['gate_count']}/{snapshot['p0']['gate_count']} PASS`, `{snapshot['p0']['proof_cases']}` proof cases",
        f"- P1: `{snapshot['p1']['gate_count']}/{snapshot['p1']['gate_count']} PASS`, `{snapshot['p1']['proof_cases']}` proof cases",
        f"- Claims: `{len(claims)}`",
        f"- Sanitized live receipts: `{len(manifest['live_receipts'])}`",
        "",
        "| Claim ID | Status | Kind | Scope | Conservative claim |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        "| "
        + " | ".join(
            _markdown_cell(claim[field])
            for field in ("claim_id", "status", "evidence_kind", "scope", "claim")
        )
        + " |"
        for claim in claims
    )
    lines.extend(["", "## Exact proof map", ""])
    for claim in claims:
        lines.extend(
            [
                f"### {claim['claim_id']}",
                "",
                claim["claim"],
                "",
                f"- Status / kind / scope: `{claim['status']}` / `{claim['evidence_kind']}` / `{claim['scope']}`",
                f"- Commit anchor: `{claim['commit_anchor']}`",
                "- Authority source:",
                *[f"  - `{source}`" for source in claim["authority_source"]],
                "- Proof nodes:",
                *(
                    [f"  - `{node}`" for node in claim["proof_nodes"]]
                    if claim["proof_nodes"]
                    else ["  - None: no live receipt is present."]
                ),
                f"- Limitations: {claim['limitations']}",
                f"- Claim SHA-256: `{claim['hash']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Truthfulness boundary",
            "",
            "Static source and mocked tests prove bounded code behavior. They do not prove a live AWS action. A live-event claim remains `NOT_YET_PROVEN` until a separate sanitized receipt is deliberately reviewed and added.",
            "",
        ]
    )
    return "\n".join(lines)


def render_evidence_readme() -> str:
    """Render the reviewed operating contract for the generated evidence files."""

    return f"""# Reviewer evidence

The AU-3 manifest maps conservative project claims to the source, tests, gates, and immutable Git snapshot that support them. It is a reviewer index only; runtime policy, typed contracts, durable approval, and the private executor remain the authority boundaries.

## Rebuild and validate

From the repository root in the documented development environment:

```bash
.venv/bin/python scripts/build_reviewer_evidence_manifest.py
.venv/bin/python scripts/build_reviewer_evidence_manifest.py --check
.venv/bin/python scripts/validate_reviewer_evidence_manifest.py
```

The immutable Phase 1 / Day 14 baseline remains anchored to `{EVIDENCE_SNAPSHOT_COMMIT}`. Unchanged Day 15 M1 claims remain at their original reviewed commit `{DAY15_ORIGINAL_M1_COMMIT}`; recovered telemetry and runtime-guard claims use `{DAY15_M1_COMMIT}`. Credential-free Local-First authority begins with the reviewed Phase 1 foundation `{LOCAL_FIRST_PHASE1_COMMIT}` and Phase 2 implementation `{LOCAL_FIRST_PHASE2_COMMIT}`. The provider-neutral primary-agent topology, tool surface, and cold-resume factory authority are anchored to portable B1 commit `{PORTABLE_B1_COMMIT}`. The historical B3 judge surface is `{PORTABLE_B3_COMMIT}`; four approval, execution, proposal, and model-authority claims changed by reliability/security hardening remain anchored to portable B4 commit `{PORTABLE_B4_COMMIT}`. The container-aware judge-surface boundary is anchored to portable B5 container commit `{PORTABLE_B5_CONTAINER_COMMIT}`. The three authority sources changed during Phase 3 are explicitly re-anchored: current Day 15 gate plus SAM release safety at `{PHASE3_IAC_COMMIT}`, and the RC package/SDK pin at `{PHASE3_RC_COMMIT}`. The preserved Day 15 recovery lineage, in order, is `{DAY15_START_COMMIT}`, then `{DAY15_ORIGINAL_M1_COMMIT}`, `{DAY15_ORIGINAL_M2_COMMIT}`, `{DAY15_ORIGINAL_M3_COMMIT}`, `{DAY15_M1_COMMIT}`, `{DAY15_M2_COMMIT}`, `{DAY15_FINAL_BLOCKER_COMMIT}`, `{DAY15_SECRET_FIX_COMMIT}`, `{DAY15_G10_IMPLEMENTATION_COMMIT}`, `{DAY15_G10_EVIDENCE_COMMIT}`, `{DAY15_G10_BLOCKER_COMMIT}`, `{DAY15_NOVA_PROBE_FIX_COMMIT}`, `{DAY15_G10_REANCHOR_COMMIT}`, and `{DAY15_G10_COMMIT}`. The candidate snapshot is deliberately `LOCAL_IMPLEMENTATION_CANDIDATE`; it records no live AWS observation, change set, or deployment. The builder never derives an anchor from changing `HEAD`; every claim anchor names a prior immutable implementation commit, avoiding a self-referential commit hash.

## Canonical model

Each claim contains the required `claim_id`, `claim`, `evidence_kind`, `authority_source`, `proof_nodes`, `commit_anchor`, `status`, `scope`, `limitations`, and `hash` fields. Python authority references use `path::symbol`; exact non-Python anchors use `path#text`; a path alone proves a tracked regular file. Pytest proof nodes use their exact `path::test_name`; P0/P1 and D15 nodes use exact gate IDs.

Claim hashes are SHA-256 over compact, key-sorted UTF-8 JSON with the derived `hash` removed and set-like source/proof lists sorted. `manifest_hash` covers the normalized complete document except itself. Canonical JSON uses sorted keys, two-space indentation, sorted claims, and one final newline. The Markdown view is generated from the same normalized model.

The validator resolves authority files and Python symbols at each claim's exact reviewed commit, resolves exact pytest nodes, and requires every referenced current source/test blob to remain byte-identical to that anchor. It admits only the frozen baseline, original M1, recovered M1, historical M2, current G10, Local-First Phase 1, and Local-First Phase 2 claim anchors; verifies their required ancestry plus the preserved Day 15 single-parent recovery chain; and extracts the Day 15 gate IDs independently from the immutable G10 Git object. It also checks the explicitly qualified frozen Phase 1 tag and requires every prior-art path to remain a tracked regular file with its immutable blob. Runtime one-agent/five-tool facts must match roots extracted directly from the immutable baseline object, so a synchronized five-for-five tool substitution or emptied provenance baseline cannot be regenerated into truth. Nova 2, its runtime region, and exact `strands-agents[otel]==1.53.0` pins are validated independently against frozen expectations.

## Live-proof boundary

Source, static checks, and mocked tests do not prove a live AWS event. The manifest therefore records the live EC2 claim as `NOT_YET_PROVEN` and contains no live receipt. A future positive live claim must use `LIVE_RECEIPT`, reference a separately reviewed and tracked sanitized receipt under `docs/evidence/live-receipts/`, and match its SHA-256.

A receipt has a closed schema: claim binding, exact `ec2:StopInstances` operation and region, distinct nonzero hashed target/request/verification identifiers, stopped observation, `SUCCESS_WITH_EVIDENCE`, explicit UTC event time, operator-attested sanitized-export provenance, the fixed affirmative attestation contract, and `sanitized: true`. The event time must fall deterministically between the L1 snapshot commit and the Git commit that introduced the receipt. Unknown or duplicate fields, noncanonical JSON, contradictory/synthetic attestation, raw provider responses, weak evidence hashes, and privacy material fail validation. Promotion also requires an intentional reviewed builder change; inserting a receipt only into generated JSON fails generator-drift validation.

The validator treats any unreviewed live-mutation statement as receipt-requiring, so relabeling it as a local test cannot bypass the proof boundary. It also rejects local paths, account identifiers, credentials, secret-like material, raw prompts, and private machine metadata.
"""


def _trusted_output_parent(path: Path) -> bool:
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return False
    current = ROOT
    for part in relative.parts[:-1]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            return False
    return True


def _safe_output_bytes(path: Path) -> bytes | None:
    if not _trusted_output_parent(path):
        raise OSError("evidence output parent is not a trusted repository directory")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise OSError("evidence output is not a regular file")
    return path.read_bytes()


def _write_if_changed(path: Path, content: bytes) -> None:
    existing = _safe_output_bytes(path)
    if existing == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _trusted_output_parent(path):
        raise OSError("evidence output parent changed during creation")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            os.fchmod(temporary.fileno(), 0o644)
        os.replace(temporary_name, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail instead of rewriting drift")
    parser.add_argument("--json", action="store_true", help="emit a stable machine result")
    args = parser.parse_args()

    claim_count = 0
    try:
        manifest = build_manifest()
        claim_count = len(manifest["claims"])
        expected_json = canonical_manifest_bytes(manifest)
        expected_markdown = render_markdown(manifest).encode("utf-8")
        expected_readme = render_evidence_readme().encode("utf-8")
        drift = (
            _safe_output_bytes(JSON_PATH) != expected_json
            or _safe_output_bytes(MARKDOWN_PATH) != expected_markdown
            or _safe_output_bytes(README_PATH) != expected_readme
        )
        if args.check and drift:
            status = "FAIL"
            reason = "GENERATED_EVIDENCE_DRIFT"
        else:
            if not args.check:
                _write_if_changed(JSON_PATH, expected_json)
                _write_if_changed(MARKDOWN_PATH, expected_markdown)
                _write_if_changed(README_PATH, expected_readme)
            status = "PASS"
            reason = ""
    except (OSError, ValueError, TypeError, tomllib.TOMLDecodeError):
        status = "FAIL"
        reason = "MANIFEST_BUILD_FAILED"

    payload = {
        "status": status,
        "claim_count": claim_count if status == "PASS" else 0,
        "reason": reason,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    elif status == "PASS":
        print(f"EVIDENCE_BUILD PASS claims={claim_count} deterministic=yes")
    else:
        print(f"EVIDENCE_BUILD FAIL reason={reason}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
