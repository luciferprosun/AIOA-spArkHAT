# Publication exclusions

The B6 builder creates a new sanitized tree; it does not delete or rewrite excluded material in the
canonical development repository. `PUBLICATION_MANIFEST.json` classifies every tracked source path
and records its inclusion decision and source hash.

## Excluded classes

| Classification | Export behavior | Rationale |
| --- | --- | --- |
| `PRIVATE_INTERNAL` | excluded | Internal audits, recovery notes, historical deployment blockers, and operator-only material are unnecessary for judging the portable product |
| `SECRET_RISK` | excluded and gate-failing if unexpectedly present | Credential-shaped files, private keys, environment files, cookies, and session stores cannot enter the candidate |
| `GENERATED` | source path excluded or replaced deterministically | The frozen B5 root README is replaced only in the exported tree by the reviewed B6 public README; manifests, hashes, and references are generated |

`PUBLIC_REQUIRED`, `PUBLIC_ALLOWED`, and reviewed `LEGAL_REVIEW` files are included. The MIT License
and prior-art disclosure are preserved. Runtime source, dependency locks, container definition,
portable tests, judge assets, submission documents, and public B5 evidence remain available.

## Path-level policy

The deterministic policy excludes:

- internal audit and roadmap directories;
- historical Day 15 operator scripts, tests, contracts, and runbooks;
- deployment-blocker receipts and private/recovered external-state evidence;
- local build, virtual-environment, cache, log, and state directories already ignored by Git; and
- any credential-shaped, browser-session, private-key, or personal PDF file.

The policy intentionally keeps source and infrastructure definitions that explain optional AWS
integration, while keeping the credential-free portable route complete.

## README transformation

The canonical B5 repository README is a frozen package-build input. B6 therefore does not edit it.
During export, `docs/submission/public/README.md` is copied to candidate-root `README.md` and its
origin is recorded in the manifest. This changes publication-only package metadata, so the rebuilt
public image is not claimed byte-identical to the frozen B5 image. Runtime source, Dockerfile, and
dependency locks remain unchanged.

## Generated bundle files

- `PUBLICATION_MANIFEST.json`: full source classification and payload hash inventory;
- `PUBLICATION_EXCLUSIONS.md`: this rationale at bundle root;
- `B5_BUILD_COMPLETE_REFERENCE.json`: sanitized pointer to frozen local B5 evidence;
- `B6_REPRODUCIBILITY_REPORT.json`: added only after the clean-room gate passes; and
- `SHA256SUMS`: hashes every candidate payload file present before the sums file itself.

No archive is uploaded by the builder. Publication, deployment, repository visibility, and final
submission remain explicit human actions outside B6.
