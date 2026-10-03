# Devpost submission draft — AIOA spArkHAT

**Draft only. Nothing has been submitted or published.**

## Project title and track

**AIOA spArkHAT — Persistent Personal AI with Human Effect Authority**

Track: **Personal AI**.

## Problem

Personal assistants need to remember a user's constraints across sessions and
help with useful actions. Model suggestions, remembered preferences and
ambiguous tool acknowledgements are not reliable authority to change a system.
A restart or repeated request must not turn uncertainty into a duplicate
effect.

## Solution

AIOA combines an existing Personal AI runtime with owner-scoped persistent
private HAT memory, an exact Nebius ProviderPort and a typed maintenance action.
The assistant prepares an advisory proposal, exposes verification status and
stops at exact human approval. A separate execution request passes through
ServiceGuard. Durable receipts, independent readback and a replay barrier let
the operator reconcile after restart without applying the same action twice.

The demonstration uses deterministic fixtures by default. The UI distinguishes
the provider's mode from the effect target's mode, so a local test cannot be
mistaken for a live cloud deployment.

## Architecture

```text
User → Personal AI ↔ persistent private HAT
     → Nebius Token Factory / exact ProviderPort
     → NVIDIA Nemotron advisory output
     → CPL advisory review → independent verification
     → ZERO_WRITE or independently admitted Verified Delta
     → exact human approval → Non-Zero / ServiceGuard
     → typed effect → receipt → independent readback
     → restart reconciliation / replay barrier
```

There is one scheduler, one memory engine, one authority path and one effect
executor. Neither the model, private memory nor CPL may approve an effect.
There is no model-controlled shell execution or silent provider fallback.
See [the architecture specification](nebius_final_architecture.md).

The fixture launcher runs the existing CPL 1+3+1 review on its established
synthetic review task. This demonstrates the advisory review machinery; it is
not a CPL review or proof of the maintenance action. The maintenance proposal
is checked independently by its typed-action verifier.

## Nebius and NVIDIA usage

The exact integration model is `nvidia/Nemotron-3_5-Lightning` through Nebius
Token Factory. The production decoder requires an exact model identity and
`finish_reason=stop`; incomplete output fails closed. Diagnostic receipts
exclude prompts, output, hidden reasoning and credentials.

The fixture provider exercises the Nebius-compatible contract and exact
identity checks. It does not run NVIDIA inference. Optional live-provider
composition leaves the target fixture and requires separate cost admission;
starting a demo is not permission for paid generation.

One separately authorized bounded live Token Factory smoke **passed** on
2026-10-03 at 13:05:34 UTC. The receipt
`evidence/cloud_activation/live_smoke_20261003T130702Z.json` records exact
Lightning identity, `finish_reason=stop`, live inference validated and no
fallback. Reported usage was 25 prompt / 136 completion / 161 total tokens;
the response content was not persisted. The request's total completion cap
was 512 tokens and timeout was 30 seconds. This proves a single live advisory
inference call, not live execution of the maintenance effect or full live CPL.

The two earlier preserved attempts failed with `INCOMPLETE_COMPLETION` and
remain in the evidence history. See [the technical analysis](nebius_lightning_incomplete_completion_analysis.md).
The default recorded maintenance scenario still uses a fixture provider and
fixture target. No further paid inference is authorized by this result.

## Persistent memory and human authority

Private HAT data is owner-scoped and survives recreation of the memory runtime.
The console exposes counts, bounded references and hashes rather than private
text. Retrieved preferences remain private context, not canonical truth or
execution authority. Without independently admitted canonical evidence the
memory delta is `ZERO_WRITE`.

Prepare cannot execute. Approve records consent for the exact proposal and
still cannot execute. A separately requested Execute / Resume crosses the
existing ServiceGuard boundary. Unknown transport outcomes are reconciled
from receipts and independent readback before any retry.

## Restart and replay safety

The fixture scenario prepares, approves, applies once, recreates the demo
service, reconciles the existing result and blocks replay of the same
operation. Its acceptance condition is one apply and zero duplicate effects.
Dedicated recovery tests also cover lost acknowledgements and conflicting
operation reuse. These are local contract tests, not production cloud metrics.

## Significant changes during the hackathon work

- Added the Personal AI coordinator over the existing private memory,
  ProviderPort, ServiceGuard and receipt/readback components.
- Added exact Nebius competition routing, typed HTTPS transport and a redacted
  Operator Console projection with separate human intent controls.
- Added safe incomplete-completion metadata handling while retaining strict
  truncated-output rejection.
- Added a fixture demo launcher and recording flow, separate provider/target
  mode indicators, deterministic restart/replay evidence and a demo self-test.
- Clarified advisory CPL versus independent verification and canonical memory
  delta; retrieval alone is not Verified Delta evidence.
- Prepared the operator runbook, 165-second video script, architecture diagram
  and non-overwriting final evidence manifest.

## Testing evidence

Prompt 02's preserved report records 229 passing tests with no failures or
timeouts. That is historical evidence, not the Prompt 03 total. The new final
manifest records exact Prompt 03 test groups and counts, a fresh final targeted
run with isolated HOME, fixture self-test state sequence, apply counts, static
checks and changed-file secret scan. No performance score or benchmark is
claimed.

Evidence locations:

- `evidence/cloud_activation/live_smoke_*.json`: sanitized live attempts.
- `evidence/personal_ai_vertical_slice/manifest_final_*.json`: final Prompt 03
  results and known blockers; choose the new manifest, not an older report.
- [Demo runbook](nebius_personal_ai_demo_runbook.md): exact recording procedure.
- [Video script](nebius_personal_ai_video_script_180s.md): maximum 180 seconds.

## Limitations and deployment status

- The default provider and effect target are fixtures. This validates the local
  authority and recovery flow, not a live Serverless deployment.
- Earlier real Lightning attempts produced incomplete output. The final
  bounded smoke passed, but does not establish reliable completion of longer
  advisory prompts or the full live maintenance/CPL flow.
- Nebius Serverless deployment remains `BLOCKED_BY_CREDENTIALS`. Deployment,
  recurring resources, additional credits and release publication were not
  authorized or performed.
- Model review is advisory. No autonomous approval, canonical learning from
  preferences, arbitrary shell endpoint or automatic provider fallback exists.
- A video file and Devpost publication require manual operator work after the
  final evidence review. This document is a draft only.
