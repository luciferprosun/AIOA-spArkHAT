# Day 13 — P0 Proof Gate and AU-1 Emergency Executor Disable

Armor Phase 1 keeps the frozen one-agent/five-tool CloudOps architecture and adds two repository-owned safety layers: an executable P0 proof gate and an independent negative veto at the private EC2 mutation boundary. All Day 13 evidence is deterministic and local. No AWS API, network DryRun, infrastructure deployment, or live workload mutation was performed.

## Executable P0 gate

[`scripts/run_p0_gate.py`](../../scripts/run_p0_gate.py) maps P0-01 through P0-15 to exact source symbols, pytest node IDs, and deterministic static checks. It proves named invariants rather than treating the full-suite count as evidence by itself. Missing/renamed evidence, collection failure, a failed/error test, or any skipped required proof produces a non-zero exit. Output omits timing, subprocess logs, environment values, and secret candidates.

K1 also closed direct-proof gaps exposed by the matrix: durable checkpoint evidence must now match the immutable proposal hash; missing proposals, cross-run/cross-proposal Approval substitution, changed decision-nonce replay, each positive execution opt-in, and terminal token exhaustion have dedicated regressions. The runtime authority remains the typed Non-Zero control plane, `CURRENT_TOOL_NAMES`, `FINAL_TOOL_CAP`, and `DefaultDenyToolPolicy`; the gate is verification code, not a second capability manifest.

## AU-1 negative veto

`EnvironmentEmergencyExecutionControl` is injected only into `Ec2SandboxStopExecutor`. It reads `AIOA_EMERGENCY_EXECUTION_DISABLED` afresh at each boundary. Only the exact string `false` releases this veto. `true`, absence, whitespace/case variants, non-string values, malformed input, or a reader failure all raise the fixed `RemediationEmergencyDisabledError`; the raw value and reader error are not retained in the result.

The effective permission remains conjunctive:

```text
durable proposal and matching evidence
AND explicit proposal/run/nonce-bound human Approval
AND exact action, target, tag, region, and running precondition
AND stable semantic idempotency ownership
AND AWS_MUTATIONS_ENABLED == true
AND AIOA_ALLOW_LIVE_SANDBOX_STOP == true
AND AIOA_EMERGENCY_EXECUTION_DISABLED == false
```

The negative flag grants nothing by itself. The executor checks it immediately before the fake-tested `StopInstances(DryRun=True)` boundary and reads it again immediately before the fake-tested real-call boundary. A flip to disabled or an unavailable second read after DryRun aborts before the non-DryRun call. Human Approval, tool/model payloads, and idempotency cannot set or override it. SAM defaults the independent control to `true`, while the two existing positive opt-ins continue to default to `false` independently.

The private Lambda converts only this one typed exception into the exact internal envelope `DENIED_BY_POLICY / EXECUTOR_EMERGENCY_DISABLED`. The orchestrator adapter recognizes only that exact two-field envelope and restores the typed exception. `StopSandboxInstanceCoordinator` then persists the existing redacted `POLICY_DENIED` audit event with `policy_code=EXECUTOR_EMERGENCY_DISABLED` when durable storage is available. If that audit write fails, the already-blocked executor remains blocked and the coordinator returns a durability/recovery failure; the outage never becomes permission.

Environment injection is the bounded operator configuration path for this phase. Re-reading closes stale in-process control state at each boundary, but this document does not claim an instantaneous out-of-band revocation of an already-running Lambda environment.

## Re-proof result

From clean `main` after K2:

- full suite: 552 passed, 0 failed, 0 skipped;
- canonical P0 runner: 15 passed, 0 failed, 0 skipped, covering 136 required pytest cases;
- focused recovery, native HITL, remediation/AU-1, verification, safety, and durable-idempotency regressions: 177 passed;
- focused IAM/infrastructure/static mutation checks: 29 passed;
- Ruff, dependency integrity, tracked-file secret scan, Phase 1 tag, pre-Armor ancestry, and Git diff checks: pass;
- runtime topology: one primary Strands Agent and exactly five canonical principal tools.

These results prove the local deterministic package only. They do not claim production readiness, production HA, broad CloudOps autonomy, live mutation demonstration, or deployed infrastructure.

## Provenance and next boundary

The global write-kill-switch concept existed in prior art; the AWS/Strands implementation here was independently re-authored as a narrow executor-local veto and strengthened with two last-boundary checks, typed cross-Lambda denial, durable audit mapping, and falsification tests. The forensic baseline and capability-evolution evidence remain in [`docs/audit/prior-art-june1-forensic-baseline.md`](../audit/prior-art-june1-forensic-baseline.md) and [`docs/audit/prior-art-capability-evolution-matrix.md`](../audit/prior-art-capability-evolution-matrix.md); their frozen blobs and the Phase 1 tag are checked by P0-15.

AU-2 tamper-evident audit continuity is not implemented. AU-3 reviewer evidence manifest is not implemented. Day 14 circuit-breaker work has not started. This checkpoint stops before those boundaries.
