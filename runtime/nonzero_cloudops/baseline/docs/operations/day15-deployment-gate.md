# Day 15 deployment gate and alias rollback

The Day 15 tools prepare and verify a candidate; they do not authorize deployment. No deployment,
Function URL publication, live Bedrock call, or EC2 mutation was performed while creating this
runbook.

## Local validation sequence

1. Validate the fixed ten-gate schema without reading deployment inputs:

   ```bash
   .venv/bin/python scripts/day15/run_day15_gate.py --validate-only --json
   ```

2. Validate the SAM template locally:

   ```bash
   .venv/bin/python scripts/day15/validate_template.py --json
   ```

   The command requires SAM CLI `1.165.0`, cfn-lint `1.52.1`, and AWS SAM Translator `1.111.0`,
   exactly as recorded in `requirements/day15-toolchain.json`. Then create and independently
   verify the deterministic CloudFormation rendering:

   ```bash
   .venv/bin/python scripts/day15/render_template.py --json
   .venv/bin/python scripts/day15/render_template.py --verify --json
   ```

   The renderer replaces only the two reviewed local `CodeUri` values with the frozen
   `Day15ArtifactBucketName` and `Day15ArtifactObjectKey` parameters before invoking the pinned
   translator. Its provenance binds the source template, toolchain, renderer, validator helper,
   clean commit, packaging transform, and exact rendered bytes. Structural validation alone is
   useful, but a missing or mismatched pinned tool remains `PARTIAL`, `BLOCKED`, or `FAIL`.

3. Run the explicit region, token-expiry, and configuration preflight. The expiry must be a UTC
   ISO-8601 value strictly in the future and no more than 86,400 seconds from the preflight clock.
   The command never reads `AWS_REGION`, `AWS_DEFAULT_REGION`, or a token value and never echoes the
   expiry. First run without the configuration digest to obtain the deterministic computed digest;
   that run is intentionally `BLOCKED`:

   ```bash
   .venv/bin/python scripts/day15/preflight_region.py \
     --template infra/sam/template.yaml \
     --region eu-central-1 \
     --judge-token-not-after '<reviewed-UTC-expiry>' \
     --json
   ```

   Review the computed digest, then rerun with it:

   ```bash
   .venv/bin/python scripts/day15/preflight_region.py \
     --template infra/sam/template.yaml \
     --region eu-central-1 \
     --judge-token-not-after '<reviewed-UTC-expiry>' \
     --lambda-configuration-sha256 '<reviewed-configuration-sha256>' \
     --json
   ```

   Pass that same digest as the template parameter `LambdaConfigurationSha256`. It covers both
   functions' reviewed runtime/configuration/environment and their complete referenced execution
   roles. A configuration-only template edit changes the digest even when the ZIP stays unchanged.
   Both retained Version descriptions bind it; the orchestrator Version also binds
   `JudgeTokenNotAfter`, so expiry rotation cannot silently reuse an old version.

4. Review `requirements/day15-deployment-contract.json`. It freezes region `eu-central-1`, profile
   `aioa-day15-deployer`, deployment-role leaf `AIOANonZeroCloudOpsDay15DeploymentRole`, stack
   `aioa-nonzero-cloudops-day15`, change set `day15-reviewed-release`, artifact path
   `day15/reviewed/aioa-lambda.zip`, `CAPABILITY_IAM`, and all required packaging-bucket controls:
   encryption at rest, TLS-only access, versioning, ownership controls, all four public-access
   blocks, and current/noncurrent version lifecycle expiration no later than three days. Its selected bucket and
   deployment-role ARN hashes deliberately remain null and `BLOCKED`. Private identities never
   replace those nulls in Git; the candidate-bound private receipt supplies authority at run time.
   The logical change-set name and `CAPABILITY_IAM` are frozen, but an actual change set is
   intentionally not a G10 prerequisite. No actual account, bucket, role ARN, target, or owner is
   committed.

### One-time operator authority bootstrap

Before creating the private contract, the explicitly authorized Day 15 operator workflow may run
the protected authority adapter. Run it only after fetching `origin`, committing and normally
pushing the exact reviewed tooling, and re-proving the complete local suite. The adapter itself
also rejects a dirty/non-`main` worktree, local `HEAD != origin/main`, or Phase 1 tag drift:

```bash
timeout 120s .venv/bin/python scripts/day15/g10_operator_bootstrap.py --json
```

It lists profile names internally but never prints them. An explicit `AWS_PROFILE` or
`AWS_DEFAULT_PROFILE` wins only when it names one configured profile; otherwise exactly one
non-deployment source profile must remain. The only direct AWS operations are bounded
`sts:GetCallerIdentity`, at most one explicit `sts:AssumeRole` to the existing exact
`AIOANonZeroCloudOpsDay15DeploymentRole`, and a temporary-role identity check. Credential-provider
clients inherit the same bounded SDK configuration, and endpoint overrides are rejected. The
local `aioa-day15-deployer` alias is append-only, byte-reverified, and fixes the exact role session
to 900 seconds; canonical G10 performs its later named-profile authentication. Root is forbidden.
IAM authority is never created, and temporary credentials are never persisted.
An already-exact role under a different profile name blocks as
`SOURCE_PROFILE_ALIAS_AUTHORITY_UNPROVEN` because credential-provider precedence cannot prove that
copying a cross-name profile preserves identity without another unbounded authentication call.

Identity-bearing account/role values remain only in protected local AWS configuration and the
canonical mode-`0600`, ignored private receipt at
`.aioa-private/day15-authority-bootstrap.json`; they never enter stdout or tracked files. Existing
valid receipts are preserved before reuse. The public result contains closed booleans and reason
codes only. A missing or unassumable exact role returns `BLOCKED` with
`EXACT_DEPLOYMENT_ROLE_NOT_ASSUMABLE`; that is a terminal
`DAY15_BLOCKED_ROLE` result for this package, so no sandbox/bucket/budget discovery, contract,
G10 AWS preflight, change set, or deployment may follow.

A `PASS` proves exact-role authority and the exact local alias configuration only. It does not
authorize deployment and is not a substitute for the candidate-bound private contract or
canonical G10 receipt. When a later
contract builder consumes the protected receipt, it must deliberately map
`EXPLICIT_ENVIRONMENT_PROFILE` to `EXPLICIT_AWS_PROFILE` and `UNIQUE_LOCAL_PROFILE` to
`UNIQUE_EXPLICIT_PROJECT_PROFILE`; bootstrap labels must never be copied into the contract as an
unvalidated new enum.

5. Run the G10 closure command once without a contract. It performs no AWS call and writes a
   sanitized `BLOCKED` receipt containing the exact candidate digest. The command first reruns the
   complete P0 and P1 matrices and stores their canonical results under `.aioa-private/`; use
   `--use-existing-gate-results` only when those exact results were just reviewed:

   ```bash
   .venv/bin/python scripts/day15/run_g10_closure.py --json
   ```

   An authorized operator may then copy
   `docs/operations/day15-private-contract.example.json` to
   `.aioa-private/day15-deployment-contract.json`, replace every placeholder, bind the displayed
   candidate digest, and set mode `0600`. The contract must explicitly name one profile/role,
   expected account, existing packaging bucket, stack-owned judge-secret policy, existing sandbox
   ID, exact tag/state/region, CloudWatch window, the pinned Nova profile and bounded probe choice,
   and an existing budget name plus owner type/target for USD 10/25/40 notifications. Bootstrap
   writes remain false. Do not discover a target, guess an owner, or copy values into a tracked
   file.

   Rerunning the same command constructs only the named profile session. It first verifies STS;
   then uses the fixed single-attempt, region-pinned read allowlist for S3 controls, Secrets Manager
   IAM simulation, the explicit EC2 instance, CloudWatch data, the exact six routed Nova model
   resources, at most one 32-token synthetic Nova probe, and the explicit budget subscribers. It
   never issues an AWS write or EC2 discovery query. The canonical private receipt is atomic,
   ignored, and mode `0600`; its sanitized companion is also ignored runtime evidence and contains
   only the candidate, whole-document hashes, booleans, operation names, and public-safe reason
   codes. Keeping both under `.aioa-private/` prevents the evidence output from dirtying or changing
   the commit-bound candidate. Any later tracked copy is archival only and is never accepted as
   deployment authority.

   The older `external_preflight_attestation.py` schema-v5 HMAC format and its two example JSON
   files remain available solely to validate historical Day 15 evidence. They are not accepted by
   D15-G10 as deployment authority because they can represent manually asserted booleans and do
   not bind the complete current candidate.

6. Run the complete local gate with the candidate-bound receipt pair:

   ```bash
   .venv/bin/python scripts/day15/run_day15_gate.py \
     --region eu-central-1 \
     --judge-token-not-after '<reviewed-UTC-expiry>' \
     --lambda-configuration-sha256 '<reviewed-configuration-sha256>' \
     --rendered-template '<reviewed-rendered-template>' \
     --g10-sanitized-receipt .aioa-private/day15-g10-readiness.json \
     --g10-private-receipt .aioa-private/day15-external-preflight.json \
     --json
   ```

The stable gates are D15-G01 runtime composition, G02 rendered IAM, G03 SDK retry ownership, G04
artifact reproducibility/scans, G05 retained state, G06 region, G07 versions/aliases/rollback, G08
logs/telemetry/cost controls, G09 the single read-only public surface, and G10 external
prerequisites plus token lifetime. All ten passing sets `ready_for_change_set=true`. It deliberately
leaves `ready_for_deployment=false` and `deployment_authorized=false`: the actual change set does
not exist yet and therefore cannot already have been reviewed. Missing SAM rendering,
scanner/container proof, build artifacts, or operator prerequisites stays visible as `PARTIAL` or
`BLOCKED`.

## Offline predeploy change-set review

Only after G10 passes may the authorized workflow create—but not execute—the application change
set. Normalize its actual `DescribeChangeSet` result and the digest of the processed `GetTemplate`
body into one canonical mode-`0600` export. It must include a fresh capture time, the exact two
read operations, private change-set ARN, candidate and exact rendered/processed-template hashes,
stack/change-set identity and type, deployment-role hash, every resolved parameter, and the
complete initial resource diff. The sanitized result binds the whole protected-export hash and a
hash of the change-set ARN. The first-stage parameter `PublicIngressEnabled` must be `false`.
Review it against the same G10 receipt pair and exact candidate:

```bash
.venv/bin/python scripts/day15/change_set_review.py \
  --change-set-export '<protected-normalized-change-set-export>' \
  --rendered-template '<reviewed-rendered-template>' \
  --g10-sanitized-receipt .aioa-private/day15-g10-readiness.json \
  --g10-private-receipt .aioa-private/day15-external-preflight.json \
  --output .aioa-private/day15-change-set-review.json \
  --json
```

This validator makes no AWS calls and emits only canonical sanitized evidence. Its operative output
stays ignored so it cannot invalidate the commit-bound candidate; any later tracked copy is
archival and non-authoritative. It rejects a stale
candidate or private receipt, stale preflight, edited change-set/template digest, partial or
duplicate initial diff, changed parameters, unexpected resource class, extra public surface,
non-exact IAM resource/condition/trust policy, enabled mutation control, wrong region, DynamoDB
retention/recovery drift, and provisioned concurrency. Even `PASS` has
`deployment_authorized=false`; a separate deployment coordinator must independently require Day 15
`10/10` and this exact candidate-bound review before execution.

The remaining frozen tools are AWS CLI `2.36.11`, Python `3.12.3`/x86_64, pip `26.2.1`,
pip-audit `2.10.1`, and Podman `4.9.3` with the exact Lambda image digest in the toolchain record.
The ignored local tool environments are conveniences, not evidence; the gate checks the executing
versions and regenerates the relevant proof.

## Staged public ingress

Public ingress is never enabled in the first change set. The first separately reviewed change set
must pass `PublicIngressEnabled=false`; after it completes, verify the deployed numeric versions,
both `live` aliases, configuration digest, judge expiry, all three disabled mutation flags, private
executor isolation, readiness, log retention, and alarms. These are read-only/private checks; they
do not call the model or mutation path.

Only then may a second separately reviewed change set set `PublicIngressEnabled=true`. Its policy
diff must add exactly the two conditioned permissions already frozen in the template: URL invoke
with `FunctionUrlAuthType=NONE`, and function invoke only with `InvokedViaFunctionUrl=true`. It must
add no API Gateway, direct public invoke, approval/resume route, or mutation route.

Rollback and teardown reverse exposure first: remove both public permissions and the Function URL,
verify they are absent, and only then consider aliases, functions, or the rest of the stack. The
retained table is governed by the separate disposition runbook. This document intentionally
contains no deployment command, and no change set was created or executed here.

## Alias-only rollback and reconciliation

Both `live` aliases always point to numeric retained versions. Rollback changes aliases only; it
does not rebuild code or alter the state table. Capture both previously reviewed numeric versions
before deployment.

The default command performs read-only AWS preflight calls: it confirms both named functions belong
to the explicit stack, reads both current `live` aliases, and proves both target versions still
exist. It then emits a canonical plan and SHA-256 for review:

```bash
.venv/bin/python scripts/day15/alias_rollback.py \
  --stack-name '<stack-name>' \
  --orchestrator-function-name '<orchestrator-function-name>' \
  --executor-function-name '<executor-function-name>' \
  --orchestrator-previous-version '<numeric-version>' \
  --executor-previous-version '<numeric-version>' \
  --profile '<authorized-profile>' \
  --region eu-central-1 \
  --json
```

Only after reviewing that exact plan may an authorized operator add both explicit write controls:

```bash
.venv/bin/python scripts/day15/alias_rollback.py \
  --stack-name '<stack-name>' \
  --orchestrator-function-name '<orchestrator-function-name>' \
  --executor-function-name '<executor-function-name>' \
  --orchestrator-previous-version '<numeric-version>' \
  --executor-previous-version '<numeric-version>' \
  --profile '<authorized-profile>' \
  --region eu-central-1 \
  --execute \
  --confirm-plan-sha256 '<reviewed-plan-sha256>' \
  --json
```

The tool strips ambient credential/region selectors, uses only the named profile and region, updates
only pending aliases, and re-reads both aliases. If one update succeeds and the other does not, it
returns `PARTIAL` with `ALIAS_RECONCILIATION_REQUIRED`; rerun the read-only plan, review the new
state, and explicitly execute reconciliation. No live rollback receipt exists in this repository,
and local tooling success does not claim one.
