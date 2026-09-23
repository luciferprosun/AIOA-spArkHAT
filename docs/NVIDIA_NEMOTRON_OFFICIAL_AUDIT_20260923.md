# NVIDIA Nemotron official alignment audit — 2026-09-23

Status: `READ_ONLY_RESEARCH_COMPLETE / NO_LIVE_PROVIDER_CALLS`

This note records only claims supported by current official NVIDIA sources.
It does not establish hosted-endpoint availability, API-key validity, live model
behavior, benchmark reproduction, or any new execution authority in AIOA.

## Model identity

Canonical model used for this audit:

- `nvidia/nemotron-3.5-lightning-30b-a3b`
- NVIDIA release date: 2026-08-11
- Architecture: hybrid Mamba-2 + Mixture-of-Experts + attention
- Parameters: 30B total, 3B active per token
- Multi-Token Prediction layers are part of the model design

Official model card:
https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b/modelcard

## Context-length interpretation

NVIDIA currently publishes two different but compatible context statements:

1. The model card describes model support up to 1M tokens.
2. NIM 2.0.10 documents 262,144 tokens (256K) as the native/default serving
   context and the value reported by `/v1/models`.

Serving beyond 262,144 in that NIM requires an explicit long-context override,
more KV-cache memory, and workload-specific quality validation. Therefore AIOA
must not treat 1M as the default operational context merely because the model
card lists that upper capability.

AIOA competition-safe interpretation:

- use 262,144 as the conservative deployed/NIM default unless the actual runtime
  is configured and validated for a larger value;
- label any larger context as deployment-specific evidence;
- never infer provider availability or quality from the model card alone.

Official NIM guide:
https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning.html

## Runtime/API facts relevant to AIOA

NIM documents OpenAI-compatible and Anthropic-compatible interfaces for this
model. The NIM guide also warns that when the `nemotron_v3` reasoning parser is
used, the returned reasoning field should not be fed back into later `messages`.

That maps cleanly to AIOA's authority model only if:

- provider/model output remains evidence or proposal, never execution authority;
- Core remains the single authority decision path;
- ServiceGuard remains the effect executor;
- replay/idempotency decisions are made from AIOA evidence, not model confidence;
- unavailable or ambiguous provider outcomes remain explicit `UNKNOWN` or
  `BLOCKED_EXTERNAL` states instead of being repaired into a success claim.

No LIVE NVIDIA request was made during this audit.

## ATIF version verified from official NVIDIA documentation

NeMo Agent Toolkit 1.7 exposes `ATIF_VERSION = "ATIF-v1.7"` and a `Trajectory`
model with `schema_version`, `session_id`, `trajectory_id`, `agent`, sequential
`steps`, optional metrics/notes, and optional subagent trajectories.
Each ATIF step has a sequential integer `step_id`, a source in
`system|user|agent`, optional model metadata, message content, optional tool
calls/observation, and optional `reasoning_content`.

Official references:

- https://docs.nvidia.com/nemo/agent-toolkit/1.7/api/nat/atif/trajectory/index.html
- https://docs.nvidia.com/nemo/agent-toolkit/latest/api/nat/atif/step/index.html
- https://docs.nvidia.com/nemo/relay/v0.6.0/configure-plugins/observability/atif

## Exporter gate

A local `nvidia-nat` package is not currently installed on this Linux host.
Therefore this audit does **not** claim that any AIOA trajectory exporter is
ATIF-compatible yet.

Before such a claim, require all of the following:

1. install a pinned NeMo Agent Toolkit validator in an isolated environment;
2. validate produced JSON with NVIDIA's `Trajectory` Pydantic model;
3. verify sequential step IDs and tool-call observation references;
4. ensure no hidden chain-of-thought is exported;
5. confirm exporter execution is read-only and cannot change Core/ServiceGuard;
6. add negative schema tests and fresh-clone reproduction evidence.

## Decision

`GO` for Nemotron 3.5 Lightning alignment as a provider/model option under the
existing AIOA authority boundaries.

`NO-GO` for claiming 1M operational context without deployment-specific proof.

`NO-GO` for claiming ATIF compatibility until an exporter artifact passes the
pinned NVIDIA model validator locally.

`NO-GO` for using Nemotron output as authority, a second scheduler, or a second
effect executor.

## Follow-up — ATIF exporter gate satisfied locally

Later on 2026-09-23, the exporter gate above was exercised with NVIDIA's pinned
`nvidia-nat-atif==1.7.0` package. The generated deterministic fixture trajectory
passed `nat.atif.trajectory.Trajectory.model_validate` as `ATIF-v1.7`, with
sequential step IDs and no `reasoning_content`.

The updated claim is intentionally narrow: local schema compatibility for the
read-only TEST_FIXTURE evidence exporter is validated. This does not establish
LIVE Nemotron/provider availability, a raw provider transcript, NVIDIA
certification, benchmark reproduction, or `24H_PASS_CLOSED`.

Detailed evidence: `docs/NVIDIA_ATIF_EXPORT_VALIDATION_20260923.md`.
