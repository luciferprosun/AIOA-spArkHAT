# One-repo convergence plan

Canonical prototype candidate: AIOA-spArkHAT-nebius, integration baseline b0cdec9bb9871361d9af4f9be9e4178a5aff67ca. Main/origin-main d26266e54ee940d7ada30aa02783dc697618a72c are ancestors and stay unchanged. No branch-tip merge is needed for chatgpt/nebius-live-gate or codex/nebius-verified-delta-bridge: both tips are already ancestors, each 35 commits behind baseline. nebius-personal-ai is one commit behind baseline; security hardening is retained. Prototype Fund docs branch has the same baseline. Cached origin/nebius-personal-ai diverges 25/32: preserve it and exclude any blind merge; no claim about current remote state is made without fetch (forbidden in this workbook).

## KEEP_IN_AIOA

- Existing singular runtime/CoreAdmission, planner/reviewer and typed proposal/provider/outcome contracts.
- Native memory/HAT and source lineage, Verified Delta/evidence admission, CPL/critics; memory/model output remain non-authorizing.
- Existing ProviderRequest/ProviderResponse, Nebius exact-model routing/cost guard and deterministic fixture providers.
- Existing ServiceGuard, intent/idempotency receipts, independent target readback/reconciliation, native disposable target and demo composition.
- lab/archaioa PCAF contracts/attenuation/effect model as explicitly isolated CONTRACT/FIXTURE/SPEC_ONLY proofs; never promote their declarations to production authorization.
- Product docs, portable deterministic reviewer command, tests and redacted metadata/provenance references. Keep licenses, package manifest, lockfiles and private historical R&D labeling.

## KEEP_EXTERNAL_DURING_HACKATHON

- MCP Commander development/control-plane repository and READ_ONLY worker PID206585.
- GitHub Task Bus and MCP transport implementation: mailbox/evidence transport only, never authority.
- N5 FIXTURE Ed25519/Temporal Authority/CAS/replay foundation and N6 typed boundary. Do not copy another authority core into AIOA.
- External immutable raw run evidence, runtime state, credentials and private lineage. Reviewer snapshots reference sanitized hashes/classifications only.

## MIGRATE_MINIMAL_RUNTIME_LATER

- Only a versioned thin typed adapter over existing AIOA task/provider/result contracts if a later architecture task proves it is required.
- Bounded artifact/task-result references with compatible opaque IDs/content, 400-byte/12-line pagination where the MCP boundary applies.
- Human-decision status references resolved solely by the local human-authority subsystem. No model approval, raw signer material, second executor or warrant issuer.
- Production signer custody and current-authority integration remain OPEN; new runtime wiring/live cloud execution require separate human gates.

## Sprint implementation boundary

The reviewer-facing AIOA repository must run the local prototype on its own using current native modules and explicit fixtures. MCP remains external; no live worker import or second bridge is required. A potential receipt graph must be a bounded read-only projection over existing authoritative records, not another receipt/evidence store or execution authority. The roadmap audit will establish the first missing capability before selecting code.

Duplicate Core/authority/task schema/provider client/scheduler/memory/evidence store is prohibited. DVM/pheromone/epistemic stigmergy stay SHADOW. No paid call, cloud resource, visibility change, push or main mutation in this sprint.

## 2026-10-08 local convergence update

STEP3 clean native baseline at c91fa13: 1283 PASS, 4 exact native-approved UI skips, no failures/errors/timeouts. Continue on existing integration branch only. Audited all canonical blocks 01-14 against files and observed tests; selected exactly block 05. Keep causal/bi-temporal graph as a bounded READ projection over existing ServiceGuard OPERATION/AUDIT records; no graph datastore or competing receipt schema. The reviewer uses the same deterministic demo/preflight. MCP/fixture authority/private raw evidence remain external. Production custody/distributed authority/cloud execution remain OPEN or human-gated. SmartRouter is excluded.
# Block 06 local convergence checkpoint

The next accepted local capability is a metadata-only context capsule over existing native retrieval lanes. Reuse the existing request/bundle hashes, Core owner/HAT READ checks, temporal/current source binding, native personal context and `context_budget_bytes`. Payload stays in the current memory/retrieval path; no new store, admission engine or authority path is introduced. The existing reviewer slice alone exposes the projection. MCP remains external. Main remains NO-GO while later architectural acceptance gates remain open. This historical Block06 scope is preserved; the separate SOL61 ULTRA authorization now permits sequential local convergence.

## SOL61 ULTRA local convergence after accepted Block06

Use accepted parent `3ed32e0f6d14bac5827d60243bdafe26dbfb2583`. Root is the sole writer on the existing integration branch. Block07 extends native Core/transaction/audit, exact Nebius port and ServiceGuard through explicit host bindings, with no new persistence or authority system. See [dual governor scope](DUAL_GOVERNOR.md). Commit only after local focused/static/security/review gates; retain failed and RED evidence. Blocks08–14 progress only after their dependencies pass. Run one full final candidate suite rather than one per edit. MCP remains READ_ONLY; LIVE/cloud/official/publication/main gates remain separate.

PRV: read-only remote lookup on 2026-10-08 found `main=d26266e54ee940d7ada30aa02783dc697618a72c` and `nebius-personal-ai=944590c4837629d5fe3b5b193a7ec75364e99eec`. Cached origin/nebius-personal-ai remains unchanged and is not this current remote snapshot. Historical CI successes certify those exact historical refs, not this unpublished candidate. The canonical Innovation Book v2 source remains UNK pending its local path; use the supplied master directive without pretending its crosswalk is independently established.
