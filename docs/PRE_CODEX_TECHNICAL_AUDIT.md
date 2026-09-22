# AIOA spArkHAT — PRE_CODEX Technical Audit

Date: 2026-09-22

Branch: `codex/nvidia-final-week-20260921`

Frozen certification baseline: `ad4a425714a764f61f5ff22f2cc59f18abc36984`

Audit scope: authority, replay/idempotency, restart/recovery, provider UNKNOWN, evidence integrity, privacy/isolation, dead-code/TODO surfaces, and submission-facing residual risk.

## Verdict

**PRE_CODEX_READY — GO with preserved external/non-production gates.**

No P0 authority, replay, isolation, evidence-integrity or restart/recovery defect was found in the audited competition path. One P1 test-hygiene defect was found and fixed: pytest could collect the imported `test_live_gate` helper as a test when `tests/test_nv02_lite.py` was selected directly. Commit `b1c9989` aliases the helper to a non-test name; direct NV02 selection now passes 41/41.

Architecture should remain frozen. The next Codex sprint should consume the existing backlog rather than create another Core, scheduler, executor, memory engine or authority path.

## Audit evidence

| Surface | Evidence inspected | Result |
| --- | --- | --- |
| Core authority | `runtime/core_admission.py`, Service Guard capability checks, mission advisory contracts | PASS |
| Provider authority | `runtime/providers/nvidia.py`, LITE/CPL contracts, competition evaluation | PASS — provider output remains advisory/data only |
| Effect authority | `runtime/service_guard/service.py`, `target.py`, competition evaluation | PASS — Service Guard remains sole competition effect executor |
| Replay/idempotency | `lite_journal.py`, Service Guard `execute_once`, target idempotency receipt, NV10 tests | PASS |
| Restart/recovery | RESERVED→UNKNOWN journal recovery, receipt reconciliation, verified replay, NV10 recovery tests | PASS |
| Provider UNKNOWN | NVIDIA failure taxonomy/quarantine and no blind equivalent retry | PASS |
| Evidence projection | `competition_view.py`, `provider_availability.py`, reviewer preflight | PASS within local-operator threat model |
| Privacy/isolation | owner/tenant/space checks, Memory Patch contracts, isolation tests | PASS |
| Dead code markers | exact code search for TODO/FIXME/HACK under runtime/scripts/web/tests | NONE FOUND |

## Findings

| ID | Severity | File | Problem | Evidence | Recommended owner | Test |
| --- | --- | --- | --- | --- | --- | --- |
| TCA-001 | P1 | `runtime/main.py`; `runtime/tools/executor.py`; `runtime/nonzero_cloudops/**`; `runtime/service_guard/**` | The repository still contains three effect-capable mechanisms: legacy `ExecutionEngine`, Non-Zero `PortableExecutor`, and Service Guard. The NVIDIA competition path currently invokes only Service Guard, so this is an architecture/maintenance ambiguity rather than a demonstrated authority bypass. | Static import/use scan; competition projection reports `competition_effect_executor=ServiceGuard` and `nonzero_executor_invoked=false`. | CODEX_P1 | `test_executor_containment.py`; `test_nv09_service_guard.py`; `test_nonzero_core_authority.py`; `test_nvidia_reviewer_preflight.py` |
| TCA-002 | P1 | `runtime/main.py` | The legacy runtime coordinator remains broad: provider routing, prompt assembly, memory, browser/filesystem/shell dispatch and multiple historical orchestration paths are still reachable through the general runtime. They are outside the bounded NVIDIA competition vertical slice but increase stale-entrypoint and reviewer-confusion risk. | Current source plus prior forensic topology; competition demo does not route its effect through the legacy executor. | CODEX_P1 | `test_runtime_router_contract_guard.py`; `test_executor_containment.py`; `test_memory_layer_isolation_smoke.py` |
| TCA-003 | P1 | `scripts/nvidia_competition_demo.py` | The deterministic reviewer demo imports `nv05_demo` and `nv09_support` from `tests/`. This is reproducible in a source checkout but couples the reviewer path to test-package layout and should be exercised explicitly in the fresh-clone phase. | Direct source inspection; current reviewer preflight intentionally inserts the repository/tests paths. | CHATGPT_SAFE_FIX | `test_nvidia_competition_demo.py`; `test_nvidia_reviewer_preflight.py` |
| TCA-004 | P2 | `runtime/**`; `scripts/**` | Static scan found 74 broad `Exception`/`BaseException` handlers. Critical provider, scheduler, Service Guard and CPL samples inspected here fail closed to `UNKNOWN`, `BLOCKED`, typed unavailability, or advisory no-op; nevertheless the breadth can hide future programming defects. | AST scan over 210 Python files; no TODO/FIXME/XXX/HACK markers found. | POST_SUBMISSION | provider safety recert; NV09/NV10 guard/recovery; CPL service/web suites |
| TCA-005 | P2 | `runtime/tools/memory.py` | `MemoryStore` is still a transitional monolith combining L0 continuity, L1 history, L2 reasoning and human-readable vault projection. The previously unsafe action-result→evidence flow is fixed, but the mixed class remains a future regression surface. | `_record_execution()` now writes replay-only history and never evidence; evidence writes require explicit kind/source/fingerprint. | POST_SUBMISSION | `test_executor_containment.py`; `test_evidence_boundary.py`; `test_evidence_write_contract.py` |

## Finalization validation

Fresh deterministic reviewer preflight was rerun after the audit review and returned `PASS`.

- artifact: `/tmp/aioa-nvidia-review-preflight-m2l65129/AIOA_NVIDIA_COMPETITION_DEMO.json`
- SHA-256: `da04b0850c1ef24632682daf8db5a6fdf89e608b36a6b34039785ed5f167f899`
- stage count: `14`
- duplicate effects: `0`
- restart/replay dispatches: `0`
- effect executor: `ServiceGuard`
- provider mode: `TEST_FIXTURE`
- memory mode/backend: `TEST_FIXTURE` / `repository-durable-test`
- DVM/pheromone mode: `SHADOW`
- live NVIDIA/Cockroach/OpenRouter/AWS validated by this run: `false`

The system interpreter on this host does not carry pytest, so this documentation-only audit finalization did not manufacture a new full-suite number. The most recent canonical repository regression remains the already-recorded `1017/1017 PASS` with four expected optional UI skips; the fresh reviewer preflight above is the targeted acceptance gate for this audit batch.

## Submission-facing residual gates

- Keep OpenRouter LIVE blocked until the operator installs `OPENROUTER_API_KEY` and explicitly authorizes policy/budget.
- Keep live AWS disabled/un-certified; Non-Zero remains contract/readiness alignment and must not become a second competition executor.
- Keep DVM/pheromone and compact-index promotion in `SHADOW`.
- Keep deterministic provider/memory fallback labels truthful; do not present fixture evidence as LIVE.
- Keep the historical contiguous-24-hour claim false; submission wording may use only `SEGMENTED_ENDURANCE_PASS` for the accepted 3×8 h evidence.

## Hybrid-core / Epistemic Control decision

**NO-GO for dual authority. GO for one authoritative Core plus advisory/shadow epistemic control.**

The current evidence does not justify a second Core, scheduler, executor or authority plane. CPL, Knowledge HAT, Personal Delta, MemoryDynamics/DVM/pheromones and Non-Zero remain useful only when they feed verified/advisory information into the existing Core-governed path. Service Guard remains the sole competition effect executor.

## PRE_CODEX handoff decision

`PRE_CODEX_READY` is accepted for the current branch provided Codex treats TCA-001 through TCA-003 as bounded cleanup/reviewer tasks rather than architecture redesign. TCA-004 and TCA-005 are post-submission maintenance unless a focused regression exposes an actual competition-path failure.

Next execution phase: adversarial/failure regression and only small reversible fixes with direct regression evidence. No new runtime architecture is authorized by this audit.

## Current-state audit matrix

| Area | Current result | Evidence / limitation |
| --- | --- | --- |
| Duplicate authority paths | PASS with residual P1 ambiguity | Competition authority remains Core/Human/Service Guard. Legacy runtime and Non-Zero retain separate effect-capable code but are not on the competition effect path. |
| Multiple schedulers | PASS | LITE has one `AgentRuntime`-owned `LiteScheduler`; duplicate ownership of the same watch is rejected and the shared mutex serializes evaluation. |
| Multiple effect executors | PARTIAL | Multiple executor implementations exist in the repository, but reviewer/competition evaluation binds the competition effect to Service Guard and records Non-Zero as contract-alignment only. See TCA-001. |
| Unused adapters / stale entrypoints | PARTIAL | Historical/legacy general runtime paths remain. No removal is justified before submission because grant history and non-competition use must be preserved. See TCA-002. |
| TODO / FIXME / XXX / HACK | PASS | Exact static scan over runtime/scripts/tests found none. |
| Broad exception handling | PARTIAL | 74 broad handlers found by AST scan; sampled authority-sensitive paths fail closed. See TCA-004. |
| Silent fallback | PASS on competition path | NVIDIA product port has no model/provider fallback; missing live permit/key is typed blocked/unavailable. Memory fallback is explicitly labelled TEST_FIXTURE in reviewer surfaces. |
| Unsafe retry / ambiguous provider outcome | PASS | Outcome-unknown errors settle `UNKNOWN`; LITE does not retry UNKNOWN. Provider quarantine and manual replay contracts preserve prior UNKNOWN. |
| Replay / idempotency | PASS | Durable intent, `execute_once`, target receipt reconciliation and verified replay prevent a second competition effect. |
| Stale/revoked approval | PASS | Scope, policy digest, target revision/effect count and expiry are rechecked at effect boundary; revocation wins. |
| Nonce / approval reuse | PASS | CPL, Memory Patch and Non-Zero tests reject stale/reused challenges; Service Guard consent is immutable/single-bound. |
| Restart recovery | PASS | Restart requires reconciliation/replay barriers; verified Service Guard effect replays without redispatch. |
| Persistence / transaction boundaries | PASS in audited paths | External effect is outside retryable DB transaction; durable intent precedes dispatch; receipt is stored before independent verification. |
| Partial writes / lost ACK | PASS | Dedicated NV09/NV10 and Non-Zero tests cover crash/lost ACK/checkpoint failure and reconcile without blind second effect. |
| Corrupted / missing / symlink evidence | PASS | Reviewer/provider/CPL/live-gate tests reject malformed, missing, changed and symlink evidence. |
| Tenant / owner isolation | PASS | NV07/NV10/Memory Patch/Non-Zero suites contain cross-owner and cross-tenant denial/reconstruction tests. |
| Secrets exposure | PASS for tracked tree scan | Token-pattern scan found five OpenAI-like strings; inspection confirms they are explicit synthetic redaction fixtures/tests. No NVIDIA/Google/AWS credential-like tracked match was found. |
| Model / critic authority leaks | PASS | Model proposals and CPL critics are advisory; schema/authority injection cannot grant approval or effect authority. |
| Memory authority leak | PASS on current bounded path | Memory/model hints cannot become evidence/approval; poisoned/prompt-injected memory remains inert. Transitional MemoryStore structure remains P2 debt. |
| DVM / pheromone authority leak | PASS | Competition mode is `SHADOW`; high tau/score cannot revive revoked or stale authority; non-SHADOW demo evidence is rejected. |

## Verification performed in this audit

Static inspection covered 210 Python files under `runtime/` and `scripts/`, plus the targeted security/recovery tests used to validate the findings above. The tracked-tree credential scan reported only deliberate fake `sk-...` values in CPL redaction fixtures/tests; raw candidate values were not copied into this report.

Targeted audit regression command used the established integration interpreter with `PYTHONPATH=runtime:tests` and exercised executor containment, evidence boundaries, NV07 isolation, NV09/NV10 guard/recovery, provider safety/availability, competition projection, Non-Zero Core authority, CPL service and CPL web contracts.

Result: **216/216 PASS** in 208.55 seconds.

A full repository regression is required after this audit batch before closure of Phase 3; record its exact result below rather than inheriting the earlier 1017/1017 result.

## Preserved non-claims and gates

- `SEGMENTED_ENDURANCE_PASS` means accepted `3 × 8 h` segmented evidence only; it is not `24H_PASS_CLOSED`.
- Historical provider `UNKNOWN` records remain evidence and are not rewritten by later success.
- DVM/pheromone/index behavior remains `SHADOW` for competition/product claims.
- OpenRouter LIVE remains blocked until an operator supplies the key and explicitly authorizes the bounded live acceptance run.
- Live AWS Non-Zero remains disabled/not certified; the competition path does not invoke its executor.
- The deterministic reviewer path is `TEST_FIXTURE` unless an artifact explicitly labels a live backend.
- No audit result authorizes push, merge to `main`, deploy, publication, submission or repository visibility changes.

## Phase-3 closure rule

Phase 3 may close when the current audit document is committed after `git diff --check`, the 216-test targeted gate remains green, the full repository regression is green under the established integration environment, and the frozen certification worktree is still clean at `ad4a425714a764f61f5ff22f2cc59f18abc36984`.
