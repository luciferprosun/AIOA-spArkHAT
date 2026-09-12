# Day 9 — Private Sandbox Remediation

`stop_sandbox_instance` remains `PLAN_AND_CONFIRM` and accepts only a durable `proposal_id`. The Non-Zero coordinator resolves the immutable proposal, positive proposal-bound `Approval`, approved run, checkpoint, and stable semantic idempotency record before building a typed internal command. Model text cannot provide an instance ID, region, force option, or AWS mutation parameters.

The model-facing orchestrator owns no `ec2:StopInstances` permission or EC2 mutation client. It can invoke only one private remediation function. The executor role grants only `ec2:StopInstances` for the explicit instance ARN in `eu-central-1`, constrained by the canonical sandbox resource tag. No terminate, start, reboot, tag, SSM, shell, IAM, or generalized EC2 write permission exists.

The private executor fails closed unless both the global mutation switch and `AIOA_ALLOW_LIVE_SANDBOX_STOP` are true. It rechecks the exact target, tag, EBS backing, region, and running precondition; performs the AWS `DryRun` permission check; then issues one normal graceful stop without force, hibernate, or skip-shutdown controls. Configuration is never human approval.

The stable idempotency claim is durable before invocation. An unresolved claim is `RECOVERY_REQUIRED` and is never blindly replayed. The provider acknowledgement is persisted separately from verified completion and advances only to `VERIFYING`; it cannot produce `SUCCESS_WITH_EVIDENCE`.

All validation in this checkpoint uses local fakes. No infrastructure was deployed and no live EC2 or DynamoDB mutation occurred.
