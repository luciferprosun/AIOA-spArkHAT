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
| NVIDIA/LITE | Integrated and safety-gated | Hosted inference currently times out intermittently | Preserve live path + explicit demo/test fallback |
| CPL | Present; plan/start/verify + web API | Not shown in one end-to-end story | Surface in competition dashboard |
| Knowledge HAT | Present with Linux corpus/provenance | Not visually connected to correction story | Reuse one deterministic evidence case |
| Cockroach Memory Patch | Live schema, 19 migrations, certificate READY | Needs concise demo evidence | Reuse; no new store |
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
- Deterministic competition vertical slice: PASS in `TEST_FIXTURE` mode.
- Broader demo/memory-CPL/timeline/Service Guard/NV10 focused regression: 120/120 PASS.
- Competition evaluation/API/UI gate: 33/33 PASS; metrics are explicit-outcome only and hidden reasoning is not requested or stored.

## Highest-value remaining work

1. Expose mission heartbeat/restart/recovery and effect receipt/independent verification in the existing dashboard.
2. Complete provider availability projection: LIVE, TEST_FIXTURE, or EXTERNAL_UNAVAILABLE.
3. Run one dashboard-level end-to-end regression over demo + evaluation + Authority Timeline.
4. Keep deterministic demo readiness independent from external NVIDIA hosted-inference availability.
5. Freeze functionality before frontend/video window.

## Non-goals before submission

No new HAT domain, no new memory engine, no second scheduler, no autonomous
shell authority, no live AWS expansion, no DVM/pheromone promotion, no broad
website rebuild, and no migration of the entire AIOA-Claw-NVIDIA tooling repo.
