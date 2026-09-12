# Day 10 — Independent Verification and Evidenced Success

`verify_instance_state` is the fifth and final canonical tool. It is `AUTO`, read-only, and accepts only a durable `proposal_id`. The target is resolved from the immutable proposal and re-read through the same exact-instance, region, and sandbox-tag boundary used by `inspect_instance`; model input cannot select another resource.

After the private executor acknowledgement is durably recorded, the run remains `VERIFYING`. A bounded application-owned poll distinguishes `stopping`, verified `stopped`, mismatch, ambiguous provider evidence, dependency failure, and timeout. The model neither controls retries nor interprets missing data as success.

Verified evidence binds run, trace, correlation, proposal, action, target, execution acknowledgement, independent observation, request reference, and UTC verification time. A canonical SHA-256 digest is persisted in DynamoDB-compatible durable truth, followed by the completed idempotency result and audit evidence. Only then may the conditional state transition produce `SUCCESS_WITH_EVIDENCE`.

An acknowledgement alone is not success. Missing evidence, mismatched state, timeout, provider ambiguity, or final persistence failure produces an explicit failure or `RECOVERY_REQUIRED`. A duplicate completed request reconciles the prior proof without another stop or EC2 read.

The approved and denied end-to-end paths are covered with the real Strands tool/intervention loop and local provider fakes. No infrastructure was deployed, no live DynamoDB write occurred, and no live EC2 mutation or verification was performed in this checkpoint.
