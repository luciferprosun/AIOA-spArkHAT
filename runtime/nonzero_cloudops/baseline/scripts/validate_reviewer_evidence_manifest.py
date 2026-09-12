#!/usr/bin/env python3
"""Validate AU-3 evidence structure, exact proof nodes, pins, Git anchors, and truth."""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import os
import re
import stat
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path, PurePosixPath
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
from scripts.build_reviewer_evidence_manifest import (  # noqa: E402
    DAY15_CANDIDATE_STATUS,
    DAY15_FINAL_BLOCKER_COMMIT,
    DAY15_G10_BLOCKER_COMMIT,
    DAY15_G10_COMMIT,
    DAY15_G10_EVIDENCE_COMMIT,
    DAY15_G10_IMPLEMENTATION_COMMIT,
    DAY15_G10_REANCHOR_COMMIT,
    DAY15_M1_COMMIT,
    DAY15_M2_COMMIT,
    DAY15_NOVA_PROBE_FIX_COMMIT,
    DAY15_ORIGINAL_M1_COMMIT,
    DAY15_ORIGINAL_M2_COMMIT,
    DAY15_ORIGINAL_M3_COMMIT,
    DAY15_RECOVERY_LINEAGE,
    DAY15_SECRET_FIX_COMMIT,
    DAY15_START_COMMIT,
    EVIDENCE_SNAPSHOT_COMMIT,
    EXPECTED_BEDROCK_REGION,
    EXPECTED_MODEL_ID,
    EXPECTED_STRANDS_REQUIREMENT,
    EXPECTED_STRANDS_VERSION,
    JSON_PATH,
    LIVE_EC2_NOT_PROVEN_CLAIM,
    LOCAL_FIRST_PHASE1_COMMIT,
    LOCAL_FIRST_PHASE2_COMMIT,
    MARKDOWN_PATH,
    P0_PROOF_CASES,
    P1_PROOF_CASES,
    PHASE3_IAC_COMMIT,
    PHASE3_RC_COMMIT,
    PORTABLE_B3_COMMIT,
    PORTABLE_B4_COMMIT,
    PORTABLE_B5_CONTAINER_COMMIT,
    PRIOR_ARMOR_COMMITS,
    README_PATH,
    SCHEMA_VERSION,
    build_manifest,
    canonical_manifest_bytes,
    claim_hash,
    manifest_hash,
    project_strands_requirement,
    project_strands_version,
    render_evidence_readme,
    render_markdown,
)
from scripts.day15.run_day15_gate import GATES as DAY15_GATES  # noqa: E402
from scripts.run_p0_gate import (  # noqa: E402
    EXPECTED_PHASE1_TAG,
    EXPECTED_PRE_ARMOR_HEAD,
    PHASE1_TAG,
    PRIOR_ART_BLOBS,
)
from scripts.run_p0_gate import GATES as P0_GATES  # noqa: E402
from scripts.run_p1_gate import GATES as P1_GATES  # noqa: E402

_TOP_LEVEL_FIELDS = {
    "schema_version",
    "evidence_snapshot",
    "day15_candidate_snapshot",
    "claims",
    "live_receipts",
    "manifest_hash",
}
_DAY15_CANDIDATE_FIELDS = {
    "status",
    "start_commit",
    "m1_commit",
    "commit",
    "primary_agent_count",
    "registered_tool_count",
    "canonical_tools",
    "final_tool_cap",
    "bedrock_model_id",
    "bedrock_region",
    "strands_version",
    "strands_requirement",
    "day15_gate_ids",
}
_SNAPSHOT_FIELDS = {
    "commit",
    "primary_agent_count",
    "registered_tool_count",
    "canonical_tools",
    "final_tool_cap",
    "bedrock_model_id",
    "bedrock_region",
    "strands_version",
    "strands_requirement",
    "phase1_tag",
    "prior_armor_commits",
    "prior_art_blobs",
    "p0",
    "p1",
}
_CLAIM_FIELDS = {
    "claim_id",
    "claim",
    "evidence_kind",
    "authority_source",
    "proof_nodes",
    "commit_anchor",
    "status",
    "scope",
    "limitations",
    "hash",
}
_RECEIPT_FIELDS = {"claim_id", "path", "sha256"}
_RECEIPT_DOCUMENT_FIELDS = {
    "schema_version",
    "claim_id",
    "operation",
    "region",
    "target_fingerprint",
    "request_reference_hash",
    "verification_evidence_hash",
    "observed_state",
    "result",
    "occurred_at",
    "provenance",
    "operator_attestation",
    "sanitized",
}
_EVIDENCE_KINDS = {
    "STATIC",
    "TEST",
    "GIT",
    "DOC",
    "OPERATOR_ATTESTATION",
    "LIVE_RECEIPT",
}
_STATUSES = {"PROVEN", "PARTIAL", "NOT_YET_PROVEN", "ATTESTED_ONLY"}
_SCOPES = {"Local deterministic", "mocked AWS", "live AWS", "documentation", "submission"}
_REQUIRED_CLAIM_IDS = {
    "AGENT-TOPOLOGY-01",
    "APPROVAL-BINDING-01",
    "BOUNDED-FAILURES-01",
    "DEFAULT-DENY-01",
    "DAY15-AWS-CLIENT-BOUNDS-01",
    "DAY15-COLD-RESUME-01",
    "DAY15-DEPLOYMENT-GATE-01",
    "DAY15-JUDGE-SURFACE-01",
    "DAY15-RELEASE-SAFETY-01",
    "DAY15-RUNTIME-GUARDS-01",
    "DAY15-TELEMETRY-01",
    "EXECUTOR-GATES-01",
    "IAM-SEPARATION-01",
    "IDEMPOTENCY-01",
    "LIVE-EC2-01",
    "LOCAL2-HITL-EXECUTION-01",
    "LOCAL2-LOOPBACK-API-01",
    "MODEL-AUTHORITY-01",
    "MODEL-PIN-01",
    "P0-GATE-01",
    "P1-GATE-01",
    "PRIOR-ART-ATTESTATION-01",
    "PRIOR-ART-HISTORY-01",
    "PROPOSAL-DURABILITY-01",
    "RECOVERY-NO-REPLAY-01",
    "SDK-PIN-01",
    "TOOL-SURFACE-01",
    "VERIFIED-SUCCESS-01",
}
_CLAIM_ID = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST_IN_TEXT = re.compile(r"(?<![A-Za-z0-9])(?:[0-9a-f]{64}|[0-9a-f]{40})(?![A-Za-z0-9])")
_ACCOUNT_ID = re.compile(r"(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])")
_FORMATTED_ACCOUNT_ID = re.compile(
    r"(?<![A-Za-z0-9])[0-9]{4}[- ][0-9]{4}[- ][0-9]{4}(?![A-Za-z0-9])"
)
_LABELED_ACCOUNT_ID = re.compile(
    r"(?i)\b(?:aws[_-]?account|account|acct)[_:= -]*[0-9]{12}\b|"
    r"(?<![0-9])[0-9]{3}\.[0-9]{3}\.[0-9]{3}\.[0-9]{3}(?![0-9])"
)
_AWS_ACCESS_ID = re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|AIPA|ANPA|ANVA)[A-Z0-9]{16}\b")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(
        r"(?i)\b(?:password|secret|access[_ -]?token|api[_ -]?key|credential|token|"
        r"client[_ -]?secret)\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(
        r"(?i)\b(?:aws_secret_access_key|secret_access_key)\s*[:=]\s*"
        r"['\"]?[A-Za-z0-9/+=]{40}\b"
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{16,}\b"),
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@"),
)
_BARE_AWS_SECRET = re.compile(
    r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"
)
_ABSOLUTE_LOCAL_PATH = re.compile(
    r"(?<![A-Za-z0-9_/])(?:~(?:[A-Za-z0-9._-]+)?/(?:[^\s'\"`<>]+)|"
    r"/(?!/)[A-Za-z0-9._~-]+(?:/[^\s'\"`<>]*)?)|"
    r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]|file://",
    re.IGNORECASE,
)
_WINDOWS_UNC_PATH = re.compile(
    r"(?<!\\)\\{2,}(?:\?\\UNC\\)?[^\\/\s]+[\\/][^\s'\"`<>]+",
    re.IGNORECASE,
)
_DOUBLE_SLASH_PATH = re.compile(
    r"(?<![:/])/{2,}[^\\/\s]+[\\/][^\s'\"`<>]+",
    re.IGNORECASE,
)
_WINDOWS_ROOTED_PATH = re.compile(
    r"(?<![A-Za-z0-9_\\])\\(?!\\)[A-Za-z0-9._~-]+[\\/][^\s'\"`<>]+",
    re.IGNORECASE,
)
_SENSITIVE_KEY = re.compile(
    r"(?:password|secret|credential|access[_-]?key|private[_-]?key|raw[_-]?prompt|"
    r"prompt[_-]?text|(?:^|[_-])prompt(?:$|[_-])|access[_-]?token|refresh[_-]?token)",
    re.IGNORECASE,
)
_PRIVATE_METADATA_KEY = re.compile(
    r"(?:hostname|host_name|machine_name|user_name|username|home_directory|working_directory|cwd)",
    re.IGNORECASE,
)
_LIVE_MUTATION_SUBJECT = re.compile(
    r"(?i)(?:\b(?:live|real|actual|production|prod|provider)\b.{0,64}"
    r"\b(?:AWS|EC2|cloud|mutation|instance|StopInstances)\b|"
    r"\b(?:AWS|EC2|cloud|mutation|instance|StopInstances)\b.{0,64}"
    r"\b(?:live|real|actual|production|prod|provider)\b|"
    r"\b(?:StopInstances|StartInstances|TerminateInstances|RebootInstances)\b)"
)
_REVIEWED_NEGATIVE_LIVE_STATEMENTS = {
    LIVE_EC2_NOT_PROVEN_CLAIM,
    "The checked-in orchestrator policy can invoke only the private executor and has no direct EC2 StopInstances action.",
    "Records deterministic repository proof; it is not a live AWS deployment test.",
    "Proves mocked verification and durable ordering, not a live EC2 observation.",
}
_RECEIPT_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
_FROZEN_L1_COMMIT = "fbb536400594306f2bb3abd31c7064a66735c82d"
_FROZEN_DAY15_START_COMMIT = "aa941a989a8b8cd0e40367bb130472e9f3c082a7"
_FROZEN_DAY15_ORIGINAL_M1_COMMIT = "17d5f4637dbd69a33eff1cbb46282c36b19ce6ad"
_FROZEN_DAY15_ORIGINAL_M2_COMMIT = "8e4583ac9341cb7b66de47cf0e7b2a442ac67b32"
_FROZEN_DAY15_ORIGINAL_M3_COMMIT = "30c2a30cda0ac6d6e2003166daf6c29bf2c764f0"
_FROZEN_DAY15_M1_COMMIT = "f2ee79c09ba174ba72cb527b70c095f412151758"
_FROZEN_DAY15_M2_COMMIT = "36fd17df981dfa593d4e63f6a143410317410763"
_FROZEN_DAY15_FINAL_BLOCKER_COMMIT = "ce35a67f6491ea92aeef534d0dc4f5dc4a8da7ff"
_FROZEN_DAY15_SECRET_FIX_COMMIT = "5a6127f43a9251a72203c0eb6c7a903d817599f7"
_FROZEN_DAY15_G10_IMPLEMENTATION_COMMIT = "3464bc869e7a11acb5aab61ae279cf196a1ebd0f"
_FROZEN_DAY15_G10_EVIDENCE_COMMIT = "41ba5586180e9aa3a25fc5469d42815073a0bbf8"
_FROZEN_DAY15_G10_BLOCKER_COMMIT = "858770d5e5c7b59fa883cc56e06f4a9e915d70c1"
_FROZEN_DAY15_NOVA_PROBE_FIX_COMMIT = "5e1904408d402c1e6492d6b2e153a7f1a5c56b58"
_FROZEN_DAY15_G10_REANCHOR_COMMIT = "99f70c43a26ce9715e9b57fde81ca265382dd5f2"
_FROZEN_DAY15_G10_COMMIT = "197db56f828b8ab0b9139a1d3708fb8a58ca336a"
_FROZEN_LOCAL_FIRST_PHASE1_COMMIT = "b5dba16a9af1bc979b2b96a50ddbf0e590e829a5"
_FROZEN_LOCAL_FIRST_PHASE2_COMMIT = "7ffe0cf7c9ca4a5c7c311fd5394a245e80bb78e0"
_FROZEN_PHASE3_IAC_COMMIT = "c16f6829e8b258af86523b0b1d61e34586702b63"
_FROZEN_PHASE3_RC_COMMIT = "5ac15d30a604434713490d77edb573d14a8f1dcd"
_FROZEN_PORTABLE_B1_COMMIT = "a2e16d0f1d625b34916440d6740a486f73cf2bb1"
_FROZEN_PORTABLE_B3_COMMIT = "1882089fbb41a3f7f3cbad821ed9d6d8c6c2e9a5"
_FROZEN_PORTABLE_B4_COMMIT = "a455379eb3de73bf6c1780b3c4726b0778873dd4"
_FROZEN_PORTABLE_B5_CONTAINER_COMMIT = "d18f945a1484a1255339a3b4bcb1560c58d06d9b"
_FROZEN_DAY15_RECOVERY_LINEAGE = (
    _FROZEN_DAY15_START_COMMIT,
    _FROZEN_DAY15_ORIGINAL_M1_COMMIT,
    _FROZEN_DAY15_ORIGINAL_M2_COMMIT,
    _FROZEN_DAY15_ORIGINAL_M3_COMMIT,
    _FROZEN_DAY15_M1_COMMIT,
    _FROZEN_DAY15_M2_COMMIT,
    _FROZEN_DAY15_FINAL_BLOCKER_COMMIT,
    _FROZEN_DAY15_SECRET_FIX_COMMIT,
    _FROZEN_DAY15_G10_IMPLEMENTATION_COMMIT,
    _FROZEN_DAY15_G10_EVIDENCE_COMMIT,
    _FROZEN_DAY15_G10_BLOCKER_COMMIT,
    _FROZEN_DAY15_NOVA_PROBE_FIX_COMMIT,
    _FROZEN_DAY15_G10_REANCHOR_COMMIT,
    _FROZEN_DAY15_G10_COMMIT,
)
_FROZEN_DAY15_CANDIDATE_STATUS = "LOCAL_IMPLEMENTATION_CANDIDATE"
_FROZEN_DAY15_GATE_IDS = tuple(f"D15-G{index:02d}" for index in range(1, 11))
_FROZEN_L1_CLAIM_IDS = {
    "LIVE-EC2-01",
    "PRIOR-ART-ATTESTATION-01",
    "PRIOR-ART-HISTORY-01",
    "RECOVERY-NO-REPLAY-01",
}
_DAY15_ORIGINAL_M1_CLAIM_IDS = {
    "BOUNDED-FAILURES-01",
    "DAY15-AWS-CLIENT-BOUNDS-01",
    "DAY15-JUDGE-SURFACE-01",
    "EXECUTOR-GATES-01",
    "IAM-SEPARATION-01",
    "IDEMPOTENCY-01",
    "MODEL-PIN-01",
    "P0-GATE-01",
    "P1-GATE-01",
}
_DAY15_RECOVERED_M1_CLAIM_IDS = {
    "DAY15-RUNTIME-GUARDS-01",
    "DAY15-TELEMETRY-01",
}
_PORTABLE_B1_CLAIM_IDS = {
    "AGENT-TOPOLOGY-01",
    "DAY15-COLD-RESUME-01",
    "TOOL-SURFACE-01",
}
_PORTABLE_B3_CLAIM_IDS: set[str] = set()
_PORTABLE_B4_CLAIM_IDS = {
    "APPROVAL-BINDING-01",
    "LOCAL2-HITL-EXECUTION-01",
    "MODEL-AUTHORITY-01",
    "PROPOSAL-DURABILITY-01",
}
_PORTABLE_B5_CONTAINER_CLAIM_IDS = {"LOCAL2-LOOPBACK-API-01"}
_LOCAL_FIRST_PHASE1_CLAIM_IDS = {
    "DEFAULT-DENY-01",
    "VERIFIED-SUCCESS-01",
}
_LOCAL_FIRST_PHASE2_CLAIM_IDS: set[str] = set()
_PHASE3_IAC_CLAIM_IDS = {
    "DAY15-RELEASE-SAFETY-01",
    "DAY15-DEPLOYMENT-GATE-01",
}
_PHASE3_RC_CLAIM_IDS = {"SDK-PIN-01"}
_FROZEN_P0_PROOF_CASES = 136
_FROZEN_P1_PROOF_CASES = 93
_FROZEN_NEGATIVE_LIVE_FIELDS = {
    "claim": LIVE_EC2_NOT_PROVEN_CLAIM,
    "evidence_kind": "DOC",
    "authority_source": [
        "docs/architecture/day-14-p1-resilience.md#"
        "Deployment remains deferred to Day 15."
    ],
    "proof_nodes": [],
    "commit_anchor": _FROZEN_L1_COMMIT,
    "status": "NOT_YET_PROVEN",
    "scope": "live AWS",
    "limitations": (
        "No sanitized live receipt is present; source and mocked tests prove only "
        "bounded capability behavior."
    ),
}
_FROZEN_GATE_CLAIMS = {
    "P0-GATE-01": (
        "The canonical P0 matrix passed all 15 gates with 136 proof cases at its reviewed commit anchor.",
        tuple(f"P0-{index:02d}" for index in range(1, 16)),
    ),
    "P1-GATE-01": (
        "The canonical P1 matrix passed all 6 gates with 93 proof cases at its reviewed commit anchor.",
        tuple(f"P1-{index:02d}" for index in range(1, 7)),
    ),
}
_LIVE_RECEIPT_ATTESTATION = (
    "I attest that this sanitized receipt accurately represents the recorded live AWS event."
)
_PROMPT_TRANSCRIPT = re.compile(
    r"(?im)(?:^|\n)\s*(?:system|user|assistant|human|developer|tool|model)\s*:\s+|"
    r"<\|(?:system|user|assistant|human|developer|tool|model)\|>|"
    r"[\"']role[\"']\s*:\s*[\"'](?:system|user|assistant|human|developer|tool|model)[\"']"
)
_RAW_PROMPT_LABEL = re.compile(
    r"(?i)\b(?:(?:(?:raw|user|system|developer|model)[_ -]?)?prompt"
    r"(?:[_ -]?text)?|(?:model|llm)[_ -]?(?:input|request)|"
    r"instructions\s+sent\s+to\s+(?:the\s+)?model)"
    r"\s*(?::|=|-{1,2}>|\u2192|\u2014|\u2013)\s*\S"
)
_PROMPT_FOLLOWS = re.compile(r"(?i)\b(?:user\s+)?prompt\s+follows\b")
_PRIVATE_METADATA_VALUE = re.compile(
    r"(?i)\b[A-Za-z0-9_-]*(?:host(?:name)?|host_name|computername|machine(?:_name)?|"
    r"user(?:_name|name)?|logname|node(?:name|id)?|home_directory|working_directory|cwd|"
    r"private_ip|local_ip|ip_address)\s*[:=]\s*[^\s,;]+"
)
_PRIVATE_NETWORK_VALUE = re.compile(
    r"(?<![0-9])(?:10(?:\.[0-9]{1,3}){3}|172\.(?:1[6-9]|2[0-9]|3[01])"
    r"(?:\.[0-9]{1,3}){2}|192\.168(?:\.[0-9]{1,3}){2}|169\.254"
    r"(?:\.[0-9]{1,3}){2}|127(?:\.[0-9]{1,3}){3})(?![0-9])|"
    r"(?<![0-9A-Fa-f:])(?:f[cd][0-9A-Fa-f]{2}|fe8[0-9A-Fa-f]):",
    re.IGNORECASE,
)


class DuplicateJsonKey(ValueError):
    """Raised when input JSON attempts to hide material behind a duplicate key."""


@dataclass(frozen=True, slots=True)
class RuntimeFacts:
    primary_agent_count: int
    registered_tool_count: int
    canonical_tools: tuple[str, ...]
    final_tool_cap: int
    model_id: str
    region: str
    strands_version: str
    strands_requirement: str
    p0_gate_ids: tuple[str, ...]
    p1_gate_ids: tuple[str, ...]
    day15_gate_ids: tuple[str, ...]
    phase1_tag_name: str
    phase1_tag_commit: str
    pre_armor_head: str
    prior_armor_commits: tuple[str, ...]
    prior_art_blobs: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class FrozenFacts:
    canonical_tools: tuple[str, ...]
    phase1_tag_name: str
    phase1_tag_commit: str
    pre_armor_head: str
    prior_armor_commits: tuple[str, ...]
    prior_art_blobs: tuple[tuple[str, str], ...]


def collect_runtime_facts(root: Path = ROOT) -> RuntimeFacts:
    return RuntimeFacts(
        primary_agent_count=PRIMARY_AGENT_COUNT,
        registered_tool_count=CURRENT_REGISTERED_TOOL_COUNT,
        canonical_tools=tuple(CURRENT_TOOL_NAMES),
        final_tool_cap=FINAL_TOOL_CAP,
        model_id=DEFAULT_BEDROCK_MODEL_ID,
        region=DEFAULT_BEDROCK_REGION,
        strands_version=project_strands_version(root),
        strands_requirement=project_strands_requirement(root),
        p0_gate_ids=tuple(gate.gate_id for gate in P0_GATES),
        p1_gate_ids=tuple(gate.gate_id for gate in P1_GATES),
        day15_gate_ids=tuple(gate.gate_id for gate in DAY15_GATES),
        phase1_tag_name=PHASE1_TAG,
        phase1_tag_commit=EXPECTED_PHASE1_TAG,
        pre_armor_head=EXPECTED_PRE_ARMOR_HEAD,
        prior_armor_commits=PRIOR_ARMOR_COMMITS,
        prior_art_blobs=tuple(sorted(PRIOR_ART_BLOBS.items())),
    )


def _literal_assignments(source: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for node in ast.parse(source).body:
        name: str | None = None
        value: ast.expr | None = None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
        if name is None or value is None:
            continue
        try:
            values[name] = ast.literal_eval(value)
        except (ValueError, TypeError):
            continue
    return values


def _day15_gate_ids_from_source(source: str) -> tuple[str, ...]:
    """Extract only literal GateDefinition IDs from reviewed source."""

    value: ast.expr | None = None
    matches = 0
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "GATES"
                for target in node.targets
            )
        ) or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "GATES"
        ):
            value = node.value
            matches += 1
    if matches != 1 or not isinstance(value, (ast.Tuple, ast.List)):
        raise ValueError("Day 15 gate definition is not one literal sequence")
    gate_ids: list[str] = []
    for item in value.elts:
        if (
            not isinstance(item, ast.Call)
            or not isinstance(item.func, ast.Name)
            or item.func.id != "GateDefinition"
            or len(item.args) != 2
            or item.keywords
            or not isinstance(item.args[0], ast.Constant)
            or not isinstance(item.args[0].value, str)
            or not isinstance(item.args[1], ast.Constant)
            or not isinstance(item.args[1].value, str)
        ):
            raise ValueError("Day 15 gate definition contains nonliteral material")
        gate_ids.append(item.args[0].value)
    return tuple(gate_ids)


def collect_frozen_day15_gate_ids(root: Path = ROOT) -> tuple[str, ...]:
    """Read Day 15 gate IDs from the immutable candidate-bound G10 Git object."""

    source = _git_blob(
        root,
        _FROZEN_DAY15_G10_COMMIT,
        "scripts/day15/run_day15_gate.py",
    )
    if source is None:
        raise ValueError("frozen Day 15 gate source unavailable")
    return _day15_gate_ids_from_source(source)


def collect_frozen_facts(root: Path = ROOT) -> FrozenFacts:
    """Derive immutable roots from the reviewed L1 Git object, never current constants."""

    if EVIDENCE_SNAPSHOT_COMMIT != _FROZEN_L1_COMMIT:
        raise ValueError("evidence snapshot root drift")
    source = _git_blob(root, _FROZEN_L1_COMMIT, "scripts/run_p0_gate.py")
    if source is None:
        raise ValueError("frozen P0 source unavailable")
    values = _literal_assignments(source)
    tools = values.get("EXPECTED_TOOLS")
    phase1_tag_name = values.get("PHASE1_TAG")
    phase1_tag_commit = values.get("EXPECTED_PHASE1_TAG")
    pre_armor_head = values.get("EXPECTED_PRE_ARMOR_HEAD")
    prior_art_blobs = values.get("PRIOR_ART_BLOBS")
    if (
        not isinstance(tools, tuple)
        or not all(isinstance(tool, str) for tool in tools)
        or not isinstance(phase1_tag_name, str)
        or not isinstance(phase1_tag_commit, str)
        or not isinstance(pre_armor_head, str)
        or not isinstance(prior_art_blobs, dict)
        or not all(
            isinstance(path, str) and isinstance(digest, str)
            for path, digest in prior_art_blobs.items()
        )
    ):
        raise ValueError("frozen P0 literals invalid")
    history = _git(
        root,
        "rev-list",
        "--first-parent",
        "--reverse",
        f"{pre_armor_head}..{_FROZEN_L1_COMMIT}",
    )
    commits = tuple(history.stdout.splitlines())
    if history.returncode != 0 or len(commits) != 4 or commits[-1] != _FROZEN_L1_COMMIT:
        raise ValueError("frozen armor history invalid")
    return FrozenFacts(
        canonical_tools=tools,
        phase1_tag_name=phase1_tag_name,
        phase1_tag_commit=phase1_tag_commit,
        pre_armor_head=pre_armor_head,
        prior_armor_commits=commits[:-1],
        prior_art_blobs=tuple(sorted(prior_art_blobs.items())),
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(key)
        result[key] = value
    return result


def load_manifest(path: Path = JSON_PATH) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    document = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(document, dict):
        raise ValueError("manifest root must be an object")
    return document


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    try:
        return subprocess.run(
            ("git", *args),
            cwd=root,
            check=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(("git", *args), 126, stdout="", stderr="")


def _safe_relative_path(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\0" in value
        or ":" in value
        or "//" in value
        or any(character.isspace() for character in value)
    ):
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(
        part in {"", ".", "..", ".git"} or "~" in part for part in candidate.parts
    ):
        return None
    return candidate.as_posix()


def _git_blob(root: Path, commit: str, relative_path: str) -> str | None:
    listing = _git(root, "ls-tree", commit, "--", relative_path)
    rows = [row for row in listing.stdout.splitlines() if row.endswith(f"\t{relative_path}")]
    if listing.returncode != 0 or len(rows) != 1:
        return None
    metadata = rows[0].split("\t", maxsplit=1)[0].split()
    if len(metadata) != 3 or metadata[0] not in {"100644", "100755"} or metadata[1] != "blob":
        return None
    content = _git(root, "show", f"{commit}:{relative_path}")
    if content.returncode != 0:
        return None
    return content.stdout


def _regular_worktree_path(root: Path, relative_path: str) -> Path | None:
    """Resolve a regular path without following a symlink in any component."""

    safe_relative = _safe_relative_path(relative_path)
    if safe_relative is None:
        return None
    try:
        trusted_root = root.resolve(strict=True)
    except OSError:
        return None
    candidate = trusted_root
    parts = PurePosixPath(safe_relative).parts
    for index, part in enumerate(parts):
        candidate /= part
        try:
            metadata = candidate.lstat()
        except OSError:
            return None
        if stat.S_ISLNK(metadata.st_mode):
            return None
        if index < len(parts) - 1:
            if not stat.S_ISDIR(metadata.st_mode):
                return None
        elif not stat.S_ISREG(metadata.st_mode):
            return None
    try:
        candidate.resolve(strict=True).relative_to(trusted_root)
    except (OSError, ValueError):
        return None
    return candidate


def _regular_index_blob(root: Path, relative_path: str) -> str | None:
    index = _git(root, "ls-files", "-s", "--error-unmatch", "--", relative_path)
    rows = index.stdout.splitlines()
    if index.returncode != 0 or len(rows) != 1:
        return None
    metadata, separator, shown_path = rows[0].partition("\t")
    fields = metadata.split()
    if (
        separator != "\t"
        or shown_path != relative_path
        or len(fields) != 3
        or fields[0] not in {"100644", "100755"}
        or _COMMIT.fullmatch(fields[1]) is None
        or fields[2] != "0"
    ):
        return None
    return fields[1]


def _worktree_git_blob(root: Path, relative_path: str) -> str | None:
    path = _regular_worktree_path(root, relative_path)
    if path is None:
        return None
    digest = _git(
        root,
        "hash-object",
        f"--path={relative_path}",
        "--",
        relative_path,
    )
    if digest.returncode != 0 or _COMMIT.fullmatch(digest.stdout.strip()) is None:
        return None
    return digest.stdout.strip()


def _worktree_blob(root: Path, relative_path: str) -> str | None:
    index_blob = _regular_index_blob(root, relative_path)
    worktree_blob = _worktree_git_blob(root, relative_path)
    path = _regular_worktree_path(root, relative_path)
    if index_blob is None or worktree_blob != index_blob or path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _assigned_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for item in target.elts for name in _assigned_names(item)}
    return set()


def _defined_symbols(source: str) -> set[str]:
    tree = ast.parse(source)
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.ClassDef):
            symbols.add(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    symbols.add(f"{node.name}.{child.name}")
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        symbols.update(
                            f"{node.name}.{name}" for name in _assigned_names(target)
                        )
                elif isinstance(child, ast.AnnAssign):
                    symbols.update(
                        f"{node.name}.{name}" for name in _assigned_names(child.target)
                    )
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                symbols.update(_assigned_names(target))
        elif isinstance(node, ast.AnnAssign):
            symbols.update(_assigned_names(node.target))
    return symbols


def _authority_parts(reference: str) -> tuple[str, str, str] | None:
    if "::" in reference:
        path, symbol = reference.split("::", maxsplit=1)
        if not symbol:
            return None
        return path, "symbol", symbol
    if "#" in reference:
        path, anchor = reference.split("#", maxsplit=1)
        if not anchor:
            return None
        return path, "anchor", anchor
    return reference, "file", ""


def _validate_authority_source(
    root: Path,
    commit: str,
    reference: object,
    cache: dict[tuple[str, str], str | None],
) -> tuple[str, ...]:
    if not isinstance(reference, str):
        return ("AUTHORITY_SOURCE_TYPE",)
    parts = _authority_parts(reference)
    if parts is None:
        return ("AUTHORITY_SOURCE_FORMAT",)
    raw_path, locator_kind, locator = parts
    relative_path = _safe_relative_path(raw_path)
    if relative_path is None:
        return ("AUTHORITY_PATH_UNSAFE",)
    key = (commit, relative_path)
    if key not in cache:
        cache[key] = _git_blob(root, commit, relative_path)
    content = cache[key]
    if content is None:
        return ("AUTHORITY_PATH_MISSING",)
    current_key = ("WORKTREE", relative_path)
    if current_key not in cache:
        cache[current_key] = _worktree_blob(root, relative_path)
    current_content = cache[current_key]
    if current_content is None:
        return ("CURRENT_AUTHORITY_PATH_MISSING",)
    if locator_kind == "anchor" and locator not in content:
        return ("AUTHORITY_ANCHOR_MISSING",)
    if locator_kind == "anchor" and locator not in current_content:
        return ("CURRENT_AUTHORITY_ANCHOR_MISSING",)
    if locator_kind == "symbol":
        if not relative_path.endswith(".py"):
            return ("AUTHORITY_SYMBOL_NONPYTHON",)
        try:
            symbols = _defined_symbols(content)
        except SyntaxError:
            return ("AUTHORITY_SOURCE_SYNTAX",)
        if locator not in symbols:
            return ("AUTHORITY_SYMBOL_MISSING",)
        try:
            current_symbols = _defined_symbols(current_content)
        except SyntaxError:
            return ("CURRENT_AUTHORITY_SOURCE_SYNTAX",)
        if locator not in current_symbols:
            return ("CURRENT_AUTHORITY_SYMBOL_MISSING",)
    if current_content != content:
        return ("CURRENT_AUTHORITY_BLOB_DRIFT",)
    return ()


def _validate_test_node(
    root: Path,
    commit: str,
    node_id: str,
    cache: dict[tuple[str, str], str | None],
) -> tuple[str, ...]:
    if "[" in node_id or "]" in node_id:
        return ("PYTEST_PARAMETER_NODE_UNRESOLVED",)
    parts = node_id.split("::")
    if len(parts) not in {2, 3}:
        return ("PYTEST_NODE_FORMAT",)
    relative_path = _safe_relative_path(parts[0])
    if (
        relative_path is None
        or not relative_path.startswith("tests/")
        or not relative_path.endswith(".py")
    ):
        return ("PYTEST_PATH_UNSAFE",)
    key = (commit, relative_path)
    if key not in cache:
        cache[key] = _git_blob(root, commit, relative_path)
    content = cache[key]
    if content is None:
        return ("PYTEST_PATH_MISSING",)
    current_key = ("WORKTREE", relative_path)
    if current_key not in cache:
        cache[current_key] = _worktree_blob(root, relative_path)
    current_content = cache[current_key]
    if current_content is None:
        return ("CURRENT_PYTEST_PATH_MISSING",)
    if current_content != content:
        return ("CURRENT_PYTEST_BLOB_DRIFT",)
    function_name = parts[-1]
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return ("PYTEST_SOURCE_SYNTAX",)
    if len(parts) == 2:
        exists = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
            for node in tree.body
        )
    else:
        class_name = parts[1]
        exists = any(
            isinstance(node, ast.ClassDef)
            and node.name == class_name
            and any(
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name == function_name
                for child in node.body
            )
            for node in tree.body
        )
    if not exists:
        return ("PYTEST_NODE_MISSING",)
    try:
        current_tree = ast.parse(current_content)
    except SyntaxError:
        return ("CURRENT_PYTEST_SOURCE_SYNTAX",)
    if len(parts) == 2:
        current_exists = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
            for node in current_tree.body
        )
    else:
        class_name = parts[1]
        current_exists = any(
            isinstance(node, ast.ClassDef)
            and node.name == class_name
            and any(
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name == function_name
                for child in node.body
            )
            for node in current_tree.body
        )
    return () if current_exists else ("CURRENT_PYTEST_NODE_MISSING",)


def _normalized_public_text(value: str) -> str:
    public_text = value
    for _ in range(4):
        normalized = unicodedata.normalize("NFKC", html.unescape(public_text))
        if normalized == public_text:
            break
        public_text = normalized
    return public_text


def _scan_private_material(value: object, *, key: str = "") -> tuple[str, ...]:
    reasons: list[str] = []
    if key and _SENSITIVE_KEY.search(key):
        reasons.append("SECRET_LIKE_KEY")
    if key and _PRIVATE_METADATA_KEY.fullmatch(key):
        reasons.append("PRIVATE_MACHINE_METADATA")
    if isinstance(value, dict):
        if value.get("role") in {"system", "user", "assistant"} and "content" in value:
            reasons.append("RAW_PROMPT_MATERIAL")
        for child_key, child in value.items():
            reasons.extend(_scan_private_material(child, key=str(child_key)))
    elif isinstance(value, list):
        for child in value:
            reasons.extend(_scan_private_material(child))
    elif isinstance(value, str):
        public_text = _normalized_public_text(value)
        account_scan_text = _DIGEST_IN_TEXT.sub("", public_text)
        if any(unicodedata.category(character) == "Cf" for character in public_text):
            reasons.append("OBFUSCATING_UNICODE")
        if "<" in public_text or ">" in public_text:
            reasons.append("OBFUSCATING_MARKUP")
        if (
            _ABSOLUTE_LOCAL_PATH.search(public_text)
            or _WINDOWS_UNC_PATH.search(public_text)
            or _DOUBLE_SLASH_PATH.search(public_text)
            or _WINDOWS_ROOTED_PATH.search(public_text)
            or public_text.startswith(("/", "~"))
        ):
            reasons.append("ABSOLUTE_LOCAL_PATH")
        is_validated_digest_shape = bool(
            _COMMIT.fullmatch(public_text) or _SHA256.fullmatch(public_text)
        )
        contains_bare_secret = any(
            _COMMIT.fullmatch(match.group()) is None
            and _SHA256.fullmatch(match.group()) is None
            for match in _BARE_AWS_SECRET.finditer(public_text)
        )
        if not is_validated_digest_shape and (
            _ACCOUNT_ID.search(account_scan_text)
            or _FORMATTED_ACCOUNT_ID.search(account_scan_text)
            or _LABELED_ACCOUNT_ID.search(account_scan_text)
        ):
            reasons.append("ACCOUNT_ID_MATERIAL")
        if _AWS_ACCESS_ID.search(public_text) or any(
            pattern.search(public_text) for pattern in _SECRET_VALUE_PATTERNS
        ) or (
            not is_validated_digest_shape and contains_bare_secret
        ):
            reasons.append("SECRET_LIKE_VALUE")
        if _PROMPT_TRANSCRIPT.search(public_text):
            reasons.append("RAW_PROMPT_MATERIAL")
        if _RAW_PROMPT_LABEL.search(public_text):
            reasons.append("RAW_PROMPT_MATERIAL")
        if _PROMPT_FOLLOWS.search(public_text):
            reasons.append("RAW_PROMPT_MATERIAL")
        if _PRIVATE_METADATA_VALUE.search(public_text):
            reasons.append("PRIVATE_MACHINE_METADATA")
        if _PRIVATE_NETWORK_VALUE.search(public_text):
            reasons.append("PRIVATE_MACHINE_METADATA")
    return tuple(reasons)


def _asserts_positive_live_mutation(claim_text: object) -> bool:
    if (
        not isinstance(claim_text, str)
        or claim_text in _REVIEWED_NEGATIVE_LIVE_STATEMENTS
    ):
        return False
    return bool(_LIVE_MUTATION_SUBJECT.search(_normalized_public_text(claim_text)))


def _is_frozen_negative_live_claim(claim: dict[str, Any]) -> bool:
    return all(claim.get(field) == expected for field, expected in _FROZEN_NEGATIVE_LIVE_FIELDS.items())


def _expected_snapshot(facts: RuntimeFacts) -> dict[str, Any]:
    return {
        "commit": EVIDENCE_SNAPSHOT_COMMIT,
        "primary_agent_count": facts.primary_agent_count,
        "registered_tool_count": facts.registered_tool_count,
        "canonical_tools": list(facts.canonical_tools),
        "final_tool_cap": facts.final_tool_cap,
        "bedrock_model_id": facts.model_id,
        "bedrock_region": facts.region,
        "strands_version": facts.strands_version,
        "strands_requirement": facts.strands_requirement,
        "phase1_tag": {
            "name": facts.phase1_tag_name,
            "commit": facts.phase1_tag_commit,
        },
        "prior_armor_commits": list(facts.prior_armor_commits),
        "prior_art_blobs": dict(facts.prior_art_blobs),
        "p0": {
            "status": "PASS",
            "gate_count": len(facts.p0_gate_ids),
            "proof_cases": P0_PROOF_CASES,
        },
        "p1": {
            "status": "PASS",
            "gate_count": len(facts.p1_gate_ids),
            "proof_cases": P1_PROOF_CASES,
        },
    }


def _expected_day15_candidate_snapshot(facts: RuntimeFacts) -> dict[str, Any]:
    return {
        "status": DAY15_CANDIDATE_STATUS,
        "start_commit": DAY15_START_COMMIT,
        "m1_commit": DAY15_M1_COMMIT,
        "commit": DAY15_G10_COMMIT,
        "primary_agent_count": facts.primary_agent_count,
        "registered_tool_count": facts.registered_tool_count,
        "canonical_tools": list(facts.canonical_tools),
        "final_tool_cap": facts.final_tool_cap,
        "bedrock_model_id": facts.model_id,
        "bedrock_region": facts.region,
        "strands_version": facts.strands_version,
        "strands_requirement": facts.strands_requirement,
        "day15_gate_ids": list(facts.day15_gate_ids),
    }


def _validate_schema(document: dict[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    if set(document) != _TOP_LEVEL_FIELDS:
        reasons.append("TOP_LEVEL_SCHEMA_DRIFT")
    if document.get("schema_version") != SCHEMA_VERSION:
        reasons.append("SCHEMA_VERSION_DRIFT")
    if not isinstance(document.get("manifest_hash"), str) or _SHA256.fullmatch(
        document["manifest_hash"]
    ) is None:
        reasons.append("MANIFEST_HASH_INVALID")
    snapshot = document.get("evidence_snapshot")
    if not isinstance(snapshot, dict) or set(snapshot) != _SNAPSHOT_FIELDS:
        reasons.append("SNAPSHOT_SCHEMA_DRIFT")
    else:
        phase1 = snapshot.get("phase1_tag")
        p0 = snapshot.get("p0")
        p1 = snapshot.get("p1")
        snapshot_types_valid = (
            isinstance(snapshot.get("commit"), str)
            and type(snapshot.get("primary_agent_count")) is int
            and type(snapshot.get("registered_tool_count")) is int
            and isinstance(snapshot.get("canonical_tools"), list)
            and all(isinstance(tool, str) for tool in snapshot["canonical_tools"])
            and type(snapshot.get("final_tool_cap")) is int
            and isinstance(snapshot.get("bedrock_model_id"), str)
            and isinstance(snapshot.get("bedrock_region"), str)
            and isinstance(snapshot.get("strands_version"), str)
            and isinstance(snapshot.get("strands_requirement"), str)
            and isinstance(phase1, dict)
            and set(phase1) == {"name", "commit"}
            and all(isinstance(value, str) for value in phase1.values())
            and isinstance(snapshot.get("prior_armor_commits"), list)
            and all(
                isinstance(commit, str) for commit in snapshot["prior_armor_commits"]
            )
            and isinstance(snapshot.get("prior_art_blobs"), dict)
            and all(
                isinstance(path, str) and isinstance(digest, str)
                for path, digest in snapshot["prior_art_blobs"].items()
            )
            and all(
                isinstance(gate, dict)
                and set(gate) == {"status", "gate_count", "proof_cases"}
                and isinstance(gate.get("status"), str)
                and type(gate.get("gate_count")) is int
                and type(gate.get("proof_cases")) is int
                for gate in (p0, p1)
            )
        )
        if not snapshot_types_valid:
            reasons.append("SNAPSHOT_TYPE_DRIFT")
    candidate = document.get("day15_candidate_snapshot")
    if not isinstance(candidate, dict) or set(candidate) != _DAY15_CANDIDATE_FIELDS:
        reasons.append("DAY15_CANDIDATE_SCHEMA_DRIFT")
    else:
        candidate_types_valid = (
            isinstance(candidate.get("status"), str)
            and isinstance(candidate.get("start_commit"), str)
            and isinstance(candidate.get("m1_commit"), str)
            and isinstance(candidate.get("commit"), str)
            and type(candidate.get("primary_agent_count")) is int
            and type(candidate.get("registered_tool_count")) is int
            and isinstance(candidate.get("canonical_tools"), list)
            and all(isinstance(tool, str) for tool in candidate["canonical_tools"])
            and type(candidate.get("final_tool_cap")) is int
            and isinstance(candidate.get("bedrock_model_id"), str)
            and isinstance(candidate.get("bedrock_region"), str)
            and isinstance(candidate.get("strands_version"), str)
            and isinstance(candidate.get("strands_requirement"), str)
            and isinstance(candidate.get("day15_gate_ids"), list)
            and all(
                isinstance(gate_id, str)
                for gate_id in candidate["day15_gate_ids"]
            )
        )
        if not candidate_types_valid:
            reasons.append("DAY15_CANDIDATE_TYPE_DRIFT")
    claims = document.get("claims")
    if not isinstance(claims, list) or len(claims) != len(_REQUIRED_CLAIM_IDS):
        reasons.append("CLAIM_COUNT_INVALID")
        claims = []
    receipts = document.get("live_receipts")
    if not isinstance(receipts, list):
        reasons.append("LIVE_RECEIPTS_SCHEMA_DRIFT")
        receipts = []
    for receipt in receipts:
        if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
            reasons.append("LIVE_RECEIPT_SCHEMA_DRIFT")
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) != _CLAIM_FIELDS:
            reasons.append("CLAIM_SCHEMA_DRIFT")
    return tuple(reasons)


def _validate_snapshot(
    snapshot: object,
    facts: RuntimeFacts,
    frozen: FrozenFacts,
) -> tuple[str, ...]:
    if not isinstance(snapshot, dict):
        return ("SNAPSHOT_UNAVAILABLE",)
    reasons: list[str] = []
    if (
        type(facts.primary_agent_count) is not int
        or type(facts.registered_tool_count) is not int
        or type(facts.final_tool_cap) is not int
    ):
        reasons.append("RUNTIME_FACT_TYPE_DRIFT")
    if (
        P0_PROOF_CASES != _FROZEN_P0_PROOF_CASES
        or P1_PROOF_CASES != _FROZEN_P1_PROOF_CASES
    ):
        reasons.append("GATE_PROOF_COUNT_DRIFT")
    expected = _expected_snapshot(facts)
    if snapshot != expected:
        reasons.append("RUNTIME_SNAPSHOT_DRIFT")
    if snapshot.get("canonical_tools") != list(facts.canonical_tools) or snapshot.get(
        "registered_tool_count"
    ) != facts.registered_tool_count:
        reasons.append("CANONICAL_TOOL_SET_DRIFT")
    if facts.primary_agent_count != 1:
        reasons.append("PRIMARY_AGENT_COUNT_DRIFT")
    if (
        facts.final_tool_cap != 5
        or facts.registered_tool_count != 5
        or len(facts.canonical_tools) != 5
        or len(set(facts.canonical_tools)) != 5
        or len(facts.canonical_tools) != facts.registered_tool_count
    ):
        reasons.append("CANONICAL_TOOL_SET_DRIFT")
    if facts.canonical_tools != frozen.canonical_tools:
        reasons.append("FROZEN_TOOL_SET_DRIFT")
    if facts.model_id != EXPECTED_MODEL_ID or facts.region != EXPECTED_BEDROCK_REGION:
        reasons.append("MODEL_PIN_DRIFT")
    if facts.strands_version != EXPECTED_STRANDS_VERSION:
        reasons.append("STRANDS_PIN_DRIFT")
    if facts.strands_requirement != EXPECTED_STRANDS_REQUIREMENT:
        reasons.append("STRANDS_REQUIREMENT_DRIFT")
    if facts.p0_gate_ids != tuple(f"P0-{index:02d}" for index in range(1, 16)):
        reasons.append("P0_GATE_ID_DRIFT")
    if facts.p1_gate_ids != tuple(f"P1-{index:02d}" for index in range(1, 7)):
        reasons.append("P1_GATE_ID_DRIFT")
    if (
        facts.phase1_tag_name != frozen.phase1_tag_name
        or facts.phase1_tag_commit != frozen.phase1_tag_commit
    ):
        reasons.append("FROZEN_PHASE1_TAG_BASELINE_DRIFT")
    if facts.pre_armor_head != frozen.pre_armor_head:
        reasons.append("FROZEN_PRE_ARMOR_BASELINE_DRIFT")
    if facts.prior_armor_commits != frozen.prior_armor_commits:
        reasons.append("FROZEN_ARMOR_HISTORY_BASELINE_DRIFT")
    if facts.prior_art_blobs != frozen.prior_art_blobs:
        reasons.append("FROZEN_PRIOR_ART_BASELINE_DRIFT")
    return tuple(reasons)


def _validate_day15_candidate_snapshot(
    snapshot: object,
    facts: RuntimeFacts,
    root: Path,
) -> tuple[str, ...]:
    if not isinstance(snapshot, dict):
        return ("DAY15_CANDIDATE_UNAVAILABLE",)
    reasons: list[str] = []
    if (
        DAY15_START_COMMIT != _FROZEN_DAY15_START_COMMIT
        or DAY15_ORIGINAL_M1_COMMIT != _FROZEN_DAY15_ORIGINAL_M1_COMMIT
        or DAY15_ORIGINAL_M2_COMMIT != _FROZEN_DAY15_ORIGINAL_M2_COMMIT
        or DAY15_ORIGINAL_M3_COMMIT != _FROZEN_DAY15_ORIGINAL_M3_COMMIT
        or DAY15_M1_COMMIT != _FROZEN_DAY15_M1_COMMIT
        or DAY15_M2_COMMIT != _FROZEN_DAY15_M2_COMMIT
        or DAY15_FINAL_BLOCKER_COMMIT != _FROZEN_DAY15_FINAL_BLOCKER_COMMIT
        or DAY15_SECRET_FIX_COMMIT != _FROZEN_DAY15_SECRET_FIX_COMMIT
        or DAY15_G10_IMPLEMENTATION_COMMIT != _FROZEN_DAY15_G10_IMPLEMENTATION_COMMIT
        or DAY15_G10_EVIDENCE_COMMIT != _FROZEN_DAY15_G10_EVIDENCE_COMMIT
        or DAY15_G10_BLOCKER_COMMIT != _FROZEN_DAY15_G10_BLOCKER_COMMIT
        or DAY15_NOVA_PROBE_FIX_COMMIT != _FROZEN_DAY15_NOVA_PROBE_FIX_COMMIT
        or DAY15_G10_REANCHOR_COMMIT != _FROZEN_DAY15_G10_REANCHOR_COMMIT
        or DAY15_G10_COMMIT != _FROZEN_DAY15_G10_COMMIT
        or LOCAL_FIRST_PHASE1_COMMIT != _FROZEN_LOCAL_FIRST_PHASE1_COMMIT
        or LOCAL_FIRST_PHASE2_COMMIT != _FROZEN_LOCAL_FIRST_PHASE2_COMMIT
        or PHASE3_IAC_COMMIT != _FROZEN_PHASE3_IAC_COMMIT
        or PHASE3_RC_COMMIT != _FROZEN_PHASE3_RC_COMMIT
        or PORTABLE_B3_COMMIT != _FROZEN_PORTABLE_B3_COMMIT
        or PORTABLE_B4_COMMIT != _FROZEN_PORTABLE_B4_COMMIT
        or PORTABLE_B5_CONTAINER_COMMIT != _FROZEN_PORTABLE_B5_CONTAINER_COMMIT
        or DAY15_RECOVERY_LINEAGE != _FROZEN_DAY15_RECOVERY_LINEAGE
        or DAY15_CANDIDATE_STATUS != _FROZEN_DAY15_CANDIDATE_STATUS
    ):
        reasons.append("DAY15_ANCHOR_CONSTANT_DRIFT")
    if snapshot != _expected_day15_candidate_snapshot(facts):
        reasons.append("DAY15_CANDIDATE_SNAPSHOT_DRIFT")
    try:
        frozen_gate_ids = collect_frozen_day15_gate_ids(root)
    except (OSError, ValueError, SyntaxError):
        reasons.append("DAY15_FROZEN_GATE_SOURCE_INVALID")
    else:
        if frozen_gate_ids != _FROZEN_DAY15_GATE_IDS:
            reasons.append("DAY15_FROZEN_GATE_ID_DRIFT")
        if facts.day15_gate_ids != frozen_gate_ids:
            reasons.append("DAY15_GATE_ID_DRIFT")
    if facts.day15_gate_ids != _FROZEN_DAY15_GATE_IDS:
        reasons.append("DAY15_GATE_ID_DRIFT")
    return tuple(reasons)


def _expected_claim_anchor(claim_id: str) -> str | None:
    if claim_id in _LOCAL_FIRST_PHASE2_CLAIM_IDS:
        return _FROZEN_LOCAL_FIRST_PHASE2_COMMIT
    if claim_id in _LOCAL_FIRST_PHASE1_CLAIM_IDS:
        return _FROZEN_LOCAL_FIRST_PHASE1_COMMIT
    if claim_id in _FROZEN_L1_CLAIM_IDS:
        return _FROZEN_L1_COMMIT
    if claim_id in _DAY15_ORIGINAL_M1_CLAIM_IDS:
        return _FROZEN_DAY15_ORIGINAL_M1_COMMIT
    if claim_id in _DAY15_RECOVERED_M1_CLAIM_IDS:
        return _FROZEN_DAY15_M1_COMMIT
    if claim_id in _PHASE3_IAC_CLAIM_IDS:
        return _FROZEN_PHASE3_IAC_COMMIT
    if claim_id in _PHASE3_RC_CLAIM_IDS:
        return _FROZEN_PHASE3_RC_COMMIT
    if claim_id in _PORTABLE_B1_CLAIM_IDS:
        return _FROZEN_PORTABLE_B1_COMMIT
    if claim_id in _PORTABLE_B3_CLAIM_IDS:
        return _FROZEN_PORTABLE_B3_COMMIT
    if claim_id in _PORTABLE_B4_CLAIM_IDS:
        return _FROZEN_PORTABLE_B4_COMMIT
    if claim_id in _PORTABLE_B5_CONTAINER_CLAIM_IDS:
        return _FROZEN_PORTABLE_B5_CONTAINER_COMMIT
    return None


def _validate_claims(
    document: dict[str, Any],
    root: Path,
    facts: RuntimeFacts,
) -> tuple[str, ...]:
    raw_claims = document.get("claims")
    if not isinstance(raw_claims, list):
        return ("CLAIMS_UNAVAILABLE",)
    claims = [claim for claim in raw_claims if isinstance(claim, dict)]
    reasons: list[str] = []
    ids = [claim.get("claim_id") for claim in claims]
    if ids != sorted(ids, key=lambda value: value if isinstance(value, str) else ""):
        reasons.append("CLAIM_ORDER_DRIFT")
    if len(ids) != len(set(map(str, ids))):
        reasons.append("DUPLICATE_CLAIM_ID")
    observed_ids = {claim_id for claim_id in ids if isinstance(claim_id, str)}
    if observed_ids != _REQUIRED_CLAIM_IDS or len(ids) != len(_REQUIRED_CLAIM_IDS):
        reasons.append("REQUIRED_CLAIM_SET_DRIFT")
    anchor_groups = (
        _FROZEN_L1_CLAIM_IDS,
        _DAY15_ORIGINAL_M1_CLAIM_IDS,
        _DAY15_RECOVERED_M1_CLAIM_IDS,
        _PHASE3_IAC_CLAIM_IDS,
        _PHASE3_RC_CLAIM_IDS,
        _PORTABLE_B1_CLAIM_IDS,
        _PORTABLE_B3_CLAIM_IDS,
        _PORTABLE_B4_CLAIM_IDS,
        _PORTABLE_B5_CONTAINER_CLAIM_IDS,
        _LOCAL_FIRST_PHASE1_CLAIM_IDS,
        _LOCAL_FIRST_PHASE2_CLAIM_IDS,
    )
    anchored_ids = set().union(*anchor_groups)
    if (
        anchored_ids != _REQUIRED_CLAIM_IDS
        or any(
            left & right
            for index, left in enumerate(anchor_groups)
            for right in anchor_groups[index + 1 :]
        )
    ):
        reasons.append("CLAIM_ANCHOR_BASELINE_INVALID")
    gate_ids = set(facts.p0_gate_ids + facts.p1_gate_ids + facts.day15_gate_ids)
    cache: dict[tuple[str, str], str | None] = {}

    for claim in claims:
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or _CLAIM_ID.fullmatch(claim_id) is None:
            reasons.append("CLAIM_ID_INVALID")
        if not isinstance(claim.get("claim"), str) or not claim["claim"].strip():
            reasons.append("CLAIM_TEXT_INVALID")
        if claim.get("evidence_kind") not in _EVIDENCE_KINDS:
            reasons.append("EVIDENCE_KIND_INVALID")
        if claim.get("status") not in _STATUSES:
            reasons.append("CLAIM_STATUS_INVALID")
        if claim.get("scope") not in _SCOPES:
            reasons.append("CLAIM_SCOPE_INVALID")
        if not isinstance(claim.get("limitations"), str) or not claim["limitations"].strip():
            reasons.append("CLAIM_LIMITATIONS_INVALID")
        commit = claim.get("commit_anchor")
        if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
            reasons.append("COMMIT_ANCHOR_INVALID")
            commit = EVIDENCE_SNAPSHOT_COMMIT
        expected_anchor = (
            _expected_claim_anchor(claim_id) if isinstance(claim_id, str) else None
        )
        if expected_anchor is None or commit != expected_anchor:
            reasons.append("CLAIM_COMMIT_ANCHOR_DRIFT")
        expected_hash = claim_hash(claim)
        if claim.get("hash") != expected_hash or _SHA256.fullmatch(str(claim.get("hash"))) is None:
            reasons.append("CLAIM_HASH_MISMATCH")

        sources = claim.get("authority_source")
        if not isinstance(sources, list) or not sources or not all(
            isinstance(source, str) for source in sources
        ):
            reasons.append("AUTHORITY_SOURCE_INVALID")
            sources = []
        elif sources != sorted(set(sources)):
            reasons.append("AUTHORITY_SOURCE_ORDER_DRIFT")
        for source in sources:
            reasons.extend(_validate_authority_source(root, commit, source, cache))

        nodes = claim.get("proof_nodes")
        if not isinstance(nodes, list) or not all(isinstance(node, str) for node in nodes):
            reasons.append("PROOF_NODES_INVALID")
            nodes = []
        elif nodes != sorted(set(nodes)):
            reasons.append("PROOF_NODE_ORDER_DRIFT")
        if (
            claim.get("status") == "PROVEN"
            and claim.get("evidence_kind") != "LIVE_RECEIPT"
            and not nodes
        ):
            reasons.append("PROVEN_CLAIM_WITHOUT_PROOF")
        for node in nodes:
            if node.startswith(("P0-", "P1-", "D15-G")):
                if node not in gate_ids:
                    reasons.append("GATE_ID_MISSING")
            else:
                reasons.extend(_validate_test_node(root, commit, node, cache))

        if claim.get("evidence_kind") == "OPERATOR_ATTESTATION" and claim.get(
            "status"
        ) != "ATTESTED_ONLY":
            reasons.append("OPERATOR_ATTESTATION_STATUS_INVALID")
        if claim.get("status") == "ATTESTED_ONLY" and claim.get(
            "evidence_kind"
        ) != "OPERATOR_ATTESTATION":
            reasons.append("ATTESTED_STATUS_KIND_INVALID")
        frozen_gate_claim = _FROZEN_GATE_CLAIMS.get(str(claim_id))
        if frozen_gate_claim is not None and (
            claim.get("claim") != frozen_gate_claim[0]
            or claim.get("proof_nodes") != list(frozen_gate_claim[1])
        ):
            reasons.append("GATE_CLAIM_DRIFT")
        if (
            claim.get("scope") == "live AWS"
            and claim.get("status") == "PROVEN"
            and claim.get("evidence_kind") != "LIVE_RECEIPT"
        ):
            reasons.append("LIVE_PROOF_KIND_INVALID")
        live_boundary_changed = claim_id == "LIVE-EC2-01" and not (
            _is_frozen_negative_live_claim(claim)
        )
        if live_boundary_changed and (
            claim.get("scope") != "live AWS"
            or claim.get("evidence_kind") != "LIVE_RECEIPT"
            or claim.get("status") != "PROVEN"
        ):
            reasons.append("LIVE_EVENT_CLAIM_MISCLASSIFIED")
        positive_live_statement = any(
            _asserts_positive_live_mutation(claim.get(field))
            for field in ("claim", "limitations")
        )
        if positive_live_statement and (
            claim.get("scope") != "live AWS"
            or claim.get("evidence_kind") != "LIVE_RECEIPT"
            or claim.get("status") != "PROVEN"
        ):
            reasons.append("LIVE_EVENT_CLAIM_MISCLASSIFIED")

    return tuple(reasons)


def _validate_receipts(document: dict[str, Any], root: Path) -> tuple[str, ...]:
    claims = document.get("claims")
    receipts = document.get("live_receipts")
    if not isinstance(claims, list) or not isinstance(receipts, list):
        return ("LIVE_RECEIPTS_UNAVAILABLE",)
    reasons: list[str] = []
    receipt_order = [
        (
            str(receipt.get("claim_id", "")),
            str(receipt.get("path", "")),
            str(receipt.get("sha256", "")),
        )
        for receipt in receipts
        if isinstance(receipt, dict)
    ]
    if receipt_order != sorted(receipt_order) or len(receipt_order) != len(receipts):
        reasons.append("LIVE_RECEIPT_ORDER_DRIFT")
    receipt_by_claim: dict[str, dict[str, Any]] = {}
    claims_by_id = {
        claim.get("claim_id"): claim
        for claim in claims
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        claim_id = receipt.get("claim_id")
        relative_path = _safe_relative_path(receipt.get("path"))
        digest = receipt.get("sha256")
        if (
            not isinstance(claim_id, str)
            or relative_path is None
            or not relative_path.startswith("docs/evidence/live-receipts/")
            or not relative_path.endswith(".json")
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            reasons.append("LIVE_RECEIPT_INVALID")
            continue
        if claim_id in receipt_by_claim:
            reasons.append("LIVE_RECEIPT_DUPLICATE")
            continue
        index_blob = _regular_index_blob(root, relative_path)
        worktree_blob = _worktree_git_blob(root, relative_path)
        path = _regular_worktree_path(root, relative_path)
        head_blob = _git(root, "rev-parse", f"HEAD:{relative_path}")
        if (
            index_blob is None
            or worktree_blob != index_blob
            or path is None
            or head_blob.returncode != 0
            or head_blob.stdout.strip() != index_blob
        ):
            reasons.append("LIVE_RECEIPT_NOT_TRACKED")
            continue
        try:
            payload = path.read_bytes()
            receipt_document = json.loads(
                payload.decode("utf-8"), object_pairs_hook=_unique_object
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            DuplicateJsonKey,
        ):
            reasons.append("LIVE_RECEIPT_UNREADABLE")
            continue
        receipt_reasons: list[str] = []
        if hashlib.sha256(payload).hexdigest() != digest:
            receipt_reasons.append("LIVE_RECEIPT_HASH_MISMATCH")
        if not isinstance(receipt_document, dict) or set(receipt_document) != (
            _RECEIPT_DOCUMENT_FIELDS
        ):
            receipt_reasons.append("LIVE_RECEIPT_DOCUMENT_SCHEMA_DRIFT")
        else:
            expected_bytes = (
                json.dumps(
                    receipt_document,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
            if payload != expected_bytes:
                receipt_reasons.append("LIVE_RECEIPT_NOT_CANONICAL")
            if (
                receipt_document.get("schema_version") != "1.0"
                or receipt_document.get("claim_id") != claim_id
                or receipt_document.get("operation") != "ec2:StopInstances"
                or receipt_document.get("region") != EXPECTED_BEDROCK_REGION
                or receipt_document.get("observed_state") != "stopped"
                or receipt_document.get("result") != "SUCCESS_WITH_EVIDENCE"
                or receipt_document.get("provenance")
                != "OPERATOR_ATTESTED_SANITIZED_EXPORT"
                or receipt_document.get("sanitized") is not True
            ):
                receipt_reasons.append("LIVE_RECEIPT_CONTRACT_INVALID")
            digests = [
                receipt_document.get("target_fingerprint"),
                receipt_document.get("request_reference_hash"),
                receipt_document.get("verification_evidence_hash"),
            ]
            if (
                not all(isinstance(value, str) and _SHA256.fullmatch(value) for value in digests)
                or len(set(digests)) != 3
                or any(value == "0" * 64 for value in digests)
            ):
                receipt_reasons.append("LIVE_RECEIPT_EVIDENCE_BINDING_INVALID")
            occurred_at = receipt_document.get("occurred_at")
            timestamp_valid = isinstance(occurred_at, str) and bool(
                _RECEIPT_TIMESTAMP.fullmatch(occurred_at)
            )
            event_time: datetime | None = None
            if timestamp_valid:
                try:
                    event_time = datetime.fromisoformat(occurred_at)
                    timestamp_valid = event_time.tzinfo is UTC
                except ValueError:
                    timestamp_valid = False
            if not timestamp_valid:
                receipt_reasons.append("LIVE_RECEIPT_TIMESTAMP_INVALID")
            else:
                lower_result = _git(
                    root,
                    "show",
                    "-s",
                    "--format=%cI",
                    EVIDENCE_SNAPSHOT_COMMIT,
                )
                upper_result = _git(
                    root,
                    "log",
                    "-1",
                    "--format=%cI",
                    "HEAD",
                    "--",
                    relative_path,
                )
                try:
                    lower_bound = datetime.fromisoformat(lower_result.stdout.strip())
                    upper_bound = datetime.fromisoformat(upper_result.stdout.strip())
                except ValueError:
                    receipt_reasons.append("LIVE_RECEIPT_TIME_ANCHOR_INVALID")
                else:
                    if (
                        lower_result.returncode != 0
                        or upper_result.returncode != 0
                        or event_time is None
                        or not lower_bound <= event_time <= upper_bound
                    ):
                        receipt_reasons.append("LIVE_RECEIPT_TIME_ANCHOR_INVALID")
            attestation = receipt_document.get("operator_attestation")
            if attestation != _LIVE_RECEIPT_ATTESTATION:
                receipt_reasons.append("LIVE_RECEIPT_ATTESTATION_INVALID")
        if _scan_private_material(receipt_document):
            receipt_reasons.append("LIVE_RECEIPT_PRIVATE_MATERIAL")
        bound_claim = claims_by_id.get(claim_id)
        if (
            not isinstance(bound_claim, dict)
            or bound_claim.get("status") != "PROVEN"
            or bound_claim.get("scope") != "live AWS"
            or bound_claim.get("evidence_kind") != "LIVE_RECEIPT"
            or not _asserts_positive_live_mutation(bound_claim.get("claim"))
        ):
            receipt_reasons.append("LIVE_RECEIPT_CLAIM_BINDING_INVALID")
        reasons.extend(receipt_reasons)
        if not receipt_reasons:
            receipt_by_claim[claim_id] = receipt

    for claim in claims:
        if not isinstance(claim, dict):
            continue
        live_boundary_changed = claim.get("claim_id") == "LIVE-EC2-01" and not (
            _is_frozen_negative_live_claim(claim)
        )
        proven_live = live_boundary_changed or (
            claim.get("status") == "PROVEN"
            and (
                claim.get("scope") == "live AWS"
                or claim.get("evidence_kind") == "LIVE_RECEIPT"
                or _asserts_positive_live_mutation(claim.get("claim"))
            )
        )
        if proven_live and claim.get("claim_id") not in receipt_by_claim:
            reasons.append("LIVE_CLAIM_WITHOUT_SANITIZED_RECEIPT")
        if claim.get("status") != "PROVEN" and claim.get("claim_id") in receipt_by_claim:
            reasons.append("UNREVIEWED_LIVE_RECEIPT")
    return tuple(reasons)


def _validate_git_anchors(
    document: dict[str, Any],
    root: Path,
    facts: RuntimeFacts,
) -> tuple[str, ...]:
    reasons: list[str] = []
    replacement_refs = _git(root, "for-each-ref", "--format=%(refname)", "refs/replace")
    graft_path = _git(root, "rev-parse", "--git-path", "info/grafts")
    graft_candidate = Path(graft_path.stdout.strip())
    if not graft_candidate.is_absolute():
        graft_candidate = root / graft_candidate
    if replacement_refs.returncode != 0 or replacement_refs.stdout.strip():
        reasons.append("LOCAL_GIT_REPLACEMENT_PRESENT")
    if graft_path.returncode != 0 or (
        graft_path.stdout.strip() and os.path.lexists(graft_candidate)
    ):
        reasons.append("LOCAL_GIT_GRAFT_PRESENT")
    snapshot = _git(root, "cat-file", "-e", f"{EVIDENCE_SNAPSHOT_COMMIT}^{{commit}}")
    if snapshot.returncode != 0:
        reasons.append("EVIDENCE_SNAPSHOT_MISSING")
    ancestor = _git(root, "merge-base", "--is-ancestor", EVIDENCE_SNAPSHOT_COMMIT, "HEAD")
    if ancestor.returncode != 0:
        reasons.append("EVIDENCE_SNAPSHOT_NOT_ANCESTOR")
    for commit in _FROZEN_DAY15_RECOVERY_LINEAGE:
        exists = _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
        if exists.returncode != 0:
            reasons.append("DAY15_COMMIT_MISSING")
    baseline_to_start = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_L1_COMMIT,
        _FROZEN_DAY15_START_COMMIT,
    )
    local_phase2_to_head = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_LOCAL_FIRST_PHASE2_COMMIT,
        "HEAD",
    )
    local_phase1_to_phase2 = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_LOCAL_FIRST_PHASE1_COMMIT,
        _FROZEN_LOCAL_FIRST_PHASE2_COMMIT,
    )
    g10_to_local_phase1 = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_DAY15_G10_COMMIT,
        _FROZEN_LOCAL_FIRST_PHASE1_COMMIT,
    )
    local_phase2_to_phase3_iac = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_LOCAL_FIRST_PHASE2_COMMIT,
        _FROZEN_PHASE3_IAC_COMMIT,
    )
    phase3_iac_to_rc = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_PHASE3_IAC_COMMIT,
        _FROZEN_PHASE3_RC_COMMIT,
    )
    phase3_rc_to_portable_b1 = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_PHASE3_RC_COMMIT,
        _FROZEN_PORTABLE_B1_COMMIT,
    )
    portable_b1_to_portable_b3 = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_PORTABLE_B1_COMMIT,
        _FROZEN_PORTABLE_B3_COMMIT,
    )
    portable_b3_to_portable_b4 = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_PORTABLE_B3_COMMIT,
        _FROZEN_PORTABLE_B4_COMMIT,
    )
    portable_b4_to_portable_b5_container = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_PORTABLE_B4_COMMIT,
        _FROZEN_PORTABLE_B5_CONTAINER_COMMIT,
    )
    portable_b5_container_to_head = _git(
        root,
        "merge-base",
        "--is-ancestor",
        _FROZEN_PORTABLE_B5_CONTAINER_COMMIT,
        "HEAD",
    )
    parent_results = tuple(
        (
            _git(root, "rev-list", "--parents", "-n", "1", child),
            [child, parent],
        )
        for parent, child in pairwise(_FROZEN_DAY15_RECOVERY_LINEAGE)
    )
    if (
        baseline_to_start.returncode != 0
        or local_phase2_to_head.returncode != 0
        or local_phase1_to_phase2.returncode != 0
        or g10_to_local_phase1.returncode != 0
        or local_phase2_to_phase3_iac.returncode != 0
        or phase3_iac_to_rc.returncode != 0
        or phase3_rc_to_portable_b1.returncode != 0
        or portable_b1_to_portable_b3.returncode != 0
        or portable_b3_to_portable_b4.returncode != 0
        or portable_b4_to_portable_b5_container.returncode != 0
        or portable_b5_container_to_head.returncode != 0
        or any(
            result.returncode != 0 or result.stdout.split() != expected
            for result, expected in parent_results
        )
    ):
        reasons.append("DAY15_ANCHOR_CHAIN_DRIFT")
    tag = _git(root, "rev-parse", f"refs/tags/{facts.phase1_tag_name}^{{}}")
    if tag.returncode != 0 or tag.stdout.strip() != facts.phase1_tag_commit:
        reasons.append("PHASE1_TAG_DRIFT")
    for commit in facts.prior_armor_commits:
        exists = _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
        history = _git(root, "merge-base", "--is-ancestor", commit, EVIDENCE_SNAPSHOT_COMMIT)
        if exists.returncode != 0 or history.returncode != 0:
            reasons.append("PRIOR_ARMOR_COMMIT_DRIFT")
    pre_armor = _git(
        root,
        "merge-base",
        "--is-ancestor",
        facts.pre_armor_head,
        EVIDENCE_SNAPSHOT_COMMIT,
    )
    current_history = _git(root, "merge-base", "--is-ancestor", facts.pre_armor_head, "HEAD")
    if pre_armor.returncode != 0 or current_history.returncode != 0:
        reasons.append("PRE_ARMOR_HISTORY_DRIFT")
    for relative_path, expected_blob in facts.prior_art_blobs:
        tracked = _git(root, "ls-files", "--error-unmatch", "--", relative_path)
        index_blob = _regular_index_blob(root, relative_path)
        worktree_blob = _worktree_git_blob(root, relative_path)
        path = _regular_worktree_path(root, relative_path)
        frozen = _git(root, "rev-parse", f"{EVIDENCE_SNAPSHOT_COMMIT}:{relative_path}")
        if (
            tracked.returncode != 0
            or index_blob != expected_blob
            or worktree_blob != expected_blob
            or path is None
            or frozen.returncode != 0
            or frozen.stdout.strip() != expected_blob
        ):
            reasons.append("PRIOR_ART_BLOB_DRIFT")
    claims = document.get("claims")
    if isinstance(claims, list):
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            commit = claim.get("commit_anchor")
            if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
                continue
            exists = _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
            history = _git(
                root,
                "merge-base",
                "--is-ancestor",
                commit,
                "HEAD",
            )
            if (
                commit
                not in {
                    _FROZEN_L1_COMMIT,
                    _FROZEN_DAY15_ORIGINAL_M1_COMMIT,
                    _FROZEN_DAY15_M1_COMMIT,
                    _FROZEN_DAY15_M2_COMMIT,
                    _FROZEN_DAY15_G10_COMMIT,
                    _FROZEN_LOCAL_FIRST_PHASE1_COMMIT,
                    _FROZEN_LOCAL_FIRST_PHASE2_COMMIT,
                    _FROZEN_PHASE3_IAC_COMMIT,
                    _FROZEN_PHASE3_RC_COMMIT,
                    _FROZEN_PORTABLE_B1_COMMIT,
                    _FROZEN_PORTABLE_B3_COMMIT,
                    _FROZEN_PORTABLE_B4_COMMIT,
                    _FROZEN_PORTABLE_B5_CONTAINER_COMMIT,
                }
                or exists.returncode != 0
                or history.returncode != 0
            ):
                reasons.append("CLAIM_COMMIT_ANCHOR_DRIFT")
    return tuple(reasons)


def validate_manifest(
    document: dict[str, Any],
    *,
    root: Path = ROOT,
    facts: RuntimeFacts | None = None,
) -> tuple[str, ...]:
    """Return stable reason codes; an empty tuple is a complete validation pass."""

    try:
        current_facts = collect_runtime_facts(root) if facts is None else facts
        frozen_facts = collect_frozen_facts(root)
        reasons = list(_validate_schema(document))
        if document.get("manifest_hash") != manifest_hash(document):
            reasons.append("MANIFEST_HASH_MISMATCH")
        reasons.extend(_scan_private_material(document))
        reasons.extend(
            _validate_snapshot(
                document.get("evidence_snapshot"),
                current_facts,
                frozen_facts,
            )
        )
        reasons.extend(
            _validate_day15_candidate_snapshot(
                document.get("day15_candidate_snapshot"),
                current_facts,
                root,
            )
        )
        reasons.extend(_validate_claims(document, root, current_facts))
        reasons.extend(_validate_receipts(document, root))
        reasons.extend(_validate_git_anchors(document, root, current_facts))
        return tuple(sorted(set(reasons)))
    except (OSError, ValueError, TypeError, SyntaxError):
        return ("MANIFEST_VALIDATION_ERROR",)


def validate_generated_files(root: Path = ROOT) -> tuple[str, ...]:
    reasons: list[str] = []
    relative_json = JSON_PATH.relative_to(ROOT).as_posix()
    relative_markdown = MARKDOWN_PATH.relative_to(ROOT).as_posix()
    relative_readme = README_PATH.relative_to(ROOT).as_posix()
    public_paths = (relative_json, relative_markdown, relative_readme)
    for relative_path in public_paths:
        if _regular_worktree_path(root, relative_path) is None:
            reasons.append("PUBLIC_EVIDENCE_PATH_UNSAFE")
            continue
        index_blob = _regular_index_blob(root, relative_path)
        if index_blob is None:
            reasons.append("PUBLIC_EVIDENCE_NOT_TRACKED")
        elif _worktree_git_blob(root, relative_path) != index_blob:
            reasons.append("PUBLIC_EVIDENCE_INDEX_DRIFT")
    if reasons:
        return tuple(sorted(set(reasons)))
    try:
        document = load_manifest(root / relative_json)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKey, ValueError):
        return ("MANIFEST_JSON_UNREADABLE",)
    reasons.extend(validate_manifest(document, root=root))
    canonical = canonical_manifest_bytes(document)
    try:
        raw_json = (root / relative_json).read_bytes()
        raw_markdown = (root / relative_markdown).read_text(encoding="utf-8")
        raw_readme = (root / relative_readme).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return tuple(sorted(set((*reasons, "GENERATED_VIEW_UNREADABLE"))))
    if raw_json != canonical:
        reasons.append("MANIFEST_JSON_NOT_CANONICAL")
    if raw_markdown != render_markdown(document):
        reasons.append("MANIFEST_MARKDOWN_DRIFT")
    if raw_readme != render_evidence_readme():
        reasons.append("EVIDENCE_README_DRIFT")
    if _scan_private_material(raw_readme):
        reasons.append("EVIDENCE_README_PRIVATE_MATERIAL")
    try:
        expected = build_manifest(root)
    except (OSError, ValueError, TypeError):
        reasons.append("MANIFEST_GENERATOR_FAILED")
    else:
        if canonical != canonical_manifest_bytes(expected):
            reasons.append("MANIFEST_GENERATOR_DRIFT")
    return tuple(sorted(set(reasons)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit stable machine output")
    args = parser.parse_args()
    reasons = validate_generated_files()
    claim_count = 0
    receipt_count = 0
    if not reasons:
        try:
            document = load_manifest()
            claims = document.get("claims")
            receipts = document.get("live_receipts")
            claim_count = len(claims) if isinstance(claims, list) else 0
            receipt_count = len(receipts) if isinstance(receipts, list) else 0
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            reasons = ("MANIFEST_JSON_UNREADABLE",)
    payload = {
        "status": "PASS" if not reasons else "FAIL",
        "claim_count": claim_count if not reasons else 0,
        "reasons": list(reasons),
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    elif reasons:
        print(f"EVIDENCE_VALIDATE FAIL reasons={','.join(reasons)}")
    else:
        print(
            f"EVIDENCE_VALIDATE PASS claims={claim_count} "
            f"live_receipts={receipt_count}"
        )
    return 0 if not reasons else 1


if __name__ == "__main__":
    raise SystemExit(main())
