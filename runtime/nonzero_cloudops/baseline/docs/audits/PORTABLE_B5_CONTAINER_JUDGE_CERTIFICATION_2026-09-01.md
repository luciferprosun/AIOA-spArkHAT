# Portable B5 container judge certification

Date: 2026-09-01
Phase: B5, clean-clone container judge flows
Baseline commit: `d18f945a1484a1255339a3b4bcb1560c58d06d9b`
Checked-in status: `PRECOMMIT_QUALIFICATION_PASS_EXACT_COMMIT_ACCEPTANCE_REQUIRED`

## Outcome

The container judge path is implemented as one installed package module and one host-side
certification gate. It reuses the existing Strands and Non-Zero implementation; it does not add an
agent loop, execution authority, provider adapter, or evidence schema.

The pre-commit qualification image passed two fresh `run --rm` invocations with no network, shared
state, bind mount, volume, port publication, credential inheritance, AWS call, or AWS mutation. Each
invocation proved:

```text
APPROVED_FINAL_STATE=SUCCESS_WITH_EVIDENCE
APPROVED_MUTATIONS_BEFORE_DECISION=0
APPROVED_MOCK_MUTATIONS=1
DENIED_FINAL_STATE=DENIED_BY_HUMAN
DENIED_MOCK_MUTATIONS=0
PENDING_APPROVAL_RECOVERED=true
RECOVERY_RECONCILED=true
RECOVERY_MOCK_MUTATIONS=0
REPLAY_REJECTED=true
REPLAY_MUTATION_DELTA=0
RESOURCE_BINDING_TAMPER=REJECTED_FAIL_CLOSED
EXTERNAL_NETWORK_CONNECTIONS=0
PROVIDER_NETWORK_CALLS=0
AWS_CALLS=0
AWS_MUTATIONS=0
```

Both deterministic portable receipts had SHA-256
`f365b07702e43c3848b3470453910b2239d640e8e9ec22a917790a702c110ba3`. The local aggregate gate
receipt had SHA-256 `4bbe17f1ef358cc84295f08eff88b7d635a9746523e9c92eec41a70f1c4d73d9`.
These are local mock/offline receipts, not live-cloud evidence.

## Image and runtime boundary

The qualified image was Linux/amd64, declared user `aioa`, MIT-labelled, read-only at runtime, and
configured with `python -m aioa_cloudops_agent.portable_server` as its entrypoint. The local rootless
engine has a single UID/GID mapping and cannot directly translate image UID/GID 65532. That engine
limitation was not represented as a successful default-user run.

Instead, the exact qualified image root filesystem was executed through a nested OCI user namespace
and a private receipt bound to the image ID, image digest, and baseline source label. It proved:

```text
EFFECTIVE_UID=65532
EFFECTIVE_GID=65532
CAP_EFF=0000000000000000
NO_NEW_PRIVS=1
PID1=python -m aioa_cloudops_agent.portable_server
HEALTH=ok
READINESS=ready
TOKEN_MODE=0600
```

Only after that separate bound proof did the local compatibility run use `--user 0:0` to work around
the engine's mapping defect. The gate rejects any other user override and arbitrary extra engine
arguments. Standard Docker/Podman certification uses the declared image user directly and does not
use this compatibility override.

## Package completeness

The canonical command is now:

```text
python -m aioa_cloudops_agent.portable
```

`scripts/run_portable_demo.py` is a thin compatibility launcher for the same function. The reviewed
offline deployment contract and verifier fixture ship inside the wheel as package data. Their bytes
are tested against the existing canonical repository inputs, preventing a second or divergent
runtime fixture.

## Qualification checks

```text
TARGETED_CLI_CONTAINER_AND_SANDBOX_TESTS=26 passed
RUFF_TARGETED=PASS
WHEEL_BUILD=PASS
WHEEL_PACKAGE_RESOURCES=2/2 present
PIP_CHECK=PASS
EVIDENCE_BUILD_CHECK=PASS claims=28
EVIDENCE_VALIDATOR=PASS claims=28 live_receipts=0
P1_SOURCE_AND_PROOF_GATES=5/5 PASS
P1_CLEAN_CLONE_GATE=EXPECTED_PRECOMMIT_FAILURE_OLD_HEAD
```

The clean-clone command necessarily checks the current committed `HEAD`; before this commit exists,
that is the B5 Commit 1 baseline and cannot contain this implementation. Acceptance therefore
requires, after creating the single planned Commit 2, cloning that exact commit, rebuilding the
image from that clone, rerunning both container invocations, and rerunning P1. Any failure must be
fixed by amending Commit 2 before B5 release freezing. The exact-commit result belongs in the B5
build-complete attestation, avoiding a circular claim inside this commit.

## External-action boundary

```text
AWS_CALLS=0
AWS_MUTATIONS=0
LIVE_DEPLOYMENTS=0
REMOTE_PUSHES=0
IMAGE_PUSHES=0
PUBLICATIONS=0
EMAILS_SENT=0
```
