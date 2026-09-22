# AIOA spArkHAT — Reproducibility Report

Date: 2026-09-22
Branch: `codex/nvidia-final-week-20260921`
Validated source SHA: `b9a4701d8d32ed341a83d02477c12981d1eda79c`

## Fresh-clone result

A new clone was created from the committed active competition repository with no hardlinks. The clone was clean and remained on the expected branch/SHA.

Validation host:
- Python `3.12.3`
- Git `2.43.0`
- pip `24.0`

The source package built successfully as `aioa-sparkhat 0.1.0` and was installed into a clean isolated target directory with no project dependencies requested.

Installed import resolved from the isolated target rather than the source checkout. The installed CLI help executed successfully.

## Deterministic one-command demo

From the fresh clone:

```bash
PYTHONPATH=.:runtime:tests python3 scripts/nvidia_reviewer_preflight.py
```

Result: **PASS**.

Observed reviewer summary:
- `scope = DETERMINISTIC_TEST_FIXTURE_ONLY`
- `stage_count = 14`
- `duplicate_effects = 0`
- `restart_replay_dispatches = 0`
- `effect_executor = ServiceGuard`
- provider = `TEST_FIXTURE`
- memory = `TEST_FIXTURE` / `repository-durable-test`
- DVM/pheromone = `SHADOW`
- live NVIDIA/Cockroach/OpenRouter/AWS validated by this run = `false`

Artifact SHA-256 from the fresh-clone preflight:
`bb38b581979ecf825cc8112149743cfd1e61c9a140151c3e865ea33652a0a786`

## Failure-path check

A copy of the generated reviewer artifact was deliberately corrupted by replacing the receipt digest with a non-hex 64-character value. The read-only competition projection returned:

```text
status = INVALID_EVIDENCE
evidence_available = false
provider_mode = UNKNOWN
```

The failure demo therefore failed closed rather than producing a false reviewer PASS.

## Acceptance verification

A second clean-clone rehearsal from committed SHA `b9a4701d8d32ed341a83d02477c12981d1eda79c` repeated the no-hardlink clone, isolated `pip --target` install and deterministic reviewer preflight. The installed `runtime` import resolved from the isolated target directory when executed outside the source checkout, and the installed CLI help completed successfully.

Focused reviewer regression in the active worktree: **21/21 PASS** across reviewer preflight, competition demo, read-only competition projection and competition evaluation.

The fresh-clone preflight again returned **PASS**, with 14 stages, `duplicate_effects=0`, `restart_replay_dispatches=0`, `ServiceGuard` as the effect executor, truthful `TEST_FIXTURE` provider/memory labels and DVM/pheromone `SHADOW`.
