# Day 15 deterministic Lambda release build

This build is local-only. It never calls AWS and never deploys a stack. A release artifact is
eligible for review only when every mandatory proof is `PASS`; `PARTIAL` or `BLOCKED` is not a
release success.

## Frozen inputs and outputs

The builder accepts only the canonical, nonsymlinked, tracked repository inputs at a completely
clean `HEAD`:

- `src/aioa_cloudops_agent/`
- `infra/sam/template.yaml`
- `requirements/lambda-runtime.in`
- `requirements/lambda-runtime.txt`
- `requirements/day15-toolchain.json`
- `scripts/day15/build_lambda_artifact.py`

It rejects an alternate source tree, template, lock, untracked file, staged change, modified
worktree file, or Git-blob mismatch. The manifest binds the source tree and inputs to the clean
commit. Build outputs are ignored local files:

- `dist/day15/aioa-lambda.zip`
- `dist/day15/aioa-lambda.manifest.json`
- `dist/day15/pip-audit.json`

The SAM template consumes the first path as `../../dist/day15/aioa-lambda.zip`.

## Required toolchain

`requirements/day15-toolchain.json` is the reviewed machine-readable record. The builder requires
its exact Python patch version, pip version, Python 3.12 runtime, x86_64 architecture, target wheel
platform, and ZIP mode. The runtime lock contains an exact version and one or more SHA-256 hashes
for every direct and transitive distribution. Editable installs, VCS URLs, local paths, extra
indexes, unpinned requirements, undeclared distributions, and source distributions are rejected.

The dependency scan and digest-pinned Lambda Python 3.12/x86_64 container import are mandatory.
The reviewed toolchain is Python `3.12.3`, pip `26.2.1`, `pip-audit` `2.10.1`, Podman `4.9.3`,
and the exact `linux/amd64` Lambda base-image digest recorded in
`requirements/day15-toolchain.json`. The container runs with no network, a read-only root and
artifact mount, all capabilities dropped, no new privileges, no cgroups, and no shared IPC. The
read-only host `/dev/pts` bind is required by the rootless single-GID builder and does not expose a
writable device surface. A missing version, local image, scanner, engine, or clean import remains
`BLOCKED` or `FAIL`; it is never inferred from an old report.

The lock is not regenerated during a release build. A lock change is a separate dependency-review
change using the exact generator versions recorded in `requirements/day15-toolchain.json`.

## Commands

From the repository root, first check the lock without installing anything:

```bash
.venv/bin/python scripts/day15/build_lambda_artifact.py --verify-lock --json
```

On the exact reviewed toolchain and a clean commit, build and validate the package. The executable
used for this command must contain the pinned scanner, and `PATH` must resolve the pinned Podman:

```bash
.venv/bin/python scripts/day15/build_lambda_artifact.py --json
```

The builder installs only hash-matching manylinux2014 x86_64 CPython 3.12 wheels into two distinct
temporary directories, copies normalized repository source, scans every archive entry, imports
every template handler first in an isolated host process and then inside the pinned Lambda image,
repeats the ZIP build, and requires byte-for-byte equality. It reruns the scanner and container
proof when D15-G04 is evaluated rather than trusting the ignored JSON files. ZIP members are
ordered, stored without compression, stamped at the ZIP epoch, and assigned fixed permissions. No
build time, hostname, username, absolute path, credential, token, account ID, or working directory
is written to the artifact, manifest, scan report, or CLI summary.

Exit codes are stable: `0` is `PASS`, `1` is `FAIL`, `2` is `PARTIAL`, and `3` is `BLOCKED`.
Never proceed to a change set unless the artifact command returns `PASS` and the manifest hashes
match the files presented for review.
