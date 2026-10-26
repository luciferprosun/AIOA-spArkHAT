# MUSE Prompt Book — META Hackathon 2026 (21 prompts, copy-ready)

**Branch:** `meta` only · **SHA:** `c7c73e929d717181a6405936285c5d3e8631ba86` · **Deadline:** 4 Nov 21:00 ET · **Total:** 21 prompts (P1×5, P2×3, P3×3, P4×3, P5×3, P6×1, P7×3)
**Standing rule for every prompt:** Muse Code implements one prompt per session; ChatGPT independently verifies; owner is sole authority for spend, data, effects. Work only on `meta` branch; no Nebius/Main merge; Gmail optional. URL allowlist is OWNER_APPROVAL_REQUIRED before any live network; development uses synthetic fixtures (owner may choose a public documentation test site later). 20 EUR is the user's PERSONAL total available, not a spend approval — no unaudited charges. No automatic progression across phases: 'continue' means when ChatGPT reviews the previous phase PASS and explicitly starts the next prompt within this conversation, never autonomous background work.
**Future prompts listed here are NOT authorized for execution now. Recommended next task: META-P1-01.**
**Audit factual status:** offline contracts G1 60/60 PASS on independent hermetic re-run (includes Muse plan contracts). Muse Code coding session successfully authenticated to Meta Model API (CLI codegen), but end-product AIOA Runtime G3 has NOT made its own real Meta probe. Do not imply live Chromium or end-product live Meta. CLI codegen ≠ product model integration.

## Global handoff format (every prompt returns exactly this)

```
phase_status: PASS/PARTIAL/FAIL/BLOCKED
task_id: <PROMPT ID>
source_sha: <verified HEAD>
changed_files: <exact paths, additive only>
executed_tests: <commands + OFFLINE/LIVE label>
pass_fail_counts: <n/n>
unresolved_risks: <list>
next_gate: <gate + ChatGPT QA + owner decision>
```

## META-P1-01 — Audit existing browser surface (Phase 1, offline READ)

Copy-ready prompt: "You are Muse Code on branch `meta` (SHA above). READ-ONLY audit, no source edits. Allowed paths: READ `runtime/tools/browser_tools.py`, `runtime/mcp_bridge/*`, `runtime/core_admission.py`, `runtime/mission/warrant.py`. Do-not-touch: everything else, no installs, no network, no browser launch."
Steps: (1) read listed files; (2) tabulate callable surface + risk per callable; (3) state what the new adapter must NOT reuse; (4) propose adapter boundary. PASS: audit table + boundary proposal complete, SHAs match. Offline tests: none (audit). Live tests: none. STOP: any file missing/diverged → BLOCKED, report, await owner/ChatGPT. Handoff: global format fields.

## META-P1-02 — Chromium adapter skeleton + admission wiring (Phase 1, offline)

Copy-ready prompt: "On `meta`, create additive adapter skeleton only. Allowed: new `runtime/browser_agent/*` + `tests/test_meta_p1_*.py` (design TBD exact test filename within that glob). Do-not-touch: `runtime/core_admission.py`, Core, MCP, warrant (import only), no live run, no network."
Steps: (1) typed task/observation dataclasses reusing `meta_hackathon/contracts.py`; (2) admission-required gate (`dispatch_allowed=False`); (3) stub READ dispatch denying all effects; (4) hermetic tests green. PASS: skeleton + gate + 4-step tests pass offline. Offline tests: `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_p1_*.py' -v`. Live: none. STOP: any WRITE/EXEC path, personal profile, Core edit → STOP + revert. Handoff: global format.

## META-P1-03 — Offline navigation/timeout/STOP/cancel tests (Phase 1, offline)

Copy-ready prompt: "On `meta`, extend the P1-02 additive module only. Allowed: `runtime/browser_agent/*` + `tests/test_meta_p1_*.py`. Do-not-touch: Core/MCP/warrant, no live pages."
Steps: (1) synthetic fixtures success/timeout/redirect; (2) STOP/cancel semantics; (3) per-task isolation (no cookie/evidence leak); (4) full offline suite green. PASS: all fixtures pass, STOP effective, isolation proven. Offline tests: hermetic unittest glob above. Live: none. STOP: cross-task leakage or STOP failure → FAIL. Handoff: global format.

## META-P1-04 — Network threat review (Phase 1, offline)

Copy-ready prompt: "On `meta`, report + fixtures only. Allowed: report text + additive test fixtures under `tests/test_meta_p1_*.py`. Do-not-touch: live config, no live run."
Steps: (1) enumerate redirect/rebind/subresource/download vectors; (2) specify enforcement points outside Python (OS egress isolation); (3) define LIVE-readiness checklist; (4) mark G2-live BLOCKED until checklist met. PASS: checklist written, Python-checks-insufficient documented. Offline: synthetic redirect/encoded-IP fixtures → DENY. Live: none. STOP: any claim Python checks authorize live Chromium → STOP + correct. Handoff: global format.

## META-P1-05 — One instrumented LIVE public-doc Chromium READ (Phase 1, gated LIVE, final)

Copy-ready prompt: "On `meta`, BLOCKED until BOTH owner URL-allowlist approval AND ChatGPT QA live-gate sign-off. Do NOT auto-run. Installing Playwright is NOT authorized by this plan — request permission first. Allowed (once unblocked): additive live-read script + test under `runtime/browser_agent/*`, `tests/test_meta_p1_*.py`. Do-not-touch: Core, credentials, personal Chrome profile."
Steps: (1) verify both gates recorded; (2) isolated ephemeral browser + OS network containment, allowlisted public-doc URL only; (3) single READ with timeout/cancel/STOP instrumented; (4) provenance observation + redacted log. PASS: one allowlisted READ observed, contained, logged. Offline: pre-flight fixtures green. Live: exactly one approved READ. STOP: missing gate, redirect off-allowlist, containment gap → abort + BLOCKED. Handoff: global format + URL, SHA, timestamp, scope."

## META-P2-01 — Meta provider path design (Phase 2, offline)

Copy-ready prompt: "On `meta`, design only. Allowed: additive planner/provider module + `tests/test_meta_p2_*.py` (design TBD). Do-not-touch: `runtime/providers/openai_compatible.py` (evaluate as base, import/reuse, no edit), Core, no live call."
Steps: (1) evaluate provider base; (2) additive planner treating model output as untrusted proposal; (3) cap + redaction design; (4) mocked-transport tests. PASS: design + mocked tests green. Offline: hermetic only. Live: none. STOP: live call attempt or key use → STOP. Handoff: global format.

## META-P2-02 — Spend-cap/receipt harness (Phase 2, offline)

Copy-ready prompt: "On `meta`, harness only. Allowed: additive module + `tests/test_meta_p2_*.py`. Do-not-touch: live keys, network."
Steps: (1) cap enforcement; (2) key redaction in logs/evidence; (3) malformed-response handling; (4) no-substitution-on-failure. PASS: all harness tests green, no secret in output. Offline only. STOP: secret leakage → FAIL. Handoff: global format.

## META-P2-03 — Single owner-approved live probe (Phase 2, gated LIVE)

Copy-ready prompt: "BLOCKED without explicit owner warrant (model, budget, scope). Allowed once approved: single minimal probe via additive module. Do-not-touch: anything beyond approved scope."
Steps: (1) verify warrant; (2) one minimal call; (3) redacted receipt (model/version/timestamp/SHA/spend); (4) `provider != authority` preserved. PASS: one verified receipt. Offline: harness green first. Live: one call only. STOP: no warrant → BLOCKED; substitution on failure → FAIL. Handoff: global format + receipt fields.

## META-P3-01 — Correlation + provenance (Phase 3, offline)

Copy-ready prompt: "On `meta`. Allowed: additive evidence module + `tests/test_meta_p3_*.py` (design TBD). Do-not-touch: Core/MCP/warrant (import only)."
Steps: (1) correlation IDs task→observation→receipt; (2) `BrowserObservationV1` provenance fields; (3) UNVERIFIED-until-corroborated tagging; (4) tests green. PASS: correlated offline run green. Live: none. STOP: certifying without evidence → FAIL. Handoff: global format.

## META-P3-02 — Injection/tamper tests (Phase 3, offline)

Copy-ready prompt: "On `meta`. Allowed: same additive module + tests. Do-not-touch: live pages."
Steps: (1) hostile page-instruction fixtures as content-only; (2) mismatch screenshot-vs-claim → UNKNOWN; (3) tamper → DENY/flag; (4) suite green. PASS: fail-closed proven. STOP: trusted-hostile-content → FAIL. Handoff: global format.

## META-P3-03 — Evidence index + manifest draft (Phase 3, offline)

Copy-ready prompt: "On `meta`. Allowed: `docs/hackathons/meta/*`, `reports/meta/*` + supporting tests. Do-not-touch: source authority."
Steps: (1) evidence index; (2) verified-run manifest draft; (3) SHA/timestamp/scope labels. PASS: index + draft complete. STOP: live claims from offline → correct. Handoff: global format.

## META-P4-01 — Risk classification (Phase 4, offline)

Copy-ready prompt: "On `meta`. Allowed: additive approval module + `tests/test_meta_p4_*.py`. Do-not-touch: warrant issuance."
Steps: (1) classify click/submit/type/download/send as protected; (2) READ vs WRITE boundary; (3) synthetic scenarios. PASS: classification + tests green. STOP: model-minted approvals → FAIL. Handoff: global format.

## META-P4-02 — Warrant binding tests (Phase 4, offline)

Copy-ready prompt: "On `meta`. Allowed: same module + tests; READ-only reuse of `runtime/mission/warrant.py` ledger. Do-not-touch: issuance logic."
Steps: (1) bind payload hash/nonce/scope/expiry; (2) absent/expired/forged/wrong-target/consumed → DENY; (3) replay → DENY. PASS: all adversarial denials. STOP: replay accepted → FAIL. Handoff: global format.

## META-P4-03 — STOP/preview/reconcile (Phase 4, offline)

Copy-ready prompt: "On `meta`. Allowed: same module + tests. Do-not-touch: live effects."
Steps: (1) STOP/preview flow; (2) lost-ack → UNKNOWN + reconcile; (3) no auto-replay of writes. PASS: reconcile correct, no replay. STOP: auto-replay → FAIL. Handoff: global format.

## META-P5-01 — Operator view contract, mock (Phase 5, offline)

Copy-ready prompt: "On `meta`. Allowed: additive UI/preview module + `tests/test_meta_p5_*.py` (design TBD). Do-not-touch: backend authority, no public endpoint."
Steps: (1) status/evidence/STOP view contract on mock data; (2) no personal data; (3) cancellation isolation. PASS: contract + tests green. STOP: secret/personal data in view → FAIL. Handoff: global format.

## META-P5-02 — Vertical slice walkthrough, mocked (Phase 5, offline)

Copy-ready prompt: "On `meta`. Allowed: same UI module. Do-not-touch: authority."
Steps: (1) walkthrough request→result + STOP visible on mocked Phase 3–4 outputs; (2) sanitized screenshots; (3) log. PASS: slice demonstrable with mocks (NOT demo-ready alone). STOP: claiming DONE without evidence → FAIL. Handoff: global format.

## META-P5-03 — Operator-integrated proof, live path (Phase 5, gated, final)

Copy-ready prompt: "Contingent on working Core↔Chromium + model AND owner review of networking; BLOCKED until then. No public unauthenticated endpoint. Allowed once unblocked: additive integration test + view wiring. Do-not-touch: auth surfaces, open endpoints."
Steps: (1) verify Core↔Chromium + model path works; (2) owner networking review recorded; (3) Android-visible end-to-end STOP + evidence view against real path; (4) authenticated-operator proof log. PASS: STOP effective end-to-end on real path. Offline: mocks green first. Live: only via approved path. STOP: missing review or open endpoint → BLOCKED. Handoff: global format."

## META-P6-01 — Gmail draft-only GO/SKIP (Phase 6, optional)

Copy-ready prompt: "On `meta`. Allowed: additive port module + `tests/test_meta_p6_*.py`. Do-not-touch: Gmail branch code (reviewed port only), no token transfer."
Steps: (1) independent Gmail branch gates check; (2) draft/approval preview compatibility; (3) explicit GO (preview) or SKIP record — either acceptable, never MVP-blocking. PASS: decision recorded offline. STOP: SEND/READ live or token move → STOP. Handoff: global format.

## META-P7-01 — Clean-room run + matrices (Phase 7, offline)

Copy-ready prompt: "On `meta`. Allowed: `docs/hackathons/meta/*`, `reports/meta/*`. Do-not-touch: source except reviewed fixes."
Steps: (1) clean-room reproduction; (2) TEST_MATRIX/EVIDENCE_INDEX; (3) full hermetic suite green. PASS: reproduction matches. STOP: unverified claims → correct. Handoff: global format.

## META-P7-02 — Demo script + capture + cost/provenance (Phase 7, offline)

Copy-ready prompt: "On `meta`. Allowed: demo script + reports. Do-not-touch: live beyond approved receipts."
Steps: (1) demo script; (2) sanitized capture; (3) cost/provenance report (20 EUR personal budget context, no unaudited charges). PASS: 2–3 min demo reproducible. STOP: private data in captures → FAIL. Handoff: global format.

## META-P7-03 — Submission package + checklist (Phase 7, offline)

Copy-ready prompt: "On `meta`. Allowed: submission package + SUBMISSION_CHECKLIST. Do-not-touch: submit button without owner authorization."
Steps: (1) package + checklist; (2) license/privacy checks; (3) owner-authorized submit only, receipt recorded. PASS: SUBMITTED-RECEIPT by 4 Nov 21:00 ET. STOP: no owner authorization → do not submit. Handoff: global format.

Total prompts: 5 (P1) + 3 (P2) + 3 (P3) + 3 (P4) + 3 (P5) + 1 (P6) + 3 (P7) = **21**.

## Browser/tool safety (all phases)

Use existing browser tooling only after independent audit. Allowlisted origins first (READ-only); URL allowlist OWNER_APPROVAL_REQUIRED; DNS rebinding; full redirect-chain re-checks; subresource/request blocking; screenshot/observation provenance; no replay of writes; per-task isolated profile/cookies; never live personal Chrome. Never present an offline fixture as a live browser result. No live proof claimed done.
