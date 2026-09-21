# AIOA spArkHAT — NVIDIA Final Week Gap Matrix

Date: 2026-09-21
Branch: `codex/nvidia-final-week-20260921`
Baseline: `ad4a425714a764f61f5ff22f2cc59f18abc36984`

## Rule

Build one competition vertical slice. Do not create a second Core, scheduler,
executor, memory system, or authority path. Provider output, CPL, memory,
pheromones and DVM never grant execution authority.

| Subsystem | Existing state | Competition gap | Action |
| --- | --- | --- | --- |
| AgentRuntime | Present; owns LITE scheduler | No unified demo projection | Reuse |
| NVIDIA/LITE | Integrated and safety-gated | Availability can change independently of demo mode | Explicit evidence-only LIVE / EXTERNAL_UNAVAILABLE projection + deterministic TEST_FIXTURE fallback |
| CPL | Present; plan/start/verify + web API; exact 1+3+1 competition preset now exposed read-only in existing UI | LIVE OpenRouter still intentionally blocked until key + explicit cost policy + bounded validation | Keep advisory-only preset; run one bounded LIVE gate only after operator installs credentials/policy |
| Knowledge HAT | Present with Linux corpus/provenance | Not visually connected to correction story | Reuse one deterministic evidence case |
| Cockroach Memory Patch | Live schema, 19 migrations, certificate READY | Cockroach-backed competition memory path now passes; offline repository fixture remains explicit fallback | Surface backend truthfully; no new store |
| Personal Delta | Verified correction/reuse present | Needs one visible correction episode | Reuse S2 semantics |
| MemoryDynamics / DVM / pheromones | Implemented; benchmarked; production status SHADOW | No proven quality gain for promotion | Keep SHADOW; show measured restraint |
| Service Guard | Real disposable target, receipt, independent verification | Live S6 depends on unstable provider | Use deterministic proposal for demo + retain live option |
| Scheduler | AgentRuntime-owned, lease/mutex/replay tested | Needs visible heartbeat/recovery | Surface status only |
| NonZero | Integrated, human-bound authority, web API | Not yet tied visually to same mission | Reuse existing boundary |
| Provenance / evidence | Present and append-only contracts tested | Evidence is scattered across surfaces | Add read-only unified projection |
| Web UI | Existing local app with CPL, Memory Patch, NonZero | No competition mission dashboard | Extend, do not rebuild |

## Verified 2026-09-21

- Original clean endurance Segment 1: > 8 hours, zero UNKNOWN inside boundary.
- Service Guard + NV10 recovery matrix: 48/48 PASS.
- S8 replay validation: PASS, actor_calls=0, duplicate_delta=0.
- NVIDIA endpoint TLS/connectivity: PASS.
- NVIDIA hosted smoke inference: timeout at 120 seconds; external availability risk.
- Authority Timeline backend focused regression: 80 tests PASS, 2 expected skips.
- Deterministic competition vertical slice: PASS in `TEST_FIXTURE` mode; explicit 14-stage one-system order now covers observe -> evidence/HAT -> Nemotron fixture proposal -> CPL/Core authority -> AgentRuntime scheduler boundary -> guarded effect -> durable receipt -> independent verification -> durable memory/audit -> restart recovery.
- Broader demo/memory-CPL/timeline/Service Guard/NV10 focused regression: 120/120 PASS.
- Cockroach-backed competition vertical slice: PASS with `cockroachdb-learning-v1` / `LIVE_COCKROACH`, verified delta write -> ZERO_WRITE reuse -> stale revalidation, durable Service Guard effect/replay, and explicit dashboard backend projection; accepted artifact SHA-256 `c012799a70aa789b6548944c5f9e41bfdda73b83cece0d537dedda77ab4fd17c`.
- Competition evaluation/API/UI gate: 33/33 PASS; metrics are explicit-outcome only and hidden reasoning is not requested or stored.
- Mission heartbeat/restart recovery plus durable receipt and independent measurement are now exposed as read-only dashboard evidence; focused E2E gate 32/32 PASS.
- Provider availability is now a separate read-only evidence projection: recovered `NV_OK` evidence -> `LIVE`, explicit outage evidence -> `EXTERNAL_UNAVAILABLE`, missing/invalid evidence -> `UNKNOWN`; focused provider/web gate 42/42 PASS.

## Highest-value remaining work

1. P1 UI/config preparation is complete; keep the exact OpenRouter preset read-only/fail-closed until `OPENROUTER_API_KEY`, explicit cost policy and one bounded LIVE validation are available.
2. P2: expose Non-Zero readiness/approval/receipt through the existing read-only competition projection only if it can reuse current authority/effect evidence without creating a second executor.
3. Keep deterministic demo readiness independent from external NVIDIA hosted-inference availability, with `repository-durable-test` clearly labeled as offline fallback and Cockroach shown only when actually used.
4. Add only bounded competition-critical adversarial hardening found by regression, then freeze functionality before the frontend/video window; DVM/pheromone remains SHADOW in product claims.

## Non-goals before submission

No new HAT domain, no new memory engine, no second scheduler, no autonomous
shell authority, no live AWS expansion, no DVM/pheromone promotion, no broad
website rebuild, and no migration of the entire AIOA-Claw-NVIDIA tooling repo.
