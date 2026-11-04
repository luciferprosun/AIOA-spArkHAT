# ULTRA one-system preflight — 4 November 2026

Status: IN PROGRESS. This is a measured checkpoint, not release acceptance.

## Facts and evidence

- Repository: `https://github.com/luciferprosun/AIOA-spArkHAT.git`, MIT.
- Latest qualified feature: `613737fc2b012594525e51664b24593f040e7a4a`, clean before integration. PR40 is OPEN/DRAFT, targeting main.
- Remote main independently read as `bda9d3126150b7c44f94d923ed236e10de5dba59` at approximately06:20UTC.
- Separate integration branch: `feat/ultra-one-system-20261104`, based exactly on613737f. Only the lead writes; three independent agents audited Core/security, GitHub and CPL/UI read-only.
- Prior Core CI41781087722 and default CodeQL41781083374 completed successfully for613737f. Optional advanced CodeQL was skipped by its existing owner policy. These are baseline results, not tests of the new integration.
- Existing host: UID1000, PID1274931/start_ticks58609609, loopback TLS4317, detached source `b7f4002b2a945a52e8ae08b66fc6b4ceeb418f54`, capsule `b167df78bfbd02f083a257e1d597800b044c690b9eb46f559e8deef25bbb3fa7`. Its worktree is clean. No competing listener was started.
- At06:20:34UTC the native operator status refused access. The one-hour operator lease had elapsed; source bytes and host/TLS key metadata were unchanged. An independent real PolicyKit check subsequently succeeded for the active local UID. This does not extend the old process lease, approve spending or authorize a remote effect. A qualified deployment must perform real admission again.
- ADB confirms the physical phone currently runs `eu.sparkhat.aioa.companion.cosmic4`, versionCode401, `4.1.0-cosmic`. The delivered402 APK exists but has NOT been observed installed. No install, uninstall, key extraction or pairing reset was performed.
- GitHub GET authenticated as `luciferprosun`. Repository numeric ID1247349659, public, default branchmain, licenseMIT. Authentication is host-only; no token was printed or extracted.
- A SQLite `mode=ro` inspection of the existing store found governor version11, epoch4: one COMMITTED model reservation and one UNKNOWN reservation for `chat-f15ea88b5afb499e980356edfa312dfd`, held bound0.0040435USD. The corresponding chat record remains CHAT_UNKNOWN. This is not a billing invoice or independent reconciliation.

## Architecture findings

FACT: the current `CoreIntentJournal` rejects new START while any owner reservation is UNKNOWN (`UNRESOLVED_INTENT`). No new scope, policy, epoch reset or second governor may bypass this.

FACT: current local-zero START does not support issue.create. The local sandbox route requires networkOFF. The existing MCP agent is fixture-only; its flags must stay unchanged.

FACT: no canonical live GitHub network executor exists. `github_issue_transport.py` is a codec, and the external untracked GitHub adapter refuses effects.

FACT: Native uses an inspection-only runtime. Legacy CPL owns separate trace/budget state; calling its constructor/plan is not a read-only inspection. Native CPL remains BLOCKED_NATIVE_CPL_NOT_BOUND.

RULING: implement scoped READ and truthful blocked projections using the same Core/operator channel. Do not implement or enable remote POST around the known UNKNOWN barrier. A real GitHub mutation remains a separate acceptance gate requiring independent liability resolution, a reviewed remote START contract, and exact native owner approval. This is the explicit READ fallback allowed by section4 of the owner brief, not full release acceptance.

## Preserved work

Other worktrees contained untracked pairing handoff reports, diagnostics review and `CODEX_COSMIC_FINAL_IMPLEMENTATION.md`. The external GitHub worktree contains untracked adapter/contracts. None were moved, overwritten, staged or deleted. Detached known-good Native sources remain immutable. Multiple Codex processes exist; no change was observed in the selected clean feature or live checkout.

## Pending observations

New-source regression, CodeQL, guarded Chrome rehearsal, fresh signed phone reconnect, current-source Muse response and independently verified GitHub mutation are NOT_RUN. Historical Muse success is retained as historical proof only.
