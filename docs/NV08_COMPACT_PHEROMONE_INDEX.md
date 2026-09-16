# NV08 — compact pheromone index and Cockroach live separation

Roadmap version: **2.1**.  This document is the pre-code component map and the
local acceptance boundary for NV08.

## Start anchor and environment

- Accepted `START_SHA` / `NV07_SHA`:
  `426cba4a2f3cf0b4ebd6110e4f641fe5cc9d5e90`.
- Branch: `codex/nv06-nv07-0ngbrvyp`.
- Initial worktree: clean.
- Accepted preceding gate: `G07_CONTRACT=PASS`; the preceding live claim stays
  `G07_LIVE=BLOCKED_EXTERNAL` and `G07_LIVE_CALL=NOT_RUN`.
- Runtime discovered locally: CPython 3.12.3 and setuptools 68.1.2.  The project
  has no mandatory third-party runtime dependencies.  Optional locked profiles
  in `pyproject.toml` are `psycopg[binary]==3.3.5`, `pydantic==2.13.4`, and
  `uuid6==2025.0.1`; none is installed in this worker environment.
- No `AGENTS.md` exists in the worktree, its checked parents, the result
  directory, or the accepted Git tree.  The injected `.agents` directory is
  empty.  Session and verified-PDF constraints therefore remain the applicable
  instructions.
- The worker explicitly forbids network use, secrets, apps/MCP, and real
  resource mutation.  No Cockroach credentials/profile were provided.
  Consequently the local gate and live gate are separated:
  `G08_DB_LIVE=BLOCKED_EXTERNAL`, never fixture-derived PASS.

## Existing component map and exact gaps

| Requirement | Existing authoritative component | Exact NV08 gap | Local/contract test mapping |
| --- | --- | --- | --- |
| One scoped durable memory system | `MemoryPatchService` owns `TransactionRunner`; `NativeLearning` stores DELTA, OVERLAY, EPISODE, TRAIL, DEPENDENCY, OBLIGATION, and pheromone events as `RecordKind.LEARNING` | No compact, inspectable candidate index derived from those accepted records | `test_nv08_index`: derivation, scope, bounds, deterministic digest |
| Transaction boundary | `TransactionRunner.run` opens one scoped transaction, rechecks Core admission, commits once, rolls back/closes on every path, retries only structured serialization failures, and treats unknown commit as unknown | Index behavior must not add a transaction/effect path or blind UNKNOWN retry | transaction/unknown/replay tests plus inherited persistence tests |
| Cockroach persistence | `CockroachTransactionFactory` plus `ScopedSQLRepository`; `learning_records` in optional migration 0019 | No permitted live profile in this run; local fixtures cannot certify Cockroach | static/local adapter contract tests; live cases explicitly NOT_RUN/BLOCKED_EXTERNAL |
| Database-side isolation | Complete tenant/owner/space/slot predicates, Core context ticket, application role checks, FORCE RLS and HAT policy on `learning_records` | Demonstrate that index input/output cannot broaden the already scoped candidate set | two-owner shared-store read/score/log/export-style projection test; SQL manifest assertions |
| Idempotency and replay | DELTA identity excludes actor; EPISODE and PHEROMONE_EVENT IDs are canonical hashes; duplicate reads precede writes | Need index replay equivalence and proof that replay creates no second delta/reward/index artifact | duplicate replay and fresh-process tests |
| Existing HOT/WORKING/DEEP/ARCHIVE and dual tau | `MemoryDynamics` eligibility, revalidation, tau update, scoring, tier events | Need a compact bounded view without replacing tiers, tau, or full eligibility | stale/revoked/high-score test; shadow-only ordering comparison |
| Verification and conditions | `EpistemicDelta` retains status, evidence refs, source versions, verifier receipts, validity, policy digest, semantic kind and required condition | Compact representation must retain the condition and verification metadata and must still dereference the full admitted delta | indexed-metadata preservation and full-reference equivalence test |
| Context bounds | `budget_context`, `LiteMemoryProfile` (40 read, 16 context maximum; deployed defaults remain smaller), whole-record UTF-8 framing | Need measured before/after shadow selection and explicit candidate-scan counts | bounded synthetic set and measurement artifact |
| Cache path | `NativeEmbeddingCache` uses an explicitly injected owner-bound `DerivedCachePort`; a cache has no source/approval authority | Index must not use cache contents as eligibility or expose another owner's score | owner isolation test; index is rebuilt only from scoped eligible durable records |
| Export path | `PersonalMemoryManagement.export_snapshot` is owner-MANAGE only; the learning lane has no export operation | Need show index diagnostics contain only the current scope and no new export bypass | owner isolation/projection test; no index export API is added |
| Audit/provenance cost | EPISODE and PHEROMONE_EVENT remain native append-only advisory records; `storage_metrics` counts canonical logical bytes | Need index bytes/entry, durable minimal-delta bytes and audit/provenance bytes | reproducible measurement runner and JSON evidence |
| Pool reconnect/non-admin/live crash matrix | Existing Cockroach pool validates session identity, non-admin role, schema certificate, RLS and resets context before reuse | Requires real Cockroach and an explicitly allowed isolated profile | `G08_DB_LIVE=BLOCKED_EXTERNAL`; no SQLite/file fixture is relabeled live |

## NV08 design boundary

The smallest index is a deterministic, owner-scoped **derived projection** of
full DELTA and TRAIL records that already passed current source, evidence,
validity, consent, policy, and independent-verifier checks.  It is not a second
store: a fresh process reconstructs it from the same durable accepted records.
It retains bounded verification metadata and the required semantic condition,
but it can only return a permutation/subset of the already eligible references.
Every returned reference is dereferenced to the complete record before context
assembly.  Scores remain advisory and cannot create evidence, consent,
ownership, publication, or execution authority.

The index mode is fixed to `SHADOW` for NV08.  Its proposed order and compact
context measurements are observable, while the accepted NV05 DVM order remains
the actual order.  No Roadmap-v2.1 condition authorizing ACTIVE index behavior
was supplied, so ACTIVE index composition is rejected rather than inferred.

Bounds are additions below existing historical ceilings, not raised ceilings:
at most 32 compact entries and at most 16 query candidates are scanned.  Source
learning-record scans retain the existing maximum of 128 and memory retrieval
retains the existing maximum of 40.  Stable ties use the canonical delta ID.

## Gate semantics

`G08` covers local deterministic contracts, isolation, replay/fresh-process
equivalence, bounds and reproducible logical measurements.  It may pass with
`G08_DB_LIVE=BLOCKED_EXTERNAL`.  `G08_DB_LIVE=PASS` requires a later explicitly
authorized real Cockroach run covering commit/rollback, concurrent dedup,
crash boundaries, restart, RLS, non-admin role, pool reconnect, cache/export
isolation and replay.  File fixtures and SQLite are never live evidence.
