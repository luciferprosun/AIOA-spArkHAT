# Critical effect model — SPEC_ONLY

`ArchAIOAEffect.tla` is **UNCHECKED_BY_TLC**. Java/TLC are unavailable;
no installation, download, tool discovery or TLC run was performed. Its syntax
and correspondence were manually reviewed; tests check module structure and
named definitions only. This is not a TLC syntax check or proof.

Executable evidence comes from the standard-library Python model:

```sh
PYTHONPATH=. python3 -m lab.archaioa.effect_model
HOME=/tmp/archaioa-pre04-final PYTHONPATH=. python3 -m unittest discover -s tests/lab_archaioa -p 'test_*.py' -v
```

The exhaustive BFS reaches **166 states**, checks **336 legal transitions** and
rejects **2818 illegal action attempts**, with maximum shortest-path depth **13**
and zero invariant violations. Its deterministic graph digest is
`6b32111cdab98d7d55d1b32a8b158a6c942084ab53fefa82043e80a77d2261c4`.

## Finite abstraction and exhaustion

The model contains one task, one warrant and at most one authorized dispatch.
`effect_count` has domain 0..2 so an unsafe second dispatch is representable;
it counts dispatched effect attempts, including attempts eventually resolved as
NOT_APPLIED. It does not assert that dispatch itself proves application.
Liability is 0..1, outcomes are NONE/APPLIED/NOT_APPLIED/UNKNOWN, and phases are
the thirteen constants in Python `PHASES`. All remaining fields are Boolean.

Actions follow a forward-only phase graph. Each of the three invalidation flags
can fall once; evidence can be recorded once. The longest phase/evidence path
has ten actions: verify, require_approval, grant_warrant, record_intent,
dispatch, lose_ack, begin_reconciliation, record_evidence, resolve_applied
(or resolve_not_applied), complete. Including three invalidations gives an
upper bound of thirteen non-stuttering actions. Terminal states have no legal
successors. There is no restoration, new warrant, retry or repeated evidence
action. The default depth cap is 32; the checker actually drains its queue to
a fixed point and raises if the cap would hide any unseen state. Tests also
exhaust at 13 and reject a cap of 12.

Python uses the declared `ACTIONS` tuple order, sorted-key JSON state records,
and a SHA-256 digest of ordered states, labeled edges and rejections. Every
action is attempted at every reachable state (166 × 19 = 3154 attempts).
Rejections leave immutable inputs unchanged. Independent corrupted fixtures
exercise all six invariant predicates and counterexample trace formatting.

## Python/TLA correspondence

TLA record `s` corresponds to Python's frozen `State`; `Init` corresponds to
`State()`. Each disjunct in `Next` maps to the identically described Python
action; parameterized Ack/Commit/Resolve have separate applied/not-applied
Python labels. Record EXCEPT updates preserve all other fields, as `replace`
does in Python. TLA `Spec` additionally permits standard stuttering; Python
counts only legal non-stuttering actions. No fairness or liveness is claimed.

| Property | State predicate and transition guards |
| --- | --- |
| P1 NoEffectWithoutWarrant | Effect history requires a present, consumed warrant and authorized-consumption witness; dispatch checks current validity. |
| P2 NoWarrantReuse | Effect count must stay at most one; dispatch requires an unconsumed warrant and zero effects. |
| P3 NoAuthorityAmplification | Dispatch requires valid attenuation and records its witness. |
| P4 NoStaleEpochCommit | Dispatch and commit/resolution require current epoch and record their respective witnesses. |
| P5 NoUnknownToSuccessWithoutEvidence | After UNKNOWN, success/resolution requires evidence and an explicit APPLIED/NOT_APPLIED outcome. |
| P6 NoCompletedTaskWithOpenLiability | Completion requires zero liability and a resolved outcome. |

History witnesses retain facts at dispatch/commit even if current flags later
become false. They are generated only by guarded transitions in reachable
states; arbitrary fabricated records are not authenticated by this abstraction.
The Python boundary additionally rejects malformed states and any unsafe input
or output. TLA describes guarded reachable behavior from Init; it has no Python
exception mechanism. Reconciliation records evidence and resolves an existing
attempt, never increments effect_count or issues another dispatch. UNKNOWN
never automatically retries. Stale epochs can leave a task unable to commit;
this model deliberately makes no recovery/liveness guarantee.
