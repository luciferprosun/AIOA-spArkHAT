# META-P1-03 Handoff — Offline state-machine repair (Muse Code)

- Task: META-P1-03-QA1, scoped FIX only. No further phases.
- Source SHA: 259a93c6de6867fb267b488bd008ef322365ec74 (branch meta).
- Changed files (only):
  - `runtime/browser_agent/offline_state.py` (untracked, created this phase)
  - `tests/test_meta_p1_state.py` (untracked, created this phase)
  - `runtime/browser_agent/__init__.py` (modified: re-exports offline_state symbols)
- New doc: `docs/meta/META_P1_03_HANDOFF.md` (this file).

## Initial failed test counts (independent QA)

- Command: `python3 -B -m unittest discover -s tests -p 'test_meta_p1_*.py' -v`
- Result: 26 tests, 3 failures, no errors.
- Failures:
  - test_success_preview_observe: actual DENIED, expected OBSERVED
  - test_stale_stop_after_observed: actual DENIED, expected OBSERVED
  - test_concurrent_task_isolation: actual DENIED, expected OBSERVED

## Root cause

- Fixture times: NOW=2026-06-01 13:00Z, INITIAL=NOW-2s, CAPTURED="2026-06-01T12:00:00Z".
- CAPTURED was one hour BEFORE INITIAL, so the production pre-start guard
  (`captured < initial_utc` → DENIED) correctly denied all three observations.
- Fault was in the synthetic fixture, not the production logic.

## Corrections

1. `tests/test_meta_p1_state.py`: CAPTURED fixed to `"2026-06-01T12:59:59Z"`
   (>= INITIAL 12:59:58Z and <= NOW 13:00Z). Pre-start denial untouched.
2. `runtime/browser_agent/offline_state.py` (`observe`): added future-capture
   guard — after the existing timeout/deadline check and pre-start check, a
   captured timestamp later than trusted `now` moves to DENIED (never OBSERVED).
3. `tests/test_meta_p1_state.py`: added adversarial regression test
   `test_future_capture_denied` (capture NOW+60s → DENIED, state stays DENIED).
4. STOP/cancel/replay/redirect logic and all denials preserved; no live browser
   imports (stdlib only), no model authority, `dispatch_allowed=False`,
   per-task instance state only (no shared mutable task state).

## Final exact tests + counts (OFFLINE, labelled)

- OFFLINE suite 1:
  `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_p1_*.py' -q`
  → Ran 27 tests, OK (26 fixed + 1 new regression test).
- OFFLINE suite 2:
  `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_*.py' -q`
  → Ran 87 tests, OK.

## Still no Chromium LIVE

- No Chromium, no live browser tools, no network, no API probes. Offline
  fixture only (`OFFLINE_FIXTURE`, `dispatch_allowed=False`).

## Phase status / next gate

- phase_status: META-P1-03 complete, awaiting independent QA.
- next_gate: META-P1-04 only after ChatGPT independent QA. No further action.
