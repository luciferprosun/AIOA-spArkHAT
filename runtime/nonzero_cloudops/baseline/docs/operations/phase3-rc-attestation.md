# Phase 3 Local Release Candidate Attestation

The attestation status is exactly `DEPLOYMENT_READY_LOCAL_RC`. It never represents a production deployment, live AWS verification, external submission, or live receipt.

Generation requires an exact expected HEAD, `main`, a clean worktree, matching `origin/main`, Python 3.12 on x86_64, the RC package version, valid executed local-gate evidence, and byte-current artifacts. Validation re-reads Git and every artifact. A different HEAD, tree, origin, dirty file, changed hash, or stale gate binding fails closed.

Because a committed report cannot contain its own commit SHA, the attestation permits only one explicit post-test delta: `docs/reports/phase3-local-release-candidate-gate-2026-08-27.md`. The final attested HEAD still must be clean and pushed, and the diff from the fully tested commit is rechecked.

## Attested artifacts

- `docs/architecture/phase3-deployment-ready-local-rc.md` — `PHASE3_ARCHITECTURE_DOCUMENT`
- `docs/evidence/release/phase3-expected-resources.json` — `EXPECTED_RESOURCE_MANIFEST`
- `docs/evidence/release/phase3-offline-verifier-receipt.json` — `OFFLINE_VERIFIER_RECEIPT`
- `docs/evidence/release/phase3-devpost-claim-audit.json` — `DEVPOST_SENTENCE_AUDIT`
- `docs/submission/demo-runbook.md` — `DEMO_RUNBOOK`
- `docs/submission/devpost-draft.md` — `DEVPOST_DRAFT`
- `infra/sam/template.yaml` — `SAM_TEMPLATE`
- `pyproject.toml` — `PYTHON_PACKAGE_CONTRACT`
- `requirements/day15-toolchain.json` — `TOOLCHAIN_LOCK`
- `requirements/lambda-runtime.txt` — `LAMBDA_DEPENDENCY_LOCK`
- `requirements/phase3-cleanup-contract.json` — `ROLLBACK_CLEANUP_CONTRACT`
- `requirements/phase3-deployment-contract.json` — `AWS_DEPLOYMENT_CONTRACT`
- `requirements/phase3-iac-manifest.schema.json` — `IAC_MANIFEST_SCHEMA`
- `requirements/phase3-verifier-receipt.schema.json` — `VERIFIER_RECEIPT_SCHEMA`

## Required local-gate checks

- `DEMO_APPROVE`
- `DEMO_DENY`
- `DEPLOYMENT_CONTRACT`
- `GENERATED_ARTIFACTS`
- `GIT_DIFF_CHECK`
- `IAC_DRY_RUN`
- `OFFLINE_NETWORK_GUARD`
- `PACKAGE_BUILD`
- `PIP_CHECK`
- `RECOVERY`
- `REPLAY_PROTECTION`
- `RUFF`
- `SECRET_SCAN`
- `VERIFIER_LOCAL_CHAIN`

The full suite must have zero skips, P0 must pass 15/15, P1 must pass 6/6, and offline demos/verifier must record zero external connections, zero AWS mutations, and zero live receipts. The one allowed mutation count is explicitly the protected local mock approved-path action.
