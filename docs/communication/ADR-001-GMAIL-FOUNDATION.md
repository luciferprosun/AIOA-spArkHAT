# ADR-001 — AIOA Gmail Gateway foundation (G0/G1)

Date: 2026-10-20. Status: **OFFLINE FOUNDATION ONLY**. Branch: feature/aioa-gmail-gateway.

## Decision

Use an inert Python package runtime.communication, inside the one canonical AIOA runtime. Proposed typed interfaces cannot create credentials, grant effects, open sockets, or send real messages. Immutable source-backed MailProposalV1 + deterministic plaintext MIME establish an exact action digest for the FUTURE Core approval gate. Neither hash nor a model-generated owner_scope_ref proves approval.

The production CoreMailEffectGate has **NO implementation here**. Real Gmail sending, OAuth, reading replies, and Android signing are all disabled/unavailable.

Existing public CoreAdmission is an in-process principal mechanism, NOT production authentication of a real human. runtime/mcp_bridge/approval.py validates a **public test key fixture** with grants_effect_authority=False; it MUST NEVER authorize Gmail. Native Core warrant/outbox and STOP integration require exact source-bound review after Linux S34 seals.

## Boundaries

- AIOA Core remains sole issuer and consumer of real owner effect authority.
- Gmail Gateway carries no independent signer, fake owner login or permission override.
- Model text, email text, GitHub Issues, fake credentials and assistant decisions are untrusted.
- No new externally reachable REST API, Google SDK, OAuth client, secrets or network call.
- Python >=3.11, standard library only for G0/G1.
- CC, BCC, HTML bodies, attachments and threading are deliberately **not qualified**; fail closed.
- The generated Message-ID uses the reserved .invalid domain as an OFFLINE correlation hint. Do not treat it as Gmail idempotency or guaranteed real-delivery header preservation.
- Personal message contents are absent from GitHub tests (fixture text only) and from outbox receipts.
- Sender domain verification, legal compliance, provider sender identity, token custody and mailbox reading are future independent gates.

## Integration source pins

Branch parent history: public main 81656e6ccbb0c02307d049e865b6df3225ddb578.
Inspected branch code:
- pyproject.toml contains no base dependencies; runtime.* packages auto-discovered.
- runtime/core_admission.py: LocalOwnerAssignment, CoreAdmission and Capability; process-local only.
- runtime/mcp_bridge/policy.py: unknown WRITE operations denied; current remote tools do not include Gmail.
- runtime/mcp_bridge/approval.py: Offline fixture signature never grants authority.
- tests/test_core_warrant.py documents native Core warrant ledger but is an offline fixture, not a live-owner signoff.
- runtime/main.py has legacy tools; **no hidden Gmail route will be added** in G0/G1.

## Next gate

G1 acceptance requires running tests/test_gmail_contracts.py on exactly committed files. G2 then adds a single-writer, crash-safe OFFLINE Outbox Ledger with negative replay/UNKNOWN tests, still no Gmail OAuth. Only after independent Core source review and real owner setup may a future phase enable live send.
