# PRE-03 — Authority attenuation and decision binding

These are portable schema/property semantics, NOT production authorization.
Executable authority delegation must be meet-only attenuation: child <= parent
<= human_root. There is no join-based authority minting, sibling union/merge API,
signature, minting action, execution, effect transport or warrant consumption.
PRE-03 stops before PRE-04.

## Authority relation

`scope_contains(parent, child)` uses the existing PRE-01 `AuthorityScope.contains`
relation. `validate_attenuation` raises a typed, sanitized
`ContractValidationError` for a proposed amplification. `attenuate_scope`
computes the meet: intersect operation sets, choose the smaller risk and money
ceilings, and intersect the validity windows. It validates the result against
both inputs. An unrestricted input cannot widen the parent.

The PRE-01 schema has one exact target identifier, owner identifier, and task
identifier. Those must match; no hierarchy, wildcard, multi-target set, currency
conversion or inferred containment is supported. Currency mismatch, disjoint
operation sets and empty validity intersections fail closed. An empty meet has
no representable executable scope in PRE-01. All fields remain mandatory.

Scope APIs accept existing immutable PRE-01 values or complete versioned scope
wire dictionaries. Raw wire operation duplicates (including duplicates within
nested bounds) are rejected before normalization. Conflicting/malformed set
entries and unknown/missing fields fail closed. PRE-01's existing constructor
continues normalizing identical operation duplicates for compatibility; once a
value is normalized, its original input multiplicity is unavailable. No new
permission can result from that normalization.

`AuthorityBounds(scope, revision_policy)` makes policy explicit without changing
the PRE-01 scope schema. Both fields are required. REQUIRE <= ALLOW_UNVERSIONED;
`attenuate_authority` selects REQUIRE when either input requires it.
`validate_authority_attenuation` rejects relaxing REQUIRE. Scope-only helpers
make no revision-policy claim: callers with policy-bearing authority must use
the bounds API. These metadata values do not authorize a real effect.

## Decision binding

`decision_dependency_root` hashes only evidence selected for the decision,
including canonical evidence digest, identity, kind, source_version, valid_time
and transaction_time. It never hashes the whole HAT/task state. The caller
supplies the complete current selected evidence set, including current additions
and removals; this lab neither discovers dependencies nor retrieves evidence.

`bind_decision(warrant, selected_evidence)` binds the exact warrant_id and
operation_hash, the expected root carried by EffectWarrant, and a freshly
computed current selected DecisionDependencyRoot. Equal digests yield CURRENT;
a well-formed mismatch yields STALE. `require_current_decision` raises on STALE.
`validate_decision_binding` also rejects reuse with a different warrant_id,
operation_hash, or expected root.
Malformed/conflicting evidence fails closed with a sanitized contract error.
CURRENT means selected-root equality only, not clock freshness or overall
warrant authorization. Reordering and exact duplicates preserve the root;
changing selected evidence metadata or membership changes it. Unrelated
unselected evidence and ambient HAT-like data cannot affect it.

DecisionBinding is immutable, roundtrips through strict versioned canonical JSON,
uses the PCAF/DecisionBinding/v1 digest domain, validates state against its roots,
and rejects implicit bool coercion. AuthorityBounds uses its own
PCAF/AuthorityBounds/v1 domain. Neither contract stores private evidence payloads
or reasoning traces. All functions are standard-library only, with no hidden
clock/random/network calls or production imports.

## Property campaign and integration boundary

Seed 3003 generates 1,200 parent/restriction cases with a containing synthetic
human root, plus four chained attenuations per case (4,800 steps). Tests check
both-input containment, per-dimension monotonicity, idempotence, scope/bounds
roundtrips, all revision-policy combinations, amplification and malformed-input
rejection, sibling non-amplification, selected evidence invalidation and unrelated
state stability. Fresh subprocesses compare canonical JSON and digests under
PYTHONHASHSEED 0, 1 and 91 while blocking production/network module imports.

There is no human signature/HSM/TEE/ServiceGuard integration in PRE-03. Future
post-unlock integration must authenticate the human root and delegation chain,
preserve each attenuation dimension and explicit policy, identify the full
current selected dependency set, recompute its root before warrant consumption,
and enforce revision, lease, validity, reservations and liability constraints in
the real guard. Those integrations require separate authorization and validation;
this phase supplies no production trust, signing or enforcement mechanism.
