# AIOA spArkHAT architecture

Canonical repository: `luciferprosun/AIOA-spArkHAT`. `main` is the release target; integration branches are temporary review work. The current product surface is White Hole Mission Control at `/devices`, backed by the existing Native composition. Historical hackathon applications are provenance sources, not additional products to start.

## Runtime path

Linux launcher → OS/PolicyKit owner admission → private Native socket and HTTPS console session → CoreAdmission → existing TransactionRunner/SQLite → domain service → qualified provider/tool → audit/outbox and signed result → Mission Control.

Android uses the same signed mobile protocol and Core. It does not receive Linux owner privileges or a second authority service. HTTP reachability, a tailnet address, a model response, a grammar match and a proposal fingerprint grant no execution authority.

The Native root is `runtime/meta_hackathon/runtime_adapter.py`; the historical directory name does not create a separate product. It constructs one Core, transaction runner, warrant ledger, MissionService and host signer. Legacy `AgentRuntime` is used in inspection mode. Do not activate its alternate store/provider lifecycle to fill a missing Native binding.

## Canonical capabilities

| Capability | Existing module / entrypoint | Current boundary |
| --- | --- | --- |
| Conversational Muse | `chat_session.send` → `chat.propose/approve` → exact Meta provider | Owner session plus intentional Send; bounded request and one attempt; advisory text |
| GitHub/local Git READ | `native_tools.dispatch` → `mcp_bridge.native_read` | Fixed recipe, bounded output/deadline, source-bound receipt |
| Code proposal and remote Git | `github_write` → `CoreRemoteGitRoute` → ServiceGuard | Exact owner review and scoped App credential; independent GET; live qualification blocked |
| Command advice | `advisory.dispatch(command_advice)` → recovered grammar | Pure local classification; no shell/subprocess or permission inference |
| Email draft preview | `advisory.dispatch(mail_preview)` → canonical MIME verifier | Local preparation with digest-only Core audit; no account connection or sending |
| CPL | `critical_loop.service`, `review`, `mission.lite_cpl` | One existing 1+3+1 contract; `build_native_cpl_preview` is read-only, zero calls; paid/executing binding disabled |
| Worker/local publish | `agent_operations`, `mission.tools`, sandbox and Git contracts | `BLOCKED_NATIVE_WORKER_NOT_CERTIFIED`; existing fixture binding retained |
| Memory and knowledge | `memory_patch.service`, `learning`, `personal` | `INTEGRATED_INERT` / `MEMORY_CONSENT_REQUIRED`; borrow Core ports after explicit HAT/scope/consent |
| NonZero | `nonzero_cloudops` | Native domain contract retained; do not restore historical checkpoint/effect stores |

See [feature evidence](../audit/2026-11-05/FEATURE_MATRIX.csv) and the [dependency graph](../audit/2026-11-05/DEPENDENCY_GRAPH.md). A source-valid module, a wired entrypoint, an offline contract test and a live production effect are separate qualifications.

## State and authority

The existing SQLite ledger remains the effect/audit truth. Preview records contain no email addresses, body or subject. Conversation text remains bounded process memory, not automatically saved knowledge. New semantic knowledge requires explicit consent and proper HAT selection.

Unknown outcomes and existing money liabilities survive sessions and source changes. No automatic retry follows an ambiguous effect. A browser refresh may repair stale presentation but cannot approve, settle, replay or change a Core record's authority.

GitHub authentication is repository-scoped App installation authentication. Broad CLI OAuth is restricted to existing qualified READ tooling and development operations; it is not the runtime write credential. The old issue proposal has no issue-create actuator and never claims a code commit.
