# Non-Zero CloudOps Agent inside AIOA spArkHAT

Status: isolated integration branch; no main merge or deployment.

```text
AIOA spArkHAT / AgentRuntime
├── existing providers, tools, memory, evidence review and CPL
└── nonzero_cloudops service
    ├── /nonzero operator CLI
    ├── /api/nonzero/* on the existing loopback server
    ├── baseline/ — complete exact frozen CloudOps subtree
    └── AOIA_HOME state — durable truth, mock inventory, Core provenance
```

## Install

Use a **separate Python >=3.12 environment**. Never install into the frozen jury
repository or modify its environment.

```bash
python3.12 -m venv /absolute/operator-selected/path/nonzero-env
/absolute/operator-selected/path/nonzero-env/bin/python -m pip install '.[nonzero]'
/absolute/operator-selected/path/nonzero-env/bin/aioa-sparkhat --help
/absolute/operator-selected/path/nonzero-env/bin/aioa-sparkhat-web --help
```

If the OS lacks `ensurepip`, its existing `virtualenv` tool can create that new
environment. No system Python upgrade is required. Ordinary Core does not need
the extra; `/nonzero status` reports missing requirements without creating state
or borrowing another checkout.

## Operator flow

```text
/nonzero help
/nonzero status
/nonzero ready
/nonzero start-json {"resource_type":"AWS::EC2::EIP","resource_id":"eipalloc-0123456789abcdef0"}
/nonzero run <run_id>
/nonzero approval <run_id>
/nonzero decision-json <exact-decision-JSON>
/nonzero resume <run_id> CONFIRM
/nonzero trace
```

The target is a synthetic fixture, not an AWS resource. Start observes/proposes
without executing. Review the exact proposal and evidence. For a decision, copy
`request_id`, `run_id`, `proposal_id`, `request_hash`, `proposal_hash`,
`evidence_hash`, `proposal_version` from the approval challenge's `request`.
Add its `decision_nonce` and `decision: "APPROVED"` or `"DENIED"`. Do not alter
the bindings. Approval still does not execute: `resume ... CONFIRM` is separate.
Denial never mutates inventory. Repeated execution reconciles the original
receipt, including after restart.

| Method and path | Purpose |
|---|---|
| `GET /api/nonzero/status` | Discovery and dependency availability |
| `GET /api/nonzero/ready` | Actual service readiness/counters |
| `POST /api/nonzero/runs` | Exact synthetic target, inert proposal |
| `GET /api/nonzero/runs/<run_id>` | State, categorized evidence and receipts |
| `POST .../<run_id>/approval-request` | Empty object, exact one-time challenge |
| `POST .../<run_id>/decision` | Exact bound decision object |
| `POST .../<run_id>/resume` | `{"confirm_execution":true}` |
| `GET /api/nonzero/trace` | Core provenance linkage verification |

All module routes require Core's `X-AIOA-Session-Token`, obtained locally from
`/api/session`; writes additionally require `X-AIOA-Intent: nonzero-operator-v1`.
Use same-origin requests. Never put credentials/nonces in URLs or public logs.
`/api/chat` cannot invoke `/nonzero`, even in Plain Chat mode. This is the existing
single-local-operator boundary, not public multi-user authentication.

`AOIA_HOME` selects the established state root. Its runtime namespace contains
the module's `nonzero_cloudops` state directory. A locally generated private
credential preserves ownership after restart; it is not a cloud/provider token
and is never committed. Do not delete state to retry ambiguous operations;
inspect `run` and `trace` first.

## Provenance and verification

- Jury: `https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent`
- Frozen SHA: `4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a`
- Private source: `luciferprosun/AIOA-Integration-Sandbox`
- Ref/tag: `baseline/judge-freeze` / `judge-freeze-4fafed8b1a87`
- Core baseline: `5f30f092f7a20035ed1caf4a8e22397673f598df`
- Exact import: `119a8ba12e54a2fbea42a43d62725e25fb5bc380`
- Strategy: non-squashed subtree; 412 exact files, no tracked exclusions.
- Original MIT license, authorship and prior-art attribution retained.
- Exact adapter commits and results: [source import map](NONZERO_SOURCE_IMPORT_MAP.json).

See [ADR NZ-001](ADR/ADR-NZ-001-frozen-subtree-adapter.md) for the dependency
matrix, existing interfaces, authority boundary and Git-aware gate context.
No frozen jury files, commits, refs or settings were modified.

```bash
PYTHONPATH=runtime PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONPATH=runtime PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_nonzero_integration.py -v
```

Use the module environment to execute all adapter tests rather than optional
dependency skips. Native checks include Ruff, full pytest, portable demo, P0,
P1, B4 and reviewer-evidence build/check in the ADR's frozen Git context. Synthetic
mutations and loopback fixture HTTP are expected; real AWS mutations and paid
model calls are forbidden. Hashes prove integrity/linkage, not factual truth.
