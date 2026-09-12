# NonZero CloudOps native convergence map

Design frozen before implementation. Product: AIOA spArkHAT. Phase 3 is local only.

Historical Phase 3 design record: source paths and retention statements below
describe the pre-retirement oracle. Phase 4 removed that tree from the active
repository after sealing its final tests. Current operation and recovery are
documented in [one-system retirement](NONZERO_ONE_SYSTEM_RETIREMENT.md).

Baseline paths below are relative to `runtime/nonzero_cloudops/baseline/src/aioa_cloudops_agent/` unless they name repository scripts/config. Native paths are relative to `runtime/nonzero_cloudops/`.

## Before and after

```text
Before: Core admission -> Phase 2 adapter -> baseline LocalApiApplication
                                          -> token authorizer / composition / Strands
                                          -> domain workflow + local durable state

After:  Core AgentRuntime / commands / WebRuntimeService (only application)
        -> native module status + admission + Core kill switch
        -> planning / exact human decision / bound portable execution
        -> independent persisted read-back / typed evidence
        -> existing Core AppendOnlyProvenanceStore

Reference only: unchanged baseline tree -> legacy regression/provenance oracle
```

## Decisions

| Subsystem | Classification | Baseline source | Native target | Core equivalent / reason |
|---|---|---|---|---|
| domain models and enums | KEEP_NATIVE | nz/contracts.py; nz/enums.py; nz/identifiers.py; domain/enums.py | models/ | No equivalent Core CloudOps resource/receipt schema. Preserve strict fields, UTC, UUIDv7, canonical hashes and state validators. |
| investigation tools | KEEP_NATIVE | cloudops/query_resource.py; cloudops/provider.py | investigation.py; adapters/resources.py | Domain reads only. Core ExecutionEngine generic shell/browser tools are not equivalent exact-target CloudOps readers. |
| proposal and binding | KEEP_NATIVE | cloudops/plan_remediation.py; nz/contracts.py:RemediationProposal | policy.py; models/contracts.py | Preserve inert proposal, canonical parameters, evidence fingerprint, TTL and exact hash/version binding. |
| policy checks | ADAPT_TO_CORE | nz/authority.py; nz/transitions.py; safety/failures.py | models/authority.py; models/transitions.py; models/failures.py | Core admission and AgentRuntime.safeguards.kill_switch outside domain policy. Never replace PLAN_AND_CONFIRM with generic tool confirmation. |
| human approval | ADAPT_TO_CORE | agent/local_hitl.py:request_approval,decide | execution.py; approval.py | Core commands.local_commands and webapp._handle_nonzero supply trusted operator admission; nonce/expiry/exact domain decision remain. No second auth server or credential. |
| execution binding | KEEP_NATIVE | agent/local_hitl.py:resume; cloudops/local_mock.py:_validate_execution_binding | execution.py; adapters/portable.py | Core tools.executor.ExecutionEngine._request_approval is unbound ENTER confirmation, not a substitute for durable domain authorization. |
| replay and idempotency | KEEP_NATIVE | persistence/memory.py; persistence/durable_logic.py; persistence/semantic_idempotency.py | state/snapshot.py; state/guards.py; state/idempotency.py | Retain compare-and-set ownership and atomic mutation+receipt, no duplicate execution. No generic equivalent in Core. |
| durability and recovery | ADAPT_TO_CORE | persistence/local.py; persistence/local_integrity.py; agent/local_hitl.py | state/repository.py; state/files.py; execution.py | Use Core runtime_state_dir child native-v1 and service lease. Domain checkpoint store is not a global provenance system. Existing CPLTraceStore handles CPL states only. |
| independent verification | KEEP_NATIVE | cloudops/local_mock.py:LocalMockStateStore.verify | adapters/portable.py; verification.py | Separate persisted read-back after execution, linked receipt; no success solely from proposal/model response. |
| evidence and receipts | ADAPT_TO_CORE | local_api/contracts.py; local_api/views.py; nz/contracts.py | views.py; evidence.py; models/contracts.py | Keep sanitized typed projections, replace runtime/framework labels with truthful Core native labels. |
| portable backend | KEEP_NATIVE | cloudops/local_mock.py; cloudops/provider.py | adapters/portable.py; adapters/resources.py | Explicit deterministic synthetic inventory, no AWS credential discovery and no external transport. |
| AWS backend | OPTIONAL_BACKEND | cloudops/ec2_readonly.py; cloudops/cloudwatch_readonly.py; remediation/; persistence/nz_dynamodb.py | adapters/aws_optional.py | Explicit unavailable boundary in phase 3; no native live backend certification or mutation. Historical AWS implementation remains reference-only, never auto-loaded. |
| Strands/provider interaction | REUSE_CORE | providers/model.py; providers/factory.py; agent/investigation.py | adapters/advisory.py | No Strands agent/factory/global manager. Portable domain advisor emits untrusted candidate JSON; any future real model must use existing runtime.providers.manager.ProviderManager exact calls after separate approval. |
| HTTP/API server | RETIRE | local_api/application.py; local_api/auth.py; local_api/server.py | service.py; existing runtime/webapp.py | Use existing WebRuntimeService/make_server and _handle_nonzero: loopback Host, Origin, session token, explicit intent. Do not port LocalApiApplication. |
| judge browser UX | RETIRE | local_api/judge_ui.py; judge/ | existing Core web surface and /api/nonzero | No duplicate UI/session/cookie application. Preserve Core UI, no hackathon UI transplant. |
| CLI/demo scripts | REUSE_CORE | scripts/run_local_hitl_api.py; scripts/run_portable_demo.py | existing runtime/commands/local_commands.py:cmd_nonzero | Core /nonzero and typed service; baseline scripts run only as reference gates outside runtime. |
| configuration/environment | ADAPT_TO_CORE | config.py; agent/local_composition.py | contract.py:ModuleConfig; service.py | Explicit typed portable default, disabled/malformed/aws unavailable states. Ignore ambient AWS/Bedrock selectors. No baseline environment parser. |
| packaging/dependencies | REUSE_CORE | pyproject.toml; Dockerfile; deployment/ | Core pyproject.toml | One aioa-sparkhat wheel, optional nonzero extra only domain validation/UUID dependencies. No second project, Strands SDK, baseline data or runtime pip/Git. |
| tests and gates | REFERENCE_ONLY | tests/; scripts/run_p0_gate.py; scripts/run_p1_gate.py; scripts/run_b4_hardening_gate.py | tests/test_nonzero_native*.py; tests/test_nonzero_integration.py | Frozen 1447-test oracle plus native parity and clean installed-wheel tests. Do not edit oracle tests to make native tests pass. |
| provenance and audit | REUSE_CORE | persistence/models.py:ProvenanceRecord; local_api/views.py | provenance.py; runtime/tools/provenance.py | Use actual AppendOnlyProvenanceStore.append_event and verify_provenance_chain. Domain AuditEvent records checkpoint facts, not a competing global chain. Hashes prove linkage/integrity, never truth. |
| hackathon hosting/release plumbing | RETIRE | judge/; release/; deployment/; .github/; Dockerfile | none in native runtime | Preserved only under unchanged baseline for reference and licensing; no deployment, workflow, second package or Git operations. |
| legacy EC2 execution schema | REFERENCE_ONLY | domain/models.py; old Strands stop-instance flows | models/contracts.py and state snapshot only where schema validators require them | Preserve dependent typed compatibility fields; do not register old autonomous executors or launchers. Live CloudWatch/Dynamo parity deferred. |

## Scope and acceptance

The only executable backend certified here is portable. Optional AWS selection fails closed explicitly; this is not a claim that live AWS implementation has converged or been tested. Native contract and domain workflow are prepared for an explicit backend boundary; transporting or certifying live AWS is deferred.

Core's existing command registry and `_handle_nonzero` admission remain the outer authority. `operator=True` is an internal trusted-dispatch marker, not authentication for arbitrary Python callers. Core's current server is single local operator, not a public multi-user service. No new top-level credential or authority manager is introduced.

A new `native-v1` state child avoids interpreting Phase 2 credentials or state as native authorization. No existing state is deleted or migrated automatically. Domain hashes retain their canonical JSON encoding because Core's generic hash encoding is not wire-identical; the global chain reuses Core's implementation.

The `models/` and `state/` subpackages hold typed domain schemas and durable semantics; they are not a renamed full source package. App/server/config/provider factory/CLI/release/hosting code is deliberately excluded. Mechanical ports must record exact source paths, SHA-256 and adaptations. Baseline is excluded from the wheel and hidden during native regression.

Reference: [native contract](../modules/NONZERO_CLOUDOPS_NATIVE_CONTRACT.md). Machine-readable counterpart: `NONZERO_CLOUDOPS_CONVERGENCE_MAP.json`.
