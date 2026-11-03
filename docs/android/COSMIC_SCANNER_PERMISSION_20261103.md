# Cosmic scanner permission verification repair

Source inspected: `29f780a710286ee6fc9e3cceb35faa24c3997dcb`.
Actual Android run: https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41582150097

The retained failure evidence reports successful `testDebugUnitTest`,
`lintDebug`, and `assembleDebug`, followed by `BLOCKED_APK_PERMISSIONS`.
No APK was published. The failed run did not retain its merged manifest;
the exact permission set must therefore be independently checked in the
next successfully verified APK, not claimed as observed in this run.

The existing `play-services-code-scanner:16.1.0` dependency includes Google
DataTransport. Official published manifests for
`transport-runtime:2.2.6` and `transport-backend-cct:2.3.3` declare
`android.permission.ACCESS_NETWORK_STATE`. This is the source-backed
explanation for the failure, pending actual merged-manifest readback.

Official source artifacts:

- https://dl.google.com/dl/android/maven2/com/google/android/gms/play-services-code-scanner/16.1.0/play-services-code-scanner-16.1.0.pom
- https://dl.google.com/dl/android/maven2/com/google/android/datatransport/transport-runtime/2.2.6/transport-runtime-2.2.6.aar
- https://dl.google.com/dl/android/maven2/com/google/android/datatransport/transport-backend-cct/2.3.3/transport-backend-cct-2.3.3.aar

The repair permits this one additional permission and records the actual
permission inventory in APK evidence. `INTERNET` remains required; the
application's AndroidX receiver permission remains optional and requires
its exact signature-level declaration in the compiled manifest. All other
permissions are rejected, including `CHANGE_NETWORK_STATE`, `CAMERA`,
location, SMS, wake locks, boot reception and advertising ID.

Risk: the dependency can observe connectivity state. This change grants no
network configuration control, camera access or new Core authority. It
does not change app dependencies, application source, STRICT, the approved
DEBUG environment exception, workflow permissions, signature verification,
source binding or artifact limits. QR scanning continues to be delegated
to Google Play services, with the existing public-packet import fallback.

Validation: reproduce the refusal with the new permission test before the
parser change; run Android configuration regressions after it. The next
diagnosed build must still pass all Kotlin tests, lint, assembly, compiled
manifest inspection and signature verification. A host-verified APK does
not establish physical phone pairing or Muse LIVE. Rollback is a normal
revert of this repair; no user data or signing keys are modified.
