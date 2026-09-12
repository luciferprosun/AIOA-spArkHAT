# Phase 3 Gate — Deployment-Ready Local Release Candidate

## Mandatory report

```text
PHASE = 3
STEP = DEPLOYMENT_READY_LOCAL_RELEASE_CANDIDATE
REPO = /media/l/LSC_DATA/AWS_HACKATHON/AIOA-NonZero-CloudOps-Agent
BRANCH = main
HEAD_BEFORE = 5dee329b1c874cbd954dcfc56c23b7504b7c1cad
HEAD_AFTER = REPORT_ONLY_COMMIT_RECORDED_IN_FINAL_HANDOFF_AND_PRIVATE_RC_ATTESTATION
ORIGIN_MAIN = MUST_EQUAL_HEAD_AFTER_BEFORE_RC_ATTESTATION
WORKTREE_CLEAN = YES_AT_FULLY_TESTED_HEAD; REQUIRED_AFTER_REPORT_COMMIT
LOCAL_PHASE3_GATE = PASS
FULL_TESTS = PASS; 1291 passed; 0 failed; 0 errors; 0 skipped; JUnit time 1247.866 seconds
P0 = PASS; 15/15 gates; 136 proof tests; 0 skipped
P1 = PASS; 6/6 gates; 93 proof tests; 0 skipped
RUFF = PASS
PIP_CHECK = PASS
GIT_DIFF_CHECK = PASS
SECRET_SCAN = PASS; 332 files; 0 findings; no secret values emitted
NETWORK_CONNECTIONS_DURING_OFFLINE_DEMOS = 0
AWS_MUTATIONS = 0
LIVE_RECEIPTS = 0
DEPLOYMENT_CONTRACT = PASS; schema 3; 41 classified fields; 8 unresolved operator inputs; sha256:17b8b8663fee59caaad493eb009ae9acf5c066017cbc205eaeb6b8b2ad8d4ce5
PREFLIGHT_ENGINE = PASS_IMPLEMENTATION; 16 typed checks; LOCAL and FIXTURE only; live checks NOT_RUN_EXTERNAL
IAC_DRY_RUN = PASS_OFFLINE; AWS SAM/CloudFormation; 22 resources; 15 tagged; 3 retained; 3 conditional public; 0 network; 0 AWS mutations
ROLLBACK_CONTRACT = PASS_PLAN_ONLY; 22 ownership-bound rules; execution disabled; no cloud commands emitted
POST_DEPLOY_VERIFIER = PASS_OFFLINE; 11/11 ordered steps; 5/5 fail-closed probes; receipt sha256:24ee3b4a622f2353ca4b9a277d8d2036c4dcdf091ae99d36d16b7bac923054e1
RC_ATTESTATION = PASS_IMPLEMENTATION_AND_TESTS; FINAL PRIVATE RECEIPT REQUIRES CLEAN PUSHED REPORT COMMIT
DEMO_APPROVE = PASS; SUCCESS_WITH_EVIDENCE; exactly 1 protected mock mutation; 0 external connections
DEMO_DENY = PASS; DENIED_BY_HUMAN; 0 mutations; receipt absent; verification claim absent
REPLAY_PROTECTION = PASS; replay rejected; mutation delta 0
RECOVERY = PASS; PENDING_APPROVAL recovered after restart; terminal receipt reconciled; 0 second mutation
DEVPOST_CLAIMS_AUDITED = PASS; 76/76 sentences; 8 evidence-map rows; 6 explicit live placeholders; 0 unsupported claims; live_receipts=0
REPORT_PATH = docs/reports/phase3-local-release-candidate-gate-2026-08-27.md
COMMITS = 10 tested implementation commits plus this report-only closure commit; exact list below
PUSH_STATUS = PERFORMED_ONLY_AFTER_THIS REPORT IS COMMITTED; FINAL RESULT RECORDED IN HANDOFF AND PRIVATE ATTESTATION
EXTERNAL_BLOCKERS = 8 private operator bindings; authorized live AWS deployment; live post-deploy verification; Devpost owner submission
NEXT_OPERATOR_ACTIONS = AUTHORIZED READ-ONLY PREFLIGHT ONLY; review receipt; request separate approval for any change set or deployment
```

`HEAD_AFTER` cannot truthfully be embedded in the commit that creates this report: changing the
report changes the Git tree and therefore the commit SHA. The exact report-commit SHA, matching
`origin/main`, clean-state proof, and attestation SHA are consequently recorded by the final handoff
and the ignored mode-0600 `.local/phase3/rc-attestation.json`. The attestation explicitly permits
only this report as the delta after the fully tested commit.

## 1. What changed

Phase 3 extends the canonical Local-2 architecture without adding a competing deployment path. The
tested implementation delta contains 68 tracked files, 15,513 insertions, and 144 deletions relative
to `HEAD_BEFORE`:

- one schema-validated AWS deployment contract and deterministic human-readable projection;
- a 16-check, redacted, hashed preflight engine with stable exit codes and explicit local, future
  read-only AWS, and mutation-approval classifications;
- static/offline validation of the actual `infra/sam/template.yaml` path plus a 22-resource expected
  manifest;
- an ownership- and provenance-bound rollback/cleanup planner that cannot emit cloud commands;
- a complete offline post-deploy verification chain with approve, deny, replay, recovery, and five
  fail-closed probes;
- exact-commit RC metadata and verification tied to Git, contract, artifacts, package/runtime, and
  executed gate evidence;
- a hardened sub-five-minute jury command in explicit `MOCK_OFFLINE_NEVER_LIVE` mode;
- a sentence-level Devpost audit and consistent `AIOA Non-Zero CloudOps` naming;
- an offline-buildable `0.2.0rc1` wheel contract, a project secret scanner, negative tests, and the
  complete Phase 3 gate runner.

The ten fully tested commits are:

```text
40b5d359651bff989946279436eaeb831cdc7342 feat(release): freeze Phase 3 deployment contract
6862cbbfa157d4aba603f3b4d3cec5cbf9270e9a feat(release): add offline-safe deployment preflight
c16f6829e8b258af86523b0b1d61e34586702b63 feat(release): add offline IaC resource manifest
43b0ae75f5d9b4216d8838515ad471d57e8b5a13 feat(release): add ownership-bound cleanup planning
9d29c0db2999a4b97bad3b4323d722c45f8019ef feat(release): add offline post-deploy verifier
1b3e9ba3ac8e0d6bca3e971cde1322b598607b22 feat(release): add exact-commit RC attestation
4ac9d631a75bf9d645229da074f6abe543267f4b feat(release): harden Phase 3 jury and local gate
ebc93c2d0b3a38be3779d3a3dbffdf8b59870bbb fix(release): align change-set review with ownership tags
5ac15d30a604434713490d77edb573d14a8f1dcd fix(build): include offline wheel backend in dev extra
c92921b8c3254dd7e2e6d4233edb7810d0cd012a docs(evidence): reanchor Phase 3 package contract
```

The first complete Phase 3 run exposed two real regressions rather than being waived. Three new IAM
ownership tags were absent from the historical change-set-review expectation; the exact ordered tags
and negative tests were added. The package proof then showed that a fresh PEP 517 build could not
rely on an undeclared local backend; the bounded setuptools build dependency was added. A final clean
gate was run only after both corrections.

## 2. Exact gate evidence

The single complete closure command was run against clean commit
`c92921b8c3254dd7e2e6d4233edb7810d0cd012a`:

```bash
.venv/bin/python scripts/phase3/run_local_gate.py \
  --expected-head c92921b8c3254dd7e2e6d4233edb7810d0cd012a
```

It returned `PASS`. Its private summary is `.local/phase3/local-gate-run.json`; the executed-evidence
receipt is `.local/phase3/local-gate-evidence.json` with SHA-256
`a64de30639bd84528c1fd8500aaf9fc1e084f13655afc54f0d6d6148dc4d7285`.

| Gate | Exact result | Captured output SHA-256 |
|---|---|---|
| Full repository suite | 1291 passed, 0 skipped; JUnit 1247.866 s | `f3fdf2a2828edd4f045ca5fe894e413169c607478aea2f13fafe97a4c87c1a8d` |
| P0 | 15/15, 136 proof tests, 0 skipped | `cd01cafba8d2268b0df4064738e23a5bf0eb4de5b6e01320224079e03cfe97fd` |
| P1 | 6/6, 93 proof tests, 0 skipped | `7c4bd4dbf501a67dcf87c279ff80b8779ecc842ee2fcd747fadf07f9808226f6` |
| Ruff | `All checks passed!` | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| pip check | `No broken requirements found.` | `9261363b733079a641c2e4cc9bc46ffa1d8336945a87f807b6cf68847dbc9b09` |
| Git diff check | empty output, exit 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Secret scan | 332 files, 0 findings, 35 reviewed synthetic identifiers | `5686c93490b4ed48dd58b88d9f8059910d4a116d312947350471e75dddb888ae` |
| Package build | `aioa_nonzero_cloudops_agent-0.2.0rc1-py3-none-any.whl` | `e82674572964805b1d3d2072ce4bf07b17b8fb733a0052f1bf07a0b6a8f8ae13` |
| Deployment contract | schema/projections current; 8 blockers | `893277a453cd3f4630a7f621053ee849ad448dd2f0fddbcf5bb8f991510da486` |
| IaC dry run | 22 resources; 0 network; 0 AWS mutation | `1464bcc62de43cd4a4f6c85200adc023264edc6c0ddd6c4ef10dc97a850184ed` |
| Offline socket guard | 5/5 focused proofs | `8b247319e11a2ef86cb1299f0a6065c718c6bf3676532879f8c8aa3d805e84f7` |
| Generated artifacts | 6/6 builders/validators passed | hashes retained in the private gate summary |
| Offline verifier | `PASS_OFFLINE`, 11 steps, 5 probes | `c743bd8da42b0d8ba96b5e8eda664d5181ec85a6ed761e7173bcecf70e32f0ff` |
| Jury demo | `PASS`, duration 1.096 s, below 300 s | `a1e64ece235f684c22faa813bf3455e0123ccf404268e3fabc0ecf1504a269e5` |

The built wheel is 275,166 bytes with artifact SHA-256
`689d00cc2cbc0ec1852fff84e8d5da47e2c453f0634ee7ed755a8fdc67270833`.
All 14 required attestation quality labels are `PASS`: approve, deny, contract, generated artifacts,
Git diff, IaC, offline network guard, package build, pip check, recovery, replay protection, Ruff,
secret scan, and verifier chain.

The expected-resource receipt records 22 resources, 15 tag-capable resources with all three ownership
tags, three retained resources, three disabled-by-default conditional public resources, 11 static
checks, zero network connections, zero AWS mutations, and zero live receipts. The cleanup projection
contains one rule for each of the same 22 resources and leaves the retained DynamoDB table and two
Lambda versions pending separate disposition.

The jury path reached `SUCCESS_WITH_EVIDENCE` with exactly one local mock mutation only after durable
human approval and independent read-back. Denial reached `DENIED_BY_HUMAN` with no receipt or
verification claim. Replaying altered authority was rejected with `LOCAL_APPROVAL_REPLAY_CONFLICT`
and mutation delta zero. Restart recovery reconstructed `PENDING_APPROVAL`; terminal reconciliation
matched the durable receipt without a second mutation. The demo and verifier opened zero external
sockets, made zero provider calls, made zero AWS mutations, and created zero live receipts.

The Devpost audit covered all 76 sentences, mapped eight evidence rows, preserved six explicit
future-live placeholders, and found zero unsupported claims. Its receipt SHA-256 is
`ef7327bda017043c9eeaac91bcd6bfe150061bcb52857348d9365709327ec8a9`.
The reviewer manifest remains deterministic at 28 claims and validates with `live_receipts=0`.

## Preflight state at the tested commit

These commands were run without AWS credentials or network calls before the report push:

```bash
.venv/bin/python scripts/phase3/run_preflight.py \
  --expected-head c92921b8c3254dd7e2e6d4233edb7810d0cd012a \
  --mode local \
  --output .local/phase3/preflight-local-tested-head.json \
  --json

.venv/bin/python scripts/phase3/run_preflight.py \
  --expected-head c92921b8c3254dd7e2e6d4233edb7810d0cd012a \
  --mode fixture \
  --fixture tests/fixtures/phase3/aws-preflight-pass.json \
  --output .local/phase3/preflight-fixture-tested-head.json \
  --json
```

Both correctly returned `FAIL` at `P3-PF-003/ORIGIN_MAIN_MISMATCH`, because the safe implementation
commits had deliberately not yet been pushed. Local mode otherwise passed the four executable local
checks and marked ten future AWS reads plus deployment approval `NOT_RUN_EXTERNAL`. Fixture mode
passed the other 14 checks and left only deployment approval `NOT_RUN_EXTERNAL`. After this report is
committed and pushed, both commands must be repeated against the final HEAD. The required truthful
terminal state is `BLOCKED_EXTERNAL`: synchronized local checks pass, fixture checks pass, and no
successful local check pretends to supply live AWS evidence or deploy approval.

## 3. Residual risks and exact blockers

No live AWS identity, account, role, resource, quota, model, secret, CloudWatch, bucket, budget, or
change set was queried or proven. The eight private deployment-contract inputs remain:

```text
EXTERNAL_OPERATOR_INPUT_REQUIRED:identity.deployment_role_arn_sha256
EXTERNAL_OPERATOR_INPUT_REQUIRED:identity.expected_account_id_sha256
EXTERNAL_OPERATOR_INPUT_REQUIRED:infrastructure.artifact_bucket_sha256
EXTERNAL_OPERATOR_INPUT_REQUIRED:operations.budget_owner_sha256
EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.cloudwatch_evidence_confirmed
EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.judge_secret_authority_confirmed
EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.model_access_confirmed
EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.sandbox_instance_id_sha256
```

The final attestation also retains
`AUTHORIZED_LIVE_AWS_DEPLOYMENT_REQUIRED`,
`LIVE_POST_DEPLOY_VERIFICATION_REQUIRED`, and
`DEVPOST_OWNER_SUBMISSION_REQUIRED`.

The official AWS SAM CLI was not available locally. Phase 3 therefore proves duplicate-safe parsing,
schema and semantic invariants, exact IAM/resource graph, local package construction, and zero-network
request fixtures, but it does not claim service-side CloudFormation transform/validation or an actual
change-set diff. The Phase 3 preflight and verifier deliberately ship no enabled live adapter. The P1
clean-clone proof may contact the public Python package index to test a fresh declared dependency
installation; that is not an AWS or demo connection and does not prove future package-index
availability. No public endpoint, live Bedrock call, live EC2 remediation, production deployment,
live receipt, video upload, or Devpost submission is claimed.

## 4. Exact later commands for an authorized read-only preflight

First synchronize and verify the exact candidate. These commands do not contact AWS:

```bash
cd /media/l/LSC_DATA/AWS_HACKATHON/AIOA-NonZero-CloudOps-Agent
git fetch origin
git switch main
git pull --ff-only origin main
FINAL_SHA="$(git rev-parse HEAD)"
test "$FINAL_SHA" = "$(git rev-parse origin/main)"
test -z "$(git status --porcelain)"

.venv/bin/python scripts/phase3/run_preflight.py \
  --expected-head "$FINAL_SHA" \
  --mode local \
  --output .local/phase3/preflight-local-final.json \
  --json

.venv/bin/python scripts/phase3/run_preflight.py \
  --expected-head "$FINAL_SHA" \
  --mode fixture \
  --fixture tests/fixtures/phase3/aws-preflight-pass.json \
  --output .local/phase3/preflight-fixture-final.json \
  --json

.venv/bin/python scripts/phase3/attest_release.py \
  --expected-head "$FINAL_SHA" \
  --verify
```

Only an explicitly authorized operator may then establish the existing deployment-role identity.
This bootstrap performs bounded STS authentication and may append the reviewed local profile alias;
it creates no IAM role and makes no AWS resource mutation, but it is not an ambient-credential probe:

```bash
cd /media/l/LSC_DATA/AWS_HACKATHON/AIOA-NonZero-CloudOps-Agent
umask 077
timeout 120s .venv/bin/python scripts/day15/g10_operator_bootstrap.py --json
```

With `.aioa-private/day15-deployment-contract.json` populated by the operator from the reviewed
example, bound to the displayed candidate digest, and mode `0600`, the existing G10 coordinator is
the exact live read-only AWS preflight entry point:

```bash
timeout 1800s .venv/bin/python scripts/day15/run_g10_closure.py \
  --private-contract .aioa-private/day15-deployment-contract.json \
  --private-receipt .aioa-private/day15-external-preflight.json \
  --sanitized-receipt .aioa-private/day15-g10-readiness.json \
  --json
```

G10 is candidate-bound, region-pinned, single-attempt, allowlisted, redacted, and records an empty
AWS write ledger. Depending on the operator's private contract it may make one explicitly selected,
bounded Nova access probe, which can incur usage cost even though it does not mutate resources. Stop
after reviewing the private and sanitized receipts. A read-only PASS authorizes neither a change set
nor deployment.

## 5. Mutating commands that MUST NOT run without explicit approval

The following command families were not run in Phase 3 and must remain unexecuted until the exact
candidate, account, role, preflight receipt, change set, rollback plan, budget owner, and fresh
operator approval are independently bound and reviewed:

```text
sam package ...                         # uploads an artifact when an S3 bucket is supplied
sam deploy ...                          # creates or updates live stack resources
aws s3 cp ...                           # writes the deployment artifact to live S3
aws cloudformation create-change-set ...
aws cloudformation execute-change-set ...
aws cloudformation update-stack ...
aws cloudformation delete-stack ...
aws secretsmanager create-secret ...
aws secretsmanager put-secret-value ...
aws ec2 stop-instances ...
.venv/bin/python scripts/day15/alias_rollback.py ... --execute ...
```

Creating a change set is itself a live AWS mutation even when execution is deferred. Cleanup and
rollback are also mutations; ownership proof and a plan-only local PASS never authorize deletion.
No generic cleanup executor or live Phase 3 verifier is shipped by this candidate.

## 6. Smallest safe next phase

The next phase should be exactly `PHASE4_AUTHORIZED_READ_ONLY_PREFLIGHT`, not deployment. Its scope is
to bind the final pushed SHA to the eight private inputs, run only the reviewed G10 read allowlist,
capture protected and sanitized receipts with an empty write ledger, and stop for human review. If
and only if that phase passes, open a separate `PHASE5_EXPLICIT_CHANGE_SET_REVIEW` with new approval.
Actual deployment, post-deploy live verification, public-ingress staging, cleanup, and Devpost owner
submission remain later, separately authorized boundaries.
