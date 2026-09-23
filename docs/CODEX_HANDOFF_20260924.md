# AIOA spArkHAT — Codex Handoff — 2026-09-24

> NVIDIA-only continuation: first read the 2026-09-22 continuation section of [CODEX_BACKLOG.md](CODEX_BACKLOG.md) and [NVIDIA_DEMO_RUNBOOK.md](NVIDIA_DEMO_RUNBOOK.md). The earlier preparation SHAs below are historical. Check the actual current main/CI and do not resume EU drafting.

Prepared: 2026-09-22; updated by the bounded Sol final-polish sprint on 2026-09-23.

Public main before the Sol sprint: `730601488fbaf3ba63ebc2677a5828ee5cf8f1ba`.
Published Sol sprint PR: `#12`.
Current public main after that merge: `e3e050408856393b45668775beda5a42b9affe74`.
The local worktree path is intentionally not part of the public handoff contract.
Frozen certified product SHA remains: `ad4a425714a764f61f5ff22f2cc59f18abc36984`.

The older preparation branch/SHAs below are historical context. On 24 September,
start from the **actual current public main after checking GitHub CI**, not from
the old preparation worktree.

## Start here

Read in this order before changing code:

1. `docs/CODEX_BACKLOG.md`
2. `docs/PRE_CODEX_TECHNICAL_AUDIT.md`
3. `docs/CORE_ZERO_EPISTEMIC_CONTROL_FEASIBILITY_20260922.md`
4. `docs/ADVERSARIAL_FAILURE_REGRESSION_20260922.md`
5. `docs/REPRODUCIBILITY_REPORT.md`
6. `docs/reviewer/NVIDIA_REVIEWER_START_HERE.md`
7. `docs/NVIDIA_FINAL_WEEK_PROGRESS.md`
8. `docs/NVIDIA_NEMOTRON_OFFICIAL_AUDIT_20260923.md`
9. `docs/NVIDIA_GOLD24H_CONTEXT_CONTINUITY.md`

## Current accepted state

- segmented endurance: `SEGMENTED_ENDURANCE_PASS`, three accepted 8-hour windows; this is **not** a contiguous `24H_PASS_CLOSED` claim;
- frozen source SHA remains `ad4a425714a764f61f5ff22f2cc59f18abc36984`;
- competition vertical slice: 14 ordered stages from observe/evidence through guarded effect, independent verification, durable memory/audit and restart/replay;
- effect executor: `ServiceGuard`;
- duplicate effects: `0` in accepted deterministic reviewer evidence;
- restart replay dispatches: `0`;
- deterministic provider/memory fallback: truthfully labelled `TEST_FIXTURE`;
- Cockroach competition memory path exists separately as `LIVE_COCKROACH` / `learning-v1` when explicitly selected;
- DVM/pheromones: `SHADOW` only for competition;
- Non-Zero competition use: read-only/Core-native contract alignment, `nonzero_executor_invoked=false`;
- OpenRouter CPL preset prepared but LIVE remains operator-gated;
- live AWS remains disabled/un-certified;
- the reviewer preflight now emits a read-only `ATIF-v1.7` trajectory sidecar
  containing explicit visible events only;
- CDB-004 dashboard clarity is completed: ZERO_WRITE, Core + human authority,
  ServiceGuard, receipt/verification/replay and SHADOW dynamics are visible;
- the final sprint keeps exactly one canonical reviewer skill at
  `skills/evidence-audit/`; the older local `nvidia/evidence-audit-20260922`
  worktree and the earlier `aioa-nvidia-reviewer` name are superseded and must
  not reappear as parallel skills.

## Most recent accepted regression evidence

On the published 2026-09-23 Sol sprint (public main `e3e0504`):

- canonical offline full regression: **1041 PASS, 5 expected skips, 0 FAIL**;
- focused evidence-audit/trajectory/preflight/dashboard gate: **24/24 PASS** with the pinned ATIF validator enabled;
- deterministic reviewer preflight: **PASS**, 14 stages, zero duplicate effects,
  zero replay redispatch, `ServiceGuard`, `TEST_FIXTURE`, `SHADOW`;
- ATIF trajectory sidecar: **PASS**, `ATIF-v1.7`, 15 sequential visible
  steps (mission + 14 stages), no hidden reasoning export;
- NVIDIA SkillEvaluator Tier 1: **6/6 PASS**, quality **A 100/100** (one low advisory lint finding, non-blocking);
- Non-Zero focused regression with the isolated optional dependency set: **101/101 PASS**;
- `node --check web/app.js`: PASS;
- `git diff --check`: PASS.

Earlier adversarial/failure and Core Zero evidence remains preserved at its
recorded commits. Treat every test result as evidence for its exact source
state, not a promise that later changes remain green.

## Hard safety boundaries

Never modify:
- the frozen provider-repair certification worktree or its bound evidence roots;
- historical trial/evidence roots;
- separate frozen CockroachDB/Memory Patch evaluation repository;
- separate frozen Agents for Humans/Non-Zero evaluation repository.

Do not:
- create a second Core, scheduler, executor, memory engine or authority path;
- let provider/CPL/memory/DVM output authorize effects;
- promote DVM/pheromones from SHADOW;
- silently rewrite historical `UNKNOWN`;
- enable live AWS;
- make OpenRouter LIVE calls without key + explicit operator policy/budget approval;
- launch the optional 24h Gold Test **before** the final candidate is frozen,
  ordinary reviewer/CI gates are green, and the final-run checkpoint contract in
  `docs/NVIDIA_GOLD24H_CONTEXT_CONTINUITY.md` is satisfied;
- push, merge, deploy, publish, submit or change repository visibility without
  the operator's current authorization.

## Architecture decision

Hybrid Core decision is closed for this sprint:

- **GO**: one authoritative Core plus advisory/shadow epistemic control;
- **NO-GO**: dual authority or competing effect authority.

If a requested refactor appears to require a second authority path, stop and reframe it as advisory/read-only or leave it for post-submission design review.

## First Codex execution sequence

1. inspect actual public `main`, GitHub CI, `git status` and this handoff;
2. run deterministic reviewer preflight before edits and verify the ATIF sidecar;
3. do **not** redo CDB-004 or create a second reviewer/evidence-audit skill;
4. treat CDB-003 as optional; skip it unless a reproduced reviewer/packaging
   defect makes the refactor necessary;
5. add/adjust a failing test before any remaining behavior change where possible;
6. make one bounded reversible change at a time;
7. run focused tests and `git diff --check`;
8. rerun reviewer preflight if competition/reviewer surfaces changed;
9. preserve a clean final-candidate SHA before preparing the last Gold 24h run.

## Reviewer command

```bash
PYTHONPATH=.:runtime:tests python3 scripts/nvidia_reviewer_preflight.py
```

Expected interpretation: deterministic fixture evidence only. PASS here does not claim live NVIDIA, Cockroach, OpenRouter or AWS validation.

## Full offline regression command

```bash
PYTHONPATH=runtime:tests python3 -m pytest -q tests \
  --ignore=tests/cockroach/test_migration_gate.py \
  --ignore=tests/cockroach/test_rls_and_transactions.py \
  --ignore=tests/cockroach/test_vector_temporal.py
```

The excluded Cockroach tests are explicit disposable certification gates, not ordinary offline tests.

## Exit condition for Codex sprint

Return the branch to ChatGPT/operator review when:
- all accepted P1 work is committed locally;
- reviewer preflight is green;
- canonical offline full regression is green after the final coherent code batch;
- worktree is clean;
- no external/operator-only action was taken.
