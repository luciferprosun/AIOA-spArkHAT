# Gmail Integration Map — branch-only G0

**Current scope:** Python data contracts; Core bridge only as an unimplemented Protocol.

| Surface | Actual public source | Gmail decision |
|---|---|---|
| Packaging | pyproject.toml includes runtime.* | Add runtime.communication without a second install |
| Owner identity | runtime/core_admission.py | Process-local principal is NOT a remote real-human signing authority |
| Human warrant | runtime/mission/warrant.py and tests/test_core_warrant.py | Must re-inspect and bind exact final MIME/source after S34 |
| MCP | runtime/mcp_bridge/policy.py | Gmail effect MUST NOT be smuggled in via a READ tool |
| Offline approvals | runtime/mcp_bridge/approval.py | Never accept public fixture test key as send permission |
| ServiceGuard | runtime/service_guard/* | Reuse actual native effect discipline later; no second policy core |
| Memory/HAT | runtime/knowledge/* and runtime/memory_patch/* | Reply evidence staging only after separately approved restricted-scope access |
| Mobile | Existing mobile READ contracts | Display only until real owner identity and secure transport accepted |
| GOLD72 | Isolated Linux evidence | Never alter sealed candidate / running process from this branch |
| Chromium/Muse | Future adapter | No Chromium code/config this phase |

G1 contracts reject new email actions by default. Only a future production implementation of CoreMailEffectGate, independently tested against the pinned native runtime, may connect Gmail send. Record any divergence when integrating with the more recent isolated Linux Sprint34 source.
