# AIOA Gmail Gateway — Independent Model Audit Registry

**Scope:** Independent research for single-owner Gmail API integration in AIOA spArkHAT.
**Branch:** feature/aioa-gmail-gateway
**Received:** 2026-10-20
**State:** FIVE ANSWERS COLLECTED; GOOGLE PRIMARY-SOURCE CROSS-CHECK COMPLETED; NO PRODUCTION / LIVE AUTHORIZATION.

| ID | Model | Material received | Evidence file | Fact check |
|---|---|---|---|---|
| A01 | Meta AI | Summary only; file name cited by model but full document unavailable | [Meta](2026-10-20_META_AI_AUDIT_RECEIVED.md) | Pending |
| A02 | DeepSeek | Long 17-section answer; structured archival transcription; original remains in chat | [DeepSeek](2026-10-20_DEEPSEEK_FULL_AUDIT.md) | Pending for code/security claims |
| A03 | Claude Sonnet | Substantive short answer; full 16-section report was offered but not supplied | [Sonnet](2026-10-20_SONNET_AUDIT_RECEIVED.md) | Pending |
| A04 | Gemini | Long report with architecture, code, states and threat model; normalized structured archive | [Gemini](2026-10-20_GEMINI_AUDIT_RECEIVED.md) | Official scope errors found |
| A05 | Kimi | Summary only; claimed longer PDF-ready report not supplied | [Kimi](2026-10-20_KIMI_AUDIT_RECEIVED.md) | Pending |

**Architect's synthesis:** [Cross-model decisions and implementation plan](CROSS_MODEL_DECISIONS_AND_EXECUTION_PLAN_2026-10-20.md).

## Verified and disputed points

- Google's official scopes table: gmail.send is Sensitive; gmail.readonly, gmail.compose, gmail.metadata are Restricted. Some Gemini claims were incorrect.
- Gmail 2026-05-01 quota update is real; verify limits for *the actual* GCP project.
- Google desktop OAuth supports loopback + PKCE; Google's seven-day Testing-mode refresh token limit applies to ordinary Gmail scopes.
- Gmail messages.send documents no idempotency-key guarantee. On ambiguous result, NEVER infer non-delivery merely because a mailbox search was empty. Retain UNKNOWN_SEND and human review.
- A01/03/05 remain summary-only. Do not falsely advertise their underlying full reports as available.
- Google's verification and CASA requirements depend on actual scope/data/distribution configuration. Timeline and dollar figures given by models are not approved project estimates.
- The public Gmail branch was based on main 81656e6…, not the latest isolated S33/34; integrations require reconciled source pins.

## Collection and editing rules

1. Preserve every model response separately; never overwrite original accounts with a synthesized verdict.
2. Keep disagreements and source/verification caveats visible.
3. Cross-model report is advisory until current AIOA Core code, Google policies and user approval are independently checked.
4. Never put real OAuth tokens, Gmail contents, personal email addresses, client secrets or approval credentials into public GitHub documents or logs.
5. Do not edit main, current Linux Sprint33/34, GOLD72 source, or enable LIVE access from this registry.
