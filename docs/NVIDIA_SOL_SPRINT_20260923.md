# AIOA spArkHAT — NVIDIA Sol final-polish sprint — 2026-09-23

## Scope

This sprint prepares the existing NVIDIA competition path for fast reviewer
inspection without creating a second Core, scheduler, executor, memory engine
or authority path.

Public main before the sprint:
`730601488fbaf3ba63ebc2677a5828ee5cf8f1ba`.

Integration branch:
`sol/nvidia-final-integration-20260923`.

The frozen Roadmap 2.1 certification SHA and historical evidence are untouched.

## Completed

- audited the superseded local `nvidia/evidence-audit-20260922` worktree;
- consolidated the previously published NVIDIA-specific reviewer skill into one
  canonical `skills/evidence-audit/` package instead of publishing a duplicate;
- hardened that canonical skill with isolated HOME/XDG state, fail-closed nested
  payload validation, exact numeric typing and temporary-artifact containment;
- added a read-only `ATIF-v1.7` trajectory exporter for the deterministic
  NVIDIA competition artifact;
- bound ATIF generation into the one-command reviewer preflight;
- preserved explicit stage order, provider/memory labels and authority fields;
- exporter rejects authority/dynamics boundary violations fail closed;
- hidden reasoning is neither requested nor exported;
- added optional `continued_trajectory_ref` support for future context segments
  while keeping one logical trajectory session ID;
- completed CDB-004 dashboard clarity for ZERO_WRITE, Core + human authority,
  ServiceGuard, receipt, independent verification, replay safety and SHADOW;
- documented Nemotron alignment and separate LIVE-vs-TEST_FIXTURE evidence;
- documented final Gold 24h context continuity and checkpoint requirements.

## Validation

Focused evidence-audit/trajectory/preflight/dashboard gate:
**24/24 PASS** with the pinned NVIDIA ATIF validator enabled.

Canonical offline regression:
**1041 PASS, 5 expected skips, 0 FAIL**.

NVIDIA SkillEvaluator Tier 1:
**6/6 PASS**, quality **A 100/100**; one low advisory lint finding remains non-blocking.

Non-Zero focused regression with its isolated dependency set:
**101/101 PASS**.

Additional gates:
- deterministic reviewer preflight: PASS;
- ATIF sidecar validation: PASS;
- `node --check web/app.js`: PASS;
- `git diff --check`: PASS.

No new LIVE provider call was made by this sprint.

## Gold 24h decision

The final contiguous 24-hour attempt is deliberately **not started here**.

AIOA's NVIDIA adapter is request-local and does not accumulate an ever-growing
chat history. Its default request budget is far below Nemotron's serving
context limits. The Gold run therefore treats durable checkpoint/evidence state
as authoritative and treats operator/model context as replaceable presentation
state.

Before the Gold clock starts, freeze the exact candidate SHA, verify a clean
worktree, bind source/evidence digests, initialize the checkpoint hash chain and
record provider/model policy. Any later operator/model context may resume only
from a verified checkpoint.

See:
- `docs/NVIDIA_GOLD24H_CONTEXT_CONTINUITY.md`;
- `docs/NVIDIA_NEMOTRON_OFFICIAL_AUDIT_20260923.md`.

## Publication

Pending exact-head GitHub CI and PR merge. Record the final PR, merge SHA and
fresh-clone evidence here after publication.
