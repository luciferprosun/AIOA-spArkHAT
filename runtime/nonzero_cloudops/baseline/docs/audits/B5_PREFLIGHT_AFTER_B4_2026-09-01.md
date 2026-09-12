# AIOA — B5 PREFLIGHT AFTER B4

## Status

PREFLIGHT=PASS
ANALYSIS_MODE=READ_ONLY
B5_IMPLEMENTATION_STARTED=NO
EXTERNAL_DEPLOYMENT_PERFORMED=NO
AWS_MUTATIONS=0
REMOTE_PUSHES=0
INPUT_HEAD=0cb0fe15f245e9df6f46d937a69b5a8305e4f3bf
DATE=2026-09-01

This is the authorized read-only architectural preflight that follows a clean B4 gate. It creates no
container, pulls no image, installs no engine, changes no runtime path, and performs no deployment.

## Canonical Roadmap Identity

B5_TITLE=BUILD-COMPLETE PORTABLE RELEASE CANDIDATE
MASTER_PROMPT=PORTABLE-P5 - BUILD-COMPLETE RELEASE CANDIDATE

Canonical sources:

- `/home/l/Downloads/AIOA_Agents_for_Humans_Next_Steps_After_B0_B2_2026-09-01.pdf`, B5 section
- `docs/ROADMAP_STATUS.md`, `NEXT_MACRO_STEP = B5_BUILD_COMPLETE_PORTABLE_RELEASE_CANDIDATE`
- `docs/JUDGE_EXPERIENCE.md` and `docs/RELIABILITY_SECURITY.md`, explicit B5 deferrals

## Mission

Freeze one platform-neutral container artifact that can later be deployed unchanged to a suitable
non-AWS container host. B5 is packaging and local certification, not deployment.

## Canonical Objectives

1. Create or harden a small Python-base Dockerfile with a non-root user, deterministic dependencies,
   a healthcheck-compatible port, and no credentials in image layers.
2. Provide one local Docker/Compose smoke path using the same API, judge UI, Strands runtime, policy,
   approval, evidence, persistence, verification, and recovery implementation already certified.
3. Define the Portable Runtime Contract: application version, source commit, container digest,
   selected provider, allowed egress, storage mode, session TTL, port, health/readiness endpoints,
   secret names, and resource limits.
4. Build from a clean clone and run the complete primary approve, deny, recovery, and replay demo
   through the container rather than a developer-only virtual environment.
5. Generate a `BUILD_COMPLETE` attestation bound to source commit, immutable container digest, and
   hashes of the runtime documentation and demo runbook.
6. Preserve the freeze rule: a later deployment-only code fix invalidates the artifact and returns
   the project to B5 for rebuild and re-certification.

## Required Outputs

- Dockerfile and minimal Compose/local-container launcher
- portable runtime contract and validation schema
- immutable container digest
- clean-clone container build/run proof
- `BUILD_COMPLETE` attestation

## Dependencies and Current Readiness

| Dependency | Current evidence | Preflight result |
|---|---|---|
| B4 gate | 1409/1409 tests, P0 15/15, P1 6/6, B4 11/11 | READY |
| Existing product path | `scripts/run_local_hitl_api.py`, `/health`, `/ready`, judge UI and Local HITL runtime | READY; reuse unchanged |
| Strands portable runtime | canonical demo reports Strands 1.53.0, portable/mock, zero AWS/external calls | READY |
| Python package | wheel build PASS for version 0.2.0rc1 | READY |
| Deterministic dependency input | core direct dependencies are pinned; only the historical Lambda runtime has a lock-style requirements file | GAP; add one portable container lock without broad upgrades |
| Container files | no tracked Dockerfile, Compose file, or `.dockerignore` | GAP; B5 output required |
| Local container engine | neither `docker` nor `podman` is available in the current command path | BLOCKING PREREQUISITE FOR B5 EXECUTION, not a B4 defect |
| Persistence mount contract | owner-only bounded JSON stores exist; container volume/UID semantics are not frozen | GAP; define and test in runtime contract |
| Port/health contract | loopback launcher and `/health`/`/ready` exist | READY INPUT; freeze container bind/port semantics in B5 |
| Egress contract | deterministic judge gate proves zero external egress | READY INPUT; enforce inside container proof |
| Secret contract | no credential needed for mock; redaction and private token file are tested | READY INPUT; document secret names and never bake values into layers |
| Clean-clone proof | P1 clean clone passes outside a container | READY INPUT; container-specific proof remains required |

## Architecture Preservation Rules

The container must be a packaging boundary only. It must not introduce:

- a second agent loop or substitute for Strands Agents;
- direct UI/API-to-mutation authority;
- a new approval or hashing scheme;
- a second persistence/evidence implementation;
- provider-specific domain logic;
- required AWS credential discovery or AWS network access;
- a shell/debug execution endpoint;
- a default root process or writable broad filesystem.

The image should invoke the existing local API/runtime and mount bounded state, inventory, token, and
evidence locations with a stable non-root UID/GID. Health checks must remain process/readiness checks
and must not contact AWS or a paid model provider.

## Suggested B5 Validation Order

1. Re-attest the exact B4 documentation commit and clean worktree.
2. Establish or obtain an authorized local Docker/Podman-compatible engine; record its version only.
3. Freeze a portable dependency lock from existing compatible versions without broad upgrades.
4. Add the minimal Dockerfile, `.dockerignore`, Compose smoke path, and typed runtime contract.
5. Build from a clean clone with no credentials in build arguments, environment, history, or layers.
6. Run as non-root with bounded resources, read-only root where practical, explicit writable mounts,
   loopback publication, and zero unexpected egress.
7. Exercise health/readiness plus approve, deny, restart/recovery, replay, tamper rejection, and
   secret redaction through the container.
8. Record source SHA, image ID/digest, package hash, docs/runbook hashes, tests, and zero-cloud facts.
9. Generate and validate the `BUILD_COMPLETE` attestation, then stop without deployment or push.

## Expected Exit Gate

BUILD_COMPLETE=PASS

The exact clean-clone container must run the full judge flow locally and all gates must pass. The
attestation must bind the tested commit, container digest, and documentation/demo hashes. Deployment,
publication, registry push, AWS mutation, and remote Git push remain forbidden until a later
explicitly authorized phase.

## Safest Next Action

Authorize B5 separately and make a compatible local container engine available. Then implement and
certify the frozen container artifact without deploying or publishing it.
