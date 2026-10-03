# Nebius Personal AI Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one judge-readable Personal AI scenario that retrieves persistent private HAT context, uses Nebius/NVIDIA only as an advisory model, preserves Core and human authority, performs one typed maintenance effect through ServiceGuard, and proves restart-safe reconciliation and replay blocking.

**Architecture:** Extend the existing Prompt 01 provider, memory, ServiceGuard, and Operator Console paths rather than adding another runtime. A small Personal AI coordinator will project the existing components into an explicit state vocabulary and a redacted evidence record; the HTTPS transport remains below `CoreServiceGuard`, and the UI only drives prepare/approve/resume operations through local authenticated APIs.

**Tech Stack:** Python 3 standard library, existing AIOA runtime and file-backed test persistence, `unittest`, local HTTP fixtures, existing HTML/CSS/JavaScript Operator Console.

**Spec:** `/home/l/Downloads/AIOA_Nebius_Codex_Prompt_02_Personal_AI_Build.pdf`

## Global Constraints

- Work only on branch `nebius-personal-ai`; keep `main` and `origin/main` at `d26266e54ee940d7ada30aa02783dc697618a72c`.
- Provider output is always `ADVISORY_ONLY`; only independent Core verification and explicit human approval may authorize the typed effect.
- Preserve one scheduler, one memory engine, one authority path, and one effect executor; add no shell endpoint and no silent provider/model fallback.
- A transport timeout is `UNKNOWN` and must lead to `READ_RECEIPT` then `READ_STATE`, with no automatic effect retry.
- Never persist prompt/response content, private HAT text, API keys, auth tokens, or chain-of-thought in receipts, reports, logs, or UI status.
- Use exact model IDs from the verified live catalog; Lightning is the default, Super and Ultra remain policy-gated.
- Tests use loopback fixtures only; live Serverless deployment remains `BLOCKED_BY_CREDENTIALS` until the operator separately authorizes and supplies cloud credentials.
- Do not merge, rebase, reset, force-push, tag, publish, create recurring cost, or modify `main`.

## Review Focus

- A provider error containing response text, credentials, or nested metadata must yield only an allowlisted redacted diagnostic.
- An HTTPS endpoint with userinfo, query, fragment, non-default path tricks, loopback/private host, or non-HTTPS scheme must fail before transport.
- A restart after a lost effect acknowledgement must reconcile the durable target receipt and state without a second `APPLY_SET_MAINTENANCE`.
- Reusing one idempotency key with a different command digest, target, or scope must fail closed.
- Fixture evidence must never be projected as `LIVE`, and private memory content must remain collapsed/redacted in the default UI.

---

### Task 1: Strict live smoke with configurable bounded output and redacted diagnostics

**Files:**
- Modify: `scripts/nebius_live_probe.py`
- Modify: `tests/test_nebius_live_probe.py`

**Interfaces:**
- Consumes: `NebiusProvider.generate_exact()` and `ExactCallError` from Prompt 01.
- Produces: `run_probe(..., max_output_tokens: int = 256) -> dict` and CLI `--max-output-tokens`, bounded to `32..512`; failure receipts may contain only reason, finish reason, request ID, numeric usage, and latency.

- [ ] **Step 1: Add failing tests for the 256-token default, hard bounds, exact model identity, `finish_reason=stop`, truncated completion failure, and allowlisted/redacted error metadata.**
- [ ] **Step 2: Run `PYTHONPATH=runtime:. python3 -m unittest tests/test_nebius_live_probe.py -v` and confirm the new tests fail for missing behavior.**
- [ ] **Step 3: Add bounded output configuration and a recursive allowlist sanitizer without changing `decode_response` or treating `length` as success.**
- [ ] **Step 4: Run the live-probe unit test and `python3 -m py_compile scripts/nebius_live_probe.py tests/test_nebius_live_probe.py`; expect PASS.**
- [ ] **Step 5: Commit the offline probe repair.**

### Task 2: Narrow HTTPS serverless transport below ServiceGuard

**Files:**
- Create: `runtime/service_guard/https_transport.py`
- Modify: `runtime/service_guard/__init__.py`
- Modify: `.env.example`
- Modify: `deploy/nebius_serverless/README.md`
- Create: `tests/test_nebius_https_transport.py`

**Interfaces:**
- Consumes: `CloudEffectTargetClient(..., transport=...)` and its typed request schema.
- Produces: `NebiusHttpsEffectTransport.from_environment(environ=None)`, `invoke(request: dict) -> dict | None`, and `validate_serverless_endpoint(value: str) -> str`.

- [ ] **Step 1: Add failing loopback tests for typed POSTs, injected bearer auth, response bounds, no retries, timeout-to-`TargetUnknown`, and strict endpoint validation.**
- [ ] **Step 2: Run `PYTHONPATH=runtime:tests python3 -m unittest tests/test_nebius_https_transport.py -v`; confirm failure.**
- [ ] **Step 3: Implement the standard-library HTTPS adapter with environment-only endpoint/auth, one attempt per invocation, fixed JSON media type, bounded timeout, and no request/body logging.**
- [ ] **Step 4: Document `NEBIUS_SERVERLESS_ENDPOINT_URL` and the cloud-injected auth variable without example secret values; keep deployment status explicit.**
- [ ] **Step 5: Run the HTTPS and existing serverless transport suites; expect all tests PASS.**
- [ ] **Step 6: Commit the transport adapter.**

### Task 3: Restart-safe Personal AI scenario coordinator

**Files:**
- Create: `runtime/personal_ai_demo.py`
- Create: `tests/test_nebius_personal_ai.py`
- Reuse without authority changes: `runtime/memory_patch/lite.py`, `runtime/service_guard/service.py`, `runtime/providers/nebius_routing.py`

**Interfaces:**
- Consumes: existing HAT/private-memory retrieval, `ProviderPort`, CPL/Verified Delta output, `CoreServiceGuard.approve()`/`cycle()`, and durable operation records.
- Produces: `PersonalAIDemoService.prepare(request)`, `approve(proposal_id)`, `resume(operation_id)`, and `status(operation_id)` with states `ADVISORY`, `VERIFIED`, `ZERO_WRITE`, `APPROVAL_REQUIRED`, `APPROVED`, `EXECUTED`, `RECONCILED`, `REPLAY_BLOCKED`.

- [ ] **Step 1: Add failing integration tests that store a private maintenance-window constraint, close/recreate the runtime, retrieve only bounded context metadata, and prepare an exact proposal without dispatch.**
- [ ] **Step 2: Add failing tests proving provider output remains advisory, verification alone yields `VERIFIED` or `ZERO_WRITE`, and no effect occurs before exact one-use approval.**
- [ ] **Step 3: Add failing tests for approval → ServiceGuard → typed effect → receipt → independent readback, lost acknowledgement → restart → reconciliation, replay blocking, and conflicting key reuse.**
- [ ] **Step 4: Implement the coordinator as a thin composition over current ports; persist only hashes, IDs, bounded statuses, and timestamps.**
- [ ] **Step 5: Run `PYTHONPATH=runtime:tests python3 -m unittest tests/test_nebius_personal_ai.py -v`; expect PASS and exactly one effect in restart/replay cases.**
- [ ] **Step 6: Commit the vertical slice.**

### Task 4: Competition policy and truthful operator projection

**Files:**
- Modify: `runtime/providers/nebius_routing.py`
- Modify: `runtime/competition_view.py`
- Modify: `tests/test_nebius_routing.py`
- Modify: `tests/test_competition_view.py`

**Interfaces:**
- Consumes: verified catalog receipt, current price quote, budget reservation journal, and Personal AI status record.
- Produces: exact provider/model, `LIVE|FIXTURE`, estimated/actual usage, authority, memory/CPL/verification/approval/ServiceGuard/receipt/replay fields in a redacted read-only view.

- [ ] **Step 1: Add failing tests for exact catalog IDs, Lightning default, explicit Super role, operator-gated Ultra, reservation-before-transport, no fallback, and fixture/live truthfulness.**
- [ ] **Step 2: Add failing projection tests requiring every visible state and rejecting private text, unknown fields, false LIVE claims, and malformed hashes/counts.**
- [ ] **Step 3: Extend the existing router and projection minimally, preserving Prompt 01 policy defaults.**
- [ ] **Step 4: Run routing and competition-view suites; expect PASS.**
- [ ] **Step 5: Commit the policy/projection changes.**

### Task 5: Compact Operator Console mission panel and local API

**Files:**
- Modify: `runtime/webapp.py`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`
- Modify or create targeted tests under: `tests/test_webapp.py` and `tests/test_nebius_personal_ai.py`

**Interfaces:**
- Consumes: `PersonalAIDemoService` and the redacted competition projection.
- Produces: authenticated local endpoints for prepare/status/approve/resume and a compact panel that never auto-approves.

- [ ] **Step 1: Add failing API tests for session-token and explicit operator-intent enforcement, strict request fields, prepare-without-effect, exact approval binding, and sanitized status.**
- [ ] **Step 2: Add the four bounded routes to the existing server and preserve all current Assistant, Evidence Review, CPL, and Non-Zero routes.**
- [ ] **Step 3: Add a compact panel showing provider/model, LIVE/FIXTURE, hidden/retrieved HAT state, CPL, verification/`ZERO_WRITE`, approval, ServiceGuard, receipt hash, reconciliation, and replay result.**
- [ ] **Step 4: Make the deterministic scenario button stop at `APPROVAL_REQUIRED`; require a separate explicit approval control.**
- [ ] **Step 5: Run API tests and static UI checks; expect no chain-of-thought/private transcript and no false LIVE claim.**
- [ ] **Step 6: Commit the UI/API slice.**

### Task 6: One authorized paid Lightning smoke

**Files:**
- Create at runtime only: `evidence/cloud_activation/live_smoke_<UTC>.json` with mode `0600`
- Modify after result: `reports/personal_ai_vertical_slice_2026-10-03.md`

**Interfaces:**
- Consumes: exact `nvidia/Nemotron-3_5-Lightning` ID from the existing PASS catalog receipt and host-supplied `NEBIUS_API_KEY`.
- Produces: one non-overwriting redacted receipt with PASS or one preserved FAIL; never retries.

- [ ] **Step 1: Confirm offline probe tests pass, the exact live catalog model is present, the secret variable exists without printing it, and no later successful Prompt 02 receipt already exists.**
- [ ] **Step 2: Run exactly one cost-authorized probe with `--max-output-tokens 256`, bounded timeout, exact Lightning ID, and a new receipt path.**
- [ ] **Step 3: Record PASS only when status, provider, no-fallback, exact model identity, `finish_reason=stop`, and live validation all pass; otherwise preserve the sanitized FAIL and stop the paid path.**

### Task 7: Evidence, runbook, regression, and commits

**Files:**
- Create: `docs/nebius_personal_ai_demo_runbook.md`
- Create: `reports/personal_ai_vertical_slice_2026-10-03.md`
- Create: `evidence/personal_ai_vertical_slice/manifest_<UTC>.json`

**Interfaces:**
- Consumes: committed branch state, live-smoke receipt, demo evidence, and exact test outputs.
- Produces: reproducible start/run/restart instructions and redacted evidence manifest with hashes/counts.

- [ ] **Step 1: Run targeted new tests, then existing Nebius routing/live/serverless, LITE, ServiceGuard, NV10 recovery, and private-chat regression sets; record exact PASS/FAIL counts and timeouts truthfully.**
- [ ] **Step 2: Run `git diff --check`, `python3 -m py_compile` for every changed Python file, JSON validation, and a changed-file secret scan that reports paths/categories without printing candidate values.**
- [ ] **Step 3: Write the runbook with exact fixture demo, restart, live-provider, and blocked Serverless deployment commands.**
- [ ] **Step 4: Write the report and non-overwriting manifest with branch SHA, model identity, LIVE/FIXTURE labels, receipt hashes, state sequence, test counts, blockers, and `MAIN TOUCHED = NO`.**
- [ ] **Step 5: Commit evidence/documentation, confirm clean worktree, confirm `main` and `origin/main` remain unchanged, and do not push or deploy.**
