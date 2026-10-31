# AIOA METAGuardiansSPARK — 31 October 2026 migration notice

**Current canonical Git branch:** `AIOA-METAGuardiansSPARK`; old `meta` was renamed. Original 26 October restrictions on Nebius remain below as historical facts. The owner later authorized *reviewed integration* of Nebius and other AIOA features, not blind merge, lost work, credential transfer or unsafe effects.

---

# META 2026 — branch-only coding and inherited source inventory

**Date:** 26 October 2026. **Owner directive:** Nebius work continues for four days; do NOT touch its branch, local active checkout, Git state, processes, caches, or credentials. All new competition changes must land only on the dedicated GitHub branch \`meta\`. No merge to \`main\`.

## Verified source lineage (READ ONLY)

Meta branched from canonical \`main\` SHA:
\`81656e6ccbb0c02307d049e865b6df3225ddb578\`.

At this checkpoint, GitHub \`main...meta\` comparison returns **meta ahead by 4 commits, behind by 0**. The following Core/MCP/provider files **already exist in \`meta\` unchanged** from \`main\`, so creating duplicate copies would introduce needless security divergence:

| Inherited code | Original Git blob SHA | Reuse |
| --- | --- | --- |
| \`runtime/core_admission.py\` | \`a16e5559cfee3b24e9bd77aa98b302f889f7c79c\` | owner scope / bounded capabilities |
| \`runtime/mcp_bridge/adapter.py\` | \`19af909efe393afc397b8916a3e1ded4cd48ac9c\` | typed READ task proposal |
| \`runtime/mcp_bridge/policy.py\` | \`a3e55100fe409e26f413fbda8ca116f429e1b608\` | deny-by-default classification |
| \`runtime/mcp_bridge/read_ops.py\` | \`6ddfb3b3f5714cb1cda4ad784406d4ddd9718f55\` | bounded READ payload checks |
| \`runtime/providers/openai_compatible.py\` | \`7465c4e135ec6acde7f3f428572f17d5fe50631e\` | existing provider base to evaluate later |
| \`runtime/mission/warrant.py\` | \`43cbc574b74df48fb72c5b5f22ab7e6a574c2f26\` | existing one-use authority ledger |
| \`runtime/tools/browser_tools.py\` | \`58ea3746189d64bf87e5abb498437a87d75c5be6\` | legacy helper; NOT approved for public effects |

No transfer from the ongoing Nebius branch, no merge, and no silent rewrite of these inherited modules is authorized. If future Nebius changes are needed, wait for a stable, owner-reviewed SHA and cherry-pick only specific reviewed commits/files INTO \`meta\`.

## META-specific additions

- \`runtime/meta_hackathon/worktree_guard.py\`: identifies a dedicated, *clean*, separately cloned \`AIOA-spArkHAT-META\` checkout, requires exact \`meta\` branch, repository origin, and owner-supplied GitHub-pinned commit SHA. Only local read-only Git inspection. Fails closed on a mismatched checkout; does not grant authority.
- \`runtime/meta_hackathon/mcp_offline_plan.py\`: imports original AIOA MCP \`build_task\`, \`evaluate_task\`, \`RiskClass\`; supports a tiny READ-only proposal surface. Its \`dispatch_allowed\` is always false.
- \`tests/test_meta_hackathon_branch_isolation.py\`: exercises real local Git fixture repos, including branch drift, malicious origin, untracked files, and forbidden operations.

## Dedicated local workspace — future execution gate

Use a **separate clone** (not \`git worktree\` sharing the active repository's .git directory), e.g.:

\`\`\`bash
git clone --branch AIOA-METAGuardiansSPARK --single-branch https://github.com/luciferprosun/AIOA-spArkHAT.git \
  "$HOME/projects/AIOA-spArkHAT-META"
\`\`\`

This is a **future operator command**, not evidence that a clone was created. A trusted host must supply both the exact owner directory and the independently verified \`meta\` commit SHA to the gate. No model may choose the checkout path, mint owner approval, run destructive Git commands, change branches, or copy credentials. Do not run Muse Code in any existing Nebius/Companion checkout.

## Current STOP line

No Muse Code installation or login; no paid Meta Model API calls; no live Chromium/Playwright; no GitHub Task Bus dispatch to the active local worker. The Meta API key stays only in the owner's local protected secret file, untouched by this step.

Even a successful local checkout check is **not** a signed owner warrant, OS confinement, live browser certification, or permission to bypass the Core approval path.
