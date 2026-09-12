# NonZero CloudOps native provenance

Canonical product: **AIOA spArkHAT**. Module: `nonzero-cloudops`.
This is a local Phase 3 convergence of the historical Core, not a second product.

## Immutable lineage

- Jury repository: `luciferprosun/AIOA-NonZero-CloudOps-Agent`.
- JUDGE_SHA: `4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a`.
- Jury source tree: `a6587b72b4f7d1365ef7de7cab107ea6578f4567`: 412 exact tracked files; 84 ancestors reachable from the selected commit.
- Private transfer source: `luciferprosun/AIOA-Integration-Sandbox`, `baseline/judge-freeze`.
- Core/main baseline: `5f30f092f7a20035ed1caf4a8e22397673f598df`.
- Full-history import: `119a8ba12e54a2fbea42a43d62725e25fb5bc380`.
- Phase 2 adapter: `15c63fda6e759312924eb272a5dbda20269bad2f`.
- Phase 2 final/start of Phase 3: `ad7d2ffa602654fab7ffe30168339f2dc138278f`.
- Phase 3 branch: `integration/nonzero-cloudops-native-v1`; parent history remains unchanged.

Source code attribution and MIT permission notice are retained verbatim in
`runtime/nonzero_cloudops/LICENSE-NONZERO.txt`, also included in the Core wheel.
Ported files identify original paths and SHA; this does not claim the imported
logic was newly authored for a different contest. The historical whole source
and its license remain unchanged under `baseline/`.

## Selective semantic migration

[Machine-readable source mapping](NONZERO_CLOUDOPS_NATIVE_MAP.json) records
26 semantic files and two small extracts, including original source hashes and
symbol renames. [Convergence map](../integration/NONZERO_CLOUDOPS_CONVERGENCE_MAP.md)
classifies the rest of the source architecture.

| Original subsystem | Native location | Preservation / adaptation |
|---|---|---|
| NZ contracts, enums, identifiers, authority and transitions | `models/` | Exact domain schemas, action/resource/UTC/UUIDv7/hash bindings retained; Python generics adapted |
| QueryResource / PlanRemediation | `investigation.py`, `policy.py` | Read-only evidence and inert policy-bound proposal; stricter ambiguous-JSON rejection |
| LocalFirst phase one | `planning.py:InvestigationWorkflow` | Safe terminal and approval boundary; persisted bounded local advisory units |
| Local HITL phase two | `execution.py:BoundExecutionWorkflow` | Exact nonce/actor/request/proposal binding, denial, expiry, intent, replay/recovery and verification |
| Mock inventory and executor | `adapters/portable.py` | Atomic synthetic mutation + receipt; independent persisted read-back |
| Durable transaction semantics | `state/` | Same compare-and-set/checkpoint/replay rules; private leased Core state namespace |
| Local read DTOs | `views.py`, `evidence.py` | Sanitized evidence, truthful Core native labels; browser session DTO removed |
| App/auth/provider factory | Core `AgentRuntime`, CLI, webapp; `service.py` | Not ported as an app; no new credential, server, provider manager or runtime Git |
| Global audit linkage | Core `tools.provenance.AppendOnlyProvenanceStore` | Reused format/verifier; native adapter adds bounded, private, fsynced intent/result linkage |

The local domain transaction image was called an in-memory test repository in
the source, but the source's durable implementation already used it for every
transaction. Native `DomainSnapshot` makes that role explicit; it is never
selected as a production durability fallback. Legacy EC2 schema fields required
by snapshot validation remain typed compatibility data, not registered legacy
executors or a second runtime.

The small `NativeComponents` dataclass is dependency injection, not an
application: it has no server, auth, run loop, provider factory or lifecycle.
Core owns the service and its state. CloudOps is not routed through CPL.

## Preserved safety and intentional hardening

For fixed IDs, clock and synthetic challenge, five independently generated
oracle scenarios preserve hashes of initial evidence/proposal, approval request,
decision and final receipt/verification: EIP approve, ingress approve, EIP deny,
clean EC2 no-action, missing-tag recommendation. Vectors live in
`tests/fixtures/nonzero_parity_v1.json` and contain only digests, no raw nonce.
`tests/test_nonzero_parity.py` runs only native code.

Native-specific hardening, not edits to the oracle:

- Pydantic's `Literal[True]` also accepted integer `1`; the native execution gesture now requires exactly boolean `true`.
- Exact proposal version rejects integer coercion.
- Advisory JSON uses Core's duplicate-field rejection and bounded byte accounting; the local advisor cannot assert authority.
- State source identity, leased ownership, explicit disabled/config states, run/evidence quotas and Core kill switch fail closed.
- Receipt/read-back run/proposal/operation/target linkage is explicitly checked before closing success.
- Private state and log writes cannot silently grant authority when provenance fails.

Full Core regression is separate from native tests; the original 1447-test
pytest suite, Ruff, portable/P0/P1/B4 and reviewer evidence remain reference
certification only. They are not claimed as 1447 tests of the new native path.

## Python and packaging decision

Policy A: Core and native module use Python >=3.11. The old source genuinely
uses PEP 695 in six files (seven definitions): `nz/errors.py`,
`persistence/local.py` (two functions), `persistence/serialization.py`,
`persistence/nz_dynamodb.py`, `local_api/application.py`,
`release/deployment_contract.py`. Only ControlResult and the two local repository
generics enter the selected native path; these use TypeVar/Generic instead.
Other 3.12-only files remain reference-only.
[Python's official 3.12 change notes](https://docs.python.org/3.12/whatsnew/3.12.html#pep-695-type-parameter-syntax)
describe the newer syntax.

Native direct dependencies are `pydantic==2.13.4` and `uuid6==2025.0.1`.
No Strands or baseline project installation is required. Discovery remains
stdlib-only; missing extras yield a typed unavailable state. Compatibility is
tested with actual CPython 3.11.13 and 3.12.3, including installed Core wheels.
The separate 3.11 test interpreter is an externally stored, SHA-256-verified
[python-build-standalone release](https://github.com/astral-sh/python-build-standalone/releases/tag/20250818);
it does not change system Python or the Core minimum.

## Reference retention and deferred work

`baseline/` is retained only for history/provenance/reference tests. It is
excluded from the wheel and hidden in native runtime tests. No native code
imports or reads it; runtime does not clone/fetch Git or launch baseline scripts.

Deferred explicitly: native live AWS/CloudWatch/Dynamo backend certification,
real-model adapter through Core's ProviderManager, Phase 2 state migration,
public multi-user service hardening, baseline removal and remote publication.
`adapters/aws_optional.py` returns unavailable even after explicit selection;
no credentials are read and no live AWS operation is certified.
The protected backend protocol alone is not proof that a future live backend
can safely replay an uncertain mutation.

The current portable backend may reconcile from its atomic inventory/receipt
store; this is not a claim of exactly-once guarantees for arbitrary cloud APIs.
Hashes prove integrity/linkage, not factual correctness or external attestation.

No push, PR, main merge, release tag or deployment is part of Phase 3.
