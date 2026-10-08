# Restricted formal and native fault evidence

PRV: the original explicit checker still exhausts 166 states with digest
`6b32111cdab98d7d55d1b32a8b158a6c942084ab53fefa82043e80a77d2261c4`.
The new restricted product exhausts 548 states, 1875 transitions, 10729 rejected
attempts, depth 15, with zero violations; digest
`f6e6a23515caffd592d6c16a3b7b2b7243aa66caf39b410544f7994a3cc28f9e`.
BFS attempts every action at every state and fails on incomplete depth cutoff.
Symbolic money/risk are paired finite 0/1 units, not prices or probabilities.
Warrant, current epoch, evidence and immutable durable history are abstract
assumptions. This is not a production/distributed/cryptographic/liveness proof.
No runtime imports this lab model. TLA+ remains SPEC_ONLY, not TLC-checked.

PRV: 28 checker/fault unit tests and 173 native fault regressions PASS, with explicit
30/240-second process bounds. The native matrix includes actual process crash,
intent/lost ACK and target receipt recovery, lease takeover, clock skew, corrupt
checkpoints/receipts, source/owner mismatch, revoked/expired approvals, kill,
provider mismatch/timeout and receipt/settlement ambiguity. Ambiguity holds
liability and does not cause blind redispatch. No external effects or provider
network are permitted in the fixture network namespace.

64 fresh native-store cases, seeded four-mode selections, completed in 7.62 seconds
without timeout/failure/duplicate dispatch permission. They are distinct fixture
cases, not proven independent world failures. Under an explicitly hypothetical iid
fixed-distribution Bernoulli model only, zero failures in 64 gives the one-sided
95% upper bound `1 - 0.05**(1/64)` (about 4.57%). No generalization or zero-risk claim.

Review: Critical 0, Important 0, Minor 2. Open minor model-hardening items: an
unreachable malformed zero-charge RESERVED initial state is not separately
classified; a focused reserve-under-kill test could strengthen guard coverage.
Dispatch remains denied in those zero-charge/killed cases. Initial namespace/import
FAIL evidence and its minimal alias repair are retained outside Git.

Historical 3x8 endurance seal has five hash mismatches: BLOCKED_EVIDENCE, cause UNK.
This new run does not repair or replace that historical seal. Exact gates, logs,
case counts, manifest and rollback are under the current external phaseF bundle.
