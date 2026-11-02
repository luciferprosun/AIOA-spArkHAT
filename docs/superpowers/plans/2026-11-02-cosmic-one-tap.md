# Cosmic one-tap implementation plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development; TDD, scoped review and whole-branch review.

Goal: QR + host approval + persistent reconnect in one AIOA application, followed by real device acceptance.
Architecture: existing Core/MobileGateway, local operator.sock, Android Keystore and Compose.
Spec: docs/android/ADR_ONE_TAP_PAIRING.md and supplied Cosmic architecture PDF.

## Global Constraints
One repo/Core/backend/Android app; package eu.sparkhat.aioa.companion. Preserve TLS1.3/CA/hostname/pinning/P256, real OS authority, nonce/expiry/revoke/UNKNOWN. No live providers, system installs, protected processes, remote writes, automatic approvals or fixture LIVE. Local commits allowed. APK <=128MiB, CI <=35min, retention1day. Human acceptance required for physical pairing; no phase is operational from files/tests alone.

## Review Focus
Unauthorized HTTP owner escalation; captured QR/request replay and racing approval; token leakage; persistent trust versus revoked/restarted source; truthful disconnected UI/UNKNOWN retry.

### Task 1: Native pairing and reconnect contracts
Files: runtime/mobile_gateway/pairing.py (small adapter), service.py, wire.py, runtime/meta_hackathon/runtime_adapter.py, runtime/webapp.py, protocol/mobile_pairing_v1.json, tests/test_mobile_pairing.py and touched regressions.
Consumes existing single Core, tx records, identity, private operator authority and v1 redeem/status.
Produces exact documented signed invite/begin/status/complete, durable binding/revocation, fresh signed challenge and session exchange. Operator methods via same socket; public routes cannot approve. Publish machine-readable contract before Android task.
- [ ] RED meaningful cases: forged/expired invite, substituted device/source/origin, missing owner, duplicate begin/approve, unknown ACK/readback, restart/reconnect, revoke old session, fake host, bounded rates.
- [ ] GREEN smallest integration; reuse existing enrollment/session mechanism rather than second session runtime.
- [ ] Run targeted tests under isolation; preserve logs and source seals; commit exact files.
- [ ] Independent task review and repair.

### Task 2: Android QR/reconnect and Cosmic interface
Files: existing MainActivity, MissionViewModel, MobileClient, Wire, TransportIdentity; small pairing/trusted-host helpers; resources/manifest/build; tests.
Consumes exact Task1 protocol. Produces scanner + safe link import, no-key-form start, private public-host binding, fresh session reconnect, explicit typed errors. Existing crypto and package retained.
- [ ] RED parser/signature/expiry/mismatch/revoked/reconnect/UNKNOWN tests.
- [ ] Implement QR scanner using vetted maintained official/library contract, deep-link/manual signed-packet fallback; no remote URL auto-fetch.
- [ ] Compose Material3 Cosmic home/missions/repositories/settings with real capabilities, 48dp/TalkBack/200% font; no fake chat/controls.
- [ ] Build unit/lint/assemble with existing qualified toolchain; no install/CI spend without gate.
- [ ] Scoped independent review.

### Task 3: Existing Linux panel and integrated acceptance
Files: web/index.html/styles.css and small device panel JS, runtime.webapp owner transport; tests, docs/android/ONE_TAP_PAIRING_ACCEPTANCE.md, docs/meta/COSMIC_MISSION_CONTROL_DEMO.md.
Consumes Task1 private operator ops and public Task2 protocol. Same existing server/Core; authenticated operator bootstrap only via local socket, never unauthenticated HTTP.
- [ ] RED token/CSRF/remote approval denial and QR/SAS binding tests.
- [ ] Add ShowQR, exact pending request approve, trusted device/revoke; same Cosmic tokens.
- [ ] E2E isolated protocol regression + Android actual build and independently verify APK/signature/hash.
- [ ] Whole-branch independent review; prepare exact diff/head/base/CI publication approval gate.
- [ ] Physical Xiaomi QR/status/reconnect/revoke with operator, no synthetic acceptance.

### Task 4: Bounded demo and explicit external gates
Only after real pairing PASS: existing permitted workflow. Paid Muse requires exact fresh one-shot cost approval; GitHub remote push separately approved. If blocked, prepare reviewable changes/artifacts and report exact gate while completing all independent authorized work.
