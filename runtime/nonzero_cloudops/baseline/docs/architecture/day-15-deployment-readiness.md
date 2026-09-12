# Day 15 deployment readiness handoff

```text
HANDOFF_SCOPE = DOCUMENTATION_ONLY
READY_FOR_DAY_15_IMPLEMENTATION_PACKAGE = YES
READY_FOR_DAY_15_DEPLOYMENT = NO
DEPLOY_NOW = NO
AWS_DEPLOYMENT_PERFORMED = NO
LIVE_STOPINSTANCES_CALLED = NO
AGENTCORE_ALLOWED = NO
```

Armor Phase 2 stops here. The repository has strong local runtime contracts, P0/P1 proof, a private executor skeleton, and deterministic reviewer evidence. It does not yet contain a deployable end-to-end orchestrator or judge route. Day 15 may close only the prerequisites below; it must not pull AgentCore or AU-2 forward.

## Existing, locally proven building blocks

- One primary Strands Agent with exactly five bounded tools and the pinned Nova 2 configuration in `eu-central-1`.
- Typed investigation, durable proposal/approval, idempotency, private execution, recovery, and independent verification behavior proven with fakes.
- A SAM skeleton containing a public `GET /health` Lambda, a private remediation executor, one DynamoDB table, bounded log groups, and managed-policy documents.
- Default-disabled mutation configuration and an independent emergency veto checked before both executor write boundaries.
- P0, P1, clean-clone, and reviewer-evidence gates that require no AWS credentials.

These are code and repository proofs. They are not deployment or live-event evidence.

## Blocking gaps to close before deployment

| ID | Current gap | Day 15 acceptance condition |
| --- | --- | --- |
| D15-01 | The SAM template has health and private-executor functions, but no primary-agent/orchestrator Lambda handler or environment composition. | Add one bounded orchestrator entry point that composes the existing clients, durable repository, HITL, recovery, verification, and a module/process-lifetime circuit registry without adding an agent or tool. Freeze reserved concurrency at `1` for the judge deployment and state explicitly that breaker state resets on a cold start. |
| D15-02 | There is no Function URL/minimal UI, judge schema, or authenticated approval/resume route. Caller-supplied actor/session and decision-nonce values are not identity or freshness proof. | Use the one Function URL topology below. Expose only health, readiness, and token-protected read-only judge investigation initially. Keep approval/resume unexposed until actor identity is derived from an authenticated principal and a server-issued, one-time CSRF/freshness value is durably bound and replay-tested. |
| D15-03 | The checked-in managed policies are detached because no orchestrator role exists; the live Nova compatibility spike remains authorization-blocked. | Create one orchestrator execution role with the exact rendered resources below. Prove the streaming Strands call uses only `bedrock:InvokeModelWithResponseStream` (and add `bedrock:InvokeModel` only if an observed code path requires it), binding the EU inference-profile ARN and every routed foundation-model ARN rather than `bedrock:InvokeModel*`. |
| D15-04 | The private executor performs a fresh `DescribeInstances` scope check, while its current role and P1/IAM expectations freeze remediation actions to only `StopInstances`. | Add a separate region-conditioned `ec2:DescribeInstances` statement and retain the resource/tag-scoped stop statement. Intentionally update the frozen IAM unit/P1 expectations and re-prove them; merely editing the policy will correctly make the current gate fail. |
| D15-05 | The executor constructs a default EC2 client, and the future orchestrator Lambda client would otherwise do the same. SDK transport retry can repeat `StopInstances` or a synchronous private-function invoke outside the application no-replay proof; it can also multiply application read retries. | Construct every AWS SDK client with reviewed `botocore.config.Config`; require `total_max_attempts: 1` for EC2 stop/DryRun, the orchestrator's `lambda:InvokeFunction`, and EC2/CloudWatch read clients. Regression-test actual configuration and call counts. Bound Bedrock attempts/cost separately. No environment or shared config may override these clients. |
| D15-06 | `CodeUri` points at source only. The project pins three direct runtime dependencies but has no fully resolved, hash-locked Lambda set and no explicit boto3/botocore build pin. | Produce a Python 3.12/x86_64 artifact from a resolved hash-locked runtime dependency file, record all transitive versions, scan the artifact, import every handler in a Lambda-like environment, and prove no editable/local path or undeclared library is used. |
| D15-07 | Read-side target configuration uses `SANDBOX_REGION`, `SANDBOX_TAG_KEY`, and `SANDBOX_TAG_VALUE`; the executor uses the Lambda region plus `SANDBOX_REQUIRED_TAG_KEY` and `SANDBOX_REQUIRED_TAG_VALUE`. | Select one canonical environment contract or map both sides explicitly in infrastructure, then add a test proving identical target ID, region, tag key, and tag value reach investigation, execution, and verification. |
| D15-08 | OTel libraries are pinned, but no Lambda tracer provider/exporter, extension, sampling policy, or CloudWatch/X-Ray destination is wired. | Add bounded telemetry initialization and prove run/trace/correlation attributes reach the selected backend without prompts, credentials, target IDs, or raw provider responses. AgentCore remains excluded. |
| D15-09 | The current health handler makes no dependency checks, and there is no readiness contract. | Preserve cheap `GET /health`; add a separate bounded readiness check for configuration and required non-mutating dependencies. It must fail closed and expose no account, resource, credential, or exception detail. |
| D15-10 | The state table currently has destructive stack-delete/replace defaults: no `DeletionPolicy`, `UpdateReplacePolicy`, PITR, or deletion protection is configured. | Before the first durable deployment, require and test retained/snapshotted replacement behavior, `DeletionPolicy: Retain`, `UpdateReplacePolicy: Retain`, PITR, and deletion protection. Teardown cannot delete retained evidence implicitly. |
| D15-11 | The template does not prevent deployment outside `eu-central-1`, although runtime contracts reject another region. | Add a template/preflight region guard, pass the deployment region explicitly, and test the rendered stack fails before resource creation in every other region. |
| D15-12 | The template publishes unqualified functions and has no alias/version/traffic policy, so “route to the last version” rollback is not currently possible. | Add immutable versions and stable aliases for both orchestrator and private executor; point ingress and invoke policy at reviewed qualifiers and prove rollback changes aliases without rebuilding old code. |
| D15-13 | No deployed receipt, endpoint, IAM simulation, CloudWatch trace, or judge-run evidence exists. | After implementation and authorization, create sanitized deployment proof. Keep `LIVE-EC2-01` at `NOT_YET_PROVEN` unless a separately reviewed live receipt satisfies the evidence contract. |
| D15-14 | Deployment prerequisites and artifact storage are not frozen; SAM CLI is not part of the repository environment. | Pin/document the SAM CLI and AWS CLI, deployment role/profile, Python 3.12/x86_64 builder, reviewed CloudFormation change set with IAM capability acknowledgement, and a packaging bucket/lifecycle policy. Runtime S3 remains unnecessary. |
| D15-15 | Positive HITL resume tests reuse one in-memory Agent; recovery proves envelope reconstruction but not a successful fresh-process Strands resume. | Add a cold-start test that persists the interrupt, destroys the runtime, creates a fresh Agent, authenticates and resumes the exact proposal plus server-issued freshness binding, and proves no duplicate execution. Until green, expose no approval route and keep mutation unavailable. |
| D15-16 | Verification defaults to three observations at one-second intervals, which is suitable for fakes but not credible proof of an asynchronous EC2 stop; the workflow elapsed-time budget defaults to 60 seconds. | Select and test a realistic but finite live verification window, align it with Lambda and workflow budgets, and use an explicit multi-request status/poll or recovery design rather than holding an ingress request indefinitely. Timeout remains non-success and reconciliation remains read-only with no replay. |
| D15-17 | A new run requires budget counters, but no deployment-owned turn/token/elapsed values exist and the schema's upper bounds are far above a safe public demo. | Freeze server-owned judge defaults at `max_turns=8`, `max_tokens=8192`, and `max_elapsed_seconds=60`, prove monotonic durable enforcement, and reject every caller/model attempt to set or raise them. Reconcile D15-16 through a separate bounded status/recovery request rather than silently extending a run. |
| D15-18 | No Function URL resource-policy contract exists, so public permission could be missing or accidentally permit direct Lambda invocation outside the one public URL. | Render and test exactly two public allow statements on the orchestrator alias: `lambda:InvokeFunctionUrl` conditioned on `lambda:FunctionUrlAuthType=NONE`, and `lambda:InvokeFunction` conditioned on `Bool lambda:InvokedViaFunctionUrl=true`. Reject every unconditional public invoke and remove both statements explicitly during teardown. |

Until D15-01 through D15-18 are closed and locally re-proven, `READY_FOR_DAY_15_DEPLOYMENT` remains `NO`. The next implementation package is ready to begin; the stack is not ready to deploy.

## Required Day 15 resource shape

The selected Day 15 topology has one public surface: a Function URL on the orchestrator Lambda. It serves the minimal same-origin UI, liveness/readiness, and typed judge APIs. Day 15 must retire the separate public `HealthHttpApi`/health Lambda only after the existing zero-dependency health contract is routed through and equivalently tested on the orchestrator. Do not add API Gateway in parallel.

The Function URL uses `AuthType: NONE` only so public liveness is reachable. Every non-health route requires a server-validated, bounded-lifetime judge token sent only in an authorization header and stored/rotated as one dedicated secret, same-origin requests, strict security headers, no wildcard CORS, request-size/schema limits, low reserved concurrency, and a server-owned durable request/spend counter. The first deployment exposes no approval or mutation route. A future approval route requires an authenticated principal whose server-derived identity is bound to the durable decision; both actor identity and a server-issued one-time freshness/CSRF value must not be accepted as caller assertions.

The smallest intended stack is:

1. One Python 3.12/x86_64 orchestrator Lambda for the existing single Agent, with bounded memory/timeout and reserved concurrency `1`. Its process-lifetime circuit registry is shared by warm requests but makes no cold-start or fleet-wide suppression claim.
2. One orchestrator Lambda Function URL and minimal same-origin UI using the route/auth contract above; no API Gateway and no second public function.
3. The existing private remediation-executor Lambda with reserved concurrency `1`; it has no public event or URL.
4. The existing DynamoDB state table using `PAY_PER_REQUEST`, encryption, and a reviewed retention/recovery policy.
5. One dedicated judge-token secret and orchestrator read permission for only that secret; no token is returned by health, logs, traces, or evidence.
6. Explicit CloudWatch log groups for every Lambda with three-day retention, bounded alarms, and the selected non-AgentCore OTel/X-Ray export path.
7. Budget notifications at USD 10, USD 25, and USD 40. The current repository records these thresholds but creates no AWS Budget resource, so ownership and notification targets remain a prerequisite.
8. A deployment-only SAM artifact bucket with encryption, public access blocked, and short lifecycle expiration if zip packaging is selected. It is not a runtime data dependency.

No runtime S3 bucket, queue, scheduler, browser tool, shell tool, second agent, or AgentCore resource is required by the current design. Add none by default.

## Operator and build prerequisites

- A pinned SAM CLI and AWS CLI, Git, and a Python 3.12/x86_64-compatible build environment.
- A named deployment role/profile scoped to the reviewed stack and `eu-central-1`; no personal long-lived access key in files or environment output.
- A pre-existing encrypted SAM artifact bucket with public access blocked and short lifecycle expiration, or a documented equivalent managed packaging path.
- CloudFormation change-set review with the IAM capability acknowledgement required by the rendered template. The region guard, template validation, artifact hash, dependency version report, and policy diff must pass before execution.
- The account's Nova 2 access/profile compatibility must be verified through a bounded, non-mutation preflight only after authorization; the prior local spike does not prove live model access.

## Environment contract

Values are non-secret unless explicitly routed through a future secret store. No credential belongs in an environment variable or template.

### Orchestrator

| Name | Required safe value/bound |
| --- | --- |
| `APP_STAGE` | Reviewed lowercase deployment stage. |
| `BEDROCK_MODEL_ID` | `eu.amazon.nova-2-lite-v1:0`. |
| `BEDROCK_REGION` | `eu-central-1`. |
| `MODEL_MAX_OUTPUT_TOKENS` | At most `1024`. |
| `STATE_TABLE_NAME` | Deployed state-table reference. |
| `SANDBOX_INSTANCE_ID` | One preconfigured sandbox identifier; never accepted from model text as authority. |
| `SANDBOX_REGION` | `eu-central-1`. |
| `SANDBOX_TAG_KEY` / `SANDBOX_TAG_VALUE` | `AIOACloudOpsSandbox` / `true`, after D15-07 normalizes the contract. |
| `IDLE_OBSERVATION_WINDOW_MINUTES` | Default `60`, bounded by the current typed settings. |
| `IDLE_METRIC_PERIOD_SECONDS` | Default `300`. |
| `IDLE_MINIMUM_DATAPOINTS` | Default `6`. |
| `IDLE_CPU_THRESHOLD_PERCENT` | Demo default `10.0`; not represented as an AWS recommendation. |
| `PRIVATE_REMEDIATION_FUNCTION_NAME` | Proposed new exact private-executor alias/name binding; Day 15 must add and test its loader because current composition accepts only a constructor argument. |
| `JUDGE_TOKEN_SECRET_ARN` | Proposed new exact reference to the one token secret; the environment contains the ARN, never the token value. |

### Private executor

| Name | Required safe value/bound |
| --- | --- |
| `SANDBOX_INSTANCE_ID` | Same target as the orchestrator. |
| `SANDBOX_REQUIRED_TAG_KEY` / `SANDBOX_REQUIRED_TAG_VALUE` | Same tag proof as the orchestrator until D15-07 unifies names. |
| `AWS_MUTATIONS_ENABLED` | `false`. |
| `AIOA_ALLOW_LIVE_SANDBOX_STOP` | `false`. |
| `AIOA_EMERGENCY_EXECUTION_DISABLED` | `true`; missing, malformed, or unavailable also denies writes. |

Lambda supplies its AWS region; the code additionally constrains it to `eu-central-1`. Enabling either positive mutation flag does not grant proposal approval. A future live demonstration requires separate operator authorization and a deliberate, reversible change of all three controls; it is outside this handoff.

The two positive mutation variables are authoritative only in the private executor today. Day 15 may add an orchestrator-side defense-in-depth denial, but it must be implemented and tested rather than inferred from setting otherwise-unused environment values.

## Pre-existing sandbox prerequisite

The stack does not create or own the target instance. Before any live candidate is considered, one operator-selected instance must already exist in the same account and `eu-central-1`, be `running`, EBS-backed, carry exactly `AIOACloudOpsSandbox=true`, and provide at least six valid CPU datapoints across the configured 60-minute window. The instance identifier remains an explicit stack input with no discovery fallback. Stack teardown never starts, terminates, retags, or deletes this external instance; any later restart is operator-owned, and stopped EBS volumes or attached network resources may continue to incur cost.

## IAM boundary

### Orchestrator role

- CloudWatch Logs delivery only to its own log group.
- `bedrock:InvokeModelWithResponseStream` for the observed streaming Strands path, scoped to the exact EU inference-profile ARN and every foundation-model ARN to which that profile can route, with an inference-profile condition where supported. Add `bedrock:InvokeModel` only if a captured, tested non-streaming path requires it; never use `bedrock:InvokeModel*` or all-model resources.
- `ec2:DescribeInstances` and `cloudwatch:GetMetricStatistics`, constrained to `eu-central-1`; these APIs require action-level rather than useful instance-resource scoping, so application target/tag checks remain mandatory.
- `dynamodb:GetItem`, `dynamodb:PutItem`, and `dynamodb:UpdateItem` only on the state table. Add no scan/delete action. Any future query/transaction action requires a new proof gate.
- `lambda:InvokeFunction` only for the private executor.
- `secretsmanager:GetSecretValue` only for the dedicated judge-token secret, with no list/write permission.
- The exact telemetry write actions needed by the selected exporter, and no observability read/admin actions.
- No `ec2:StopInstances` or other direct mutation action.

### Private-executor role

- CloudWatch Logs delivery only to its own log group.
- Region-bounded `ec2:DescribeInstances` for the mandatory fresh target/state/tag check.
- `ec2:StopInstances` only on the configured instance ARN with the required sandbox-resource tag and region condition.
- No DynamoDB, Bedrock, broad Lambda invoke, start, terminate, reboot, tag, or general EC2 write permission.

### Health role

- Log delivery only. `/health` has no AWS client and receives no mutation authority.

Before deployment, render the SAM/CloudFormation template and fail review if policy substitution introduces wildcard write authority, an unattached managed policy, a second public mutation path, or a broader trust principal. The public Function URL policy must contain only the two D15-18 statements: URL invocation bound to `AuthType: NONE`, plus function invocation bound by `lambda:InvokedViaFunctionUrl=true`.

## Health, readiness, and judge paths

- `GET /health`: keep the existing deterministic response (`service`, `stage`, `status`) and zero dependency calls.
- Readiness: validate handler/package import, canonical configuration, state-table access, and required read dependencies with finite timeouts. Report only typed component status; never echo identifiers or provider exceptions. It must not invoke the model or executor mutation.
- Judge read-only path: execute the configured-instance investigation, preserve run/trace/correlation IDs, and return typed evidence or an explicit ambiguous/dependency failure. It must not accept a different resource as authority.
- Approval/resume path: do not expose it in the initial Day 15 deployment. A later route requires the D15-02 authenticated principal and server-issued one-time binding plus the D15-15 fresh-process resume proof; the current caller-supplied nonce is not a CSRF/freshness control.
- A live-stop judge path is a separate later authorization boundary, not a Day 15 readiness prerequisite.

## Cost and operational gates

- Keep `eu-central-1`, Nova 2 Lite, temperature at the model-supported minimum, and the `1024` output-token cap.
- Keep DynamoDB on-demand billing, three-day log retention, finite Lambda timeout/memory, and low reserved concurrency; add throttling for any public ingress.
- Install budget notifications before public model access. Alarm on Lambda errors/throttles/duration, DynamoDB throttling, and bounded application failure metrics without logging sensitive payloads.
- Use orchestrator reserved concurrency `1` and a module/process-lifetime shared circuit registry. It suppresses repeated calls only within one warm process, resets on cold start, and provides no fleet-wide guarantee. Durable/hybrid state is a separately reviewed change and must not use workflow/approval truth.

## Deployment entry gate

Day 15 implementation may proceed to a change set only after:

1. D15-01 through D15-18 are closed in code and tests.
2. The complete suite, P0, P1, evidence build/validation, and clean-clone proof pass from the candidate commit.
3. A reproducible Lambda artifact imports all handlers and contains the exact pinned dependencies.
4. Rendered IAM shows the role separation above and no unreviewed action.
5. The private executor's authoritative safe defaults are `AWS_MUTATIONS_ENABLED=false`, `AIOA_ALLOW_LIVE_SANDBOX_STOP=false`, and `AIOA_EMERGENCY_EXECUTION_DISABLED=true`.
6. The Phase 1 tag, prior-art anchors, one-agent/five-tool topology, model, region, and SDK pin remain unchanged.
7. The proposed change set is reviewed before execution. No command in this document performs deployment.

## Rollback and teardown

Rollback triggers include failed health/readiness, permission drift, unexpected public access, missing trace continuity, budget alarm, ambiguous durable state, any P0/P1/evidence failure, or an emergency-veto read failure.

Rollback order:

1. Block new public ingress and new orchestrator-to-executor invokes first.
2. Explicitly set `AIOA_EMERGENCY_EXECUTION_DISABLED=true`, `AWS_MUTATIONS_ENABLED=false`, and `AIOA_ALLOW_LIVE_SANDBOX_STOP=false`. A Lambda environment update is not instantaneous authority over an invocation already running.
3. Reconcile every in-flight or ambiguous action read-only; never replay it. Preserve durable state and sanitized logs required for that decision.
4. After D15-12 exists, move both orchestrator and executor aliases to their last proven immutable versions.
5. Re-run health and the public-safe proof set against the rollback versions before reopening any read-only ingress.

The current unmodified template would delete its table during stack deletion or replacement; do not deploy it with durable evidence. After D15-10 makes retention mandatory, teardown first deletes the Function URL and explicitly removes both D15-18 public permission statements, then removes functions, roles/policies, logs, and the stack while the retained table follows a separate evidence disposition. Confirm no orphan Function URL permission, Lambda, log group, alarm, artifact, secret, or budget notification remains. The external sandbox instance is never stack-deleted, restarted, terminated, or untagged.

## Next boundary

The next package is Day 15 stable deployment implementation: orchestrator Lambda, one bounded Function URL/minimal UI, CloudWatch/OTel, readiness, and a judge test path. AgentCore remains optional Day 16 work and is not approved by this handoff.
