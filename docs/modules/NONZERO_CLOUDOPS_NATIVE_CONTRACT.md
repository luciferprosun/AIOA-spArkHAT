# AIOA spArkHAT — native NonZero CloudOps contract v1

Frozen before implementation on child branch `integration/nonzero-cloudops-native-v1`.
The same native behavior is retained after local Phase 4 reference-tree retirement.

## Identity and discovery

Stable identity `nonzero-cloudops`; product name exactly `AIOA spArkHAT`. `module_descriptor(config=None)` is dependency-free and side-effect-free. It reports contract version, capabilities, availability code, prerequisites, selected/default backend, source SHA, `/nonzero`, and `/api/nonzero`. AgentRuntime.snapshot_status uses the same metadata. Missing extras, invalid configuration, disabled module, unsupported Python, provenance mismatch and unavailable AWS do not crash ordinary Core discovery.

Immutable source SHA: `4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a`. Core baseline: `5f30f092f7a20035ed1caf4a8e22397673f598df`. Source lineage commits `119a8ba12e54a2fbea42a43d62725e25fb5bc380`, `15c63fda6e759312924eb272a5dbda20269bad2f`, `ad7d2ffa602654fab7ffe30168339f2dc138278f` remain intact.

## Admission and lifecycle

AgentRuntime lazily owns one NonZeroCloudOpsService in its `runtime_state_dir/nonzero_cloudops/native-v1` namespace. Constructor injection supplies the Core kill-switch guard and Core-owned local operator identity. Only the existing local CLI or authenticated Core HTTP handler may set the internal operator marker. No model tool registers execution/approval; assistant chat rejects `/nonzero` in ordinary and CPL paths. Existing HTTP Host/Origin/token/intent checks remain mandatory. No second server, auth token, cookie/session manager, provider manager or top-level authority plane.

Core owns admission and service lifecycle. NonZero owns only domain-specific exact approval and recovery. Service has a process lease, serialized requests, explicit close, no background execution and no automatic recovery action on startup. Existing Phase 2 state requires a separate future migration; never silently grant its credentials authority.

The Core identity `core-local-operator` denotes one trusted local operator. The
legacy DTO field name `actor_session_id` carries that identity across runtime and
browser restarts. It is not an identity for each browser session and provides no
public multi-user isolation. The HTTP session token admits requests to Core;
the separate exact decision nonce binds the human decision.

## Configuration and Python

`ModuleConfig` is immutable and rejects unknown fields/coercion: enabled bool; backend `portable` or `aws`; explicit AWS enable flag; immutable expected source SHA; bounded approval TTL and run/state/output quotas. Defaults are enabled portable, no external models, no AWS. Ambient environment cannot turn on privileged capabilities. AWS explicitly selected without config or a certified backend returns a fixed unavailability code, never mock fallback. No credential reads or live AWS in this phase.

Phase 6 fixes configuration for an entire `AgentRuntime` lifetime.
`create_runtime(nonzero_config=...)` snapshots input into a private frozen value;
malformed input retains only a typed error. The `nonzero_config` and service
`config` properties reject assignment. Reconfiguration requires closing the old
runtime and creating a new one. Status before initialization describes startup
configuration without creating module state; afterward it describes the cached
service's effective configuration. Close makes both status and retained service
references unavailable and prevents lazy reinitialization.

Target Python policy A: native and Core >=3.11. Preserve Pydantic/UUID schema behavior using TypeVar/Generic instead of PEP 695 syntax. Exact compatibility must be tested on real 3.11 and 3.12 interpreters, not version mocking alone. Optional dependencies are installed once through `aioa-sparkhat[nonzero]`, not an embedded project. Discovery on an interpreter below minimum returns an unavailable code where parsing permits; Core >=3.11 remains the installation floor.

## Typed operations and data

`NonZeroCloudOpsService` exposes typed start/investigate, run inspection, request approval, decision and resume methods using frozen Pydantic domain DTOs. A small compatibility dispatcher `request(method, path, payload, operator=...) -> (HTTP status, JSON object)` serves existing Core CLI/API only; it validates exact route/body and maps typed results. Unknown fields, duplicate JSON keys, non-finite JSON, oversized bodies and arbitrary URL/shell/path selection are rejected.

Inputs: `StartRunRequest(resource_type, resource_id)` with exact resource type/ID validation and server-owned region/budget; `DecisionRequest(request_id, run_id, proposal_id, request_hash, proposal_hash, evidence_hash, proposal_version, decision, decision_nonce)`; `ResumeRequest(confirm_execution=True)`. Run/request/proposal/trace/correlation IDs are UUIDv7. No caller can supply executable scripts, credentials, an approved flag or a privileged backend through a run body.

Outputs: typed initial completion, exact proposal/evidence challenge, durable approval resolution, terminal execution completion, sanitized run view and runtime counters. Failures return stable code/kind/retryability, never raw exceptions/provider payloads. Nonces are returned only in the operator challenge, never in public trace/logs. Runtime labels say Core native portable/deterministic, never falsely claim Strands or real cloud execution.

## Safety workflow

```text
RECEIVED -> INVESTIGATING -> EVIDENCE_READY -> inert proposal -> AWAITING_APPROVAL
  -> fresh exact challenge -> durable APPROVED or DENIED_BY_HUMAN
  -> explicit resume + confirmed execution + Core admission/kill switch
  -> durable intent -> EXECUTING -> independent VERIFYING -> SUCCESS_WITH_EVIDENCE
```

Safe alternatives: NO_ACTION_REQUIRED or RECOMMENDATION_ONLY. Failure states stay typed (policy denial, validation/model output invalid, dependency/storage unavailable, expired approval, conflict, verification failure, recovery required). Incomplete/uncertain state never masquerades as success.

Advisory candidate output has no execution authority. Domain policy validates target, operation, normalized parameters and evidence. Proposal authority is PLAN_AND_CONFIRM and remains inert. Human decision binds request/run/proposal/hash/evidence/version/action/target/operator/nonce and TTL. Approval does not execute. Denial cannot mutate. Replayed same decision may return its prior resolution, but conflicting or cross-action reuse is rejected. Expired/stale evidence cannot silently authorize a new action.

The portable backend atomically writes synthetic mutation and execution receipt together; domain checkpoint compare-and-set and durable idempotency prevent duplicate execution across retries/restarts. Reconciliation reads receipt first. A genuinely uncertain/corrupt state fails closed; no blind cloud retry is possible. Execution and verification are separate operations; verification reads the persisted inventory independently and validates exact postconditions, not model assertions.

## Evidence and boundaries

Resource evidence -> proposal hash -> request hash -> decision hash -> intent hash/idempotency key -> receipt hash -> independent verification hash. Every record binds relevant run/proposal/trace/correlation IDs and UTC timestamps. Run view exposes sanitized audit categories and integrity status. Determinism is for fixed inputs/clock/IDs, not a claim that wall-clock runs have identical hashes.

Reuse `tools.provenance.AppendOnlyProvenanceStore` and `verify_provenance_chain` for Core-visible intent/result linkage. Include native contract version, immutable JUDGE_SHA and domain hashes. Validate persistent source identity before dispatch, and record intent durably before mutation. Log inability or corruption must fail closed. Domain checkpoint events are not a competing global provenance system. Hashes establish integrity/linkage, never factual truth; local filesystem ownership is the trust boundary, not an external attestation.

Phase 6 persists the Core chain's entry count and terminal hash in a private,
integrity-enveloped `provenance/chain-head.json`. Each append fsyncs the log before
atomically replacing and fsyncing that head. A valid prefix of a truncated log
therefore fails closed. A crash between the two durable writes also fails closed;
the service never adopts a mismatched head automatically. Existing unanchored
Phase 3–5 state requires explicit operator recovery or a separate clean state
namespace. Preserve the entire old namespace for investigation; do not delete
receipts, checkpoints or the log to manufacture a successful recovery. An operator
may restore a known complete matching log/head pair from a trusted backup; this
release provides no automatic migration or repair command. These local digests
cannot detect a privileged owner deliberately rewriting both log and anchor.

If a Core result append fails after the durable human decision or after verified
execution, the request fails visibly. An explicit retry uses the exact durable
decision/receipt/verification and sets `reconciled=true`; it cannot change the
decision or execute a second mutation. The earlier unmatched Core request remains
in the trace, and the recovered result links the same domain hashes. If the chain
itself is incomplete, integrity repair must precede that retry.

Before resume dispatch, the service checks a conservative serialized execution
budget: 8192 bytes for bounded fixed fields/framing, the exact approval, and three
copies of the observed resource. The only executable operations remove an EIP or
an ordered subset of ingress rules, so after/observed resources cannot be larger.
ASCII-escaped JSON including nulls bounds the service and HTTP encodings. The
minimum accepted limit is 16384 bytes. Oversized resources are refused before
intent/dispatch; after an explicit restart with a larger valid limit, the same
approved action can resume. This calculation creates no action or simulated
receipt and does not duplicate mutation logic.

## Runtime independence and certification

No native import/read/launch into baseline; no runtime Git, pip, clone/fetch, shell launcher or second app. The frozen source repositories stay untouched. The imported reference directory is now retired from the active Core tree and installed wheel, while Git history preserves recovery. Static checks plus clean installed-wheel happy/deny/binding/replay/restart/provenance tests must pass with baseline physically absent, not masked or restored. The sealed pre-retirement reference results are historical evidence; full current Core/native regression has no source-tree oracle dependency.

The original Phase 3/4 local-only publication restriction ended with Phase 5's
authorized Draft PR #1. Phase 6 may update only that existing candidate branch
after local certification. Its no-secrets GitHub CI uses Python 3.11/3.12 and
read-only repository permissions. Hosted checks are reported separately from
local checks. PR #1 must stay Draft; merge, tags, release, deployment, live cloud
and paid model calls require a separate future decision.
