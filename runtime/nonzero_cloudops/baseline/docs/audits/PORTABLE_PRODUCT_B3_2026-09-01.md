# AIOA PORTABLE PRODUCT — B3 JUDGE-FACING UX

## Identity

PROJECT=AIOA / AIOA-NonZero-CloudOps-Agent
REPO=/media/l/LSC_DATA/AWS_HACKATHON/AIOA-NonZero-CloudOps-Agent
BRANCH=codex/portable-p3-judge-ux
HEAD_BEFORE=d81e5cf925e540a7dbdbab1716fd6049244dd7b1
IMPLEMENTATION_COMMIT=1882089fbb41a3f7f3cbad821ed9d6d8c6c2e9a5
EVIDENCE_COMMIT=4e330f1cb3c38fed5e969761dd94af9e1f1c6d60
HEAD_AFTER=4e330f1cb3c38fed5e969761dd94af9e1f1c6d60
WORKTREE=CLEAN
RUN_DATE=2026-09-01
TIMEZONE=Europe/Berlin
AUDITED_AT=2026-09-01T08:35:23+02:00

`HEAD_AFTER` is the exact implementation/evidence head used for the final full regression, P0, P1,
clean-clone proof, package check, and portable demo. A documentation-only commit containing this
report and the roadmap status follows that audited head, avoiding a self-referential report SHA.

## Mission

B3_STATUS=PASS
PRODUCT_COMPLETE=PASS
JUDGE_PRIMARY_FLOW=PASS
JUDGE_FLOW_TARGET_LE_3_MIN=PASS_BY_REVIEWED_SELF_GUIDED_ONE_CLICK_FLOW
EXTERNAL_DEPLOYMENT_PERFORMED=NO
AWS_CALLS=0
AWS_MUTATIONS=0
REMOTE_PUSHES=0
EXTERNAL_UPLOADS=0

B3 adds one judge-facing experience on top of the existing Local-2 API. It does not redesign the
domain, create a second agent loop, or move authority into the browser. A judge can start either
seeded story without a terminal command, inspect evidence and an inert proposal, make an explicit
human decision, execute only the exact approved action, inspect independent verification, and read
the durable receipt/audit timeline.

The interface labels itself `DEMO SANDBOX`, `portable`, and `mock`, and repeatedly states that no
resource is live AWS. The one-command deterministic evidence demo remains:

```bash
.venv/bin/python scripts/run_portable_demo.py
```

The primary browser product entrypoint is:

```bash
.venv/bin/python scripts/run_local_hitl_api.py --open-browser
```

## Judge Experience

PRIMARY_FLOW=Observe -> Evidence -> Proposal -> Policy -> Human -> Execute -> Verify -> Receipt
APPROVE_SCENARIO=PASS SUCCESS_WITH_EVIDENCE
DENY_SCENARIO=PASS DENIED_BY_HUMAN
RECOVERY_SCENARIO=PASS RESTART_RECONCILED_ZERO_REEXECUTION
REPLAY_SCENARIO=PASS DUPLICATE_RESUME_ZERO_MUTATION_DELTA
STALE_TAB_SCENARIO=PASS BINDING_MISMATCH_FAIL_CLOSED
REFRESH_RESUME=PASS DURABLE_RUN_ID_RESTORATION
SLOW_DUPLICATE_CLICK_GUARD=PASS SINGLE_IN_FLIGHT_UI_ACTION
DESKTOP_LAYOUT=PASS 1440px reference capture
PHONE_LAYOUT=PASS 390px reference capture

The UI exposes target, operation, impact, required authority, evidence/proposal/request/decision/
receipt/verification hashes, before/after state, per-run mutation count, process sandbox mutation
count, provider calls, and external-network count. It renders only a sanitized projection: approval
nonce material, actor session identifiers, raw credentials, tracebacks, environment data, and
unbounded audit metadata are absent.

Human approval and protected execution remain separate durable transitions. There is no generic
`/execute`, `/mutate`, shell, URL, provider, or cloud-client endpoint. A proposal remains
non-authorizing, and the model never obtains mutation authority.

## Browser Session Boundary

SESSION_BOOTSTRAP=BEARER_IN_URL_FRAGMENT_ONLY
SESSION_STORAGE=HTTPONLY_SAMESITE_STRICT_LOOPBACK_COOKIE
BROWSER_WEB_STORAGE=NONE
STATE_CHANGING_COOKIE_REQUEST_GUARD=X-AIOA-Intent: judge-console-v1
AUTHORIZATION_HEADER_PRECEDENCE=YES
TOKEN_LOGGING=NO

The launcher never places the token in an HTTP request path or query. The page synchronously removes
the fragment and exchanges the exact bearer credential for a process-derived HttpOnly cookie.
Invalid Authorization headers cannot fall through to cookie authentication. Token rotation or
process configuration change invalidates the derived session.

## API Contract

- `GET /health` preserves the existing process-health response.
- `GET /ready` returns truthful portable/mock readiness with zero cloud prerequisites.
- `GET|POST|DELETE /api/session` provides the bounded browser bridge.
- Existing `/api/runs` and approval/decision/resume routes retain the application-service authority
  path and exact typed schemas.
- `GET /api/runs/{run_id}` returns a sanitized view plus a bounded, exact-run audit timeline.
- The HTTP server remains loopback-only and same-origin; no CORS allowance was added.

## Strands Truth

STRANDS_FRAMEWORK=1.53.0
ONE_PRIMARY_AGENT=YES
CANONICAL_TOOL_COUNT=5
PORTABLE_STRANDS_DEMO=PASS
UI_DIRECT_AGENT_TOOL_ACCESS=NO

The canonical portable demo invokes the actual five-tool `strands.Agent` and records that proof in
its evidence receipt. The interactive Local-1/2 browser path intentionally uses the existing
deterministic provider plus application-owned policy, persistence, approval, executor, verification,
and audit services. It does not claim live Strands model inference and cannot invoke a tool directly.

## Final Regression

BASELINE_B0_B2_TESTS=1318 passed / 1318 total / 0 failed / 0 skipped
TEST_TOTAL=1328
TEST_PASSED=1328
TEST_FAILED=0
TEST_SKIPPED=0
TEST_XFAILED=0
TEST_DURATION=854.86s
BASELINE_COMPARISON=+10 passing tests; no test removed, skipped, or converted to xfail
P0=PASS 15/15 gates, 136 proof tests, 0 skipped
P1=PASS 6/6 gates, 93 proof tests, 0 skipped
CLEAN_CLONE=PASS commit 4e330f1cb3c38fed5e969761dd94af9e1f1c6d60, 6/6 checks
LINT=PASS (`ruff check .`)
TYPECHECK=NOT_CONFIGURED (no mypy/pyright dependency or project configuration)
FORMAT_CHECK=NO_REPOSITORY_FORMATTER_CONFIG; `git diff --check` and Ruff PASS
PACKAGE_CHECK=PASS (`aioa_nonzero_cloudops_agent-0.2.0rc1-py3-none-any.whl`)
PACKAGE_SHA256=2dacff8830d07080df297c49190924b0a4aeabe609330704ad6173336008e46b
PIP_CHECK=PASS (no broken requirements)
GIT_DIFF_CHECK=PASS
JS_SYNTAX_CHECK=PASS (`node --check` on the embedded script)
SECRET_SCAN=PASS (353 files, 0 findings, no secret values emitted)
GENERATED_EVIDENCE_CHECK=PASS (28 claims, 0 live receipts)
PORTABLE_E2E=PASS

The first full post-change regression had 1327 passes and one expected evidence-manifest failure:
the changed Local API authority and proof blobs still pointed to the historical Local-First Phase 2
commit. No test was weakened. The precise `LOCAL2-LOOPBACK-API-01` claim was updated and anchored to
the immutable B3 implementation commit, after which the dedicated manifest suite passed 120/120 and
the full suite passed 1328/1328.

The first P1 run passed P1-01 through P1-05 but its clean-clone command returned a generic transient
`COMMAND_PROOF_EXIT_1`. Running the exact command with visible output passed all six clean-clone
checks at the audited commit. A complete P1 rerun then passed 6/6 with 93 proof cases and zero skips.

## Portable Demo Evidence

DEMO_STATUS=PASS
DEMO_RUNTIME_MODE=portable
DEMO_PROVIDER=mock
DEMO_STRANDS_AGENT=YES
DEMO_APPROVE=SUCCESS_WITH_EVIDENCE
DEMO_DENY=DENIED_BY_HUMAN
DEMO_RECOVERY=RECONCILED
DEMO_REPLAY_MUTATION_DELTA=0
DEMO_SANDBOX_MUTATIONS=1
DEMO_PROVIDER_NETWORK_CALLS=0
DEMO_EXTERNAL_NETWORK_CONNECTIONS=0
DEMO_AWS_CALLS=0
DEMO_AWS_MUTATIONS=0
DEMO_RECEIPT_SHA256=3440d2e0aab5427a456d9f2074d5557305017f1864559bb01cc322b48eb53bbd

## Screenshot Evidence

- `docs/assets/judge-ux-desktop-success.png` — 1440x2000 —
  `b292f7f165655e23d2a32fddf77c8dba7633315a7c2b7696d1ecd1bc7c5fc557`
- `docs/assets/judge-ux-desktop-denied.png` — 1440x1700 —
  `56d655de88396cd1000efec9c294191110013614d5753297fc3d6eed36753354`
- `docs/assets/judge-ux-mobile-success.png` — 390x1800 —
  `4d0382a686af3a778f3e586624d8694811ded8b7f95b13aec0cdb18ef6d5278d`

TOKEN_BYTES_IN_SCREENSHOTS=0
EXTERNAL_ASSETS=0
INLINE_CSP_HASHES=EXACT_SHA256

The captures were made locally against loopback with external hostname resolution mapped to a sink.
The application made zero provider/cloud network calls. Chrome attempted platform background IPv6
DNS connections that failed with `ENETUNREACH`; no successful external browser connection was
observed. This browser-process fact is separate from the application's zero-egress evidence.

## Architecture Audit

DUPLICATE_PROVIDER_ABSTRACTIONS=NONE
NEW_RUNTIME_DEPENDENCIES=0
DIRECT_MODEL_TO_MUTATION_AUTHORITY=NONE
DIRECT_UI_TO_MUTATION_AUTHORITY=NONE
GENERIC_EXECUTE_OR_MUTATE_ENDPOINT=NONE
APPROVAL_BYPASS=NONE
HASH_BINDING_BYPASS=NONE
REPLAY_IDEMPOTENCY_REGRESSION=NONE
RECOVERY_REGRESSION=NONE
SILENT_FAILURE_TO_SUCCESS=NONE
UNBOUNDED_RETRY=NONE
ARBITRARY_SHELL_OR_URL_TOOL=NONE
AWS_IMPORT_OR_CLIENT_ADDED=NONE
AWS_CREDENTIAL_DISCOVERY=NONE
SECRET_LOGGING=NONE
UNSAFE_HTML_INJECTION=NONE (`textContent`/DOM construction only)
EXTERNAL_FRONTEND_DEPENDENCY=NONE
HARD_CODED_MACHINE_PATH_IN_RUNTIME=NONE

Broad catches at the HTTP adapter boundary return stable redacted `401`/`500` failures and never
claim success or authorize execution. Audit reads are bounded, sorted, and restricted to the exact
run. Production read models validate portable/mock truth before emitting zero-AWS labels.

## Safety

HUMAN_AUTHORITY_PRESERVED=YES
APPROVAL_BINDING_PRESERVED=YES
REPLAY_PROTECTION_PRESERVED=YES
RECOVERY_PRESERVED=YES
NO_SILENT_FAILURES=YES
NO_SECRET_LEAKAGE=YES
NO_REAL_CLOUD_MUTATION=YES
ONE_AGENT_FIVE_TOOL_CAP_PRESERVED=YES
PROPOSAL_REMAINS_NON_AUTHORIZING=YES
INDEPENDENT_VERIFICATION_PRESERVED=YES
AUDIT_AND_DURABLE_ORDERING_PRESERVED=YES

## Commits

1. `1882089fbb41a3f7f3cbad821ed9d6d8c6c2e9a5` —
   `feat(product): add judge-facing portable experience`
2. `4e330f1cb3c38fed5e969761dd94af9e1f1c6d60` —
   `docs(evidence): reanchor judge experience proofs`

No commit was pushed.

## Files

FILES_ADDED=10 (including this audit report)
FILES_MODIFIED=20

Added:

- `docs/JUDGE_EXPERIENCE.md`
- `docs/assets/judge-ux-desktop-denied.png`
- `docs/assets/judge-ux-desktop-success.png`
- `docs/assets/judge-ux-mobile-success.png`
- `docs/audits/PORTABLE_PRODUCT_B3_2026-09-01.md`
- `src/aioa_cloudops_agent/local_api/judge_ui.py`
- `src/aioa_cloudops_agent/local_api/views.py`
- `tests/integration/test_portable_judge_experience.py`
- `tests/unit/test_judge_console_launcher.py`
- `tests/unit/test_judge_console_ui.py`

Modified:

- `README.md`, `docs/DECISIONS.md`, `docs/JUDGE_SANDBOX.md`, `docs/ROADMAP_STATUS.md`
- `docs/architecture/local-first-phase-2.md`, `docs/submission/demo-runbook.md`
- `docs/evidence/README.md`, `docs/evidence/reviewer-evidence-manifest.json`,
  `docs/evidence/reviewer-evidence-manifest.md`
- `scripts/build_reviewer_evidence_manifest.py`, `scripts/run_local_hitl_api.py`,
  `scripts/validate_reviewer_evidence_manifest.py`
- `src/aioa_cloudops_agent/local_api/__init__.py`,
  `src/aioa_cloudops_agent/local_api/application.py`,
  `src/aioa_cloudops_agent/local_api/auth.py`,
  `src/aioa_cloudops_agent/local_api/contracts.py`
- `src/aioa_cloudops_agent/persistence/local.py`,
  `src/aioa_cloudops_agent/persistence/memory.py`
- `tests/unit/test_local_hitl_api.py`, `tests/unit/test_reviewer_evidence_manifest.py`

## Known Limitations

1. The judge surface is loopback-only and designed for one local operator. Public-host rate limits,
   abuse controls, safe production origins, bounded concurrency/soak evidence, and an explicit
   provider egress allowlist belong to B4.
2. The deterministic API path completes in seconds, and the self-guided one-click desktop/mobile
   experience was reviewed against the three-minute flow. A separate formal novice usability study
   was not performed.
3. The interactive Local-1/2 path uses the deterministic provider and existing control-plane
   services directly. The canonical portable evidence command separately exercises the actual
   `strands.Agent`; the browser truthfully does not claim live Strands model inference.
4. The shipped non-AWS provider remains deterministic/mock. No paid key, networked real-model
   provider, or local LLM is required or configured.
5. No static type checker or repository-wide formatter is configured. Ruff, strict contracts,
   whitespace checks, 1328 tests, P0, and P1 pass.
6. The screenshots prove layout and final states, not public-host behavior. Their Chrome process had
   blocked background connection attempts as recorded above.
7. AWS, Bedrock, AgentCore, public deployment, and real infrastructure mutation remain intentionally
   optional and unexecuted.

## Next Recommended Macro-Step

B4 — RELIABILITY + SECURITY + EVIDENCE HARDENING. Add the bounded public-demo reliability,
security, observability, egress, concurrency/soak, and artifact evidence required by the roadmap.
Do not start deployment or B5 in this run.
