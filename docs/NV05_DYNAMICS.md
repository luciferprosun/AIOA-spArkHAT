# NV05: bounded memory dynamics and revalidation

`MemoryDynamics` is owned by `MemoryPatchService.learning`, composed once by the
existing `AgentRuntime`. It uses the native LEARNING repository/transactions
introduced in NV04. It creates no new database, model provider, scheduler,
process daemon, credential layer or domain action path. No dependencies or SQL
migrations beyond NV04's explicit optional native profile are added.

The Core binds `DynamicsPolicy` by digest. OFF remains the historical default.
SHADOW computes the baseline and proposed selection, returning the baseline.
ACTIVE requires matching DVM/pheromone modes, an explicitly controlled corpus,
and `MissionContext.classification=CONTRACT_TEST`. Switching from SHADOW to
ACTIVE requires a new manifest revision; the scoring policy is unchanged and
existing trail state survives. Active production retrieval is not enabled.

## Separate channels, deterministic equations

Each native TRAIL references one delta and two path hashes: the original wrong
claim and the verified correction. `tau_positive` measures usefulness of the
correction; `tau_negative` records recurrence of the original wrong path.
Neither channel is evidence, truth, consent, verification status or permission.

- Decay: `clip(tau * exp(-0.0001 * elapsed_seconds), 0, 1)` by default.
- Independently verified correction: positive `+0.2 * independence`, negative
  `+0.15`; each increment is capped at 0.25 and each channel at 1.
- Independently verified reuse: positive `+0.2 * independence`. The delta must
  have appeared in the actual actor input, and its corrected claim must pass
  the current independent domain checks. Correct answers without that context
  get no reinforcement.
- A previously seen actor family receives factor 0.25; a new family receives 1.
  Family tracking is capped at eight. CPL critic count/confidence is not used.
- Same delta + episode + actor/source family + signal is idempotent. Different
  policy content under an existing event identity is a conflict.

Every numeric change atomically stores a PHEROMONE_EVENT and revised TRAIL:
old/new tau, reason, elapsed time/rate, exact evidence/source versions, actor
family, source-family digest, independence, timestamp, policy and previous-event
reference. Decay below one second is deferred without changing stored tau.
Negative elapsed time and non-finite/out-of-range numbers are rejected.

Recall salience is `relevance * affinity * quality * freshness * (1 + tau+ +
tau-)`. The separately reported hypothetical bad-path desirability is
`0.1 / (1 + tau-)^2`. Thus negative tau increases recall and suppresses the bad
path. Actual action desirability is always multiplied by the disabled effect
policy and is zero; a score never calls an executor.

## DVM moves references

Eligibility always runs first: native owner/HAT, publication/provenance,
temporal freshness, conflict/supersession, current source versions, delta
status, independent re-verification and pending revalidation obligations.
Scoring receives only that eligible set. The context budget accepts only a
permutation of eligible references, preventing a scorer from adding a record.

| Tier | Reference policy |
| --- | --- |
| DEEP | Verified deltas and model experience; initial correction tier. |
| HOT | At most two eligible task-matched references that actually fit the current context. |
| WORKING | Pending critical-age rechecks; excluded from factual reuse until resolved. |
| ARCHIVE | Ineligible/superseded/conflicting basis retained for audit. |

The score exposes lexical relevance, the Core-bound recurring-task match,
model-family affinity, tau, evidence quality and freshness. Task risk matching
sets a relevance floor of 0.75 inside this one registered task; it is not an
unscoped semantic search. Default HOT threshold is 0.75. A context that cannot
fit a HOT reference demotes it to DEEP. TIER_EVENT records each active change.
SHADOW exposes baseline/proposed selections without changing actual tiers.

The same NV03 whole-record/UTF-8 framing budget limits final context. Knowledge
is not duplicated between tiers. The existing LITE provider accounts for the
assembled input before reserving its request. Stable heartbeats read neither
memory scores nor models. No performance or real LLM accuracy improvement is
claimed from the controlled fixture.

## Durable revalidation work

A DEPENDENCY links each delta to its exact source versions and evidence. A
changed/missing/withdrawn/conflicting/stale source, an ineligible delta, or the
default 300-second critical recheck deadline creates an OPEN OBLIGATION. It
contains subject, dependencies, old/current source versions, owner, reason,
next check, deadline, last verification, policy, watch and task identifiers.

The delta's adjacent `reuse_status` becomes REVALIDATION_REQUIRED. Historical
verification stays visible while current reuse is denied. The flag survives
restart and cannot be removed by high tau, normal retrieval or repeating the
same correction. Repeated observations do not duplicate the obligation.

`MemoryDynamics.revalidate` is an explicit Core operation, not a model tool or
heartbeat action. It reruns current independent verification. An unchanged
basis can resolve an age obligation; a changed version requires a separately
verified replacement delta. Resolution, supersession links and a
REVALIDATION_EVENT are committed atomically. It issues no approval, executes no
action and deposits no reward. The three-run demo intentionally leaves the
changed-version obligation OPEN because the independent oracle still binds v1.

All dynamics records share the Core-scoped native storage budget (default 128
learning records). At the bound, writes stop rather than silently deleting
history. Production Cockroach/RLS validation remains BLOCKED_EXTERNAL; the
durability tests use NV03's labeled native-port test adapter.

## Controlled three-process evidence

`tests/nv05_demo.py --root <fresh-test-directory> --run 1|2|3` provides JSON
evidence from three separately launched Python processes:

1. Wrong actor claim -> actual NVIDIA adapter fixture -> original five-call CPL
   HTTP fixture -> independent evidence/oracle -> one delta and both tau channels
   stored in DEEP.
2. Same stored delta is retrieved after restart, promoted to a bounded HOT
   reference, and appears in the actual actor input. The deterministic actor
   fixture returns the correct claim only when that reference is present.
   Verification gives ZERO_WRITE plus a verified-reuse event.
3. Explicit source v2 supersedes v1. D1 becomes REVALIDATION_REQUIRED; an
   obligation is durable, D1 is absent from actor input and no new delta is
   created from insufficient verification. All runs have AUTO disabled and
   zero domain mutations.

The fixture proves integration/data flow, not real model learning. Tests also
cover scoped privacy, caps/decay/correlation, stale/withdrawn/conflicting and
superseded data, recheck deadlines, demotion/budgets, and native owner-text
prompt injection surviving restart without changing authority.
