# Decisions and provenance

All comparisons use base `2be99da7aa07f7eb5faa9459fe8a78c5d0b6653a`. No changes to the default branch, production processes, state, credentials or launchers are included in these decisions.

| Decision | Source | Evidence and disposition |
| --- | --- | --- |
| Canonical product | luciferprosun/AIOA-spArkHAT | Owner direction; one Native composition, one release on main through review. |
| Preserve local work | 12 Git stores, 54 registered worktrees | 44 clean, 8 dirty archived, 2 external inaccessible; 6 additional entries are bare metadata, not broken checkouts. No cleanup. |
| Complete backup | 320 refs / 15,600 objects | `aioa-all-local-sources.bundle`, SHA256 `0853fc1f4825e87b2f2adf67a2ab2b5d9ec075d6b0969fa4f5aba8c52ed93745`; independent restore, fsck and complete ref match PASS. Private backup outside all worktrees. |
| Chat foundation | PR44 / 16fcfeed477f92f2ec65bd235e0b1cd98f87e7fd | Complete coherent chain preserved with `cherry-pick -x`; five source commits, no old-runtime fallback. Source behavior includes v3 money-policy reader. |
| Remote Git candidate | PR45 / ff38e17a837b223a65cb095f832e1a103e573572 | Five unique commits retained. 220b7be6 and 2016ad50 duplicate c7c927c5 and 16fcfeed; resulting tracked tree byte-identical to ff38 before new fixes. Remote qualification remains NOT_LIVE_VERIFIED. |
| Repair state projection | ff38 preflight and chat UI | Six regression cases reproduced old failures before fixes; preserve real UNKNOWN, source/session fences, exact approval and no automatic replay. |
| Unavailable external trees | sprint30 external checkout; nebius-personal-ai external checkout | Committed refs available in local Git and backed up; uncommitted external bytes unknown. They remain PROTECTED and cannot be deleted or certified redundant. They are not dependencies of the existing Native prototype. |
| Auth/policy review | PR44 and PR45 code | Offline integration is authorized; applying changed money-policy behavior or GitHub authority to production still requires the final exact deployment decision. |

The full inventory is not a deletion list. An ancestor/patch-equivalent commit proves history preservation, not current runtime availability or completeness of intermediate experimental trees.
