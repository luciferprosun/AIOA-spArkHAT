# A11 — Android post-merge baseline, 2026-11-01

Canonical repo: https://github.com/luciferprosun/AIOA-spArkHAT, default `main`.
Fresh main/source: `ad5ae30494b9844e0433ffb1712254b781b3fa77`, merged PR #27;
tree `dda2cbb2047c35df79b8eb1833453ec1b67d689b`.
Writer: `codex/android-postmerge-apk-20261101`, isolated worktree
`/home/l/AIOA_LOCAL_WORKTREES/android-postmerge-apk-20261101`.
The prior verified-main detached checkout is preserved as evidence.
Baseline tracked files:1577; Android input manifest:24 files (unchanged).

One Android module `clients/android/:app`, package `eu.sparkhat.aioa.companion`,
versionCode2 / 0.2.0-n1, minSDK26 / compile+targetSDK36, build-tools35.0.0,
JDK17, Kotlin2.2.21, AGP8.11.1, Gradle8.13. Android source manifest matches.
Existing Core/MissionService/MCP/webapp and mobile v1/v2 are retained.

## Observed blockers

- Active `.github/workflows/android-manual-build.yml` and
  `scripts/android/ci_build.py` both permit only old
  `refs/heads/codex/android-toolchain-mobile-20261031`; current main is denied.
- Existing actions use historical v4 pins. Current official releases resolved
  read-only: checkout7.0.1, setup-java6.1.0, upload-artifact7.0.2, all node24.
- Official Ubuntu24 image release `ubuntu24/20261026.354` declares ImageVersion
  `20261026.354.1`; runtime availability must also be verified by the future job.
- CodeQL dynamic run41303106848 / job124837962048 failed finalization32 in
  `build-mode:none`; dependency resolution is not Kotlin compilation.
  Existing four-language scanning must remain protected.
- No real Kotlin/JVM/lint/APK test has been certified. APK: NONE.
- Xiaomi/TLS/enrollment/production owner: NOT_VERIFIED / NOT_BOUND.
  Tailscale Connected does not qualify the gateway or grant Core authority.

## Authorized local work and external gates

Implement and test source/ref/workflow/image guards, current action pins,
an owner-gated real Kotlin CodeQL build path, and reports. Reuse the one
existing Android builder/verification/installer; no second app or Core.

Preserve original checkouts, dirty Nebius and five protected processes.
No SDK/JDK installation on this host or writes to unqualified WD.
No paid inference, Tailscale changes, public listener, phone install,
workflow dispatch, repo security-setting change, push/PR or main merge
without the concrete owner gates required in the supplied A11–A20 PDF.

Raw Git statuses, process IDs, source/API SHA-256 seals and supplier metadata
are retained privately under `AIOA_ANDROID_POSTMERGE_PRIVATE_20261101`.
This baseline is an observation, not a build certificate.
