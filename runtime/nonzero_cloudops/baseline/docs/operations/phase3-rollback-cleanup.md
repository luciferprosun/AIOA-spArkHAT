# Phase 3 Rollback and Cleanup Contract

Status: local plan-only contract. It performs no AWS read or write and emits no cloud command.

- Deployment contract SHA-256: `17b8b8663fee59caaad493eb009ae9acf5c066017cbc205eaeb6b8b2ad8d4ce5`
- Expected-resource manifest SHA-256: `259190cdd158b8477016ee0c65bb2b000f581554c858e29ccd88aaab7de7021b`
- Cleanup contract SHA-256: `811d32052af95a7c42b0559551c58c03a9b454cd6be51587182f939941414f4b`
- Execution enabled by default: `false`
- Network connections / AWS mutations / live receipts: `0 / 0 / 0`

## Partial states

- `DEPLOYMENT_STARTED_THEN_FAILED`
- `RESOURCE_EXISTS_VERIFICATION_FAILED`
- `APPROVAL_EXPIRED`
- `RETRY`
- `ROLLBACK_PARTIALLY_FAILED`
- `DEPLOYMENT_VERIFIED`

Every retry rebuilds the same plan from durable bindings. Expired approval requires a fresh decision. A failed rollback plans only still-observed, proven-owned resources.

## Resource rules

| Logical ID | Type | Ownership proof | Lifecycle | Normal rollback | Partial failure |
|---|---|---|---|---|---|
| `JudgeTokenSecret` | `AWS::SecretsManager::Secret` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `OrchestratorAlias` | `AWS::Lambda::Alias` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `OrchestratorDurationAlarm` | `AWS::CloudWatch::Alarm` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `OrchestratorErrorsAlarm` | `AWS::CloudWatch::Alarm` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `OrchestratorFunction` | `AWS::Serverless::Function` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `OrchestratorFunctionLogGroup` | `AWS::Logs::LogGroup` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `OrchestratorFunctionUrl` | `AWS::Lambda::Url` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `CONDITIONAL_STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `OrchestratorRole` | `AWS::IAM::Role` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `OrchestratorThrottlesAlarm` | `AWS::CloudWatch::Alarm` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `OrchestratorVersion` | `AWS::Lambda::Version` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `RETAIN_EXPLICIT_DISPOSITION` | `RETAIN_PENDING_EXPLICIT_DISPOSITION` | `RETAIN_PENDING_EXPLICIT_DISPOSITION` |
| `PublicFunctionInvokeViaUrlPermission` | `AWS::Lambda::Permission` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `CONDITIONAL_STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `PublicFunctionUrlInvokePermission` | `AWS::Lambda::Permission` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `CONDITIONAL_STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `RemediationExecutorAlias` | `AWS::Lambda::Alias` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `RemediationExecutorDurationAlarm` | `AWS::CloudWatch::Alarm` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `RemediationExecutorErrorsAlarm` | `AWS::CloudWatch::Alarm` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `RemediationExecutorFunction` | `AWS::Serverless::Function` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `RemediationExecutorLogGroup` | `AWS::Logs::LogGroup` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `RemediationExecutorRole` | `AWS::IAM::Role` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `RemediationExecutorThrottlesAlarm` | `AWS::CloudWatch::Alarm` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |
| `RemediationExecutorVersion` | `AWS::Lambda::Version` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `RETAIN_EXPLICIT_DISPOSITION` | `RETAIN_PENDING_EXPLICIT_DISPOSITION` | `RETAIN_PENDING_EXPLICIT_DISPOSITION` |
| `StateTable` | `AWS::DynamoDB::Table` | `STACK_AND_EXACT_TAGS` | `RETAIN_EXPLICIT_DISPOSITION` | `RETAIN_PENDING_EXPLICIT_DISPOSITION` | `RETAIN_PENDING_EXPLICIT_DISPOSITION` |
| `StateTableThrottledRequestsAlarm` | `AWS::CloudWatch::Alarm` | `STACK_AND_EXACT_TAGS` | `STACK_DELETE` | `DELETE_WITH_CLOUDFORMATION_STACK` | `RETRY_CLOUDFORMATION_STACK_DELETE` |

A name is never ownership proof. Deletion eligibility requires the deployment ID, contract hash, stack ID hash, CloudFormation membership, logical ID/type, and exact ownership tags when the resource supports tags. Foreign or ambiguous resources are always `DO_NOT_DELETE_OWNERSHIP_UNPROVEN`.

## Approval and execution boundary

The local CLI can only produce a plan. A future executor must separately validate a fifteen-minute maximum approval bound to the exact deployment, plan hash, one-time nonce, operator subject hash, and exact action set. Even the authorization envelope remains `AUTHORIZED_BUT_NOT_EXECUTED`; it emits no AWS command.

## Cost containment and residual verification

Logs have three-day retention, DynamoDB uses on-demand capacity, Lambda reserved concurrency is one, model output is bounded, and no CloudFront or provisioned capacity is planned. Stack deletion handles ordinary resources. The DynamoDB table and two immutable Lambda versions are intentionally retained and require separate, ownership-bound data or rollback disposition; they are never silently deleted. After any future rollback, the operator must perform a read-only stack/resource inventory, reconcile it against the expected manifest, and record either zero unexpected residuals or a typed residual list.
