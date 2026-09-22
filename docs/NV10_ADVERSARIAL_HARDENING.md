# NV10 adversarial contracts

The NV10 suite uses controlled actors, fresh durable file fixtures and actual
disposable loopback targets. It does not spend external generation calls.
Native Cockroach pool certification is recorded separately and must never be
inferred from a file-fixture test.

## Observed expiry is durable

An expired Personal Delta consent records `expiry_observed_at` in the existing
consent record, advancing its revision and preserving the previous digest. This
only narrows consent. It does not grant consent, write a delta or alter the owner
decision. A concurrent explicit owner renewal wins over an observation bound to
an older revision. Unknown persistence remains a recovery error. A write-time
expiry is recorded after the rejected transaction has rolled back.

Service Guard records an expired or mismatched immutable approval in its existing
`blocked` phase, including denial before intent creation. A later clock rollback
or process restart cannot turn that operation into a new effect. The effect
boundary still checks current consent, target revision and the one-use token.

These barriers preserve an **observed** expiry. They cannot reconstruct an
unobserved wall-clock event when no process or durable trusted time source saw it.
Explicit revocation and source/target revision history already use durable state.
Tests change injected clocks; the host clock remains untouched.

## Formats and recovery

The native memory reader accepts `memory-patch-native-v1` only. Matching unknown
versions in two configuration fields do not select a new decoder. The existing
compact index and local target envelope retain their own strict format versions.
There is no compression dictionary in the delta/index path; tests cover its
actual typed schema, integrity digest and truncated-state boundaries.

`test_nv10_memory.py` exercises source disappearance, source A-B-A2, historical
selection, expiry/revocation, verifier conflict, poisoning and derived-state loss.
`test_nv10_guard.py` exercises target A-B-A2, foreign bindings, stale scheduler
ownership, poisoned observations/receipts, lost ACK and real process recovery.
`test_nv10_recovery.py` kills disposable child processes before commit and after
reservation, and rejects corrupted disposable checkpoints/envelopes.

The acceptance manifest also reruns existing source revalidation, bounds, native
transaction/provenance, owner isolation, provider binding and Service Guard
tests. A mandatory failure stops acceptance; full regression and package gates
must pass before a local NV10 acceptance commit. NV11 requires a new mandate.
