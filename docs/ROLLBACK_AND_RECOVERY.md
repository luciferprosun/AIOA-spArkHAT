# Rollback and source preservation

No production deployment or state migration was performed by this consolidation. The live Muse checkout at `16fcfeed477f92f2ec65bd235e0b1cd98f87e7fd`, its launcher, SQLite, TLS, host signer, Android pairing and UNKNOWN liabilities remain intact.

## Verified source checkpoint

Private owner backup directory: `/home/l/AIOA_BACKUPS/unification-20261105T074138Z/`.

| Backup | SHA-256 | Verified scope |
| --- | --- | --- |
| `aioa-canonical-pre-unification.bundle` | `9a4b9f47c34a3ec168f696211b557a561fda736fcf581f380cdd6fa0100020c0` | 173 canonical refs; independent bare restore, fsck and exact manifest match |
| `aioa-all-local-sources.bundle` | `0853fc1f4825e87b2f2adf67a2ab2b5d9ec075d6b0969fa4f5aba8c52ed93745` | 320 canonical/historical refs, 15,600 reachable objects; same independent verification |

The directory also contains private raw Git metadata and eight uncommitted-file archives with individual checksums. These may contain private configuration and must not be published. Two external worktree directories were unavailable; their uncommitted contents are not certified. Their available committed histories are in the full bundle. Ref deletion is not authorized by backup existence.

To inspect recovery material, restore into a **new empty diagnostic directory**, verify the recorded checksum and `git bundle verify`, fetch `refs/*:refs/*` into a new bare repository, run `git fsck --full` and compare the exact saved manifest. Do not overwrite existing worktrees or production state. This was already performed independently for both listed bundles.

## Code and state compatibility

PR44 introduced `aioa.governor.money-policy.v3`. Old main `2be99da7aa07f7eb5faa9459fe8a78c5d0b6653a` cannot be assumed to read the current production database. **Never roll back to that old main against live v3 state.** Preserve the compatible known-good Muse source and compare schemas before selecting any rollback version.

Source rollback does not erase effects, revoke remote commits or settle UNKNOWN. The new preview records use the existing generic Core operation/audit format; no database migration or alternate memory store is introduced. Core/GitHub preflight failures retain exact source bindings and cannot be replayed as fresh writes.

A future production rollback requires a separate owner decision, no running effect worker, a consistent SQLite backup made with the SQLite backup API or a quiesced database including its WAL, and preserved original key/TLS/pairing files. Validate a copy before any replacement. Never copy a live SQLite main file alone and call it a verified state backup. This task's source bundles are **not** a production-state backup certificate.

Branch cleanup is a later phase: accepted main release → exact branch/SHA preservation table → owner approval → recheck current remote SHAs → small deletion batches. Active worktrees, dirty files, PR44/45 and unresolved source classifications stay protected.
