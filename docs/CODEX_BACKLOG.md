# AIOA spArkHAT — Codex Backlog

Date: 2026-09-22
Branch: `codex/nvidia-final-week-20260921`
Preparation HEAD: `4d1099b`

## Operating rule

Codex should improve the existing one-system product, not redesign authority. Preserve one `AgentRuntime`, one final effect authority, `ServiceGuard` as the competition effect executor, human-bound approval, durable receipt/independent verification, and DVM/pheromones in `SHADOW`.

## NVIDIA-only continuation — 2026-09-22

The EU reviewer draft is paused and excluded from this NVIDIA batch. Published
baseline before this batch: `5eb9ab48c70fb47cef2da33416cf9c9a44f00348`.
Always read current Git/CI state rather than treating the preparation HEAD above
as the final candidate.

- CDB-001/CDB-002: bounded reviewer clarification and negative executor-construction
  regression added. No legacy implementation was deleted or authority changed.
- CDB-003: foreign-working-directory launch is hardened and tested without
  PYTHONPATH or credentials. Fixture helpers still live in `tests/`; moving that
  code remains a separate low-risk decision, not a completed refactor.
- CDB-004: bounded reviewer/dashboard clarity was completed in the 2026-09-23
  Sol final-polish sprint. The dashboard now makes provider mode, memory mode,
  ZERO_WRITE reuse, Core + human authority, receipt, independent verification,
  replay safety, ServiceGuard and SHADOW dynamics legible without adding write
  controls or approval shortcuts. Do not churn this surface unless a reproduced
  defect appears.
- Release rule for this authorized batch: publish by a non-destructive PR only
  after every CI check completes successfully for the exact head SHA. A mergeable
  or empty/pending check set is not a passing check set.

## Verified competition requirements — 2026-09-22

Read [NVIDIA_SUBMISSION_CHECKLIST.md](NVIDIA_SUBMISSION_CHECKLIST.md) before the final sprint. The organizer brief prioritizes a working long-running task, innovation and usefulness. The recorded prototype must demonstrate a useful outcome, not only a fixture test report. Finish that flow before optional refactors or extra benchmark work. No mandatory OpenClaw migration or continuous 24-hour test is stated in the fetched brief. Luma registration is not the Airtable project submission; final form acceptance remains an explicit release gate.

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

### CDB-004 — reviewer/UI polish — COMPLETED 2026-09-23

Completed:
- provider mode and memory backend remain literal;
- verified reuse is surfaced as `ZERO_WRITE`;
- the authority boundary is surfaced as `CORE + HUMAN` only when the
  evidence proves a human-bound effect authority and provider output has no
  authority;
- receipt, independent verification, restart recovery, ServiceGuard and
  DVM/pheromone `SHADOW` remain visible;
- Authority Timeline remains a read-only projection.

Acceptance evidence:
- endpoint/token protections unchanged;
- UI remains read-only for competition evidence;
- focused reviewer/trajectory/dashboard regression green;
- canonical full offline regression green after the batch.

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
- optional contiguous 24h Gold Test: do not launch during ordinary polish. It is
  reserved for the final frozen candidate only. Follow
  [NVIDIA_GOLD24H_CONTEXT_CONTINUITY.md](NVIDIA_GOLD24H_CONTEXT_CONTINUITY.md):
  authoritative state must be durable/checkpointed and must not depend on one
  Nemotron/operator conversation remaining open.
- deploy/submission/visibility changes: operator-only; no authorization is granted by this backlog.
- push/merge/publication: require an explicit current operator mandate. The NVIDIA-only reviewer batch above has that mandate, subject to all-green exact-SHA CI; it does not authorize unrelated releases.

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
