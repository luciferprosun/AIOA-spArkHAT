# Branch cleanup after PR46

Baseline main: `a095878831f978cb1c8a8df679bbc648dbaedac6`. PR46 is already merged; this work does not repeat that consolidation. No branch is deleted, no Native deployment is performed, and GitHub WRITE remains disabled.

## Inventory and preservation

The initial live inventory contains **77 GitHub branches**, **23 canonical local branches**, and **46 branches in 11 other local Git stores**: 146 branch references and 122 distinct commit tips. Another 142 remote-tracking references are not additional live GitHub branches. On GitHub, 41 tips are reachable from main and 36 have history outside main. The union of outside history contains 686 commits, affecting 3,087 paths, including 1,447 code paths.

The complete owner-private inventory records names, full SHAs, merge bases, outside commits, worktree protections and exact backup-ref locators. An independent archive covers all 146 initial branch references and all 122 tips:

- Bundle: `aioa-current-all-refs.bundle`, 27,043,640 bytes, 321 refs.
- SHA-256: `6d1bb3690ce88843f1b2e361ec8e58e5b35537bf3ee3ebd34a8ec0585505a407`.
- `git bundle verify`, standalone private restore, `git fsck --full`, exact ref comparison and unchanged source refs: PASS.

The private bare restore is backup verification, not another product repository. Eight dirty worktrees and two unavailable external worktrees remain protected; committed-history backup is not proof that their uncommitted content is redundant. All registered worktrees are retained.

Open PRs 22, 25, 44 and 45 remain protected, together with PR25's non-main base `AIOA-METAGuardiansSPARK`. The running Native source `16fcfeed477f92f2ec65bd235e0b1cd98f87e7fd` is retained. A short-lived review branch for this candidate adds a technical branch to the initial counts; final live counts and exact SHAs belong to the owner manifest, not this initial snapshot.

## New source findings

The accompanying source review records implementation, callers, dependencies, tests and limitations. Static inspection is not reported as runtime PASS. Historical test files often use injected transports, temporary corpora or fixture critics.

Only the hardened deterministic CPT preview is adapted in this candidate, through existing Native admission and digest-only Core audit. See [CPT_PREVIEW.md](../../docs/modules/CPT_PREVIEW.md). Other useful source is archived with its limitations:

- Memory Hats creates an independent tag store and lacks current HAT admission. The old citation checker can accept an empty claims list; canonical claim-span verification is stronger. The pinned law adapter requires an unqualified external corpus.
- Knowledge staging/factory code is substantial, but research parses local fixture facts and reports `production_verified=False`. It is not a live acquisition engine.
- Orchestra has implemented contracts and provider calls but uses separate JSON configuration, secrets and sessions. Its revision compiler has no live caller. The original desktop CPL slice is already in main.
- W7A has real repair and Codex worker code, but no current Native warrant/CPL binding. Its Git actuator requires another file-based effect ledger. Companion has another enrollment database, two explicit `NOT_IMPLEMENTED` adapters and no production `OriginalCoreAdapter`.
- R3's adapter registry is empty. Old startup/backup code depends on retired checkpoint/provenance persistence and can perform writes; it is not a drop-in diagnostic.
- Gmail's unported effect gate is only a Protocol. Its pure MIME/OAuth-intent slice already exists in main. Historical Bash classification, legacy Git barriers and JSONL ledgers do not replace current admitted principals, exact warrants or audit.
- Nebius parallel probes, NVIDIA developer tools and Nemotron Vision/48 experiments use independent provider/state paths. Funding and launch documents add no product execution capability. The Product Hunt chain verifier is byte-identical to main; PR22's stdin counter is unbound tooling.

Eight historically deleted code paths were checked separately: two package initializer corrections, the retired Aureon adapter and five W7A probe/monkeypatch paths. No deleted path is silently discarded; every source commit remains in the verified archive.

## Approval boundary and incomplete inputs

An ancestor proof means history is retained in main; it does not assert that every old feature is still active. An archived unmerged branch must never be labelled merged. The manifest distinguishes merged candidates, archive-only candidates, review holds, open PRs, active/dirty worktrees and main.

Deletion requires the owner's later approval of exact names and SHAs, followed by small batches with a fresh ref/PR/worktree check and backup verification. No deletion command or auto-cleanup job is introduced here. Main is the sole intended permanent product branch; protected and technical branches are temporary holds.

**Required input missing:** `ASTRA_BRANCH_CLEANUP.pdf` was not found in the available files. Its location has been requested. This audit follows the explicit user message, but cannot claim compliance with an unread PDF or final deletion readiness under its unknown conditions.
