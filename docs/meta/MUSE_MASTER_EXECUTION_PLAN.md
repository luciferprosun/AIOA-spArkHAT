# AIOA METAGuardiansSPARK — Muse Master Execution Plan 2026

**Branch:** `AIOA-METAGuardiansSPARK` only · **Origin:** https://github.com/luciferprosun/AIOA-spArkHAT.git · **Pinned source SHA:** `c7c73e929d717181a6405936285c5d3e8631ba86`
**Branch identity update:** 31 October 2026; previous branch meta renamed to AIOA-METAGuardiansSPARK. Historical plan SHAs and test evidence are dated; always revalidate current HEAD before execution.
**Window:** 26 Oct – 4 Nov 2026 · **Deadline:** 4 Nov 21:00 Eastern · **Date of plan:** 26 Oct 2026
**Roles:** Muse Code = implementer (bounded tasks only). ChatGPT = architecture + QA gatekeeper. Owner = sole authority for spend, data, effects.

## Gate status from evidence (no live claims)

| Gate | Status | Evidence |
|---|---|---|
| G0 GO / kickoff | READY (offline planning) | `META_HACKATHON_START_LINE.md`, G0/G1 kickoff doc |
| G1 contracts | READY (offline-tested) | `runtime/meta_hackathon/contracts.py`, `policy.py`, `mcp_offline_plan.py`, `worktree_guard.py`; 60/60 hermetic META suite PASS on independent re-run (includes Muse plan contracts) |
| G2 network preview | IN_PROGRESS (offline preview only) | `runtime/meta_hackathon/network_admission.py`; NOT a Chromium driver, NOT network certification |
| G2 real Chromium | NOT_STARTED | No browser launch verified |
| G3 real Meta Model API | BLOCKED (product) | Muse Code coding session successfully authenticated to Meta Model API (CLI codegen), but end-product AIOA Runtime G3 has NOT made its own real Meta probe. No product live call, no spend approval, no product credential use. CLI codegen ≠ product model integration; no live Chromium or end-product live Meta implied. |
| G4 evidence correlation | NOT_STARTED | Depends on G2+G3 |
| G5 approvals | NOT_STARTED | Existing `runtime/mission/warrant.py` is authority baseline; no new warrant issuance |
| G6 Android operator | NOT_STARTED | Design only |
| G7 Gmail draft-only | NOT_STARTED (skippable) | Separate branch; never a prerequisite |
| G8 demo proof | NOT_STARTED | — |
| G9 submission | NOT_STARTED | — |

Offline PASS is never relabelled LIVE. Report levels: READY / IN_PROGRESS / BLOCKED / NOT_STARTED, plus report tags IMPLEMENTED / OFFLINE-TESTED / LIVE-VERIFIED / BLOCKED / NOT-STARTED.

## Working phases (chronological)

### Phase 1 — G2 real isolated Chromium READ (28 Oct; prompts META-P1-01 … META-P1-05)
- **Objective:** audited, isolated Chromium adapter; allowlisted public-page READ/navigation with timeout/cancel/STOP; provenance-carrying observations. No WRITE. One instrumented LIVE public-doc READ only as final gated proof (P1-05).
- **Prerequisites:** G0/G1 offline outcomes reused as-is (60/60 offline PASS, no live claim); URL allowlist OWNER_APPROVAL_REQUIRED before any live network (owner may choose a public documentation test site later; development uses synthetic fixtures); isolated ephemeral profile + OS network containment decision (Playwright/CDP evaluation; installing Playwright is NOT authorized by this plan).
- **Prompts:** META-P1-01 audit existing browser surface (`runtime/tools/browser_tools.py` legacy — NOT approved — vs new adapter boundary); META-P1-02 adapter skeleton + Core admission wiring design (no live run); META-P1-03 offline navigation/timeout/STOP tests; META-P1-04 DNS-rebinding/redirect/subresource/download threat review; META-P1-05 one instrumented LIVE public-doc Chromium READ (isolated browser + OS network containment, owner + QA permission-gated; BLOCKED until both gates, never auto-run).
- **Allowed files:** new `runtime/browser_agent/*` (or equivalent additive module) + tests only; READ-only reuse via imports of `runtime/core_admission.py`, `runtime/mcp_bridge/*`, `runtime/mission/warrant.py`. Never edit Core.
- **Expected tests:** hermetic unit tests for allowlist, redirect rejection, timeout/cancel, observation schema; LIVE distinction: no live navigation until owner approves domains + OS egress isolation.
- **Risk gate:** DNS rebinding (Python checks don't pin Chromium DNS), redirects, subresources/service workers, downloads, cross-task cookie/profile leakage, screenshot provenance.
- **Evidence:** test logs, review notes, threat checklist; observations tagged UNVERIFIED until corroborated.
- **Exit criteria:** offline adapter + tests pass; audit finds no personal-profile use, no WRITE path; ChatGPT QA signs G2-offline.
- **Rollback:** delete/disable additive adapter; G1 contracts unchanged.
- **Cost:** zero (no paid calls, local only).
- **Dependency:** builds on G1; gates all later phases.

### Phase 2 — G3 real Meta Model API planning path (29 Oct; META-P2-01 … META-P2-03)
- **Objective:** one budget-controlled real call through an eligible Meta model (plan/perception/critique as untrusted proposal); raw provider receipt audited, no secrets logged.
- **Prerequisites:** owner confirms eligible model, price, quota, cost ceiling + explicit probe approval; Phase 1 offline adapter exists.
- **Prompts:** META-P2-01 provider-path design reusing `runtime/providers/openai_compatible.py` as evaluated base (no new Core); META-P2-02 spend-cap/receipt-redaction harness (offline, mocked transport); META-P2-03 single owner-approved live probe + receipt (owner-supervised only).
- **Allowed files:** additive provider/planner module + tests; READ imports of existing provider base.
- **Expected tests:** OFFLINE: cap enforcement, key redaction, malformed-response handling. LIVE (once, owner-approved): one minimal call, model/version recorded.
- **Risk gate:** spend, key leakage into logs/repo/evidence, provider-substitution on failure, model output treated as authority.
- **Evidence:** redacted receipt, model/version, timestamp, SHA, spend.
- **Exit:** one verified real Meta receipt with `provider != authority` preserved; failure path bounded (no silent substitution).
- **Rollback:** revoke/rotate key handling per owner; disable live path, offline harness remains.
- **Cost:** owner-capped; one minimal probe first.
- **Dependency:** requires Phase 1 scoping; owner + ChatGPT QA gate before any live call.

### Phase 3 — G4 AIOA+MCP+evidence correlation (30 Oct; META-P3-01 … META-P3-03)
- **Objective:** end-to-end correlation task→observation→receipt with provenance; injection/tamper tests.
- **Prerequisites:** Phases 1–2 exit criteria met.
- **Prompts:** META-P3-01 correlation IDs + `BrowserObservationV1` provenance; META-P3-02 adversarial page-instruction/injection tests; META-P3-03 evidence index + verified-run manifest draft.
- **Allowed files:** additive evidence module + tests; imports of Core/MCP/warrant (no edits).
- **Expected tests:** mismatch screenshot-vs-claim → UNKNOWN; tamper → DENY/flag; missing evidence → FAIL.
- **Risk gate:** certifying success without evidence; trusting screenshots as proof of unseen ops.
- **Evidence:** evidence index, manifest, tamper-test log.
- **Exit:** correlated offline run green; adversarial cases fail closed.
- **Rollback:** keep prior phase artifacts; drop correlation module.
- **Cost:** zero beyond Phase 2 spend.
- **Dependency:** Phases 1–2.

### Phase 4 — G5 approvals / protected effects (31 Oct; META-P4-01 … META-P4-03)
- **Objective:** risk-tiered action proposals + exact one-use owner warrant binding (payload hash, nonce, scope, expiry); synthetic scenarios only, never silent WRITE.
- **Prerequisites:** Phase 3 provenance; `warrant.py` ledger as authority (READ-only reuse).
- **Prompts:** META-P4-01 risk classification; META-P4-02 warrant-binding + replay/expired/forged denial tests; META-P4-03 STOP/preview/reconcile (UNKNOWN, no auto-replay of writes) flow.
- **Allowed files:** additive approval module + tests; no warrant-issuance changes.
- **Expected tests:** absent/expired/forged/consumed/wrong-target warrant → DENY; lost-ack → UNKNOWN + reconcile.
- **Risk gate:** model minting approvals; vague "yes use browser" approvals; replay.
- **Evidence:** synthetic approval test log, no real effects.
- **Exit:** all adversarial approval tests deny/stop correctly; ChatGPT QA signs.
- **Rollback:** disable action path; READ-only demo unaffected.
- **Cost:** zero.
- **Dependency:** Phase 3.

### Phase 5 — G6 Android operator slice (1 Nov; META-P5-01 … META-P5-03)
- **Objective:** phone-friendly mission/status/STOP/evidence preview; one coherent vertical slice (request → result + STOP visible) PLUS operator-integrated end-to-end STOP/evidence proof on working Core↔Chromium + model (P5-03; mock UI alone is NOT sufficient for DEMO-READY). Voice input optional only if safe (never a credential). No public unauthenticated endpoint.
- **Prerequisites:** Phases 1–4; P5-03 additionally contingent on working Core↔Chromium + model path and owner review of networking.
- **Prompts:** META-P5-01 status/evidence/STOP view contract (mock data); META-P5-02 slice walkthrough against Phase 3–4 outputs; META-P5-03 operator-integrated proof: Android-visible end-to-end STOP + evidence view against real Core↔Chromium + model path (owner networking review required; BLOCKED until then).
- **Allowed files:** additive UI/preview module + tests; no backend authority changes.
- **Expected tests:** STOP reachable and effective; no personal data in views; cancellation isolates tasks.
- **Risk gate:** exposing secrets/cookies/personal data; UI claiming DONE without evidence.
- **Evidence:** screenshots of mock UI (sanitized), walkthrough log.
- **Exit:** slice demonstrable with mocks; no authority bypass.
- **Rollback:** drop UI module; demo falls back to CLI/log evidence.
- **Cost:** zero.
- **Dependency:** Phases 1–4.

### Phase 6 — G7 Gmail draft-only (optional, 2 Nov; META-P6-01) — SKIPPABLE
- **Objective:** only if the independent Gmail branch passes its own gates: draft/approval preview compatibility behind same Core authority, separate consent, durable outbox. Never SEND/READ live as MVP prerequisite.
- **Prerequisites:** Gmail branch independent pass + owner OAuth consent; Phases 1–5.
- **Prompt:** META-P6-01 compatibility preview design + skip-decision record.
- **Allowed files:** additive port module + tests; no Gmail code merged blindly (reviewed port/cherry-pick only).
- **Expected tests:** offline draft-preview; no token transfer; no send path.
- **Risk gate:** OAuth/token custody; scope creep into MVP.
- **Evidence:** SKIP or preview-approval record.
- **Exit:** explicit GO (preview) or SKIP, either acceptable.
- **Rollback:** SKIP; nothing merged.
- **Cost:** zero unless owner approves otherwise.
- **Dependency:** none for MVP (parallel track).

### Phase 7 — G8 demo proof + G9 submission (3–4 Nov; META-P7-01 … META-P7-03)
- **Objective:** clean-room reviewer run, reproducible setup, diagrams, demo capture, cost/provenance report; final regression, license/privacy checks, 2–3 min demo, submission package + owner-authorized submission.
- **Prerequisites:** Phases 1–5 (6 optional); all QA gates signed.
- **Prompts:** META-P7-01 clean-room run + TEST_MATRIX/EVIDENCE_INDEX; META-P7-02 demo script + capture + cost/provenance report; META-P7-03 submission package + SUBMISSION_CHECKLIST.
- **Allowed files:** `docs/hackathons/meta/*`, `reports/meta/*`, demo script; no source changes except reviewed fixes.
- **Expected tests:** full hermetic suite green; clean-room reproduction; privacy/license checklist.
- **Risk gate:** last-minute unverified claims; private data in captures; missed deadline buffer.
- **Evidence:** verified-run-manifest, submission receipt.
- **Exit:** G8 DEMO-READY then G9 SUBMITTED-RECEIPT by 4 Nov 21:00 ET.
- **Rollback:** submit narrower verified slice (critical path only).
- **Cost:** sunk Phase 2 spend only.
- **Dependency:** all prior.

## Critical path

Model plans (untrusted) → Core admission → separate Chromium public READ → provenance → Android-visible evidence/STOP. Gmail draft-only skippable. Demo readiness > feature count.

## Global rules

- One Muse Code session per prompt; small bounded tasks; work only on `AIOA-METAGuardiansSPARK` branch; no Nebius/Main merge; Gmail optional (never MVP-blocking).
- Owner approval required for: paid API probes, personal data, OAuth, external effects, URL allowlist, any live network. 20 EUR is the user's PERSONAL total available, not a spend approval; no unaudited charges.
- No automatic progression across phases. 'Continue' means: when ChatGPT reviews the previous phase PASS and explicitly starts the next prompt within this conversation — never autonomous background work. No live proof claimed done. Total: 7 phases, 21 prompts. Deadline stays 4 Nov 21:00 ET.
- Safeguards hold throughout: provider != authority, Non-Zero, STOP, ZERO_WRITE (except explicitly warranted paths post-G5), owner warrants for effects, approval receipts, bounded errors, no replay. Offline results labelled offline, live labelled live with SHA/timestamp/scope.
