# Cosmic4 — prebuild gate,2026-11-03

Owner requested a new APK4.0, preservation of existing pairing/data, and automatic setup of the connected Xiaomi. No further design approval was requested. This is authorization for the development/provisioning task; Core still verifies its real local operator and exact READ-only device approval.

The original signing key was not recovered. Android cannot update the old package with a different private signer or move its non-exportable Keystore identity to another UID. Cosmic4 is therefore an additional variant of the same application/repository: `eu.sparkhat.aioa.companion.cosmic4`, code400, version4.0.0-cosmic. The original application remains installed. The new public host configuration comes through verified USB, and the existing Core grants the new installation its own transport identity. No secret/session/key is included in the APK.

## Verified before CI

- Frozen live source:5fae31002031ab0eb0aa94b9e57e8f6fbb3b6e01; changes isolated in `feat/cosmic4-usb-20261103`.
- Kotlin/JVM:73 PASS, including7 USB/store contract cases. This is not Android compilation.
- Python configuration/mobile regression:177 PASS; JavaScript:29 PASS.
- Targeted pairing:24 PASS. The separate128-reconnect endurance case was interrupted, is NOT PASS, and retains its partial evidence. It is not needed to claim this bounded build gate.
- Build-input manifest, generated tokens and diff checks:PASS.
- Owner-private original-data backup: encrypted, decryption verified; no hardware key export.
- New persistent APK signing key: private local storage, protected CI secrets, independent public-certificate export/readback; no regeneration at retry.

## Independent review

Fresh reviewer `cosmic4_code_review`: **PASS — proceed with the exact CI build.** Actual Gradle, APK inspection and physical phone acceptance remain pending.

Addressed review findings: stale USB evidence on invalidation; nested host exact schema/source validation; synchronous delivery persistence with reopen/write-failure coverage; independently matching installed APK bytes; read-only wait for Core pending after local pre-BEGIN save; exact Android `Result: Bundle` parser; no unverified data-preservation claim inside pairing helper.

The default original-package update certificate remains pinned. `COSMIC4_USB_V1` is a distinct package/version/certificate channel. It is available only from the exact reviewed branch, owner actor, source SHA, workflow hash and existing runner policy. STRICT, SDK inventory/download verification, limited permissions,35-minute CI limit,128MiB and1-day retention remain intact. The two new signing secrets are exposed only to the controlled build step on that branch; main receives neither value. No CodeQL setting migration or main merge.

## Remaining execution

1. Push reviewed exact commit; dispatch the existing registered Android workflow on its branch using exact SHA/hash and DEBUG_UBUNTU22_V1.
2. Verify real test/lint/build reports, aapt identity/permissions, apksigner, SHA-256 and installed-byte equality.
3. Install alongside the original; independently compare original APK/data inventories.
4. Use `python3 -B -m scripts.android.provision_usb --help`. The required `--verified-apk` must already pass independent artifact verification.
5. Obtain actual Core admission; exact device/SAS/request approval remains inside existing Core. On an OS/human gate, stop there.
6. Compare actual accepted Android signed status against the same proof in Core; restart/reconnect without QR.

No AGENT_READY claim; current Native profile is status READ only. Muse LIVE, WRITE/EXEC and paid inference remain disabled.

## References

- [Android app signing](https://developer.android.com/studio/publish/app-signing)
- [Android Keystore](https://developer.android.com/privacy-and-security/keystore)
- [Build variants](https://developer.android.com/build/build-variants)
- [ContentProvider caller checks](https://developer.android.com/reference/android/content/ContentProvider)
- [GitHub CLI branch dispatch](https://cli.github.com/manual/gh_workflow_run)
