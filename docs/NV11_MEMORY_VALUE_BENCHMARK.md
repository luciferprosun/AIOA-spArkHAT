# NV11 memory value benchmark

This source-checkout CLI measures the existing memory implementation using the
repository's durable JSON fixture and a deterministic literal-context selector.
It does **not** measure a live LLM's accuracy or Cockroach performance. No provider
generation, production LIVE permit or target effect occurs. Source files under
`runtime/` remain unchanged.

Run in an isolated network namespace, with a new writable evidence directory,
Python 3.12 and this source checkout:

```sh
python -B tests/nv11_benchmark.py --root /absolute/new/disposable-state \
  --output /absolute/new/NV11_BENCHMARK_RESULTS.json --trials 8 --warm 32
```

The benchmark is a source-checkout tool: it intentionally imports existing test
fixtures. It is not an installed production command. Run with the repository's
offline test environment; real credentials are unnecessary. Existing roots and
result files are rejected. Every variant/trial runs in its own process; B0–B3
order rotates. Each trial also starts fresh processes for durable continuation
and checks revoked/expired state after restart. Child waits have finite bounds.

## Variants

| Variant | Actual composed runtime |
| --- | --- |
| B0 | Memory, CPL, Personal Delta and dynamics disabled |
| B1 | Native HAT memory; CPL/Personal Delta/dynamics disabled |
| B2 | HAT and explicitly consented verified Personal Delta; no dynamics |
| B3 | B2 plus existing controlled-corpus ACTIVE dynamics; compact index SHADOW |

B3's benchmark binding is permitted only by the existing CONTRACT_TEST boundary.
It changes no production default. Deployment status stays SHADOW: a synthetic
selector on one tiny corpus cannot justify production promotion.

Every variant receives identical queries, supplied current facts, authoritative
source bytes, clock stimuli, limits and actor implementation. B0 receives no
long-term context. The common synthetic prior is wrong about `systemctl status`;
the selector uses a relevant retrieved literal if present. This deliberately
simple task establishes data flow and overhead. It must not be generalized to
model intelligence or real user task performance. Cold versus warm quality,
repeated errors and unnecessary recalls are retained even when delta is redundant.

## Evidence and limitations

Raw JSON includes every query, expected/observed answer, selected references and
lanes, context byte units, lookup/end-to-end latency, transaction opens, explicit
revalidation, durable growth, logical delta/audit/pheromone/index bytes and RSS.
Context bytes are not billed tokens. Model calls and provider tokens are zero;
provider cost extrapolation is `COST_NOT_AUTHORITATIVELY_AVAILABLE`.

Warm p95 uses nearest rank and is suppressed below 40 observations. Eight trials
with 32 warm queries yield 256 warm observations per variant, plus controls.
Report distributions and trial medians, not statistical significance. Setup cost
includes common test scaffolding and is not a minimal production boot estimate.
Peak RSS includes fixture setup and local controls; child processes report their
own evidence. Fixture file bytes are not database pages or compression savings.

The workload covers repeated/relevant/irrelevant queries; positive and negative
synthetic history; verified correction/reuse; duplicate episodes; decay and
revalidation; source revisions/A-B-A2; revoked/expired consent and clock rollback;
foreign tenant/owner; verifier conflict; poisoned proposals; unavailable sources;
truncated persistence; and fresh-process continuation. Every destructive control
forks disposable warm state. Old accepted evidence is never touched.

Target revision and effect replay are covered by fresh existing Service Guard
regression contracts. They have no honest per-variant value estimate here: the
benchmark dispatches zero effects. Safety counters over zero dispatches are
explicitly identified. Other safety counters inspect actual forbidden reference
exposure, record authority flags, verifier results and logical duplicate writes.
Hazards are reported separately from the fixed cold/warm accuracy denominator.

## Declared comparison rule

At least four trials are required for a directional classification. For this
specific selector workload, a higher/lower success rate means BETTER/WORSE.
With equal success, lookup overhead exceeding both 1 ms and 25%, in at least 75%
of paired trial medians, means WORSE; inconsistent material overhead means
INCONCLUSIVE; otherwise SAME. Raw latency and storage deltas remain visible even
when quality wins. These labels are descriptive, not universal utility scores.

Keep the actual results outside the source tree. Targeted tests, a fresh full
regression, compile/diff/wheel/sdist/install/package gates precede acceptance.
No NV12 work is included.
