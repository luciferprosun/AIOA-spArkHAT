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

## Final source-consolidation decisions under ASTRA_MERGE.pdf

- Keep one PR46 and one writer. Baseline `41aa47e5` already preserved all five PR44 commits and five unique PR45 commits; do not cherry-pick these again. PR44/45 stay open and protected until accepted main preservation is independently verified.
- Classify 31/31 feature groups without wholesale merges: 11 already in frozen main, 6 ports in PR46, 11 deferred/preserved, one external corpus blocker, one deduplicated reviewer slice and one obsolete authority use. Every group has an exact source SHA, canonical destination, reason and evidence boundary. No source receives deletion approval.
- Use only the existing canonical CPL preview; paid 1+3+1 execution remains unbound. Project worker `BLOCKED_NATIVE_WORKER_NOT_CERTIFIED` and memory `INTEGRATED_INERT` / `MEMORY_CONSENT_REQUIRED`; never pick an operator HAT or widen scope automatically.
- Implementation `bb48d7940f1e759adce4ff8b24c9a296819dc461` adds installed real Native/Core acceptance and missing offline refusal/ACK/source/input regressions. Model and remote ports remain fixtures in tests; production is not touched.
- The official private SQLite snapshot is readable by active, baseline and implementation readers with identical UNKNOWN/audit/warrant/pairing projections. Old main refuses it. State compatibility is a read-only copy certificate, not permission to restart Native or restore an older journal.
- Separate code-source completeness from product LIVE readiness. GitHub/Gmail effects, canonical paid CPL, worker activation, semantic memory and physical Android acceptance remain separate explicit gates. Keep CodeQL `SKIPPED` under the existing owner policy.
- Exact final PR HEAD, tested merge tree, CI and evidence hashes go in the operator's final release report and current PR description. Require separate exact owner GO for main merge and another for deployment, as ASTRA_MERGE.pdf sections1.5/7.6–7.7 specify.
