# Cosmic4 Meta Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. No unapproved paid calls. Steps use checkbox syntax.

**Goal:** Deliver one actual advisory Muse conversation on the paired Xiaomi and existing Linux panel, using the existing Core and persistent APK signer.

**Architecture:** Extend the current provider, binding/receipts and MissionService with typed chat, then bind it to the existing signed mobile transport and operator UI. Exact local owner approval precedes each paid operation; uncertain operations only permit readback. Bounded transient conversation text is backed by durable Core metadata/audit, not another DB.

**Tech Stack:** Python/native Core ports, existing HTTPS/Meta Chat Completions, vanilla Linux HTML/JS, Kotlin/Compose, current Gradle/CI, physical Xiaomi.

**Spec:** `docs/superpowers/specs/2026-11-03-cosmic4-meta-chat-design.md`

## Global Constraints

- Preserve live frozen5fae310/PID1178571 until isolated backend tests and rollout admission; keep4314/4316/4321 untouched.
- Same state/host/TLS/owner scope, same Cosmic4 package and cert3aa33eda63d3516010ddbf0fe0ff8de6b6dab6f6fc48088ee2592bde3b627bc4; code401/version4.1.0-cosmic.
- No key/token in APK, HTML, URL, logs or localStorage; no HTTP cost approval, no native/GitHub/browser WRITE.
- One exact LIVE call only after separate human financial consent,<=0.05USD, no uncertain POST retry.
- Default history bounded20 messages/byte cap/TTL; Save knowledge OFF. No new runtime, agent, journal/store or provider.
- Existing STRICT/DEBUG CI policy preserved,35min/run,128MiB,1day; no main merge.

## Review Focus

1. Duplicate IDs/restart/lost ACK cannot create a second paid request or release a consumed warrant.
2. A fresh session/source does not reauthorize a previous paid request; device scope precedes every lookup.
3. Model text/HTML/forged owner flags cannot call tools, approve cost or leak keys.
4. Source upgrade preserves durable pairing and Keystore; old-token drift becomes transport recovery, never SEND replay.
5. Linux bootstrap delivers no credential in HTML/URL/storage; the actual owner/private OS transport remains the authority.

### Task1 — Typed advisory provider and shared receipt path

**Files:** Modify `runtime/providers/meta_model_api.py`, `meta_receipts.py`, `config.py`; create `tests/test_meta_chat_provider.py`.

**Interfaces:** `MetaChatTask`, `MetaChatRequest.payload/public_binding/digest/estimate`; `MetaModelProvider.chat_text(request,cancel,live_binding=None) -> ProviderChat`; `ProviderManager.generate_meta_chat`. Existing MetaLiveBinding/MetaCallRecords/MetaReceiptView support a closed chat binding/receipt discriminator and distinct META_CHAT_TEXT_V1 operation; legacy plan schema unchanged.

- [ ] RED: plain text differs from plan, one actual transport call, exact source/model/scope/approval, no credential before approval, all HTTP errors/malformed/usage/model mismatch, no replay/UNKNOWN, no implicit tool dispatch, no credential echo.
- [ ] Implement same transport, ledger and typed receipts; retain real provider completion ID orNone, usage-rate estimate distinct from invoice/settlement.
- [ ] GREEN new provider tests plus corrected existing Meta/model/receipt baseline. Commit.

### Task2 — Existing MissionService chat journal and workers

**Files:** Create `runtime/meta_hackathon/chat.py`, `tests/test_meta_chat_service.py`; modify `mission_service.py`.

**Interfaces:** service `chat_propose`, `chat_request`, `chat_thread`, `chat_threads`, `chat_review`, `chat_approve`, `chat_stop`; existing worker/cancellation maps. Existing Core OPERATION/AUDIT/OUTBOX records hold metadata and receipts, bounded memory holds text/context.

- [ ] RED: PENDING before cost, device isolation, immutable IDs/digests, history bounds/expiry, CAS transition, source/revocation/epoch veto, STOP, restart and lost ACK leave UNKNOWN without automatic dispatch.
- [ ] Implement native exact financial review -> existing governor reservation/warrant -> existing provider worker -> receipt/state. No second authority store or execution engine.
- [ ] GREEN scoped journal/audit/worker tests and regression. Commit.

### Task3 — Signed mobile API and explicit Native chat profile

**Files:** Modify `runtime/mobile_gateway/wire.py`, `service.py`, `runtime/meta_hackathon/runtime_adapter.py`, `runtime/webapp.py`; create `runtime/mobile_gateway/chat_views.py`, `protocol/mobile_chat_v1.json`, `tests/test_mobile_chat.py`, `tests/test_native_chat.py`.

**Interfaces:** POST/GET v2/chat and exact request/thread GET, signed envelope normalizes device/session/source/nonce. Same NativeMobileComposition optional chat profile, same OwnerScope and store. Private operator review/approve; HTTP allowlist explicitly denies financial approve.

- [ ] RED: exact valid signed chat, wrong nonce/source/capsule/device/revoked/capability, operator elevation denial, native v1 remains unchanged, unknown paid result supports only GET.
- [ ] Implement same source/identity/session machinery and actual key-configured provider profile; all native effects remain disabled. Include new files in source seals.
- [ ] GREEN isolated composition tests before any live host replacement. Commit.

### Task4 — Android chat state, transport and Compose

**Files:** Create `ChatView.kt`, `ChatStateTest.kt`; modify `MobileClient.kt`, `MissionViewModel.kt`, `MissionUi.kt`, `CosmicMissionPages.kt`, locale resources and source/input manifests.

**Interfaces:** typed `ChatView.decode`; client `chatSend/chatRead/chatThread/chatThreads`; VM owns public pending IDs, bounded message state and read-only polling. ChatPage calls only VM callbacks. Model selection fixed to actual Meta binding.

- [ ] RED: active/disabled Send,2000B UTF8 limit, duplicate click, expiry/session loss/background/rotation/IME, stable pending ID and no automatic POST, malformed/foreign receipt, historical messages cannot restore freshness.
- [ ] Implement real bubbles/status/cost/readback and explicit errors. Source drift invalidates old bearer into existing prepare/reconnect, preserving pending request IDs and frozen old approvals.
- [ ] GREEN pure JVM and existing Android regressions; actual Compose compilation in Task7. Commit.

### Task5 — Linux chat and local financial review

**Files:** Create `web/mobile_chat.js`, `web/mobile_chat_dom.js`, `runtime/mobile_gateway/operator_chat.py`, native launcher script/desktop template, tests `mobile_chat.test.cjs`, `test_mobile_chat_operator.py`; modify existing index/device console/webapp.

**Interfaces:** owner-authenticated reads/proposals for same thread journal, per-message Refresh and STOP; cost approval via actual private operator/PolicyKit and explicit trusted local review. Never expose chat_approve through HTTP.

- [ ] RED: same thread/state, XSS/injection text escaping, no token/key in DOM/storage/logs, disabled unsupported controls, owner review exact digest/budget/source, cancellation/expiry deny, no auto-yes.
- [ ] Implement Home/provider state, chat, bounded history, actual approval review links and truthful mission/GitHub limitations using existing modules only.
- [ ] GREEN Node/HTTP/native operator tests. Commit.

### Task6 — Token-free actual Chrome console bootstrap

**Files:** Create `runtime/mobile_gateway/chrome_console.py`, tests `test_mobile_console_secure_bootstrap.py`; modify existing webapp launcher/delivery/session adapter and device JS initialization.

**Interfaces:** same one-use SO_PEERCRED grant/TTL, owner-private Chrome CDP pipe, HttpOnly Secure SameSite session cookie, same-origin authenticated JSON CSRF bootstrap. No credential in HTML/URL/argv/storage, no TCP debugger or disabled sandbox/TLS.

- [ ] RED: ticket expiry/replay/ACK loss, exact framing/origin/cookie/CSRF/rotation/owner-source checks; no public financial approve. Update inherited bootstrap assertions to new security requirement, not remove them.
- [ ] Implement source-bound launcher; preserve unrelated browser tasks/profile and existing UI. Test protocol against bounded fake pipe before real Chrome.
- [ ] GREEN console security/packaging and existing mobile UI regression. Commit.

### Task7 — Exact build, in-place install and source rollout

**Files:** Modify `clients/android/app/build.gradle.kts`, Android input manifest, `scripts/android/cosmic4_channel.py`, `verify_apk.py`, `ci_build.py`, existing workflow/tests; owner-private evidence and rollout helpers.

- [ ] Verify real installed code400/package/cert/bytes and same durable signer first; preserve read-only baseline data/key/device evidence.
- [ ] Explicit code401/version4.1 channel and derivative-branch allowlist; legacy channel/STRICT/signing checks remain. Required preflight/regressions/review then exact SHA workflow; no merge.
- [ ] Actual Gradle tests/lint/assemble, independent APK hash/aapt/apksigner, size and signer/version continuity. `adb install -r` only; original data/key identity remain.
- [ ] Test backend separately; gracefully migrate recognized4317 deployment to frozen approved new source with same state/TLS/SPKI and real PolicyKit. Verify source seal, old approvals/revocations and reconnect without new QR.
- [ ] Real Chrome panel and Android POST/GET transport ready before asking for exact one-shot financial consent.

### Task8 — Real gated smoke, P1 disposition, PR/report

**Files:** `CODEX_FINAL_META_ANDROID_MUSE_20261103.md`, one integration draft PR and owner-private redacted receipts/QA.

- [ ] On physical phone submit stable-ID question “Jaki jest stan AIOA Core?”; inspect same pending thread in actual Linux Chrome.
- [ ] Present exact message/source/request/estimate/ceiling<=0.05USD/count1 in trusted local review; wait for actual owner financial acceptance. No earlier paid call, no automatic second call.
- [ ] Verify actual Meta model/ID/usage/receipt, signed Android response, same Linux journal/rendered conversation, no secret leaks; otherwise record exact external blocker.
- [ ] Only after real P0 evaluate existing native READ Worker. Run only genuinely admitted path; otherwise MISSION_READ_BLOCKED with precise missing bindings. No relabelling offline MCP/Worker or AGENT_READY.
- [ ] Preserve existing PR39 live/frozen branch; one new cumulative draft may be necessary because updating39's live branch would invalidate its source seal. Verify current open PRs before creation. No main merge.
- [ ] Final artifact/cert/source/CI/actual gates, launch/rollback, bounded demo60–120s if real ready; never publish secrets or false LIVE.

## Execution ledger

- Read-only preflight: current base4c00d7b clean; frozenNative5fa/PID1178571/4317; protected listeners4314/4316/4321 preserved; Meta key metadata configured0600, no key read or paid calls.
- Existing PR39 draft at5fa; no Cosmic4/Meta PR exists. GitHub connector reads verified current metadata.
- Existing provider/finance reusable; current Native has no model and chat is deliberately501/disabled. Core operation count65, no existing chat governor/large migration needed.
- Initial baseline runner referenced nonexistent test_meta_receipts (runner error, not product); preserved log. Corrected run uses actual test_meta_p2_receipts/test_meta_p03_receipts names.

## Builder review rulings and execution evidence

The independent builder check identified historical receipt/source migration, trusted Core context, shared OPERATION scan quotas and exact version/branch pins. These are incorporated without adding a provider, journal or authority system. Task1 GREEN:129 tests (synthetic transports only), Task2 GREEN:10 native local-store tests. Detailed RED/GREEN logs are private under `/home/l/projects/AIOA_META_CHAT_PRIVATE_20261103`. New text history expires after900 seconds or restart; durable request IDs/receipts remain readable and never authorize a replay. No paid call has been authorized or attempted.
