# A02 — DeepSeek: AIOA spArkHAT Gmail API Gateway independent architecture, security and policy audit

**Date:** 2026-10-20
**Attribution:** DeepSeek, full 17-section response pasted by the owner
**Source scope:** Single-owner, Linux-hosted Gmail integration for AIOA; one Google account, no multi-tenant SaaS.
**Branch:** feature/aioa-gmail-gateway, starting from 81656e6...
**Status:** RECEIVED_LONG_REPORT, fact check and actual repository integration review pending. No code or Gmail action authorized.
**Archive fidelity:** All 17 sections, code models, matrix, scenarios, and source URLs transcribed in structured form; some formatting was normalized and some narrative condensed. The original unabridged wording remains in the source conversation.

---

## 1. Executive technical recommendation

Do NOT build a second authorization engine inside Gmail Gateway. The adapter is a client of existing AIOA Core, not a peer authority. Gateway cannot hold its own owner approval state, decide that a message is authorized, or treat tool calls as consent.

Use a desktop-native OAuth 2.0 Authorization Code with PKCE and loopback redirect on Linux. Refresh tokens belong in GNOME Keyring/libsecret or an AIOA-owned encrypted vault. MailProviderPort exposes typed owner-approved operations, no raw tokens. Only Gmail write capability: send an already-approved exact message. Read explicit selected threads as UNTRUSTED evidence.

Claimed rationale: quickest single-owner pilot without public web callbacks or separate mobile authority; temporary Testing mode with seven-day refresh token. Actual Google verification/CASA policy and production conditions require separate primary-source checking.

## 2. Existing AIOA vs new components

| Component | DeepSeek proposal | Integration concern |
|---|---|---|
| CommunicationPort | Reuse/extend task and approval paths | Need actual repo inspection |
| MailProviderPort | Build narrow provider-neutral interface | Typed proposals/read/status |
| GmailAdapter | Build Gmail-specific MIME/REST/error mapping | No independent authorization |
| OAuthCredentialBroker | Build security-critical token custody | Tokens never model-visible |
| MessageProposal | Immutable, content addressed | Not an authorization |
| OwnerApprovalBinding | Reuse Core | Exact recipient/subject/body/attachment/thread/task hash |
| SendAuthorization | Short-lived single-use Core capability | Verify scope, expiry, binding |
| OutboxLedger | New, integrated with existing checkpoints | Durable record, not new scheduler |
| GmailThreadReader | New | Selected messages only |
| ReplyCorrelationVerifier | New | threadId, References/In-Reply-To, never From as identity |
| CommunicationAudit | Reuse Core audit + email receipts | Avoid parallel audit ledger of authority |
| HATStagingAdapter | Reuse HAT staging | Message provenance, untrusted flag |
| Android approval | Reuse operator controls | No additional signer |

## 3. Google OAuth and Gmail API policy findings

### 3.1 Desktop OAuth

- Desktop Authorization Code + PKCE with loopback redirect 127.0.0.1 on ephemeral port.
- Official native app guidance: https://developers.google.com/identity/protocols/oauth2/native-app
- OOB manual copy/paste deprecated: https://developers.google.com/identity/protocols/oauth2/resources/oob-migration
- PKCE S256; generate high-entropy verifier/challenge. One observed report of PKCE exchange failing without a client secret is a testing signal, not a reason to abandon PKCE.
- Linux runs OAuth consent in its local system browser. Android remains only an AIOA operator UI and does not hold authorization code, refresh token, or client secret.
- Store refresh token in OS secret store, never .env, Git, logs or ordinary unencrypted database.
- Revocation endpoint: https://oauth2.googleapis.com/revoke. A revoked token, invalid_grant or changed account scope fails closed.
- External Testing mode: 100 test users, generally 7-day refresh token lifetime for Gmail scopes.
- Public sensitive/restricted apps may require OAuth verification. A security assessment applies under Google's restricted-scope processing conditions; exact timeline and cost claims in the model's report were estimates, not established facts.
- Multi-user requires separately designed user isolation and per-user OAuth.

### 3.2 Scope classifications claimed by DeepSeek

| Scope | Claimed classification | Practical capabilities |
|---|---|---|
| https://www.googleapis.com/auth/gmail.send | Sensitive | Send messages only |
| https://www.googleapis.com/auth/gmail.readonly | Restricted | Read message/thread bodies |
| https://www.googleapis.com/auth/gmail.metadata | Restricted | Labels and headers, no body |
| https://www.googleapis.com/auth/gmail.compose | Restricted | Manage drafts and send |
| https://www.googleapis.com/auth/gmail.modify | Restricted | Broader read/update |
| https://www.googleapis.com/auth/gmail.labels | Non-sensitive | Labels only |
| https://mail.google.com/ | Restricted | Broad/full mail access |

MVP A: gmail.send only, local AIOA drafts, no Gmail drafts. MVP B: gmail.readonly only for messages/replies. MVP C: gmail.send + gmail.readonly. gmail.send alone cannot read the Sent folder or replies; gmail.compose is not needed for an in-AIOA draft.

### 3.3 Quotas, MIME, threading and send idempotency

- Claimed new project limits: 1,200,000 units/min per project and 6,000 units/min per user. messages.send 100 units, drafts.send 100, messages.get 20, messages.list 5, threads.get 40; newer daily billing threshold to verify.
- Pagination uses nextPageToken; do not assume one page is complete.
- Rate 429 and 5xx handling: truncated exponential backoff with jitter, but **NEVER automatically retry an ambiguous Gmail send**. Other read-only operations can use bounded retry.
- Gmail messages.send uses RFC 2822 MIME encoded base64url in the raw field. Attachments require multipart MIME.
- Threading may require threadId, consistent subject, References and In-Reply-To headers.
- Claimed Gmail could rewrite self-generated Message-ID, so treat it as a correlation hint, not an idempotency guarantee.
- No idempotency-key parameter for Gmail messages.send, so provider-level exactly-once cannot be guaranteed.
- UNKNOWN_SEND recovery: save intent and proposed Message-ID/hash before network call, query Sent/thread/readback where permitted, never blind retry. DeepSeek further proposed moving to CONFIRMED_NOT_SENT after five minutes with no match and permitting a new human-authorized attempt. **This inference is UNSAFE; an empty search is insufficient proof of non-delivery. Preserve UNKNOWN and require informed human decision; never certify negative delivery solely by absence in a search.**

### 3.4 Policy and privacy

- Google API Services User Data Policy / Limited Use: user-facing purpose, no resale/ads or disallowed data transfer. Privacy disclosures required under applicable distribution conditions.
- Google Workspace User Data/Developer Policy has approved productivity and email enhancement/reporting cases; app must describe actual use accurately.
- Raw Gmail data should not flow to third-party LLMs without appropriate consent/terms and explicit case-specific disclosure policy.
- Germany/EU: minimize personal data processing, encrypt stored content where needed, do not persist full mail into HAT by default; handle proper lawful basis, data retention/deletion and potential international data transfers. These are not final legal findings.

## 4. Three architecture alternatives

**A — Desktop-native OAuth loopback + in-process narrow adapter (recommended).**
Pros: no public callback, no Android OAuth, simple integration with Core, best for a single owner. Cons: temporary Testing-mode expiry, desktop client secret isn't confidential, loopback service lifetime/binding requires correct handling.

**B — Web OAuth client with public HTTPS callback.**
Pros: easier future multiuser deployment/central custody. Cons: public surface, state/callback/session/redirect security, more complexity and infrastructure. Not MVP.

**C — Workspace service account with domain-wide delegation.**
Suitable only for controlled Workspace domain/admin and broad privileges; not appropriate for consumer single-owner Gmail. Reject.

## 5. Architecture dataflow

~~~text
Android / ChatGPT presentation only
        |
        v
AIOA Core
  task state / Non-Zero / ServiceGuard / owner approval / STOP / replay
        |
        v
CommunicationPort / MailProviderPort (typed proposals; no tokens)
        |
        v
Gmail Gateway
  GmailAdapter ----- OAuthCredentialBroker (Keyring)
       |
  Durable OutboxLedger
       |
  ReplyCorrelationVerifier / CommunicationAudit / HATStagingAdapter
        |
        v
Gmail API (messages.send, messages.list, threads.get)

Reply direction:
Gmail API → selected thread reader → sanitized provenance envelope
  → untrusted evidence → Epistemic Control → HAT staging
  → separate human/policy review, NEVER automatic authority
~~~

## 6. Proposed module structure

~~~text
aioa/
  communication/
    ports/
      mail_provider.py
      models.py
    gmail/
      __init__.py
      adapter.py
      auth/
        broker.py
        loopback.py
        keyring_store.py
      send/
        mime_builder.py
        outbox_ledger.py
        send_authorization.py
        unknown_recovery.py
      read/
        thread_reader.py
        reply_correlation.py
        sanitizer.py
      audit/
        communication_audit.py
      errors.py
tests/
  offline/
    fake_gmail.py
    test_outbox_ledger.py
    test_unknown_recovery.py
    test_reply_correlation.py
  integration/
    test_live_send.py
~~~

DeepSeek acknowledges this proposed top-level package may not match actual installed runtime layout and requires repo inspection before adoption.

## 7. Typed interfaces

DeepSeek proposed immutable dataclasses and a Protocol:

~~~python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Sequence, Literal, Optional
from datetime import datetime

@dataclass(frozen=True)
class Recipient:
    address: str
    display_name: Optional[str] = None

@dataclass(frozen=True)
class AttachmentRef:
    filename: str
    mime_type: str
    sha256: str
    size_bytes: int

@dataclass(frozen=True)
class MessageProposal:
    proposal_id: str
    task_id: str
    thread_id: Optional[str]
    recipients: tuple[Recipient, ...]
    subject: str
    body_text: str
    body_html_sha256: Optional[str]
    attachments: tuple[AttachmentRef, ...] = ()
    in_reply_to: Optional[str] = None
    references: tuple[str, ...] = ()
    deterministic_message_id: str
    content_sha256: str
    created_at: datetime

@dataclass(frozen=True)
class SendAuthorization:
    authorization_id: str
    proposal_id: str
    task_id: str
    owner_approval_ref: str
    scope_granted: tuple[str, ...]
    expires_at: datetime
    single_use: bool = True

@dataclass(frozen=True)
class SendReceipt:
    proposal_id: str
    status: Literal["SENT", "UNKNOWN", "FAILED", "CONFIRMED_NOT_SENT"]
    provider_message_id: Optional[str]
    provider_thread_id: Optional[str]
    sent_at: Optional[datetime]
    reconciliation_hint: Optional[str]

@dataclass(frozen=True)
class ThreadMessage:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    body_text: Optional[str]
    received_at: datetime
    provenance: dict

class MailProviderPort(Protocol):
    async def validate_proposal(self, proposal: MessageProposal) -> list[str]: ...
    async def send_authorized(
        self, proposal: MessageProposal, auth: SendAuthorization
    ) -> SendReceipt: ...
    async def reconcile_send(
        self, proposal: MessageProposal, receipt: SendReceipt
    ) -> SendReceipt: ...
    async def get_thread(self, thread_id: str) -> Sequence[ThreadMessage]: ...
    async def list_selected_messages(
        self, query: str, max_results: int = 20
    ) -> Sequence[str]: ...
    async def get_message_metadata(self, message_id: str) -> dict: ...
~~~

Design requirements: model proposals cannot authorize; Core issues exact single-use token after actual owner action, full hash scope/recipient binding, broker hides refresh tokens, ledger before send, reconcile never sends, read functions return untrusted evidence. A mere Boolean single_use or approval_ref is not cryptographic proof; actual native Core authority mechanism required.

## 8. OAuth, token custody, privacy and human authority

- Store refresh tokens in keyring/libsecret or reviewed encrypted vault; access token in memory. Avoid storing any token fingerprints unnecessarily, especially across logs.
- Linux loopback binds 127.0.0.1 random port and shuts down on callback/short timeout; PKCE S256 and unpredictable state protect against interception/CSRF.
- Approvals bind exact recipient set, subject, body bytes/hash, attachments, task, proposal, scope and expiry; verify actual serialized MIME pre-send.
- Approval consumed exactly once durably; STOP before send, and ambiguous in-flight send must remain UNKNOWN, not STOPPED-with-guarantee.
- Revoked/expired refresh token requires explicit reauthorization; do not silently bypass.
- Logs contain limited nonsecret metadata; HAT staging stores source-backed summary not raw body; disclosure to external models needs explicit reviewed policy.
- Germany GDPR questions require actual data classification, deletion and legal basis review.

## 9. Durable send and UNKNOWN recovery

~~~text
Model draft → Core validates and shows exact recipient/body
 → owner approves → Core issues exact scoped capability
 → adapter rechecks binding and STOP → ledger INTENT/SENDING durable
 → Gmail messages.send
   → success receipt/id: SENT
   → lost ACK/5xx/timeout: UNKNOWN_SEND, never repeat automatically
 → optional read-only reconciliation with gmail.readonly
 → if not proven: UNKNOWN_REQUIRES_HUMAN, not proof of non-delivery
 → any new send needs informed owner authorization with explicit duplicate risk
~~~

DeepSeek originally proposed treating absence after a five-minute search as CONFIRMED_NOT_SENT; this recommendation is archived but disputed. No native exactly-once guarantee exists. Even observed SENT status may not guarantee final recipient delivery.

## 10. Threat model: 14 negative cases

| # | Threat | Defense/expected result |
|---|---|---|
| 1 | Model attempts send without approval | Core-bound authorizer denies; no Gmail call |
| 2 | Post-approval recipient/body tampering | Content hash mismatch, deny and audit |
| 3 | Email prompt injection | Treat as untrusted evidence; no instruction/authority |
| 4 | Spoofed collaborator reply | Thread/reference signals plus human identity confirmation |
| 5 | Gmail sends then network response lost | UNKNOWN_SEND; reconcile without resending |
| 6 | Restart/replay of task | Durable ledger idempotency prevents second call |
| 7 | OAuth token revoked | Fail closed, require owner reconnect |
| 8 | Android session compromised | No Gmail tokens on phone; separate Core authentication/approval |
| 9 | LLM data exfiltration | Redacted context, model egress policy and owner disclosure |
| 10 | HTML/attachment hostile content | Sanitize/quarantine, type/size/source caps |
| 11 | Two agents racing same thread | Single-writer/serialized ledger, conflict result |
| 12 | Approval reused on another message | Fingerprint/task/expiry/single-use rejection |
| 13 | Gmail quota exceeded | Bounded backoff for safe READ, not ambiguous send retry |
| 14 | STOP during send | Check before network call; if in-flight return UNKNOWN |

For high-impact statements or purported collaborator consent, sender name, From header and even mail authentication results are indicators, NOT identity or broad legal permission.

## 11. Multi-model orchestration

AIOA models only see a typed propose-message tool, never credential or raw HTTP client. One model may draft, another critic may review, but neither approves or sends. Provider hops and context resets do not elevate/preserve authority. AIOA Core revalidates task, exact proposal, scope, owner decision, expiry and STOP. Store minimal audit envelope: task/proposal/authorization IDs, recipient hash, content hash, provider ID/thread ID and result; no raw personal mail body.

## 12. Roadmap / estimates for low-RAM Linux PC

| Phase | Features | Tests / gates | Estimate |
|---|---|---|---|
| G0 | Repo integration review, typed mail contracts, threat model | No network, no credentials; tests fail closed | 1–2 days |
| G1 | Fake Gmail provider, durable ledger, UNKNOWN/reply correlation | Offline replay, spoof, injection, duplicated tasks | 3–5 days |
| G2 | Linux Desktop OAuth, PKCE loopback and keyring | Real test-account consent, refresh/revoke/expiry; owner action | 2–3 days |
| G3 | Exact single-owner-approved Gmail send and readback | First send to test recipient; content binding and LOST-ACK simulation | 3–5 days |
| G4 | AIOA provider orchestration + Epistemic Control + HAT staging | Model A drafts, B critiques, owner approves, reply is untrusted | 5–8 days |
| G5 | Android operator view through existing Core | No phone Gmail token, independent mobile signer or public endpoint | 3–5 days |

Auditor's original total estimate: ~17–28 working days for G0–G5, with ~9–15 working days to initial live send. This is an estimate not a schedule guarantee.

## 13. Chromium future boundary — no implementation

Keep provider-independent CommunicationPort/CapabilityGrant/EvidenceEnvelope/ApprovalBinding. Future managed-browser/Chromium implementation may use these interfaces under the same Core authorization, but do not implement browser, Chrome OAuth or public REST listener in Gmail MVP.

## 14. GOLD72 isolation

Gmail G1 fake conversations can run in isolated offline/SHADOW mode without modifying sealed GOLD72 source. Live pilot uses separate runtime/credentials/outbox/evidence and its own limits. HAT records from email are staged as untrusted. A separate Google Cloud project recommended. Gmail delivery should NOT become necessary for unrelated GOLD72 reliability PASS.

## 15. Ten architectural risks

1. Second authorization engine in adapter.
2. False exactly-once claim.
3. Restricted scope verification/CASA underestimation.
4. Prompt injection in email.
5. OAuth token leakage.
6. Stale/reusable approval.
7. Seven-day Testing refresh expiration.
8. Android independent approval/token.
9. Message-ID rewrite and reconciliation ambiguity.
10. Cross-contamination with Linux Sprint33/34 or GOLD72.

## 16. Errors/unsafe assumptions identified by DeepSeek

1. gmail.send is Sensitive, not Restricted.
2. gmail.compose is Restricted, so do not use Gmail drafts for MVP.
3. Gmail lacks native exactly-once messages.send.
4. From does not establish sender identity.
5. Android should not hold Gmail OAuth credentials for this Linux custody design.
6. Testing mode is a temporary piloting solution, not a durable production strategy.
7. Repo features described in initial prompt are not automatically production ready.
8. A public Web OAuth callback is unnecessary for a local single-owner desktop test.

## 17. Final implementation recommendation and acceptance gates

DeepSeek chooses Desktop Loopback OAuth + PKCE, MailProviderPort, existing AIOA Core sole authority, exact content-bound single-use send authorization, durable OutboxLedger, honest UNKNOWN_SEND, and untrusted HAT staging. First build G0/G1 offline with full negative tests. Then G2/G3 on owner-approved *test account* using gmail.send first, adding gmail.readonly for selected replies only after policy/consent review. No Chromium, external API access or GOLD72 runtime mutation.

Required before connecting owner account:
1. Offline G0/G1 PASS.
2. Explicit owner consent, preferably dedicated test Gmail first.
3. Dedicated GCP project/test-user config.
4. Desktop loopback 127.0.0.1 + PKCE S256.
5. Keyring/vault token custody and redacted logs.
6. Exact first-send owner review.
7. STOP tested before first live send.
8. Durable ledger + UNKNOWN negative tests.
9. Android UI only; no Android OAuth client.
10. No shared mutable GOLD72/Sprint33 runtime.

Blocked: broad scopes, unapproved outgoing messages, silent resends, auto HAT trusted promotion, email data egress without permission, publishing/CASA actions, remote bridge/Chromium or production LIVE claims.

## Official links supplied by DeepSeek

- Desktop native OAuth: https://developers.google.com/identity/protocols/oauth2/native-app
- OOB migration: https://developers.google.com/identity/protocols/oauth2/resources/oob-migration
- Scope table: https://developers.google.com/workspace/gmail/api/auth/scopes
- Quotas: https://developers.google.com/workspace/gmail/api/reference/quota
- Workspace data/developer policy: https://developers.google.com/workspace/workspace-api-user-data-developer-policy
- Limited Use: https://developers.google.com/terms/api-services-user-data-policy
- users.messages.send: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send
- Threading: https://developers.google.com/workspace/gmail/api/guides/threads
- Push: https://developers.google.com/workspace/gmail/api/guides/push

---

**Archive integrity statement:** This archive is a structured, substantive transcription of the supplied 17-section report with narrative compression and formatting cleanup. It does not present itself as byte-for-byte original. The exact chat text remains the primary user-supplied evidence. Google factual assertions and any code contract require separate official-documentation and AIOA source verification.
