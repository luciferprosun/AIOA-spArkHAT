# Cosmic shared design implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement task by task. The owner has supplied the design references and explicitly authorized local implementation; do not add another approval gate for the already selected Compose/Web architecture.

**Goal:** Apply the verified Cosmic design to the existing Android and native Linux operator views, preserving their authority and pairing contracts.
**Architecture:** Existing MissionViewModel/MobileClient and /devices transport remain canonical. Presentation only adapts signed observations and capabilities; no provider, Core or protocol is created.
**Tech Stack:** Kotlin Jetpack Compose, existing HTML/CSS/JavaScript, Python offline checks, Kotlin/JVM and Node tests.
**Spec:** docs/design/COSMIC_DESIGN_INTEGRATION_READINESS.md and owner's latest design implementation instruction.

## Global constraints
- No merge, paid operations, phone install/reset or private key changes.
- Preserve unknown operations, exact authority, source seals and trusted binding.
- versionCode4 / packageeu.sparkhat.aioa.companion; update signer must remain75a539bc1cc1cf9ca9cde7fddf32f8dc82ceaee3fd2c8831d9e32a7a14ab6404.
- Native profile is status-only; no chat/MuseLIVE/GitHubWRITE availability inferred from artwork.

## Review focus
- A saved device or expired proof must never render current signed/online.
- Missing capabilities and UNKNOWN must leave effects unavailable.
- Long content / 200% font / narrow display must preserve navigation and scrolling.
- Entry through invitation must reveal existing confirmation controls without changing saved identity.
- Leaving, locking or failing operator readback must not retain positive availability.

## Tasks
- [x] 1. Record source inventories and evidence; verify untouched live worktree and preserved trust.
- [x] 2. RED: presentation behavior tests for stale/invalid/missing capability and operator UNKNOWN; do not create tests mirroring text.
- [x] 3. Shared token artifact, theme/cards/navigation; preserve existing connection and settings controls.
- [x] 4. Compose routes for Home/Chat/Missions/Critical/GitHub/Devices/Approvals/Details/Activity/Providers/Recovery/Settings; bind only existing model methods.
- [x] 5. Existing /devices shell and read-only sections; same exact approval/revoke transport, no new API.
- [x] 6. GREEN: Node, pure Kotlin and relevant Android/mobile regressions; disclose full Android build blockers separately.
- [x] 7. Independent read-only review, source seals/input hashes, patch and installation readiness report.
Rollback: preserve df1a13e baseline; changes remain on local feat/cosmic-design-system-20261103, live 11b1505 untouched. No reset/clean or data migration.


Completed only as locally prepared source. Full Android compilation and install remain BLOCKED by signer/toolchain; no live deployment or phone modification.
