# Post-unlock test plan

PLAN, not new PASS evidence. Historical source baseline: sealed Prompt03 manifest records419PASS/0FAIL/0timeout across nine disjoint families. This mission only executes focused preflight utility tests and static checks. Reconciliation must validate the new active target before and after each integration stage.

## Offline test environment

Run from the integration worktree, use a fresh temporary HOME for each group, put `runtime:tests:.` on PYTHONPATH and remove inherited provider credentials. A standard-library harness can use `tempfile.TemporaryDirectory`, copy the environment, remove API_KEY/AUTH_TOKEN/ACCESS_TOKEN/SECRET_KEY variables and call subprocess with a reviewed timeout. Record exact command, source/target/checkpoint SHA, counts and timeout independently. Do not persist operator secrets in logs.

`run_prompt03_regressions.py` is branch-locked to nebius-personal-ai: do not run it on a new integration branch or weaken it merely to avoid its guard. Run the unittest groups below directly with the isolated test environment. Test modules missing from target must be ported with behavior or recorded BLOCKED, not silently counted PASS. Do not execute live probe CLI; test_nebius_live_probe mocks transport.

## Exact regression baseline

All listed source modules exist in the sealed source tree. Commands below assume scoped offline fixture composition, not live transport.

| Family | Exact command after porting its contracts | Required invariant |
|---|---|---|
| Provider/routing | `python3 -m unittest tests.test_nebius_provider tests.test_nebius_cpl tests.test_nebius_routing tests.test_nebius_safe_diagnostics tests.test_nebius_live_probe -v` | Exact identity, stop-only completion, no fallback, fresh catalog/rate/budget, redacted errors, no automatic retry |
| CPL | `python3 -m unittest tests.test_cpl_service tests.test_cpl_original_contract tests.test_cpl_original_redaction tests.test_cpl_generic tests.test_cpl_evidence tests.test_cpl_wait_contract tests.test_cpl_preset tests.test_cpl_web tests.test_cpl_retrieval_root tests.test_cpl_assistant_cli -v` | Advisory scope, independent verification, redaction, deterministic termination |
| Memory/Verified Delta | `python3 -m unittest tests.test_nv07_chat tests.test_nv07_isolation tests.test_memory_patch_authority tests.test_memory_patch_persistence_ports -v` | Owner isolation, persistence, no memory effect authority, private preferences ZERO_WRITE, Verified Delta provenance |
| ServiceGuard/HTTPS/LITE | `python3 -m unittest tests.test_nv02_lite tests.test_nv02_http tests.test_nv09_service_guard tests.test_serverless_effect_transport tests.test_nebius_https_transport -v` | Sole executor, exact human binding, bounded typed effects/readback, no unsafe endpoint/redirect |
| Replay/recovery | `python3 -m unittest tests.test_nv10_guard tests.test_nv10_memory tests.test_nv10_recovery tests.test_nebius_personal_ai -v` | Receipt crash windows, UNKNOWN reconcile-before-retry, apply1 duplicate0 fixture |
| Web/API | `python3 -m unittest tests.test_competition_view tests.test_competition_evaluation tests.test_webapp -v` | Auth/CSRF boundary, no private text, no provider/target LIVE conflation, no legacy mutation bypass |
| Optional demo/UI | `python3 -m unittest tests.test_personal_ai_demo_launcher tests.test_personal_ai_demo_ui -v` | Isolated state, explicit fixture; startup no spend/approval, UNKNOWN retained |
| Security/preflight | `python3 -m unittest tests.test_changed_secrets tests.test_oct6_integration_preflight -v` | Six secret categories; safe offline Git reads; captured target refs |

## Gate levels

FAST after every stage: active target baseline relevant to the changed area, all tests required by that stage in OCT6_INTEGRATION_ORDER, and invariant suites already integrated by earlier stages. I1 requires provider/exact/CPL diagnostics, I2 adds routing/LITE, I3 adds memory/Verified Delta, I4 adds ServiceGuard/HTTPS, I5 adds Personal AI recovery. Future-stage modules are NOT_YET_INTEGRATED (no PASS claim), never prerequisites for an earlier stage. Missing contracts required by the current or a completed stage block. Run changed_secrets after each stage, or use the source scanner read-only if it is not integrated. Preflight before each stage checks exact refs and clean checkpoint. `git diff --check <captured-target>...HEAD`, temporary Python compile, JS syntax if JS changed, strict JSON validation if JSON changed, secret scan of all changed files. Any FAIL, unknown test completion or timeout prevents next stage.

MEDIUM after I5: all required I1–I5 families once in serial fresh-HOME groups; optional web/API and demo/UI stay NOT_YET_INTEGRATED or NOT_APPLICABLE until selected. After I6/I7, include every selected optional family. Exclude optional demo/UI only when those features are deliberately not integrated; record NOT_APPLICABLE and omitted names. Do not sum repeated groups as unique coverage. No fixed future PASS count is promised, since the active base may add/remove tests.

FULL ENDURANCE before any scale advance: MEDIUM plus active target's existing memory authority/security suites, bounded local fault-injection tests for crash before intent, after intent, after target apply, before receipt, after receipt/before projection, partitioned readback, corrupt receipt, replay and approval revision drift. Add race tests below once contracts exist. Define deterministic seeds, reviewed worker/concurrency/runtime caps and expected assertions before running. Paid/provider/cloud stress is NOT authorized by this plan; use local transport/store fixtures until separately approved.

## Cloud Agent Layer tests to implement after unlock

These are future acceptance cases, not currently executable modules or PASS claims:

- Immutable CloudTask digest/schema/owner/deadline validation, operation identity retained across run IDs.
- Concurrent cost reservations do not overcommit task/provider/global ceilings; unknown liability remains reserved; kill switch blocks new calls/effects but permits reconciliation.
- Atomic lease claim/renew/takeover, stale fence rejected at executor AND target; clock/partition/redelivery/restart simulations.
- Intent/outbox/receipt version transaction integrity; store serialization retries preserve operation identity.
- External target duplicate operation returns the original evidence; no receipt is fabricated from transport ACK alone.
- Verifier disagreement/insufficient evidence returns ZERO_WRITE; workers cannot self-approve or create shell commands.
- Tenant queue/store/readback isolation and bounded transient HAT egress; public events never contain prompt/reasoning/private memory.
- Cancellation/deadline prevents new dispatch while UNKNOWN operations remain reconcileable; explicit terminal states distinct from success.

## Acceptance report

For each gate record command, exact SHA, PASS/FAIL/SKIP/TIMEOUT counts and log hash. A killed process is UNKNOWN, never PASS. Fresh final verification is required after final runtime commit. No live inference, deployment, load score or distributed safety claim without its separate evidence and authorization.
