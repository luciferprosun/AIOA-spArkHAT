# AIOA spArkHAT — Roadmap 2.1 Closure

Date: 2026-09-21 / 2026-09-22 UTC boundary

Active competition branch: `codex/nvidia-final-week-20260921`

Certification baseline: `ad4a425714a764f61f5ff22f2cc59f18abc36984`

Post-endurance closure commit: `3d28896c0da83dfced318c3d491fcc5724b26d0a`

## Verdict

Roadmap 2.1 is **functionally closed for the NVIDIA competition path with explicit preserved limitations**. This does not rewrite the original NV12 contract: the original contiguous 24-hour trial never reached `PASS_CLOSED`. The replacement endurance qualification is exactly `SEGMENTED_ENDURANCE_PASS` (`3 × 8 h`).

The closure does not promote SHADOW-only dynamics, enable live AWS, claim OpenRouter LIVE validation without operator authorization, create a second authority path, or rewrite historical `UNKNOWN` outcomes.

Allowed status vocabulary: `PASS`, `PARTIAL`, `SHADOW`, `BLOCKED_EXTERNAL`, `NOT_APPLICABLE`, `NOT_IMPLEMENTED`.

## NV01–NV12 closure matrix

| Stage | Requirement | Implementation / tests | Evidence / commit | Status | Limitations |
| --- | --- | --- | --- | --- | --- |
| NV01 | Mission/Core foundation, inspection and trust boundaries | `docs/nv01/FOUNDATION.md`; `test_nv01_foundation.py`, `test_nv01_advisory.py` | `38df1c3` | PASS | Inspection foundation grants no execution authority. |
| NV02 | Read-only LITE runtime plus bounded NVIDIA provider adapter | `docs/NV02_LITE_RUNTIME.md`; `test_nv02_lite.py`, `test_nv02_http.py`; provider safety recertification | `88733b7`; frozen lineage ending at `ad4a425` | PASS | Hosted provider availability remains external to deterministic demo readiness. |
| NV03 | Native scoped Memory Patch composition in LITE | `docs/NV03_MEMORY_INTEGRATION.md`; `test_nv03_memory.py`; competition Cockroach composition | `a51a93f`; `9244a05` | PASS | Repository-durable fallback is never relabeled as Cockroach. |
| NV04 | Original CPL plus independently verified epistemic deltas | `docs/NV04_CPL_LEARNING.md`; `test_nv04_learning.py`; CPL regression and competition preset | `9614dea`; `5b0b7f1` | PASS | LIVE OpenRouter remains `BLOCKED_EXTERNAL` until key, live-cost policy and bounded budget are explicitly authorized. |
| NV05 | Bounded MemoryDynamics, dual pheromone signals, DVM selection and durable revalidation | `docs/NV05_DYNAMICS.md`; `test_nv05_shadow.py`, `test_nv05_active.py`; three-process demo | `f994ca4`; competition SHADOW enforcement `e71a54a` | SHADOW | Controlled ACTIVE is contract-test-only; production/competition behavior is fail-closed SHADOW. |
| NV06 | Personal verified-delta contracts, consent, scope, privacy and one-repair budget | `docs/NV06_PERSONAL_DELTA_CONTRACT.md`; `test_nv06_personal.py`, `test_nv06_profile_compatibility.py` | `fa612a1` | PASS | Auto behavior remains scope/consent/evidence gated; UNKNOWN does not restore actor-repair budget. |
| NV07 | Private correction loop and owner isolation with restart-safe repair reservation | `test_nv07_chat.py`, `test_nv07_isolation.py`; G07 recovery evidence | `426cba4`; later G07 repairs | PASS | Historical provider UNKNOWN is preserved; ambiguous outcomes do not gain hidden retry. |
| NV08 | Compact owner-scoped pheromone index plus Cockroach live separation | `docs/NV08_COMPACT_PHEROMONE_INDEX.md`, `docs/NV08_TEST_MATRIX.md`; index/migration tests | `72d78ad`; `f19b89e` | SHADOW | Compact index ordering remains SHADOW; fixture evidence is never substituted for live DB proof. |
| NV09 | Guarded service effect with human approval, durable receipt and independent verification | `docs/NV09_GUARDED_SERVICE.md`; `test_nv09_service_guard.py` | `0360a7c` | PASS | Service Guard remains the sole competition effect executor. |
| NV10 | Revocation, crash/recovery, replay/idempotency and UNKNOWN hardening | `docs/NV10_ADVERSARIAL_HARDENING.md`; guard/memory/recovery tests | `9c1c39b`; 48/48 Service Guard + NV10 gate | PASS | Failure semantics remain fail-closed; no silent replay authorization. |
| NV11 | Reproducible memory/pheromone value benchmark | `docs/NV11_MEMORY_VALUE_BENCHMARK.md`; `tests/nv11_benchmark.py`, `test_nv11_benchmark.py` | `834e7dc` | PASS | Benchmark did not justify product promotion; ACTIVE remains test-only. |
| NV12 | Provider-repair recertification, functional scenario closure and endurance qualification | preserved S1–S8 evidence; segmented 3×8 monitor/closure | `ad4a425`; closure `3d28896` | PARTIAL | Functional semantics accepted with preserved external-provider risk; original contiguous 24 h remains false; replacement is exactly `SEGMENTED_ENDURANCE_PASS`. |

## NV12 preserved evidence

The frozen source binds SHA `ad4a425714a764f61f5ff22f2cc59f18abc36984`, source digest `a90dd64d8f028ce3b194e01d955561c20e173cc4d09a9854df550fd0367a12e4` and evidence digest `a7c05e24c23a713d38d957095d67c249ef11b004af783ba61ebc34006d0687c3`. The preserved certification worktree remained clean.
`reports/FUNCTIONAL_CLOSURE.json` preserves S1/S2/S3/S5/S8 PASS semantics, S4 `PASS_AFTER_HARNESS_REPAIR`, S6 `FUNCTIONAL_PASS_PROVIDER_LIVE_UNKNOWN_PRESERVED`, and S7 `BLOCKED_EXTERNAL_ACCEPTED_SEMANTIC`. It deliberately records the original contiguous pass as false and does not manufacture NV12B live cloud-effect proof.

## Segmented endurance closure

`docs/ENDURANCE_3X8_CLOSURE.md` and `reports/SEGMENTED_ENDURANCE_3X8_MANIFEST.json` bind the immutable endurance evidence:

- Segment 1: 28,898.455834 attested active seconds — PASS.
- Segment 2: 28,909.535110 attested active seconds — PASS.
- Segment 3: 29,029.012337 attested active seconds — PASS.
- Combined: 86,837.003281 s against 86,400 s required.
- Recorded downtime: 0 s.
- Source/evidence integrity: PASS; frozen worktree clean.
- Cockroach: PASS / READY / 19 migrations.
- Segmented monitor provider calls: 0.

Classification is **SEGMENTED_ENDURANCE_PASS** only, never `24H_PASS_CLOSED`.

## Current competition-path overlay

Post-certification competition work remains isolated on the active branch. Current accepted hardening includes the explicit 14-stage one-system trajectory, read-only evidence projection, Authority Timeline, Cockroach `learning-v1` competition memory with truthful repository fallback, fail-closed OpenRouter preset, Non-Zero read-only contract alignment with live AWS disabled, and enforced SHADOW dynamics. None of these retroactively mutate frozen certification evidence.
Accepted current competition evidence also includes:

- production NVIDIA adapter recovery validation: HTTP 200, `finish_reason=stop`, strict `VALID`, one-use permit, no effect authority;
- Cockroach-backed competition memory: `cockroachdb-learning-v1`, 19 migrations, verified write → `ZERO_WRITE` reuse → stale revalidation, durable receipt and replay-safe restart;
- Non-Zero projection: `CORE_NATIVE`, portable/mock, read-only alignment, live AWS disabled, Non-Zero executor not invoked;
- canonical full regression after SHADOW hardening: **1017/1017 PASS**, plus 4 expected optional UI skips;
- reviewer preflight canonical gate: **62/62 PASS**.

## Explicit non-claims carried forward

1. Do not claim contiguous 24-hour certification; use `SEGMENTED_ENDURANCE_PASS`.
2. Preserve historical NVIDIA `UNKNOWN` outcomes and external hosted-inference availability risk.
3. Keep DVM/pheromones and compact-index behavior in SHADOW for competition/product claims.
4. Keep OpenRouter LIVE blocked until explicit operator key, live-cost policy and budget authorization.
5. Keep live AWS disabled/un-certified; Non-Zero is contract-alignment/readiness only and Service Guard remains sole effect executor.
6. Do not infer Cockroach LIVE from repository fixture tests; keep backends truthfully labeled.
7. No provider, critic, memory score, pheromone value or benchmark output gains execution authority.

## Closure decision

NV01–NV11 are accepted under their documented boundaries. NV12 remains `PARTIAL` relative to its original contiguous-24-hour contract, while the replacement endurance evidence is accepted as `SEGMENTED_ENDURANCE_PASS`. This is sufficient to proceed to post-3×8 technical audit, adversarial/reproducibility hardening and reviewer preparation without falsifying the historical contract.

A future true `1×24 h` Gold Test is optional and should run only on the final frozen submission candidate SHA with adequate schedule buffer.