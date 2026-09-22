# AIOA spArkHAT — Reviewer Quickstart

## Fast path

Requirements:
- Git
- Python 3.11+
- no API key for the deterministic reviewer path

From a fresh clone:

```bash
git clone <repository-url> aioa-sparkhat
cd aioa-sparkhat
PYTHONPATH=.:runtime:tests python3 scripts/nvidia_reviewer_preflight.py
```

Expected top-level result:

```text
status: PASS
scope: DETERMINISTIC_TEST_FIXTURE_ONLY
stage_count: 14
duplicate_effects: 0
restart_replay_dispatches: 0
effect_executor: ServiceGuard
provider_mode: TEST_FIXTURE
memory_mode: TEST_FIXTURE
dvm_pheromone_mode: SHADOW
```

## What the command proves

The preflight creates a fresh temporary state root, executes the deterministic 14-stage competition slice, loads the resulting evidence through the read-only competition projection, and evaluates the same reviewer-facing contract.

It verifies:
- model/provider output has no execution authority;
- human-bound authority remains required;
- Service Guard is the competition effect executor;
- a durable receipt and independent measurement agree;
- restart/replay causes zero additional dispatches;
- fixture memory/provider modes are truthfully labelled;
- DVM/pheromone remains SHADOW.

It does **not** claim that live NVIDIA, CockroachDB, OpenRouter, or AWS was validated by that run.

## Optional package install

The package itself can be installed before the preflight:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
PYTHONPATH=.:runtime:tests python scripts/nvidia_reviewer_preflight.py
```

On Debian/Ubuntu, `python3-venv` may need to be installed by the reviewer if the OS Python was packaged without `ensurepip`.

## Raw demo and interpretation

To keep the raw artifact:

```bash
PYTHONPATH=.:runtime:tests python3 scripts/nvidia_competition_demo.py \
  --root /tmp/aioa-nvidia-review-demo \
  --output /tmp/aioa-nvidia-review-demo.json
```

Read these fields first: `execution_mode`, `provider`, `effect`, `safety`, `mission`, and `memory`.

Authority interpretation:
- `TEST_FIXTURE` means deterministic local evidence, not a live provider claim;
- a proposal is advisory until the Core/human boundary authorizes the exact effect;
- a receipt records what the executor reports;
- independent measurement is the separate verification surface;
- replay safety is demonstrated only when restart does not create another effect.

For the complete NVIDIA review path, continue with `docs/reviewer/NVIDIA_REVIEWER_START_HERE.md`.
