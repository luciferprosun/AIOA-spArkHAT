# AIOA spArkHAT — Roadmap History and Gap Analysis

Date: 2026-09-22

Branch: `codex/nvidia-final-week-20260921`

Frozen certification baseline: `ad4a425714a764f61f5ff22f2cc59f18abc36984`

## Reconstruction rule

Only Roadmap **2.1** is explicitly versioned in the surviving NV documentation (`docs/NV08_COMPACT_PHEROMONE_INDEX.md`) and now has a formal closure document. The labels **1.0** and **2.0** below are reconstructed historical phases from Git anchors, docs and tests; they are not retroactively asserted as contemporaneous signed release names.

The reconstruction uses capability boundaries rather than dates alone: Core authority/provenance foundation → NVIDIA one-system composition foundation → personal/recovery/effect/adversarial/final-certification closure.

## Version comparison

| Reconstructed version | Evidence anchors | Capability boundary | What was still missing at that boundary |
| --- | --- | --- | --- |
| 1.0 — Core-first certified baseline | `d7e3448` scope-boundary baseline; `be16267` pre-NVIDIA M2 repaired checkpoint; `796d681` certified inert NVIDIA foundation; `360e900` Memory Patch hackathon jury final | Single Core authority, provenance/containment, hardened runtime foundations, HAT/Memory Patch lineage, inert NVIDIA boundary | No admitted NVIDIA/LITE mission path, no composed CPL learning loop, no DVM/pheromone runtime contract, no final competition effect/receipt trajectory |
| 2.0 — NVIDIA composition foundation | `38df1c3` NV01; `88733b7` NV02; `a51a93f` NV03; `9614dea` NV04; `f994ca4` NV05 | Controlled mission contracts, bounded NVIDIA provider, native Memory Patch composition, original CPL/verified deltas, bounded MemoryDynamics/revalidation | Personal-delta consent contract, restart-safe private correction, compact index/live separation, guarded effect receipt, adversarial recovery matrix, value benchmark and final NV12 recert/endurance |
| 2.1 — closure line | `fa612a1` NV06; `426cba4` NV07; `72d78ad`/`f19b89e` NV08; `0360a7c` NV09; `9c1c39b` NV10; `834e7dc` NV11; frozen `ad4a425` NV12; closure `3d28896` + `4c61ee4` | Personal verified-delta consent, private correction/restart reservation, SHADOW compact index, Service Guard effect/receipt/verification, adversarial crash/replay/UNKNOWN hardening, benchmark, provider repair and segmented endurance closure | Original contiguous 24 h remains unclosed; external provider availability risk remains; OpenRouter LIVE and AWS LIVE remain blocked by operator policy; DVM/index stay SHADOW |

## Roadmap 1.0 — reconstructed baseline

The earliest stable line already established the architectural rule that infrastructure authority belongs to Core, not to model/provider output. Historical hardening also established containment, source/provenance boundaries and deterministic local state. The pre-NVIDIA checkpoints show that NVIDIA integration was initially inert by design rather than an authority-bearing runtime path.

The Memory Patch jury tag (`hackathon-jury-final-2026-08-15`, commit `360e900`) proves a separately hardened durable-memory lineage before the September NVIDIA roadmap. That history matters because Roadmap 2.x composes existing memory contracts rather than inventing a new store.
### 1.0 → 2.0 gap that was actually closed

- NV01 added controlled mission contracts and side-effect-free diagnostics instead of letting provider output enter Core directly.
- NV02 added the read-only LITE runtime and bounded NVIDIA adapter.
- NV03 composed the existing scoped Memory Patch into LITE.
- NV04 composed original CPL with independently verified epistemic deltas; critics remained advisory rather than evidence.
- NV05 added audited dual pheromone signals, DVM selection and durable revalidation, with OFF/SHADOW defaults and tightly bounded CONTRACT_TEST ACTIVE behavior.

The resulting 2.0 boundary was materially more than “provider integration”: it made NVIDIA one participant in a Core-governed system while preserving memory, provenance and authority separation.

## Roadmap 2.0 — reconstructed NVIDIA foundation

Evidence is strongest from the NV01–NV05 commits and dedicated tests: `test_nv01_*`, `test_nv02_*`, `test_nv03_memory.py`, `test_nv04_learning.py`, `test_nv05_shadow.py` and `test_nv05_active.py`.

The main unresolved gap after NV05 was operational closure. The system could observe, propose, verify and learn, but it still needed a complete personal/private correction path, explicit long-running guarded effect semantics, stronger crash/replay/UNKNOWN contracts, measurable memory value and a final provider/endurance recertification story.

### 2.0 → 2.1 gap that was actually closed

- NV06 added owner-scoped personal verified-delta consent, secret checks, bounded storage and one-repair budget semantics.
- NV07 closed the private correction loop with durable restart-safe repair reservation and owner isolation.
- NV08 added a compact owner-scoped pheromone index as a derived SHADOW projection and kept live Cockroach evidence separate from fixtures.
- NV09 added the disposable Service Guard effect path with exact human approval, single-use authorization, durable receipt, independent measurement and replay-safe reconciliation.
- NV10 hardened expiry/revocation, stale targets, poisoning, corrupt persistence, process crash/recovery and UNKNOWN preservation.
- NV11 added a reproducible B0–B3 benchmark without claiming live-LLM intelligence gains or production promotion.
- NV12 repaired the NVIDIA adapter, preserved historical UNKNOWN outcomes, recertified offline safety and exercised the final scenario/endurance closure path.
## Roadmap 2.1 — explicit closure state

`docs/ROADMAP_2_1_CLOSURE.md` is the authoritative competition-branch summary of NV01–NV12. It keeps NV05/NV08 SHADOW, records NV12 as `PARTIAL` relative to the original contiguous-24-hour contract, and accepts the replacement endurance result only as `SEGMENTED_ENDURANCE_PASS`.

The accepted segmented evidence is 28,898.455834 s + 28,909.535110 s + 29,029.012337 s = 86,837.003281 attested active seconds, with zero recorded downtime on the frozen SHA. This closes the replacement endurance requirement without falsifying the historical interrupted trial.

## Final-week competition overlay after 2.1

The current competition branch adds presentation/integration hardening, not a new authority architecture:

- one deterministic 14-stage trajectory from observation through receipt, independent verification, durable memory and restart recovery;
- Authority Timeline and competition evaluation as read-only projections;
- a bounded Cockroach `learning-v1` memory composition while retaining repository-durable `TEST_FIXTURE` fallback;
- fail-closed OpenRouter CPL preset configuration without LIVE calls when the key/policy/budget gate is absent;
- Non-Zero readiness/approval/receipt alignment as a read-only projection, with Service Guard remaining the sole effect executor;
- DVM/pheromones explicitly fail-closed to SHADOW for competition evidence;
- one-command deterministic reviewer preflight.

## Remaining gaps after 2.1

| Gap | Current state | Submission impact | Required action before freeze |
| --- | --- | --- | --- |
| Original contiguous 24 h NV12 | Not passed; historical contract remains false | Must not be overclaimed | Keep `SEGMENTED_ENDURANCE_PASS`; optional future Gold Test only on final frozen candidate |
| Hosted NVIDIA availability | Adapter recovered and separate live evidence exists, but historical timeout risk remains | Demo may lose hosted inference temporarily | Preserve deterministic fallback and explicit LIVE/TEST/UNAVAILABLE labeling |
| OpenRouter LIVE CPL | `BLOCKED_EXTERNAL` by absent key/policy/budget authorization | No LIVE multi-observer claim yet | Do not call until operator explicitly authorizes; local exact-model fixture is sufficient for deterministic demo |
| Live AWS Non-Zero | Disabled/un-certified | No AWS execution claim | Keep readiness/contract alignment only; do not create second executor |
| DVM/pheromone promotion | SHADOW | No autonomous ranking authority claim | Keep SHADOW for submission |
| Compact index promotion | SHADOW | No production ordering claim | Keep derived/read-only semantics |
| Cockroach evidence scope | Competition learning-v1 path has live evidence; fixture path remains separate | Risk of misleading storage claims | Always expose exact backend used |
| Reviewer reproducibility | One-command preflight exists and passes | Low remaining risk | Rehearse fresh-clone/install and package only; no new runtime architecture |

## Decision

There is no evidence-backed reason to create Roadmap 2.2 before the NVIDIA submission. The highest-value path is to freeze architecture, audit authority/replay/evidence/privacy boundaries, rehearse reproducibility and package the existing one-system vertical slice. New Core, scheduler, executor, memory engine or DVM promotion would increase risk without closing a current evidence gap.