# Launch and acceptance — AIOA spArkHAT

Python 3.11+. The new CPL/fixture and evidence paths use the standard library. Run with a fresh private `AOIA_HOME`; do not point verification at another project's state. Use one runtime process per CPL state root. Sources and audit traces are separate.

## Safe local fixture

From this repository root:

```bash
./runtime/run.sh --cpl-fixture --command '/cpl fixture'
./runtime/run_web.sh --cpl-fixture --port 4311
```

Open `http://127.0.0.1:4311` → Assistant (CPL is already the default) → enter an ordinary question in **Your question** → **Preview CPL plan** → inspect → **Authorize TEST plan and run fixture** → **Verify Evidence Chain**. No copy into a specialist form is needed. Evidence starts empty. Optional exact models, lower limits and per-run budget are in the advanced settings. Only COMPLETED publishes the final revision to the normal answer log; the draft/reports and trace are in the inspector.

The explicit **Load synthetic dated example** button is a separate TEST convenience. Its deliberately prewritten replies describe two/three synthetic jobs; they do not demonstrate factual answers to other questions. Production orchestration is domain-generic. German-law material belongs to the separate deterministic review scenario, not CPL routing. Errors/cancellation never become a draft-as-final or an ordinary-chat fallback. Cancel remains available while the worker waits on HTTP. Changing an input invalidates pending approval, including responses from a plan request still in flight.

Choosing **Plain Chat** is an explicit CPL bypass, prominently labeled as not reviewed. Reload starts in CPL, even when an old installation retained a legacy chat preference. Existing slash commands, including `/help`, `/status` and `/review`, remain explicit commands rather than topics routed through a model.

Use the same fixture command in a fresh process to read previous runs: `/cpl status`, `/cpl status ID`, `/cpl verify ID`. A new process cannot start a previous unconsumed plan: restart marks it INTERRUPTED. To plan then start manually, use the interactive CLI in a single process. `--command` is appropriate for the complete fixture flow or read/verify actions, not a multi-process nonce handoff.

Interactive CLI normal questions also create CPL plans by default. Inspect the printed plan then use `/cpl start ID HASH NONCE` in that process; nothing automatically approves. `--plain-chat` explicitly restores the legacy Core action/chat path and its existing action-approval controls. For a later separately authorized LIVE session, combine `--cpl-live-policy` with `--cpl-run-budget POSITIVE_USD_CAP`, or use `/cpl plan-json` to set per-plan options. The cap is admission data, not generation authorization. The optional Textual launcher accepts the same policy/budget and bypass flags; its default admission adapter uses the same runtime. Ctrl+X cancels an active CPL run when no tool approval is pending. Mounted Textual UI testing requires the optional dependency; its dependency-free admission adapter is tested in the required suite.

## Installed entry points

Install this repository into an operator-selected local venv, never globally. Packaging supports editable and regular installation with no external runtime dependencies for the bounded CPL path. `aioa-sparkhat` and `aioa-sparkhat-web` delegate to the same legacy runtime. `python -m runtime` is also supported. Web assets are included. Optional historical Gemini/browser/Textual dependencies remain separate and are not silently installed.

## Live is a later operator action, not this fixture

Do not treat a passing fixture as evidence of live provider success. No live model call is required for the test suite. Before a later live smoke, manually verify model availability, exact returned model identity, token/context/output limits and fresh input/output USD prices. Use the existing OpenRouter credential mechanism; do not put keys in a policy, repo, trace or report. No credentials are provisioned by CPL.

Start with `--cpl-live-policy /absolute/private/policy.json` instead of `--cpl-fixture`. The bounded JSON must contain exactly:

```json
{
  "live_enabled": true,
  "session_budget_usd": "OPERATOR_POSITIVE_LIMIT",
  "quotes": {
    "vendor/exact-model-id": {
      "currency": "USD",
      "input_usd_per_million": "VERIFIED_PRICE",
      "output_usd_per_million": "VERIFIED_PRICE",
      "quoted_utc": "VERIFIED_CURRENT_UTC_TIMESTAMP",
      "input_bound_policy": "utf8-bytes-plus-framing-v1"
    }
  }
}
```

These placeholders are intentionally invalid; no price or budget is guessed. Provide quotes for all four chosen model bindings (one quote suffices for identical IDs). Set a positive per-run budget in the UI, preview the full plan and approve only that plan. Unsupported IDs/identity, disabled provider, missing key/price, exhausted budgets and stale quotes fail closed. The local process cannot guarantee a provider stops billing when an HTTP call is cancelled.

## Tests

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -v
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_cpl_*.py' -v
node --check web/app.js
bash -n runtime/run.sh runtime/run_web.sh
```

Use an isolated HOME/XDG/AOIA_HOME and blocked external networking for tests. Required CPL tests use loopback HTTP, never API keys. Historical optional Playwright/Textual skips must be reported separately. Reports must distinguish pure-helper ports from real runtime/HTTP/browser/install execution.
