# AIOA PORTABLE FOUNDATION — B0+B1+B2

## Identity

PROJECT=AIOA / AIOA-NonZero-CloudOps-Agent
REPO=/media/l/LSC_DATA/AWS_HACKATHON/AIOA-NonZero-CloudOps-Agent
BRANCH=codex/portable-foundation-b0-b2
HEAD_BEFORE=6a83e1a09a26b6572edea52e728e3d51857035e3
HEAD_AFTER=aad53ecf4a26f8aba01d869ff993b0757b8f203f
WORKTREE=CLEAN
RUN_DATE=2026-09-01
AUDITED_AT=2026-09-01T05:26:30+02:00
REMOTE=origin https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent.git (unchanged)

`HEAD_AFTER` is the exact implementation head used for the final full regression, P0, P1,
clean-clone proof, package check, and portable demo. A documentation-only commit containing this
report follows that audited head; this avoids a self-referential report commit hash.

## Mission

AWS_REMOVED_FROM_CRITICAL_PATH=YES
STRANDS_RETAINED_AS_AGENT_FRAMEWORK=YES
EXTERNAL_DEPLOYMENT_PERFORMED=NO
AWS_MUTATIONS=0
REMOTE_PUSHES=0
EXTERNAL_UPLOADS=0

The canonical application default is `portable/mock`. Import, startup, the actual five-tool Strands
Agent, HITL, evidence, approval/denial, execution against bounded local state, verification, replay,
recovery, tests, API contracts, and the judge demonstration require no AWS credential, client,
network service, paid API, or local LLM. Preserved Bedrock/AWS code is selected only through an
explicit fail-closed optional boundary.

## Preflight

DATE_TIME=2026-09-01 Europe/Berlin
INITIAL_BRANCH=main
INITIAL_WORKTREE=CLEAN
WORK_BRANCH=codex/portable-foundation-b0-b2
PYTHON=3.12.3
PIP=26.2.1
NODE=18.19.1 (host tool; no frontend package manifest in B0-B2)
NPM=9.2.0 (host tool; no frontend package manifest in B0-B2)
PROJECT_METADATA=0.2.0rc1
STRANDS_AGENTS=1.53.0
PYTEST=8.4.2
RUFF=0.16.4
PYDANTIC=2.13.4
BOTO3=1.43.78 (transitive Strands dependency; not selected in portable mode)
BOTOCORE=1.43.78 (transitive Strands dependency; not selected in portable mode)

## B0

B0_STATUS=PASS
BASELINE_TESTS=1291 passed / 1291 total / 0 failed / 0 skipped / 0 xfailed / 1109.38s
AWS_CORE_DEPENDENCIES_BEFORE=1 (implicit Bedrock default in canonical agent construction)
AWS_CORE_DEPENDENCIES_AFTER=0 (operational integrations required by portable core)
PORTABLE_IMPORT_PASS=YES
PORTABLE_STARTUP_PASS=YES
B0_COMMIT=abd602cc91b6043ee78aa355e986618f7e1968c8

B0 introduced one typed runtime contract with the safe `portable/mock` default, explicit AWS opt-in,
and fail-closed mode/provider combinations. AWS credentials, profiles, region variables, and metadata
were removed for import/startup proofs. Socket guards prove the portable startup path does not open a
network connection. The full baseline was executed rather than replaced by a smoke test.

AWS dependency classifications are recorded in
`docs/architecture/portable-aws-dependency-inventory.md`: `REQUIRED_CORE`,
`OPTIONAL_INTEGRATION`, `TEST_ONLY`, `DEMO_ONLY`, `LEGACY`, and `UNUSED`.

## B1

B1_STATUS=PASS
STRANDS_RUNTIME_PASS=YES
PROVIDER_FACTORY_PASS=YES
DETERMINISTIC_PROVIDER_PASS=YES
NON_AWS_PROVIDER_PATH=DETERMINISTIC_STRANDS_MOCK_SHIPPED; STRANDS_MODEL_EXTENSION_BOUNDARY_READY
SECRET_HANDLING_PASS=YES
PROVIDER_FAILURE_SEMANTICS_PASS=YES
B1_COMMIT=a2e16d0f1d625b34916440d6740a486f73cf2bb1

`providers/factory.py::create_model_provider` is the only provider factory. It resolves a native
Strands `Model` plus public-safe metadata and never performs fallback. Bedrock and AWS client imports
are lazy inside the explicitly selected Bedrock constructor. The canonical `create_primary_agent`
default now creates one real `strands.Agent` using the deterministic provider and the unchanged five
tools.

The deterministic provider contract covers success, approval-required proposal, malformed output,
empty output, timeout, generic provider failure, retryable failure, non-retryable failure,
policy-invalid authority, and denied action. Failures become typed Non-Zero results; none can become
approval, mutation, `None`, or ambiguous success. Provider initialization catches third-party
exceptions only at the factory boundary and converts them to a fixed, redacted
`ModelProviderUnavailableError`.

No paid real non-AWS adapter was added merely for checklist breadth. The provider-neutral Strands
`Model` boundary is ready for a later supported adapter without changing agent topology or authority.

## B2

B2_STATUS=PASS
LOCAL_SANDBOX_PASS=YES
APPROVE_SCENARIO_PASS=YES
DENY_SCENARIO_PASS=YES
RECOVERY_SCENARIO_PASS=YES
EVIDENCE_PASS=YES
ZERO_AWS_CALL_PROOF=SOCKET_GUARD_PLUS_TYPED_COUNTERS_PLUS_CREDENTIAL_FREE_PROCESS
ONE_COMMAND_DEMO=.venv/bin/python scripts/run_portable_demo.py
B2_COMMIT=b1101e090e22ea98b7b6e961b1b959c09ac15b3d

The canonical command invokes the real Strands Agent first, proving the exact agent ID and five-tool
surface with an inert proposal. It then reuses the existing strict Phase 3 / Local-2 verification
receipt rather than duplicating approval or evidence schemas.

The approved synthetic elastic-IP path records zero mutations before explicit human decision,
exactly one bounded sandbox mutation after approval, independent read-back, and
`SUCCESS_WITH_EVIDENCE`. The separate security-group denial path records `DENIED_BY_HUMAN`, no
receipt, no verification claim, and zero mutation. Binding mismatch, missing approval, invalid model
access, invalid identity, and invalid verification evidence fail closed. Conflicting replay adds zero
mutations; a fresh runtime reconciles the committed receipt with zero re-execution.

FINAL_DEMO_STATUS=PASS
FINAL_DEMO_DURATION=4.27s
FINAL_DEMO_RECEIPT_SHA256=3440d2e0aab5427a456d9f2074d5557305017f1864559bb01cc322b48eb53bbd
FINAL_DEMO_EVIDENCE=/media/l/LSC_DATA/AWS_HACKATHON/AIOA-NonZero-CloudOps-Agent/.local/portable/portable-demo-receipt.json
FINAL_DEMO_EVIDENCE_MODE=0600
FINAL_DEMO_STRANDS_CALLS=4
FINAL_DEMO_AWS_CALLS=0
FINAL_DEMO_AWS_MUTATIONS=0
FINAL_DEMO_EXTERNAL_NETWORK_CONNECTIONS=0

## Final Regression

TEST_TOTAL=1318
TEST_PASSED=1318
TEST_FAILED=0
TEST_SKIPPED=0
TEST_XFAILED=0
TEST_DURATION=963.58s pytest / 967.40s wall
BASELINE_COMPARISON=+27 passing tests; no baseline test removed or skipped
P0=PASS 15/15 gates, 136 proof tests, 0 skipped, 116.85s
P1=PASS 6/6 gates, 93 proof tests, 0 skipped, 171.88s
CLEAN_CLONE=PASS exact aad53ecf4a26f8aba01d869ff993b0757b8f203f, 6/6 smoke checks
LINT=PASS (`ruff check .`)
TYPECHECK=NOT_CONFIGURED (no mypy/pyright dependency or project configuration)
FORMAT_CHECK=NO_REPOSITORY_FORMATTER_CONFIG; `git diff --check` and Ruff lint PASS
PACKAGE_CHECK=PASS (`aioa_nonzero_cloudops_agent-0.2.0rc1-py3-none-any.whl`)
PIP_CHECK=PASS (no broken requirements)
GIT_DIFF_CHECK=PASS
SECRET_SCAN=PASS (346 files, 0 findings, no secret values emitted)
GENERATED_EVIDENCE_CHECK=PASS (28 claims, 0 live receipts)
PORTABLE_E2E=PASS

The first post-change full run exposed two documentation/evidence drift failures. They were fixed by
preserving the truthful historical `DEPLOYMENT_READY_LOCAL_RC` label and re-anchoring only the three
claims whose authority source changed in portable B1. A later P1 run exposed that the old local
clean-clone proof forced `main`; it was corrected to clone full local history and detach the exact
clean feature-branch commit while retaining public `main` binding. No failure was converted to a
skip. The final full run above is from the corrected exact implementation head.

## Architecture Audit

DUPLICATE_PROVIDER_ABSTRACTIONS=NONE
TOP_LEVEL_AWS_IMPORT_IN_PORTABLE_PATH=NONE
BEDROCK_IMPORT_BOUNDARY=LAZY_EXPLICIT_ONLY
NEW_RUNTIME_DEPENDENCIES=0
DIRECT_MODEL_TO_MUTATION_AUTHORITY=NONE
APPROVAL_BYPASS=NONE
HASH_BINDING_BYPASS=NONE
REPLAY_IDEMPOTENCY_REGRESSION=NONE
RECOVERY_REGRESSION=NONE
SILENT_NONE_OR_AMBIGUOUS_SUCCESS=NONE
UNBOUNDED_RETRY=NONE
ARBITRARY_SHELL_OR_URL_TOOL=NONE
ACCIDENTAL_NETWORK_CLIENT=NONE
TEST_ONLY_LOGIC_IN_PRODUCTION=NONE
HARD_CODED_MACHINE_PATH_IN_RUNTIME=NONE
SECRET_LOGGING=NONE

The only new broad exception catch surrounds optional third-party provider initialization; it never
swallows the failure and emits a fixed typed/redacted error. Socket references added in this phase
exist only in negative tests that replace connection functions with a forbidden guard. No
`pyproject.toml` dependency changed.

## Safety

HUMAN_AUTHORITY_PRESERVED=YES
APPROVAL_BINDING_PRESERVED=YES
REPLAY_PROTECTION_PRESERVED=YES
RECOVERY_PRESERVED=YES
NO_SILENT_FAILURES=YES
NO_SECRET_LEAKAGE=YES
NO_REAL_CLOUD_MUTATION=YES
ONE_AGENT_FIVE_TOOL_CAP_PRESERVED=YES
PROPOSAL_REMAINS_NON_AUTHORIZING=YES
INDEPENDENT_VERIFICATION_PRESERVED=YES
AUDIT_AND_DURABLE_ORDERING_PRESERVED=YES

## Files

FILES_ADDED=13 (including this audit report)
FILES_MODIFIED=24

Added:

- `docs/audits/PORTABLE_FOUNDATION_B0_B2_2026-09-01.md`
- `docs/JUDGE_SANDBOX.md`
- `docs/PORTABLE_RUNTIME.md`
- `docs/architecture/portable-aws-dependency-inventory.md`
- `docs/architecture/provider-neutral-strands-runtime.md`
- `scripts/run_portable_demo.py`
- `src/aioa_cloudops_agent/config/runtime.py`
- `src/aioa_cloudops_agent/portable/__init__.py`
- `src/aioa_cloudops_agent/portable/demo.py`
- `src/aioa_cloudops_agent/providers/factory.py`
- `tests/integration/test_portable_judge_sandbox.py`
- `tests/unit/test_model_provider_factory.py`
- `tests/unit/test_portable_runtime_boundary.py`

Modified:

- `.env.example`, `README.md`
- `docs/DECISIONS.md`, `docs/PROJECT_CHARTER.md`, `docs/ROADMAP_STATUS.md`
- `docs/evidence/README.md`, `docs/evidence/reviewer-evidence-manifest.json`,
  `docs/evidence/reviewer-evidence-manifest.md`
- `scripts/build_reviewer_evidence_manifest.py`, `scripts/prove_clean_clone.py`,
  `scripts/run_local_hitl_demo.py`, `scripts/run_local_phase1_demo.py`,
  `scripts/validate_reviewer_evidence_manifest.py`
- `src/aioa_cloudops_agent/agent/factory.py`,
  `src/aioa_cloudops_agent/agent/local_composition.py`,
  `src/aioa_cloudops_agent/agent/local_first.py`
- `src/aioa_cloudops_agent/config/__init__.py`
- `src/aioa_cloudops_agent/providers/__init__.py`,
  `src/aioa_cloudops_agent/providers/model.py`
- `tests/integration/test_local_first_phase_one.py`,
  `tests/integration/test_local_provider_strands_compatibility.py`
- `tests/unit/test_clean_clone_reproducibility.py`,
  `tests/unit/test_local_first_tools_and_providers.py`,
  `tests/unit/test_reviewer_evidence_manifest.py`

## Known Limitations

1. B0-B2 ships the deterministic non-AWS Strands provider, not a paid or networked real-model
   adapter. The single Strands `Model` boundary is prepared for one; adding it belongs to a later
   explicit provider decision and must preserve the same contract matrix.
2. `strands-agents==1.53.0` transitively installs boto3/botocore. Portable mode does not import the
   Bedrock integration, create an AWS client, discover credentials, or authorize an AWS call.
3. The reused verifier retains historical names such as `PostDeployVerificationReceipt` and
   `deployment_contract_sha256` for evidence-schema compatibility. In portable mode these represent
   local static contract provenance and do not claim a deployment.
4. The judge sandbox uses typed synthetic AWS-shaped resources. It proves product control flow and
   safety invariants, not live cloud availability, IAM effectiveness, Bedrock access, or a real AWS
   mutation.
5. No static type checker or repository-wide formatter is configured. Ruff lint, Python compilation,
   whitespace checks, strict Pydantic contracts, 1318 tests, P0, and P1 pass.
6. AgentCore and all live AWS deployment paths remain intentionally unexecuted and optional.

## Next Recommended Macro-Step

B3 — PORTABLE PRODUCT COMPLETION / API CONTRACT HARDENING. Harden the existing loopback API and
judge-facing product contract around the proven portable runtime; do not make B3 contingent on AWS
and do not start deployment without separate explicit authority.
