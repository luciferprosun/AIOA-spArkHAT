# Muse → AIOA → GitHub: integration gap analysis

Audit date: 2026-11-05. This is a read-only audit and implementation plan, not a
remote WRITE receipt. No model call or remote demonstration mutation was made
by the auditing assistant.

## Verified starting point

| Item | Observation | Consequence |
| --- | --- | --- |
| Product repository | `luciferprosun/AIOA-spArkHAT`, main `2be99da7aa07f7eb5faa9459fe8a78c5d0b6653a` | Main has not been replaced or merged. |
| Active Native | `235c8591bbee807061e966d59ae2f0968ae6ef07`, loopback 4317, existing SQLite profile | Preserve source seal, TLS, owner identity, paired devices and journal. |
| PR #44 | Draft, open, head `235c8591`, includes direct owner chat session and console transport fix | Separate product change; not automatically approved for merge by this WRITE task. |
| Earlier WRITE candidate | `37c9e7afc7277d1bbb2c1690a57c17dedd8de285` | Changes issue proposal target only; does not implement remote dispatch. |
| Demonstration repository | `luciferprosun/AIOA-spArkHAT-Meta-Hackathon-2026`, repository ID `1445911975` | Sole permitted future WRITE target. |
| Demonstration main | GitHub GET returned `e655ea94527cff9ba9066ef30c7976d5eda16c51` | Observation only; refresh and bind exact base before owner approval. |
| Chat acceptance | Two owner-submitted LIVE responses verified at 03:12 and 03:13 UTC; third at 03:18 returned `META_INCOMPLETE_UNKNOWN` | Chat reliability repair is a separate prerequisite; no automatic retry. |
| Current liabilities | Old UNKNOWN retained; new 03:18 UNKNOWN also retained | Remote START must remain `BLOCKED_OWNER_LIABILITY_UNKNOWN`. |

The integration checkout initially branches from `235c8591` because the active
journal already uses the explicitly owner-enabled money-policy v3 reader. This
is a development dependency, not permission to merge PR #44. Returning to old
main against the current journal is not a safe rollback. Release requires an
explicitly reviewed dependency/merge sequence and a compatible state reader.

## Existing components and missing connections

| Component | State | Evidence / reuse boundary |
| --- | --- | --- |
| Native owner authentication, Core identity, SQLite audit | EXIST | `runtime/meta_hackathon/runtime_adapter.py`, `runtime/mobile_gateway/operator_chat.py`; native profile and console tests. Genuine PolicyKit owner admission. |
| Typed Muse chat, provider receipt, exact spend warrant | EXIST | `runtime/meta_hackathon/chat.py`, `chat_session.py`, `runtime/providers/meta_model_api.py`, `meta_receipts.py`; provider/service/native session tests. Text alone conveys no execution authority. |
| Model proposal provenance | PARTIAL | `runtime/meta_hackathon/native_tools.py:proposal` requires a successful current-source LIVE chat result and records a signed proposal. Current parser permits only `issue.create`, against the product repository. |
| Old candidate `37c9e7a` | PARTIAL | Narrows issue target to demonstration repository; no network executor, no enabled capability. Do not transplant whole historical branches. |
| Local GIT_COMMIT | EXIST | `runtime/mission/git_publish.py`, `git_publish_worker.py`, `git_worker.py`; local immutable plan, deterministic object/tree verification, network OFF sandbox. This is not a remote effect. |
| Agent operation workflow | PARTIAL | `runtime/meta_hackathon/agent_operations.py`, `mission_service.py`; real Core journal/warrants, but trusted binding is `offline-fixture`/MOCK and local sandbox recipes. Preserve that barrier. |
| Core intent START, outbox, reconciliation | EXIST | `runtime/mission/intent.py`: atomic consumed warrant/reservation/held outbox; first-dispatch marker; subsequent delivery readback only. Owner-wide unresolved intent and UNKNOWN checks already fail closed. |
| Remote zero-currency START contract | NOT_BOUND | Existing local-zero v2 checks `aioa.local-operation.v2`; a remote effect must not be mislabeled local to reuse it. Add an explicit reviewed version on the same journal. |
| Core route and ServiceGuard | PARTIAL | `runtime/mission/tools.py` has a GitHub capability; `CoreServiceGuard.dispatch_registered_local` validates the registered local route and releases executor outside retryable transactions. Native remote route is absent. Extend this authority path; no parallel ledger or guard. |
| GitHub MCP | PARTIAL | `runtime/mcp_bridge/github_issue_transport.py` is a mailbox codec, not authenticated GitHub HTTP. `native_read.py` supplies genuine signed READ observations, currently for product repository. |
| Historical remote transport | PARTIAL / unsuitable as-is | `nebius-nemotron-integration-20261028/runtime/prototype/git_transport.py` has remote readback patterns but old sealed-library/credential/target assumptions and force-with-lease logic. Do not copy its credential handling or push path. |
| Scoped credential | NOT_BOUND | No validated demonstration-only installation token or fine-grained PAT has been bound. Existing broad development `gh` authorization is not a runtime credential. |
| Model-generated file manifest | NOT_BOUND | Need strict UTF-8 create-only files under `agent-demo/`, full content/diff/hash/base/source binding, path/mode/size checks and no executable auto-load locations. |
| Exact remote owner warrant | NOT_BOUND | Chat spending session cannot authorize GitHub. Each effect requires exact repository ID/base SHA/branch/manifest/operation/expiry and new operation ID. |
| Remote executor and independent GET | NOT_BOUND | Need create-only unique branch, bounded commit and PR, verified ref/commit/tree/blob/PR identity from separate GET requests. No mutation retry after ambiguous response. |
| Durable signed remote receipt | NOT_BOUND | Existing host signing identity and Core record/audit/outbox are reusable. Receipt must bind the independent observations and survive restart. |
| Mission Control remote operation UI | NOT_BOUND | Reuse existing panel; show proposal → exact owner review → dispatch → verified receipt, with genuine link or concrete blocked/unknown reason. |

## Safety and release decisions

1. Audit original liability records, intent/outbox and available provider
   readback without changing their state. A new request, scope, epoch, database,
   repository or governor cannot erase or evade an old liability.
2. Implement and test remote composition offline against the existing Core,
   guard and journal. Keep production WRITE disabled until the complete remote
   route and independent verification pass. Offline fixtures are not LIVE proof.
3. Register a versioned remote contract, not a widened local network-OFF grant.
   Credential permissions are limited to demonstration repository Contents and
   Pull Requests; model, browser prompts and receipts never receive credentials.
4. Only a new unique branch may be created. No force push, merge, main update,
   workflow change, settings change, path traversal, symlink or submodule write.
5. Lost ACK, conflict or rate/service errors yield retained UNKNOWN and read-only
   reconciliation, never another automatic mutation attempt.
6. CI must pass on the exact release SHA. Existing CodeQL run is gated and
   SKIPPED; do not call it PASS. Merge, production activation and LIVE acceptance
   require their corresponding owner decisions after a concrete reviewable build.

## Stage A result

The missing bridge is the registered remote Core/ServiceGuard execution route,
not local Git and not a new autonomous framework. The present Native cannot
perform the required remote code commit. A live attempt is currently blocked by
retained liabilities as well as the missing route, exact warrant and scoped
credential. Offline integration remains possible without altering those facts.

Private original record evidence is retained outside the repository in
`AIOA_MUSE_GITHUB_WRITE_PRIVATE_20261105`. Public reports contain no prompt text,
credential or host private key.
