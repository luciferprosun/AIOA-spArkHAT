# Hackathon Decision Register

## D-001 — New Independent Repository

- Date: 2026-08-22
- Status: ACCEPTED
- Decision: Build the hackathon entry in a newly initialized, independent repository.
- Rationale: A clean repository creates a provable competition boundary and protects all prior work.
- Reversal condition: None during this hackathon bootstrap; any future repository-boundary change requires explicit written approval before implementation.

## D-002 — No Legacy Implementation Import

- Date: 2026-08-22
- Status: ACCEPTED
- Decision: NO_LEGACY_CODE_IMPORT = TRUE.
- Rationale: Prior projects may inform concepts, but this hackathon implementation must be newly authored.
- Reversal condition: No reversal is authorized in the current competition boundary. Any future exception must be explicitly approved and publicly disclosed before import.

## D-003 — Professional Agents Track

- Date: 2026-08-22
- Status: ACCEPTED
- Decision: Enter the Professional Agents track.
- Rationale: The project is intended to address professional CloudOps work with explicit authority and evidence controls.
- Reversal condition: Only an official eligibility or submission-rule constraint may trigger a documented track review.

## D-004 — Python

- Date: 2026-08-22
- Status: ACCEPTED
- Decision: Use Python as the implementation language.
- Rationale: Python is the planned language for the agent and deterministic application layer.
- Reversal condition: Only demonstrated platform incompatibility may trigger a documented language review.

## D-005 — Strands Agents SDK Is Structurally Central

- Date: 2026-08-22
- Status: ACCEPTED
- Decision: The Strands Agents SDK must be structurally central to the planned agent architecture.
- Rationale: The orchestration foundation must be substantive rather than decorative.
- Reversal condition: Only documented SDK unavailability or incompatibility may trigger a formal Go/No-Go review.

## D-006 — Single-Agent Architecture

- Date: 2026-08-22
- Status: ACCEPTED
- Decision: Start with a single Strands agent.
- Rationale: A single-agent design minimizes coordination ambiguity while the exact product scope is being frozen.
- Reversal condition: Later evidence must prove that one agent is insufficient before a multi-agent design is approved.

## D-007 — DynamoDB as Planned Durable Source of Truth

- Date: 2026-08-22
- Status: SUPERSEDED_IN_CRITICAL_PATH_BY_D-016
- Decision: Plan DynamoDB as the durable source of truth.
- Rationale: Durable state must be explicit and separate from model output.
- Reversal condition: A later product-scope or compatibility review must demonstrate that DynamoDB cannot satisfy the frozen use case.

## D-008 — S3 as Planned Evidence and Artifact Store

- Date: 2026-08-22
- Status: SUPERSEDED_IN_CRITICAL_PATH_BY_D-016
- Decision: Plan S3 as the evidence and artifact store.
- Rationale: Evidence artifacts require durable, inspectable storage outside transient agent context.
- Reversal condition: A later product-scope review must demonstrate a concrete incompatibility.

## D-009 — Authority Model

- Date: 2026-08-22
- Status: ACCEPTED
- Decision: AUTHORITY_MODEL = AUTO / PLAN_AND_CONFIRM / NEVER_AUTONOMOUS.
- Rationale: Every operation must have an explicit authority class; no ambiguous authorization state is valid.
- Reversal condition: Changes require explicit governance review and evidence that Non-Zero safety properties remain intact.

## D-010 — AgentCore Outside the P0 Critical Path

- Date: 2026-08-22
- Status: ACCEPTED
- Decision: AGENTCORE = NOT_ON_P0_CRITICAL_PATH.
- Rationale: P0 must not depend on an optional platform decision before the core product contract is proven.
- Reversal condition: A later documented Go/No-Go decision may add AgentCore without making the already-proven P0 path contingent on it.

## D-011 — Exact CloudOps Problem Intentionally Unfrozen

- Date: 2026-08-22
- Status: SUPERSEDED
- Decision: EXACT_CLOUDOPS_USE_CASE = NOT_YET_FROZEN.
- Rationale: The exact problem must be selected through a dedicated product-scope phase rather than invented during repository bootstrap.
- Reversal condition: Satisfied by D-012.

## D-012 — Bounded Idle EC2 Remediation Agent

- Date: 2026-08-23
- Status: ACCEPTED
- Decision: Build one bounded idle-EC2 remediation agent for exactly one allow-listed sandbox instance, with a maximum five-tool surface: `inspect_instance`, `read_utilization_metrics`, `build_remediation_evidence`, `stop_sandbox_instance`, and `verify_instance_state`.
- Rationale: The narrow workflow demonstrates professional CloudOps observation, durable evidence, explicit human authority, bounded remediation, and post-action verification without broad account authority.
- Reversal condition: Any scope or tool-surface expansion requires an explicit documented decision proving that the five-tool single-agent design is insufficient.

## D-013 — Local-First Adapter Foundation Without Tool-Surface Expansion

- Date: 2026-08-26
- Status: ACCEPTED
- Decision: Add provider-neutral `ModelProvider`, `CloudProvider`, local durable-state, `QueryResource`, and `PlanRemediation` boundaries for credential-free Phase 1 execution. These are domain/application services and do not add registered tools to the canonical five-tool Strands agent.
- Rationale: Loss of AWS access must not block contract, policy, state-machine, evidence, proposal, persistence, and approval-boundary engineering. The mock path must exercise production-intended interfaces rather than become a disposable agent architecture.
- Reversal condition: Live adapters may replace mock implementations only behind the same contracts. Any registered Strands tool expansion still requires a separate decision under D-012.

## D-014 — Local Human Authority Before Protected Mock Execution

- Date: 2026-08-26
- Status: ACCEPTED
- Decision: Complete Local-2 by persisting a server-issued approval challenge and an exact human decision before any protected mock execution. Bind the decision to run, proposal ID/hash, evidence hash, proposal version, expiry, authenticated actor session, and a one-time nonce hash. Persist idempotency ownership before execution and require an atomic receipt plus independent read-back before `SUCCESS_WITH_EVIDENCE`.
- Rationale: A visually convincing demo is not sufficient authority. The local path must prove the same ordering, replay, recovery, and verification invariants intended for a future cloud adapter while keeping every side effect inside an isolated mock state file.
- Reversal condition: A future live adapter may replace the mock executor only after separate deployment authority and account-scoped prerequisites are proven. It may not weaken or bypass any Local-2 binding or durable ordering invariant.

## D-015 — Loopback-Only Local Operator Surface

- Date: 2026-08-26
- Status: ACCEPTED_LOOPBACK_BOUNDARY_AMENDED_BY_D-017_FOR_BROWSER_SESSION
- Decision: Expose the Local-2 demo through one standard-library HTTP server bound only to `127.0.0.1`, with an owner-only bearer-token file, strict JSON and request-size handling, no CORS, hardened response headers, and a same-origin UI that retains its token only in page memory. The surface is an application boundary, not a sixth Strands tool.
- Rationale: Judges and developers need an inspectable human interaction without turning local demonstration convenience into public or cloud authority.
- Reversal condition: Any non-loopback or deployed approval surface requires a separately reviewed identity, freshness, quota, secret-management, and infrastructure decision.

## D-016 — Portable-First Product Completion With Optional AWS

- Date: 2026-09-01
- Status: ACCEPTED
- Decision: Product completion, tests, Strands execution, HITL, evidence, replay, recovery, local API and judge demonstration must run in explicit portable mode without AWS. The deterministic local Strands provider and local durable/evidence implementations are first-class. Bedrock, DynamoDB, S3, Lambda, CloudWatch and AgentCore remain preserved optional integrations and cannot be selected implicitly.
- Rationale: Missing access to an external AWS account must not block a complete Agents for Humans product. The existing Local-1/Local-2 contracts already prove the same policy, approval, durable ordering, execution binding, verification and recovery boundaries without granting cloud authority. This product-scope review satisfies the D-007 and D-008 reversal conditions for critical-path status while retaining both designs for a later authorized integration.
- Reversal condition: A future provider or deployment may be enabled only through an explicit runtime/infrastructure decision and must pass the same Non-Zero contract suite. It may not make the proven portable path contingent on AWS or weaken D-005, D-009, D-012, D-014 or D-015.

## D-017 — Judge UX Remains a Projection, Not an Authority Layer

- Date: 2026-09-01
- Status: ACCEPTED
- Decision: Promote the existing loopback Local-2 console into the primary judge-facing UX while keeping all proposal, policy, approval, execution, verification, replay, and recovery authority in existing application/domain services. Use a fragment-only raw-token bootstrap followed by an `HttpOnly`, `SameSite=Strict` browser session; retain exact Bearer support for local verification clients. Expose only a sanitized durable projection and bounded audit metadata.
- Rationale: A judge must understand and complete the product flow without terminal choreography, but presentation convenience cannot create a browser-to-executor path or leak nonce/session material. An HttpOnly session allows safe refresh/resume without persistent script-readable credentials, and the fixed intent header prevents ordinary cross-origin form submission from exercising cookie-authenticated state changes.
- Reversal condition: The UI may move beyond loopback only after a separate public-identity, origin, CSRF, quota, abuse, session-expiry, and deployment review. It may never receive direct mutation authority or bypass D-009 and D-014.
