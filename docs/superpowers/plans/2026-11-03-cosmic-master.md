# Cosmic Master implementation plan
> **For agentic workers:** Use superpowers:executing-plans task by task; independent review before publishing. Existing isolation is reused; no new Core or frontend.
**Goal:** Finish presentation components/state preservation and verify the existing Linux native console, preserving phone identity.
**Architecture:** Existing MissionViewModel/MobileClient, MissionService/Gateway and /devices remain canonical. Separate task observation deadlines from transport freshness; only verified task payloads refresh task controls.
**Tech stack:** Compose1.9/Material3, Kotlin2.2.21/JDK17; existing HTML/CSS/JS; isolated Chrome.
**Spec:** AIOA_COSMIC_SKIN_IMPLEMENTATION_MASTER_CODEX_2026-11-03.pdf (read all3pages); base4960ba2.

## Global constraints
- Same applicationId/versionCode4, APK certificate, AndroidKeyStore, host/TLS keys, store and pairing.
- No paid inference, sudo/global SDK, reset/uninstall, new provider/runtime/Core or merge to main.
- Unsupported native chat/missions/GitHub remain disabled with concrete reasons.
- Do not replace a recognized native process until code/restart preservation tests and review pass; real PolicyKit admission required.
- Muted token#AAB7D2; remaining palette and local OFL fonts preserved.
- Existing staged/untracked .superpowers/ must remain untouched.

## Review focus
- Catalog/list readback never refreshes selected task evidence or re-enables stale STOP.
- Retained tasks stay historical across source/session changes and errors.
- Restored drafts/navigation never replay operations or save bearer/enrollment credentials.
- Exact reviewed task/pending ID binds STOP/Git preview/handoff controls.
- Short landscape/IME/font200% keeps content reachable.

## Tasks
- [x]1. Verify baseline, source connectors/package, existing API/capability and signing workflow.
- [x]2. RED/GREEN task observation metadata, status/receipt rendering rules, bounded local history; integrate through existing ViewModel.
- [x]3. Shared Compose components and destination saveable state; preserve pairing and restore existing gated actions.
- [x]4. Linux capability/state views, responsive/keyboard/contrast/error screenshots through existing Chrome.
- [x]5.166Python baseline/build handoff,39Native security/restart,29JS,66JVM,1Chrome and1offline Worker E2E pass. Additional130reconnect stress hit600s; NOT_PASS and original assertions preserved.
- [x]6. Independent review Critical0/Important0; exact51input manifest and106source seals, scope/secret review. Commit and scoped draft PR follow; never merge.
- [ ]7. Recognize/deploy one native profile to4317 with same state/TLS through real PolicyKit; stop only at physical approval if required.
- [ ]8. CODEX_COSMIC_FINAL_IMPLEMENTATION.md and sanitized artifacts; ANDROID_UPDATE_BLOCKED if signer/CI unavailable; one necessary owner action maximum.
Rollback: retain4960ba2 and prior bundle; live11b1505/source/persistent identity remain recoverable without reset. No automatic phone install or alternate package ID.
