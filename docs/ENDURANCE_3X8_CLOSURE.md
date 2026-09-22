# AIOA spArkHAT — 3×8 h Segmented Endurance Closure

Generated from preserved certification evidence on 2026-09-21T23:36:59Z.

## Final classification

**SEGMENTED_ENDURANCE_PASS**

This is a segmented `3 × 8 h` qualification. It is **not** a contiguous 24-hour certification and must not be described as `24H_PASS_CLOSED`.

Frozen certification SHA:
`ad4a425714a764f61f5ff22f2cc59f18abc36984`

Evidence root (read-only):
`/home/l/.local/state/aioa-roadmap-v2-1-final-closure-20260919T114331Z/segmented-endurance-ad4a425-20260921T071749Z`

## Segment results

| Segment | Status | Attested active seconds | Required | Downtime at closure | Completed / boundary UTC |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | PASS | 28,898.455834 | 28,800 | 0 | 2026-09-20T22:14:37.744224Z |
| 2 | PASS | 28,909.535110 | 28,800 | 0 | 2026-09-21T15:28:52.859090Z |
| 3 | PASS | 29,029.012337 | 28,800 | 0 | 2026-09-21T23:30:52.868698Z |

Total attested active time: **86,837.003281 s**. Required segmented total: **86,400 s**. Total recorded downtime: **0 s**.
## Integrity and source binding

- source status: `PASS`
- source worktree clean: `true`
- source digest: `a90dd64d8f028ce3b194e01d955561c20e173cc4d09a9854df550fd0367a12e4`
- evidence digest: `a7c05e24c23a713d38d957095d67c249ef11b004af783ba61ebc34006d0687c3`
- Cockroach status at closure: `PASS`
- Cockroach certificate: `READY`
- Cockroach migration count: `19`
- accepted invalidation marker in closure evidence: **none found**

The invalidation/error text found by broad grep belongs to source/test vocabulary and historical narrative, not to an accepted segment invalidation record.

## Provider-call accounting

The segmented monitor recorded `provider_calls=0` at the Segment 1 boundary heartbeat and the Segment 2/3 segment records also report `provider_calls=0`.

This statement is limited to the segmented endurance monitor/accounting. It does not rewrite or erase historical provider activity or historical `UNKNOWN` outcomes from the source NV12 trial outside the accepted segment boundary.

## Preserved limitation

`reports/FUNCTIONAL_CLOSURE.json` explicitly records:

- `original_contiguous_24h_pass_closed = false`
- `nv12b_live_effect_path = null`
- `nv12b_independent_cloud_proof = null`

Therefore this closure qualifies the segmented endurance evidence only; it does not manufacture a contiguous 24-hour result or an NV12B cloud-effect proof.
## Evidence file digests

| Evidence file | SHA-256 |
| --- | --- |
| `segments/SEGMENT_01.json` | `2c42c8b3e24343212f874cb56f21e4250b2ba840406885696a7ae360e3cbb8e5` |
| `segments/SEGMENT_02.json` | `08c5dc30d56df442355e8ea60e86e685b8917e75e8b9af0fd0d41ee2829d5c21` |
| `segments/SEGMENT_03.json` | `c4ee54bbeeefa42625f552c0f5d13b3aa7f601c77ce85fa7da618c65e67b5342` |
| `reports/SEGMENTED_ENDURANCE_COMPLETE.json` | `4cfede5a8589f601ae3af9e4208861f00f46044e99ce88709870eedd0150637e` |
| `reports/FUNCTIONAL_CLOSURE.json` | `aaee1447dc924ed8b07baf1757b8b17c06fd0bbfa81cec9357380339184c3b6e` |

Segment 1 additionally binds the accepted in-window scenario evidence digests for S1, S2 and S3 and the trial-freeze digest recorded in `SEGMENT_01.json`.

## Closure decision

All three accepted segments exceed 28,800 attested active seconds, the combined accepted total exceeds 86,400 seconds, downtime is zero, source integrity remains PASS, the source worktree is clean, and Cockroach remains PASS/READY on the 19-migration learning profile.

Roadmap 2.1 may therefore use **SEGMENTED_ENDURANCE_PASS** as its endurance closure evidence, while preserving the explicit limitation that the original contiguous 24-hour claim remains false.