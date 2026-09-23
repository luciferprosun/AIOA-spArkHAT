# AIOA spArkHAT — NVIDIA Berlin Submission Pack

Status: draft for final recording/submission; **not yet submitted**

## One-line pitch

AIOA spArkHAT is a human-bound cognitive agent runtime that combines evidence-aware reasoning, durable memory, planning, restart/replay safety and guarded execution so a long-running agent can act once, prove what happened, and avoid repeating the effect after restart.

## Short description

AIOA spArkHAT demonstrates a long-running maintenance workflow in which model output is never authority. Evidence and Knowledge HAT context feed a Critical Prompt Loop; the Core authority gate evaluates the proposed action; explicit human approval is required before Service Guard performs one bounded disposable-local effect. The system writes a durable receipt, independently verifies the result, persists memory/audit state, restarts, and proves that the effect is not redispatched.

The deterministic reviewer path is offline and reproducible. Optional live provider paths are labeled separately and fail closed when unavailable.

## Public repository

https://github.com/luciferprosun/AIOA-spArkHAT

Reviewer start:
https://github.com/luciferprosun/AIOA-spArkHAT/blob/main/docs/reviewer/NVIDIA_REVIEWER_START_HERE.md
## What the demo proves

The primary competition trajectory contains 14 visible stages:

1. Observe the maintenance condition.
2. Build evidence / Knowledge HAT context.
3. Produce an NVIDIA/Nemotron proposal or deterministic TEST_FIXTURE equivalent.
4. Run Critical Prompt Loop review.
5. Reuse or create only a verified epistemic delta.
6. Revalidate stale evidence when required.
7. Pass the proposal through the single Core authority gate.
8. Place the bounded plan through AgentRuntime / scheduler.
9. Require explicit human approval.
10. Execute exactly one bounded effect through Service Guard.
11. Write a durable effect receipt.
12. Independently measure the target state.
13. Persist memory/audit evidence.
14. Restart and prove replay protection: no duplicate dispatch.

Expected reviewer metrics:
- stage count: 14
- duplicate effects: 0
- restart redispatches: 0
- effect executor: ServiceGuard
- verified reuse: ZERO_WRITE
- authority boundary: Core + human
- DVM / pheromone mode: SHADOW
- trajectory sidecar: ATIF-v1.7, visible events only
## Judging criterion mapping

### 1. Working deployment / real engineering

Evidence:
- public fresh clone works;
- one-command deterministic reviewer preflight;
- the same preflight emits a read-only ATIF-v1.7 trajectory sidecar with an independent SHA-256;
- documented local web launcher works from a foreign working directory;
- public main CI is required green on Python 3.11 and 3.12 for the exact published head;
- NVIDIA SkillEvaluator Tier 1 on the current sprint skill: 6/6 PASS, quality A 100/100;
- full offline regression on the integrated sprint candidate: 1041 PASS, 5 expected skips, 0 FAIL;
- durable receipt + independent verification + restart/replay are exercised, not described only on slides.

### 2. Innovation / creativity

AIOA does not treat model output, critic consensus or memory salience as execution authority.

The architecture combines:
- Critical Prompt Loop;
- Evidence Chain / Knowledge HAT;
- verified epistemic delta with ZERO_WRITE reuse;
- Cockroach-backed Memory Patch architecture;
- Personal Delta / consent boundaries;
- Service Guard;
- explicit UNKNOWN preservation;
- DVM / pheromone memory dynamics kept SHADOW until evidence justifies promotion.

The novelty is the separation between cognition and authority: the system may reason, remember and criticize broadly while consequential execution remains narrow, human-bound and auditable.
### 3. Real-world value

Primary use case:
long-running guarded service maintenance.

Problem:
agent systems can duplicate actions after timeout/restart, lose provenance, or mistake model confidence for permission.

AIOA outcome:
- detects and reasons about the maintenance task;
- proposes a bounded transition;
- waits for human approval;
- applies one disposable-local maintenance effect;
- records a durable receipt;
- independently verifies target state;
- survives restart;
- does not repeat the effect.

This pattern is reusable for operations, infrastructure maintenance, compliance workflows and other tasks where a safe agent must continue over time without silently gaining authority.

## Claims allowed in the final submission

Allowed:
- SEGMENTED_ENDURANCE_PASS
- FUNCTIONAL_CLOSURE_PASS
- deterministic reviewer preflight PASS
- 1041 PASS / 5 expected skips on the integrated candidate's supported offline regression
- zero duplicate effects in the competition trajectory
- restart/replay protection demonstrated
- Service Guard is the competition effect executor
- bounded live NVIDIA provider validation succeeded separately
- public fresh-clone reviewer path works
## Claims NOT allowed

Do **not** claim:
- `24H_PASS_CLOSED`
- one contiguous certified 24-hour PASS
- live provider execution when the run used TEST_FIXTURE
- live CockroachDB when the reviewer run used repository-durable-test fallback
- live AWS / NonZero execution
- DVM/pheromone production authority
- autonomous permission to perform consequential actions
- hidden chain-of-thought as evidence
- that historical UNKNOWN/FAIL trials disappeared after later fixes

Correct endurance language:
`SEGMENTED_ENDURANCE_PASS`

Historical provider UNKNOWN evidence remains intentionally preserved.

## 60–90 second demo script

### 0–8 s — Problem

On screen:
AIOA spArkHAT dashboard + product name.

Narration:
“Long-running agents have a dangerous failure mode: after a timeout or restart they may not know whether an action already happened. AIOA spArkHAT is designed to reason broadly but execute narrowly.”
### 8–22 s — Reasoning without authority

On screen:
evidence / HAT, CPL review, provider mode label.

Narration:
“The agent observes the task, builds evidence, and creates a proposal. Critical Prompt Loop can challenge it, but neither the model nor the critics have execution authority.”

Highlight:
- provider mode
- evidence digest
- authority timeline

### 22–38 s — Human-bound gate

On screen:
Core decision + explicit human approval.

Narration:
“A single Core authority gate checks the plan. The consequential transition remains blocked until explicit human approval is bound to the current plan.”

Highlight:
- human-bound approval
- single Core
- no second executor

### 38–55 s — Real effect + proof

On screen:
Service Guard effect, durable receipt, independent measurement.

Narration:
“Service Guard performs one bounded disposable maintenance effect. The system writes a durable receipt and independently measures the target state instead of trusting the model’s claim.”

Highlight:
- effect executor = ServiceGuard
- receipt = VERIFIED
- independent measurement = VERIFIED / MAINTENANCE
### 55–72 s — Restart/replay

On screen:
restart/replay state + duplicate effects metric.

Narration:
“Now the runtime restarts. It reconstructs state from durable evidence and refuses to dispatch the already-completed effect again.”

Highlight:
- restart recovery = VERIFIED_REPLAY
- duplicate effects = 0
- restart redispatches = 0

### 72–90 s — Why it matters

On screen:
competition evaluation summary + repository link.

Narration:
“This is the core idea of AIOA spArkHAT: reasoning, memory and planning can evolve, but authority stays explicit, human-bound and auditable. The public repository includes a deterministic reviewer path and reproducible evidence.”

End card:
AIOA spArkHAT
github.com/luciferprosun/AIOA-spArkHAT

## Recording checklist

Before recording:
- freeze backend candidate;
- confirm public main CI green;
- run reviewer preflight;
- run dashboard from documented launcher;
- use deterministic evidence artifact;
- confirm all LIVE / TEST_FIXTURE labels are truthful;
- confirm DVM/pheromone shows SHADOW;
- close unrelated windows and notifications.
During recording:
- record 1080p if practical;
- keep browser zoom readable;
- do not scroll rapidly;
- show one continuous primary workflow;
- avoid terminal noise unless proving reproducibility;
- keep narration under 90 seconds;
- show the result before explaining architecture.

After recording:
- verify every visible claim against the evidence;
- remove dead time;
- add only minimal labels/zoom;
- do not edit screenshots in a way that changes evidence;
- export one clean final version plus one backup.

## Submission links to prepare

Repository:
https://github.com/luciferprosun/AIOA-spArkHAT

NVIDIA reviewer guide:
https://github.com/luciferprosun/AIOA-spArkHAT/blob/main/docs/reviewer/NVIDIA_REVIEWER_START_HERE.md

Reproducibility:
https://github.com/luciferprosun/AIOA-spArkHAT/blob/main/docs/REPRODUCIBILITY_REPORT.md

3×8 closure:
https://github.com/luciferprosun/AIOA-spArkHAT/blob/main/docs/ENDURANCE_3X8_CLOSURE.md

Roadmap 2.1 closure:
https://github.com/luciferprosun/AIOA-spArkHAT/blob/main/docs/ROADMAP_2_1_CLOSURE.md
## Final pre-submit gate

Do not submit until all are true:

- [ ] final frontend freeze completed
- [ ] backend freeze completed
- [ ] public main CI green
- [ ] fresh-clone reviewer rehearsal PASS
- [ ] reviewer preflight PASS
- [ ] demo recording reviewed once without stopping
- [ ] video links work without login
- [ ] repository link is public
- [ ] short description matches current implementation
- [ ] no 24H_PASS_CLOSED claim
- [ ] no TEST_FIXTURE presented as LIVE
- [ ] no hidden secrets or local paths exposed
- [ ] final submission form reviewed before send

## Current technical checkpoint

Published through PR **#12** on 2026-09-23.

Current public main:
`e3e050408856393b45668775beda5a42b9affe74`

Verified on the published sprint path:
- GitHub CI on PR head: all four Python 3.11/3.12 packaging/certify jobs PASS
- public-main CI for the merge SHA: PASS
- public fresh-clone reviewer rehearsal: PASS and clean
- deterministic reviewer preflight: PASS
- ATIF-v1.7 trajectory sidecar: PASS
- focused evidence-audit/trajectory/preflight/dashboard tests: 24/24 PASS with the pinned ATIF validator enabled
- full offline regression: 1041 PASS, 5 expected skips, 0 FAIL
- Non-Zero focused regression with isolated optional dependencies: 101/101 PASS
- NVIDIA SkillEvaluator Tier 1: 6/6 PASS, quality A 100/100, one low non-blocking lint advisory
- memory mode: TEST_FIXTURE in the deterministic reviewer path
- provider mode: TEST_FIXTURE in the deterministic reviewer path
- DVM / pheromones: SHADOW
- effect executor: ServiceGuard

This remains a preparation artifact: the demo video and official project form
are still outstanding, and `24H_PASS_CLOSED` is not claimed.
