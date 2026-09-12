# Prior-art capability evolution matrix

## Reading rules

The June-1 column describes only evidence reachable from AOIA-Core
`d7e3448afa4e33d58be8babbfcc615b13dff533f`. Related behavior is marked
`IMPLEMENTED_PARTIAL` rather than treated as an exact equivalent. `NOT_FOUND` means the exact
capability was not proved in that tree; it does not deny that a neighboring idea existed.

The handwritten roadmap has no independently proved creation timestamp in the inspected
evidence. Its text alone therefore cannot establish a June plan. Post-June keys `P12`–`P54`
resolve to full commits, timestamps, paths, symbols, and tests in the evidence register below.
All registered author and committer timestamps are identical.

Current paths beginning with `src/` are repository-relative; shortened package paths such as
`nz/contracts.py` and `agent/factory.py` are under `src/aioa_cloudops_agent/`. Current comparison
classifications count only the 43 notebook rows, so the denominator and final report remain
unambiguous.

## Roadmap items 12–54

| # / capability | June-1 status | Public evidence and reachability | Post-June evolution | Current AWS equivalent | Strength | Reuse mode | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 12 Authority Bypass Adversarial Suite | `DOCUMENTED_ONLY` | `d7e3448`; reviewer/stress-test docs only; no executable exact suite. **YES** for docs, no for implementation. | `P12`: executable adversarial regression suite. | `src/aioa_cloudops_agent/safety/policy.py::DefaultDenyToolPolicy`; `tests/unit/test_safety_hardening.py`; injection-before-dispatch integration tests. | `CURRENT_STRONGER` | `KEEP_CURRENT` | Current tests are scoped to the actual five-tool AWS authority surface and durable denial outcomes. |
| 13 Audit Logger (prefix uncertain) | `IMPLEMENTED_PARTIAL` | `8c2e9e0a...` and `4f2bffec...`: hash-linked local provenance plus verifier; not the later durable audit logger. **YES**. | `P13`: `DurableAuditEvent`, append and chain verification; later summarized in HackVerse production reports. | `nz/contracts.py::AuditEvent`; `persistence/nz_dynamodb.py::append_audit_event`; append-only, redaction, trace/correlation tests. | `DIFFERENT_SCOPE` | `ARMOR_UPGRADE` | Current AWS events have stronger workflow identity and conditional durability; the later AOIA chain makes ordered omission/tamper evidence explicit. |
| 14 Static Capability Boundary Enforcement | `IMPLEMENTED_PARTIAL` | `d7e3448`: retrieval/import boundary and executor-containment tests, but no exact exported-capability scan. **YES**. | `P14`; hardened at `47fcf394f9ece47988999949df8dbf606b442258` on `2026-07-17T15:55:11+02:00`. | `agent/factory.py::CURRENT_TOOL_NAMES`, factory drift rejection, `DefaultDenyToolPolicy`, exact one-agent/five-tool tests. | `CURRENT_STRONGER` | `KEEP_CURRENT` | The current executable surface and schema are asserted directly and denied before dispatch. |
| 15 Global Write Kill Switch | `NOT_FOUND` | No exact switch in `d7e3448`; safety/approval was only adjacent. **NO**. | `P15`; hardened at `5b66890a5bed6976e7733a0f696f307a7436b678` on `2026-07-17T21:44:13+02:00`. | `config/remediation.py::SandboxRemediationSettings.live_execution_enabled` requires two false-by-default opt-ins. | `OLD_STRONGER` | `ARMOR_UPGRADE` | Current positive gates are safe while disabled; a separate negative emergency-off check would improve an intentionally enabled live executor. |
| 16 Workspace Guard / Tool Hardening | `IMPLEMENTED_PARTIAL` | `runtime/tools/executor.py`, `tests/test_executor_containment.py`, blocked-pattern policy; no stable filesystem-identity/TOCTOU guard. **YES**. | `P16`; hardened at `ba9d00e41bfa3c871b37742ddb81f2fae8bbe903` on `2026-07-21T17:19:58+02:00`. | Filesystem and arbitrary-code capabilities are `NEVER_AUTONOMOUS`; no filesystem tool is exported. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | The stronger CloudOps boundary is absence of filesystem authority, so importing a workspace writer would create risk. |
| 17 Tool Chain Fail-Closed Integration | `IMPLEMENTED_PARTIAL` | Validator, human prompt, executor containment, and public register's partial safety claim. **YES**. | `P17`; hardened test-only closure at `849b4e820ab9619d5417acd246b7d16d8e1b5890` on `2026-07-21T18:45:41+02:00`. | `tests/integration/test_human_approved_remediation_e2e.py`, `test_durable_hitl_approval_flow.py`, and policy/failure tests. | `CURRENT_STRONGER` | `KEEP_CURRENT` | Current chain composes durable proposal, native HITL, approval, idempotency, private execution, and independent verification. |
| 18 Proposal → Preview Bridge | `NOT_FOUND` | Structured model action existed, but no distinct immutable preview bridge was found. **NO**. | `P18`: `build_preview_from_action_proposal`. | `ActionProposal` is durably written before approval; `ApprovalPayload` exposes exact bounded review data. | `CURRENT_STRONGER` | `KEEP_CURRENT` | A separate artifact-preview bridge is unnecessary for the single typed EC2 action. |
| 19 Proposal Preview Gate Binding | `IMPLEMENTED_PARTIAL` | In-process approval viewed the pending action, but had no durable hash/nonce binding. **YES**. | `P19`: explicit proposal/preview/gate binding hash. | `ActionProposal.evidence_hash`, `Approval.evidence_hash`, interrupt ID, target, decision nonce, and prerequisite loader. | `CURRENT_STRONGER` | `KEEP_CURRENT` | Current binding survives restart and rejects copied, stale, cross-run, or mismatched approval. |
| 20 Action Proposal Safe Naming Protection | `IMPLEMENTED_PARTIAL` | JSON action validation and named action set existed, without the later review projection. **YES**. | `P20`: `ActionProposalSafeProjection`. | Exact `Capability` values, `CURRENT_TOOL_NAMES`, strict Pydantic fields, and unknown/alias default deny. | `CURRENT_STRONGER` | `KEEP_CURRENT` | The current dispatcher treats names as exact authority identifiers, not display text. |
| 21 Diff-Based Edit Proposal / Patch Preview | `NOT_FOUND` | No exact patch-preview subsystem. **NO**. | `P21`: hashed bounded unified-diff preview. | No filesystem/edit tool; capability is denied. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Patch automation does not help the bounded EC2 demo. |
| 22 Patch Logic Policy Check | `NOT_FOUND` | No exact patch policy. **NO**. | `P22`: `check_patch_local_policy`. | No patch surface. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Adding policy for a nonexistent capability would invite expansion. |
| 23 Human Patch Barrier | `NOT_FOUND` | No exact hash-bound patch barrier. **NO**. | `P23`: `create_human_patch_barrier` and verifier. | HITL applies only to the proposal-bound EC2 stop. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Reuse the authority pattern, not the patch capability. |
| 24 Controlled Patch Apply | `NOT_FOUND` | No bounded patch executor. **NO**. | `P24`: `apply_controlled_patch`. | No filesystem mutation. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Directly outside the frozen product. |
| 25 Post-Patch Barrier / Verification Plan | `NOT_FOUND` | No post-patch plan. **NO**. | `P25`: `build_post_patch_verification_plan`. | Independent EC2 read-back exists, but it verifies cloud state rather than files. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | The transferable concept is already native in CloudOps verification. |
| 26 Controlled Post-Patch Test (transcription uncertain) | `NOT_FOUND` | No exact controlled post-patch runner. **NO**. | `P26`: `run_controlled_post_patch_verification`; confirms this was a real later capability, not merely a note. | Current test suite is development evidence, not an agent-exposed test runner. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | An agent-callable test runner would expand authority. |
| 27 “Git Road” section marker | `NOT_FOUND` | No capability; notebook date/provenance is unproved. **NO**. | No discrete implementation commit; `P28` follows a separate hardened read-adapter foundation at `042ccb552e67338e620951baf7c8729e193d34d3`. | No Git tool. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Treat as a heading, not an implementation claim. |
| 28 Git Read-Only Governance | `NOT_FOUND` | No agent Git-governance subsystem. **NO**. | `P28`: `evaluate_git_read_governance`. | Git is development infrastructure only, never a Strands tool. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Judge workflow needs no agent Git access. |
| 29 Git Native State Checkpointing | `NOT_FOUND` | No exact Git checkpoint. **NO**. | `P29`: `create_git_state_checkpoint`. | `Checkpoint` stores workflow state/hashes, not Git state. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Current durable recovery is the relevant scoped checkpoint. |
| 30 Git Write Preview | `NOT_FOUND` | No Git write preview. **NO**. | `P30`: `GitWritePreview`. | No Git write authority. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Surface expansion only. |
| 31 Git Commit Preview | `NOT_FOUND` | No Git commit preview. **NO**. | `P31`: `create_git_commit_preview`. | No Git tool. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Surface expansion only. |
| 32 Human Commit Barrier | `NOT_FOUND` | No agent commit barrier. **NO**. | `P32`: `evaluate_git_commit_barrier`. | Human approval is reserved for the EC2 proposal. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Approval must not imply unrelated Git authority. |
| 33 Controlled Git Commit | `NOT_FOUND` | No controlled commit executor. **NO**. | `P33`: `controlled_git_commit`. | No Git mutation. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Development commits remain outside the agent. |
| 34 Git Push Governance Preview | `NOT_FOUND` | No push preview. **NO**. | `P34`: `create_git_push_preview`, with later fail-closed hardening. | No Git/network push tool. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | It would not improve CloudOps reliability. |
| 35 Controlled Git Push | `NOT_FOUND` | No controlled push. **NO**. | `P35`: `controlled_git_push`; edge tests added at `f8fc328fe59e19afc627423acba71f772c14081b`. | No Git push authority. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Explicitly excluded from the frozen architecture. |
| 36 Structured “Git” Taxonomy (handwriting corrected by history) | `NOT_FOUND` | No exact capability. **NO**. | `P36` proves the historical exact name was **structured critic taxonomy**, not Git taxonomy. | Typed `FailureKind`, failure-to-state map, and fixed policy codes cover CloudOps outcomes. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Do not add a general critic subsystem; preserve the transcription correction. |
| 37 Critic/Critical Adversarial Corpus | `DOCUMENTED_ONLY` | Stress/adversarial material existed as reviewer documentation; no executable critic corpus. **YES** for docs. | `P37`: typed critic adversarial cases and tests. | Day 12 executable injection/tool-confusion corpus on the actual dispatcher. | `CURRENT_STRONGER` | `KEEP_CURRENT` | Scoping cases to real P0 authority yields stronger proof than a general critic catalog. |
| 38 Provider Gateway Circuit | `IMPLEMENTED_PARTIAL` | Provider manager/fallback and switching existed; no circuit/rate guard. **YES** for adjacent behavior. | `P38`: `ProviderGatewayGuardState` and rate/circuit evaluation. | One pinned Bedrock model, typed dependency failures, model bounds, and no provider expansion. | `DIFFERENT_SCOPE` | `CONCEPT_ONLY` | Preserve bounded failure semantics; a multi-provider gateway would bloat the single-provider demo. |
| 39 Provider Response Schema Validation | `IMPLEMENTED_PARTIAL` | `runtime/tools/validator.py::validate_action`; structured JSON action tests. **YES**. | `P39`: dedicated provider-response schema validator/hash. | Strict Pydantic Non-Zero contracts, exact tool schemas, `SchemaCorrectionBudget`, terminal invalid-output state. | `CURRENT_STRONGER` | `KEEP_CURRENT` | Current schema failure is bounded, audited, and tied to deterministic dispatch. |
| 40 Provider Payload Expansion Governance | `NOT_FOUND` | No exact payload-expansion policy. **NO**. | `P40`: `evaluate_provider_payload_expansion_governance`. | No provider payload expansion capability. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | The pinned Bedrock boundary should remain fixed. |
| 41 Controlled Provider Expansion | `NOT_FOUND` | No exact controlled expansion. **NO**. | `P41`: human barrier and controlled expansion result. | No dynamic provider expansion. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Would weaken the one-model architecture. |
| 42 Package Install Proposal | `IMPLEMENTED_PARTIAL` | Install shell commands were classified as requiring confirmation; `tests/test_main.py::test_classify_install_command_requires_confirmation`. **YES**. | `P42`: typed package proposal and TOCTOU evidence. | Package install and shell execution are `NEVER_AUTONOMOUS`; no tool exists. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Absence is stronger for this deployed agent. |
| 43 Controlled Package Install | `IMPLEMENTED_PARTIAL` | Broad approved shell execution could run installs, but lacked a bounded package subsystem. **YES**. | `P43`: controlled installer; interpreter fallback fixed at `a74751d88c9ffbb58a7030ab53d7fa844e1fadf7`. | No package/shell executor. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Dependencies remain build-time and pinned. |
| 44 Controlled Browser Read-Only Execution | `IMPLEMENTED_PARTIAL` | Browser open/read/screenshot tools plus approval and tests existed, but browser authority was not isolated read-only. **YES**. | `P44`: typed controlled browser-read boundary. | No browser tool or arbitrary URL fetch; both are denied. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Browser access does not help the EC2 remediation path. |
| 45 Browser Automation Preview | `NOT_FOUND` | No immutable browser preview. **NO**. | `P45`: hashed automation-step preview. | No browser surface. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Surface expansion only. |
| 46 Browser Automation Governance | `IMPLEMENTED_PARTIAL` | Basic URL/action validation and approval existed; no dedicated governance policy. **YES**. | `P46`: browser automation governance evaluator. | Browser and arbitrary URL capabilities are structurally denied. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Denial is the right CloudOps control. |
| 47 Controlled Browser Automation | `IMPLEMENTED_PARTIAL` | Public runtime exposed approved browser open/click/type/read/screenshot operations with focused tests. **YES**, but broad/partial. | `P47`: controlled automation context, barrier, and executor. | No browser capability. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Do not turn the CloudOps agent into a general operator browser. |
| 48 Architecture-Native Codex/AIOA Integration Boundary | `NOT_FOUND` | No exact coding-assistant boundary. **NO**. | `P48`: inert typed coding-assistant envelopes/review. | Codex is a development tool, not a runtime principal tool. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Runtime integration would confuse development authority with agent authority. |
| 49 MCP — Model Context Protocol | `DOCUMENTED_ONLY` | 28 May future-compatibility note says `Scope: notes only; no implementation`. **YES** for docs. | `P49`: inert MCP declarations/proposal/review boundary with tests. | No MCP server/client/tool; five-tool surface is direct Strands. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | MCP adds no value to the one-scenario demo. |
| 50 Async I/O Orchestration | `NOT_FOUND` | No exact async orchestration boundary. **NO**. | `P50`: typed operation DAG/review boundary. | Deterministic sequential investigation, one primary agent, bounded polling only. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Concurrency would add ordering ambiguity without a demonstrated need. |
| 51 Feedback and Auto-Recovery Loop | `NOT_FOUND` | Model next-action behavior existed, but no proved bounded recovery loop. **NO**. | `P51`: inert typed recovery-plan evaluator. | `RecoveryCoordinator`, lease/version checks, lost-ACK read-back, schema correction and typed failures. | `CURRENT_STRONGER` | `KEEP_CURRENT` | Current recovery is deterministic and never converts feedback into authority or retries a mutation. |
| 52 Minimal Codex Live Flow | `NOT_FOUND` | No Codex live-flow capability. **NO**. | `P52`: inert request/handoff/observation/output review boundary. | No runtime Codex integration. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Development workflow is outside the deployed agent. |
| 53 Local Agent Loop | `IMPLEMENTED_PARTIAL` | `runtime/main.py::AgentRuntime` ran a local model/action/result loop with approval; not the later typed inert boundary. **YES**. | `P53`: local objective/state/candidate review boundary. | One bounded Strands agent with deterministic application control. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | A second/general local loop would violate the frozen architecture. |
| 54 Provider Agent Loop | `IMPLEMENTED_PARTIAL` | Provider manager/fallback and orchestration existed, but no isolated typed provider-loop boundary. **YES**. | `P54`: provider input evidence/candidate review boundary. | One pinned Bedrock provider behind one Strands agent. | `DIFFERENT_SCOPE` | `OUT_OF_SCOPE` | Dynamic provider loops do not improve the P0 scenario. |

## Post-June exact evidence register

Each entry names the first exact capability commit. Source and test paths are from that commit.

| Key | Exact commit and timestamp | Source symbol/path | Executing test evidence |
| --- | --- | --- | --- |
| `P12` | `1bc059ffddfc60ac8076fa4e393828d94ff8da77`, `2026-06-26T06:03:24+02:00` | adversarial suite commit | `tests/test_authority_bypass_adversarial_1a.py::AuthorityBypassAdversarial1ATests` |
| `P13` | `a1aef86830d8570ac5f1070504f599901a43ae8e`, `2026-06-26T06:44:07+02:00` | `runtime/audit/durable_log.py::append_durable_audit_event`, `verify_durable_audit_log` | `tests/test_durable_audit_ledger_1a.py` |
| `P14` | `fcf20f1cd9e59cad2f5182caa27b00502020251e`, `2026-06-26T06:59:08+02:00` | static AST/import scan | `tests/test_static_capability_boundary_1a.py` |
| `P15` | `e8af8f504cc59cf84d15a1f33d822e6326323571`, `2026-06-26T07:09:07+02:00` | `runtime/safety/write_kill_switch.py::check_write_kill_switch_file` | `tests/test_global_write_kill_switch_1a.py` |
| `P16` | `eb3b176af80e37c19948fa0a5c35ba795028ca87`, `2026-06-26T07:26:50+02:00` | `runtime/safety/workspace_guard.py::require_workspace_guard_allowed` | `tests/test_workspace_guard_toctou_1a.py` |
| `P17` | `d1869ece055adae98cba0f4f79b8cb5ce3e7b65b`, `2026-06-26T07:42:49+02:00` | full-chain composition test | `tests/test_full_chain_fail_closed_1a.py` |
| `P18` | `7c38cb307c0492a9c2e2d28152b0d6d071d6d2e8`, `2026-06-26T10:26:25+02:00` | `runtime/bridges/proposal_to_preview.py::build_preview_from_action_proposal` | `tests/test_proposal_to_preview_bridge_1a.py` |
| `P19` | `f2beb1dac1f140e5f538dace870c9ddfbcebe527`, `2026-06-26T11:43:47+02:00` | `build_proposal_preview_gate_binding` | `tests/test_proposal_preview_gate_binding_1a.py` |
| `P20` | `faeb96f2ad52fea73676467bee43b29e30b5688f`, `2026-06-26T12:13:09+02:00` | `runtime/schemas/action_proposal_projection.py::project_action_proposal_for_review` | `tests/test_action_proposal_safe_naming_projection_1a.py` |
| `P21` | `b399518e1551c292f96fd014185d4e9b0a85b41a`, `2026-06-26T13:55:35+02:00` | `runtime/patches/patch_preview.py::build_patch_preview` | `tests/test_diff_based_edit_proposal_patch_preview_1a.py` |
| `P22` | `d25031311c4d5eb9700f09d23632a3a4256b5f3c`, `2026-06-26T16:00:51+02:00` | `runtime/patches/patch_policy.py::check_patch_local_policy` | `tests/test_patch_local_policy_check_1a.py` |
| `P23` | `f7365e70871217135889c1beed05ffac6adb6aa9`, `2026-06-26T16:49:03+02:00` | `runtime/patches/patch_barrier.py::create_human_patch_barrier` | `tests/test_human_patch_barrier_1a.py` |
| `P24` | `8dc0be2f7088994b8a6234513b387d9a7d47b68b`, `2026-06-27T08:28:44+02:00` | `runtime/patches/controlled_patch_apply.py::apply_controlled_patch` | `tests/test_controlled_patch_apply_1a.py` |
| `P25` | `e511d1abded438debee804627681666fba6e2499`, `2026-06-27T08:52:43+02:00` | `build_post_patch_verification_plan` | `tests/test_post_patch_verification_plan_1a.py` |
| `P26` | `a277cb7e777c32bcc208680b9140d6dbc11812f0`, `2026-06-27T10:12:20+02:00` | `run_controlled_post_patch_verification` | `tests/test_post_patch_controlled_test_integration_1a.py` |
| `P28` | `4af2537698778bb3bda6b740e0ebccfa938f5947`, `2026-06-27T18:55:48+02:00` | `runtime/git_ops/git_governance.py::evaluate_git_read_governance` | `tests/test_git_read_only_governance_1a.py` |
| `P29` | `d630a78bf62ad532db37737670fecfe8d1b1d3db`, `2026-06-28T06:35:33+02:00` | `runtime/git_ops/git_checkpoint.py::create_git_state_checkpoint` | `tests/test_git_native_state_checkpoint_1a.py` |
| `P30` | `ee7497a4fd6b1443298da8ee9a295e8c41896cc5`, `2026-06-28T06:53:20+02:00` | `runtime/git_ops/git_write_preview.py::GitWritePreview` | `tests/test_git_write_preview_1a.py` |
| `P31` | `9b9208b56d8dea385599f461d72de8774a803529`, `2026-06-28T07:06:47+02:00` | `runtime/git_ops/git_commit_preview.py::create_git_commit_preview` | `tests/test_git_commit_preview_1a.py` |
| `P32` | `79dbb8bf9d3a0018d278ea145af6a4516fcfe7e9`, `2026-06-29T07:49:30+02:00` | `runtime/git_ops/git_commit_barrier.py::evaluate_git_commit_barrier` | `tests/test_git_commit_barrier_1a.py` |
| `P33` | `1ea547a47ff37150476d5bb44dd1a35bc67eb276`, `2026-06-29T09:05:50+02:00` | `runtime/git_ops/controlled_git_commit.py::controlled_git_commit` | `tests/test_controlled_git_commit_1a.py` |
| `P34` | `456d39bee9f9d12671826bc8d4c75b4f25cfccf5`, `2026-07-04T07:11:07+02:00` | `runtime/git_ops/git_push_preview.py::create_git_push_preview` | `tests/test_git_push_governance_preview_1a.py` |
| `P35` | `eccbcd912c050ad8bfe36cc7dba1c8a3d4312243`, `2026-07-04T15:17:55+02:00` | `runtime/git_ops/git_controlled_push.py::controlled_git_push` | `tests/test_controlled_git_push_1a.py` |
| `P36` | `651c51f819e85d9d558b0d55b06d6826b2782344`, `2026-07-04T17:48:52+02:00` | `runtime/providers/critic_taxonomy.py::CriticTaxonomyEntry` | `tests/test_structured_critic_taxonomy_1a.py` |
| `P37` | `1279a5aa1ee3bf52a28f52ebb188b88def42e058`, `2026-07-04T18:25:19+02:00` | `runtime/providers/critic_adversarial_corpus.py::default_critic_adversarial_cases` | `tests/test_critic_adversarial_corpus_1a.py` |
| `P38` | `b3a4a9e4c90f84aeacd6eda63c22b200c259ce4f`, `2026-07-04T18:56:11+02:00` | `runtime/providers/provider_gateway_guard.py::evaluate_provider_gateway_guard` | `tests/test_provider_gateway_circuit_rate_guard_1a.py` |
| `P39` | `e5f22b6ee3647ad598f0852936fcd3d08fde1b2d`, `2026-07-05T07:09:57+02:00` | `validate_provider_response_schema` | `tests/test_provider_response_schema_validation_1a.py` |
| `P40` | `c9cdc2bb6038b5fd673b500cd639b583cd1d7bc7`, `2026-07-05T07:24:50+02:00` | `evaluate_provider_payload_expansion_governance` | `tests/test_provider_payload_expansion_governance_1a.py` |
| `P41` | `d0465d068519c10878e314a0d14bfee876c85ae8`, `2026-07-05T07:36:52+02:00` | `runtime/providers/provider_controlled_expansion.py::apply_controlled_provider_expansion` | `tests/test_controlled_provider_expansion_1a.py` |
| `P42` | `dff45c6af7acea63f6dda9b681be8091c3295c80`, `2026-07-05T15:49:24+02:00` | `runtime/package_ops/package_install_proposal.py::propose_package_install` | `tests/test_package_install_proposal_1a.py` |
| `P43` | `5ed23979f4733f2cc9ad30e34b91dd7b8eebdc29`, `2026-07-05T16:52:01+02:00` | `runtime/package_ops/controlled_package_install.py::execute_controlled_package_install` | `tests/test_controlled_package_install_1a.py` |
| `P44` | `0d1a23384841ba51199212c31385a7ecedd48f75`, `2026-07-05T18:54:06+02:00` | `runtime/browser_ops/controlled_browser_read.py::ControlledBrowserReadRequest` | `tests/test_controlled_browser_read_1a.py` |
| `P45` | `67bcea8e38535ff1726e61a3ecfdac1e3d24f8db`, `2026-07-05T20:21:55+02:00` | `runtime/browser_ops/browser_automation_preview.py::create_browser_automation_preview` | `tests/test_browser_automation_preview_1a.py` |
| `P46` | `d13c276751b4f2005ba83fabbbd8f72d5b7a727e`, `2026-07-06T06:22:50+02:00` | `evaluate_browser_automation_governance` | `tests/test_browser_automation_governance_1a.py` |
| `P47` | `9fe25e72d25b34bb4e3bbc3141b465dfdb5c99bc`, `2026-07-06T09:51:00+02:00` | `execute_controlled_browser_automation` | `tests/test_controlled_browser_automation_1a.py` |
| `P48` | `6a6301a85c06511ddc002bca1b85a58c7ce27364`, `2026-07-06T10:47:56+02:00` | `runtime/integration_boundaries/coding_assistant_boundary.py::CodingAssistantBoundaryReviewResult` | `tests/test_coding_assistant_boundary_1a.py` |
| `P49` | `d1b8839f4251bf4030b63700337c15667b842b03`, `2026-07-06T11:20:42+02:00` | `runtime/integration_boundaries/mcp_boundary.py::MCPBoundaryReviewResult` | `tests/test_mcp_boundary_1a.py` |
| `P50` | `44f2e741fd61b2e1d64c18d2c00d9eea5454e2d0`, `2026-07-06T11:49:49+02:00` | `runtime/orchestration/async_io_orchestration.py::evaluate_async_io_orchestration` | `tests/test_async_io_orchestration_1a.py` |
| `P51` | `0912633cb267050872d84c1f51c6bff951691e43`, `2026-07-06T12:19:40+02:00` | `runtime/orchestration/feedback_recovery_loop.py::evaluate_recovery_plan` | `tests/test_feedback_recovery_loop_1a.py` |
| `P52` | `a3b4585e1b56d2e0a24cffba26b40c692327355b`, `2026-07-06T13:03:09+02:00` | `runtime/live_flows/codex_live_flow.py::evaluate_codex_live_flow` | `tests/test_codex_live_flow_1a.py` |
| `P53` | `76112f9aa104e49cc6b3f914595658f758af344a`, `2026-07-06T13:32:48+02:00` | `runtime/agent_loops/local_agent_loop.py::evaluate_local_agent_loop_iteration` | `tests/test_local_agent_loop_1a.py` |
| `P54` | `62107bc6f78e4861d2c7d151f167c726ab22d9c8`, `2026-07-06T14:01:05+02:00` | `runtime/agent_loops/provider_agent_loop.py::evaluate_provider_agent_loop_iteration` | `tests/test_provider_agent_loop_1a.py` |

No `P12`–`P54` commit is reachable from `d7e3448`. Several later modules are intentionally inert
review/boundary contracts rather than live authority; code plus tests does not turn them into a
June implementation or prove production deployment.

## Additional material public-baseline findings

| Capability | June-1 forensic status | Evidence | Current treatment |
| --- | --- | --- | --- |
| Evidence write boundary | `IMPLEMENTED_PARTIAL` | `5b7e6da8bc4d94afb3145c811fbb729b2beac943`; `MemoryStore.append_evidence`; two focused test modules | Prior-art concept; current AWS durable contracts and repositories are independently authored. |
| Append-only provenance | `IMPLEMENTED_AND_TESTED` within its narrow local scope | `8c2e9e0a8683df716e8fc8941086ad1413dcf2c4`; `AppendOnlyProvenanceStore`; append tests | Concept retained; no source reuse. |
| Provenance verification | `IMPLEMENTED_AND_TESTED` for local chain integrity, not truth | `4f2bffecbe2b72ff67317be56c10552ccf682150`; `verify_provenance_chain`; verification tests | Current independent verification concerns AWS state and success evidence, a different scope. |
| Provider switching | `IMPLEMENTED_AND_TESTED` | `78ab53851ac8f2e70bc48cead44582aa05c9bfe3`; provider config/local command; `tests/test_main.py` | Do not import; current one-model pin is deliberate. |
| Human approval | `IMPLEMENTED_PARTIAL` | executor/TUI prompt and tests; public register says Partial | Superseded by native Strands HITL and durable proposal/nonce binding. |
| Runtime safety | `IMPLEMENTED_PARTIAL` | validator, executor containment, governance docs/tests; public register says Partial | Superseded for scope by exact default-deny AWS policy and typed failures. |
| Replay verification | `DOCUMENTED_ONLY` after evidence reconciliation | external register says Partial, but detailed governance status says `NOT_STARTED` and no verifier was found | Do not claim implementation; current restart recovery is independently tested. |
| MCP adapter | `DOCUMENTED_ONLY` | 28 May notes explicitly say no implementation | Remains out of scope. |

## Counts and conclusion

For notebook items 12–54:

- total classified: **43**;
- `IMPLEMENTED_AND_TESTED` by June 1: **0** exact notebook capabilities;
- `IMPLEMENTED_PARTIAL` by June 1: **15**;
- `DOCUMENTED_ONLY` by June 1: **3**;
- `PLANNED_ONLY` by June 1: **0** (notebook date was not proved);
- `LOCAL_ONLY_UNPUBLISHED` by June 1: **0 proven**;
- `NOT_FOUND` by June 1: **25**;
- exact post-June capability implementations/boundaries: **42**;
- section marker/non-capability: **1** (`27`).

Current AWS reuse classification for those same 43 rows:

- `KEEP_CURRENT`: **9**;
- `ARMOR_UPGRADE`: **2**;
- `CONCEPT_ONLY`: **1**;
- `OUT_OF_SCOPE`: **31**;
- `NEEDS_MORE_EVIDENCE`: **0**.

The high-value conclusion is not that the June system already contained the roadmap. It did not.
The defensible narrative is that a public conceptual skeleton existed, most roadmap-specific
armor arrived later, and the current AWS project independently implemented a narrower and often
stronger Non-Zero/Strands control plane.
