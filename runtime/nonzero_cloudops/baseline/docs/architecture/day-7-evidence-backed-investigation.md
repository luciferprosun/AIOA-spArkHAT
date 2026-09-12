# Day 7: Evidence-Backed Investigation

The single primary Strands Agent now exposes exactly three canonical `AUTO` tools: `inspect_instance`, `read_utilization_metrics`, and `build_remediation_evidence`. The prompt can request only these scoped operations. The deterministic Non-Zero control plane validates their order, target, typed results, authority, budgets, and legal workflow transitions.

The implemented non-mutating path is:

`RECEIVED -> INVESTIGATING -> scoped inspection -> typed utilization -> deterministic policy -> EVIDENCE_READY -> durable ActionProposal -> REMEDIATION_PROPOSED`

`build_remediation_evidence` has no external side effect. It consumes closure-bound typed inspection and utilization contracts, creates canonical SHA-256 evidence, and emits a fixed `stop_sandbox_instance` proposal only for a running sandbox instance with sufficient eligible evidence. The model cannot provide the action, target, precondition, authority, or evidence hash. A busy or non-running instance produces an explicit non-proposal outcome; ambiguous evidence produces `AMBIGUOUS_RESULT`.

The proposal is written before the run enters `REMEDIATION_PROPOSED`. It has `PLAN_AND_CONFIRM`, `PROPOSED`, and `authorizes_execution = false`. No `Approval` or execution idempotency record is created. Exact duplicate requests reconcile through the stable run/proposal identities and conditional create semantics; incompatible durable state fails closed.

Typed checkpoints retain the three tool-result hashes at `EVIDENCE_READY` and `REMEDIATION_PROPOSED`. Append-only audit events retain run/trace/correlation identity plus redacted evidence hashes. Raw provider responses and secrets are not durable evidence. S3 evidence artifacts are deferred because no S3 evidence store exists yet.

The flow applies Strands turn/token limits and maps incomplete tool sequences to explicit model-invalid or budget-exhausted outcomes. `SUCCESS_WITH_EVIDENCE` is unreachable in this package because no AWS action or post-action verification exists.

No Day 8 approval interrupt/resume handler, approval token, private executor, `stop_sandbox_instance` tool, `verify_instance_state` tool, AgentCore component, UI, deployment, live DynamoDB write, or AWS resource mutation was added. The pre-existing Strands intervention guard remains a deny/confirm boundary for unknown tools; it is not a completed HITL workflow.
