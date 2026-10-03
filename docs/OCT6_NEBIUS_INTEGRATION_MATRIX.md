# October 6 Nebius integration matrix

Source snapshot: `ea485478321f769857ba3380bdfd440030953439`; frozen base `d26266e54ee940d7ada30aa02783dc697618a72c`. Inventory includes all 25 unique commits, including two merges. Files are first-parent diffs: merge payload is listed rather than hidden. This mission adds preparation commits later; inventory those with preflight and retain them as documentation/read-only tooling, not product runtime.

Priority P0 = provenance only, P1 = provider foundation, P2 = guarded cloud primitives, P3 = recovery/contracts, P4 = optional offline tooling, P5 = optional demonstration. Dispositions describe future work, not executed integration.

Test labels identify existing suites and the sealed historical evidence, not individual-commit PASS claims. Prompt03 sealed coverage is 419 PASS /0 FAIL /0 timeout across disjoint families; failed experiments and interrupted runs remain in history. New target must rerun tests. See `OCT6_POST_UNLOCK_TEST_PLAN.md`.

## 00e8c03d59a2cd3fae86d3e5c01f8097f6d92245

feat(nebius): add fail-closed Token Factory provider

- Category: **CORE_REQUIRED**; disposition/priority: **RECREATE_CLEANLY P1**.
- Dependencies: active ProviderPort/config.
- Authority/semantic impact: Advisory-only Nebius adapter; fail closed, no fallback.
- Test evidence/validation: nebius_provider.
- Files touched (first parent):
  - `.env.example`
  - `.gitignore`
  - `runtime/providers/__init__.py`
  - `runtime/providers/config.py`
  - `runtime/providers/nebius.py`
  - `tests/test_nebius_provider.py`

## f34e4ed41fcaaa8c29647734e48bfc103d78a047

feat(nebius): add locked Personal AI competition profile

- Category: **CORE_REQUIRED**; disposition/priority: **CONCEPTUAL_SQUASH_WITH_PROVIDER P1**.
- Dependencies: 00e8c03.
- Authority/semantic impact: Locked competition identity must not grant effects.
- Test evidence/validation: nebius_provider.
- Files touched (first parent):
  - `runtime/providers/config.py`
  - `tests/test_nebius_provider.py`

## c152514eb0219d1edcc64b2d5b75ec8100dabae5

feat(nebius): route CPL exact calls through Token Factory

- Category: **CORE_REQUIRED**; disposition/priority: **RECREATE_CLEANLY P1**.
- Dependencies: 00e8c03 + active CPL service.
- Authority/semantic impact: Exact CPL transport retains role/authority separation.
- Test evidence/validation: nebius_cpl, nebius_provider.
- Files touched (first parent):
  - `runtime/critical_loop/service.py`
  - `runtime/providers/config.py`
  - `runtime/providers/exact.py`
  - `runtime/providers/nebius.py`
  - `tests/test_nebius_cpl.py`
  - `tests/test_nebius_provider.py`

## e24aa767135d4df366b14816bbb31335dd136f5c

feat(nebius): bridge CPL corrections into verified model experience

- Category: **OPTIONAL**; disposition/priority: **PORT_TEST_INTENT P3**.
- Dependencies: active memory/Verified Delta implementation.
- Authority/semantic impact: Test-only correction evidence; no new learning authority implementation in this commit.
- Test evidence/validation: nv07_chat.
- Files touched (first parent):
  - `tests/test_nv07_chat.py`

## a0ea11d815edf9bdb8e38b230212a42201f8d46c

feat(nebius): add bounded live readiness probe

- Category: **OPTIONAL**; disposition/priority: **RECREATE_FINAL_TOOL_ONLY P4**.
- Dependencies: exact provider + bounded authorization.
- Authority/semantic impact: Probe is paid only with explicit separate authorization.
- Test evidence/validation: nebius_live_probe.
- Files touched (first parent):
  - `scripts/nebius_live_probe.py`
  - `tests/test_nebius_live_probe.py`

## 0c32fd59e06c380b9c3be6bd09b2981ee3484ae2

merge(nebius): add live readiness gate

- Category: **EVIDENCE_ONLY**; disposition/priority: **LEAVE_HISTORY P0**.
- Dependencies: a0ea11d.
- Authority/semantic impact: Merge provenance; do not cherry-pick merge and payload twice.
- Test evidence/validation: nebius_live_probe.
- Files touched (first parent):
  - `scripts/nebius_live_probe.py`
  - `tests/test_nebius_live_probe.py`

## 1949ccf712a5088c422f0263fbfaee35ed220c85

merge(nebius): add verified model experience bridge evidence

- Category: **EVIDENCE_ONLY**; disposition/priority: **LEAVE_HISTORY P0**.
- Dependencies: e24aa76.
- Authority/semantic impact: Merge provenance/test payload; no new runtime Verified Delta code.
- Test evidence/validation: nv07_chat.
- Files touched (first parent):
  - `tests/test_nv07_chat.py`

## 5871f254b13dda6e1a26801747bcff0f3bb495f1

Add bounded Nebius routing and serverless guard target

- Category: **CLOUD_LAYER_REQUIRED**; disposition/priority: **SPLIT_AND_RECREATE P2**.
- Dependencies: provider + existing LITE/ServiceGuard.
- Authority/semantic impact: Budget routing and typed worker target; preserve existing scheduler and effect executor.
- Test evidence/validation: nebius_routing, serverless_effect_transport, nv02_lite.
- Files touched (first parent):
  - `deploy/nebius_serverless/README.md`
  - `deploy/nebius_serverless/deployment.json`
  - `evidence/cloud_activation/catalog_20261003T061407Z.json`
  - `evidence/cloud_activation/live_smoke_20261003T061504Z.json`
  - `reports/cloud_activation_2026-10-03.md`
  - `runtime/mission/lite_chat.py`
  - `runtime/mission/lite_cli.py`
  - `runtime/mission/lite_contracts.py`
  - `runtime/mission/lite_runtime.py`
  - `runtime/providers/nebius_routing.py`
  - `runtime/providers/nvidia.py`
  - `runtime/service_guard/serverless_worker.py`
  - `runtime/service_guard/service.py`
  - `runtime/service_guard/target.py`
  - `scripts/nebius_live_probe.py`
  - `tests/test_nebius_live_probe.py`
  - `tests/test_nebius_routing.py`
  - `tests/test_serverless_effect_transport.py`

## 74a0db033b72b30a53414ebff73e3a4a8c88ec98

docs: plan Nebius Personal AI vertical slice

- Category: **EVIDENCE_ONLY**; disposition/priority: **LEAVE_HISTORY P0**.
- Dependencies: Prompt02 source history.
- Authority/semantic impact: Plan only; no runtime authority impact.
- Test evidence/validation: not an executable claim.
- Files touched (first parent):
  - `docs/superpowers/plans/2026-10-03-nebius-personal-ai-vertical-slice.md`

## 87a18acee1b7866fef6db25573e5ab55304ae073

fix(nebius): harden bounded live smoke diagnostics

- Category: **OPTIONAL**; disposition/priority: **CONCEPTUAL_SQUASH_PROBE P4**.
- Dependencies: a0ea11d.
- Authority/semantic impact: Bounded probe hardening, not inference authorization.
- Test evidence/validation: nebius_live_probe.
- Files touched (first parent):
  - `scripts/nebius_live_probe.py`
  - `tests/test_nebius_live_probe.py`

## 37ce4d612b10b7e370e96d07110c4e2c515cc716

feat(nebius): add guarded serverless HTTPS transport

- Category: **CLOUD_LAYER_REQUIRED**; disposition/priority: **RECREATE_CLEANLY P2**.
- Dependencies: 5871f25 + active typed transport.
- Authority/semantic impact: HTTPS effect boundary, safe endpoint validation, no automatic retries.
- Test evidence/validation: nebius_https_transport.
- Files touched (first parent):
  - `.env.example`
  - `deploy/nebius_serverless/README.md`
  - `runtime/service_guard/__init__.py`
  - `runtime/service_guard/https_transport.py`
  - `tests/test_nebius_https_transport.py`

## 94292e6e2d96d6f3808d5885db5f845f287a3ce2

feat(nebius): add restart-safe personal AI coordinator

- Category: **DEMO_ONLY**; disposition/priority: **EXTRACT_CONTRACTS_RECREATE P3**.
- Dependencies: ServiceGuard + persistent target/journal.
- Authority/semantic impact: Demo coordinator approval/restart/replay behavior is useful; do not promote it to second scheduler.
- Test evidence/validation: nebius_personal_ai.
- Files touched (first parent):
  - `runtime/personal_ai_demo.py`
  - `tests/test_nebius_personal_ai.py`

## 602d2016e21abd36e33889050dda5da141d6afa4

feat(nebius): add competition policy and status projection

- Category: **CORE_REQUIRED**; disposition/priority: **SPLIT_POLICY_FROM_PROJECTION P2**.
- Dependencies: 5871f25 +94292e6.
- Authority/semantic impact: Competition routing policy useful; UI projection advisory only.
- Test evidence/validation: nebius_routing, competition_view.
- Files touched (first parent):
  - `runtime/competition_view.py`
  - `runtime/providers/nebius_routing.py`
  - `tests/test_competition_view.py`
  - `tests/test_nebius_routing.py`

## 54a161c3959c633dd08b05e4ae83537657570875

feat(nebius): add Personal AI operator panel and API

- Category: **DEMO_ONLY**; disposition/priority: **OPTIONAL_RECREATE P5**.
- Dependencies: 94292e6 +602d201.
- Authority/semantic impact: API exact approval binding; keep active base authentication and mutation gates.
- Test evidence/validation: webapp.
- Files touched (first parent):
  - `runtime/webapp.py`
  - `tests/test_webapp.py`
  - `web/app.js`
  - `web/index.html`
  - `web/styles.css`

## 628f9ccb2f9ada475bf2c27a2c377ed04458d1df

docs(nebius): record Personal AI evidence and runbook

- Category: **CLOUD_LAYER_REQUIRED**; disposition/priority: **SPLIT_SECURITY_FIX_FROM_EVIDENCE P2**.
- Dependencies: 37ce4d6.
- Authority/semantic impact: Despite docs subject includes HTTPS hardening; inspect runtime diff, preserve sanitized evidence externally.
- Test evidence/validation: nebius_https_transport; manifest_20261003T092636Z.json historical229PASS.
- Files touched (first parent):
  - `docs/nebius_personal_ai_demo_runbook.md`
  - `docs/superpowers/plans/2026-10-03-nebius-personal-ai-vertical-slice.md`
  - `evidence/cloud_activation/live_smoke_20261003T092018Z.json`
  - `evidence/personal_ai_vertical_slice/manifest_20261003T092636Z.json`
  - `reports/personal_ai_vertical_slice_2026-10-03.md`
  - `runtime/service_guard/https_transport.py`

## 7ab2403daa087fa3e5e344f4f03657da03800728

fix(nebius): preserve safe incomplete completion diagnostics and bound probes

- Category: **CORE_REQUIRED**; disposition/priority: **RECREATE_DIAGNOSTICS P1**.
- Dependencies: exact transport + probe.
- Authority/semantic impact: Strict stop-only decoder and independently sanitized diagnostics; max_completion_tokens opt-in.
- Test evidence/validation: nebius_safe_diagnostics, nebius_live_probe.
- Files touched (first parent):
  - `docs/superpowers/plans/2026-10-03-nebius-prompt03-execution.md`
  - `runtime/providers/exact.py`
  - `scripts/nebius_live_probe.py`
  - `tests/test_nebius_live_probe.py`
  - `tests/test_nebius_safe_diagnostics.py`

## ae593df30c31cbb6f95818827b1698cf53d2bbab

fix(nebius): reject authenticated catalog redirects and pin final live smoke

- Category: **CORE_REQUIRED**; disposition/priority: **CONCEPTUAL_SQUASH_PROVIDER_HARDENING P1**.
- Dependencies: 00e8c03 +7ab2403.
- Authority/semantic impact: No authenticated redirect/proxy credential forwarding; pin authorized model in probe.
- Test evidence/validation: nebius_provider, nebius_live_probe.
- Files touched (first parent):
  - `runtime/providers/nebius.py`
  - `scripts/nebius_live_probe.py`
  - `tests/test_nebius_provider.py`

## 3134b3dfbbad02e0476f3857af30b11306e5051d

fix(nebius): redact credential-shaped diagnostic identifiers

- Category: **CORE_REQUIRED**; disposition/priority: **CONCEPTUAL_SQUASH_DIAGNOSTICS P1**.
- Dependencies: 7ab2403.
- Authority/semantic impact: Credential-shaped identifiers redacted; no raw content persistence.
- Test evidence/validation: nebius_safe_diagnostics.
- Files touched (first parent):
  - `runtime/providers/exact.py`
  - `tests/test_nebius_safe_diagnostics.py`

## f1800b8fd812ad58aa09b281094dd572c603f858

test(nebius): preserve bounded live success and offline verification evidence

- Category: **EVIDENCE_ONLY**; disposition/priority: **SPLIT_OPTIONAL_OFFLINE_TOOLS P4**.
- Dependencies: diagnostics + previous authorized live attempt.
- Authority/semantic impact: Receipts/logs historical; scanner/test runner reusable, not runtime code.
- Test evidence/validation: changed_secrets; sealed Prompt03 manifest.
- Files touched (first parent):
  - `evidence/cloud_activation/live_smoke_20261003T130702Z.json`
  - `evidence/cloud_activation/price_quote_20261003T130309Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_cpl.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_lite_serviceguard_https.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_nebius.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_nv10_recovery.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_private_memory_competition_web.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_secret_scanner.log`
  - `scripts/check_changed_secrets.py`
  - `scripts/run_prompt03_regressions.py`
  - `tests/test_changed_secrets.py`

## 70f798c69556a5c08555a9239abf08afdd7d7a08

feat(nebius): launch isolated Personal AI demo with truthful recovery flow

- Category: **DEMO_ONLY**; disposition/priority: **SPLIT_SECURITY_CONTRACTS_RECREATE P3**.
- Dependencies: 94292e6 + existing Core memory/CPL.
- Authority/semantic impact: Broad fixture/runtime/UI composition; preserve isolated storage, transient private context and deny legacy mutation paths; synthetic CPL is not maintenance proof.
- Test evidence/validation: personal_ai_demo_launcher, nebius_personal_ai, webapp.
- Files touched (first parent):
  - `runtime/authority_timeline.py`
  - `runtime/competition_view.py`
  - `runtime/personal_ai_demo.py`
  - `runtime/personal_ai_demo_launcher.py`
  - `runtime/personal_ai_fixture.py`
  - `runtime/providers/config.py`
  - `runtime/providers/nebius_routing.py`
  - `runtime/service_guard/service.py`
  - `runtime/webapp.py`
  - `scripts/start_nebius_personal_ai_demo.sh`
  - `tests/test_competition_view.py`
  - `tests/test_nebius_personal_ai.py`
  - `tests/test_personal_ai_demo_launcher.py`
  - `tests/test_webapp.py`
  - `web/app.js`
  - `web/index.html`

## 505e54290dbddb8211cad5351dff1646318f3bed

docs(nebius): finalize recording package and validated live diagnosis

- Category: **EVIDENCE_ONLY**; disposition/priority: **SPLIT_OPTIONAL_STATIC_TOOLS P4**.
- Dependencies: 70f798c.
- Authority/semantic impact: Documentation/browser evidence and offline checks only.
- Test evidence/validation: sealed manifest/browser_demo_20261003T131600Z.json.
- Files touched (first parent):
  - `docs/nebius_devpost_submission_draft.md`
  - `docs/nebius_final_architecture.md`
  - `docs/nebius_lightning_incomplete_completion_analysis.md`
  - `docs/nebius_personal_ai_demo_runbook.md`
  - `docs/nebius_personal_ai_video_script_180s.md`
  - `docs/superpowers/plans/2026-10-03-nebius-prompt03-execution.md`
  - `evidence/personal_ai_vertical_slice/browser_demo_20261003T131600Z.json`
  - `evidence/personal_ai_vertical_slice/demo_panel_20261003T131600Z.png`
  - `evidence/personal_ai_vertical_slice/fixture_demo_20261003T132724Z.json`
  - `scripts/check_prompt03_static.py`
  - `scripts/run_prompt03_regressions.py`

## ea6b9539e826d8da25c1910cd59e972f30be9e7f

fix(nebius): use a public marker for fixture transport credentials

- Category: **DO_NOT_PORT**; disposition/priority: **LEAVE_SUPERSEDED_HISTORY P0**.
- Dependencies: 70f798c.
- Authority/semantic impact: Short fixture marker broke exact loopback fixture protocol; replaced by9289d9a.
- Test evidence/validation: fixture_marker_debug_20261003T133500Z.json records22PASS/2FAIL.
- Files touched (first parent):
  - `runtime/providers/config.py`

## 9289d9af5eef09cd62c0f47ed57f85d5bd03f13a

fix(nebius): preserve the exact public fixture authentication contract

- Category: **DEMO_ONLY**; disposition/priority: **PORT_FINAL_MARKER_IF_FIXTURE_USED P5**.
- Dependencies: 70f798c; supersedes ea6b953.
- Authority/semantic impact: Preserve public loopback-only protocol marker; never use it in live transport.
- Test evidence/validation: personal_ai_demo_launcher.
- Files touched (first parent):
  - `runtime/providers/config.py`

## 8cef056aa5b8f68defffdc2e3c56dc452b27d572

fix(nebius): keep unmeasured demo outcomes visibly unknown

- Category: **DEMO_ONLY**; disposition/priority: **RECREATE_TRUTHFUL_PROJECTION_IF_UI_USED P5**.
- Dependencies: 70f798c +54a161c.
- Authority/semantic impact: Unknown/unmeasured remains UNKNOWN; null count is not0; standalone renderer tests.
- Test evidence/validation: personal_ai_demo_ui.
- Files touched (first parent):
  - `scripts/run_prompt03_regressions.py`
  - `tests/test_personal_ai_demo_ui.py`
  - `web/app.js`
  - `web/index.html`

## ea485478321f769857ba3380bdfd440030953439

docs(nebius): seal Prompt 03 final evidence and verification manifest

- Category: **EVIDENCE_ONLY**; disposition/priority: **LEAVE_HISTORY_COPY_SEALED_EVIDENCE P0**.
- Dependencies: all Prompt03 implementation.
- Authority/semantic impact: Seals provenance only; no product changes.
- Test evidence/validation: manifest_final_20261003T135440Z.json.
- Files touched (first parent):
  - `docs/superpowers/plans/2026-10-03-nebius-prompt03-execution.md`
  - `evidence/personal_ai_vertical_slice/fixture_marker_debug_20261003T133500Z.json`
  - `evidence/personal_ai_vertical_slice/interrupted_run_20261003T132055Z.json`
  - `evidence/personal_ai_vertical_slice/manifest_final_20261003T135440Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131046Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131046Z_live_diagnostics.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131046Z_secret_scanner.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_cpl.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_demo_launcher.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_lite_serviceguard_https.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_live_diagnostics.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_nebius.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_nv10_recovery.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_private_memory_competition_web.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_secret_scanner.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132055Z_cpl.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132055Z_lite_serviceguard_https.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132055Z_live_diagnostics.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132055Z_nebius.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_cpl.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_demo_launcher.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_lite_serviceguard_https.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_live_diagnostics.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_nebius.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_nv10_recovery.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_private_memory_competition_web.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_secret_scanner.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_cpl.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_demo_launcher.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_lite_serviceguard_https.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_live_diagnostics.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_nebius.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_nv10_recovery.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_private_memory_competition_web.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_secret_scanner.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T134707Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T134707Z_demo_launcher.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T134707Z_demo_ui.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T134707Z_live_diagnostics.log`
  - `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T134707Z_private_memory_competition_web.log`
  - `evidence/personal_ai_vertical_slice/prompt03_static_20261003T132535Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_static_20261003T133231Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_static_20261003T134319Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_static_20261003T135129Z.json`
  - `evidence/personal_ai_vertical_slice/prompt03_static_20261003T135444Z.json`

## Integration policy

Do not cherry-pick the full range. Recreate final reviewed behavior against the active Core. Mixed commits require file/hunk separation and tests; subjects do not classify content reliably. Never replay ea6b953 independently. Do not duplicate merge payloads. Keep historical logs, images and failed receipts in provenance storage rather than importing them into future runtime. Preserve original SHAs in every new integration commit message.

The correction bridge commit e24aa76 is test-only: inspect active base memory hooks before assuming new implementation is needed. The full CPL fixture remains a separate synthetic demonstration. Private preference context creates ZERO_WRITE, not canonical learning.
