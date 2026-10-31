# AIOA METAGuardiansSPARK

**Official Meta Global AI Developer Hackathon project name:** AIOA METAGuardiansSPARK
**Canonical Git branch:** `AIOA-METAGuardiansSPARK`
**Canonical GitHub repository:** https://github.com/luciferprosun/AIOA-spArkHAT
**Branch:** https://github.com/luciferprosun/AIOA-spArkHAT/tree/AIOA-METAGuardiansSPARK
**Rename date:** 31 October 2026
**Pre-rename commit:** 9ee80c635f6cb2fea13613152188220a2fa90564
**Archive/rollback branch:** `archive/meta-before-metaguardiansspark-20261031`

## Product identity and source history

This is the Meta hackathon name for the existing, unified **AIOA spArkHAT** platform, not a new GitHub repository or an unrelated application. The legacy `meta` branch was renamed, preserving all commits. Preserve dated original Muse reports rather than rewriting the historical name or source SHA.

Keep existing Python imports `runtime.meta_hackathon`, model contract and JSON schema identifiers stable for backward compatibility. Branding does not create owner approval or LIVE verification.

## Integration destination and work preservation

All reviewed Meta-hackathon development should target `AIOA-METAGuardiansSPARK` after QA. The prior AIOA `main` foundation is an ancestor of the Meta branch. Do not blindly merge dirty Nebius worktrees. In particular, as of the rename, local Nebius/Nemotron integration had 24 modified files and 199 untracked files; the Meta checkout contained two untracked Muse MVP files. Preserve these through recoverable checkpoints before transferring code.

Priority functional sources to review and integrate into **this same AIOA application**:

1. Nebius/Nemotron provider and frontend v2.2, without parallel default UI.
2. Web Mission Control, Linux gateway, knowledge, MCP and GitHub Agent.
3. Muse Code via official controlled MSP session gateway and Meta Model API through a separately gated product adapter.
4. Android Mission Control and owner approval/STOP evidence readback.
5. Optional Gmail draft-only, Nemotron48 knowledge and older engine features, after MVP verification.

**LIVE checks require separate owner approval:** real model spending, Chromium network access, GitHub writes, package installation and Linux effects. OFFLINE fixtures cannot be labelled LIVE.

## Branch migration status

- [x] GitHub branch renamed from legacy meta to `AIOA-METAGuardiansSPARK`
- [x] Historical pre-rename commit referenced by dedicated archive branch
- [x] Local checkout follows canonical renamed upstream; untracked Muse MVP retained
- [x] Offline branch-identity policy and unit fixtures updated (independent QA required after full suite)
- [ ] Finish and independently QA the two untracked Muse MVP files before commit
- [ ] Safely integrate selected Nebius/Mission Control/Android code via reviewed phases
- [ ] Verify single backend/frontend with Muse and model router and actual STOP
- [ ] Produce owner-authorized LIVE proof before claiming working browser/Meta API
