# Portable B6 publication-ready audit

## Result

```text
PHASE=B6_PUBLICATION_READY_LOCAL
PUBLICATION_READY=PASS
PUBLIC_SOURCE_COMMIT=c7fa5a5c2509cccf071a9e58477776c1a1e00aea
LICENSE=MIT_CONFIRMED_FROM_INITIAL_COMMIT
AWS_CALLS=0
AWS_MUTATIONS=0
EXTERNAL_DEPLOYMENTS=0
REMOTE_PUSHES=0
PUBLICATION_ACTIONS=0
PUBLIC_BUNDLE_UPLOADED=NO
```

B6 produced and certified a local, sanitized hackathon candidate. It did not publish a repository,
push a Git branch or image, upload an archive, create an endpoint, deploy infrastructure, contact
AWS, record a video, send an email, or submit a Devpost entry.

## Sanitized source

The deterministic builder read Git blobs from exact Commit 4
`c7fa5a5c2509cccf071a9e58477776c1a1e00aea`. It classified every one of 407 tracked files:

| Classification | Count | Export behavior |
| --- | ---: | --- |
| `PUBLIC_REQUIRED` | 178 | included |
| `PUBLIC_ALLOWED` | 147 | included |
| `LEGAL_REVIEW` | 2 | included after MIT/prior-art review |
| `PRIVATE_INTERNAL` | 79 | excluded |
| `GENERATED` | 1 | frozen root README replaced by reviewed public overlay |
| `SECRET_RISK` | 0 | none present |

The source project was not deleted or rewritten. The exported root README is the reviewed B6
overlay; the manifest records that transformation. The resulting image is therefore not claimed
byte-identical to B5 even though runtime source, Dockerfile, locks, and safety behavior are unchanged.

The final cross-phase regression found that the first public Devpost rewrite had dropped three
historical Phase 3 document-contract markers. Commit 4 was repaired to preserve the canonical name,
`DEPLOYMENT_READY_LOCAL_RC` status, and audited no-live-AWS sentence. The full B6 export, privacy
scan, no-cache build, runtime checks, two judge flows, and deterministic final build were then rerun
from the repaired exact commit; none of the prior B6 hashes is reused here.

## Clean-room reproduction

The initial archive was unpacked into a separate directory without `.git`. Only public
`README.md` and `docs/submission/REPRODUCIBILITY.md` were used.

```text
CANDIDATE_SHA256SUMS=PASS 331/331
SANITIZED_CLEAN_ROOM_BUILD=PASS NO_CACHE
HASH_PINNED_DEPENDENCIES=PASS
PIP_CHECK_IN_CONTAINER=PASS
SANITIZED_CLEAN_ROOM_START=PASS
HEALTH=PASS HTTP_200
READINESS=PASS HTTP_200
SANITIZED_APPROVE=PASS
SANITIZED_DENY=PASS
SANITIZED_RECOVERY=PASS
SANITIZED_REPLAY=PASS
CLAIMS_PROOF_AUDIT=PASS 29/29
```

Two isolated container invocations emitted identical bytes and the same inner receipt SHA-256
`f365b07702e43c3848b3470453910b2239d640e8e9ec22a917790a702c110ba3`. Each proved one approved
mock mutation after decision, terminal denial with zero mutation, restart recovery, reconciliation,
replay and binding rejection with zero mutation delta, five fail-closed probes, zero external
connections, zero provider calls, zero AWS calls, and zero AWS mutations.

## Container identity and host limitation

```text
LOCAL_REFERENCE=localhost/aioa-portable:b6-public-c4-r1
RUNTIME_IMAGE_ID=05ae93a9efa117d7fe27b5f8dbc08b511ee8618754a4c3630e7c0ba6a689a225
BUILD_MANIFEST_DIGEST=sha256:2acaf338711940cd2d0318659df3dd3cb06d9ce2a0fb8767eac167e22a8be613
LOCAL_MANIFEST_DIGEST=sha256:aa40e619414ba81bf1c5e5964f991505f17a78f884a767a60fa547382c462a9d
OCI_ARCHIVE_SHA256=f5b082e0976ff8e5cf8084d5e018dae152bd482c65e51ee2c10650a214c052ca
IMAGE_SIZE_BYTES=219807803
CONFIGURED_USER=aioa
ENTRYPOINT=python -m aioa_cloudops_agent.portable_server
NETWORK=none
ROOT_FILESYSTEM=read-only
CAP_EFF=0000000000000000
NO_NEW_PRIVS=1
TOKEN_MODE=0600
```

The host's Podman runtime has no usable subordinate-ID helper for the declared UID/GID 65532. A
direct run failed before application startup, so the B6 runtime invocations used the disclosed local
`0:0` compatibility override. They are not represented as a non-root proof. Non-root authority
remains the exact, image-bound B5 receipt for the frozen image, which proves UID/GID 65532, zero
capabilities, `NoNewPrivs=1`, health/readiness, PID 1, and token mode `0600`. B6 did not change the
Dockerfile or runtime source.

## Privacy and claim audit

The final candidate, including its B6 report, contained 333 regular files. The final scan read 330
text files and reviewed three expected image assets. It found no secret, private key, credential
file, personal PDF, real email, phone number, local user path, browser/session file, or AWS account
identifier. Thirteen synthetic fixtures in tests were classified rather than hidden; their values
were not emitted.

```text
PUBLIC_SECRET_SCAN=PASS
PUBLIC_PRIVATE_DATA_SCAN=PASS
FINDINGS=0
SCAN_RECEIPT_SHA256=91ff2b8262b516bc6ddc0065b88adedd002e7dded95a9008e51786ac6f7fe6e8
CLAIMS_PROOF_AUDIT=PASS 29/29
UNSUPPORTED_CLAIMS=0
```

The claims matrix forbids promotion to live AWS, live Bedrock, production readiness, public
availability, real cloud mutation, registry publication, or final submission. The exact MIT License
and prior-art disclosure originate in initial commit
`d813290727b89017bd348c04f68a7f07156652f7`; no human license decision remains open.

## Frozen local bundle

```text
PUBLIC_BUNDLE=dist/submission/portable-b6-2026-09-01/aioa-agents-for-humans-publication-candidate.zip
ARCHIVE_BYTES=4408888
ARCHIVE_SHA256=c69baf9322cfcd234ca6610f733f5a8de4ae6a463f3e2a66ce8e78664b4c43de
MANIFEST_FILE_SHA256=b0a89730d24cba4208e3f69c35ffccc453a1fe6e6c49c6e4ca2287cc93af8624
PAYLOAD_TREE_SHA256=248a692e4e797b44d5f4f4e2747ea77b4a1bffa975a3370c61c2069e5b2b916a
B6_REPORT_SHA256=318cfc5dde379e9f5c8806f7c68e662581a7d7ee1e8b50ff7a375ecc51d9f416
DETERMINISTIC_REBUILDS=2/2 IDENTICAL
ARCHIVE_UPLOADED=NO
```

The archive contains the sanitized source tree, `PUBLICATION_MANIFEST.json`,
`PUBLICATION_EXCLUSIONS.md`, `SHA256SUMS`, `B5_BUILD_COMPLETE_REFERENCE.json`, and
`B6_REPRODUCIBILITY_REPORT.json`. The committed bundle receipt is
`docs/evidence/submission/portable-b6-publication-bundle.json`.

## Host diagnostics

The first no-cache build exhausted the small system filesystem while creating VFS layers. No source
or product gate failed. The build was repeated from the same source on a graphroot located on the
project disk and passed. Four verified incomplete layers and then dangling build caches were removed;
all tagged B5 images were preserved. A local OCI archive moved the resulting image into the proven
runtime storage. Registry transports remained denied.

The optional native venv path was not run because the host Python lacks `ensurepip`. This does not
block B6: the canonical no-cache container build, package wheel, `pip check`, server, judge flows,
checksums, claims audit, and privacy gates passed from the sanitized candidate.

## Commit 5 gate

```text
SANITIZED_CLEAN_ROOM_BUILD=PASS
SANITIZED_CLEAN_ROOM_START=PASS
SANITIZED_APPROVE=PASS
SANITIZED_DENY=PASS
SANITIZED_RECOVERY=PASS
SANITIZED_REPLAY=PASS
CLAIMS_PROOF_AUDIT=PASS
PUBLIC_SECRET_SCAN=PASS
PUBLIC_PRIVATE_DATA_SCAN=PASS
PUBLIC_BUNDLE_CREATED=YES
PUBLIC_BUNDLE_UPLOADED=NO
REMOTE_PUSHES=0
PUBLICATION_ACTIONS=0
EXTERNAL_DEPLOYMENTS=0
PUBLICATION_READY=PASS
HARD_BLOCKER=NONE
HUMAN_ACTION_REQUIRED=NONE_FOR_LOCAL_B6
```

B6 stops at local publication readiness. Deployment, push, upload, repository visibility change,
video publication, and submission require a later explicit human-authorized phase.
