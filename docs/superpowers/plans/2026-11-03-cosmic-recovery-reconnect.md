# Cosmic Recovery & Reconnect Implementation Plan

> For agentic workers: execute the approved PDF task by task with superpowers:executing-plans. Review the resulting client changes independently before deployment.

**Goal:** Restore a verified read-only session automatically from the existing approved host binding, without repeating an uncertain pairing or session mutation.

**Architecture:** Extend the existing Android MissionViewModel and MobileClient only. A small JVM-testable SessionRecovery helper sequences existing host proof, session challenge/reconnect and signed status; public retry hints live in the existing mobile-ui-v1 preferences. It grants no authority. Native Core, state root, device approval and protocol TTLs remain unchanged.

**Tech Stack:** Existing Kotlin2.2.21/Compose/Android26+, Coroutines, OkHttp4.12.0, Python Core and existing APK verification tools.

**Spec:** /home/l/Downloads/AIOA_Cosmic_Recovery_Reconnect_CODEX_2026-11-03.pdf

## Global constraints

- Preserve installed package, Android Keystore identity, public binding shape and owner approval.
- No automatic retry of pairing/begin, approve, complete, WRITE or an unacknowledged session POST.
- Before the first session POST persist an uncertainty hint bound to the exact existing public record; clear it only after signed readback is accepted and the binding owner is still current.
- Two attempts with one 1000ms backoff for safe host/status reads only; each attempt calls existing code and creates fresh signed request nonces. No retries for TLS, signature, host mismatch, denial or cancellation.
- At most two consecutive automatic wakeups per failed recovery episode; only a verified signed readback or a new foreground interval resets that budget; callbacks are coalesced by the existing single-flight task lock. Offline callbacks send no requests. Uncertain POST requires a manual action after process restart.
- Keep existing 8s connect/read/call bounds: the proven failure was missing Connection:close, not slow transport. Do not extend crypto TTLs.
- Preserve prior diagnostics and active Core checkout. No paid APIs, GitHub WRITE, merge, global install, uninstall, data clear or key reset.
- New APK versionCode4/versionName0.3.1-cosmic; same signing certificate is mandatory. If signing key is unavailable, source/tests can proceed but installation remains BLOCKED.

## Review focus

1. Expired invitation must not block a trusted persisted binding, including restart after token expiry.
2. No infinite reconnect loop on resume/network callbacks or repeating an unknown session mutation.
3. No stale foreground job can publish FRESH after background/forget/rebind; owner revision and freshness generation remain authoritative locally.
4. General connectivity/VPN presence does not prove Tailscale reachability: display a network hint, never fake online/approved status.
5. Partial success/lost ACK, host mismatch, revoked access and clock/signature failures remain fail-closed. Old APK cannot be replaced by a different signer.

## Task 1 — Recovery sequence, RED/GREEN

Files: new SessionRecovery.kt and SessionRecoveryTest.kt in the existing companion package.

- [ ] Write tests for expired invite with trusted binding, missing approval, in-memory session reuse, expired token, offline/online, process restart and persisted uncertainty, bounded safe-read backoff, cancellation, host conflict, rejection, unknown POST and signed-readback failure.
- [ ] Run RED with the existing verified Kotlin compiler/JUnit; preserve actual failures.
- [ ] Implement SessionRecoveryPort<T>, RecoveryCheckpoint and SessionRecovery<T> using existing protocol operations. Result acceptance clears only the bound hint.
- [ ] Run GREEN. These are explicitly offline unit tests, not physical E2E.

## Task 2 — Existing ViewModel/lifecycle/UI binding

Files: MissionViewModel.kt, MobileClient.kt, new RecoveryNetworkMonitor.kt, CosmicScreen.kt, existing EN/PL strings, existing localization tests.

- [ ] Wire automatic recovery only for trusted persisted records on foreground/network return. Use existing mutex and pairing task. Preserve signed freshness and owner checks after every await.
- [ ] Keep manual recovery for uncertain complete/session outcomes. Block automatic mutation replay across restart using existing preferences.
- [ ] Reuse live in-memory session for safe status; otherwise prove host, issue one fresh session sequence and accept signed readback.
- [ ] Hide expired-invite/SAS guidance once binding is trusted; put reconnect/status actions before old pairing diagnostics. Show reconnecting/waiting-network/authentication errors accurately.
- [ ] Register/unregister the existing Android connectivity callback within ViewModel lifetime. Network callback does not grant authority and never performs network I/O itself.
- [ ] Add client wiring/cancellation tests where build environment allows; do not substitute static checks for Android compilation.

## Task 3 — Build metadata, review, acceptance gates

Files: app/build.gradle.kts, ANDROID_BUILD_INPUT_MANIFEST.json, build_handoff.py, verify_apk.py and affected version regression tests only as needed.

- [ ] Set versionCode4 and regenerate exact input manifest; make verifier validate the reviewed version against inspected source without silently weakening existing checks.
- [ ] Run existing protocol/Python regressions, JVM tests, lintDebug, assembleDebug when a qualified build environment and matching signer are available. Report not-run gates honestly.
- [ ] Independent review of diff, no secret inspection/publication.
- [ ] Compare new and installed public signing certificate SHA256 before any install. Keep original APK as rollback. No uninstall workaround.
- [ ] Physical acceptance: old binding unchanged, app reopen auto recovery, real Tailscale off/on, signed readback, phone restart. Owner interaction is one clear instruction at a time.

Rollback: retain original APK and unchanged canonical Core. Remove only new client code through a reviewed revert; preserve public binding JSON and Android Keystore. Never erase Core database or approval history. A different signer is not a rollback/update path.
