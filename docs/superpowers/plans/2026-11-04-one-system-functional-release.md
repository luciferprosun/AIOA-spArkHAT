# AIOA One System Functional Release Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans task by task. ROOT alone writes and tests; at most two lightweight reviewers work read-only.

**Goal:** Improve the existing Native Mission Control into an independently launchable, truthful Linux application while preserving the existing Core and Android identity.

**Architecture:** Extend the current private operator transport, existing Web UI and bounded provider contracts. Reuse the existing Core records and governor; do not introduce another authority model, runtime, journal or frontend.

**Tech Stack:** Python, existing SQLite Core records, vanilla JavaScript/CSS, existing Chrome console, Jetpack Compose unchanged.

**Spec:** Owner PDF `AIOA_spArkHAT_ULTRA_SWARM_ONE_SYSTEM_FUNCTIONAL_RELEASE_2026-11-04 (1).pdf`, received 2026-11-04. Private source evidence remains outside Git.

## Global Constraints

- Baseline main: `23caa63619057b48c6b239ec0b5b946f1913e808`; existing branch only.
- Active Native checkout and state remain untouched during development.
- No paid inference, public GitHub mutation, deployment/restart or APK installation without its concrete owner gate.
- No new APK unless Android changes are necessary; no pairing reset, key export, session deletion or stale database rollback.
- Preserve UNKNOWN, reservations, expiry, source seals, TLS, PolicyKit, Tailscale and exact financial approval.
- GitHub WRITE, CPL LIVE and autonomous worker remain blocked without actual execution and receipt gates.

## Review Focus

- Unrelated background reads cannot recover an uncertain mutation or enable its duplicate.
- Lease renewal cannot revive old web grants, warrants or pending spending approvals.
- A previous-source or expired READ receipt cannot become model authority or current evidence.
- Polling cannot select stale UNKNOWN over a fresh conversation or discard a draft/scroll position.
- A launcher cannot start a second Core or silently substitute an empty state directory.

### Task 1 — Independent UI state and chat history

Files: `web/mobile_devices.js`, `web/mobile_chat.js`, `web/mobile_devices_dom.js`, `web/index.html`, `web/styles.css` (actual stylesheet located before editing); tests `tests/mobile_devices.test.cjs`, `tests/mobile_chat.test.cjs`.

- [x] RED: lost pairing approval ACK followed by successful `chat_catalog` remains UNKNOWN and denies another mutation.
- [x] Fix only relevant readback recovery; retain token/generation/duplicate barriers.
- [x] RED: fresh successful thread is the initial choice while manual historical selection and drafts survive refresh.
- [x] Fix polling busy/focus/scroll, ten existing navigation destinations, bounded chat history and composer.
- [x] GREEN: targeted Node suite and contained browser verification.

### Task 2 — Existing private operator lease lifecycle

Files: `runtime/meta_hackathon/runtime_adapter.py` (existing owner lifecycle), `runtime/mobile_gateway/operator_chat.py`, `runtime/webapp.py`; new focused tests and existing transport/source-seal tests.

- [x] RED: status separates AUTH_REQUIRED from OFFLINE; renewal requires actual local PolicyKit and exact source/instance/revision.
- [x] Add closed private-socket operations only; re-use Core records/CAS and governor epoch; invalidate old browser grants before publishing a renewed lease.
- [x] Test cancellation, source drift, replay, ACK loss, active worker/read serialization, preserved pairing/UNKNOWN/budget and absence of model calls.
- [x] GREEN and independent security review before deployment.

### Task 3 — Checkout-bound desktop command

Files: existing `runtime/webapp.py` CLI and a small `runtime/mobile_gateway/desktop.py`, local desktop template/icon as appropriate; source capsule and focused launcher tests.

- [x] RED: existing healthy host opens the same console; expired host reports/renews authentication; no host never creates a new state silently.
- [x] Reuse existing Native startup and Chrome console, one command and documented desktop installation without secrets or elevated privileges.
- [x] GREEN: no second instance, exact state/source binding, path quoting, absent GUI and offline diagnostics.

### Task 4 — Verified READ context and truthful capabilities

Files: existing `runtime/meta_hackathon/native_tools.py`, `chat.py`, `runtime/providers/meta_model_api.py`, existing CPL preset module and Web projections; focused provider/chat/native-tool tests.

- [x] RED: signed current Core READ can be referenced as bounded untrusted data in an exact existing financial approval; forged/stale/mismatched receipts fail before provider transport.
- [x] Preserve v1 requests; add explicit versioned context only as needed and bind it in the existing request digest.
- [x] Expose pure CPL preview and separate Core records, MemoryPatch and Cockroach statuses without executing jobs or discovering secrets.
- [x] GREEN: offline only; no model calls or new authority grants.

### Task 5 — Acceptance and release evidence

- [x] Sequential targeted and authority/source/packaging regressions; no Android build if unchanged.
- [x] Independent read-only code review; fix findings and rerun affected checks.
- [x] Produce the seven owner-required reports, capability registry, runbook and exact source/diff/test references; truthful historical versus current/physical evidence.
- [ ] Prepare concrete owner gates for publication, exact-head CI/merge and deployment; no self-approval.
- [ ] Following approved deployment, real Chrome QA and owner-assisted Android signed status/reconnect. Stop only at physical interaction or concrete external authorization.

Rollback: revert only this phase's commits or restore its exact pre-change file versions in staging. For deployment use a separately approved prior source with the same current state; never restore an old database over current authority, budget or UNKNOWN records.

### Owner budget update — local financial policy only

- Replace the fixed chat ceiling with an explicitly reviewed total allocation, at most USD 148, in the existing governor state chain. Keep the immutable bootstrap digest and all prior OPERATION/AUDIT/OUTBOX bytes. Preserve UNKNOWN, historical exposure, risk, circuits, kill, one attempt and exact paid-message approval.
- Financial-policy v2 increments the epoch and requires a Native authority guard inside the transaction. A stale, forged or replayed review cannot apply a second transition.
- The provider does not expose a documented credit-balance endpoint used by this integration. Optional Native owner dashboard attestation is explicitly OWNER_ATTESTED, binds current source/instance/policy/key metadata and expires after 300 seconds; it is not API-verified balance or a provider hard cap. No new paid calls were made.
- No attestation means credit-only chat remains blocked. Renewal/restart/expiry clears or invalidates it. Currency configuration does not approve inference. Only LINUX_OWNER chat can use the expanded ceiling; Android mobile v1 and MetaPlan retain USD 0.05 at proposal, provider and receipt boundaries.
- Once v2 is applied, use a v2-capable reader for rollback; do not restore old records or start an incompatible governor over new history.

### Verification evidence

The first full local run completed: 2,765 tests, 13 failures, 1 error and 5 allowed skips. Preserve that result as FAILED. Eleven subprocess cases lacked the absolute inherited source/dependency path; the remaining causes were user-environment leakage into a Nebius fixture, the v1 English provider policy text, and a disappearing /proc cleanup observer. All fourteen exact failed cases passed their isolated final retest. Final targeted suites cover subsequent authority, money-policy and UI changes; do not represent their results as a second full-suite run.

Contained Chrome geometry passed eight width/font scenarios; these are TEST_ONLY, without production effects or networking. Exact-head remote CI and production/physical acceptance remain pending the concrete owner gates.
