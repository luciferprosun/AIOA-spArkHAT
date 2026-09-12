# Non-Zero Workflow Contracts

The canonical idle-EC2 workflow is represented by closed Pydantic contracts and an application-owned transition table. New runs begin at `RECEIVED`; approval, execution, verification, and `SUCCESS_WITH_EVIDENCE` cannot be skipped. Terminal states cannot re-enter active execution.

Capability authority is closed and deterministic. The three observational/evidence capabilities and verification use `AUTO`; the future sandbox stop uses `PLAN_AND_CONFIRM`; destructive, shell, code-execution, URL-fetch, network-opening, IAM, database-deletion, termination, and out-of-sandbox capabilities are `NEVER_AUTONOMOUS`. Unknown values fail closed.

`ActionProposal` is typed write-before-execute data, not approval. It accepts only the canonical sandbox-stop capability, a typed EC2 target, a running-state precondition, matching evidence hashes, and `PLAN_AND_CONFIRM`. Human approval is a separate immutable record with an explicit decision, actor session, timestamp, and nonce.

Run, proposal, approval, idempotency, checkpoint, audit-event, failure, and result contracts preserve UUIDv7 identifiers, enums, UTC timestamps, hashes, authority, and explicit failure categories across serialization. This layer adds no AWS mutation, persistence claim, recovery executor, HITL completion, or deployment.
