# GOLD24: What We Learned from a 24-Hour AIOA spArkHAT Endurance Run

*Engineering update · 14 October 2026 · AIOA spArkHAT*

> **Headline:** A local GOLD24 endurance run on 28–29 September 2026 reported **86,426 active seconds** and **722 checkpoints**. We later rechecked every checkpoint's SHA-256 digest and all 721 predecessor links. This was a *local resilience and checkpoint-integrity milestone*, **not** 24 hours of live NVIDIA inference, a replay-attack stress test, or third-party certification of the current repository.

## Why we ran it

A useful AI agent needs more than a convincing answer. It needs to survive time, interruptions and uncertainty without treating its model's advice as permission to act. We are building **AIOA spArkHAT**, a modular, open-source, *human-governed* agent runtime. We separate provider output, evidence, approval, execution and verification.

Our research spans four hackathon tracks that became modules of one system: **Critical Prompt Loop (CPL)**, **Memory Patch/CockroachDB**, **Non-Zero action controls**, and **NVIDIA/GO24 resilience experiments**. Optional Nebius/NVIDIA provider integration sits behind explicit policy. An unattended, arbitrary browser/desktop WRITE or EXEC agent is **not** a product capability we are claiming here.

The specific GOLD24 question was narrower: *Can our local runtime maintain its supervised state and produce an internally consistent, inspectable sequence of checkpoints for at least 24 hours?*

## Run card

| Field | Value and interpretation |
| --- | --- |
| Test profile | Local `STRICT_ENDURANCE` |
| Run ID | `gold24-20260928T041316Z` |
| Started / ended (UTC) | 28 Sep 04:13:17 → 29 Sep 04:14:05, 2026 |
| Reported wall-clock elapsed | **86,448 s** (24 h 48 s) |
| Reported active time | **86,426 s** (24 h 26 s) |
| Final report status | `GOLD24_PASS` (harness's own classification) |
| Numbered checkpoints | **722**, from `000000` through `000721` |
| Independently recalculated checkpoint digests | **722 / 722** matched |
| Verified predecessor links | **721 / 721** matched |
| Reported duplicate effects / replay redispatches | **0 / 0** |
| Replay attempts in this run | **0** — so this does *not* demonstrate fault-injection/replay-attack resistance |
| Supervisor cadence | 120-second heartbeat, 300-second lease TTL as specified in the run manifest/harness |
| CockroachDB requirement | `READY` as reported by the harness |
| Fresh-process reconstruction | `VERIFIED` as reported by the harness (not reproduced by an outside auditor) |
| NVIDIA live integration | **Unavailable; live probe disabled** |
| Exact historical candidate commit | `2b0443fe1e60b8497da1923b7fc860f6c2f8c5cb` — **not presently resolvable in canonical public GitHub** |

The harness and report refer to an operator-authorized, local test. These numbers are **not** benchmarks of tokens/sec, autonomous work completed, production uptime, hosted deployment or live model response quality.

## What we checked afterwards

On 13 October we inspected the retained local run data. Our read-only verification:

1. Enumerated **722 JSON checkpoint files**, ensuring a complete `000000..000721` sequence.
2. Recalculated SHA-256 over each canonical, sorted, compact JSON object *without* its `checkpoint_digest` field, and matched the recorded digest.
3. Matched all **721 `previous_checkpoint_digest` links** against the preceding checkpoint.
4. Confirmed every checkpoint retained the same run ID, source commit hash and harness hash.
5. Checked nondecreasing reported active-time counters, the final active-time value and the final checkpoint digest against the report.
6. Confirmed the archived harness SHA-256 matched the harness digest recorded by the run.

That is useful **file-chain consistency evidence**. It is not an external attestation of physical wall-clock continuity, database persistence under all failure modes, or correct behavior during real-world effect execution. Checkpoint hashes also cannot establish that an absent replay attack was resisted.

For an overview of the evidence and exact SHA-256 fingerprints, read the **[GOLD24 local evidence review](../launch/GOLD24_LOCAL_EVIDENCE_REVIEW_20261013.md)**.

The open-source [read-only verifier](../../scripts/verify_gold24_chain.py) accepts a path to the retained run bundle:

```bash
python3 scripts/verify_gold24_chain.py /path/to/gold24-20260928T041316Z
```

The full historical checkpoint dataset has **not yet been released**, pending privacy, licensing and source-provenance review. Publishing a checker is **not** the same as publishing independently reproducible evidence.

## What GOLD24 did *not* prove

We prefer explicit boundaries to inflated metrics:

- **No live NVIDIA workload:** the manifest records `nvidia_live_probe: false` and final report `nvidia_gate: UNAVAILABLE`. Neither NVIDIA nor any other external provider certified this run.
- **No replay-attempt stress campaign:** there were **zero replay attempts**. The zero-redispatch count is an observation, not a proof that every replay would have been prevented.
- **No verified 24-hour stream of approved external actions:** the run primarily exercised the supervisor, state and checkpoint loop; it does not demonstrate 24 hours of completed customer tasks.
- **No independent reproduction of the original candidate source:** the historical tested commit is absent from public canonical GitHub as checked on 13 October.
- **No blanket certification of today's `main`:** this was a historical candidate/configuration, not an acceptance test for every later commit.
- **Not the same as our earlier segmented endurance evidence:** the older [3 × 8-hour manifest](../../reports/SEGMENTED_ENDURANCE_3X8_MANIFEST.json) correctly remains `SEGMENTED_ENDURANCE_PASS` with `contiguous_24h_pass_closed: false`. The GOLD24 local report is a later, separate run.

## Why the architecture matters

```text
Task from the human operator
        ↓
Optional LLM / provider (ADVISORY ONLY)
        ↓
CPL + evidence / provenance checks
        ↓
Human authorization + Non-Zero gate
        ↓
ServiceGuard (bounded effect)
        ↓
Independent readback + durable receipt
        ↓
Restart/recovery logic (check before redispatch)
```

The distinction between **model advice** and **authority to act** is our fundamental design choice. AIOA's remote MCP/GitHub task-bus transport remains constrained to **bounded READ** without a separate human-approved WRITE/EXEC pathway. The GOLD24 endurance run studied only part of this broader architecture.

## Next experiments and open questions

Our follow-up work prioritizes four independent proof gates:

1. **Reproducibility:** recover the exact historical candidate, preserve its source and publish a privacy-reviewed, SHA-bound evidence bundle and verifier output.
2. **Replay and crash injection:** intentionally interrupt runs at selected receipt/write boundaries, then demonstrate no accidental duplicate effect, with negative cases preserved.
3. **Real-world state and provider boundaries:** independently test database recovery and bounded live inference, including outages, token budgets, wrong-provider answers and human-denied actions.
4. **Current-main recertification:** repeat a clearly specified acceptance suite against a public release/tag rather than projecting old test evidence onto new code.

## An open request for collaborators and hardware support

We are doing this as independent, resource-constrained open-source research. Much of our development has happened on a modest Linux computer with **4 GB RAM**, which limits the experiments we can run locally.

We would especially appreciate **donated or loaned Linux-compatible hardware, more RAM/SSD storage, GPU or inference time, cloud credits, and independent reviewers** who can scrutinize our design and reproductions. We're particularly interested in input from reliability engineers, security researchers and developers working on long-running agent systems.

- **Project / demos:** https://sparkhat.eu/aioa/
- **Canonical source:** https://github.com/luciferprosun/AIOA-spArkHAT
- **NVIDIA Claw Challenge demo:** https://youtu.be/ABJijoNKmYM
- **Technical GOLD24 evidence and limits:** [evidence review](../launch/GOLD24_LOCAL_EVIDENCE_REVIEW_20261013.md)
- **Equipment or research support:** https://sparkhat.eu/sponsorship/

**What would you test next?** If you can identify a flaw in our assumptions, propose an adversarial recovery scenario, help publish independently verifiable artifacts, or provide modest computing resources, we'd value the conversation.

*This is a research-stage engineering report. It does not claim a hackathon prize, NVIDIA endorsement, verified production SLAs, or universal agent safety.*
