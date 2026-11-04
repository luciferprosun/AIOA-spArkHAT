# AIOA METAGuardiansSPARK

**Cosmic 4.1 — one Core, human-approved actions, signed evidence.**

A native Android companion connects a real Xiaomi phone to the existing AIOA Core on Linux over private HTTPS. Meta Muse Spark 1.3 answers through the host, with an exact local owner decision before spending. The Android app and Linux Mission Control read the same conversation and receipt.

## What has actually worked

On 4 November 2026, Cosmic `4.1.0-cosmic` was updated in place on a physical Xiaomi 13T Pro. Its package, signing certificate, Android Keystore public identity and saved pairing record were preserved. A fresh signed reconnect/status was matched to the Core journal.

The owner then sent a real message from Android and separately approved its exact cost packet on Linux. One Meta Model API call to `muse-spark-1.3` succeeded. Signed Android result/thread readbacks matched Core observations, the owner confirmed receipt, and the actual Linux Chrome panel displayed the same answer and receipt.

- Request: `89c750cf10f643798858a60de5fa7aaf`.
- Thread: `6b9e092798b7477ba6930c3bc116cbd6`.
- State: `SUCCEEDED`; actor: `ANDROID`; one attempt and one model call; no fallback.
- Usage: 229 prompt + 301 completion = 530 tokens.
- Usage estimate: **USD 0.0015655, not an invoice**. Exact approved ceiling: USD 0.05. Conservative governor bound: USD 0.00392975.
- Response SHA-256: `7f3bbcbb075fdcd54d5674bc400f4f548aa9d01fe1ca377a361c9ae48d2e0b27`.
- The original real response was Polish. It is not being relabeled as an English exchange.

This acceptance proves a bounded local chat demonstrator. It is not full `AGENT_READY`, production/M12 certification or evidence of native tool execution. The next paid request requires a new exact owner approval. Account billing and balance are not inferred from this successful call.

## Architecture and Meta usage

```text
Cosmic Android / Keystore
  -> signed mobile v2 / private HTTPS / Tailscale
  -> existing Native host and CoreAdmission
  -> MissionService / warrant ledger / governor / existing journal
  -> exact local owner approval
  -> Meta Model API: muse-spark-1.3, advisory text only
  -> durable receipt + response SHA-256
  -> signed Android readback + the same Linux conversation
```

The fixed Meta endpoint is `https://api.meta.ai/v1/chat/completions`. The host uses the existing governed provider adapter, one attempt, a 15-second provider timeout and at most 512 completion tokens. The API key stays on Linux. It is absent from the APK, browser, CI and public evidence.

We reused the existing Core, MissionService, transaction runner, warrant ledger, governor, mobile gateway, Jetpack Compose client and HTML/CSS/JavaScript console. We did not create a parallel Core, approval database, agent runtime or frontend framework.

## Human control and failure handling

- Native owner admission requires real PolicyKit authentication in an active local Linux session.
- Each paid message requires a separate immutable review of its request, model, context/history, source/capsule, session, scope, expiry, policy epoch and cost bound.
- The phone and HTTP UI cannot approve model spending or grant native execution authority.
- The request ID is saved before POST. Lost ACK, timeout or restart uses readback; an uncertain effect is not retried automatically.
- `UNKNOWN` remains explicit. Historical receipts do not grant current authority.
- Model text is rendered as text and cannot become a tool command.
- TLS verification, host signing, nonce, audience, expiry, revocation and device identity remain enforced.
- Save knowledge is Off. Text is held in memory for up to 15 minutes; digests and receipts remain durable. Native operator admission lasts up to one hour.

## Release and reproducible evidence

The installed Android APK and originally accepted Native source are:

`0b3f48ef0842833e17cf6bb79e8b72d44e7e7eee`

Package: `eu.sparkhat.aioa.companion.cosmic4`; versionCode `401`; versionName `4.1.0-cosmic`.

APK SHA-256:

`c88aa9c106b1f4464b66e9ef9ffc68eeaa85e4eda5d966f1ab1455713e23209e`

Signing certificate SHA-256:

`3aa33eda63d3516010ddbf0fe0ff8de6b6dab6f6fc48088ee2592bde3b627bc4`

The external operator-client startup fix is `3e9f9f541697ecbed21d3bdd59930a0e77d42216`. Later report commits are distinct from the APK source. This branch adds English Linux UI copy; deploying a new Native source still requires exact-source qualification and authentic admission. Android can use its already packaged English resources through Android's per-app locale setting, without rebuilding or resetting pairing.

- [Android build 41720343414](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41720343414): 82 actual Gradle/JUnit tests, zero failures/skips, lint zero errors, assemble and signature verification passed.
- [Core/Native 41720308283](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41720308283): Python 3.11 and 3.12 each ran 2703 tests, zero failures/errors, five explicitly allowed optional skips, plus 105 NonZero tests passed per interpreter.
- [Operator client 41756784319](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41756784319): each interpreter ran 2705 tests with the same five allowed skips and zero failures/errors, plus 105 NonZero tests passed. Actual isolated Chrome and installed wheel/sdist checks also passed.
- Default CodeQL was preserved. The optional owner-gated advanced scan was separate.

The five allowed skips concern optional Playwright, Textual and pinned NVIDIA ATIF dependencies. Counts from different interpreters and overlapping suites are not summed as unique tests.

This is a DEBUG APK. The explicit `DEBUG_UBUNTU22_V2` image/metadata discrepancy remains disclosed; STRICT was not weakened. Dependencies are not fully hash-locked and no third-party build attestation is claimed. CI artifact retention is one day, so retain the owner's verified local APK and evidence.

For the full actual acceptance and repair history, read [the physical acceptance report](CODEX_REAL_ANDROID_LINUX_ACCEPTANCE_20261104.md), including its final LIVE update. Earlier BLOCKED sections are historical. [PR #40](https://github.com/luciferprosun/AIOA-spArkHAT/pull/40) remains a draft; do not confuse it with main.

## Running an already qualified host

Use the existing operator-approved installation and private state. Do not start a second listener or substitute fixture authority. The supported entry points are:

```sh
python3 -B -m runtime.webapp --mobile-native --mobile-chat --help
python3 -B -m runtime.webapp --mobile-operator console --help
```

An actual launch needs the existing private origin, TLS certificate/key, state directory and a real local PolicyKit decision. Never put credentials into commands, URLs, screenshots or the APK. On an already paired phone, choose Reconnect and Refresh signed status. New enrollment is unnecessary unless the actual trust state requires it.

To verify a new chat, send one deliberate request, review its exact financial packet locally, then compare the signed result and receipt in both UIs. Do not repeat a paid call simply to reproduce this historical proof.

## Known limits and hackathon scope

Native READ Worker is `NOT_BOUND`; mission READ is not ready. Native execution, GitHub WRITE, deployment, browser actions and autonomous computer control are not enabled in this demonstrator. A model's statement about Core is not a tool measurement. Phone reconnect/status evidence is separate from the LLM answer.

The UI may briefly show BUSY during overlapping read polling. Text can expire and admission must be renewed authentically. These are not promises of permanent online availability or unlimited memory.

The system builds on pre-existing AIOA spArkHAT work. The submission focus is the Android/Linux/Meta chat integration and its verified evidence chain, not a claim that the entire historical Core was created during the hackathon. Historical Nebius/Nemotron experiments are separate from this Meta LIVE proof.

The final English demo, video and formal submission have separate acceptance gates. A script or local report does not mean a video was recorded, published or a form was submitted.

## License

[MIT](LICENSE). Bundled Cosmic fonts have their existing OFL notices. Owner: LuciferSun; public GitHub: [luciferprosun](https://github.com/luciferprosun).
