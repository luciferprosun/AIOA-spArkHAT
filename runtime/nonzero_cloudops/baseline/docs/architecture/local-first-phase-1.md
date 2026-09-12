# Local-First Phase 1 — Core Foundation Multipack

## Scope and outcome

This package makes the cloud-independent CloudSecOps foundation runnable with zero AWS credentials.
It performs exact resource reads, deterministic policy evaluation, model-output validation, inert
proposal creation, durable local persistence, and a hard stop at human approval. It performs no AWS
deployment, credential discovery, Bedrock invocation, or cloud mutation.

The established single Strands agent and its five registered tools remain canonical and unchanged.
`QueryResource` and `PlanRemediation` are provider-neutral domain services, not additional registered
Strands tools, so D-012's five-tool surface is not expanded. `MockModelProvider` also implements the
native Strands `Model` interface, allowing the existing agent path to use the same local provider
boundary in deterministic tests.

## Dependency direction

```text
LocalFirstPhaseOneFlow
  ├─ ModelProvider ── MockModelProvider          (Bedrock adapter later)
  ├─ QueryResource ── CloudProvider
  │                    └─ MockAwsAdapter          (boto3 adapter later)
  ├─ PlanRemediation ── local NZ authority policy
  └─ DurableTruthRepository
                       └─ LocalFileDurableTruthRepository
                                                    (DynamoDB adapter preserved)
```

Domain services receive their dependencies explicitly. AWS-shaped data is normalized at the adapter
boundary before it can become evidence. Raw model JSON is parsed as untrusted data and must match the
action, target, parameters, and authority independently derived from evidence.

## Canonical flow and lifecycle mapping

The internal workflow preserves the more precise existing `WorkflowState` vocabulary:

```text
RECEIVED
  -> INVESTIGATING
  -> EVIDENCE_READY
  -> REMEDIATION_PROPOSED
  -> AWAITING_APPROVAL
  -X-> cloud mutation
```

The public lifecycle projection is:

| Phase contract | Existing canonical representation |
|---|---|
| `INIT` | `ExecutionState.INIT` / `WorkflowState.RECEIVED` |
| `RUNNING` | `ExecutionState.RUNNING` / active investigation substates |
| `PENDING_APPROVAL` | `ExecutionState.PENDING` plus `ApprovalStatus.PENDING_APPROVAL` / `WorkflowState.AWAITING_APPROVAL` |
| `SUCCESS` | `ExecutionState.SUCCESS` / evidence-backed safe terminal states |
| `FAIL` | `ExecutionState.FAIL` / typed terminal failure substates |

This preserves persisted compatibility while keeping approval waiting unambiguous. Terminal states
cannot escape, and `AWAITING_APPROVAL` cannot transition directly to verified success.

Clean resources end explicitly at `NO_ACTION_REQUIRED`. A safe recommendation which current policy
classifies `NEVER_AUTONOMOUS` ends at `RECOMMENDATION_ONLY`; neither path fabricates a remediation.

## Deterministic mock inventory

| Scenario | Fixture | Expected result |
|---|---|---|
| A | `eipalloc-0123456789abcdef0`, unattached | `RELEASE_ELASTIC_IP` proposal, `PLAN_AND_CONFIRM` |
| B | `sg-0123456789abcdef0`, public SSH ingress | `REVOKE_PUBLIC_INGRESS` proposal, `PLAN_AND_CONFIRM` |
| C | `i-0fedcba9876543210`, required tags missing | non-executable tag recommendation, `NEVER_AUTONOMOUS` |
| D | `i-0123456789abcdef0`, compliant | explicit `NO_ACTION` |
| E | any absent exact identifier | typed `NOT_FOUND`; never empty success |
| F | injected adapter failure | typed `TOOL_ADAPTER_FAILURE` |

The adapter tracks reads, network calls, and mutation calls. Local execution must retain zero network
and mutation calls. It also provides the narrow `describe_instances` and `get_metric_statistics`
methods used by the established Strands investigation, without importing boto3.

## Evidence, proposal, and persistence invariants

- `ResourceEvidence` contains typed normalized facts, structured provenance, UUIDv7 identities, UTC
  timestamps, `AUTO` authority, and a canonical SHA-256 evidence hash.
- `RemediationProposal` is immutable data with an exact target, operation, normalized parameters,
  evidence references, risk, expiry, version, authority class, and `authorizes_execution=false`.
- `proposal_hash` excludes proposal IDs and timestamps and includes the stable resource/action
  fingerprint, so identical canonical actions retain the same hash.
- Model output cannot supply authority. A candidate differing from local evidence or policy is denied.
- `LocalFileDurableTruthRepository` atomically replaces a mode-0600 JSON snapshot under a process
  lock. Every load reconstructs Pydantic contracts; malformed or unknown state fails closed.
- Optimistic run versions reject stale writers. A failed atomic write leaves the prior file intact.
- Evidence and the awaiting proposal are saved in a typed `Checkpoint` before the final
  `AWAITING_APPROVAL` transition.

The local file stores no credentials, approval tokens, provider clients, or opaque model internals.

## Configuration and commands

Safe defaults are shown in `.env.example`:

```text
AIOA_LOCAL_MODE=mock
AIOA_LOCAL_STATE_PATH=.local/aioa-local-phase1-state.json
```

Run the deterministic EIP scenario:

```bash
.venv/bin/python scripts/run_local_phase1_demo.py \
  --state-path .local/aioa-local-phase1-state.json
```

An explicit `AIOA_LOCAL_MODE=live` request is rejected because live composition is outside this
phase. There is no live-to-mock fallback and no ambient credential lookup.

## Preserved live integration points

- Bedrock remains behind the existing `create_bedrock_model` / Strands `Model` boundary. A later
  synchronous plan adapter can implement `ModelProvider.create_plan` without changing proposal policy.
- boto3 reads plug into `CloudProvider.get_resource`; the current scoped EC2 and CloudWatch client
  protocols remain intact for the five-tool Strands workflow.
- `DynamoDbDurableTruthRepository` remains the live durable store. The extended `Checkpoint` uses the
  existing generic serializer, so resource evidence and proposal metadata do not require a second
  lifecycle or table contract.

## Deferred to Local-2 and live AWS

Local-2 must add an authenticated approve/reject/resume API, bind the human decision to proposal ID,
proposal hash, evidence hash, version, expiry, actor session, and nonce, and enforce replay protection.
Only then may a protected local mock executor be introduced. Live boto3 mutation, live Bedrock tests,
DynamoDB deployment, Lambda/API Gateway, IAM changes, frontend work, and deployment verification remain
explicitly deferred.
