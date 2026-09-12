# Skeleton to armor: evidence-backed plan

## Provenance rule

AOIA/Non-Zero work predating this AWS hackathon is prior art: it supplied concepts, experiments,
partial controls, governance language, and later independent implementations. The current
AIOA Non-Zero CloudOps Agent is newly authored competition work. No historical source, commit,
deployment definition, test, or asset is imported by this plan.

The safe evolution statement is:

> A prior-art concept existed; the AWS hackathon implementation was independently re-authored
> and strengthened with native Strands HITL, typed Non-Zero contracts, durable truth, exact AWS
> scope, restart reconciliation, and independent verification.

## What already constitutes the armor

The current design should remain narrow. These controls are already stronger for the one-scenario
CloudOps scope and need no legacy transplant:

| Current control | Exact current evidence | Decision |
| --- | --- | --- |
| One agent and exactly five tools | `src/aioa_cloudops_agent/agent/factory.py::CURRENT_TOOL_NAMES`; factory rejects drift; `test_factory_creates_exactly_one_primary_agent_and_five_canonical_tools` | Keep current. This is already an executable architecture assertion. |
| Default-deny capability boundary | `src/aioa_cloudops_agent/safety/policy.py::DefaultDenyToolPolicy`; `src/aioa_cloudops_agent/nz/authority.py`; Day 12 adversarial and integration tests | Keep current. Unknown names, aliases, extra fields, dangerous capability names, and cross-run substitution fail before dispatch. |
| Durable proposal and human authority | `ActionProposal`, `Approval`, Strands `HumanInTheLoop`, evidence hash, interrupt identity, and decision nonce | Keep current. It supersedes an in-process ENTER prompt or an unbound preview. |
| Write-before-execute and semantic idempotency | durable repository, prerequisite loader, idempotency record, private executor | Keep current. Model text never becomes execution authority. |
| Failure and retry bounds | typed failure map, schema-correction budget, read-only transient retry, turn/token/time budget | Keep current. No blind retry of mutation or ambiguous acknowledgement. |
| Recovery and verification | `RecoveryCoordinator`, checkpoint lease/version checks, lost-ACK read-back, `BoundedVerificationCoordinator`, `SUCCESS_WITH_EVIDENCE` | Keep current. It is a scoped replacement for a generic feedback/auto-recovery loop. |
| Scoped adversarial corpus | Day 12 prompt-injection, tool-confusion, forged approval, redaction, and capability-denial tests | Keep current. A general critic agent/corpus would add surface without improving the demo. |

The historical suggestion of a separate capability manifest has already been satisfied in the
runtime boundary: `CURRENT_TOOL_NAMES`, `FINAL_TOOL_CAP`, `DefaultDenyToolPolicy`, and static/factory
tests are executable sources of truth. A second manifest must not become a drifting authority
file. The later submission-evidence artifact proposed below should reference, not replace, them.

## Evidence-backed armor upgrades

These are design recommendations only. None is implemented by this audit.

### AU-1 — Independent emergency executor disable

**Historical signal:** AOIA later implemented a fail-closed write kill-switch and hardened it at
`5b66890a`. This is post-June prior art, not competition code.

**Current gap:** `SandboxRemediationSettings.live_execution_enabled` already requires two
independent positive opt-ins and defaults false. That is sufficient while live mutation remains
disabled. If both opt-ins are deliberately enabled, however, there is no separately named,
negative emergency-off control checked immediately before both DryRun and live `StopInstances`.

**Native AWS design:** add a newly authored executor-local emergency-disable input with strict
boolean parsing, default-disabled writes, fail-closed missing/malformed handling in live mode,
and a final check immediately before every mutation boundary. It must not be model-visible and
must not grant authority when enabled; proposal, approval, scope, idempotency, and preconditions
remain mandatory.

**Expected proof:** tests show disabled/missing/malformed emergency state causes zero
`stop_instances` calls; a state change between DryRun and mutation fails closed; positive-path
tests still require both existing opt-ins and a valid durable proof bundle.

**Placement and necessity:** candidate for the next P0 armor package before any live-mutation
demonstration. It is not necessary if the final submission keeps live mutation disabled.

### AU-2 — Tamper-evident audit continuity and export

**Historical signal:** the post-June durable audit ledger used event hashes and chain
verification. The current system is independently stronger in AWS identity, durable context,
redaction, and conditional uniqueness, but its `AuditEvent` records do not carry a previous-event
hash or a run-level chain verifier.

**Current gap:** DynamoDB conditional writes prevent an event-id overwrite and payloads are
hashed, yet a judge-facing export cannot currently prove ordered continuity or make omission
visible from one final anchor.

**Native AWS design:** extend the current deterministic persistence boundary with a per-run,
versioned audit-chain head and a verifier/exporter. Bind canonical redacted event material,
previous hash, run/trace/correlation IDs, and event order. Use conditional updates so concurrent
appenders cannot fork silently. Do not import the AOIA ledger implementation.

**Expected proof:** deterministic hash vectors; reordered, deleted, duplicated, modified, or
cross-run events fail verification; concurrent append conflict is explicit; secrets remain absent;
existing workflow results are unchanged.

**Placement and necessity:** useful after the next P0 gate and before a final evidence package.
Recommended, but not a blocker for a no-live functional submission if time is constrained.

### AU-3 — Release/submission evidence manifest

**Historical signal:** both AOIA and HackVerse accumulated reviewer reports and freeze manifests.
The useful concept is claim-to-proof traceability, not their implementation or broad product
surface.

**Current gap:** current claims are truthful and tested, but commit anchors, test node IDs, frozen
tool names, model pin, IAM assertions, and no-live-mutation statements are distributed across
documents and source.

**Native AWS design:** generate a compact, deterministic, reviewer-facing evidence manifest from
the current repository. Each claim should name the exact authoritative source symbol, test node,
commit, and expected invariant. The manifest is evidence, never runtime authority, and must fail
validation when a referenced path/test or frozen tool name drifts.

**Expected proof:** a documentation/evidence integrity check validates paths, test identifiers,
tool count/name set, dependency/model pin, Phase 1 tag, and commit ancestry; deliberately stale
references fail. The artifact contains no credentials, raw prompts, local paths, or AWS account
data.

**Placement and necessity:** after Day 13 stabilizes the P0 gate and before final submission.
Necessary for the final judge package, not for runtime correctness.

## Priority

| Priority | Upgrade | When to act |
| --- | --- | --- |
| P0 conditional | AU-1 emergency executor disable | Before the first authorized live mutation; omit if mutation remains disabled. |
| P1 | AU-3 release/submission evidence manifest | After Day 13, before final submission. |
| P2 | AU-2 tamper-evident audit continuity/export | After core P0 gates; promote only if it does not destabilize the demo. |

## Do not import or add

The following historical surfaces would broaden the five-tool CloudOps agent without improving
the one approved scenario:

- patch creation, policy, apply, and post-patch test loops;
- Git read/write/commit/push automation;
- package installation;
- browser read or automation;
- MCP or coding-assistant adapters;
- multi-provider expansion, provider-agent loops, and local-agent loops;
- general async orchestration or an unbounded autonomous feedback loop;
- old UI, desktop cockpit, shell/filesystem runtime, or HackVerse legal-review prototype;
- historical source, tests, manifests, deployment files, commits, or assets.

The provider gateway/circuit idea remains concept-only. The current product has one pinned
Bedrock model and bounded typed failure behavior; adding provider selection or expansion would
weaken scope clarity. Filesystem workspace guards are likewise unnecessary because filesystem
capability is structurally `NEVER_AUTONOMOUS` and no filesystem tool exists.

## Next boundary

The next implementation package may evaluate AU-1 alongside the frozen Day 13 P0 gate. It must
not automatically implement AU-2 or AU-3, expand the tool surface, introduce a second agent, or
perform live AWS mutation. This audit itself stops at design and documentation.
