# OpenAI Workflow Feedback Draft — AIOA spArkHAT final-week work

Status: **DRAFT ONLY — DO NOT SEND AUTOMATICALLY**

Date: 2026-09-22

## Context

This feedback comes from a multi-day software-engineering workflow that combined ChatGPT planning, scheduled tool-enabled runs, an authorized Linux workstation, local Git worktrees, Codex, long-running certification processes, and strict separation between frozen evidence and active competition development.

The workflow was unusually safety-sensitive: historical evidence had to remain immutable, development had to stay on a separate branch/worktree, provider output could not become execution authority, and every accepted batch needed tests and local commits.

## What worked especially well

### 1. Scheduled ChatGPT runs can act as a disciplined operator loop

The strongest pattern was a recurring run that always began by checking current state, then performed one bounded task, ran tests, recorded evidence, and committed locally. This made long certification and final-week preparation much easier to supervise without granting uncontrolled autonomy.

### 2. Tool use plus explicit repository constraints is powerful

Giving ChatGPT a precise worktree, forbidden paths, branch name, frozen SHA, test gates and no-push/no-deploy rules produced a useful separation between planning and execution. Remote terminal/file tools were enough for most work when Codex was unavailable.

### 3. ChatGPT and Codex complement each other

ChatGPT worked well as the continuity layer: architecture, evidence review, safety constraints, phased roadmap and operator reporting. Codex is most useful for heavier implementation/refactor batches once the acceptance contract is already explicit.

### 4. Evidence-first status reporting reduces hallucinated progress

Requiring exact test counts, artifact digests, Git SHA/status and explicit LIVE vs TEST_FIXTURE labels substantially improved trust. A product feature that made this style first-class would be valuable for engineering teams.

## Main friction points

### 1. Usage-limit visibility is still too coarse for sprint planning

For deadline-driven coding, it is difficult to plan when Codex capacity may become unavailable without a precise remaining-budget/reset view. A clear dashboard showing remaining coding capacity, reset time and which actions consume the most quota would help teams choose between Codex, ChatGPT tools and local execution before a critical batch starts.

### 2. Handoff between ChatGPT and Codex should be a first-class workflow

Today the safest pattern is manual: ChatGPT writes a handoff/backlog, Codex reads it, executes, and then ChatGPT audits the result. A native handoff object could carry:

- repository/worktree and branch;
- forbidden paths;
- authority/safety constraints;
- acceptance tests;
- allowed external actions;
- current evidence SHA/test baseline;
- stop conditions.

That would reduce prompt repetition and make operator intent harder to lose.

### 3. Long-running processes need better durable observation

For multi-hour certification/tests, it would help to have a persistent process card with heartbeat, latest verified status, last log digest and explicit "do not restart automatically" / "repair and resume" policy. This is safer than repeatedly reconstructing process state from terminal sessions.

### 4. Scheduled work would benefit from a durable project ledger

A scheduled engineering agent should have a native append-only ledger containing accepted commits, tests, artifacts, blockers and non-claims. This could be scoped to one project and reviewed by the user without relying on chat history alone.

### 5. Tool permissions should expose a clearer read/write boundary

For workflows with frozen evidence, it would be useful to mark directories or connected resources as read-only at the orchestration layer. The model can already be instructed not to write, but an enforceable path-level policy would make certification work safer.

## Feature requests

1. **Codex capacity dashboard** — remaining usage, reset time, recent consumption and optional alert before a long run begins.
2. **Native ChatGPT → Codex handoff** — structured constraints, tests, branch/worktree, stop conditions and evidence baseline.
3. **Durable project execution ledger** — append-only record of accepted changes/tests/artifacts across scheduled runs.
4. **Long-process monitor primitive** — heartbeat/log digest/status with operator-selected restart/repair policy.
5. **Path-level read-only tool policy** — enforce immutable certification/evidence roots.
6. **Explicit external-action policy per project** — e.g. local commits allowed, push/deploy/publish forbidden unless separately approved.
7. **Test/evidence cards** — show command, result, duration, commit and artifact digest as reusable project state.
8. **Better quota-aware routing** — when Codex capacity is unavailable, allow an approved local-tool fallback without losing the same handoff contract.

## Why this matters

The value is not unrestricted autonomy. The useful model is **bounded autonomy with verifiable state**: the user defines authority and irreversible-action boundaries, while ChatGPT/Codex can autonomously execute reversible local engineering work inside those bounds and continuously prove what changed.

That pattern made it possible to run a complicated final-week engineering workflow while preserving frozen certification evidence and keeping all publication/deployment decisions with the human operator.

## Sending rule

Do not send this draft automatically. The operator should review/edit it first and decide whether and where to submit it to OpenAI.
