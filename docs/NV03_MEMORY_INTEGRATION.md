# NV03: explicit Memory Patch composition in LITE

`runtime.main.create_runtime` still creates one `AgentRuntime`. Its LITE branch
now composes the existing `MemoryPatchService` only from
`CoreLiteMemoryBindings`, with a matching immutable `LiteMemoryProfile` digest
in `LiteProfile`. Historical runtimes remain disabled. No action executor,
NonZero execution service, migration or provider credential discovery is added.

## Composition

`LiteMemoryProfile` binds OFF/SHADOW/ACTIVE, the complete owner scope, HAT,
backend identity, schema version, Core evidence/publication policy, native
temporal policy, an exact freshness policy reference, write policy and budgets.
`CoreLiteMemoryBindings` supplies the already-admitted Core, immutable owner
assignment, `CoreMemoryPatchDependencies` and existing HAT selection.

ACTIVE without matching bindings/digest is rejected. OFF opens no memory
backend. SHADOW computes and records candidate context while keeping the
actor's input unchanged. ACTIVE injects bounded quoted context only on an
observation event. Stable heartbeat probes never read memory or invoke a model.
Missing dependencies produce DEGRADED; active inference abstains instead of
silently pretending that memory was consulted.

The existing factory's inspection guard remains on legacy execution, approval,
assistant and NonZero endpoints. The explicit
`AgentRuntime.lite_memory_operator_request` permits only the native memory
lifecycle, requires the configured write policy and existing Core capability,
and is never called with generated actor/critic output. Sharing, migration and
domain actions are excluded. Native owner approval, separate commit/activation
and append-only provenance remain mandatory for personal memory activation.

## Eligible context before relevance

The LITE source port adds `scan_scope(principal, hat_id, limit)`. It receives no
query or vector and must scope the scan before its limit. A legacy pre-ranked
source port cannot substitute for this capability. LITE does not enable vector
similarity or install an embedding model.

1. Validate Core tenant/owner/space/slot and HAT; reject an out-of-scope port result.
2. Exclude unpublished sources. Wrap each source independently in existing
   evidence DTOs; their constant one-item contribution is identity framing, not
   query relevance or a source ranking.
3. Resolve native applicability, freshness, supersession and material conflicts
   over the bounded full candidate set.
4. Require the exact Core source bytes, evidence publication and registry binding.
5. Read eligible personal records through `NativeMemoryRetrieval` and existing
   activation, temporal and provenance checks. The remaining candidate read
   budget caps this scan; the legacy 1023-record limit remains its default.
6. Apply local lexical relevance and fit complete references/claims into the
   context budget. No truncated claim is turned into a new asserted fact.

The context preserves separate canonical evidence and owner-context lanes,
evidence references, source versions, record revision and validity. Owner text
is not canonical evidence. Every context reference has immutable
`execution_authority=False`. The source bundle remains internal; the model
gets only the bounded selected projection.

The read budget defaults to 40 source/personal candidates combined. Overflow of
the source scan or remaining personal scan returns an explicit denial instead
of ranking a silently truncated pool. The context defaults to eight records and
1024 conservative UTF-8 byte units, including JSON framing and references.
These units bound context size; they are not measured tokenizer usage. Provider
input estimation includes the assembled context before reservation/transport.

## Backend and durability evidence

Production ports remain the existing Cockroach transaction factory and the
18-unit `aioa_memory_patch` migration contract. NV03 adds no database engine,
SQL schema or package dependency. Constructors never connect to a database or
apply migrations. Configuration means CONFIGURED_UNPROBED until a read succeeds.

This environment's preserved certification cluster is stopped and has no
active handed-over test target. Live Cockroach validation is
`BLOCKED_EXTERNAL`. It must not be inferred from the contract tests.

`tests/nv03_support.py` explicitly extends the repository's native `FakeFactory`
with bounded canonical StoredRecord JSON, OS file locking, atomic replacement
and fsync. The fixture exercises the real service, Core publication and native
lifecycle in separate fresh Python processes. It is test support, is never
constructed by production and is not a substitute claim for SQL/RLS validation.

Tests cover OFF/SHADOW/ACTIVE, approved native writes, actual process restart,
four scope dimensions, stale/future/revoked/conflicting/superseded evidence,
read and context budgets, idle zero calls, context included in provider budget,
malformed authority fields and prompt-injection persistence without authority.
No cloud or consequential action is executed by these tests.
