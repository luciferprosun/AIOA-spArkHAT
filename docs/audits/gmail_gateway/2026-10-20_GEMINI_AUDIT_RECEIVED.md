# A04 — Gemini: AIOA spArkHAT Gmail API Gateway independent audit

**Audit delivered by:** Gemini (per owner attribution)  
**Date:** 2026-10-20  
**Evidence:** Full long response pasted by owner. Section order and core content preserved below in readable Markdown; formatting normalized.  
**Verification:** External AI output — NOT independently accepted. In particular, Google's official scope table contradicts some of Gemini's classifications; see audit registry comparison.

## Executive Technical Recommendation

To integrate Google Gmail API into **AIOA spArkHAT** without violating AIOA’s core security invariants (**Provider is not authority**, **ZERO_WRITE by default**, **Human approval by default**, and **One Core**), we recommend a **Decoupled Outbox-Ledger Architecture with Mandatory Hash-Bound State Machine Seals**.

### Core Decision Highlights

1. **Zero-Trust Outbox Ledger:** AI models NEVER issue API calls or handle raw OAuth tokens. Models create a strictly typed, immutable MessageProposal inside the AIOA Core. Core enforces a cryptographic ApprovalBinding containing SHA-256 hashes of the exact recipient, subject, body, attachment hashes, and task ID.
2. **Explicit Human Authority via Loopback OAuth:** For a single-owner Linux environment (Ubuntu/Mint), use a Desktop App (Native/Loopback) OAuth client configuration using PKCE (RFC 7636). Refresh tokens are stored encrypted via OS-level secret storage (SecretService/keyring with AES-256-GCM backed by a passphrase/hardware TPM/keychain), completely inaccessible to model context or agent processes.
3. **Strict Scope Minimization:**
   - **MVP A (Draft & Send):** gmail.send (**Gemini claims Restricted**) or gmail.compose (**Gemini claims Sensitive**) + gmail.send.
   - **MVP B & C (Full Bidirectional Exchange):** gmail.send + gmail.readonly.
   - **Banned Scopes:** mail.google.com (full access—excessive and dangerous) and gmail.modify/gmail.labels (unnecessary for simple communication).
4. **Deterministic UNKNOWN_SEND Protocol:** Gmail API's users.messages.send does NOT provide native idempotency keys. Network drops/5xx can cause duplicate sends if blindly retried. Gateway enforces pre-send draft creation or cryptographic Client-Header tracking. If HTTP response is lost, move to UNKNOWN_SEND and freeze automatic retries until reconciliation checks (users.messages.list by RFC 5322 Message-ID) verify status.

## 1. Existing AIOA Baseline vs. New Gateway Requirements

Based on repository inspection and architectural alignment with AIOA-spArkHAT:

| Architectural responsibility | Existing AIOA system capabilities (claimed) | Required Gmail Gateway extensions |
|---|---|---|
| Authority & approvals | Human-controlled authority, ServiceGuard, STOP controls | OwnerApprovalBinding with payload hash seal |
| Model operations | MCP Bridge / MCP Commander, Bounded Execution | Typed GmailToolCall schema (proposals only) |
| Data safety | Non-Zero safety, ZERO_WRITE default | Outbox ledger with DRAFT_ONLY default posture |
| Epistemic integrity | Epistemic Control, independent criticism | ReplyCorrelationVerifier & untrusted evidence tagging |
| State & persistence | Checkpoints, receipts, persistent task state | OutboxLedger table + UNKNOWN_SEND reconciliation |
| Knowledge capture | HAT knowledge and memory management | HATStagingAdapter for extracted email evidence |

## 2. Google OAuth 2.0 & Gmail API Policy Research

### OAuth 2.0 Architecture

- **Client type:** Desktop Application: https://developers.google.com/identity/protocols/oauth2/native-app
- **Flow:** Authorization Code + PKCE (RFC 7636). Linux app launches loopback web server, such as 127.0.0.1:AUTO_PORT/oauth2callback.
- **Deprecated/unsafe:** Out-of-band manual copy/paste (urn:ietf:wg:oauth:2.0:oob) deprecated and blocked; embedded WebViews blocked.
- **Android/Linux:** Android acts only as remote client UI; no Google secrets or refresh token on Android. Linux AIOA Core initiates authorization or retrieves locally stored credentials.
- **Custody:** OS secret stores with encrypted-at-rest refresh tokens and 0600 file permissions.
- **External Testing mode:** Explicitly allow up to 100 test users; Gemini claims refresh tokens expire after 7 days if not continuously refreshed. The final clause requires correction against Google docs.

### Gmail scopes and policy verification classifications

**The following table preserves Gemini's claims and is NOT validated:** Google's current official page classifies gmail.send Sensitive; gmail.compose and gmail.metadata Restricted, contrary to Gemini.

| Scope | Gemini's classification | Use |
|---|---|---|
| gmail.send | Restricted (incorrect) | MVP A/C send |
| gmail.readonly | Restricted | Read/search |
| gmail.compose | Sensitive (incorrect) | Draft operations |
| gmail.metadata | Sensitive (incorrect) | Headers/labels |
| gmail.modify | Restricted | Not recommended |
| mail.google.com | Restricted | Broad full access, banned by proposed policy |

Gemini asserted restricted scopes require Limited Use compliance and for public apps a CASA security assessment; one-owner test app could use Testing mode. Actual applicability requires evaluating Google policy, data storage/transmission and user distribution context.

## 3. Recommended Architecture Diagram & Data Flow

~~~text
AI AGENT LAYER
  Multi-Model LLM / Epistemic Critic / Prompt Context (NO TOKENS)
                   |
                   v Propose + critique
AIOA CORE GATEWAY
  MessageProposal Engine
                   |
  Cryptographic Approval Binding
  SHA-256(recipient, subject, body, attachments, task ID)
                   |
  HUMAN OWNER UI: exact text + digest → APPROVE/REJECT
                   |
  ServiceGuard + SendAuthorization
                   |
  Gmail Adapter + Outbox Ledger + Token Custody
                   |
                   v HTTPS
Google Gmail API: users.messages.send / users.threads.get / users.messages.list
~~~

Models can propose drafts. Core computes/revalidates exact hashes and obtains explicit human authorization. The adapter enforces ledger state and calls Google.

## 4. Proposed Repository File & Module Structure

New self-contained proposed module under aioa/gateways/gmail:

~~~text
aioa/
  gateways/
    gmail/
      __init__.py
      contracts.py         # typed dataclasses and enum definitions
      exceptions.py
      oauth_broker.py      # PKCE and Linux keyring
      approval.py          # hash and owner approval binding
      outbox_ledger.py
      adapter.py           # Gmail REST/MIME send and read
      thread_reader.py
      hat_staging.py
tests/
  gateways/
    gmail/
      test_approval_binding.py
      test_outbox_ledger_state.py
      test_idempotency_recovery.py
      test_security_threats.py
~~~

## 5. Typed Contracts & Minimal Interface Definitions

Gemini proposed Pydantic schema definitions:

~~~python
import enum
import hashlib
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, EmailStr, Field

class OutboxState(str, enum.Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENDING = "SENDING"
    SENT = "SENT"
    UNKNOWN_SEND = "UNKNOWN_SEND"
    FAILED = "FAILED"
    REVOKED = "REVOKED"

class MessageProposal(BaseModel):
    proposal_id: str
    task_id: str
    sender: EmailStr
    recipient: EmailStr
    subject: str
    body_text: str
    body_html: Optional[str] = None
    custom_message_id: str = Field(description="RFC 5322 Unique Message-ID for tracking")
    attachment_hashes: List[str] = Field(default_factory=list)

    def compute_payload_hash(self) -> str:
        """Computes deterministic SHA-256 seal over proposal content."""
        hasher = hashlib.sha256()
        hasher.update(self.task_id.encode('utf-8'))
        hasher.update(self.recipient.lower().encode('utf-8'))
        hasher.update(self.subject.encode('utf-8'))
        hasher.update(self.body_text.encode('utf-8'))
        for att in sorted(self.attachment_hashes):
            hasher.update(att.encode('utf-8'))
        return hasher.hexdigest()

class OwnerApprovalBinding(BaseModel):
    approval_id: str
    proposal_id: str
    payload_hash: str
    approved_by_owner: bool
    timestamp: datetime
    owner_signature: str  # HMAC or signed token from owner UI

class Receipt(BaseModel):
    proposal_id: str
    gmail_message_id: Optional[str]
    gmail_thread_id: Optional[str]
    state: OutboxState
    error_details: Optional[str] = None
    executed_at: datetime
~~~

**Cross-audit concern:** The proposed concatenated-string SHA-256 omits sender, body_html and other material and lacks unambiguous canonical serialization. This has NOT been adopted.

## 6. Delivery, Idempotency and UNKNOWN_SEND Recovery

Gemini proposes:

~~~text
INITIATE SEND
  → Create deterministic RFC 5322 Message-ID header
  → Durable ledger SENDING
  → POST users.messages.send
      ├─ HTTP 200 → SENT
      └─ Network failure / 5xx → UNKNOWN_SEND
           → query users.messages.list(rfc822msgid:...)
               ├─ FOUND → SENT, no retry
               └─ NOT FOUND → FAILED / re-approval
~~~

Details:
1. Inject Message-ID: <AIOA-TASKID-PROPOSALID@domain.com> into raw MIME.
2. Persist SENDING on disk before API call.
3. On loss of response transition to UNKNOWN_SEND and NEVER automatically retry.
4. Reconcile by Gmail messages.list query; Gemini claims nonempty result means delivered and empty result means never delivered, then FAILED with re-approval.

**Critical audit caveat:** A negative search result does NOT prove non-delivery; UNKNOWN must remain until sufficient independent evidence/human judgment. Gmail does not guarantee exactly-once, and a matching Message-ID is not guaranteed unique API idempotency.

## 7. Security Threat Model & Mitigation Matrix

| Scenario | Risk | Mitigation | Failure/recovery |
|---|---|---|---|
| Unauthorized send by model | Critical | ServiceGuard & hash-bound owner approval | Reject, log |
| Recipient/body modification | Critical | Verify exact payload hash | Block, alert |
| Indirect prompt injection | High | Untrusted external evidence + Epistemic Control | Isolate, no effect |
| Forged collaborator reply | High | SPF/DKIM metadata signals, no authority | Informational only |
| Stale approval reuse | Medium | Proposal ID, single use, 15-minute expiry | Reject |
| Credential leakage in prompts/logs | Critical | OS keyring, logging sanitization | Secret-pattern tests |

## 8. Implementation Roadmap

- **G0 — Contracts & threat model (3 days):** contracts, exceptions, Pydantic schemas, tests for hash seals.
- **G1 — Offline Gmail simulator & outbox ledger (4 days):** fake API simulates network loss/UNKNOWN; durable ledger with file locking.
- **G2 — Real OAuth & token custody (3 days):** Desktop PKCE loopback, Linux keyring; authorized test account.
- **G3 — Controlled pilot (4 days):** approved send and reply readback; UNKNOWN recovery.
- **G4 — Multi-model orchestration (5 days):** Gemini drafting, Claude critique, Epistemic Control and HAT staging.
- **G5 — Android approval UI integration (4 days):** display and signing via existing Core.

## 9. Future Architecture Boundaries

The proposed CommunicationPort and MailProviderPort abstractions allow later browser-based webmail or Chromium drivers beneath the same AIOA Core/ServiceGuard/approval boundary. No Chromium implementation now.

GOLD72 remains an isolated runtime; Gmail gateway optional OFFLINE_SIMULATOR mode with synthetic messages only. No external network dependence in qualification.

## 10. Top 10 Architectural Risks

1. Gmail messages.send has no native idempotency; duplicate send on ambiguous failure.
2. Testing-mode refresh token lifetime misinterpreted.
3. Prompt injection in inbound mail.
4. Approval payload displayed by UI may not match exact raw MIME bytes.
5. OAuth token leakage in HTTP traces.
6. Quota exhaustion/HTTP 429; Gmail account daily send limits.
7. Multiple models acting on one thread.
8. Loopback port unavailable in headless Linux.
9. Accidental mail.google.com/ overly broad scope.
10. Interrupted durable state write during power loss.

## 11. Final Recommendation

Adopt Decoupled Outbox-Ledger Architecture with cryptographic hash seals and RFC 5322 Message-ID reconciliation.

Proposed Gmail scopes:
- https://www.googleapis.com/auth/gmail.send
- https://www.googleapis.com/auth/gmail.readonly

Quickest route: G0 contracts and G1 simulator offline, then G2 Google Cloud Desktop OAuth client in Testing, then G3 one manually approved send.

Blocked: no auto-send without owner, no mail.google.com, no untrusted email command execution.

---

**Preservation note:** Some HTML entities and table layout in the original pasted answer were normalized. Claims, technical direction, schema, and risks are recorded for independent comparison, not as verified design facts.