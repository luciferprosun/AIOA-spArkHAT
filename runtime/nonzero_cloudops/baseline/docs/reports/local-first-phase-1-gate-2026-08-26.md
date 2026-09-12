# Local-First Phase 1 Gate — Core Foundation Multipack

## Mandatory report

```text
PHASE = LOCAL_1
STEP = CORE_FOUNDATION_MULTIPACK

REPO = /media/l/LSC_DATA/AWS_HACKATHON/AIOA-NonZero-CloudOps-Agent
BRANCH = main
HEAD_BEFORE = 958744edeaed209aa53cddcd1cbc3b99b20b96e8
HEAD_AFTER = 98c53cd6e3e9e8548ba131440766f81f6e0b2221
WORKTREE_CLEAN = YES
PREEXISTING_DIRTY_FILES_PRESERVED = YES

PHASE_1_GATE = PASS
LIVE_AWS_REQUIRED_FOR_GATE = NO
LIVE_AWS_MUTATIONS_PERFORMED = NO

PACKAGES:
P0_BASELINE = PASS
P1_CONTRACTS = PASS
P2_STATE_MACHINE = PASS
P3_MODEL_PROVIDER = PASS
P4_CLOUD_ADAPTER = PASS
P5_STATE_STORE = PASS
P6_READ_PLAN_TOOLS = PASS
P7_APPROVAL_BOUNDARY = PASS
P8_TEST_DOC_GATE = PASS

TESTS_BASELINE = 1089 passed; one harness-only FileNotFoundError because the isolated historical worktree had no local .venv; the exact affected test passed after the documented .venv path was supplied (effective code baseline 1090/1090 PASS)
TESTS_FINAL = 1131 passed in 634.55s
LINT = PASS — .venv/bin/ruff check .
TYPECHECK = N/A — no repository type-check target is configured
BUILD = PASS — 55 locked distributions; lock_sha256=a9f9f3eeb78d5cd07185a805c2694712aeaae9ac9acd571386c3053a9bbab4a6

NEW_OR_CHANGED_FILES =
- .env.example
- .gitignore
- README.md
- docs/DECISIONS.md
- docs/ROADMAP_STATUS.md
- docs/architecture/local-first-phase-1.md
- docs/evidence/reviewer-evidence-manifest.json
- docs/evidence/reviewer-evidence-manifest.md
- docs/reports/local-first-phase-1-gate-2026-08-26.md
- scripts/build_reviewer_evidence_manifest.py
- scripts/run_local_phase1_demo.py
- scripts/validate_reviewer_evidence_manifest.py
- src/aioa_cloudops_agent/agent/__init__.py
- src/aioa_cloudops_agent/agent/local_composition.py
- src/aioa_cloudops_agent/agent/local_first.py
- src/aioa_cloudops_agent/cloudops/__init__.py
- src/aioa_cloudops_agent/cloudops/plan_remediation.py
- src/aioa_cloudops_agent/cloudops/provider.py
- src/aioa_cloudops_agent/cloudops/query_resource.py
- src/aioa_cloudops_agent/config/__init__.py
- src/aioa_cloudops_agent/config/local_first.py
- src/aioa_cloudops_agent/nz/__init__.py
- src/aioa_cloudops_agent/nz/authority.py
- src/aioa_cloudops_agent/nz/contracts.py
- src/aioa_cloudops_agent/nz/enums.py
- src/aioa_cloudops_agent/nz/transitions.py
- src/aioa_cloudops_agent/persistence/__init__.py
- src/aioa_cloudops_agent/persistence/local.py
- src/aioa_cloudops_agent/persistence/memory.py
- src/aioa_cloudops_agent/providers/__init__.py
- src/aioa_cloudops_agent/providers/model.py
- src/aioa_cloudops_agent/safety/failures.py
- tests/integration/test_local_first_phase_one.py
- tests/integration/test_local_provider_strands_compatibility.py
- tests/unit/test_cloudops_security.py
- tests/unit/test_local_file_state_store.py
- tests/unit/test_local_first_contracts.py
- tests/unit/test_local_first_tools_and_providers.py
- tests/unit/test_reviewer_evidence_manifest.py

KEY_ARCHITECTURE_DECISIONS =
- Preserve the existing single Strands agent and its exact five-tool surface; QueryResource and PlanRemediation are provider-neutral domain services, not extra registered tools.
- Reuse the canonical NZ Run, WorkflowState, Checkpoint and DurableTruthRepository contracts rather than introduce a parallel lifecycle.
- Project PENDING_APPROVAL as ExecutionState.PENDING plus ApprovalStatus.PENDING_APPROVAL and WorkflowState.AWAITING_APPROVAL, preserving stored compatibility.
- Treat all model output as untrusted candidate data and require exact equality with evidence-derived local policy before proposal creation.
- Persist typed evidence and an inert proposal checkpoint before the final AWAITING_APPROVAL transition.
- Default local composition to deterministic mock providers; reject unavailable live mode explicitly and never discover ambient AWS credentials.
- Keep Local-1 structurally incapable of cloud writes by exposing no mutation method or executor in its provider/tool path.
- Use an atomic, locked, mode-0600 JSON snapshot as the local DurableTruthRepository adapter; retain DynamoDbDurableTruthRepository as the later live adapter.
- Anchor changed safety claims to commit b5dba16a9af1bc979b2b96a50ddbf0e590e829a5 and preserve their ancestry to the prior evidence baseline.

PREEXISTING_FAILURES =
- None. The historical-SHA rerun's sole initial failure was an isolated-worktree harness path issue, not a code/test failure; its exact node passed once the documented .venv path existed.

NEW_BLOCKERS =
- None.

DEFERRED_TO_LIVE_AWS_PHASE =
- Live Bedrock provider implementation and invocation.
- boto3 CloudProvider implementation, live reads and every cloud mutation.
- DynamoDB deployment/migration and live durability verification.
- Lambda, API Gateway, IAM, S3/CloudFront, frontend and deployment verification.
- AWS credential/account recovery and any post-deployment smoke test.

RECOMMENDED_NEXT_PHASE = LOCAL_2_HITL_EXECUTION_API
```

`HEAD_AFTER` is the tested implementation/evidence commit. This report is intentionally added in a
subsequent documentation-only commit, whose SHA is reported in the final handoff; a Git commit cannot
truthfully contain its own SHA. `PREEXISTING_DIRTY_FILES_PRESERVED=YES` is vacuously true because the
attested starting worktree was clean.

## Outcome

Local execution can now inspect deterministic normalized AWS-like resources, produce typed evidence,
validate mock-model output against local Non-Zero authority policy, create a stable evidence-bound inert
proposal, persist it atomically, reopen the store after a simulated restart, and reconcile the same run.
None of those capabilities existed as one credential-free mandatory flow before this package.

Yes: the complete mandatory path reaches `WorkflowState.AWAITING_APPROVAL`, projected publicly as
`ExecutionState.PENDING` plus `ApprovalStatus.PENDING_APPROVAL`, with no AWS credentials, boto3 import,
network call, Bedrock call or cloud mutation. Protected EIP and security-group proposals stop there.
Clean inventory ends at `NO_ACTION_REQUIRED`; missing resources and injected adapter/model/storage
failures produce typed failures rather than false success.

## Canonical execution path and later adapters

The Local-1 path is composed by `agent/local_composition.py::create_local_first_runtime` and executed by
`agent/local_first.py::LocalFirstPhaseOneFlow`. It calls
`cloudops/query_resource.py::QueryResource` through `cloudops/provider.py::CloudProvider`, validates the
result of `providers/model.py::ModelProvider` through
`cloudops/plan_remediation.py::PlanRemediation`, applies `nz` authority/contracts/transitions, and writes
through `persistence::DurableTruthRepository`. The established production-facing Strands path in
`agent/factory.py` remains the single canonical agent with five registered tools; compatibility tests
prove the product mock model/cloud implementations can drive that path without expanding the tool cap.

Later integrations replace interfaces at the composition boundary:

- Bedrock plugs into `ModelProvider.create_plan`; the existing `create_bedrock_model` / Strands `Model`
  boundary remains available for the five-tool agent.
- boto3 resource reads plug into `CloudProvider.get_resource`; existing narrow EC2 and CloudWatch client
  protocols remain available to the Strands investigation path.
- DynamoDB plugs in as `DynamoDbDurableTruthRepository` wherever the flow currently receives
  `DurableTruthRepository`; the extended checkpoint remains compatible with the generic serializer.

The model cannot bypass approval because strict Pydantic contracts reject extra/invalid fields, the
candidate target/action/parameters/authority must exactly match independently derived evidence policy,
the resulting proposal has `authorizes_execution=false`, the proposal and evidence are stored before
the approval state, the transition graph has no approval-to-success shortcut, and Local-1 contains no
executor or mutation provider method.

## Validation evidence

- Historical baseline at `958744edeaed209aa53cddcd1cbc3b99b20b96e8`: 1089 tests passed in the full
  isolated run; the only initial failure was `FileNotFoundError` for that worktree's absent local
  `.venv/bin/python`. Supplying the documented venv path made the exact affected test pass, establishing
  an effective 1090/1090 code-test baseline with no pre-existing failure.
- Focused Local-1 tests: 38 passed.
- Final complete repository suite: 1131 passed in 634.55 seconds.
- Canonical P0 proof matrix: 15/15 gates passed.
- Canonical P1 resilience matrix, including clean-clone proof: 6/6 gates passed.
- Reviewer evidence/security selection: 126 passed; builder check and validator passed after re-anchoring.
- Locked Lambda artifact build: passed with 55 distributions and the lock hash recorded above.
- `ruff check .`, `python -m pip check`, and `git diff --check`: passed.
- Credential-free local demo: success at the durable approval boundary; mock network and mutation
  counters remained zero in integration proofs.

## Phase 2 boundary

Before frontend or live deployment, Local-2 must connect the existing durable HITL controls to these
new provider-neutral proposals: authenticated approve/reject/resume behavior, exact binding to proposal
ID/hash, evidence hash, version, expiry, actor session and nonce, replay protection, recovery tests, and
a protected executor against local mock state. API endpoints follow that proof. Live Bedrock, boto3
mutation, DynamoDB deployment, frontend and AWS deployment remain later, separately authorized work.

## Mutation invariant

- AWS resource creates: 0
- AWS resource updates: 0
- AWS resource deletes: 0
- live DynamoDB writes: 0
- Bedrock invocations: 0
- network calls from the mandatory local flow: 0
- protected mock/cloud mutation calls from the mandatory flow: 0
