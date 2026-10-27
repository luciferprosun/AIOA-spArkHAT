# META-P3-01 — OFFLINE provenance/correlation handoff

**Status:** IMPLEMENTED + OFFLINE-TESTED. **NOT G4 LIVE.**
**Author:** ChatGPT, implementing the owner's explicit 27 October 2026 instruction; **not a Muse Code run**.
**Baseline Git branch:** meta only, source SHA cd5062bfa543487164eb6e1c8f247ad98a6f0b72.
**Output commit:** inspect Git history after push; not predeclared.
**No real Meta API, Chromium, credentials, Gmail or network calls.**

## Changed-file allowlist

1. runtime/meta_hackathon/offline_correlation.py
2. tests/test_meta_p3_correlation.py
3. docs/meta/META_P3_01_HANDOFF.md

Existing AIOA Core, MCP bridge, warrant logic, main, Nebius, Gmail and Codex workspaces were not changed.

## Design / authority

- OfflineCorrelationLedger receives a typed BrowserTaskV1, BrowserObservationV1, and optionally a P2-02 ProviderReceipt. It does not launch browser/network effects.
- It binds task_digest, owner_scope_digest, source SHA, exact public allowlisted target URL, content SHA-256 (recomputed from the host-provided fixture), observation digest, optional synthetic receipt digest and UTC timestamps.
- An internally consistent tuple becomes OFFLINE_LINKED_UNVERIFIED, **never VERIFIED**. Missing receipt, missing content or failed/uncertain fixture outcomes produce UNKNOWN.
- STOP, expired task/receipt, wrong owner/source/task binding, cross-origin URLs, unproven redirects, corrupted content or replay are rejected; the one-shot ledger uses an atomic lock.
- Browser page content is untrusted opaque data, never a model instruction, approval or authentication source.
- Public serialization contains only allowlisted metadata and hashes; it excludes page body, prompt, credentials, raw receipts and cookies.
- Records are in-memory/offline contracts, not independent proof that a real browser has run. Digest consistency is not cryptographic authentication of the original website.

## Test evidence (27 October 2026)

From isolated /home/l/projects/AIOA-spArkHAT-META checkout:

    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_p3_*.py' -q
    # 20/20 PASS (OFFLINE)

    PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_*.py' -q
    # 147/147 PASS (OFFLINE)

Cases include valid links, missing receipt/content → UNKNOWN, forged owner/task/source, expired or future evidence, alternate origin and URL redirect, content tampering, hostile page instructions, replay and concurrency, STOP, malformed Unicode, secret-free output and network monkeypatch denial.

## Risks, STOP, next gate

- No real Meta provider receipt; P2-02 mock budget labels do not cap actual spending.
- No Chromium/CDP session, OS-level egress containment or trusted observation attestation.
- No durable event ledger or real operator approval. For a future LIVE G4, provenance must include verified browser readback, real model source and approved network controls.
- **P1-05 Chromium LIVE, P2-03 Meta API LIVE and all consequential browser/Gmail WRITE are BLOCKED** until the owner independently approves appropriate domains/model/budget/safety gates.
- No automatic transition to P3-02 or owner-facing demo-ready status from this OFFLINE evidence.
- Previous overnight Muse P2-02 failure and spent-session indicator remain preserved separately in private RaportyMUSE. No new Muse model session was invoked.
