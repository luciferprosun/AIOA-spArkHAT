# Local-First Phase 2 — Human Authorization and Verified Mock Execution

## Outcome and boundary

Local-2 completes the credential-free path from an evidence-backed proposal to a human-controlled,
verified terminal result. It supports exact approve and deny decisions, durable restart recovery,
replay protection, two protected local mock mutations, a loopback HTTP API, and a same-origin operator
console. It performs no credential discovery, Bedrock call, AWS API call, infrastructure deployment,
or live cloud mutation.

`QueryResource` and `PlanRemediation` remain application services behind the canonical single-agent
architecture. The Local-2 executor is not registered as an extra Strands tool. It can mutate only the
separate mock inventory file and cannot receive a provider client or arbitrary command.

## Canonical lifecycle

```text
RECEIVED -> INVESTIGATING -> EVIDENCE_READY -> REMEDIATION_PROPOSED
         -> AWAITING_APPROVAL
              | deny    -> DENIED_BY_HUMAN
              | approve -> APPROVED -> EXECUTING -> VERIFYING
                                             -> SUCCESS_WITH_EVIDENCE
```

Approval never implies execution. `resume` is a separate authenticated gesture. The durable
checkpoint retains the Local-1 evidence and proposal and adds the approval request, decision,
execution intent, receipt, and verification in order. The existing application-owned transition
table rejects shortcuts such as `AWAITING_APPROVAL -> EXECUTING` or `EXECUTING -> SUCCESS`.

## Human authority binding

The server issues a fresh decision nonce but persists only its SHA-256 hash. The challenge and
decision are bound to all decision-critical facts:

| Binding | Purpose |
|---|---|
| run and correlation identity | prevents cross-run authority substitution |
| proposal ID and canonical proposal hash | authorizes one immutable proposed action |
| evidence hash | prevents approving a proposal against different observed facts |
| proposal version and expiry | rejects stale action descriptions |
| approval-request ID/hash | gives one durable challenge ownership record |
| authenticated actor session | rejects caller-supplied or cross-session authority |
| one-time nonce hash | proves possession of the issued freshness value without persisting it raw |
| decision hash | binds the later execution intent to the exact approve/deny record |

An identical decision retry reconciles to the existing record, including after the challenge later
expires. A changed nonce, actor, decision, ID, version, proposal hash, or evidence hash is denied. A
denial is terminal and never calls the executor.

## Protected execution and recovery

`LocalMockRemediationExecutor` is the only mutation-capable local component. Before calling it, the
flow saves `LocalExecutionIntent`, including a semantic idempotency key and hashes of the proposal,
evidence, and human decision, and then enters `EXECUTING`.

The executor applies only these exact `PLAN_AND_CONFIRM` operations:

- `RELEASE_ELASTIC_IP` when the approved EIP is still unattached and byte-for-byte equal to the
  observed resource;
- `REVOKE_PUBLIC_INGRESS` for only the approved rules that still exist on the exact Security Group.

`APPLY_REQUIRED_TAGS` remains `NEVER_AUTONOMOUS`. Unknown operations, changed resources, ambiguous
rules, missing approval, mismatched hashes, expired proposals, and idempotency ownership conflicts
fail closed.

The inventory and execution receipt are committed together under a process lock using a mode-0600
temporary file, `fsync`, and atomic replace. If a process stops after that replace but before the
checkpoint stores the receipt, `resume` finds the receipt by idempotency key and reconciles without a
second mutation. A conflicting replay cannot take over the key.

## Independent verification

Provider acknowledgement is not success. After a durable receipt, the flow enters `VERIFYING` and
performs a separate read from the persisted inventory:

- a released EIP must be absent;
- a remediated Security Group must equal the exact receipt post-state.

The verification hash binds the receipt hash, target, operation, observed state, and timestamp. Only
after this proof is saved may the repository transition to `SUCCESS_WITH_EVIDENCE`. Corrupt or
unavailable state becomes a typed dependency failure; a read-back mismatch becomes a verification
failure rather than an optimistic success.

## Local API and operator console

The server exposes only:

| Method and path | Authority | Behavior |
|---|---|---|
| `GET /health` | public loopback | static liveness only |
| `GET /ready` | public loopback | truthful portable/provider/sandbox readiness |
| `GET /` | public loopback | embedded same-origin operator console |
| `GET/POST/DELETE /api/session` | loopback credential | inspect, exchange, or clear an HttpOnly browser session |
| `POST /api/runs` | Bearer or protected browser session | start one server-budgeted Local-1 investigation |
| `GET /api/runs/{run_id}` | Bearer or protected browser session | read a sanitized durable run/evidence/audit view |
| `POST /api/runs/{run_id}/approval-request` | Bearer or protected browser session | issue an exact approval challenge |
| `POST /api/runs/{run_id}/decision` | Bearer or protected browser session | persist approve or deny |
| `POST /api/runs/{run_id}/resume` | Bearer or protected browser session | explicitly resume protected execution |

The server refuses a bind other than `127.0.0.1`. It creates or loads one regular owner-only token
file, compares token digests in constant time, derives the actor session on the server, suppresses
request logging, accepts no query authority, caps request bodies, rejects duplicate/non-finite JSON
and unknown fields, and emits no exception text. B4 also caps headers and concurrent handlers, sets
a socket timeout, and makes `/ready` validate provider plus both local stores. Responses are
non-cacheable and carry CSP,
frame-denial, content-type, permissions, and referrer protections. The B3 launcher passes the raw
token only in a URL fragment, the page removes it immediately and exchanges it for an `HttpOnly`,
`SameSite=Strict` session cookie, and no credential is written to browser storage. Cookie-authenticated
state-changing requests require a non-simple fixed intent header. The run view omits nonce material
and actor-session identifiers and exposes only allow-listed audit metadata.

## Configuration and operation

```text
AIOA_LOCAL_MODE=mock
AIOA_LOCAL_HITL_STATE_PATH=.local/aioa-local-hitl-state.json
AIOA_LOCAL_INVENTORY_PATH=.local/aioa-local-mock-inventory.json
AIOA_LOCAL_APPROVAL_TTL_SECONDS=600
```

The durable-truth and inventory paths must differ, reject traversal/symlinks/hard-link aliasing, and
approval TTL must be 60–3600 seconds. An explicit `live` mode is unavailable and fails during
configuration; there is no silent fallback.

```bash
.venv/bin/python scripts/run_local_hitl_demo.py --scenario elastic-ip --decision approved
.venv/bin/python scripts/run_local_hitl_api.py --open-browser
```

Every automated demo run receives a new subdirectory under `.local/aioa-local2-demo/`, preserving
its durable JSON evidence without overwriting a prior scenario.

## Proven and not proven

Local tests prove approve, deny, replay, expiry, actor mismatch, exact-rule mutation, crash/restart
receipt reconciliation, unavailable-state classification, independent verification, HTTP schema and
authentication controls, token-file permissions, loopback binding, and zero mock network calls.
B4 additionally proves type-bound whole-snapshot integrity, atomic partial-write protection, exact
intent binding, 16-request duplicate concurrency, secret sanitization, and explicit readiness. See
[`../RELIABILITY_SECURITY.md`](../RELIABILITY_SECURITY.md).

They do not prove a live AWS identity, effective IAM policy, deployed endpoint, DynamoDB/S3 state,
Bedrock/Nova access, CloudWatch evidence, provider receipt, or live mutation. Those claims remain
blocked by the explicit Day 15 external prerequisites and require separate operator authorization.
