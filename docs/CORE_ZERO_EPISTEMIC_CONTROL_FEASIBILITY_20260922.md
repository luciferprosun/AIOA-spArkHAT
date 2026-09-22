# AIOA spArkHAT — Core Zero / Epistemic Control Feasibility Audit — 2026-09-22

## Decision

**GO:** one authoritative Core with a strictly advisory/shadow epistemic control plane.

**NO-GO:** a second authority Core, second scheduler, second executor, or any mechanism where model consensus, memory score, CPL critics, DVM/pheromone state, or retrieval rank can approve or execute an effect.

This is a feasibility/audit result only. No dual-authority implementation is authorized by this document.

## What “Core Zero” means here

For this submission, Core Zero is treated as a set of non-delegation invariants around the existing Core, not as another runtime:

1. provider/model output is data or proposal, never execution authority;
2. evidence/provenance may constrain a proposal but cannot approve an effect;
3. approval remains exact, human-bound and revocable at the existing Core/Service Guard boundary;
4. Service Guard remains the competition effect executor;
5. restart/replay must reconcile durable intent/receipt before any re-dispatch;
6. UNKNOWN remains UNKNOWN until a separate, explicit later attempt produces new evidence;
7. memory, CPL and dynamics can advise ranking/review only and cannot revive stale/revoked authority.

## Existing one-Core evidence

- `runtime/main.py` / `AgentRuntime` owns the existing application lifecycle and module composition.
- `runtime/critical_loop/` is advisory review inside the same runtime; critics cannot approve, execute or promote knowledge.
- Memory Patch / Knowledge HAT contracts separate verified evidence from retrieval/memory hints and preserve source/version binding.
- competition evidence requires a human-bound Core gate, then one `ServiceGuard` effect executor, durable receipt, independent measurement and replay-safe restart.
- Non-Zero is shown only as Core-native contract/readiness alignment on the competition path; the competition projection records `nonzero_executor_invoked=false`.
- DVM/pheromone is explicitly `SHADOW` in competition mode and non-SHADOW evidence is rejected.

## Feasible epistemic control plane

The safe shape is a read/advisory plane feeding the existing Core:

```text
observation / provenance
        |
        v
Knowledge HAT + verified evidence
        |
        +--> CPL critics (advisory)
        +--> Personal Delta / ZERO_WRITE decision
        +--> Memory Patch retrieval / source freshness
        +--> DVM / pheromone scoring (SHADOW)
        |
        v
existing Core admission / authority gate
        |
        v
explicit human approval
        |
        v
Service Guard -> receipt -> independent verification -> durable audit
```

The epistemic plane may reduce uncertainty, detect contradictions, refuse stale sources, or rank what deserves review. It must never emit an approval capability or effect command.

## Why dual authority is NO-GO

A second authority plane would introduce unresolved split-brain semantics in exactly the areas that are currently strongest in the evidence:

- which Core wins if one approves and the other revokes;
- which scheduler owns replay/recovery after restart;
- which executor/receipt is authoritative after lost ACK or ambiguous provider state;
- whether epistemic confidence can accidentally become execution capability;
- how idempotency and stale-target checks remain single-source-of-truth;
- how a reviewer can distinguish advisory consensus from actual authority.

No current competition requirement justifies taking those risks before submission.

## Promotion criteria for any future change

A future proposal to promote part of the epistemic plane beyond SHADOW/advisory would require all of the following before implementation:

1. a concrete user/product requirement that cannot be met by the current Core;
2. an authority model proving there is still exactly one final effect authority;
3. explicit replay/idempotency and revocation precedence rules;
4. adversarial tests for stale evidence, poisoned memory, critic collusion, restart, lost ACK and duplicate-effect prevention;
5. migration/rollback design that preserves historical evidence;
6. separate review after the NVIDIA submission freeze.

Absent those conditions, promotion remains **NO-GO**.

## Submission recommendation

Freeze the architecture at one Core plus advisory/shadow epistemic control. Spend remaining final-week effort on reviewer clarity, reproducibility, regression evidence, UI/demo polish and Codex cleanup of legacy ambiguity—not on a second authority mechanism.

## Validation

Focused authority/epistemic-control regression completed **91/91 PASS** across Authority Timeline, competition evaluation, CPL service, Memory Patch authority, Non-Zero Core authority and NV05 SHADOW dynamics. `git diff --check` is required before commit.
