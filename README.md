# AIOA spArkHAT 🐾

> **Meta Global AI Developer Hackathon project:** [**AIOA METAGuardiansSPARK**](docs/meta/PROJECT_IDENTITY.md) is developed on branch [`AIOA-METAGuardiansSPARK`](https://github.com/luciferprosun/AIOA-spArkHAT/tree/AIOA-METAGuardiansSPARK). This is the same unified AIOA spArkHAT repository; no separate frontend or main rename.

### Long-Running Agent | NVIDIA Claw Challenge Berlin 2026

![GOLD24](https://img.shields.io/badge/GOLD24-PASSED-00FF00)
![Uptime](https://img.shields.io/badge/Uptime-86%2C426s-blue)
![Checkpoints](https://img.shields.io/badge/Checkpoints-722-orange)
![Replay](https://img.shields.io/badge/Replay-0-red)

**GOLD24 evidence scope:** A **local, historical endurance-run report** from **September 28–29, 2026** records `GOLD24_PASS`, 86,426 **reported active seconds**, 722 hash-linked checkpoints, and zero observed duplicate effects/redispatches. The subsequent evidence review independently checked all **722 checkpoint digests** and **721 predecessor links**. **Replay attempts were zero**, so this is *not* evidence of a replay-attack stress test. NVIDIA LIVE was unavailable. The tested candidate SHA is **not currently in this public repository**, and the raw evidence bundle has not been released; the result is *not independent certification of current main or a hosted service*. Read the [full local GOLD24 evidence review](docs/launch/GOLD24_LOCAL_EVIDENCE_REVIEW_20261013.md).

**New engineering write-up (14 October 2026):** [GOLD24 — 24-hour endurance, 722 checkpoint records and next validation gates](docs/announcements/GOLD24_24H_ENDURANCE_2026-10-14.md) · [Community technical review and hardware-collaboration thread (#20)](https://github.com/luciferprosun/AIOA-spArkHAT/issues/20). The summary explicitly distinguishes reported active time, verified checkpoint-file integrity, and outstanding replay/live-provider validation.

**Separate historical test:** [3×8-hour segmented endurance PASS](reports/SEGMENTED_ENDURANCE_3X8_MANIFEST.json) relates to an earlier candidate and **must not be confused** with the later local GOLD24 run.

[Product overview](https://sparkhat.eu/aioa/) · [Demo video](https://youtu.be/ABJijoNKmYM) · [Product Hunt launch kit](docs/launch/PRODUCT_HUNT_LAUNCH_PACK.md) · [Support the research](https://sparkhat.eu/sponsorship/)

**One canonical AIOA codebase.** AIOA spArkHAT is the unified, human-governed AI runtime and the public entry point for the project. Nebius/NVIDIA, CockroachDB memory, Critical Prompt Loop (CPL), Verified Delta and the native Non-Zero safety module are capabilities within AIOA, **not separate products**.

> **Status:** local, reproducible fixture demonstrations are implemented. Do not confuse an offline test result with live provider certification, cloud deployment, validated legal rights or a hackathon submission.

## What it does

AIOA receives an owner-approved task, applies provenance and evidence checks, uses optional model advice behind bounded cost/risk policies, requires exact human approval for effects, and produces a durable receipt. Replay protection and ServiceGuard preserve the boundary between *advice* and *authority*.

```text
Owner / Operator (approval authority)
    |
AIOA Core + HAT / owner-scoped context
    |-- CPL critics + evidence, DVM/Verified Delta (advisory)
    |-- Memory Patch / CockroachDB adapter
    |-- ProviderManager / Nebius Token Factory + NVIDIA Nemotron (optional)
    |-- Money and risk governors
    |-- MCP Commander transport (bounded READ; separate local policy)
    |
Exact human decision -> ServiceGuard -> bounded effect -> receipt/readback
```

AI models, GitHub issues and external services have **no implicit WRITE/EXEC authority**. The real MCP transport currently supports bounded READ. Nebius/NVIDIA LIVE validation and spending are separate operator-authorized activities. No paid call is necessary for deterministic fixture review.

## Start locally

Requires Python 3.11+ and a complete source checkout.

```bash
python3 -I -B scripts/nvidia_reviewer_preflight.py --unified
./runtime/run.sh
./runtime/run_web.sh
```

Web console is loopback-only by default. The historical `start_nebius_personal_ai_demo.sh` launcher still requires its explicitly approved Nebius branch names; it is not a canonical-main startup command. Use the offline reviewer above to inspect the integrated fixture from main. LIVE provider use requires separate authorization gates.

## Canonical repository layout

| Path | Role |
| --- | --- |
| `runtime/` | AIOA core, execution boundaries, provider routing, CPL and integrations |
| `runtime/memory_patch/` | native memory module and optional CockroachDB adapter |
| `runtime/nonzero_cloudops/` | integrated Non-Zero safety / bounded CloudOps implementation |
| `runtime/mcp_bridge/` | READ-only GitHub task bus and MCP policy bridge |
| `memory/`, `provenance/`, `contradictions/` | state and epistemic semantics |
| `web/`, `tui/` | user interfaces |
| `tests/` | active deterministic and integration tests |
| `docs/architecture/` | current product architecture and source-of-truth decisions |
| `docs/archive/hackathons/` | legacy competition evidence, not active product identity |
| `docs/nebius/`, `docs/release/` | historical Nebius hackathon claims, receipts and runbooks |
| `archive/` | historical and forensic material, excluded from default active test collection |

## Preserve history; separate products from past submissions

- **Canonical active AIOA:** this repository.
- **Non-Zero competition repository:** [AIOA-NonZero-CloudOps-Agent](https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent) — remains independent and unchanged while evaluation is pending. The native AIOA module is separate from the frozen submission.
- **CockroachDB historical source:** [Memory-Patch-for-AIOA-Hackathon-CockroachDB](https://github.com/luciferprosun/Memory-Patch-for-AIOA-Hackathon-CockroachDB). Native design is selectively ported; 847 original files have provenance classifications, including intentionally excluded original material. Never assume the frozen submission can be discarded merely because native AIOA tests pass.
- **Projects for Future:** private historical/project archive; not automatically published into this public codebase.
- **EagleEYE D'Arc:** local-only sensitive core; no migration or publication authorized.

Details: [unification record](docs/architecture/UNIFICATION_2026-10-09.md), [CockroachDB provenance](docs/provenance/memory_patch_source_map.json), [historical launch instructions](docs/archive/hackathons/nebius/README_ORIGINAL_SPARKHAT_20261009.md), [Prototype Fund handoff](docs/grants/PROTOTYPE_FUND_HANDOFF.md).

## Verification and security

Use `python3 -I -B scripts/nvidia_reviewer_preflight.py --unified` for the supported offline reviewer path and the scoped MCP tests described in `docs/architecture/UNIFICATION_2026-10-09.md`. The `certify` CI jobs run the active unittest suite and native authority regressions on Python 3.11 and 3.12. Optional database integration tests require their own CockroachDB setup; arbitrary recursive collection of archival tests is not a universal acceptance command. See the [CI clock correction](docs/architecture/CI_CERTIFICATION_2026-10-09.md).

Real rights/provenance review, binary-content inspection, current model/provider cost confirmation, live inference, public Judge Mode, and Devpost receipts remain **separate external gates**. Historical documents record exact results as observed; this README does not promote their claims to verified current production behavior.

## License

See [LICENSE](LICENSE), original imported-module notices and the rights inventories. The repository's license does not grant rights to all third-party code, media, models, service terms or historical attachments.
