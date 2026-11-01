# Android post-merge closure implementation plan

> **For agentic workers:** Use superpowers:executing-plans in this session. One independent final reviewer; do not start an implementer per task. Steps use checkbox tracking.

**Goal:** Prepare one safe, source-bound Android build from canonical main and a genuine Kotlin CodeQL path, then stop only external effects at the exact owner gate.
**Architecture:** Extend the existing Android workflow, ci_build/build_apk/verifier and installer. The APK job keeps contents:read. Additional CodeQL security permission and default-to-advanced activation require a separate explicit owner decision. Existing Core/mobile authority remains intact.
**Tech stack:** Python standard library, GitHub Actions Node24 pins, existing Gradle8.13/JDK17/SDK36/Kotlin2.2.21/AGP8.11.1.
**Spec:** `/home/l/Downloads/AIOA_ANDROID_POSTMERGE_CODEX_MASTER_2026-11-01-1.pdf`; private extracted MASTER_EXECUTION.txt and progress ledger outside repo.

## Global constraints

- main is the source of truth; preserve verified checkout and all dirty/history branches.
- No native host SDK/install/WD writes, model calls, API credentials, Tailscale mutation or phone install.
- Source ref allowlist starts with main only; SHA, actual checkout, workflow bytes and ImageVersion must match.
- workflow_dispatch-only APK build; owner confirmations default false; no PAT or persistent checkout credentials.
- One worker, no daemon, bounded heap/output/time; no automatic retry of uncertain dispatch.
- Fixture/source checks are never JVM/APK/phone or LIVE proof.
- Publish/PR/merge/security-settings/CI/license/artifact exposure stay at the owner gate until a concrete reviewed patch exists.

## Review focus

1. A changed input alone must not authorize a fork, old ref, mutable workflow/image or changed checkout — Task2 negative guards.
2. HEAD/ref races and lost dispatch ACK must not start an unreviewed/repeated build — Task2 branch binding and Task5 run handoff.
3. Curated build environment must preserve genuine CodeQL tracing without exposing credentials — Task3 trace-command tests; real analysis remains gated.
4. APK/hash/signer/JUnit evidence must describe the actual controlled build, not fabricated XML or copied unrelated APK — Task4 adversarial tests and limitations.
5. A phone key, Tailscale state or fixture must never mint owner/TLS authority — Task4 reuse mobile negatives and document blocked edge.

### Task1: A11 baseline and supplier evidence

Files: docs/android/A11_BASELINE.md; this plan; private metadata/seals/ledger.
Interfaces: consumes existing main ad5ae304 and source manifests; produces pinned supplier records and a protected source inventory.

- [x] Read PDF, verify main, branch/worktree/remote/status and protected sources/processes.
- [x] Create exactly one isolated writer from origin/main; preserve verified checkout.
- [x] Verify official action commit SHAs/node24, runner inventory and current CodeQL error.
- [x] Commit baseline and plan. Expected: clean source, no external mutations.

### Task2: A12/A13 source guards and action runtime

Modify: .github/workflows/android-manual-build.yml, scripts/android/ci_build.py, tests/test_android_manual_workflow.py.
Interfaces: context_check(env,source_sha,image,purpose='apk'); workflow seal and branch-head checks precede execute; same existing execute/build API remains the APK entry point.

- [x] Write RED tests for old/unapproved ref, source/workflow SHA mismatch, owner/actor/ref/run-attempt/image drift and changing only inputs; spy zero build/download effects.
- [x] Bind main/GITHUB_SHA/GITHUB_WORKFLOW_SHA, exact workflow bytes, reviewed image and actual clean source; canonical branch observation before/after controlled build.
- [x] Update only supplier-verified action pins to node24, preserving permissions and upload scope.
- [x] GREEN targeted guards + existing Android tooling regressions; commit source then runtime/pins as coherent reviewed stages.

### Task3: A14 real Kotlin analysis path, activation gated

Modify existing APK workflow/ci_build; add a gated advanced CodeQL configuration preserving four current languages; tests/test_android_codeql.py.
Interfaces: codeql purpose reuses preparation/installer/source gates; compiles existing :app Kotlin under trusted CodeQL trace-command, then actual analyze produces SARIF. It never claims compilation in offline tests.

- [x] RED closed context/permission/trace-path/no-credential tests and loss-of-trace regression.
- [x] Preserve APK-job contents:read. Isolate security-events:write to optional owner-gated CodeQL job. No settings/variable change in this phase.
- [x] Pin official CodeQL action/bundle; use manual build between init/analyze with bounded existing helper; preserve four existing analyses in prepared advanced setup.
- [x] GREEN source/contract tests; record precise default-to-advanced owner effect and potential runs; commit.

### Task4: A15/A16 artifact proof and mobile acceptance

Modify existing build_apk/verify_apk only if demonstrated gaps require it; tests/test_android_build_verification.py and focused new regressions; docs/android/EDGE_AND_XIAOMI_ACCEPTANCE.md.
Interfaces: actual controlled JUnit/lint/build, APK inspection and signer evidence; mobile uses existing ES256, sessions and same Core with remote admission still NOT_BOUND.

- [x] RED tests for signer/artifact binding and catalog result; GREEN through existing builder. Evidence retained privately.
- [x] Preserve exact Android input manifest; one-run command/exposure boundary prepared in final handoff.
- [x] Reuse mobile packet/SPKI/nonce/replay/UNKNOWN/source/permissions regressions. Document precise HTTPS/owner adapter boundary and Wi-Fi/LTE phone acceptance; do not fake qualification.
- [x] Commit validated artifact/mobile handoff. JVM/APK/phone results remain NONE until real authorized execution.

### Task5: A17–A20 acceptance, independent review and one owner decision

Files: docs/android/ANDROID_POSTMERGE_OWNER_REPORT_20261101.md; private patch, review, logs, source/secrets/license seals and exact dry-run request.
Interfaces: consumes exact final local head/main base and successful targeted suites; produces one concrete effect authorization request without dispatch/merge before consent.

- [x] Run Android74/Core202/mobile77/native42/Node15 regressions; no redundant full20min run.
- [ ] One fresh independent review of whole diff, CI permissions and absent build evidence; fix Critical/Important once with RED→GREEN + green necessary suite; defer Minor explicitly.
- [ ] Scan changed files and outgoing local history; preserve raw results and source seals.
- [ ] Produce exact workflow/source/image/owner acknowledgments and CodeQL settings transition plan, bounded public artifact exposure and ACK-loss readback procedure.
- [ ] Final status BUILD_BLOCKED_OWNER_GATE/APK_NOT_BUILT unless real separately authorized build exists. Preserve worktree and evidence; ask one precise GO only after concrete patch/review.
