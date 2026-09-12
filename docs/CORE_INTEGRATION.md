# AIOA spArkHAT — Core integration and compatibility

AIOA spArkHAT continues the existing AOIA-Core repository and its history. The Critical Prompt Loop (CPL) is one module in the existing runtime, not a replacement for Core. The pre-integration main reference is `20a53ff8872e3aff4b872a021b5a46110549450a`; the selectively recovered CPL source is `5ec74f85256c260dadbc795143eb132b4119aab6`. Existing historical branches remain separate, not silently merged into main.

## Module map

```text
AIOA spArkHAT
├── runtime/main.py                  AgentRuntime and agent lifecycle
├── runtime/router/, adaptive_routing/  local routing and epistemic controls
├── runtime/providers/               shared ProviderManager and ordinary providers
│   └── exact.py                     bounded, one-attempt CPL HTTP transport
├── runtime/critical_loop/
│   ├── service.py                   primary draft → 3 critics → one primary revision
│   ├── review.py                    immutable snapshot, roles, strict report contracts
│   ├── policy.py                    explicit budgets and per-call/run limits
│   └── evidence.py                  view over the existing append-only provenance store
├── runtime/evidence_review/         unchanged deterministic dated-evidence module
├── runtime/nonzero_cloudops/        optional portable CloudOps adapter and exact frozen baseline
├── runtime/knowledge/, retrieval/   local corpus, isolation, refusal and provenance
├── runtime/tools/, memory/          controlled actions, evidence and operational state
├── runtime/orchestrator/            existing optional orchestration surfaces
├── runtime/commands/                existing CLI registry plus /cpl and operator-only /nonzero
├── runtime/webapp.py + web/         shared API and browser console
├── tui/                            preserved optional operator console
└── tests/, docs/, state/            tests, documentation and public-safe defaults
```

There is no second agent executor or separate CPL app. `AgentRuntime.critical_loop` owns the service; CLI and HTTP share it, along with the same provider manager and provenance implementation. The three sequential roles are exactly **Logic & Claims**, **Safety & Authority**, and **Evidence & Consistency**. A single final revision uses the original primary model only after every critic completes. A failed, cancelled or incomplete run never returns its draft as a completed final review.

The optional [Non-Zero CloudOps module](NONZERO_CORE_INTEGRATION.md) follows the
same service/CLI/API ownership pattern on its isolated integration branch. It
does not change CPL or grant model output execution authority. Its independent
native runtime is preserved as a vendored implementation, not duplicated by the
adapter; synthetic execution still requires its original human approval gate.

## Final Assistant routing

```text
AIOA spArkHAT
├── Core runtime / AgentRuntime
│   └── Assistant (web, interactive CLI, optional terminal adapter)
│       ├── Critical Prompt Loop [DEFAULT]
│       │   ├── Primary Draft
│       │   ├── Logic & Claims
│       │   ├── Safety & Authority
│       │   ├── Evidence & Consistency
│       │   ├── Original Primary Final Revision
│       │   └── Evidence Chain / Trace
│       └── Plain Chat [EXPLICIT BYPASS]
├── Dated Evidence Review [SEPARATE DETERMINISTIC MODULE]
└── Existing routing / providers / knowledge / tools / provenance
```

`AgentRuntime.assistant_request` is the shared default admission boundary. Normal prompts create immutable plans in the existing CPL service; no model call happens until explicit plan-hash/nonce approval. Evidence defaults to empty. Routing is generic: Python, arithmetic, creative writing, current-information and German-law questions use the same algorithm. The main web composer is used once, not copied into a specialist form. Only COMPLETED final revisions reach the normal answer surface. Draft/review/trace details remain inspectable. Explicit slash commands are preserved; the low-level `run_text_request` and existing action engine remain available to deliberately selected Plain Chat.

The focused generic regression matrix covers 12 unrelated prompts using production LIVE orchestration with a mocked generation transport boundary; real loopback HTTP tests cover transport and browser behavior separately. Neither is live-model certification. Mounted optional Textual/Playwright tests may remain separately listed environment skips; the dependency-free terminal admission adapter is in the required suite. Run full Core regression and report local results separately from GitHub Actions. If no suitable workflow is configured or run, `GITHUB_CI_STATUS=NOT_CONFIGURED_OR_NOT_RUN`; local PASS does not imply hosted CI PASS. This closure does not deploy, promote knowledge, train models, create repositories or start future modules.

## Preserved contracts

- Existing ordinary routing, provider selection/fallback, knowledge routing, memory hats, local utilities and operator approval remain in Core. CPL has its own strict **no fallback/no retry** policy on the same provider manager.
- `/review` and `/api/review` keep the deterministic dated-evidence contract; they are not renamed into CPL and never become model calls.
- CPL output is advisory data, never an executor command or automatic promotion to active knowledge. Hashes establish integrity/linkage relative to retained references, not factual truth, trusted time or model training.
- Core kill-switch/model-disable checks guard CPL planning, authorization and each generation phase. A model-disable flag permits only the explicitly selected local fixture, not live generation.
- Existing CLI commands, API routes, schemas, tools, public-safe defaults and historical documentation remain. New browser write endpoints use the session token obtained from `/api/session`; updated browser code supplies it.
- Imports, `AOIA_HOME`, existing environment-variable names and the legacy health field `system: "AOIA-Core"` remain compatibility identifiers. Human-facing product names use **AIOA spArkHAT**.
- Explicit missing or empty retrieval roots cannot fall back to a different corpus. Bundled default retrieval remains supported.

## Verification and live boundary

See [CPL launch and acceptance](CPL_LAUNCH.md) for CLI, web, installed entry points and the complete test commands. The safe fixture uses the actual HTTP adapter on isolated loopback. The live path uses the existing OpenRouter configuration and requires exact model identities, fresh operator-provided prices, positive session/run budgets and approval of an immutable plan. A missing key never turns a live run into a mock result.

Local verification does not certify real provider behavior, tokenization, billing or response quality. No live smoke test or deployment is required for repository publication. Keep secrets, state, browser profiles and private release reports outside the tracked source tree.

The legacy candidate-triage test now puts its temporary input in an isolated temporary directory instead of beside the tracked knowledge corpus. Its provenance assertions are unchanged. This permits running the whole suite with the source checkout read-only.
