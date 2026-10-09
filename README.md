# AIOA SparkHub

**One canonical AIOA codebase.** SparkHub is the unified, human-governed AI runtime and the public entry point for the AIOA project (previously AIOA spArkHAT). Nebius/NVIDIA, CockroachDB memory, Critical Prompt Loop (CPL), Verified Delta and the native Non-Zero safety module are capabilities within AIOA, **not separate products**.

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

Web console is loopback-only by default. For the personal-AI fixture demo, use `./scripts/start_nebius_personal_ai_demo.sh --fixture`. This filename is a historical launch interface; the implementation belongs to the unified AIOA runtime. Do not use `--live-provider` without separately completing the live authorization gates.

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

Use `python3 -I -B scripts/nvidia_reviewer_preflight.py --unified` for the supported offline reviewer path and the scoped MCP tests described in `docs/architecture/UNIFICATION_2026-10-09.md`. The broader test tree includes archival tests with incompatible standalone import assumptions; running arbitrary `pytest` over the entire repository is not a supported single acceptance command.

Real rights/provenance review, binary-content inspection, current model/provider cost confirmation, live inference, public Judge Mode, and Devpost receipts remain **separate external gates**. Historical documents record exact results as observed; this README does not promote their claims to verified current production behavior.

## License

See [LICENSE](LICENSE), original imported-module notices and the rights inventories. The repository's license does not grant rights to all third-party code, media, models, service terms or historical attachments.
