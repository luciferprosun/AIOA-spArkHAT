# Rozstrzygnięcie niezależnego review

Raport poniżej jest niezmienionym odczytowym review oryginalnego zakresu
`de6fddb..f0ddb3e`. Po nim autor wykonał jeden fix pass, bez re-review:

| Finding | Poprawka | Dowód |
|---|---|---|
| I1 Important | Shared `_load_unrevoked` dla nowych legacy authority uses; historyczny v1 i reconciliation zachowane | RED6/5fail → GREEN82/82; commit0399a78 |
| I2 Important | Jawny, persisted/bounded local v2 pending-ID handoff; strict session scope bez zmian | SOURCE RED13/3fail → GREEN40/40; signed native restart1/1; commit1cd2a91 |
| I3 Important | Root LICENSE sealed read-only; wszystkie76 capsule files dostępne przez zamierzone mounty | RED4/3fail → GREEN20/20; commit9d6cf4d |
| M1 Minor | Odroczone: Android v2 cursor / starsze strony >16 zadań | host/task-ID handoff; brak obietnicy mobile history paging |

Końcowy autorski test suite na `1cd2a91da0a1e8ef10186458327d4a115d9444a0`:
Python 2488 total/2483 PASS+5SKIP/2138subtests; native42/42,
Node15/15, package2/2. To weryfikacja autora, a nie nowe niezależne review.
Kotlin/JVM/real Chrome nadal NOT_RUN. Decyzje o wszystkich13 declined items
i koszty są w OWNER_HANDOFF_PL.md. Niezależna klasyfikacja synthetic fixtures
dotyczyła f0; po dodaniu testu I1 cały plik Meta API ma nowy hash, lecz
fingerprinty samych kandydatów są identyczne z publicznym źródłem17280c0.

---

# Independent whole-branch migration review

Reviewed range: `de6fddb236db1702879fc65838c0c94b53d24cb2..f0ddb3ee66afbd5a5c3540d2fe1e54d612283676`.
Checkout: `/home/l/AIOA_LOCAL_WORKTREES/one-aioa-core-muse-mobile-20261101`.
Reviewer: `/root/review_one_system_final_20261101`; one independent fresh-context review, 2026-11-01.

**Assessment: With fixes for the bounded LOCAL OFFLINE FIXTURE candidate.** No Critical finding; three Important findings and one Minor finding. This is neither main-merge approval nor production authorization. The Important findings below require the executor's single RED→GREEN fix pass and applicable final QA.

## Review scope and evidence

I read `FINAL_REVIEW_BRIEF.md`, the extracted user specification `MASTER_EXECUTION.txt`, the progress/Ruling ledger, and the required code-reviewer template. I inspected the complete range inventory and history (42 commits, 214 changed files, 24,035 additions and 58 deletions), then reviewed in passes: Core authority/intent/executor boundaries; HTTP and web wiring; mobile transport and Android lifecycle; inherited Meta/browser/provider paths; Android tooling, source lineage, licensing and flagged secret fixtures; documentation and measured evidence.

Depth was concentrated on executable trust boundaries. Source inspected includes the new agent operations and web adapter; MissionService and runtime composition; warrant/intent/local-session changes; ServiceGuard and MCP changes; Linux sandbox changes and private host-cache codec; SensorBridge worker/readback; local Git and dependency-plan ports; mobile gateway/wire/v2 projection; Android DTO/client/ViewModel/UI; web controller/bootstrap/authenticated request wiring; inherited provider/receipt/browser/network-admission code; and Android installation/build/verification guards. I read selected adversarial and integration tests alongside these paths. This is a whole-range review with prioritized depth, not a claim to have read every line of all historical documents/tests or re-audited every unchanged native implementation.

I did not run tests, imports of product modules, services, effects, browser/API calls, installs or builds. I did not inspect operator credentials, generated private keys or `core-records.json`. The checkout, index, HEAD and branches were not changed. The only reviewer output is this private report.

Evidence read directly:

- `U9_NATIVE_RELEASE/result.json`: 41 tests, 28 subtests, zero failures/errors/skips, 150.482 seconds. I also inspected relevant native security/cache/launch/recovery test source. These are executor-produced results, not a reviewer rerun.
- `U9_DEMO_HOME_GREEN/DEMO_REPORT.json`: `PASS_OFFLINE_LOCAL_SLICE`, source `9f5e6b437df5a9ebd711c257a092da102d12b038`, five workspace checks, independently verified local receipt, predicted Git commit equal to actual HEAD, fresh-process signed readback, remote write HTTP 403, USD 0 and risk 2. It explicitly states no model invocation, paid call, APK, physical Android or verified TLS. The final reviewed commit only adds reports after that product code seal.
- Previous full portable and Node/package results are documented; the final `U9_PORTABLE_RELEASE` had `suite.log` and `command.json` but no final result at the last inspection. I do not count it as passed. Final portable/package results and any post-fix seals remain the executor's gate.

## Strengths

- The local native path uses the existing Core admission, transaction runner, warrant, governor, intent journal, AUDIT/OUTBOX and durable fixture store. I found no second authoritative persistent ledger in the inspected composition. Historical in-memory fixture correlation/receipt classes are not silently installed as another production authority.
- Local zero-money intent is explicit and retains a real risk reservation. The new path records consumption and UNKNOWN before release; the owner-wide unresolved barrier and independent reconciliation prevent treating a lost response as permission to retry. Native STOP and readback use the existing broker rather than an HTTP shell.
- The registered workspace and local Git paths carry actual file/receipt identities. Remote publishing remains a denied boundary; installation is a typed proposal/fake artifact observation with `installed=false`. No unrestricted GitHub-token loading, delegated READ installer, generic HTTP command execution or silent paid-provider fallback was found in the inspected paths.
- Mobile scope is checked before the canonical mission reader. Device signatures remain transport evidence and do not mint owner authority. UI/model labels explicitly separate the fixed local recipe from an invoked model and disclose unverified LIVE/billing/phone/TLS/APK scope.
- The HOME cache correction is narrow: the private descriptor has its own codec, while public contract path validation remains restrictive. The retained HOME demo and native regression address the actual failure rather than changing public path policy.
- Integration/source records preserve the inherited Meta/N1/tooling lineage, reference-only external Android projects, and the existing licensing notices. Production gates are materially disclosed rather than represented as completed fixture work.

## Issues

### Critical — none found

No Critical finding was identified in the code inspected. This is not certification of the declined or unexecuted environments below.

### Important I1 — a recorded warrant revocation does not stop existing consumption paths

**Locations:** `runtime/mission/warrant.py:137` and `runtime/mission/warrant.py:156`; `runtime/mission/intent.py:185`; downstream `runtime/providers/meta_model_api.py:228` and `runtime/providers/meta_model_api.py:242`; `runtime/meta_hackathon/mission_read_offline.py:119`.

The new `approve()` writes an APPROVAL witness for every warrant, and `revoke()` successfully sets that witness's `revoked` flag. Only `require_active_in_transaction()` checks it. Existing `consume()` still checks the OPERATION record/consumption only; the non-local-zero branch of `CoreIntentJournal.start()` similarly loads the old record directly. Both can therefore accept an otherwise valid newly approved warrant after `revoke()` has succeeded. The inherited Meta exact-approval check also ignores the witness, and its release path calls this unchecked `consume()`.

**Effect:** a caller receives a successful revocation from the shared ledger but can still consume that authority through existing v1/offline/provider paths. The native local-zero path is protected; this finding does not claim that the current default profile enables a paid LIVE call. It is a real inconsistency introduced into the central authority API and a compatibility/security gap in the assembled branch.

**Minimum fix:** enforce any recorded revocation in every new authority use, including legacy `consume`, delegation and v1 START, through a shared transaction check. Preserve the distinction between a historical v1 record with no new witness and a present witness explicitly revoked; do not accidentally impose all new v2 session rules on valid historical records. A root revocation must also defeat use of an attenuated active child sharing the nonce. Read-only inspection/reconciliation should remain available.

**Required regression:** approve→revoke→consume and approve→revoke→v1 START must fail before dispatch/risk changes; include a delegated child and the inherited provider/fixture release boundary. Assert zero executor/provider transport calls, with the existing local-zero and historical compatibility tests remaining green.

### Important I2 — Android v2 pending proposals have no recovery exit after session loss

**Locations:** `clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MissionViewModel.kt:32`, `:158`, and `:176`; `clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MobileClient.kt:22`; `runtime/mobile_gateway/views_v2.py:39` and `:102`; UI `clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MainActivity.kt:89`.

Before POST, `proposeAgent()` synchronously persists `pending_agent_proposal`. It clears that value only after a successful proposal response or successful proposal GET returning a task. The token is intentionally memory-only, and every new enrollment gets a new session. Proposal readback keys and task links include the original session ID, so after process death, session expiry, revocation or re-enrollment, the restored pending ID cannot be read under the new session. The resulting denial leaves `pendingAgent` set forever. `proposeAgent()` and its UI button then remain disabled; the v2 code has no counterpart of v1's `archivePendingHint()`.

**Effect:** ordinary interruption during a proposal permanently blocks further v2 use in this app's stored state, even after valid re-enrollment. The user is pushed toward clearing app data and losing the unresolved ID. Host reconciliation alone cannot clear the Android preference, and the old scoped record does not become readable in a new session.

**Minimum fix:** provide a supported recovery exit. The smallest change is an explicit bounded v2 pending-ID handoff/archive following the v1 pattern: retain the unresolved ID for host reconciliation, clear only the local UI block after the explicit action, and leave Core UNKNOWN unchanged. Expose the action and retained IDs in the existing UI.

**Same-key re-enrollment alternative:** the executor specifically asked whether stable device binding could restore signed readback. It can be a valid read-only recovery design, but changing `_key` alone is insufficient: `SCOPE_FIELDS` itself includes `session_id` (`runtime/mobile_gateway/service.py:23`), both proposal and task lookup enforce it, and `_redeem()` explicitly revokes old same-key sessions at `:157`. A new authenticated, unrevoked session could recover observations only after matching every stable binding (`device_id`, `source_sha`, `capsule_digest`, `owner_scope_digest`, `audience`) before mission lookup. Keep old-session authentication/revocation and nonce checks, ordinary action scope and owner authority intact; do not globally remove session checks from v1 or action routes. Preserve duplicate-proposal/no-replay semantics and compatibility with existing session-keyed records. This must be an explicit scoped observation-recovery rule, not acceptance of the old token. Intentional key/source/owner/audience changes must still deny cross-scope readback; those cases, and a genuinely orphaned UNKNOWN proposal, still need the bounded retained-ID handoff/archive. This design choice belongs in the executor's Ruling.

**Required regression:** persist pending before POST, lose process/session, re-enroll with the same key and exact stable bindings, then exercise the selected supported recovery path. If using signed recovery, prove it succeeds only under the fresh session while the old revoked token and a different key/source/owner/audience fail before mission lookup. For intentional binding changes or orphan UNKNOWN, prove archive retains the ID and allows a new proposal without replaying the old one or clearing Core UNKNOWN. Persistence failure must keep the pending state blocked. Pure lifecycle/source tests can support the available environment; actual Kotlin/JVM compilation must remain separately labelled until performed.

### Important I3 — the inherited isolated Chrome capture cannot calculate the new source capsule

**Locations:** `runtime/browser_agent/chrome_process_read.py:88` and `:93`; `runtime/meta_hackathon/runtime_adapter.py:54` and `:86`; consumers `runtime/browser_agent/chrome_process_read.py:152` and `:194`.

The sandbox mounts `runtime`, `web` and `lab`, then individually mounts capsule entries only if they begin with `protocol/` or `clients/`. The new capsule also includes root `LICENSE`. Nothing mounts `/app/LICENSE`. Inside the worker, `current_source()` unconditionally resolves and hashes every SOURCE_FILES entry. Consequently preview source checking, and independently the final capture record, encounter the missing file and cannot produce a valid `capture_ui()` result on this assembled branch.

**Effect:** the inherited networkless browser/UI verification capability is broken by the expanded capsule. Controller/static tests and historical browser evidence do not demonstrate that this current namespace can boot and complete the same capture. This is a functional regression in retained tooling, not evidence of network escape.

**Minimum fix:** explicitly include the root license in the read-only source mounts using the existing sealed-source validation, and make capsule/mount completeness an invariant so later allowed source additions do not recreate the failure. Preserve the exclusion of `.git`, `.local`, credentials and host HOME; do not mount the whole checkout.

**Required regression:** build the real sandbox argv and prove every SOURCE_FILES path is available through an intended read-only mount, including root LICENSE. If executing the actual capture is within the qualified host's permitted test scope, validate it there; otherwise disclose the remaining browser execution gate rather than claiming browser PASS from an argv test.

### Minor M1 — Android v2 discards the mission-history pagination cursor

**Locations:** `clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MissionViewModel.kt:146`; `clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MobileClient.kt:211`; server `runtime/mobile_gateway/views_v2.py:89`; UI `clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MainActivity.kt:95`.

The server supplies pages of 16, `history_truncated` and `next_cursor`, and the client validates the cursor. The v2 ViewModel only retains `missions`; there is no v2 page request/UI action. Within a session containing more than 16 proposals, older tasks disappear from the selectable history with no way to navigate to them.

**Minimum fix:** retain a v2 cursor and expose a bounded older-page action through the existing view/client pattern, keeping server scope checks and page bounds. A two-page test should prove an older task can be selected. This can be tracked separately from the Important fix pass if explicitly deferred.

## Lineage, secret fixtures and licensing disposition

The full diff inventory and commit history include inherited Meta P01/P03, N1 and Android tooling before the unification changes; the local merge of the main/G8 base is present. The inspected current integration matrix identifies the canonical repository and source SHAs, describes external Android labs as reference-only, and does not claim their unestablished license authorizes copied implementation. The changed-path inventory did not introduce an unrelated AWS/GOLD72/recovery tree, old authority database or private operator artifact. Current remote PR state was not queried by this reviewer.

I independently checked the four flagged current test files against the locally available `17280c0` public-lineage commit: all four are byte-identical and match the disposition SHA-256 values. The flagged lines belong to prompt-injection/redaction/error/invalid-receipt tests (`test_prompt_injection_is_data_and_secret_text_is_not_serialized`, `test_http_auth_billing_rate_and_server_errors_are_redacted_and_not_retried`, `test_error_redaction`, and `test_malformed_nan_inf_duplicate_keys_and_secret_like_fields`). The fifth outgoing-history flag is the older `test_meta_model_api.py` blob; its candidate line matches the current fixed test literal, and its hash matches the history disposition. These supplied flags are correctly classified as inherited synthetic negative fixtures. I did not suppress the raw scanner failures, infer a full secret-free guarantee from them, or independently rescan all history. The executor's final outgoing scan remains required.

I read the Android NOTICE and lock/installer/build/verification boundaries. The wrapper JAR hashes to `81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f`, matching the pinned lock and NOTICE; the accompanying Apache license is retained. This is an independent local-byte check, not a fresh upstream download verification or binary audit. The unset independent SHA-256 values for platform/build-tools remain explicit acquisition blocks. External license correctness and complete transitive-artifact notices cannot be certified without actual provenance/build evidence.

## Recommendations

Address I1–I3 in the executor's single bounded RED→GREEN pass. Prefer shared revocation semantics, the existing bounded pending-hint pattern, and a general capsule mount completeness assertion over special-case UI resets or broad mounts. Keep the new tests tied to observable denial/recovery/readability outcomes. Record any Minor deferral explicitly.

After code changes, refresh source/capsule and Android source manifests as required by existing seals, run the relevant regressions and the final green suite, and update evidence to the final SHA. Do not count this frozen-HEAD review as an independent review of subsequent edits; no second reviewer/re-review is requested.

## Declined to judge

Each item below was considered and set aside for the stated reason; the executor should retain or explicitly rule on these boundaries.

1. Production owner identity, real CPL admission and production authority deployment: intentionally NOT_BOUND; the candidate is a synthetic owner/local fixture, not a production owner implementation.
2. Production CockroachDB/M12 migration, backup/restore, schema writes, cross-process production transaction durability and production load: no such operations were authorized or performed; inspected persistence is the existing fixture store.
3. LIVE Meta/Nebius/local-LLaMA inference, provider API availability, current prices/credits/billing and paid-call receipts: no paid or network calls; product explicitly blocks or labels these unbound.
4. GitHub create-only transport, real credential hosting, remote 401/403/429 behavior, exact canonical remote ancestry, push/PR and remote cancellation: remote publishing is a denial/future boundary; local Git and synthetic classifications are not remote proof.
5. Real dependency acquisition/install, Android SDK/JDK download, owner license acceptance, system installation and rollback: typed/fake install and blocked toolchain paths only; no install execution.
6. Kotlin/JVM compilation, Android lint, real APK generation/signing, physical Xiaomi behavior, Android Keystore lifecycle on a device and qualified TLS: explicitly NOT_RUN/NOT_VERIFIED and no authorized toolchain/device environment in this review. Static source review does not substitute for these gates.
7. Current real-browser DOM/visual/mobile-layout success and actual networkless Chrome capture execution: no browser effects were permitted. I3 is still an actionable source regression; a repaired argv alone would not establish a visual/browser pass.
8. Installed wheel unified startup on a different host: the declared unified profile requires a qualified source checkout. Packaging inclusion and installed-runtime portability are distinct, and the latter is not certified.
9. All host/kernel/native isolation permutations, malicious same-UID interference and full unchanged C worker audit: source/caller checks and selected native evidence were inspected; this was not a new penetration test or exhaustive kernel-security certification.
10. Every historical documentation/test line and every binary/transitive dependency: range inventory was covered, executable trust paths prioritized, and selected evidence examined; no exhaustive binary or third-party legal audit is claimed.
11. Fresh external provenance/license-service verification and a complete new outgoing-history secret scan: review was restricted to local read-only material. The supplied flagged fixtures were independently classified; the executor owns the final scan and remaining provenance gate.
12. Current GitHub PR22/PR25/PR26 state, branch publication, workflow dispatch, default-service cutover and promotion to main: no remote API or existing service interaction; these are separate owner/integration actions, not authorized by this review.
13. Final frozen-HEAD portable/package results and post-fix validation: no completed final result was present at the last read; the executor must wait for and assess actual outcomes, including any required rerun after fixes.

## Assessment

**Ready for the local fixture candidate: With fixes.** The inspected architecture and measured native/HOME evidence support the claimed bounded local Core/workspace/Git/mobile-fixture slice, with production gates honestly separated. I1–I3 should be fixed and validated before accepting the assembled candidate; M1 should be fixed or explicitly deferred. Main promotion, production use, paid execution, remote publishing, installs and APK/device deployment remain separately gated and are not approved here.
