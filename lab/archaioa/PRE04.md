# PRE-04 — Critical effect state model

This phase supplies a finite abstract safety model only. It does not execute
effects or connect authorization contracts to production enforcement.
PRE-01..PRE-03 semantics remain unchanged. Work stops before PRE-05.

`effect_model.py` provides immutable `State`, pure guarded `transition`, named
P1..P6 predicates, deterministic state serialization, shortest counterexample
trace formatting and an exhaustive breadth-first checker. Its API is imported
directly from the lab module; no package-level stable API is added.

The normal path records intent, atomically consumes the abstract warrant at
dispatch, accepts an explicit acknowledgment, commits under a current lease
epoch and completes only with zero open liability. Missing acknowledgment
creates UNKNOWN and one open liability. Reconciliation must record evidence
before resolving APPLIED or NOT_APPLIED under a current epoch; resolution
closes liability and preserves the original effect count. There is no UNKNOWN
retry, warrant replacement or duplicate dispatch.

Warrant validity, attenuation and epoch are explicit Boolean assumptions.
History witnesses record their validity at the authorized dispatch/commit;
later invalidation cannot rewrite history. `effect_count` counts attempts,
not confirmed application. The model represents a single warrant and task,
with bounded effect count 0..2 and liability 0..1. Unsafe count 2 is available
for sensitivity fixtures but unreachable through the real transition system.

## Executable evidence

The fixed point contains 166 states, 336 legal transitions and 2818 rejected
attempts, maximum depth 13, zero violations. All nineteen action labels are
attempted at every state. The finite bound and state/transition mapping are
documented in [formal/README.md](formal/README.md).

Tests require exact counts and graph digest, verify seeds 0/1/91 in separate
processes, and independently corrupt safe states to trigger exactly each of
P1..P6. Each fixture causes the checker to report a counterexample and all
actions on that fixture to fail closed. Further tests cover dispatch guards,
post-consumption replay, UNKNOWN retry, stale commit/resolution, open liability,
evidence-free reconciliation, immutable state and finite-domain rejection.

The TLA artifact is **SPEC_ONLY / UNCHECKED_BY_TLC**. Java/TLC are unavailable
on PATH; no TLC jar was found in /tmp, /usr/share or /opt. Nothing was
installed or downloaded. Manual/structural review provides
no TLC syntax validation or model-check proof. Python provides executable
bounded exhaustive evidence, not a proof about external services.

## Validation and scope

Required gates are the complete lab unittest suite under the isolated HOME,
`git diff --check`, compilation of all lab/test Python modules, changed-file
secret scan against `dd50630d0f274790143da8563884c6b439308277`, and path/import
and branch/ref audits. Only `lab/archaioa/**` and `tests/lab_archaioa/**` are
in scope. No production integration, network calls, paid calls or dependencies
are introduced. The complete suite passed: **120 PASS, 0 FAIL, 0 TIMEOUT**,
including all **107 PRE-01..PRE-03 regression tests** and thirteen PRE-04 tests.
All six independent unsafe-property fixtures were rejected as expected.
Compilation, whitespace, secret and path/import gates passed. The branch is
`nebius-personal-ai`; main and origin/main remain frozen at
`d26266e54ee940d7ada30aa02783dc697618a72c`.

## PRE-05 assumptions

Future work must separately define how a real guard establishes warrant
currency, authenticates authority attenuation, atomically consumes warrants
with durable intent and epoch fencing, and classifies acknowledgments and
reconciliation evidence. It must preserve ambiguity liability and forbid retry
without a separately justified protocol. Multiple warrants/tasks, concurrency,
crash durability, evidence trust, signatures, provider behavior and liveness
are outside this abstraction. These are future design obligations, not granted
authorization or implementation in PRE-04.
