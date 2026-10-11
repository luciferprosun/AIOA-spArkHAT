# AIOA spArkHAT — Mobile/Nebius Bridge P0 (implementation handoff)

**Date:** 2026-10-11. **Scope:** existing canonical AIOA project; short-lived integration worktree, no new Core. **Status:** local READ contract; Nebius deployment, mobile application, live Nemotron and effect execution are NOT implemented by this change.

## Objective

Use ChatGPT Android (today) OR the future AIOA Android/web client to submit owner-identified tasks to AIOA at home, without exposing the household Linux host publicly. Eventually use Nebius as a thin, authenticated, durable cloud **relay** while the AIOA Core/PCAF/ServiceGuard on the home Linux device remains the sole execution authority. Nebius Token Factory/NVIDIA Nemotron is a separately configured, bounded advisory provider — **not the signer or authority**.

## Target connection topology

```text
  ChatGPT Android               AIOA Mobile (PWA/Android)
         |                                 |
         +--------------+------------------+
                        | HTTPS / authenticated owner identity
                        v
               Nebius Control Relay
            [proposal/status transport only]
                   outbound poll/reply
                        ^
                        | mTLS or equivalent device credentials
                        |
                Home AIOA Bridge Worker
                        |
                existing MCP Commander
                        |
            AIOA Core / SessionGrant / PCAF
                        |
               Policy / Warrant / Liability
                        |
          isolated product executor (U06/U07)
                        |
           receipt / readback / UNKNOWN
                        |
               remote redacted status

Optional: Nemotron on Nebius Token Factory -> advisory proposal only
No inbound public ports on the home router. No cloud-exposed host shell.
```

## Implemented P0 slice (locally testable)

Module: `runtime/mcp_bridge/mobile_nebius.py`. Tests: `tests/test_mobile_nebius_bridge.py`.

1. Strict `aioa.mobile-nebius-bridge.v1` READ_REQUEST with opaque session/message UUID, peer binding, ordered sequence, UTC creation/expiry, payload, source type and SHA-256 integrity fingerprint. Body <= 4096 bytes, lifetime <= 300 seconds.
2. Allowed origins: `android-chatgpt`, `aioa-android`, `aioa-web`. Allowed operations: **only** `system.status` or `git.status`; existing strict payload validator and existing Commander READ policy apply.
3. Input is **untrusted**; caller must separately provide authenticated peer identity derived from trusted transport (not from JSON). Exact peer match; time window; replay guard; deny unknown, approval-shaped, dangerous or unverified operations.
4. Reuse existing `TaskEnvelope`, `evaluate_task`, `encode_task/parse_task`, `TaskResult`, `admit_commander_result`, and `encode_result/parse_result`. No second Core or tool execution code.
5. Mobile status projection includes **only** opaque message ID, lifecycle state and fixed advisory fields. Raw summary, file names, artifacts, metadata, secrets and approval records are not forwarded.
6. Local test covers Android -> typed P0 packet -> existing Commander wire task -> synthetic READ result -> redacted AIOA observation.

P0 is not connected to the Internet, ChatGPT tunnel, physical Android client, Nebius cloud or a LIVE provider. The SHA-256 fingerprint is **not an authentication signature**. The process-local sequence guard is **not durable across restart**. All request admission must remain within trusted transport and Core.

## Trust/authority separation

| Component | Can do | Cannot do |
| --- | --- | --- |
| Android ChatGPT or AIOA PWA | Request READ/proposals; show status | Authorize host operations based on model text |
| Nebius Relay (future) | Authenticate transport, store/poll bounded envelopes, deliver results | Execute on home PC or sign PCAF permissions |
| Home AIOA Bridge | Validate packet, peer, TTL, replay; call existing READ task policy | Convert a cloud packet to standing WRITE/EXEC approval |
| AIOA Core/PCAF | Decide available capabilities and human grant boundaries | Treat Nemotron/model text as signature |
| U06/U07 worker | Only explicit, tested sandbox action with receipt | Run arbitrary shell or silently retry UNKNOWN |
| Nemotron | Advisory plans/inference behind budget and exact-model router | Grant permissions or claim observed effects |

**OPEN SECURITY GATES:** real OIDC/device pairing + authenticated transport (not mocked peer ID); durable idempotency/replay across restarts; bounded outbound-only connection and reconnect; quotas, tenant/session separation; client-specific redaction; STOP propagation; threat model, prompt injection, receipts, security audit. Never deploy the P0 adapter directly as a public endpoint.

## Next engineering batches — one canonical system

**BR-01 — local cross-process broker proof.** A trusted, independently reviewed adapter uses existing task store/READ policy, persistent idempotency and exact result binding. Run local device/client integration with no cloud secrets and no effect execution.

**BR-02 — Nebius relay sandbox staging.** Select a supported Nebius deployment platform after verifying program credits and cost. Define least-privilege auth, tenant/device binding, expiration, outbound worker connection, TLS, rate limits, retention and one-worker fencing. Staging only with explicit cloud deployment/budget approval. Do not substitute DigitalOcean as authority; separate provider-neutral transport permits dev fallback if credits unavailable.

**BR-03 — Android mobile surface.** Small PWA or mobile app showing connection health, task state, tested outcome and owner approval requests **without** approval secrets. Test on a real Android phone. Same client can work without ChatGPT once AIOA backend is available.

**BR-04 — U07 effect integration.** After U07 accepted, bind bounded `PROJECT_WRITE`/`SANDBOX_EXEC` only through canonical SessionGrant -> policy -> warrant -> durable START/outbox -> sandbox -> readback -> liability/completion. No remote write on generic bearer token; no model-provided `requires_confirmation` authority.

**BR-05 — Nebius/Nemotron LIVE advisory.** Verify allowed Nebius Token Factory model (exact ID) and budget; test a genuinely useful inference with Nebius and NVIDIA model. Distinguish LIVE vs fixture evidence. Token Factory is inference, not cloud worker control.

**BR-06 — hackathon demonstration and release.** Rehearse: Android task in Berlin -> authenticated Nebius relay -> AIOA in Emstek -> controlled local build/test -> verifiable result on Android, plus advisory Nemotron. Record proof, costs, failure/reconnect; prepare <3-minute video, public repo, README and Devpost; human submits. Do not claim full `.deb` or cloud S1/S2 gates without separate acceptance.

## Milestones and handoff checks

- Re-run `python3 -B -m unittest -v tests.test_mobile_nebius_bridge tests.test_mcp_bridge_contract tests.test_mcp_read_payloads tests.test_mcp_task_bus` on exact tree.
- `git diff --check`, compile/AST, focused tests and secret scan. Report exact commit and file list.
- Rebase or cherry-pick the independent bridge commit onto the integration candidate **after U07 has passed**, then run shared CI. Owner authorizes remote PR/merge/push; never move `main` during tests.
- Document any incompatibility with current NVIDIA Nebius hackathon branch scope before release.
- IMPORTANT: do not confuse Cloud Relay, Token Factory Inference and the U06 home sandbox; they are three different boundaries.
