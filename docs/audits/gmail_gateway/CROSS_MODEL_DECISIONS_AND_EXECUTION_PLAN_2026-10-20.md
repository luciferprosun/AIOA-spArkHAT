# AIOA Gmail Gateway — Cross-model decisions / execution plan (DRAFT, 2026-10-20)

**Target branch:** feature/aioa-gmail-gateway  
**Sources:** A01 Meta (summary), A02 DeepSeek (17-section long answer), A03 Sonnet (summary), A04 Gemini (long answer), A05 Kimi (summary). External model statements are not implementation authority.  
**No Gmail connection, real send, OAuth flow, production owner acceptance or main merge authorized by this document.**  
**Google primary-source verification:** official sources linked below, checked on 2026-10-20.

## Five-model architecture comparison

| Auditor | Deployment proposal | Important insight | Missing/incorrect |
|---|---|---|---|
| Meta A01 | Sidecar gateway, separate credential broker / outbox | Restrict token custody; separate Core authority | Full report unavailable. Quoted 6-week/CASA price is an unverified estimate. |
| DeepSeek A02 | In-process adapter beneath AIOA Core, Linux OAuth | Exact consent, typed mail port, UNKNOWN/send ledger, untrusted reply/HAT | A negative Sent search does not prove NOT_SENT; estimate only. |
| Sonnet A03 | Thin Python in-process adapter | Minimal four new modules, send-only MVP, manual Sent reconciliation | Full report unavailable. Revoke-on-STOP conflates stopping one task and disconnecting an account. |
| Gemini A04 | Hash-sealed outbox with Gmail adapter | Strong tests and audit event boundaries | Incorrect scope classifications: gmail.send is Sensitive, gmail.compose and gmail.metadata Restricted. Proposed hash omits fields; negative query does not prove non-delivery. |
| Kimi A05 | In-Core ChannelPort / ServiceGuard | Reuse instead of duplicating Core; quota changes 2026 | Full PDF-ready report unavailable. The "50-token" cliff requires verification (Google also documents client-user refresh token limits). |

## Primary-source checks, not majority votes

1. Gmail scopes: **gmail.send Sensitive**. gmail.readonly, gmail.compose, gmail.metadata, gmail.modify and mail.google.com/ are **Restricted**. gmail.labels is **Non-sensitive**. Source: https://developers.google.com/workspace/gmail/api/auth/scopes
2. Restrictive scope data transmitted to other services/stored on servers entails Google additional assessment requirements under stated distribution/processing conditions; a one-owner dev/test app is not automatically subject to each commercial requirement. Verification applicability: https://support.google.com/cloud/answer/13464323 and assessment: https://support.google.com/cloud/answer/13465431. Actual GCP app behavior is a separate G2 gate.
3. New Gmail quotas effective 2026-05-01 for applicable new Cloud projects: 1,200,000 units/min/project, 6,000/min/user/project, 80,000,000 units/day/project billing threshold. One messages.send = 100 units, messages.list = 5, messages.get = 20, threads.get = 40. Existing projects may have different grandfathered quotas. Source: https://developers.google.com/workspace/gmail/api/reference/quota
4. Native desktop OAuth using system browser and 127.0.0.1 ephemeral callback + PKCE S256. OOB/manual copy-paste deprecated. Source: https://developers.google.com/identity/protocols/oauth2/native-app
5. External OAuth Testing generally yields 7-day expiring refresh tokens for Gmail scopes. Source: https://developers.google.com/identity/protocols/oauth2/
6. Gmail messages.send uses base64URL MIME, and has no documented idempotency-key option. Do NOT treat custom Message-ID as exactly-once. Source: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send
7. An accepted HTTP send response does not by itself guarantee delivery to recipient; see Google error handling: https://developers.google.com/workspace/gmail/api/guides/handle-errors
8. Gmail connector in ChatGPT is **not** the same as AIOA Gmail OAuth; connector credentials cannot be inferred or copied to AIOA.

## Architect decision — Draft ADR-GMAIL-001

**Choose a thin, in-process Python Gmail channel adapter** under the existing runtime/Core and existing owner approval/ServiceGuard policy, with narrowly held credentials via a local keyring-backed broker. NO second authority plane, no always-on network service, no public REST callback, no Android Gmail token, no Chromium dependency.

One alternative isolation: credential broker may become a separate locked-down process later *only* if audit demonstrates a concrete isolation benefit and proves token, IPC, receipt and STOP semantics. Do not implement process sidecar in G0/G1.

Rationale: smallest merge surface against public main, easiest tests on 4GB Linux Mint, reuse Core audit/nonce/STOP/recovery. **AIOA current M12 real-owner/production backend is NOT_ACCEPTED; offline fixtures cannot be promoted to live owner authorization.**

**Suggested module paths to confirm with actual code:** runtime/communication/contracts.py, runtime/communication/ports.py, runtime/communication/gmail/{fake.py,adapter.py,oauth_broker.py,mime.py,outbox.py,reply.py,privacy.py}, tests/test_gmail_* and docs/communication/. Avoid guessed aioa/gateways package until actual setup.py/pyproject entrypoint inspection.

## Gmail task state / authorization contract

PREPARED -> WAITING_OWNER -> APPROVED (exact human review) -> SENDING (durable pending record)
-> SENT_ACCEPTED_BY_API (when response ID received) **or** UNKNOWN_SEND (request maybe took effect)
-> optional independent SENT_FOLDER_OBSERVED / REPLY_EVIDENCE (never equivalent to final delivery).
Denied, expired, cancelled, revoked and STOPPED transitions are explicit. STOP during a network call yields UNKNOWN until reconcilable; STOP cannot un-send an accepted message.

Use canonical structured bytes and domain-separated hash over **actual sender, all To/Cc/Bcc recipients, subject, normalized MIME exact body/text+HTML and attachments, task + proposal ID, thread/reference fields, scope, expiry, nonce**. Bind human approval to the same final MIME digest and separately verified Core capability. Recompute before send. Any mismatch => DENY.

Before calling messages.send, atomically retain a durable, single-writer attempt record and consume the grant in Core's approved effect path. Crash, timeout, 5xx or lost ACK => UNKNOWN_SEND with no automatic retry. A negative mailbox query NEVER proves not sent. Only an explicitly informed owner may authorize a distinct new attempt while acknowledging duplicate risk; a fresh authorization must not mutate the historical ledger.

Read incoming content only from selected threads, tag it untrusted, sanitize/suppress personal content in model outputs and logs, and stage into existing CoreKnowledgeStaging/HAT for separate verification. Email never authorizes shell/browser/Git or changes Core policy.

## Phased work and acceptance

| Phase | Work | Gate / tests | Rough effort, sequential |
|---|---|---|---|
| G0 | Source/authority integration spike, ADR, immutable typed contracts; create isolated local worktree/branch based on verified public base | No networking/secrets; no new authority; maintainer approves narrow integration points | 0.5–1.5 days |
| G1 | Offline FakeGmail, Core proposal-admission adapter, durable WAL, negative tests, MIME exact-byte hash | Tamper, spoof, 401/429, STOP, lost ACK, restart, duplicate send, sender spoof, concurrency; all local synthetic | 1–4 days |
| G2 | Linux Desktop OAuth + PKCE loopback + local Keyring; separate Google Cloud test project and gmail.send-only consent | Separate explicit owner consent and source audit; no OAuth token in Git/Android/logs | 1–2 days + GCP setup |
| G3a | First self-addressed message with EXACT owner approval, no hidden retry | One live test; receipt binds proposed MIME to actual API response; UNKNOWN remains blocked | 0.5–2 days |
| G3b | Optional selected reply read with gmail.readonly | Requires separate restricted scope privacy/verification assessment, owner consent and legal/data review | Extra 1–3 days plus possible Google review |
| G4 | Multi-model proposal/critic + HAT staging on untrusted selected data | Source provenance, no autonomous email send, no data egress beyond approved route | 2–5 days |
| G5 | Android presentation under existing Core after safe mobile pairing | Compromised UI tests, exact approval display, STOP; no second signer | After actual mobile owner gate |

Estimates are engineering guesses, not guaranteed delivery dates. Do not mix external Gmail scopes or acceptance into GOLD72 offline qualification.

## First useful demo

Agent drafts question for owner/Natalia -> Core creates immutable proposal -> owner checks full recipient/body and approves -> Gmail Gateway sends exactly ONE authorized attempt -> API receipt stored or UNKNOWN -> for earliest send-only MVP owner manually pastes reply as untrusted evidence -> Knowledge/HAT staging with human review.

No automatic email to Natalia or actual Gmail connection before owner explicitly approves credentials and final exact message.

## Branch integration / isolation

Current development branch was created from public main SHA 81656e6… (2026-10-14), while the local Linux Sprint33/34 source has changed separately. Implement the Gmail module in a distinct local checkout/worktree and separate evidence/test storage, not the active S33/S34/GOLD72 runtime. Do not change main, do not auto-merge. When S34 is independently sealed, compare exact source and interface changes, port the adapter with review, run affected + full regression and independent security review; reject broad import of stale authority paths.

## Owner decisions required later

- Approve G0/G1 offline coding (no Google account linked).
- Decide dedicated test Gmail / GCP project and consent to gmail.send.
- Approve exact one-off email (self test first, Natalia only later).
- Decide separately whether reading replies warrants gmail.readonly and associated privacy/compliance steps.
- Authorize eventual integration PR/merge after completed qualification.

**Status now:** five model outputs collected; A01/A03/A05 summary-only and A02/A04 long forms. Architecture chosen as DRAFT, not implementation authority.
