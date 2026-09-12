# AIOA Non-Zero CloudOps — Phase 3 Deployment-Ready Local Release Candidate

Status: `DEPLOYMENT_READY_LOCAL_RC`; not deployed, not live verified, and not externally submitted.

## Preserved architecture

Phase 3 hardens the existing AWS SAM/CloudFormation path rather than adding a second deployment
system. The future stack contains the read/plan orchestrator, a separately permissioned private
remediation executor, immutable versions and aliases, a retained on-demand DynamoDB durable-truth
table, a bounded judge secret, short-retention logs, alarms, and a disabled-by-default Lambda
Function URL. The public surface has no approval or mutation route.

Authority remains split:

- `READ_ONLY` is `AUTO` inside bounded evidence and budget contracts;
- `REMEDIATION` is `PLAN_AND_CONFIRM` and reaches only the private executor after durable exact
  human authority;
- unknown capability is `NEVER_AUTONOMOUS`;
- the orchestrator has no direct EC2 write action;
- the executor has only the exact tagged-instance `ec2:StopInstances` mutation, guarded by target,
  region, tag, approval, idempotency, and three fail-closed runtime flags.

## Release proof layers

1. `requirements/phase3-deployment-contract.json` is the single classified AWS deployment contract.
   It records required, defaulted, derived, and external-operator fields without embedding raw
   identity or secret values.
2. The preflight engine executes local checks and synthetic AWS-read fixtures only. Future STS,
   account, IAM, Bedrock, quota, collision, sandbox, bucket, secret, and budget checks remain typed
   read-only interfaces; deploy approval is always a separate unexecuted check.
3. The IaC validator duplicate-safely parses `infra/sam/template.yaml`, checks topology, IAM,
   encryption, retention, tags, exposure, cost, and graph invariants, then derives all 22 resource
   intents from the template.
4. Cleanup planning requires deployment ID, stack ID hash, contract hash, CloudFormation membership,
   logical ID/type, and exact ownership tags where supported. It emits no cloud command. A future
   authorization envelope additionally requires a fresh one-time approval bound to the exact plan.
5. The post-deploy verifier runs the complete ordered chain against the local API and durable mock
   adapters. It proves approve, deny, replay rejection, restart reconciliation, and five fail-closed
   probes with no socket, provider network call, or AWS mutation. `LIVE_AWS` is disabled and no live
   adapter ships in this RC.
6. RC attestation binds the exact clean pushed commit, Git tree, deployment contract, artifact bytes,
   runtime/package versions, full-suite result, P0/P1 results, and all quality gates. Any stale SHA,
   dirty tree, origin mismatch, changed artifact, or invalid gate receipt fails closed.
7. The jury command executes approve, deny, replay, pending-approval restart recovery, terminal
   reconciliation, and five failure probes in explicit `MOCK_OFFLINE_NEVER_LIVE` mode. The final
   gate also audits every Devpost sentence against local evidence and refuses unsupported live claims.

## Local release gate

`scripts/phase3/run_local_gate.py` accepts one expected clean commit and executes the full suite once,
P0/P1, Ruff, dependency/package checks, generated-artifact checks, secret scanning, explicit socket
guards, the offline verifier, and the complete jury demo. It writes private hashed evidence under
`.local/phase3/`; generated output does not grant deployment authority. Actual RC attestation is
created only after the tested commit and the report-only closure commit are clean and synchronized to
`origin/main`.

## Lifecycle and cost

All tag-capable stack resources carry `AIOAProject=NonZeroCloudOps`, `AIOAStage=hackathon`, and
`ManagedBy=CloudFormation`. Logs retain three days, Lambda reserved concurrency is one per function,
DynamoDB is on demand, model output and judge investigations are bounded, and no CloudFront,
provisioned concurrency, or managed database cluster is planned. The DynamoDB table and two immutable
Lambda versions are intentionally retained for durable authority and rollback; they require separate
ownership-bound disposition and are never silently deleted.

## External boundary

No local PASS supplies an AWS identity, account, role, artifact bucket, sandbox binding, CloudWatch
history, judge-secret authority, Bedrock access, budget owner, reviewed change set, deploy approval,
live verification receipt, or Devpost submission. Those remain explicit external blockers. The next
safe external flow is read-only preflight, then a separately approved change set/deployment, then live
verification, receipt review, and owner submission.
