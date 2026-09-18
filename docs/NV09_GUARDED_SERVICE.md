# Guarded disposable service domain

NV09 adds an explicit host `GuardLoopBinding` to the existing `LiteBindings`.
`AgentRuntime` still owns one `LiteScheduler`, its mutex and durable flock lease.
The normal read-only LITE manifest does not enable effects. An admitted host
composition must separately supply a `CoreServiceGuard`, its existing
`CoreAdmission`, scoped `TransactionRunner`, `ServicePolicy` and immutable
`LoopbackTargetClient`. Inspection ticks (`execute=False`) cannot infer or act.

The model supplies the strict `aioa-service-proposal-v1` data schema. It cannot
supply principals, consent, policy, verification, transport handles or tools.
The existing NVIDIA provider, exact model pin, source-bound live gate and
reservation journal remain in use. Each operation has one actor reservation;
an uncertain or already attempted proposal is never regenerated automatically.

## Effect and durability

Only `SET_MAINTENANCE` on the exact disposable local target is supported.
Owner approval binds owner/scope, operation, target, revision, effect class,
maximum one logical effect, policy digest and expiry. `OWNER_APPROVAL` is
required to approve/revoke; `COMMIT` is required to attempt an effect; `READ`
is required to inspect the private operation. Existing sealed Core principals
are used throughout. No new authority issuer or scheduler is introduced.

Existing scoped Cockroach `operations` and `audit_events` hold immutable
approval, revocation, proposal, intent, receipt, verification and denial facts.
Native `execute_once` makes each stage idempotent. There are no SQL changes.
No transport runs inside a transaction callback, including retries on 40001.
An uncertain database commit requires an exact durable read before progressing.

The mutating client boundary consumes a registered single-use authorization
bound to the client and exact request. Under the same Core lock used by
revocation, it re-reads target identity/version, current consent, policy and
expiry immediately before POST. Target-side compare-and-set closes the final
revision race. The disposable process atomically stores its state change and
idempotency receipt using existing private-file locking/integrity/fsync helpers.

After dispatch, Core reads the target's receipt, persists its own receipt, then
independently GETs actual state. Only exact identity, next revision, mode and
effect count permit a `VERIFIED` event. Neither model output nor ACK alone is
verification. Replay returns the historical verified event without a new effect.

Any existing intent resumes through read-only target reconciliation. A missing,
unavailable, malformed or conflicting target receipt remains `UNKNOWN`; no
automatic equivalent POST exists on that path. The displayed mutation count
is unknown while the outcome is unresolved. Consent/target denial before the
network effect is separately reported as `BLOCKED` with no dispatch.

## Containment and test qualifications

The target is a disposable process, bound to `127.0.0.1`, with its own private
state directory and host-owned authentication material. It does not control
system services, user data, cloud resources or networking. Bootstrap uses an
inherited pipe, not command-line secrets. Model/agent strings never receive the
host key or Python execution. Arbitrary code execution as the trusted host user
is outside this composition's threat model; Core principals are process-local.

`operator_advance` is a host-only disposable-test control, absent from the HTTP
interface. `drop_ack` is an explicit process-bootstrap fault used to prove lost
ACK recovery after durable target commit. Tests also actually exit a worker
after the effect, before the local receipt, then open a fresh scheduler.

No NemoClaw/OpenShell/OpenClaw integration is claimed when their runtimes are
unavailable. The existing bounded runtime and isolated local tests establish
the contract. File transaction fixtures and TEST provider responses remain
labelled separately from actual Cockroach and actual NVIDIA generation evidence.

Service transitions create minimal operation/audit facts, not Personal Delta or
conversation storage. Memory, CPL, tags, index scores and pheromones have no
entry into the consent/dispatch decision; existing owner-scoped memory contracts
remain unchanged.
