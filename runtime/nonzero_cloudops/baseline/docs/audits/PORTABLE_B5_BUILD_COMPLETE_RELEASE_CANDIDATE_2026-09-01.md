# Portable B5 build-complete release candidate

## Result

```text
BUILD_COMPLETE=PASS
PHASE=B5_BUILD_COMPLETE_PORTABLE_RELEASE_CANDIDATE
FROZEN_SOURCE_COMMIT=dbea5411b1c0d81de0035d9ef08e28211fb79e79
FROZEN_SOURCE_TREE=ad83b97461abec6af171441267c63ee33b2f3e71
APPLICATION_VERSION=0.2.0rc1
PLATFORM=linux/amd64
PYTHON_VERSION=3.12.14
AWS_CALLS=0
AWS_MUTATIONS=0
DEPLOYMENTS=0
IMAGE_PUSHES=0
REMOTE_GIT_PUSHES=0
PUBLICATIONS=0
```

B5 freezes one local, provider-neutral OCI artifact built from a detached clean clone. It does not
deploy that artifact, publish it to a registry, create a public endpoint, contact AWS, or turn an
offline/mock receipt into live-cloud evidence.

## Frozen image

```text
LOCAL_REFERENCE=localhost/aioa-portable:b5-c2
IMAGE_ID=524fe1212fc65e3d35a015717d03250e25c5ad32359e1c9595878c5bc6b057e8
LOCAL_OCI_MANIFEST_DIGEST=sha256:a835f9bdbc7a3854304e5574440a6a9944ea4bd04e839eae317a8e6554855eae
IMAGE_SIZE_BYTES=219809071
REGISTRY_DIGEST=NONE_NOT_PUSHED
CONFIGURED_USER=aioa
EFFECTIVE_CERTIFIED_UID_GID=65532:65532
ENTRYPOINT=python -m aioa_cloudops_agent.portable_server
BASE_IMAGE=docker.io/library/python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
```

The tag is only a local convenience and is mutable. The frozen content identity is the recorded
local Docker-schema manifest digest plus image ID and exact source label. No registry digest exists
because pushing was forbidden.

The rootless Podman 4.9.3 environment available for this build has a single host UID/GID map. The
normal declared-user probe is therefore separately proven with the exported exact root filesystem
under a nested OCI user namespace. The bound receipt records UID/GID 65532, zero effective
capabilities, `NoNewPrivs=1`, the canonical PID 1, passing health/readiness, and token mode `0600`.
The two judge-flow containers used a disclosed local `0:0` engine workaround only after that exact
image-bound proof. The public runbook requires normal engines to run the declared image user.

## Deterministic build inputs

| Input | SHA-256 |
| --- | --- |
| `Dockerfile` | `62ab24342fb35961e6b5b05969f3749b3d4d201afd4f6510223b870c0f4ba93c` |
| `.dockerignore` | `c6bf8a28a6fbcb1ba2e94fcdedcb00cf6f6620556262c88629dd14d800346458` |
| `requirements/build.lock` | `d46492123b794c100b45c485f2981c1a12f71388f61439a5a662d850b19039a5` |
| `requirements/portable.lock` | `a7be92862cb66b67f2bf5b664f62abee1dbd48d65e2ee12fbcbaa5be2dff5dcd` |
| project wheel | `fe5b5df0448bf41c9aa0d6460b998adf280cab567b9ba688e5111cb71c0ff395` |
| portable runtime contract | `c5af5e77349a1038d860f3108a2bbaee6fbb6d3df7340f931095551a72240233` |
| container judge runbook | `26c37b52d5f153c582e10b824f18a5a06840def479bb49d77365c97e9f99f81a` |
| submission demo runbook | `3ee0e75aab70b9e63860e7deb3e5785cfd6a1df9ac60ea9462d9022fe61d3f47` |

The project wheel was reproduced twice with the same digest. The runtime closure contains 55
hash-pinned dependencies plus the project wheel and `pip` from the digest-pinned base image: 57
installed distributions total. No dedicated SBOM tool was locally available, so the checked-in
deterministic package manifest is the explicit fallback; it records every installed name, version,
provenance, and available artifact hash.

## Container execution evidence

The exact source-bound image passed two separate `run --rm` invocations with:

```text
NETWORK=none
ROOT_FILESYSTEM=read-only
TMPFS=/tmp:rw,nosuid,nodev,noexec,size=64m
CAPABILITIES_DROPPED=ALL
NO_NEW_PRIVILEGES=true
HOST_PORTS_PUBLISHED=0
SHARED_MOUNTS=0
SHARED_STATE=false
CREDENTIAL_ENVIRONMENT_INHERITED=false
```

Both invocations produced the same deterministic portable receipt SHA-256
`f365b07702e43c3848b3470453910b2239d640e8e9ec22a917790a702c110ba3` and proved approved success,
human denial, pending-approval recovery, terminal reconciliation, replay rejection, and
resource-binding-tamper rejection. Approved mock mutation count was exactly one after explicit
decision; denial, recovery replay, and tamper deltas were zero. Provider network, external network,
AWS calls, and AWS mutations were zero.

## Image privacy scan

The exact exported root filesystem scan covered 11,287 regular files and 209,599,215 bytes,
including 284 application-package files. It found no `.git`, `.env`, AWS credential file, raw AWS
credential, private-key block/file, or baked operator token. Public example identifiers in boto data
are recognized only by exact SHA-256 allowlist; values are neither emitted nor accepted by path or
substring. Binary files are not interpreted as text credentials.

## Release evidence

| Evidence | File SHA-256 | Internal SHA-256 |
| --- | --- | --- |
| package manifest | `cd578d6e6abef666424a05b3aa710f91781791e57b5e19760d1b0c38c10956a8` | `9f4528ce6e9bfdc7a165c58377eaadf34c64a70f644b34d70a925f987e10d335` |
| artifact manifest | `4963d32bf76aff6da8f221430dfff702d5b4fa879429afa0ba7d63bb1d323223` | `340c4d00a97a39692b41661dde7b13142f6c5247d03389ee1fb0bbe2796f67ce` |
| container gate | `e2ab3e4e3491c60320a5434128e232c33934b93b3cf37f1354e736b07bddb1ca` | `8d3de09bc1d6756647eba8b74d67b4e86ee302be3889e666ac90058c2ec28db3` |
| image privacy scan | `cfed55c4afc0c1222a922a6e392f3a9149f4810e595b4aef565c81a96de52ef8` | `19fc3b0c12ba11305f25f595fd85d7344ccf0999af58ea70f5703daa926ffcac` |
| non-root runtime | `e6db47a0f1845f1cfebc0c5f2fbee330814928805c0047e430c774b7940dd761` | image/digest bound |
| `portable-b5-SHA256SUMS` | `76acd797b841b5c10ec89888917b01849b2cd04f82fd0ec4456cb292e1cbe0e7` | deterministic sorted list |
| build-complete attestation | `9b635d95fd3f59ffef3dd461a2a40908c72bbf074f647d242cf6234db701a5b8` | `d0a0db0fedac0e3a37b776fea52d5624f6f3525a059307423d64fca7109a15dd` |

The generator re-reads every bound source file from the frozen Git commit and rejects current blob
drift. It independently recomputes receipt, manifest, attestation, file, and sums hashes.

## Final B5 gate

```text
FULL_PYTEST=PASS 1428 passed 0 skipped
P0=PASS 15/15
P1=PASS 6/6
B4=PASS 11/11 43 proof tests
RUFF=PASS
PACKAGE_BUILD=PASS
PIP_CHECK=PASS
SECRET_SCAN=PASS 0 findings
EVIDENCE_VALIDATOR=PASS 28 claims 0 live receipts
NATIVE_PORTABLE_FLOW=PASS
CONTAINER_JUDGE_GATE=PASS 2/2
NONROOT_OCI_RUNTIME=PASS
IMAGE_EXPORT_PRIVACY_SCAN=PASS 0 findings
DIFF_CHECK=PASS
```

The 1,428-test source run uses the reviewed Python 3.12 project environment against the detached
checkout with no tracked changes; one untracked checkout-local `.venv` link selected that environment
because a suite test intentionally invokes the documented local path. P1 separately proves a fresh,
non-editable install in its own no-local clone. The first diagnostic invocation without that path was
not treated as a product failure or gate result.

## Freeze rule

Any runtime source, dependency lock, Dockerfile, build-context policy, package-data manifest,
portable runtime contract, container runbook, submission demo runbook, or bound evidence change
invalidates `BUILD_COMPLETE`. The project must return to B5, rebuild from a clean clone, rerun every
gate, and issue a new artifact identity before deployment or publication can be considered.

B5 stops here. B6 may assemble a sanitized public hackathon package from this frozen source and
evidence, but it may not rewrite the artifact identity or claim deployment/publication.
