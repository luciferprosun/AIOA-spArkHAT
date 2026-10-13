# GOLD24 — independently checked local evidence inventory (2026-10-13)

**Scope: local experimental 24-hour endurance run, not independent/cloud/NVIDIA certification.**
This document was prepared from read-only inspection of evidence on the project's operator-controlled Linux machine. It does not imply public hosting or release of the complete checkpoint dataset.

## Exact run

| Item | Recorded/checked value |
| --- | --- |
| Run ID | `gold24-20260928T041316Z` |
| Local final status | `GOLD24_PASS` |
| Start (UTC) | 2026-09-28 04:13:17 |
| End (UTC) | 2026-09-29 04:14:05 |
| Reported wall elapsed | 86,448 seconds |
| Reported active | **86,426 seconds** |
| Required | 86,400 seconds |
| Checkpoint files | **722** (numbered `000000..000721`) |
| Verified canonical checkpoint digests | **722/722** |
| Verified predecessor links | **721/721** |
| Monotonic active-second counters | **721/721** |
| Consistent source/run/harness references | **722/722** |
| Duplicate effects | 0 reported |
| Replay redispatches | 0 reported |
| **Replay attempts** | **0 reported**; this is NOT a positive replay attack/fault test |
| Fresh-process reconstruction | `VERIFIED` as recorded by harness, not independently reproduced on a fresh host |
| Cockroach gate | `READY` as recorded |
| NVIDIA gate | `UNAVAILABLE`; NVIDIA live probe `false` |
| Effect execution | ServiceGuard configured; no 24h real external effect throughput evidenced |
| Candidate SHA | `2b0443fe1e60b8497da1923b7fc860f6c2f8c5cb` |
| Harness SHA-256 | `6e3af360bc756df4289af5c5c44c4620f53ff8e37dd4d8fc6393f25f0caf2448` |

### Independent mechanical consistency checks performed

We enumerated all checkpoint JSON files; required contiguous numbers 0–721; independently recalculated SHA-256 of the canonical compact sorted JSON representation *excluding* `checkpoint_digest` and checked each stored digest; checked predecessor hash links; compared every checkpoint's run ID, candidate SHA, and harness SHA with the final report; checked nondecreasing active-second counters and matching final sequence/digest/time; and compared the SHA-256 of the archived harness file with its reported hash.

**Local artifact fingerprints (for future publication of raw evidence):**
- `final-report.json` SHA-256: `8a0f2188d1ea025a74eb5e4b4a8ce7b22e5b521ac4f729a01525a900aabb128e`
- `manifest.json` SHA-256: `86850161c1b0952ebca72e2d1d8d946937481b9594dc22cf368beb6387900537`
- `checkpoint-000000.json` SHA-256: `e231b381945b58993a490e55bdfb692bf409e1d1dc0f6c1f46d230c0931b863f`
- `checkpoint-000721.json` SHA-256: `0b83fecda013979a35def28f9ca18a79c8c14552836b4bbb124f2c9da6201890`
- Ordered checkpoint-file-set SHA-256 v1: `64ae1db784d38ee7fd9aa9d232176976dda52aaaaa6d6e7db960e057f7a3b70d`
  - v1 algorithm: for each lexicographically ordered `checkpoint-*.json`, update SHA-256 with ASCII filename, NUL byte, and raw 32-byte SHA-256 of file bytes.
- Ordered canonical digest-lines SHA-256: `b6a657aeea052be4f41354a24b70f10d9666629c69171042107e3cc588deaca7`
  - Algorithm: update SHA-256 with each 64-character ASCII `checkpoint_digest` followed by LF in filename order.

## Material limitations — publish alongside every PASS headline

1. **The source commit above is NOT currently resolvable from the canonical public GitHub repository.** A direct GitHub lookup on 2026-10-13 returned `No commit found for SHA`. The local result is a historical tested candidate, not a claim that current `main` has passed this exact test.
2. These checks validate the checkpoint *file chain* and report self-consistency. They do **not** independently verify uninterrupted physical execution, clock correctness, database contents, power availability, network inference or all externally relevant effects.
3. `replay_attempts: 0`, `replay_redispatches: 0`, and `duplicate_effects: 0` describe **no replay attempts / no duplicate effects observed in this profile**. Do not claim a replay-attack campaign was passed.
4. The provider was NOT live during this run; the report explicitly says `nvidia_gate: UNAVAILABLE` and the manifest says `nvidia_live_probe: false`.
5. The 722 checkpoints have no effect receipt references in the sampled run fields. This is a timed supervision/checkpoint endurance demonstration, **not** 24 hours of continuously completed end-user agent tasks.
6. The previous public [segmented 3×8-hour manifest](../../reports/SEGMENTED_ENDURANCE_3X8_MANIFEST.json) belongs to a **different historical frozen candidate** and properly states `contiguous_24h_pass_closed: false`. Do not rewrite that immutable record. This GOLD24 local report is a **later, separate run**.
7. The local raw artifacts are not uploaded to the public repo because a separate privacy, credential and provenance review is required; this public inventory alone is not sufficient for third-party independent reproduction.

## Remaining proof gates

- Recover/identify a public, rights-reviewed immutable source archive for candidate SHA and link an exact tag, release, or archival digest.
- Export the raw checkpoint set and harness to a reviewed evidence bundle; verify no credentials, private data or proprietary material.
- Publish a reviewer script and captured checksum report for that exact bundle.
- Re-run fault-injection/replay-attempt scenarios, independent CockroachDB tests and bounded live provider probes separately, recording failures honestly.
- Only then make unqualified third-party-reproducible or provider-certified claims.

**Use in marketing:** “Our September 2026 local GOLD24 endurance run recorded 86,426 active seconds and 722 hash-linked checkpoints; all 722 digests and 721 chain links were later checked. No duplicate redispatches were observed (there were zero replay attempts). Live NVIDIA operation and public source reproducibility were not demonstrated by this run.”
