# NVIDIA Reviewer — Start Here

## AIOA spArkHAT in one sentence

**AIOA spArkHAT is a local-first long-running agent runtime that separates model
advice from execution authority, learns only verified epistemic deltas, and
survives restart/replay without duplicating guarded effects.**

This repository is intentionally broader than the NVIDIA competition demo.
For a fast review, use the path below instead of reading the historical project
documents first.

## 3-minute review path

1. **Run the deterministic reviewer preflight**
   - `PYTHONPATH=.:runtime:tests python3 scripts/nvidia_reviewer_preflight.py`
   - expected top-level status: `PASS`
   - this path is intentionally `TEST_FIXTURE`, not a LIVE-provider claim

2. **Read the reproducibility and troubleshooting notes**
   - `docs/REPRODUCIBILITY_REPORT.md`
   - `docs/TROUBLESHOOTING.md`

3. **Competition story and current gaps**
   - `docs/NVIDIA_FINAL_WEEK_GAP_MATRIX.md`

4. **Deterministic end-to-end demo source/test**
   - `scripts/nvidia_competition_demo.py`
   - `tests/test_nvidia_competition_demo.py`

5. **Human/authority boundary**
   - `runtime/service_guard/`
   - `runtime/nonzero_cloudops/`
   - `runtime/authority_timeline.py`

6. **Memory and verified learning**
   - `runtime/memory_patch/`
   - CockroachDB backend: 19 applied migrations with a READY
     `learning-v1` certificate in the certified disposable environment

7. **Critical Prompt Loop**
   - `runtime/critical_loop/`
   - exact contract: primary draft -> 3 bounded critics -> primary revision
   - critics are advisory metadata only and never gain execution authority

8. **Evidence and validation ledger**
   - `docs/NVIDIA_FINAL_WEEK_PROGRESS.md`

## Competition vertical slice

The competition trajectory is deliberately one runtime and one authority path:

```text
observe
  -> evidence / Knowledge HAT
  -> NVIDIA/Nemotron proposal (or explicit TEST_FIXTURE fallback)
  -> Critical Prompt Loop review
  -> Core authority gate
  -> AgentRuntime scheduler boundary
  -> explicit human approval
  -> Service Guard disposable effect
  -> durable receipt
  -> independent measurement
  -> durable Memory Patch / audit
  -> restart
  -> replay barrier with zero duplicate effect
```

Provider output, CPL critics, memory scores, pheromones and DVM never authorize
an effect.

## What the demo proves

The accepted deterministic competition path demonstrates:

- one `AgentRuntime`, not a second competition-only agent;
- verified correction followed by **ZERO_WRITE** reuse;
- stale evidence causing `REVALIDATION_REQUIRED`;
- one human-bound guarded effect;
- durable effect receipt;
- independent post-effect measurement;
- process restart and replay without a duplicate effect;
- explicit provider state (`LIVE`, `TEST_FIXTURE`,
  `EXTERNAL_UNAVAILABLE`, or `UNKNOWN`);
- optional CockroachDB-backed Memory Patch using the existing
  `learning-v1` schema;
- preserved UNKNOWN states rather than silently retrying ambiguous provider
  outcomes.

## Run the deterministic demo

From the repository root, with Python 3.11+:

For the fastest reproducibility check, run the one-command reviewer preflight:

```bash
PYTHONPATH=.:runtime:tests python3 scripts/nvidia_reviewer_preflight.py
```

It executes only the deterministic `TEST_FIXTURE` vertical slice and validates
the generated artifact through the same read-only projection/evaluation used
by the dashboard. Its JSON summary explicitly states that this run does **not**
validate live NVIDIA, CockroachDB, OpenRouter, or AWS.

To inspect the raw demo directly:

```bash
PYTHONPATH=.:runtime:tests \
  python3 scripts/nvidia_competition_demo.py \
  --root /tmp/aioa-nvidia-review-demo \
  --output /tmp/aioa-nvidia-review-demo.json
```

The default demo is intentionally deterministic and clearly reports
`TEST_FIXTURE`; it must never be presented as a live-provider result.

The local web console uses the same runtime:

```bash
./runtime/run_web.sh
```

Then open:

```text
http://127.0.0.1:4311
```

The competition dashboard is read-only evidence projection. Reading it cannot
approve or execute an effect.

## NVIDIA live validation

The project includes a safety-gated NVIDIA adapter for:

`nvidia/nemotron-3.5-lightning-30b-a3b`

A bounded live adapter validation has produced HTTP 200,
`finish_reason=stop`, and strict `VALID` parsing while consuming one
one-use permit and granting no effect authority.

Historical provider timeouts remain preserved as UNKNOWN evidence; they were
not rewritten to create a cleaner benchmark result.

## OpenRouter critics

CPL already supports three distinct exact-model observers through the existing
OpenRouter strict path. A prepared free-model preset exists, but LIVE execution
remains fail-closed until the operator supplies credentials, an explicit cost
policy, bounded budget, immutable plan approval and exact model identity.

See:

- `docs/OPENROUTER_CPL_3_FREE_OBSERVERS.md`

## Memory

Memory Patch is part of the same runtime, not a separate service architecture.

Reviewer-relevant properties include:

- verified-delta write;
- ZERO_WRITE when no epistemic delta exists;
- source/version binding;
- stale-source revalidation;
- owner/tenant isolation;
- CockroachDB persistence through the existing transaction ports;
- no authority granted by retrieval rank, pheromone score, DVM tier or critic
  agreement.

## Agents for Humans / Non-Zero

The integrated Non-Zero module is `CORE_NATIVE` and remains human-bound.
The competition uses its portable/local contract rather than pretending that
an un-certified live AWS backend exists.

The domain flow is:

```text
investigate -> propose -> request human approval -> record decision
-> execute approved bounded effect -> verify -> inspect evidence
```

## Endurance strategy

The competition certification uses segmented long-duration evidence:
three independently attested 8-hour windows. This is described as **3x8h
segmented endurance**, not misrepresented as one contiguous 24-hour PASS.

A contiguous 24-hour run may be attempted later as an optional gold
validation only if it does not threaten submission readiness.

## What we deliberately do not claim

AIOA spArkHAT is not:

- AGI;
- a self-authorizing agent;
- a truth engine;
- a system where model consensus becomes evidence;
- a live-AWS-certified CloudOps product;
- a claim that TEST_FIXTURE output is LIVE;
- a claim that 3x8h is identical to one contiguous 24-hour run.

## Suggested review order

For a deeper review:

1. this file;
2. `docs/NVIDIA_FINAL_WEEK_GAP_MATRIX.md`;
3. `scripts/nvidia_competition_demo.py`;
4. `runtime/authority_timeline.py`;
5. `runtime/service_guard/`;
6. `runtime/memory_patch/`;
7. `runtime/critical_loop/`;
8. `runtime/nonzero_cloudops/`;
9. `docs/NVIDIA_FINAL_WEEK_PROGRESS.md`;
10. `README.md` for the wider project history and general runtime.
