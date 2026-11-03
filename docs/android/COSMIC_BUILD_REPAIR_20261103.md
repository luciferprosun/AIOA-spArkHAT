# Cosmic build repair — 2026-11-03

PR #35 was merged at `9e428c27e81c12f9f7a914fbce4e20da597ad620` after current-tree Core and CodeQL PASS. Android run [41576997028](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41576997028) failed before checkout: the assigned Ubuntu24 runner reported `20261018.96.1` in both metadata and environment, metadata SHA-256 `381d7f87209f02403f1b1575b22efeb99742581ef5555289f8854d6dfcb74a6c`. The reviewed profile expected `20261026.354.1`. No Gradle task or APK was produced. Its original log is preserved privately.

The undocumented image is NOT newly allowed. The owner's current instruction authorizes diagnosed repairs toward the APK and removes the owner time limit; no paid service, automatic retry or security-setting migration is authorized by this change.

## Alternative builder

`DEBUG_UBUNTU22_V1` selects the existing standard GitHub-hosted `ubuntu-22.04` runner and accepts only matching native metadata/environment `20261026.341.1`. [Official release](https://github.com/actions/runner-images/releases/tag/ubuntu22/20261026.341) is published, non-draft and non-prerelease; [official inventory](https://github.com/actions/runner-images/blob/ubuntu22/20261026.341/images/ubuntu/Ubuntu2204-Readme.md) lists Android36 revision2 and Build Tools35.0.0. The runtime must still pass the existing complete SDK inventory digest and existing-license check. Public documentation is not a cryptographic attestation of a particular VM.

The runner label cannot pin an image revision: if GitHub allocates any other version, the build fails closed before checkout. `STRICT` remains the default with its unchanged Noble identity semantics. `DEBUG_TOOLCHAIN_V1` retains its exact existing exception. The alternative permits neither metadata mismatch nor CodeQL migration. It retains manual owner consent, exact main/source/workflow SHA, actor checks, read-only permissions, verified downloaded JDK17/Gradle, pre/post SDK seals, no secrets, fresh DEBUG signer, APK <=128 MiB and one-day artifact retention. The reviewed workflow's technical timeout is retained for this attempt; removing the owner's time cap does not require an unbounded process.

Tradeoff: the alternative trusts a different published GitHub Ubuntu22 VM image and its supplied SDK, subject to the same SDK byte inventory pin. It is a DEBUG-only builder, not production platform certification. No AppArmor exception is added to the Android build. Core CI remains separate and unchanged. Issue [runner-images #15202](https://github.com/actions/runner-images/issues/15202) is a user report under investigation, not a security attestation or approval for any mismatched image.

## APK verifier

The verifier still required N1 versionCode2/versionName0.2.0-n1 even though the accepted Android source and build-input manifest require Cosmic3/0.3.0-cosmic. Update its exact identity requirement and related parser fixtures. The regression compares the result with the current build manifest and rejects old/wrong identities. No permission or signature check is relaxed.

## Validation and rollback

RED reproduced missing alternate-profile support and rejection of Cosmic identity. Targeted offline Android tests pass after the change; these are not a Kotlin build or physical-phone acceptance. Required hosted regression checks and a real manual JVM/lint/assemble build remain necessary before APK delivery.

Rollback is a normal revert of this repair; retain failed logs, main history, old APK and device state. No reset, force push, phone uninstall, Keystore deletion or secret publication.
