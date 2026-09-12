# AWS Boundary and Cost Guardrails

## Execution Boundary

The application boundary is fixed to `eu-central-1`. The runtime architecture uses one Strands Agent with Amazon Bedrock, deterministic Non-Zero controls, and planned DynamoDB state. The current development model candidate is Nova 2 Lite through the explicit `eu.amazon.nova-2-lite-v1:0` identifier. AgentCore is not used.

AWS operations are classified through a closed catalog:

- read-only discovery may use `AUTO`;
- mutations must never use `AUTO`;
- `PLAN_AND_CONFIRM` may produce a proposal, but execution requires both the global mutation capability and separate explicit human approval;
- `NEVER_AUTONOMOUS` operations cannot be executed autonomously, even when configuration and approval are present.

AWS mutations are globally disabled by default. Configuration enabling AWS writes is not authorization to perform a specific mutation. Missing or malformed configuration fails explicitly.

## IAM Boundary

The active `CloudOpsReadOnlyRole` design grants only `ec2:DescribeInstances` for `inspect_instance` and `cloudwatch:GetMetricStatistics` for `read_utilization_metrics`. These read APIs do not support useful resource-level scoping, so the documented `Resource: "*"` limitation is constrained by the exact actions, an `eu-central-1` condition, and application checks for one configured instance ID, its required sandbox tag, and a fixed metric request.

No remediation policy is active. A future `stop_sandbox_instance` policy must remain separate and cannot be introduced before explicit authority, human approval, and least-privilege review are implemented. Templates contain no account ID, principal, credential, trust policy, or secret, and nothing was deployed.

## Cost Boundary

- budget warning: USD 10;
- elevated warning: USD 25;
- critical warning: USD 40;
- model output cap: 1024 tokens;
- DynamoDB billing: `PAY_PER_REQUEST`;
- CloudWatch retention: 3 days.

Threshold ordering and service limits are typed and validated. No AWS Budget, AWS resource, model invocation, or deployment occurred in this step.
