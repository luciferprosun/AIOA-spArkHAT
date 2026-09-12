# BUILD_COMPLETE attestation — 2026-09-01

## Attested status

```text
BUILD_COMPLETE=PASS
ATTESTATION_STATUS=BUILD_COMPLETE
SOURCE_COMMIT=dbea5411b1c0d81de0035d9ef08e28211fb79e79
SOURCE_TREE=ad83b97461abec6af171441267c63ee33b2f3e71
CONTAINER_DIGEST=sha256:a835f9bdbc7a3854304e5574440a6a9944ea4bd04e839eae317a8e6554855eae
CONTAINER_ID=524fe1212fc65e3d35a015717d03250e25c5ad32359e1c9595878c5bc6b057e8
ATTESTATION_SHA256=d0a0db0fedac0e3a37b776fea52d5624f6f3525a059307423d64fca7109a15dd
AWS_CALLS=0
AWS_MUTATIONS=0
DEPLOYMENTS=0
IMAGE_PUSHES=0
REMOTE_GIT_PUSHES=0
PUBLICATIONS=0
LIVE_RECEIPTS=0
```

I attest only to a locally built and locally executed portable/mock OCI artifact. The exact clean
source, hash-pinned inputs, image identity, two ephemeral judge flows, non-root OCI proof, package
manifest, image-export privacy scan, and local test gates are bound by the machine-readable files in
`docs/evidence/release/`.

This attestation does not assert a registry publication, live container host, public endpoint,
production identity, AWS account access, Bedrock access, cloud mutation, or externally submitted
hackathon entry. The local OCI manifest digest is not described as a registry digest.

## Machine authority

The canonical authority is
`docs/evidence/release/portable-b5-build-complete-attestation.json`. Its compact canonical material
excluding `attestation_sha256` hashes to the value above. Its bound artifact manifest file SHA-256
is `4963d32bf76aff6da8f221430dfff702d5b4fa879429afa0ba7d63bb1d323223`; its deterministic sums file
SHA-256 is `76acd797b841b5c10ec89888917b01849b2cd04f82fd0ec4456cb292e1cbe0e7`.

Run the offline verifier from a clean checkout with:

```bash
.venv/bin/python scripts/build_b5_release_evidence.py --check --json
.venv/bin/python scripts/validate_reviewer_evidence_manifest.py
```

Any bound drift causes failure. The freeze rule in the machine attestation requires a full B5
rebuild and re-certification after any runtime, dependency, container, or bound-document change.
