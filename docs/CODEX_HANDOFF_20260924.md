# AIOA spArkHAT — Codex Handoff — 2026-09-24

Prepared: 2026-09-22
Competition worktree: `/media/l/LSC_DATA1/AIOA_NVIDIA_FINAL_WEEK_20260921`
Branch: `codex/nvidia-final-week-20260921`
Preparation HEAD at handoff drafting: `4d1099b`
Frozen certified product SHA: `ad4a425714a764f61f5ff22f2cc59f18abc36984`

## Start here

Read in this order before changing code:

1. `docs/CODEX_BACKLOG.md`
2. `docs/PRE_CODEX_TECHNICAL_AUDIT.md`
3. `docs/CORE_ZERO_EPISTEMIC_CONTROL_FEASIBILITY_20260922.md`
4. `docs/ADVERSARIAL_FAILURE_REGRESSION_20260922.md`
5. `docs/REPRODUCIBILITY_REPORT.md`
6. `docs/reviewer/NVIDIA_REVIEWER_START_HERE.md`
7. `docs/NVIDIA_FINAL_WEEK_PROGRESS.md`

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
- live AWS remains disabled/un-certified.

## Most recent accepted regression evidence

- canonical offline full regression after adversarial hardening: **1019 PASS, 4 expected skips, 0 FAIL**;
- adversarial/failure suite: **401/401 PASS**;
- Core Zero / epistemic-control focused gate: **91/91 PASS**;
- reviewer focused gate: **21/21 PASS**;
- fresh-clone deterministic reviewer preflight: **PASS**, 14 stages, zero duplicate effects, zero replay redispatch, `ServiceGuard`, `TEST_FIXTURE`, `SHADOW`.

Treat these as evidence at the recorded commits, not a promise that later changes remain green.

## Hard safety boundaries

Never modify:
- `/home/l/.local/worktrees/aioa-provider-repair-recert-20260919T072933Z`;
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
- launch the optional 24h Gold Test;
- push, merge, deploy, publish, submit or change repository visibility.

## Architecture decision

Hybrid Core decision is closed for this sprint:

- **GO**: one authoritative Core plus advisory/shadow epistemic control;
- **NO-GO**: dual authority or competing effect authority.

If a requested refactor appears to require a second authority path, stop and reframe it as advisory/read-only or leave it for post-submission design review.

## First Codex execution sequence

1. inspect `git status`, current HEAD and this handoff;
2. run deterministic reviewer preflight before edits;
3. take only the first unblocked P1 item from `docs/CODEX_BACKLOG.md`;
4. add/adjust a failing test before behavior changes where possible;
5. make one bounded reversible change;
6. run focused tests and `git diff --check`;
7. rerun reviewer preflight if competition/reviewer surfaces changed;
8. commit locally with a precise message;
9. continue to the next backlog item only after the worktree is clean.

## Reviewer command

```bash
PYTHONPATH=.:runtime:tests python3 scripts/nvidia_reviewer_preflight.py
```

Expected interpretation: deterministic fixture evidence only. PASS here does not claim live NVIDIA, Cockroach, OpenRouter or AWS validation.

## Full offline regression command

```bash
PYTHONPATH=runtime:tests /home/l/AIOA-Integration-Sandbox/.venv/bin/python -m pytest -q tests \
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
