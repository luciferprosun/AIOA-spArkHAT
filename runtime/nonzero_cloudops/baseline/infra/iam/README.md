# IAM Design Boundary

These policy documents are public-safe design templates only. They were not deployed and contain no account identifiers, principals, trust policies, or credentials.

## CloudOpsReadOnlyRole

`cloudops-read-only-policy.json` permits only `ec2:DescribeInstances` and `cloudwatch:GetMetricStatistics` for the canonical `inspect_instance` and `read_utilization_metrics` tools. These read APIs do not support useful resource-level scoping, so the policy requires `Resource: "*"`. The application independently requires one configured instance ID, matching sandbox tag proof, fixed namespace/metric/dimension, and `eu-central-1`. The policy grants no write or mutation action.

## CloudOpsRemediationRole

The model-facing orchestrator retains read-only EC2/CloudWatch access and may invoke only the exact private remediation function. It has no direct `ec2:StopInstances` authority.

The private remediation executor policy grants only `ec2:StopInstances` for the explicitly configured instance ARN, constrained to `eu-central-1` and the canonical sandbox resource tag. It grants no terminate, start, reboot, tag, shell, SSM, IAM, or generalized EC2 mutation capability. Configuration flags default to false and are not human approval. These artifacts have not been deployed.

Configuration does not authorize a mutation. The global mutation flag, explicit human approval, application boundary, and remediation role are independent controls.

Reference: <https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html>
