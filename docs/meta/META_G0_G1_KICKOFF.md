# META 2026 — G0/G1 kickoff engineering checkpoint

**Date:** 26 October 2026 · **Branch:** meta · **Scope:** offline contract skeleton and security tests

## What this commit does

- Introduces runtime/meta_hackathon/ as an additive, dependency-free package.
- Defines strict BrowserTaskV1, BrowserObservationV1, ActionProposalV1 and canonical correlation hashes.
- Screens external HTTPS navigation proposals against an exact origin allowlist, immutable owner-scope digest, pinned source SHA, deadline and STOP.
- Forbids userinfo, alternate URL schemes, URL fragments/queries, raw IPs, explicit ports, encoded/relative paths, localhost/private suffixes and arbitrary effect operations at the contract layer.
- All accepted READ proposals return CORE_ADMISSION_REQUIRED, never executable permission; all effect proposals require exact owner review or are denied.
- Treats browser observations as UNVERIFIED_EVIDENCE until independently corroborated; no fabricated VERIFIED state.
- Adds a reproducible hermetic unittest suite: python -m unittest discover -s tests -p 'test_meta_hackathon_contracts.py' -v

## What this commit does NOT do

- No real Chromium/Playwright navigation, browser profile, screenshots or computer control.
- No Meta Model API call, Muse login, inference credit spending, OAuth or Gmail access.
- No new Core, warrant issuance, MCP EXEC/WRITE route, Android service or public web endpoint.
- No touching main, Gmail branch, Nebius branch, Codex workspace or GOLD72 state.

## Required follow-up gates

1. Official contest rules: owner must accept the published rules; check eligibility of reusing existing AIOA Core and start-time requirements. Public event page still states that official rules will be published before kickoff; access can be participant-only.
2. G1 integration design: existing runtime/core_admission.py, runtime/mission/warrant.py, runtime/mission/browser_preview.py and MCP Commander are authority sources. New contracts must not replace or bypass them.
3. G2 LIVE browser: add a Chromium adapter only after isolated profile, DNS resolution/IP filtering including all redirects, multi-tab escape prevention, downloads denied, timeout/STOP, transport admission, evidence integrity and Core lease validation. Domain syntactic validation alone does not prevent DNS rebinding.
4. G3 Meta planner: use Meta Model API under operator-provided credentials and a known, approved spend cap. Never log keys; use a real eligible model call for competition demonstration. Default to no network, no spend.
5. Human effects: no real click/submit/type/send permitted by this module. Exact one-use owner warrant, durable pre-effect receipt and post-effect reconcile must be independently audited before execution.

Success label: META_G1_OFFLINE_CONTRACTS_TESTED only after passing tests. Never label this as LIVE_BROWSER, REAL_META or DEMO_READY.

## Sources checked at kickoff

- Official event: https://dev.meta.ai/events/global-hackathon
- Meta API: https://dev.meta.ai/docs/overview
- Existing start line: META_HACKATHON_START_LINE.md
