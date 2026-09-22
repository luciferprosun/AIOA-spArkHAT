# NLnet Reviewer — Project Context and Repository Guide

**Project:** AIOA spArkHAT (formerly AOIA-Core)

**Date:** 2026-09-22

**Repository role:** canonical integrated runtime and reviewer-facing engineering history

## Publication status

This reviewer guide is being prepared on the local integration/competition branch before controlled consolidation. It does **not** claim that the remote default branch already contains every change documented here. Public merge/push/tagging remains a separate operator-approved release step.

## Executive summary

AIOA spArkHAT is one local-first runtime for auditable AI-assisted engineering. Its core design separates:

- model output from evidence;
- advisory review from authority;
- memory from permission;
- provenance from truth claims;
- human approval from execution;
- execution receipts from independent verification.

The repository may look unusually dense because it preserves the engineering lineage of several successive external validation / hackathon cycles instead of rewriting history into a single clean narrative. The current repository is not four products glued together. It is one Core that selectively absorbed verified contracts from earlier frozen projects while retaining source maps, hashes, tests, and historical reports.

For a quick current-state review, read this document first, then:

1. `README.md`
2. `docs/REPRODUCIBILITY_REPORT.md`
3. `docs/REVIEWER_QUICKSTART.md`
4. `docs/PRE_CODEX_TECHNICAL_AUDIT.md`
5. `docs/ROADMAP_HISTORY_AND_GAP_ANALYSIS.md`
6. `docs/governance/GENAI_TRANSPARENCY.md`

## Why the repository changed so much in a short period

The project was exposed to several external engineering validation contexts during 2026. Each one forced a different subsystem to become testable and explicit.

### Track 1 — earlier AOIA / OpenAI Build Week lineage

Earlier work hardened the Core boundary, deterministic retrieval, provenance, controlled execution, and reviewer-facing architecture.

This stage established the rule that model/provider output does not own authority.

The current repository preserves that lineage, but the old competition packaging is not the active product boundary.

### Track 2 — CockroachDB Memory Patch

The memory-focused hackathon forced the project to make persistence, owner scope, lifecycle, provenance, migrations, and replay semantics concrete.

What was retained in AIOA spArkHAT:

- the native Memory Patch contracts;
- Cockroach transaction ports;
- `learning-v1` schema;
- 19-migration certified profile;
- owner/tenant isolation;
- explicit `ZERO_WRITE` when there is no verified epistemic delta;
- stale-source revalidation.

The original CockroachDB hackathon repository remains frozen and must not be rewritten for the NVIDIA or NLnet review.

### Track 3 — AWS Agents for Humans / Non-Zero

The Agents for Humans work forced the system to make consequential authority explicit.

What was retained:

- investigate → propose → human approval → bounded execution → receipt → verification;
- human-bound decision contracts;
- idempotency/replay semantics;
- portable/mock backend for deterministic validation;
- explicit fail-closed handling for un-certified live AWS.

The original Agents for Humans / Non-Zero repository also remains frozen. AIOA spArkHAT contains a Core-native convergence layer with source/provenance mapping rather than silently replacing the original history.

### Track 4 — NVIDIA Claw Agent Challenge

The NVIDIA track forced the previously separate contracts to operate as one bounded vertical slice:

```text
observe
  -> evidence / Knowledge HAT
  -> NVIDIA/Nemotron advisory proposal
  -> Critical Prompt Loop
  -> Core authority gate
  -> scheduler boundary
  -> explicit human approval
  -> Service Guard effect
  -> durable receipt
  -> independent verification
  -> durable memory/audit
  -> restart/replay without duplicate effect
```

NVIDIA is a provider/advisory participant, not the authority root.

## The apparent “24-hour chaos”

The project originally attempted one contiguous 24-hour final endurance trial.

That trial produced useful evidence for many hours but later encountered a genuine ambiguous hosted-provider timeout. The result was preserved as `UNKNOWN`; it was not rewritten into PASS and was not automatically retried as if the provider outcome were known.

Because repeatedly restarting a fragile external-provider-dependent 24-hour run would consume the remaining competition window, the team changed the competition qualification strategy to three independently attested 8-hour endurance windows.

Final accepted segmented result:

- Segment 1: PASS;
- Segment 2: PASS;
- Segment 3: PASS;
- Segments 2–3: zero downtime;
- frozen source/evidence digest remained stable;
- Cockroach health remained PASS/READY;
- provider calls during Segments 2–3: zero.

This is documented as:

`SEGMENTED_ENDURANCE_PASS`

It is **not** described as a contiguous 24-hour `PASS_CLOSED`.

This distinction is intentional and reviewer-visible.

See:

- `docs/ENDURANCE_3X8_CLOSURE.md`
- `reports/SEGMENTED_ENDURANCE_3X8_MANIFEST.json`
- `docs/ROADMAP_2_1_CLOSURE.md`

## What is current vs historical

### Current runtime

Primary implementation surfaces:

- `runtime/`
- `web/`
- `scripts/`
- `tests/`
- `docs/governance/`
- `docs/reviewer/`

### Historical and audit material

The following remain intentionally preserved:

- `archive/`
- `docs/audit/`
- `docs/stabilization/`
- `docs/forensic-runtime-audit/`
- older phase reports;
- provenance/source maps;
- grant/NLnet reviewer snapshots.

These are not all current product instructions.

They are retained so a reviewer can reconstruct how the architecture changed and why.

## NLnet alignment

NLnet's current public guidance emphasizes technical merit, relevance/impact, value for money, public and testable deliverables, and Free/Libre/Open Source publication under a recognised licence.

This repository is MIT licensed.

Reviewer-relevant current evidence includes:

- fresh-clone reproducibility;
- one-command deterministic reviewer preflight;
- explicit limitations;
- adversarial regression;
- replay/idempotency tests;
- source/provenance mapping;
- human authority boundaries;
- documented external-provider risk.

Current canonical validation after the latest bounded hardening:

- 1019 tests PASS;
- 4 expected optional UI skips;
- 0 FAIL;
- deterministic reviewer preflight PASS;
- 14-stage competition trajectory;
- duplicate effects = 0;
- restart redispatch = 0;
- DVM/pheromone mode = SHADOW;
- Service Guard remains the competition effect executor.

The repository does **not** claim production readiness, AGI, scientific truth validation, or an un-certified live AWS backend.

## Open-source and reproducibility boundary

The repository is licensed under MIT.

The project uses explicit installation and reproducibility documentation:

- `docs/REPRODUCIBILITY_REPORT.md`
- `docs/REVIEWER_QUICKSTART.md`
- `docs/TROUBLESHOOTING.md`

The deterministic reviewer path does not require a paid external model call.

When a LIVE provider is used, the result is separately labelled and never silently substituted for fixture evidence.

## Generative-AI transparency

The project uses generative AI as an engineering tool.

Tools used during the current development cycle include:

- ChatGPT for architecture review, repository inspection, test planning, documentation, operator coordination, and bounded code changes;
- Codex CLI for repository-wide implementation and test work;
- external models for bounded comparison/review experiments where explicitly configured.

Human responsibility remains with the project maintainer.

The human operator:

- defines the architecture and scope;
- decides what may be executed;
- approves consequential operations;
- reviews accepted changes;
- owns final technical claims;
- decides what is committed/published/submitted.

GenAI output is not treated as evidence or authority merely because a model produced it.

See:

`docs/governance/GENAI_TRANSPARENCY.md`

Historical commits do not uniformly contain model/prompt metadata. This repository does not retroactively invent such provenance. From the 2026-09-22 reviewer checkpoint onward, substantive AI-assisted changes should be disclosed in commit metadata or the project GenAI log.

## Why old documents are not being deleted during review

There are two simultaneous reviewer contexts:

1. NLnet / grant evaluation;
2. NVIDIA competition evaluation.

Deleting older grant, audit, or provenance documents simply to make the NVIDIA repository look smaller would make the project harder to audit and could erase relevant context for NLnet.

Therefore the current policy is:

- preserve historical material;
- provide clear reviewer entry points;
- mark stale snapshots as historical;
- move or remove only after both evaluation tracks are complete and only with preserved hashes/history.

A full file-by-file classification is generated at:

`docs/reviewer/REPOSITORY_FILE_CLASSIFICATION_20260922.csv`

and summarized in:

`docs/reviewer/REPOSITORY_CLEANUP_AUDIT_20260922.md`

## Known limitations

- the original contiguous 24-hour trial did not achieve its original `PASS_CLOSED` contract;
- hosted model availability is external and can time out;
- OpenRouter LIVE CPL remains operator/key/budget gated;
- live AWS remains disabled/un-certified;
- DVM/pheromone scoring remains SHADOW;
- the repository still contains historical orchestration surfaces outside the bounded competition vertical slice;
- the historical repository is intentionally documentation-heavy.

These limitations are documented rather than hidden.

## Recommended NLnet review order

1. `docs/reviewer/NLNET_REVIEWER_START_HERE.md`
2. `docs/governance/GENAI_TRANSPARENCY.md`
3. `docs/reviewer/PROJECT_OVERVIEW_FOR_REVIEWERS.md`
4. `docs/governance/IMPLEMENTED_CAPABILITIES.md`
5. `docs/REPRODUCIBILITY_REPORT.md`
6. `docs/PRE_CODEX_TECHNICAL_AUDIT.md`
7. `docs/ROADMAP_HISTORY_AND_GAP_ANALYSIS.md`
8. `docs/nms/NLNET_UPDATE_SUMMARY.md` as an older grant-facing snapshot
9. Git history / provenance maps for source-level verification

## External policy references

NLnet public references consulted for this reviewer guide:

- https://nlnet.nl/foundation/policies/generativeAI/
- https://nlnet.nl/useroperated/guideforapplicants/
- https://nlnet.nl/useroperated/eligibility/
- https://nlnet.nl/officehour/

This file is a project-side reviewer guide. It does not replace the specific NLnet project plan, Memorandum of Understanding, or milestone agreement.
