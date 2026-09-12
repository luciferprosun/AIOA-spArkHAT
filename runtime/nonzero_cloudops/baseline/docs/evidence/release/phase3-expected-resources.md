# Phase 3 Expected AWS Resource Manifest

Status: deterministic offline dry-run only. No AWS account was contacted and no resource was created or modified.

- Template SHA-256: `8d094f3edb0b3d1d52b716621fb0fd3179264de4dd62e4d221592082cd0de263`
- Deployment contract SHA-256: `17b8b8663fee59caaad493eb009ae9acf5c066017cbc205eaeb6b8b2ad8d4ce5`
- Intended resources: `22`
- Explicitly tagged resources: `15`
- Retained resources requiring separate disposition: `3`
- Conditional public-ingress resources: `3`
- Offline network connections: `0`
- AWS mutations: `0`
- Live receipts: `0`

This document is generated from the duplicate-safe parse of `infra/sam/template.yaml` and the canonical Phase 3 deployment contract.

## Resources

| Logical ID | Type | Purpose | Authority | Lifecycle | Ownership proof | Cleanup |
|---|---|---|---|---|---|---|
| `JudgeTokenSecret` | `AWS::SecretsManager::Secret` | Bounded judge bearer-token material | `SECRET_AUTH` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `OrchestratorAlias` | `AWS::Lambda::Alias` | Stable routing to one reviewed orchestrator version | `ROUTING` | `STACK_DELETE` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `OrchestratorDurationAlarm` | `AWS::CloudWatch::Alarm` | Orchestrator duration guardrail | `OBSERVABILITY` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `OrchestratorErrorsAlarm` | `AWS::CloudWatch::Alarm` | Orchestrator error guardrail | `OBSERVABILITY` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `OrchestratorFunction` | `AWS::Serverless::Function` | Read/plan judge API and durable HITL orchestration | `READ_PLAN` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `OrchestratorFunctionLogGroup` | `AWS::Logs::LogGroup` | Bounded orchestrator logs | `OBSERVABILITY` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `OrchestratorFunctionUrl` | `AWS::Lambda::Url` | Disabled-by-default public read-only judge ingress | `CONDITIONAL_PUBLIC_READ_INGRESS` | `CONDITIONAL_STACK_DELETE` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `OrchestratorRole` | `AWS::IAM::Role` | Read, plan, state, model, secret, and exact executor-invoke authority | `READ_PLAN` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `OrchestratorThrottlesAlarm` | `AWS::CloudWatch::Alarm` | Orchestrator throttle guardrail | `OBSERVABILITY` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `OrchestratorVersion` | `AWS::Lambda::Version` | Immutable reviewed orchestrator rollback target | `IMMUTABLE_ROLLBACK` | `RETAIN_EXPLICIT_DISPOSITION` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `RETAIN_THEN_SEPARATE_OWNERSHIP_BOUND_DISPOSITION` |
| `PublicFunctionInvokeViaUrlPermission` | `AWS::Lambda::Permission` | Conditional invocation-via-URL permission | `CONDITIONAL_PUBLIC_READ_INGRESS` | `CONDITIONAL_STACK_DELETE` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `PublicFunctionUrlInvokePermission` | `AWS::Lambda::Permission` | Conditional Function URL invocation permission | `CONDITIONAL_PUBLIC_READ_INGRESS` | `CONDITIONAL_STACK_DELETE` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `RemediationExecutorAlias` | `AWS::Lambda::Alias` | Stable routing to one reviewed executor version | `ROUTING` | `STACK_DELETE` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `RemediationExecutorDurationAlarm` | `AWS::CloudWatch::Alarm` | Executor duration guardrail | `OBSERVABILITY` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `RemediationExecutorErrorsAlarm` | `AWS::CloudWatch::Alarm` | Executor error guardrail | `OBSERVABILITY` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `RemediationExecutorFunction` | `AWS::Serverless::Function` | Private exact-plan-and-confirm remediation executor | `EXACT_PLAN_AND_CONFIRM_WRITE` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `RemediationExecutorLogGroup` | `AWS::Logs::LogGroup` | Bounded private executor logs | `OBSERVABILITY` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `RemediationExecutorRole` | `AWS::IAM::Role` | Exact private executor read and tagged-instance stop authority | `EXACT_PLAN_AND_CONFIRM_WRITE` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `RemediationExecutorThrottlesAlarm` | `AWS::CloudWatch::Alarm` | Executor throttle guardrail | `OBSERVABILITY` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |
| `RemediationExecutorVersion` | `AWS::Lambda::Version` | Immutable reviewed executor rollback target | `IMMUTABLE_ROLLBACK` | `RETAIN_EXPLICIT_DISPOSITION` | `STACK_MEMBERSHIP_AND_LOGICAL_ID` | `RETAIN_THEN_SEPARATE_OWNERSHIP_BOUND_DISPOSITION` |
| `StateTable` | `AWS::DynamoDB::Table` | Durable run, approval, idempotency, provenance, and evidence truth | `DURABLE_STATE` | `RETAIN_EXPLICIT_DISPOSITION` | `STACK_AND_EXACT_TAGS` | `RETAIN_THEN_SEPARATE_OWNERSHIP_BOUND_DISPOSITION` |
| `StateTableThrottledRequestsAlarm` | `AWS::CloudWatch::Alarm` | Durable-state throttle guardrail | `OBSERVABILITY` | `STACK_DELETE` | `STACK_AND_EXACT_TAGS` | `DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF` |

## Future request boundary

- `P3-REQ-01` — `local:sam:build`; `LOCAL`; disabled by default; binding `REVIEWED_SOURCE_AND_LOCK_HASHES`.
- `P3-REQ-02` — `s3:s3:PutObject`; `REQUIRES_EXPLICIT_MUTATION_APPROVAL`; disabled by default; binding `CONTRACT_BUCKET_HASH_AND_ARTIFACT_HASH`.
- `P3-REQ-03` — `cloudformation:cloudformation:CreateChangeSet`; `REQUIRES_EXPLICIT_MUTATION_APPROVAL`; disabled by default; binding `ACCOUNT_REGION_STACK_CONTRACT_AND_COMMIT`.
- `P3-REQ-04` — `cloudformation:cloudformation:ExecuteChangeSet`; `REQUIRES_EXPLICIT_MUTATION_APPROVAL`; disabled by default; binding `REVIEWED_CHANGE_SET_AND_FRESH_OPERATOR_APPROVAL`.

Only `P3-REQ-01` is local. Every AWS-side request remains disabled and requires a fresh, deployment-bound operator decision. Creating a change set is treated as a cloud mutation even though it does not execute the stack.
