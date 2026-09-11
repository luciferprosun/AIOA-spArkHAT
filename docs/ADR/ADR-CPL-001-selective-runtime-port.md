# ADR CPL-001 — selective port into one runtime

Status: implemented on an integration branch; operator review required before merge/deployment.

Canonical product: **AIOA spArkHAT**, formerly AOIA-Core. Repository identity, not a mutable name, is the boundary: GitHub ID `1247349659`. A future remote rename to `AIOA-spArkHAT` is an independent administrative operation, not implied by local branding.

## Context and sources

Target base: `20a53ff8872e3aff4b872a021b5a46110549450a`. Historical source: `5ec74f85256c260dadbc795143eb132b4119aab6`, `apps/aoia_desktop_demo/critical_review.py`, `security/secret_redaction.py`, and the 70 core test scenarios in `test_critical_review.py` (53) plus `test_app_controller.py` (17). The existing MIT license and authorship are retained.

We port the pure review/snapshot/parser/prompt logic and redaction; we do not merge the historical branch. Tk, AppController, historical credential stores, HAT, Orchestra, recording/release applications and Memory Patch are not runtime/build dependencies.

## Decision

- `AgentRuntime.critical_loop` owns one `CriticalPromptLoopService`; CLI and `WebRuntimeService` delegate to it. The existing web server and Assistant gain a CPL mode; no second product or production server is created.
- The same `ProviderManager` exposes `generate_exact`. CPL uses the shared OpenRouter adapter with strict identity/bounds/no retries/no fallback, while the ordinary chat contract remains distinct. The explicit TEST transport uses a loopback fixture through that HTTP adapter.
- Shared `AppendOnlyProvenanceStore` is wrapped, not replaced. CPL logs live under the existing isolated `AOIA_HOME` runtime namespace, not the checkout or retrieval corpus.
- An exclusive state-root lease prevents another process from interrupting a live peer. Restart recovery marks unfinished persisted runs INTERRUPTED and never replays them. Existing completed runs remain readable.
- Installation adds a facade over the existing sibling-import runtime. Only this package's own directory is added for legacy imports; there is no search for another checkout. Web assets are installed under the environment prefix.

## Deliberate changes to historical behavior

- Exactly three canonical roles in order are mandatory. Historical duplicate roles and partial manual observer configurations do not authorize the new CPL.
- Sequential review stops on the first execution/transport/parse failure. Historical tests that continued later critics after a failure are replaced by fail-fast, stage-by-stage real HTTP tests.
- Provider-reported identity is mandatory and must exactly equal the captured requested model. Missing identity and routing aliases are not success.
- Critic output limit is reduced from 2400 to 512 tokens; draft/revision each have a 1024-token maximum. One successful run caps requested output at 3584 tokens.
- Unknown JSON report fields are rejected, not silently accepted. No model-supplied authority field can become an approval.
- Approved plans bind models, prompt/evidence, roles, limits, prices and budgets by hash plus one-use nonce and expiry. No automatic initiation on ordinary chat, model selection or error.
- The working draft is visible separately in the new UI, including the synthetic non-law scenario. Only COMPLETED can populate the final-answer surface.

## Retrieval regression

The facade passed an explicit project root, but low-level indexes and canonical source metadata still read globals. The missing-root test reproduced two unintended bundled results. Root-keyed dependency injection now returns zero results/refusal for missing or empty explicit resources and preserves default bundled behavior. Two pre-existing kernel tests supplied the repository directory rather than the runtime resource root; their fixture path is corrected, with all original assertions preserved. No expectation was weakened from zero to a hit.

## Consequences and limits

The pure legacy helper's independent `.run()` tests remain compatibility evidence only; production CPL exposes sequential 1+3+1. Actual transport/browser/installation evidence is recorded separately. The timestamp/hash chain is an integrity aid, not truth, authorship or trusted chronology. Live prices, billing and model semantics remain provider/operator-dependent; a local fixture cannot validate live behavior. No merge, deployment, knowledge promotion or model training is part of this implementation pass.
