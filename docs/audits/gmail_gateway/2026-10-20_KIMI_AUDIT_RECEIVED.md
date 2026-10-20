# A05 — Kimi independent Gmail Gateway audit (received summary)

**Date:** 2026-10-20
**Author:** Kimi, per user attribution
**Completeness:** Only the supplied summary; the model says a longer PDF-ready Markdown exists but did not provide the document.
**Verification:** Unverified external model findings; NOT implementation authority.

---

I'll approach this as an independent audit: first verify current Google OAuth/Gmail policy facts against official documentation, then inspect the actual repository before making any claims about what exists.

I got the quota and scope facts (with some important 2026 changes to verify). The direct URL fetches were rejected, so I'll use targeted searches against official documentation for the remaining policy facts.

The README confirms the real repository layout. Let me inspect the key architecture docs and runtime modules to ground the audit in actual code structure.

I have enough verified policy facts and repository grounding. Now I'll write the full audit report to a PDF-ready Markdown file.

The full audit is complete and saved as a PDF-ready Markdown report. Summary of the load-bearing findings:

**Verified Google policy facts (do not re-derive from memory):**
- **Scopes:** gmail.send is *Sensitive* (send-only, no read, no security assessment); gmail.labels is non-sensitive; gmail.readonly, gmail.compose, gmail.metadata, gmail.modify, and mail.google.com/ are all *Restricted* — restricted scopes trigger verification plus an annual security assessment for production, and the Limited Use policy fully applies. Workspace policy confirms any Gmail scope that reads/creates/modifies mail is restricted.
- **Quotas changed 2026-05-01:** new projects get 1.2M units/min per project, 6,000 units/min per user, 80M-unit daily billing threshold; messages.send costs 100 units, threads.get 40, messages.get 20, history.list 2. Confirm your project's actual values in the Cloud Console, since older projects keep legacy quotas.
- **OAuth:** Desktop/installed client with loopback + PKCE is the correct flow; the OOB copy-paste flow was blocked for new clients from Feb 2022. Testing mode = 100 test users and **refresh tokens expiring in 7 days** — plan weekly re-auth or publish the app, and never "fix" expiry by re-consenting in a loop (50-token silent revocation cliff).
- **Idempotency: Gmail messages.send has none.** Idempotency keys are a provider-specific feature that some modern email APIs added explicitly — Gmail is not among them. The entire reliability design therefore hinges on the self-generated RFC 822 Message-ID + UNKNOWN_SEND + human-gated reconciliation in the report's §8.

**Core architectural verdicts:**
1. Your proposed component list is 60% rename-and-reuse; only the adapter, credential broker, outbox ledger, and reply correlator are genuinely new. The repo's existing MCP_APPROVAL_TOKEN_V1_FIXTURE, ServiceGuard, receipt/checkpoint chain, and FORBIDDEN_MEMORY_FLOWS discipline absorb most of it — but that must be confirmed by a half-day spike against a local checkout (all repo claims in the report are flagged as structural, not line-level).
2. The "tool sidecar" and "Gmail-drafts staging" architectures are rejected; the recommended design is an in-Core runtime/gateway/ module behind a ChannelPort, executed as a ServiceGuard effect.
3. Build the UNKNOWN_SEND state machine and the 14-case negative test suite **before any credential exists** — fastest honest route to the first real email is 1 week (G0→G1→G2, gmail.send only).
4. The published-but-unverified-app token-lifetime behavior for restricted scopes is a flagged gray zone to confirm at G2.

---

**Record limitations:** The Kimi full report was NOT attached in the user's message. Claims of repo inspection and up-to-date documentation were made by Kimi and have not been independently authenticated. The model's phrase about *50-token* silent revocation differs from Google's separately published limits and must be checked rather than treated as fact.