# Day 8 — Native Strands HITL

The canonical `stop_sandbox_instance` tool is now present as a `PLAN_AND_CONFIRM` boundary. The three investigation tools remain `AUTO`; Strands `HumanInTheLoop` allow-lists only those read-only tools and emits a native `Confirm` interrupt before the stop boundary.

The human-visible payload is reconstructed from the immutable durable `ActionProposal`, not model prose. It includes the run and proposal identifiers, exact sandbox target, action, precondition, evidence hash, and a deterministic impact statement. The interrupt identifier and payload hash are checkpointed with `AWAITING_APPROVAL`.

Resume accepts a strict typed response bound to the same interrupt, proposal, target, action, and evidence. The first durable decision wins; an identical replay reconciles, while conflicting or tampered responses fail closed. A positive decision is persisted before the run enters `APPROVED`; denial enters terminal `DENIED_BY_HUMAN`. Model text and configuration flags cannot become approval.

This checkpoint adds no EC2 execution. The stop tool's default handler fails closed, and Day 8 tests use a non-mutating boundary solely to prove native interrupt/resume ordering. No AWS resource mutation, deployment, or live DynamoDB write occurred.
