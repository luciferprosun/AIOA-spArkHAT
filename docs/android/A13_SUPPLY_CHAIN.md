# A13 — supplier verification, 2026-11-01

Read-only metadata verification; no action, SDK or build executed locally.

| Supplier | Exact official release commit | Runtime |
|---|---|---|
| [actions/checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) | `3d3c42e5aac5ba805825da76410c181273ba90b1` | node24 |
| [actions/setup-java v6.1.0](https://github.com/actions/setup-java/releases/tag/v6.1.0) | `b843ebf9b913146b38da2eaa7aeddf76074ae1ad` | node24 |
| [actions/upload-artifact v7.0.2](https://github.com/actions/upload-artifact/releases/tag/v7.0.2) | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | node24 |
| [github/codeql-action v4.39.1](https://github.com/github/codeql-action/releases/tag/v4.39.1) | `9b3254085494b55a0f7c4c2b3d2d52cc712ce370` | node24 |

Official action.yml and README were read at those commits; release commit
signatures report verified. Node24 requires runner >=2.327.1; the observed
CodeQL runner is2.338.2. Checkout authenticated container Git needs2.329.0;
this build uses no container action and persist-credentials:false.

## Reviewed Ubuntu24 image

Official [release ubuntu24/20261026.354](https://github.com/actions/runner-images/releases/tag/ubuntu24%2F20261026.354)
and [tagged inventory](https://github.com/actions/runner-images/blob/ubuntu24/20261026.354/images/ubuntu/Ubuntu2404-Readme.md)
state ImageVersion **20261026.354.1**, JDK17.0.21+9, API36rev2 and
build-tools35.0.0. Preinstalled Gradle9.8.2 and command-line-tools12.0 do not
match the required Gradle8.13/cmdline22.0: existing pinned downloader/extractor
acquires those only after owner approval on the hosted runner.

The actual earlier CodeQL job used **20261025.353.1**, not that image.
The ubuntu-24.04 label does not guarantee a fixed image rollout. The build
must reject any unreviewed ImageVersion before acquiring/building; changing
the expected-image text cannot widen the policy. One authorized attempt may
therefore stop on image drift; it must not automatically retry.

SDK package paths/versions/licenses are checked again in the actual job.
The image inventory is supplier evidence, not execution or an independently
published Android SDK archive SHA256. Null Google archive SHA256 values in
the existing toolchain lock remain hard local-install blocks.

## CodeQL bundle

Official bundle release: [2.27.3](https://github.com/github/codeql-action/releases/tag/codeql-bundle-v2.27.3).
Full Linux archive `codeql-bundle-linux64.tar.gz`, size695275440,
publisher/GitHub asset SHA256
`64518dc413c8e7b5733fee2489e830a899bb1e3f28c8873b5869d5cc90164c5c`.
No archive was downloaded for this local task. Actual CodeQL version and
manual tracing/analysis success remain future runtime gates.

## Owner decisions still required

Standard public hosted runner compute is free according to
[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions);
artifact/cache limits and any other billable usage still require review.
Owner must accept actual [Android SDK terms](https://developer.android.com/studio/terms),
dependency acquisition, public DEBUG APK exposure and short retention.
Stored SDK license records do not accept terms on the owner's behalf.
No model/API budget is changed by an Android build approval.
