# NV-01: integrated AIOA G1 foundation

This phase adds configuration and inspection to the existing `AgentRuntime`.
It does not deliver a live NVIDIA agent. The default profile is disabled, all
effects are off, and the existing CLI remains unchanged outside the new
`doctor` and `mission validate` subcommands.

## Installed CLI

```console
aioa-sparkhat doctor --profile nvidia-lite --json
aioa-sparkhat doctor --help
aioa-sparkhat mission validate --help
aioa-sparkhat mission validate tests/fixtures/nv01_mission.json --contract-fixture --json
aioa-sparkhat doctor --profile nvidia-lite --manifest tests/fixtures/nv01_mission.json --contract-fixture --json
```

The fixture path is a source-tree example, not an installed runtime resource.
The explicit `--contract-fixture` flag uses a fixed synthetic owner/source
registry. It cannot grant a Core principal or approval. Ordinary CLI validation
without an injected trusted Core context reports `UNAVAILABLE`, not a guessed
owner. `mission start` and product dispatch are not implemented.

Exit codes for these new commands: `0` validated/disabled inspection, `2` invalid
input, `3` unavailable configuration, `4` policy block/conflict, `5` technical
error. Historical commands retain their exit behavior. JSON contains status,
reason_code, trace_id, profile, manifest_revision, components, next_action and
retry_class. A missing trace is `null`; the CLI does not mint a second trace ID.

## Canonical manifest and trust boundary

Schema `aioa-mission-v1`, profile `nvidia-lite`, mode `CONTROLLED`,
`enabled=false`, `effects_enabled=false`, scheduler owner `AgentRuntime`.
An `AUTO_SCOPED` activation is policy-blocked. The manifest never contains
`approved`, live credentials, arbitrary source URLs, shell strings or paths in
place of registered source IDs. Secret references are configuration names only.

The parser reuses native Memory Patch bounded JSON parsing and canonical
serialization. It rejects duplicate keys, unknown fields at every supported
level, non-finite numbers, boolean integers, unsafe logical IDs, out-of-range
budgets and files larger than 24,000 bytes. Defaults are materialized before
hashing. Source and secret reference sets are sorted, unique tuples. Adapter and
policy mappings have fixed supported keys and versions. JSON objects are sorted
by the native serializer, using compact separators and UTF-8; there is no fuzzy
normalization of identifiers. The fixture's canonical SHA-256 is
`24b0541fc29998aee0b39c3bdf48596e8acec686a1d41be3d3e3746461d05e5a`.
Same owner/mission/revision with a different canonical payload is `CONFLICT`.
This is a pure comparison contract; durable CAS is a future adapter obligation.

`MissionContext` is supplied by trusted host/Core wiring, not accepted from model
JSON. The complete native tenant/owner/space/slot must match the manifest.
Registered source IDs must exist in that context. A digest is an identity
binding, not evidence of truth or authorization.

## Composition and future wiring

`runtime.main.create_runtime(inspection_only=True, mission_context=...,
mission_bindings=..., memory_patch_config=..., memory_patch_dependencies=...)`
constructs the same `AgentRuntime`, with its existing Memory Patch and NonZero
descriptors. It does not initialize ProviderManager, MemoryStore,
MemoryHatStore, ExecutionEngine, lazy CPL recovery or SQLite. Operational
entry points are guarded against using an inspection-only instance.

| Caller | Existing port/service | Required trusted input | Current test/next gate |
| --- | --- | --- | --- |
| `AgentRuntime.mission_doctor` | native Memory Patch descriptor, `CoreMemoryPatchDependencies` | assignment scope, backend factory, source registry, evidence, provenance | `test_nv01_foundation`; G3 live wiring |
| existing critical prompt loop | `CPLExactRequest` / exact OpenRouter 1+3+1 | native cost policy and run identity | legacy CPL tests; no NVIDIA relabel |
| future product provider call | NVIDIA product adapter, not yet bound | bounded client, key reference, budget gate, timeouts/429 | G2, explicitly NOT_IMPLEMENTED |
| future mission loop | `SchedulerPort.describe`, owner `AgentRuntime` | one injected scheduler owner | no start method invoked in G1 |
| future delta verification | `CorrectionDeltaLink` → native `CorrectionCandidate` | native evidence, owner, source revision, trusted verifier | G4 contract tests only |
| future trail evaluation | `PheromoneEvent` → native `ModelExperienceEvent` | scoped events, separate tau+ / tau- references | G5; no store/scoring/learning |

Presence is not readiness: a borrowed backend is `ENABLED`/not probed, not
`READY`. The product NVIDIA adapter and HAT live handles remain unavailable to
inspection. Key-present, key-missing and key-not-checked are distinct. Existing
NV00 `nvbuild` developer tooling is not a product provider. No scheduler starts.

## Delta, pheromone and DVM limits

Native candidates and experience records are reused, with thin immutable links.
The built-in no-change oracle covers Unicode NFC and outer whitespace only;
it preserves case, dates, units, literals and internal whitespace. It does not
claim general semantic equivalence. No-change retains audit identity and creates
no knowledge delta. Evidence absence, foreign scope, wrong revision and revoked
evidence fail closed. The trusted verifier seam has no default implementation
and never mints authority, approval or a Core principal.

`VERIFIED_REUSE` and `USEFUL_PROBE` are positive utility candidates;
`ERROR_RECURRED` is recheck salience, not truth; `FAILED_REUSE` is distinct.
`CONFLICT`/`REVOKED` block reuse. Snapshot references keep tau+ and tau- separate
and carry no score capable of overriding evidence revocation. Pure replay
comparison does not claim an installed durable event ledger or exactly-once
effects. The future adapter must enforce uniqueness transactionally.

The existing circadian router is not a mission scheduler. DVM-Context and
DVM-Cadence are future SHADOW/NOT_IMPLEMENTED integrations. Intent/CAS/receipt
and UNKNOWN recovery remain on the native-authority side, not in model output.

## Operational mailbridge is not part of this package

The local developer mailbridge, Gmail metadata, queue, PDF prompts, authentication
and timer are outside this repository and outside AIOA memory/HAT/indexes.
There is no dependency on Gmail or Codex for importing or installing the product.
No product live provider call or product effect is required by these tests.
