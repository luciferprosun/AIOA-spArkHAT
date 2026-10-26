# META-P1-02 Handoff — Offline browser adapter skeleton

- task_id: META-P1-02
- phase_status: PARTIAL
- source_sha: 1998eefd3f9be14cbc06edbe4016cf8148c11961
- changed_files (4 new, no edits to read-only files):
  - runtime/browser_agent/__init__.py
  - runtime/browser_agent/offline_adapter.py
  - tests/test_meta_p1_adapter.py
  - docs/meta/META_P1_02_HANDOFF.md

## What was built
Stdlib-only OFFLINE adapter reusing existing `CoreAdmission` and
`BrowserTaskV1`/`BrowserObservationV1`. Trusted fixture: one synthetic
bundled text (`FIXTURE_TEXT`), `FIXTURE_URL =
https://docs.example.org/offline-fixture`, captured-at
`2026-06-01T12:00:00Z`. `preview_task` wraps `screen_task`;
`read_fixture` requires caller-supplied `CorePrincipal` with
`Capability.READ` via `admission.require`, exact `OwnerScope`, matching
owner digest + source SHA, STOP/deadline screening, exact URL match,
bounded content, SHA-256 excerpt hash, and `screen_observation`
UNVERIFIED check. Observation is `status=OBSERVED`,
`environment=OFFLINE_FIXTURE` — a candidate, never DONE/VERIFIED/REAL.
Every `dispatch_allowed` is False. No browser/network imports.

## QA history
- Original Muse output: full Meta suite 71/72 at time of run; targeted
  `tests.test_meta_p1_adapter` 12/12. Reviewer independently verified
  72/72 before QA1. QA1 verdict (ChatGPT): model-generated security
  FIX REQUIRED — trust-binding weaknesses listed below. This security
  status stands until ChatGPT independently re-runs and clears it.

## QA1 security fixes (this change)
- `read_fixture` now binds caller-supplied `core_owner_scope_digest` to
  the actual admitted `OwnerScope` via existing
  `canonical_sha256(scope)` (same helper `warrant.py` uses), exact
  equality, fail closed. `screen_task` still independently matches
  `task.owner_scope_digest`. New adversarial test: task digest + supplied
  core digest both forged consistently while scope is real -> DENY.
- Gate check is now exact: `gate.effect is CORE_ADMISSION_REQUIRED`,
  anything else (DENY or any unexpected future effect) -> DENY.
- Fixture `captured_at_utc <= now` (trusted clock) enforced in addition
  to `<= deadline`; new future-capture test.
- `test_absent_principal_denied` now asserts exactly
  `OfflineAdapterDenied`; no broad `(Denied, Exception)` assertions remain.
- `test_no_browser_import` is now stdlib `ast`-based: parses the adapter
  source, collects static `import`/`from-import` top-level modules plus
  `__import__`/`import_module` string arguments, asserts banned bridge
  modules absent. No docstring-word scan, no `sys.modules` state.

## Executed tests (OFFLINE, no network/browser/packages)
- `python3 -m unittest tests.test_meta_p1_adapter -v`: 14/14 OK.
- `python3 -m unittest discover -s tests -p "test_meta_*.py"`: 74 tests OK
  (combined meta + P1 adapter, offline only).

## Unresolved risks / gaps
- Historical note: first Muse run did not recheck the combined suite after a docstring-only fix. In Muse QA1, the combined suite was rerun (74/74 PASS OFFLINE); ChatGPT independently repeated 74/74 PASS OFFLINE. This is not a LIVE browser result.
- No live Chromium exists anywhere in this change; nothing here may be
  presented as a real browser read.

## Next gate
META-P1-03 only after ChatGPT QA verifies and archives to private
RaportyMUSE. No auto-next.

## Independent QA acceptance (ChatGPT reviewer)

- **Audit verdict:** PASS for META-P1-02 OFFLINE skeleton only. Muse authored all Python implementation and tests. ChatGPT changed no Python source; only repaired the stale test-history sentence in this handoff.
- **Verified branch and scope:** separate `meta` checkout, starting commit `1998eefd3f9be14cbc06edbe4016cf8148c11961`, exactly four allowed new files, no inherited Core/MCP modifications.
- **Security checks:** `canonical_sha256(scope)` binding enforced, Core READ principal validated, unexpected screen effect denied, future fixture timestamps denied, no legacy browser imports, all dispatch flags false.
- **Independent tests:** `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_*.py' -q` → **74 PASS / 0 FAIL / 0 ERROR**, OFFLINE on Linux.
- **Still NOT verified:** real Chromium navigation, DNS-rebinding containment, real Meta Model API inside product, protected real-world effects or Android integration.
- **Next step:** only `META-P1-03` after archiving this QA result in private RaportyMUSE; do not auto-start additional prompts.
