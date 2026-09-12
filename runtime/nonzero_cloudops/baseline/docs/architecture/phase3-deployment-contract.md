# Phase 3 AWS Deployment Contract

Status: deployment-ready local policy; live deployment and verification not performed.

- Contract ID: `AIOA_PHASE3_AWS_DEPLOYMENT_CONTRACT`
- Schema version: `3`
- Canonical SHA-256: `17b8b8663fee59caaad493eb009ae9acf5c066017cbc205eaeb6b8b2ad8d4ce5`
- Classified fields: `41`
- Unresolved external inputs: `8`

This document is generated from `requirements/phase3-deployment-contract.json`. Edit the JSON source and rerun the builder; do not hand-edit this projection.
The historical `requirements/day15-deployment-contract.json` is only the frozen Day 15 G10 operator-selection policy and is not a second current architecture source.

## Classified fields

| Field | Authority class | Reviewed value |
|---|---|---|
| `release.rc_identifier` | `REQUIRED` | `"phase3-local-rc1"` |
| `release.version` | `REQUIRED` | `"0.2.0-rc.1"` |
| `release.branch` | `REQUIRED` | `"main"` |
| `release.commit_binding` | `DERIVED` | `"CURRENT_CLEAN_ORIGIN_MAIN_AT_ATTESTATION"` |
| `identity.partition` | `REQUIRED` | `"aws"` |
| `identity.target_regions` | `REQUIRED` | `["eu-central-1"]` |
| `identity.expected_account_id_sha256` | `EXTERNAL_OPERATOR_INPUT` | `<operator input required>` |
| `identity.deployment_profile` | `EXTERNAL_OPERATOR_INPUT` | `"aioa-day15-deployer"` |
| `identity.deployment_role_name` | `REQUIRED` | `"AIOANonZeroCloudOpsDay15DeploymentRole"` |
| `identity.deployment_role_arn_sha256` | `EXTERNAL_OPERATOR_INPUT` | `<operator input required>` |
| `application.stack_name` | `REQUIRED` | `"aioa-nonzero-cloudops-day15"` |
| `application.application_name` | `REQUIRED` | `"aioa-nonzero-cloudops-agent"` |
| `application.stage` | `OPTIONAL_WITH_DEFAULT` | `"hackathon"` |
| `application.resource_prefix` | `REQUIRED` | `"aioa-nonzero"` |
| `application.ownership_tags` | `REQUIRED` | `{"AIOAProject":"NonZeroCloudOps","AIOAStage":"hackathon","ManagedBy":"CloudFormation"}` |
| `infrastructure.mechanism` | `REQUIRED` | `"AWS_SAM_CLOUDFORMATION"` |
| `infrastructure.template_path` | `REQUIRED` | `"infra/sam/template.yaml"` |
| `infrastructure.artifact_object_path` | `REQUIRED` | `"day15/reviewed/aioa-lambda.zip"` |
| `infrastructure.artifact_bucket_sha256` | `EXTERNAL_OPERATOR_INPUT` | `<operator input required>` |
| `infrastructure.artifact_bucket_controls` | `REQUIRED` | `sha256:63c4d0cbf95ef8b482e8a390f81b2240c84f68ba27d4de3898577fbe24b8d1db` (structured value) |
| `infrastructure.s3_stack_managed` | `REQUIRED` | `false` |
| `infrastructure.cloudfront_enabled` | `REQUIRED` | `false` |
| `runtime.lambda_functions` | `REQUIRED` | `sha256:8486a4502f10252b060022f79de9c499bebf5b357aa808fd0832a6edddb74c3a` (structured value) |
| `runtime.api` | `REQUIRED` | `sha256:ecf290dcb86f5bf92738a8bf9cd4d585089a7ecb84b6c7f15cd4cfccaf32bece` (structured value) |
| `runtime.dynamodb` | `REQUIRED` | `sha256:f2065fa727199bc905a16ed64d5290aa900786921cd858c72e4422511355a12b` (structured value) |
| `runtime.model` | `REQUIRED` | `sha256:c903e1c089344cb6c612f3f93bcedb69039670a2913b6a30d06e9a3afd65d1c5` (structured value) |
| `runtime.iam` | `REQUIRED` | `sha256:9ddc26e1335725e8379ba428b341456921234f5c596398ee6d74aeaf439ce415` (structured value) |
| `runtime.environment_variables` | `REQUIRED` | `sha256:69fcdcee8242965c30aed6c34bb22e946353217d0dac76bb417880280116ae86` (structured value) |
| `runtime.feature_flags` | `REQUIRED` | `{"AIOA_ALLOW_LIVE_SANDBOX_STOP":"false","AIOA_EMERGENCY_EXECUTION_DISABLED":"true","AWS_MUTATIONS_ENABLED":"false","PUBLIC_INGRESS_ENABLED":"false"}` |
| `runtime.judge_secret_logical_id` | `REQUIRED` | `"JudgeTokenSecret"` |
| `runtime.judge_token_lifetime_seconds_max` | `REQUIRED` | `86400` |
| `runtime.sandbox_instance_id_sha256` | `EXTERNAL_OPERATOR_INPUT` | `<operator input required>` |
| `runtime.judge_secret_authority_confirmed` | `EXTERNAL_OPERATOR_INPUT` | `<operator input required>` |
| `runtime.cloudwatch_evidence_confirmed` | `EXTERNAL_OPERATOR_INPUT` | `<operator input required>` |
| `runtime.model_access_confirmed` | `EXTERNAL_OPERATOR_INPUT` | `<operator input required>` |
| `operations.observability` | `REQUIRED` | `sha256:555a0d120d574f301592aa689979e64f5383f2430cff3903261391f1a37a9a47` (structured value) |
| `operations.cost` | `REQUIRED` | `sha256:fcc179cb2b82d47d2f4c2756d6552b954c6a8d05c86ef8de510b2c9e52b73bd6` (structured value) |
| `operations.budget_owner_sha256` | `EXTERNAL_OPERATOR_INPUT` | `<operator input required>` |
| `operations.verification` | `REQUIRED` | `sha256:6f762938260b0163ec4ce306af72800fecc70d19575cd503c9cc095e642e9ff7` (structured value) |
| `operations.rollback_policy` | `REQUIRED` | `"OWNERSHIP_BOUND_EXPLICIT_APPROVAL_ONLY"` |
| `operations.post_deploy_endpoints` | `DERIVED` | `["/health","/ready"]` |

## Remaining operator inputs

- `EXTERNAL_OPERATOR_INPUT_REQUIRED:identity.deployment_role_arn_sha256`
- `EXTERNAL_OPERATOR_INPUT_REQUIRED:identity.expected_account_id_sha256`
- `EXTERNAL_OPERATOR_INPUT_REQUIRED:infrastructure.artifact_bucket_sha256`
- `EXTERNAL_OPERATOR_INPUT_REQUIRED:operations.budget_owner_sha256`
- `EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.cloudwatch_evidence_confirmed`
- `EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.judge_secret_authority_confirmed`
- `EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.model_access_confirmed`
- `EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.sandbox_instance_id_sha256`

Every unresolved value is a typed blocker. None may be inferred from ambient AWS configuration, guessed from resource names, or replaced by a successful local test.

## Authority and exposure boundary

The orchestrator retains read/plan authority and can invoke only the exact private executor alias. The private executor alone contains the exact `ec2:StopInstances` authority, constrained by target, region, tag, three disabled-by-default flags, durable human approval, and emergency veto. The public surface contains no approval or mutation route. Unknown capabilities remain `NEVER_AUTONOMOUS`.

## Data, lifecycle, and cost boundary

The retained on-demand DynamoDB table intentionally has no TTL because durable authority and evidence require explicit disposition. Cleanup therefore needs ownership proof and separate operator approval. Logs expire after three days, concurrency and model output are bounded, the packaging bucket is external and short-lived, and CloudFront is not part of the current architecture.
