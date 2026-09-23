# NVIDIA Gold 24h — context continuity and checkpoint plan

Status: design gate for the final optional contiguous 24-hour run.
Checked: 2026-09-23.
This document does **not** claim `24H_PASS_CLOSED`.

## Why model context must not be test state

The Gold 24h run must remain valid even if an operator chat, coding-agent session,
or hosted-model conversation is replaced during the run. Authoritative state
must live in durable trial/checkpoint evidence, never in a model's hidden or
conversation context.

The current AIOA NVIDIA adapter is already request-local: every provider call
builds one bounded system message plus one bounded user message. It does not
append an ever-growing conversation history. `LiteBudget` defaults to only
4096 input bytes and 256 output tokens per call.

The segmented endurance monitor used for the accepted 3x8 evidence made zero
provider calls during its endurance accounting. Therefore a future 24-hour
continuity claim must be based on process/evidence continuity, not on keeping a
single Nemotron chat open for 24 hours.

## NVIDIA context-capacity note

Two current official NVIDIA surfaces describe different serving envelopes:

- the Nemotron 3.5 Lightning model card describes context length **up to 1M
  tokens**;
- the NVIDIA NIM 2.0.10 deployment guide documents a **262,144-token native
  context** as its default `--max-model-len`, with longer serving requiring an
  explicit vLLM override and additional memory/quality validation.

Sources checked on 2026-09-23:

- https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b/modelcard
- https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning.html

AIOA must not make correctness depend on either ceiling. Its own request bound
is intentionally far smaller.

## Gold 24h invariant

A valid final Gold run should bind all of the following before the clock starts:

1. exact frozen source SHA;
2. clean worktree and source/evidence digests;
3. exact trial/harness version;
4. provider/model identity and bounded live-call policy, if LIVE calls are used;
5. Cockroach certificate/profile when selected;
6. heartbeat interval and allowed accounting semantics;
7. immutable test ID and initial checkpoint digest.

During the 24 hours, every heartbeat/checkpoint must be reconstructible from
disk without asking a model what happened earlier. Context replacement is
allowed only outside the authoritative runtime state.

## Context-rotation protocol

If a future operator or agent wrapper maintains conversational context, rotate
it without touching trial authority:

1. finish the current bounded operation;
2. atomically persist the trial checkpoint;
3. hash the checkpoint and record the previous checkpoint digest;
4. export the visible trajectory segment;
5. start a fresh operator/model context;
6. load only the explicit checkpoint summary plus immutable test contract;
7. verify source SHA, checkpoint hash chain, effect receipt state and next
   scenario before continuing;
8. never infer missing state from model prose.

The ATIF sidecar supports this by keeping one logical `session_id` while a
segment may set `continued_trajectory_ref` to the next trajectory file.
Context rotation therefore changes the presentation/session container, not the
authoritative test state.

A stateful wrapper should rotate proactively rather than wait for a provider
context error. No particular token threshold is part of the Gold acceptance
contract; the persisted checkpoint is the contract.

## Failure semantics

The Gold run must fail closed or preserve UNKNOWN when any of these occur:

- source SHA or evidence digest drifts;
- a checkpoint hash chain breaks;
- a consequential effect lacks its bound approval or durable receipt;
- replay would redispatch an already committed effect;
- hosted inference crosses the network but its outcome becomes ambiguous;
- the monitor cannot attest elapsed time under the declared contiguous policy.

An operator/model context ending is **not by itself** a trial failure if the
authoritative process and evidence remain healthy and the next context resumes
from a verified checkpoint. Conversely, a new context cannot repair an
unattested gap in the trial clock.

## Final-run sequence

The Gold 24h attempt should happen only after the submission candidate is
feature-frozen and all ordinary CI/reviewer gates are green:

`freeze SHA -> preflight -> initialize checkpoint chain -> start 24h monitor
-> bounded scenarios/live probes -> checkpoint/trajectory segments -> final
integrity verification -> PASS or preserved failure/UNKNOWN -> immutable report`.

Do not start this run merely for optics. It is an optional final validation and
must not consume the submission/video safety buffer.
