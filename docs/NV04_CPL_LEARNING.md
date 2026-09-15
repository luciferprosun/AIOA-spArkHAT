# NV04: original CPL and native epistemic deltas

The existing `AgentRuntime` composes `LiteCPL` from a Core Python binding and an
immutable profile digest. The binding holds the existing
`CriticalPromptLoopService`; it does not create a second provider manager,
scheduler, memory engine or action executor. OFF stays the historical default.
SHADOW runs the bounded verification path without persisting knowledge. ACTIVE
requires the native memory write policy and Core MANAGE capability.

## Inference and budget

Only an admitted NV02 inference event can invoke CPL, after the NVIDIA actor's
reserved request completes. A stable probe invokes neither actor nor CPL. The
original CPL still makes exactly OpenRouter DRAFTING + three ordered critics +
REVISING calls, retaining exact model matching, cost admission, nonce use,
timeouts, cancellation and trace integrity checks. There is no provider swap.

CPL receives the actor's bounded proposal, the registered task signature,
quoted memory context and allowed verifier references. The existing SQLite
watch journal reserves all five exact OpenRouter slots atomically before any
CPL transport. These share the actor's hourly request/unit limits. An
insufficient budget admits zero CPL calls. The original live cost policy is
also required; no fixture substitutes for an unavailable live provider.

Unavailable, malformed, incomplete, unverifiable or disabled CPL is exposed as
DEGRADED/NO_CRITIC with ZERO_WRITE. Unacknowledged calls retain UNKNOWN and
block automatic reuse of the budget. No repair generation or automatic retry
is added. A learning commit with unknown outcome also requires reconciliation.

## Verified difference, not a chat transcript

The existing `CorrectionCandidate` and `CorrectionDeltaLink` define the
candidate boundary. A typed `EpistemicDelta` adds the minimal original/corrected
claim pair, exact actor attribution, model-neutral identity, HAT/task, evidence
and source versions, independent verifier receipts, status, validity, lineage,
privacy and audit timestamps. Equivalence is the existing conservative Unicode
NFC plus outer whitespace rule. It never equates different case, numbers,
negations, units or internal whitespace.

Current native scope, temporal, conflict, provenance and publication eligibility
is checked again after CPL. All registered verifier methods must support the
claim, with at least two methods and two source families. The included domain
methods are exact equality to an admitted authoritative atomic source and a
separate Core-reviewed deterministic rule, bound to task, scope, source
versions and expiry. There is no default oracle for arbitrary prose.
Signatures establish integrity; the explicit domain methods establish support.
Three correlated CPL critics contribute zero independent proofs. Agreement
score is recorded separately and grants no authority.

An already verified actor claim records ZERO_WRITE telemetry. An unsupported
revision is discarded as CONTESTED. A supported difference becomes a private
advisory delta. It does not activate a personal patch, publish canonical
evidence or issue an owner approval. TEAM/PUBLIC exist in the DTO vocabulary;
this integration's policy only writes PRIVATE records.

Model experience uses the existing `ModelExperienceEvent` and a compact overlay
containing delta reference, model identity, task/failure pattern, recurrence and
verification metadata. The delta identity and applicability exclude actor
identity; another model gets an overlay pointing to the same correction.
Episode replay and delta identity are checked inside one scoped native
transaction. No full chat or private chain of thought is stored as a delta.

## Native persistence and retrieval

`NativeLearning` is attached to the composed `MemoryPatchService` and uses its
existing `TransactionRunner`, `StoredRecord`, scope validation and revision CAS.
LEARNING is an optional native record kind; only Core MANAGE may write it.
Candidate/critic principals cannot write learning records. The storage/read
budget is explicit in `LearningPolicy` (128 records by default, maximum 512).
This is additional to NV03's source/personal read budget. Context still uses the
same bounded NV03 projection, with a distinct VERIFIED_DELTA_ADVISORY lane.
Every reuse rechecks current source versions and the independent domain rules.

The Cockroach adapter adds `aioa_memory_patch.learning_records`, with scoped
keys, canonical digest checks, FORCE RLS, HAT restrictions, PRIVATE-only and
no-authority constraints. The opt-in `learning-v1` migration profile extends
the original 18 byte-identical units with unit 19. The original default
manifest remains unchanged. The existing inspect/plan/admission/controller and
pool certificate checks must explicitly select this profile. An existing base
certificate cannot silently upgrade: a fresh admitted disposable target or a
separately reviewed upgrade is required. Startup executes no migrations.

There is no active admitted Cockroach target in this environment. SQL/live RLS
validation remains BLOCKED_EXTERNAL. Acceptance uses NV03's explicitly labeled
durable test adapter, actual native service contracts, NVIDIA transport fixture,
and the original local HTTP CPL service. It includes a separate-process restart;
neither that restart nor retrieval sends a model request or executes an action.
