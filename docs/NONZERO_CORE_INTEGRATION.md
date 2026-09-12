# Native NonZero CloudOps inside AIOA spArkHAT

Status: local `integration/nonzero-cloudops-one-system-v1`; no push, PR, main merge or deployment.
Module identity: `nonzero-cloudops`. Contract: `nonzero-native-v1`.

```text
AIOA spArkHAT / AgentRuntime
├── existing providers, tools, memory, evidence review and CPL
└── nonzero_cloudops service
    ├── /nonzero operator CLI
    ├── /api/nonzero/* on the existing loopback server
    ├── native planning / policy / approval / execution / verification
    ├── models/ and state/ — typed domain safety and durable checkpoints
    ├── adapters/portable.py — atomic synthetic inventory plus receipts
    └── AOIA_HOME state — native-v1 domain state and existing Core provenance
```

## Install

Use one **Core Python >=3.11 environment** with the optional `nonzero` extra.
Never install into the frozen jury repository or modify its environment.

```bash
python3.11 -m venv /absolute/operator-selected/path/nonzero-env
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
the module's `nonzero_cloudops/native-v1` directory. Core supplies the authenticated
single-local-operator identity; there is no second module credential or server.
Private source-identity metadata binds state to the contract and JUDGE_SHA.
Phase 2 state remains intact and is not silently migrated or authorized.
Do not delete state to retry ambiguous operations; inspect `run` and `trace` first.

`AgentRuntime(..., nonzero_config=...)` accepts a Core-owned `ModuleConfig` or
its exact dictionary fields. `enabled=False` returns `NONZERO_DISABLED` without
initializing the service. Defaults ignore ambient AWS/Bedrock environment switches.
Selecting `backend='aws'` fails closed: explicit enablement is required, and even
with it native v1 returns `NONZERO_AWS_BACKEND_NOT_CERTIFIED`. No live backend or
external model call was enabled by this convergence pass.

The native public methods are `start(StartRunRequest)`, `inspect(UUID)`,
`request_approval(UUID)`, `decide(DecisionRequest)`,
`resume(UUID, ResumeRequest)`, `ready()` and `trace()`. The trusted Core dispatcher
supplies `operator=True`; this marker is not an authentication system for
untrusted Python callers. JSON bodies cannot provide that authority.

## Provenance and verification

- Jury: `https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent`
- Frozen SHA: `4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a`
- Private source: `luciferprosun/AIOA-Integration-Sandbox`
- Ref/tag: `baseline/judge-freeze` / `judge-freeze-4fafed8b1a87`
- Core baseline: `5f30f092f7a20035ed1caf4a8e22397673f598df`
- Exact import: `119a8ba12e54a2fbea42a43d62725e25fb5bc380`
- Strategy: non-squashed subtree; 412 exact files, no tracked exclusions.
- Original MIT license, authorship and prior-art attribution retained.
- Historical Phase 2 adapter commits and results: [source import map](NONZERO_SOURCE_IMPORT_MAP.json).
- Native implementation provenance: [native source mapping](provenance/NONZERO_CLOUDOPS.md).

See the [native contract](modules/NONZERO_CLOUDOPS_NATIVE_CONTRACT.md) and
[convergence map](integration/NONZERO_CLOUDOPS_CONVERGENCE_MAP.md).
[ADR NZ-001](ADR/ADR-NZ-001-frozen-subtree-adapter.md) records the historical
Phase 2 decision, superseded by native v1 and Phase 4 retirement. Its old
repository-aware test context is historical, not a current installation or test
requirement. Original source is recoverable from Git history, including Phase 3
commit `6563f93e2b895d494063161b438d05209e2655ca`, without rewriting any history.
See the [hash-only retirement lock](provenance/NONZERO_CLOUDOPS_RETIREMENT_LOCK.json).
No frozen jury files, commits, refs or settings were modified.

```bash
python3 -c "import runtime, unittest, sys; result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests')); sys.exit(not result.wasSuccessful())"
python3 -c "import runtime, unittest, sys; result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests', pattern='test_nonzero*.py')); sys.exit(not result.wasSuccessful() or bool(result.skipped))"
python3 -m runtime.tools.nonzero_architecture --project-root .
```

Use the Core extra to execute all native tests rather than optional dependency
skips. Native certification includes Core unittest regression, typed failure
matrix, fixed-input parity, static independence and a clean installed Core wheel.
The normal `runtime` facade is Core's existing public package bootstrap; no
PYTHONPATH setting, private loader, second checkout or baseline is required.
The final pre-retirement original pytest/P0/P1/B4/evidence/secret results are
sealed in the provenance lock. Do not restore or launch the old source to run
current acceptance tests. Synthetic
mutations and loopback fixture HTTP are expected; real AWS mutations and paid
model calls are forbidden. Hashes prove integrity/linkage, not factual truth.

The one-system static gate checks the actual tree and hash lock, and optionally
the exact wheel with `--wheel /absolute/path/to/aioa_sparkhat.whl`. It performs
no Git/network retrieval. Live AWS, real-model advisory, public multi-user
hosting and legacy state migration remain separate operator-approved work.
