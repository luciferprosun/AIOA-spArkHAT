# AIOA Gmail Gateway — Meta AI independent audit (received summary)

- **Auditor (as identified by sender):** Meta AI
- **Received:** 2026-10-20
- **Project:** AIOA spArkHAT
- **Target branch:** `feature/aioa-gmail-gateway`
- **Evidence type:** User-pasted auditor summary, preserved without independent validation
- **Full report claimed by auditor:** `AIOA_Gmail_Gateway_Arch_Report.md`
- **Full report received as attachment:** **NO — NOT AVAILABLE**. This file does not represent or reconstruct the full report.
- **Review status:** `RECEIVED_SUMMARY_ONLY / INDEPENDENT_FACT_CHECK_PENDING / NOT_APPROVED_FOR_IMPLEMENTATION`
- **Secrets:** None intentionally included

## Exact supplied response

> Meta Full independent audit completed — research only, no code changes.
>
> I've synthesized all official Google policy findings, quota/idempotency behavior, and AIOA integration analysis into a professional architectural report:
>
> **📄 📎 AIOA_Gmail_Gateway_Arch_Report.md**
>
> TL;DR - Principal Architect Recommendation:
>
> Architecture: Sidecar Communication Gateway (not in-process library). AIOA Core remains sole authority, sidecar owns OAuthCredentialBroker + OutboxLedger, models never see tokens.
>
> Minimum safe scopes:
>
> MVP A (send only): gmail.send only — sensitive, not restricted vs restricted list, so no CASA blocking
>
> MVP B/C (read + monitor reply): Requires gmail.readonly (restricted) → triggers 6-week verification + annual CASA assessment $500-4500/yr
>
> Fastest to first real email:
>
> G0 contracts (2d) → G1 offline simulator with UNKNOWN handling (3d) → G2 PKCE loopback bootstrap (2d) → G3 one exact owner-approved send via users.messages.send, verify raw MIME base64url and no idempotency.
>
> Exact conditions to connect account: Linux Desktop OAuth client + loopback 127.0.0.1:random + PKCE S256, encrypted storage 0600, Testing mode limits (100 users, 7-day refresh expiry), owner runs bootstrap locally.
>
> Must remain blocked: All restricted scopes, auto-retry of UNKNOWN_SEND (requires manual Sent folder check), token on Android, unauthenticated REST for future Chromium, Gmail body in logs/GitHub, foundation model training per Limited Use, and any GOLD72 sealed source modification.
>
> The report includes:
> 2 architectures compared (tight vs sidecar)
> Full typed contracts (Pydantic)
> 14-scenario threat model with prevention/detection/recovery/tests
> G0-G5 roadmap with time estimates for 4GB Mint + Android operator
> GDPR Germany compliance mapping
> 10 top risks and unsafe assumptions in proposal
>
> All conclusions cite official docs — OAuth native flow, loopback migration, quotas, User Data Policy, and scope tables.

## Review/verification queue (not endorsement)

1. Verify official Google scope classifications and separate **restricted scope classification**, **OAuth verification requirements**, and **CASA assessment applicability**; their conditions are not universal simply because a scope is requested.
2. Check quoted cost and six-week lead time as **unverified model estimates**, not confirmed Google policy.
3. Compare sidecar process costs, IPC attack surface, token custody, restart/durability and resource isolation against the existing single-core AIOA architecture.
4. Check that `0600` file permissions and encryption claims are independently specified; permissions alone do not encrypt credentials.
5. Verify sender-message correlation cannot be equated with authentication of a person and that `UNKNOWN_SEND` never triggers blind resend.
6. Request the full `AIOA_Gmail_Gateway_Arch_Report.md` to inspect official URLs, threat matrix, contracts and actual recommendations before accepting findings.
7. Respect the user's boundaries: no Gmail OAuth connection, outbound email, Chromium implementation, LIVE activation, or changes to main based solely on this report.

## Provenance notes

This document was transcribed from the user's 2026-10-20 chat message. The quoted claims are statements of the external auditor as relayed by the user, **not verified technical requirements**. No code, OAuth credentials, Gmail messages, or API interactions were involved in storing this summary.
