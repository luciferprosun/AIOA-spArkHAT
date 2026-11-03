# Proposed bounded Jammy DEBUG exception

Status: prepared for explicit owner review; not executed or a claim of VM safety.

The alternative builder run [41578914010](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41578914010), source `24bca9a392a43cb07c7af7ac0f502035c2540fac`, failed IMAGE_CHECK before checkout. `ImageVersion` was the published `20261026.341.1`; native image metadata reported `20261025.340.1`, SHA-256 `08a840f7186e0ab52ee613d5cafee66d245430928627dd25f6dc638bdd7e481f`. This differs from the first failed run on undocumented Noble `20261018.96.1`, which remains rejected.

[Ubuntu22 release 20261026.341](https://github.com/actions/runner-images/releases/tag/ubuntu22/20261026.341) is public, but the metadata's `20261025.340` release URL returned 404. No publisher statement establishes that these two identifiers describe an identical VM. [Issue #15202](https://github.com/actions/runner-images/issues/15202) concerns related Noble discrepancies; it is not proof about this Jammy VM or its security.

## Exact proposal

Only `DEBUG_UBUNTU22_V1`, with explicit DEBUG environment consent and CodeQL disabled, may accept:

- OS image: ubuntu-22.04;
- environment/expected ImageVersion: 20261026.341.1;
- native metadata version: 20261025.340.1;
- entire metadata SHA-256: 08a840f7186e0ab52ee613d5cafee66d245430928627dd25f6dc638bdd7e481f.

Both workflow bootstrap and Python context validation enforce this exact pair/hash. The receipt must retain the discrepancy as `MISMATCH_ACCEPTED_DEBUG`. STRICT and the prior Noble profile remain unchanged. Different metadata bytes, versions, OS, missing consent or CodeQL request remain denied. Actual SDK inventory must still equal `9f81aed02ae39189e55282cd66a561969590f2c032a868beaa1afc7e3b51e793`, before tool acquisition and again before execution; a different inventory is not auto-approved.

Source/main/workflow identity, actor, permissions, official-download checksums, JDK/SDK/Gradle constraints, testDebugUnitTest/lintDebug/assembleDebug, DEBUG signature, artifact size <=128 MiB and one-day retention remain required. No secrets or paid services are introduced. Do not migrate CodeQL or manufacture an APK result.

## Risk and authorization boundary

This relaxes VM image identity from strict equality to one observed mismatch. A metadata digest identifies bytes; it does not attest the kernel, OS or SDK as safe. The unchanged SDK inventory and verified downloaded components limit toolchain drift but cannot prove the host operating system equivalent to the release. The original approved exception covered a different Noble version pair/hash. The new risk decision should explicitly name this Jammy pair before publication/merge/manual build. Broad repair authorization and removal of the owner time limit are not recorded as proof of image equivalence.

## Validation and rollback

The unit fixture reconstructs vendor-format metadata bytes and matches the actual logged digest; it is marked reconstructed, not LIVE. RED reproduces the denial. Tests cover exact acceptance, disclosure, changed bytes, cross-profile use, missing consent, CodeQL denial, and both authority/context guards. Offline PASS is not a Kotlin build or device result.

Before approval: keep the prepared commit local. After approved publication: required CI and independent review must pass before merge. One diagnosed build from the actual merged main, no automatic retries or unknown-ACK reposts. On any new image/SDK mismatch, stop at the actual evidence. Rollback is a normal revert; preserve all logs, existing APK, host/phone state and keys.
