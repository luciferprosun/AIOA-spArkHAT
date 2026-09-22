# AIOA spArkHAT — Codex Backlog

Date: 2026-09-22
Branch: `codex/nvidia-final-week-20260921`
Preparation HEAD: `4d1099b`

## Operating rule

Codex should improve the existing one-system product, not redesign authority. Preserve one `AgentRuntime`, one final effect authority, `ServiceGuard` as the competition effect executor, human-bound approval, durable receipt/independent verification, and DVM/pheromones in `SHADOW`.

## P0 — reviewer/submission blockers only

No open P0 defect is currently known. If a new P0 appears, stop feature work and reproduce it with a minimal failing test before changing runtime behavior.

Acceptance for any P0 fix:
- focused regression proving the bug and fix;
- no new authority/scheduler/executor/memory engine;
- canonical offline full regression green;
- deterministic reviewer preflight green;
- frozen certification/evidence roots untouched.

## P1 — bounded cleanup before final submission

### CDB-001 — remove reviewer ambiguity around multiple legacy effect-capable implementations

Problem: legacy `ExecutionEngine`, Non-Zero `PortableExecutor`, and `ServiceGuard` all exist in the repository, although the NVIDIA competition path executes effects only through `ServiceGuard`.

Goal: clarify or statically fence competition entrypoints so reviewers cannot infer a second competition executor.

Do not delete grant/history code merely for aesthetics.

Acceptance:
- competition path still reports `effect_executor=ServiceGuard`;
- `nonzero_executor_invoked=false` remains true in competition projection;
- executor containment + Service Guard + Non-Zero authority tests green.

### CDB-002 — narrow legacy runtime entrypoint ambiguity

Problem: `runtime/main.py` still exposes broad historical orchestration paths outside the bounded NVIDIA vertical slice.

Goal: improve naming/docs/static assertions so the supported competition path is obvious without breaking historical/general runtime compatibility.

Acceptance:
- no route from competition reviewer/demo path into legacy effect execution;
- runtime router/containment tests green;
- reviewer docs remain accurate.

### CDB-003 — move deterministic demo helpers out of `tests/` only if low-risk

Problem: `scripts/nvidia_competition_demo.py` imports small fixture helpers from `tests/`.

Goal: if and only if the refactor is mechanical and low-risk, move reusable fixture-only helpers to a non-authority support module while keeping the exact deterministic contract.

Acceptance:
- fresh-clone reviewer preflight works without relying on test-package import layout;
- artifact schema and 14-stage order unchanged;
- no LIVE-provider behavior added.

### CDB-004 — reviewer/UI polish

Goal: improve competition dashboard readability without adding write controls or authority.

Preferred improvements:
- make provider mode, memory backend, authority boundary, receipt, independent verification, replay safety and Non-Zero contract-alignment legible at a glance;
- keep `TEST_FIXTURE`, `LIVE_COCKROACH`, `UNKNOWN`, `EXTERNAL_UNAVAILABLE` labels literal;
- preserve Authority Timeline as read-only projection.

Acceptance:
- endpoint/token protections unchanged;
- UI remains read-only for competition evidence;
- dashboard E2E regression green.

## P2 — post-submission maintenance unless elevated by a failing test

### CDB-101 — broad exception-handler inventory

Audit broad `Exception`/`BaseException` catches and convert only authority-sensitive ambiguous cases to typed fail-closed outcomes. Do not churn stable code without a reproduced failure.

### CDB-102 — transitional `MemoryStore` decomposition plan

Prepare a design/refactor plan for separating continuity/history/reasoning/vault concerns. Do not create a second memory engine and do not perform a large migration during final-week freeze.

### CDB-103 — stale/dead entrypoint map

Produce a static reachability/ownership map for legacy commands, orchestration helpers and providers before deleting anything. Preserve grant/history artifacts.

## External/operator-gated items — not autonomous Codex tasks

- OpenRouter LIVE: blocked until `OPENROUTER_API_KEY`, explicit live cost policy and bounded budget are operator-provided.
- live AWS Non-Zero: disabled and un-certified; do not enable for demo optics.
- DVM/pheromone/index promotion: remains `SHADOW`; no promotion in final-week sprint.
- optional contiguous 24h Gold Test: do not launch.
- push/merge/deploy/publish/submission/visibility changes: operator-only and currently forbidden.

## Required regression gates

After each coherent code batch:
1. run the smallest focused tests that prove the change;
2. run `git diff --check`;
3. rerun `scripts/nvidia_reviewer_preflight.py` if reviewer/competition surfaces changed.

After larger integration batches:

```bash
PYTHONPATH=runtime:tests /home/l/AIOA-Integration-Sandbox/.venv/bin/python -m pytest -q tests \
  --ignore=tests/cockroach/test_migration_gate.py \
  --ignore=tests/cockroach/test_rls_and_transactions.py \
  --ignore=tests/cockroach/test_vector_temporal.py
```

The three ignored Cockroach modules are separate explicit disposable certification gates; do not fabricate their required inputs.
