# Day 14 P1 Resilience Boundary

Status: implemented locally and proven without AWS calls. Deployment remains deferred to Day 15.

## P1 proof surface

`scripts/run_p1_gate.py` freezes six claims: injection denial, ambiguous metrics, the dependency circuit breaker, IAM permission separation, end-to-end trace continuity, and clean-clone reproducibility. The runner resolves exact source symbols and pytest nodes, runs deterministic static checks, rejects missing/failed/skipped proof, and exposes stable JSON through `--json`.

Empty, missing, stale, mixed-unit, or contradictory CloudWatch datapoints remain typed `AMBIGUOUS_RESULT`; they cannot be interpreted as zero utilization and cannot create an idle remediation proposal.

## Circuit contract

The breaker is application-owned safety logic around existing bounded read retries. It is not a Strands tool, workflow authority, approval record, retry path for mutation, or evidence of successful execution.

- States are `CLOSED`, `OPEN`, and `HALF_OPEN`.
- Identities are dependency-specific: `EC2_READ`, `CLOUDWATCH_READ`, and `VERIFICATION_READ`.
- Only a terminal, allow-listed transient read failure counts once after the existing retry budget is exhausted.
- `AccessDenied`, policy denial, validation failure, user denial, and scope denial do not count.
- `OPEN` returns a redacted dependency-unavailable failure with zero provider calls during cooldown.
- The injected monotonic clock controls cooldown; tests never sleep.
- `HALF_OPEN` admits one raw provider read with no internal retry. A competing probe is suppressed.
- A successful or permanent-response probe closes the breaker. A transient probe failure reopens it for one fresh bounded cooldown.
- Mutation operation classes are rejected before circuit acquisition. Ambiguous mutation acknowledgement remains `RECOVERY_REQUIRED` and is never replayed.

The primary runtime shares one breaker registry between EC2 and CloudWatch read services. A verification composition can share the same registry under the separate `VERIFICATION_READ` identity, as proven by the deterministic full-workflow test.

## Persistence decision

`CIRCUIT_PERSISTENCE = PROCESS_LOCAL` for the current repository shape.

There is no deployed orchestrator Lambda yet; the SAM skeleton contains health and private remediation executor functions, while Day 15 owns agent runtime deployment. A durable breaker namespace now would add DynamoDB schema, conditional-write, migration, and IAM surface before a lifecycle exists, and using DynamoDB to protect a DynamoDB outage would create a circular dependency.

Process-local state therefore suppresses repeated calls within the shared runtime/warm process only. It does not claim cross-cold-start or cross-instance suppression. Day 15 must review the real Lambda reuse/concurrency model before production wiring and choose process-local, hybrid, or a separate conditional durable record without turning circuit state into workflow or approval truth.

## Trace continuity

The primary Agent and all five tool spans carry the same `run_id`, `trace_id`, and `correlation_id`. The full mocked workflow proves that lineage through investigation evidence, proposal, HITL interrupt, durable approval, private executor command, independent verification evidence, and audit metadata. A substituted identity fails as `RUN_IDENTITY_INVALID` before durable creation, provider reads, approval, or execution.

## Scope freeze

This checkpoint adds no tool, IAM action, network egress, provider, AgentCore component, live AWS call, or mutation. AU-2 audit hash chaining remains evaluation-only after P1 is green.
