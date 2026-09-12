# AIOA spArkHAT

AIOA spArkHAT (formerly AOIA-Core) is one local-first runtime for AI-assisted engineering and evidence-aware review. It keeps model output, tool results, evidence, provenance, contradictions, runtime state, and human authority separate instead of treating them as interchangeable forms of truth. This is the same repository and runtime, not a fork or an integration with a frozen hackathon application.

AOIA means **Adaptive Oceanic Intelligence Architecture**. In this repository the name describes a bounded routing and control architecture; it does not imply AGI, autonomous authority, or a self-modifying system.

## What is implemented

- deterministic local routing before provider use
- optional external model providers behind one `ProviderManager`
- structured shell, filesystem, browser, and project-inspection actions
- explicit operator approval for non-response actions
- local Linux/RHCSA retrieval with provenance and refusal boundaries
- append-only provenance support and contradiction tracking
- local CLI, web console, and optional Textual TUI over the same runtime
- deterministic dated-evidence review with source hashes and a mandatory human-review result
- advisory Critical Prompt Loop: draft → three sequentially informed critics → one revision by the original model

The dated-evidence capability is a module of AIOA spArkHAT, not a second application. Its CLI command, JSON endpoints, browser workbench, tests, and documentation all live in this repository and use the same launch surface.

## Critical Prompt Loop — integrated Core module

The CPL uses the same `AgentRuntime`, `ProviderManager`, command registry and web console. A successful run performs exactly five bounded generation requests. Critics are sequentially informed, **not independent consensus**. They cannot run tools, authorize changes, promote knowledge or train models.

```bash
./runtime/run.sh --cpl-fixture --command '/cpl fixture'
./runtime/run_web.sh --cpl-fixture
```

In the Assistant select **Critical Prompt Loop**, load the synthetic dated example, preview the immutable plan, then authorize the **TEST** plan. The fixture traverses the actual HTTP adapter on loopback; it is not a live model result. Ordinary cloud chat is disabled in this explicit fixture session. Without the fixture flag, CPL live execution is disabled unless an operator supplies an explicit cost policy, fresh model-specific price quotes, positive budgets and approval of the displayed plan. A missing key never causes synthetic fallback.

See the [CPL contract](docs/modules/CRITICAL_PROMPT_LOOP.md), [launch and acceptance guide](docs/CPL_LAUNCH.md), and [selective-port ADR](docs/ADR/ADR-CPL-001-selective-runtime-port.md). Existing `/review` and `/api/review` remain deterministic and separate. No paid live smoke test is claimed.

## Quick start

Requirements: Python 3.11 or newer. The deterministic evidence-review path uses only the Python standard library and needs no API key.

Run the terminal interface:

```bash
./runtime/run.sh
```

Run the unified local web console:

```bash
./runtime/run_web.sh
```

Open <http://127.0.0.1:4311>. The server accepts loopback bindings only. The **Assistant**, **Critical Prompt Loop** mode and **Evidence review** views are modules of the same AIOA spArkHAT process.

Install optional provider/browser dependencies into a local virtual environment:

```bash
./runtime/install.sh
```

The optional Textual interface starts with:

```bash
./scripts/start_tui.sh
```

## Dated evidence review

The bundled scenario demonstrates a common high-stakes failure: a fluent answer repeats Germany's 2025 statutory minimum-wage value for a July 2026 question. AIOA spArkHAT compares the answer with three dated official records, identifies stale or conflicting values, checks temporal/source attribution, and hashes both the evidence set and answer snapshot.

Run the bundled stale example in the CLI:

```text
/review
```

Run the corrected example or supply your own candidate text:

```text
/review corrected
/review Seit Januar 2026 gelten laut BMAS 13,90 Euro brutto je Zeitstunde.
```

The web API exposes the same engine:

```text
GET  /api/review/scenario
POST /api/review
```

Example request:

```json
{
  "candidate_answer": "Der Mindestlohn beträgt 12,82 Euro brutto pro Stunde."
}
```

Every successful comparison retains these authority boundaries:

```json
{
  "decision_state": "HUMAN_REVIEW_REQUIRED",
  "authority": "METADATA_ONLY_NO_AUTHORITY",
  "legal_advice": false,
  "network_used": false
}
```

The module is intentionally bounded. A matching number corroborates one registry value; it does not prove that an entire answer is correct, decide whether a rule applies to a person, or replace current official sources or qualified advice. The bundled records were rechecked on 2026-08-25 against [BMAS guidance](https://www.bmas.de/DE/Arbeit/Arbeitsrecht/Mindestlohn/Informationen-zum-Mindestlohn/informationen-zum-mindestlohn-deutsch.html), the [official rate history](https://www.bmas.de/DE/Arbeit/Arbeitsrecht/Mindestlohn/Glossar/G/Gesetzlicher-Mindestlohn.html), and [MiLoV5](https://www.gesetze-im-internet.de/milov5/MiLoV5.pdf).

See [Dated Evidence Review](docs/modules/DATED_EVIDENCE_REVIEW.md) for the contract and extension rules.

## Runtime flow

```text
Operator
  ├─ /review or evidence-review UI
  │    -> bounded input validation
  │    -> immutable dated registry
  │    -> deterministic comparison + SHA-256
  │    -> HUMAN_REVIEW_REQUIRED
  │
  ├─ Critical Prompt Loop (/cpl or Assistant mode)
  │    -> immutable plan + explicit one-use approval
  │    -> primary draft -> Logic & Claims -> Safety & Authority
  │    -> Evidence & Consistency -> one primary-model revision
  │    -> advisory response + persisted integrity trace
  │
  └─ normal request
       -> slash commands / local router
       -> epistemic and knowledge gates
       -> optional provider planning
       -> structured action validation
       -> operator approval when required
       -> local executor
       -> result, state, and provenance boundaries
```

External providers are optional and non-deterministic. Their output may assist an operator, but it is not evidence, provenance, or runtime authority by default. The evidence-review module never calls a provider.

## Useful commands

```text
/status
/model
/model gemini
/providers
/setup
/review
/cpl help
/hat list
/scan /path/to/project
/rhcsa status
/tools
/help
```

`/model` changes the assistant provider/model selection. It does not change the deterministic review engine or its authority state.

## Provider configuration

Provider credentials must remain outside the repository. Depending on the selected provider, AIOA spArkHAT can read environment variables such as:

- `AUREON_API_BASE_URL` and `AUREON_API_KEY`
- `OPENROUTER_API_KEY`
- `GEMINI_API_KEY`
- `XAI_API_KEY`
- `DEEPSEEK_API_KEY`

Use `/setup` for the local configuration checklist and `/providers` for availability. Never commit keys, browser profiles, session logs, or machine-specific state.

## Repository structure

```text
AIOA-spArkHAT/
├── runtime/
│   ├── main.py                 # canonical AgentRuntime and CLI
│   ├── webapp.py               # one local HTTP server and JSON API
│   ├── evidence_review/        # dated registry and deterministic review engine
│   ├── critical_loop/          # advisory draft, 3 distinct critics, one final revision
│   ├── adaptive_routing/       # local classifiers and epistemic kernel
│   ├── commands/               # slash-command registry
│   ├── knowledge/              # local Linux/RHCSA corpus and validators
│   ├── providers/              # optional model-provider adapters
│   ├── retrieval/              # canonical retrieval facade
│   ├── tools/                  # controlled local tools and provenance helpers
│   ├── run.sh
│   └── run_web.sh
├── web/                        # unified browser console
├── tui/                        # optional Textual console
├── tests/                      # deterministic, boundary, API, and runtime tests
├── docs/                       # architecture, governance, reports, and module docs
└── state/                      # public-safe provider/model defaults only
```

Mutable runtime state is stored outside the checkout under `~/.local/state/aoia` by default. Set `AOIA_HOME` to use another local state root.

## Safety and authority

AIOA spArkHAT is designed around explicit boundaries:

- risky local actions require operator confirmation where gates are implemented
- model output cannot silently become evidence
- provenance verifies recorded lineage/integrity, not factual truth
- unresolved local retrieval can refuse instead of fabricating an answer
- evidence review is read-only, deterministic, size-bounded, and human-gated
- the local web server rejects non-loopback bindings and applies restrictive browser headers

AIOA spArkHAT is not a truth engine, legal adviser, generic autonomous agent, production security certification, or scientific validation system.

## Tests

Run the complete suite from the repository root:

```bash
PYTHONPATH=runtime PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s tests -v
```

The suite covers routing determinism, execution containment, evidence/provenance contracts, retrieval refusal, provider selection, CLI commands, the dated-evidence engine, its static no-provider/no-write boundaries, and the integrated local web API. Browser and TUI tests skip cleanly when their optional dependencies are not installed.

## Reviewer and governance entry points

- [Project overview](docs/reviewer/PROJECT_OVERVIEW_FOR_REVIEWERS.md)
- [Implemented capabilities](docs/governance/IMPLEMENTED_CAPABILITIES.md)
- [Authority scope](AUTHORITY_SCOPE.md)
- [External model output policy](docs/governance/EXTERNAL_MODEL_OUTPUT_POLICY.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Runtime map](AOIA_RUNTIME_MAP.md)
- [Core integration and compatibility map](docs/CORE_INTEGRATION.md)
- [Stress-test documentation](docs/stress_tests/README.md)

Research material under `MHLM_MHSR/` and LSC case-study documentation provide background and stress-test context. They are not a second runtime and do not override AIOA spArkHAT's authority contracts. Historical documents retain the names used when they were written.

## License

AIOA spArkHAT is released under the [MIT License](LICENSE). Linked official sources remain subject to their respective terms.
