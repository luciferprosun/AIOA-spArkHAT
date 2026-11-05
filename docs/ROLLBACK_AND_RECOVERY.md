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

A future production rollback requires a separate owner decision, no running effect worker, a fresh consistent SQLite backup and preserved original key/TLS/pairing files. Validate a copy before any replacement. Never copy a live SQLite main file alone and call it a verified state backup. The source bundles above are separate from the state snapshot below.

## State snapshot and reader qualification, 5 November 2026

At 10:36:05 UTC, the official SQLite `Connection.backup` API read the running profile through a `mode=ro`, `query_only` connection into the private directory `/home/l/AIOA_BACKUPS/final-release-state-20261105T103605Z`. Integrity and foreign-key checks passed. SQLite SHA-256: `31c39bbf86c0f0148426363695ff9824449750525daf0399b1cda3b82b099500`. Host signer and TLS files were copied privately with stable source hashes, owner-only permissions, and a matching, currently valid TLS key/certificate. No secret values were printed or committed.

The readers at active `16fcfeed477f92f2ec65bd235e0b1cd98f87e7fd`, baseline `41aa47e57e5c8e875f0a67d87108cba62d1d623c`, and implementation `bb48d7940f1e759adce4ff8b24c9a296819dc461` all decode the same 1200 records: 443 audit events and matching outbox entries, 16 warrants and owner witnesses, 71 governor versions, two governor UNKNOWN reservations, three CHAT_UNKNOWN records, two paired devices and two mobile sessions. Policy/v3, reservation/exposure, audit-chain and retained-record hashes agree. Exported Python files are checked against each Git commit's blobs and all 43 imported project modules originate in that export. No Native is booted on this snapshot, no principal is issued and no write transaction is constructed. See [aggregate evidence](../audit/2026-11-05/STATE_COMPATIBILITY.json).

The old-main reader `2be99da7` was tested only against the copy and refused it with `INVALID_GOVERNOR_AMOUNT`. This confirms the rollback prohibition; the refusal is retained as evidence, not hidden as a passing test.

This certifies **snapshot integrity and offline reader compatibility**, not production startup or restoration. The installed Native test uses an unrelated temporary fixture database and synthetic OS/TLS/source admission. It must never be pointed at this owner snapshot to renew old authority.

For a future code rollback, preserve the **current** journal, keys and UNKNOWN records. Do not restore this older snapshot to erase later events. `16fcfeed` is a candidate reader only while the current journal contains no newer remote-intent schema; revalidate the then-current copy before selecting it. After remote effects or new intents, choose a reader that understands those records. Restoring a state backup is a separate owner-approved recovery procedure with reconciliation, never ordinary code rollback.

Deployment remains `NOT_DEPLOYED`: require exact owner approval, fresh backup/state comparison, stopped or reconciled effect workers, existing source/TLS/OS admission, and a controlled same-profile restart with rollback available. Do not reuse expired chat sessions or invent new scopes. No such restart was performed here.

Branch cleanup is a later phase: accepted main release → exact branch/SHA preservation table → owner approval → recheck current remote SHAs → small deletion batches. Active worktrees, dirty files, PR44/45 and unresolved source classifications stay protected.
