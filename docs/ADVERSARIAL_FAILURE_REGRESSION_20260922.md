# AIOA spArkHAT — Adversarial / Failure Regression — 2026-09-22

## Scope and safety boundary

This phase tests the existing NVIDIA competition path after the accepted 3×8 h segmented endurance closure. It does not modify the frozen certification worktree or historical evidence, does not enable live AWS/OpenRouter, does not promote DVM/pheromones from SHADOW, and does not add a scheduler, executor, memory engine, or authority path.

## Baseline before the adversarial fix

The canonical offline repository suite completed **1015 PASS, 4 expected skips, 0 FAIL** in 555.92 s with only the three explicitly provisioned Cockroach certification modules excluded. Those three modules remain a separate fail-closed live/disposable gate.

## Adversarial matrix

| Surface | Tests / evidence | Result |
| --- | --- | --- |
| provider malformed/timeout/quota/UNKNOWN/manual replay | `test_provider_safety_recert.py` | PASS |
| owner/tenant isolation, stale/revoked memory | `test_nv07_isolation.py` | PASS |
| consent/revocation/stale target/duplicate delivery/lost ACK/crash | `test_nv09_service_guard.py` | PASS |
| expiry/A-B-A revision/poisoning/recovery/lease handoff | `test_nv10_guard.py` | PASS |
| corrupt checkpoint / UNKNOWN recovery envelope | `test_nv10_recovery.py` | PASS |
| evidence boundary / action-result containment | `test_executor_containment.py`, `test_evidence_boundary.py`, `test_evidence_write_contract.py` | PASS |
| memory layer authority separation | `test_memory_layer_isolation_smoke.py` | PASS |
| Non-Zero Core-native authority / replay / corruption | `test_nonzero_core_authority.py` | PASS |
| read-only competition evidence / evaluation / timeline | `test_competition_view.py`, `test_competition_evaluation.py`, `test_authority_timeline.py` | PASS after AFR-001 fix |

## AFR-001 — strict evidence scalar typing

Severity: **P1, fixed in this phase**.

A bounded adversarial fixture showed that JSON booleans in `receipt_effect_count` and `independent_measurement_effect_count` were accepted because Python boolean values compare equal to integers (`True == 1`). Before the fix, the forged artifact projected `READY` and the competition evaluation returned `PASS`. `safety.duplicate_effects` had the analogous `False == 0` ambiguity. Receipt/measurement digests were also checked for length but not hexadecimal shape.

The fix strengthens only the read-only evidence boundary:

- receipt and independent-measurement counts must be exact non-negative integers, never booleans;
- projected effect/safety flags must be exact booleans;
- `duplicate_effects` must be an exact non-negative integer;
- receipt and measurement digests must be exactly 64 hexadecimal characters.

No runtime execution, authority, scheduler, provider, memory, or Service Guard behavior changed.

## Validation

Focused competition/evaluation/preflight regression after the fix: **21/21 PASS**.

Bounded adversarial/failure suite across provider, NV07, NV09, NV10, evidence boundaries, Non-Zero and competition projections: **141/141 PASS** in 142.86 s.

Canonical offline full regression after the fix: **PENDING**.

## Acceptance rule

Accept the phase only if the canonical offline full regression remains green, `git diff --check` passes, the competition worktree contains only the intended reversible changes, and the frozen certification tree remains untouched at `ad4a425714a764f61f5ff22f2cc59f18abc36984`.

## Final acceptance

Canonical offline full regression after AFR-001 completed **1019 PASS, 4 expected skips, 0 FAIL** in **555.07 s** with the same three explicit disposable Cockroach certification modules excluded.

`git diff --check` is required immediately before commit. The frozen certification worktree must still be clean at `ad4a425714a764f61f5ff22f2cc59f18abc36984`.

Phase 4 acceptance: **PASS**, subject only to those final repository hygiene checks. No architecture expansion was introduced; AFR-001 is a bounded read-only evidence-validation hardening change.
