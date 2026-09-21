# AIOA spArkHAT — Module Readiness Audit

Date: 2026-09-21
Branch: codex/nvidia-final-week-20260921
Baseline/frozen certification SHA: ad4a425714a764f61f5ff22f2cc59f18abc36984

## Executive result

The three requested modules already exist in the one-system AIOA codebase and
their core contracts are healthy. The remaining work is composition and
competition presentation, not reimplementation.

### 1. Critical Prompt Loop + OpenRouter observers

Status: READY_FOR_LIVE_KEY / LOCAL CONTRACT PASS

Verified:
- CPL contract is `cpl-1plus3plus1-v1`.
- Exact sequence is primary draft -> observer-1 -> observer-2 -> observer-3 ->
  primary revision.
- Observer slots and roles are fixed and bounded:
  - Logic & Claims
  - Safety & Authority
  - Evidence & Consistency
- All observer output is `ADVISORY_ONLY` and cannot approve, execute, write
  memory or promote knowledge.
- LIVE execution requires an explicit immutable plan, plan hash, nonce, local
  approval and budget admission.
- Strict OpenRouter path uses exactly
  `https://openrouter.ai/api/v1/chat/completions`.
- Exact model identity is required; auto/free routing aliases are intentionally
  rejected by the strict CPL path.
- Existing CPL test suite: 138/138 PASS.

Prepared free binding:
- Primary: `minimax/minimax-m3:free`
- Observer 1: `google/gemma-4-26b-a4b-it:free`
- Observer 2: `google/gemma-4-31b-it:free`
- Observer 3: `qwen/qwen3.8-27b:free`

The exact four-model binding was executed through the local CPL fixture:
- COMPLETED
- generation_requests = 5
- reviews = 3
- final revision present
- shared_model_for_roles = false

Blocker:
- No `OPENROUTER_API_KEY` is currently detected on this Linux host.
- Supported local secret paths exist in code, but both are currently absent.
- No live OpenRouter call was made.

Runbook:
- `docs/OPENROUTER_CPL_3_FREE_OBSERVERS.md`

## 2. CockroachDB Memory Patch

Status: CORE + LIVE DATABASE HEALTHY

Verified unit/integration contracts:
- Memory Patch focused suite: 150/150 PASS.
- Current disposable Cockroach target is reachable.
- CockroachDB CCL v26.2.5.
- 19/19 schema migrations APPLIED.
- schema certificate = READY.
- certificate manifest digest matches `learning-v1`.
- 22 tables are present in the `aioa_memory_patch` schema.
- The active segmented endurance monitor independently checks Cockroach health
  every five minutes.

Important gap for the NVIDIA demo:
- the current deterministic competition demo memory episode uses
  `repository-durable-test` through `tests/nv05_demo.py`;
- therefore the Cockroach module is healthy, but the final competition
  trajectory does not yet prove that its visible memory episode is backed by
  Cockroach.

Required final-week action:
- add a bounded Cockroach-backed competition memory composition using the
  existing Memory Patch / learning-v1 contracts and a disposable demo scope;
- keep the deterministic repository fixture as an explicit offline fallback;
- expose the selected backend truthfully in demo evidence and dashboard;
- never copy a second memory engine or create a second authority path.

## 3. Agents for Humans / Non-Zero CloudOps

Status: CORE_NATIVE / AVAILABLE / PORTABLE PASS

Module descriptor:
- contract: `nonzero-native-v1`
- implementation: `CORE_NATIVE`
- mode: `portable`
- provider: `mock`
- available: true
- missing requirements: none
- authority: `EXPLICIT_HUMAN_APPROVAL_SYNTHETIC_ONLY`
- live AWS: disabled
- external models: disabled
- CLI: `/nonzero`
- API: `/api/nonzero`

Capabilities already present:
- investigate
- propose
- request approval
- record decision
- execute approved portable effect
- verify
- inspect evidence

Verification:
- Non-Zero suite: 101/101 PASS.
- Core/web tests prove no implicit approval, hash-bound human decision,
  idempotent execution, durable receipt, verification and restart/replay
  behavior.

Competition rule:
- keep portable/mock mode for the NVIDIA submission unless a separately
  certified live backend becomes necessary.
- Do NOT enable live AWS merely for demo optics.
- Reuse Non-Zero as evidence of human-bound authority; do not create a second
  effect executor alongside Service Guard.

## Recommended one-system composition

Competition trajectory should show:

1. bounded observation / Knowledge HAT evidence
2. primary proposal
3. CPL with three OpenRouter observers (when live key is available)
4. Core decision — observers remain advisory
5. Memory Patch write/reuse backed by Cockroach in live demo mode
6. explicit human approval
7. one guarded disposable effect
8. durable receipt + independent verification
9. restart/replay with zero duplicate effect
10. Non-Zero / Agents-for-Humans authority evidence shown as the existing
    human-bound domain contract, not as a second Core

## Priority

P0:
- integrate Cockroach-backed demo memory path;
- preserve deterministic offline fixture fallback;
- keep 3x8 endurance untouched.

P1:
- once operator provides an OpenRouter key, run one bounded live CPL smoke with
  the prepared four-model binding;
- expose a simple UI selector/preset for CPL enabled vs plain mode and show the
  three observer identities.

P2:
- expose Non-Zero readiness/approval/receipt status in the competition
  dashboard if it can reuse the existing read-only projection without adding
  another authority path.

No feature in this audit requires modification of the frozen certification
worktree.
