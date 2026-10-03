# October 6 conflict forecast

Observed: frozen main is the merge-base; target-side changed-file overlap is empty today. Forecasts below are semantic risks, not observed merge conflicts. Repeat inventory after fetch. Source of truth for authority/engine composition is the active AIOA Core after explicit release; source branch provides selected tested Nebius behavior. Never overwrite the active base wholesale.

| Changed file | Risk | Source of truth / behavior to preserve |
|---|---|---|
| `.env.example` | MEDIUM | Active local config/ignore conventions; placeholders only, never import operator env files. |
| `.gitignore` | MEDIUM | Active local config/ignore conventions; placeholders only, never import operator env files. |
| `deploy/nebius_serverless/README.md` | HIGH operational | Future authorized deployment configuration; current templates are not credentials/deployment proof. No deploy before separate authorization. |
| `deploy/nebius_serverless/deployment.json` | HIGH operational | Future authorized deployment configuration; current templates are not credentials/deployment proof. No deploy before separate authorization. |
| `docs/nebius_devpost_submission_draft.md` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `docs/nebius_final_architecture.md` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `docs/nebius_lightning_incomplete_completion_analysis.md` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `docs/nebius_personal_ai_demo_runbook.md` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `docs/nebius_personal_ai_video_script_180s.md` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `docs/superpowers/plans/2026-10-03-nebius-personal-ai-vertical-slice.md` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `docs/superpowers/plans/2026-10-03-nebius-prompt03-execution.md` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/cloud_activation/catalog_20261003T061407Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/cloud_activation/live_smoke_20261003T061504Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/cloud_activation/live_smoke_20261003T092018Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/cloud_activation/live_smoke_20261003T130702Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/cloud_activation/price_quote_20261003T130309Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/browser_demo_20261003T131600Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/demo_panel_20261003T131600Z.png` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/fixture_demo_20261003T132724Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/fixture_marker_debug_20261003T133500Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/interrupted_run_20261003T132055Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/manifest_20261003T092636Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/manifest_final_20261003T135440Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_cpl.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_lite_serviceguard_https.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_nebius.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_nv10_recovery.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_private_memory_competition_web.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T125634Z_secret_scanner.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131046Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131046Z_live_diagnostics.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131046Z_secret_scanner.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_cpl.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_demo_launcher.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_lite_serviceguard_https.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_live_diagnostics.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_nebius.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_nv10_recovery.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_private_memory_competition_web.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T131617Z_secret_scanner.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132055Z_cpl.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132055Z_lite_serviceguard_https.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132055Z_live_diagnostics.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132055Z_nebius.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_cpl.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_demo_launcher.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_lite_serviceguard_https.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_live_diagnostics.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_nebius.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_nv10_recovery.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_private_memory_competition_web.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T132742Z_secret_scanner.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_cpl.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_demo_launcher.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_lite_serviceguard_https.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_live_diagnostics.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_nebius.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_nv10_recovery.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_private_memory_competition_web.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T133729Z_secret_scanner.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T134707Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T134707Z_demo_launcher.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T134707Z_demo_ui.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T134707Z_live_diagnostics.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_regression_20261003T134707Z_private_memory_competition_web.log` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_static_20261003T132535Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_static_20261003T133231Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_static_20261003T134319Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_static_20261003T135129Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `evidence/personal_ai_vertical_slice/prompt03_static_20261003T135444Z.json` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `reports/cloud_activation_2026-10-03.md` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `reports/personal_ai_vertical_slice_2026-10-03.md` | LOW / archive | Historical immutable provenance; retain outside product integration; not runtime source of truth. |
| `runtime/authority_timeline.py` | HIGH | Active authentication/CSRF/API contracts; separate provider/target labels, private redaction, null UNKNOWN, CPL scope, exact approval. |
| `runtime/competition_view.py` | HIGH | Active authentication/CSRF/API contracts; separate provider/target labels, private redaction, null UNKNOWN, CPL scope, exact approval. |
| `runtime/critical_loop/service.py` | HIGH | Active CPL roles/timeouts/verifier; exact provider routes are advisory. Synthetic fixture result is not action proof. |
| `runtime/mission/lite_chat.py` | HIGH | Active mission scheduler/budget and owner scope; port adapter behavior without a second scheduler. |
| `runtime/mission/lite_cli.py` | HIGH | Active mission scheduler/budget and owner scope; port adapter behavior without a second scheduler. |
| `runtime/mission/lite_contracts.py` | HIGH | Active mission scheduler/budget and owner scope; port adapter behavior without a second scheduler. |
| `runtime/mission/lite_runtime.py` | HIGH | Active mission scheduler/budget and owner scope; port adapter behavior without a second scheduler. |
| `runtime/personal_ai_demo.py` | HIGH semantic | Active Core memory and coordinator; extract restart invariants, keep fixture isolated; no new memory authority or canonical preference writes. |
| `runtime/personal_ai_demo_launcher.py` | HIGH semantic | Active Core memory and coordinator; extract restart invariants, keep fixture isolated; no new memory authority or canonical preference writes. |
| `runtime/personal_ai_fixture.py` | HIGH semantic | Active Core memory and coordinator; extract restart invariants, keep fixture isolated; no new memory authority or canonical preference writes. |
| `runtime/providers/__init__.py` | HIGH | Active ProviderPort/config plus final Nebius exact IDs, stop-only decoder, explicit budgets, credential redaction, no redirects/fallback. |
| `runtime/providers/config.py` | HIGH | Active ProviderPort/config plus final Nebius exact IDs, stop-only decoder, explicit budgets, credential redaction, no redirects/fallback. |
| `runtime/providers/exact.py` | HIGH | Active ProviderPort/config plus final Nebius exact IDs, stop-only decoder, explicit budgets, credential redaction, no redirects/fallback. |
| `runtime/providers/nebius.py` | HIGH | Active ProviderPort/config plus final Nebius exact IDs, stop-only decoder, explicit budgets, credential redaction, no redirects/fallback. |
| `runtime/providers/nebius_routing.py` | HIGH | Active ProviderPort/config plus final Nebius exact IDs, stop-only decoder, explicit budgets, credential redaction, no redirects/fallback. |
| `runtime/providers/nvidia.py` | HIGH | Active ProviderPort/config plus final Nebius exact IDs, stop-only decoder, explicit budgets, credential redaction, no redirects/fallback. |
| `runtime/service_guard/__init__.py` | CRITICAL | Active approval and sole effect executor; exact proposal binding, typed transport, receipts/readback, UNKNOWN reconcile-before-retry. |
| `runtime/service_guard/https_transport.py` | CRITICAL | Active approval and sole effect executor; exact proposal binding, typed transport, receipts/readback, UNKNOWN reconcile-before-retry. |
| `runtime/service_guard/serverless_worker.py` | CRITICAL | Active approval and sole effect executor; exact proposal binding, typed transport, receipts/readback, UNKNOWN reconcile-before-retry. |
| `runtime/service_guard/service.py` | CRITICAL | Active approval and sole effect executor; exact proposal binding, typed transport, receipts/readback, UNKNOWN reconcile-before-retry. |
| `runtime/service_guard/target.py` | CRITICAL | Active approval and sole effect executor; exact proposal binding, typed transport, receipts/readback, UNKNOWN reconcile-before-retry. |
| `runtime/webapp.py` | HIGH | Active authentication/CSRF/API contracts; separate provider/target labels, private redaction, null UNKNOWN, CPL scope, exact approval. |
| `scripts/check_changed_secrets.py` | MEDIUM | Source final offline tool behavior; branch-name guards may need explicit future integration scope. Paid probe remains separately authorized. |
| `scripts/check_prompt03_static.py` | MEDIUM | Source final offline tool behavior; branch-name guards may need explicit future integration scope. Paid probe remains separately authorized. |
| `scripts/nebius_live_probe.py` | MEDIUM | Source final offline tool behavior; branch-name guards may need explicit future integration scope. Paid probe remains separately authorized. |
| `scripts/run_prompt03_regressions.py` | MEDIUM | Source final offline tool behavior; branch-name guards may need explicit future integration scope. Paid probe remains separately authorized. |
| `scripts/start_nebius_personal_ai_demo.sh` | HIGH semantic | Active Core memory and coordinator; extract restart invariants, keep fixture isolated; no new memory authority or canonical preference writes. |
| `tests/test_changed_secrets.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_competition_view.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_nebius_cpl.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_nebius_https_transport.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_nebius_live_probe.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_nebius_personal_ai.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_nebius_provider.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_nebius_routing.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_nebius_safe_diagnostics.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_nv07_chat.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_personal_ai_demo_launcher.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_personal_ai_demo_ui.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_serverless_effect_transport.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `tests/test_webapp.py` | HIGH semantic | Combine active base assertions with Nebius negative/recovery contracts; passing old tests alone does not prove compatibility. |
| `web/app.js` | HIGH | Active authentication/CSRF/API contracts; separate provider/target labels, private redaction, null UNKNOWN, CPL scope, exact approval. |
| `web/index.html` | HIGH | Active authentication/CSRF/API contracts; separate provider/target labels, private redaction, null UNKNOWN, CPL scope, exact approval. |
| `web/styles.css` | HIGH | Active authentication/CSRF/API contracts; separate provider/target labels, private redaction, null UNKNOWN, CPL scope, exact approval. |

## Cross-file semantic hazards

- Config guard hard-coded to nebius-personal-ai cannot silently authorize an integration branch; update only explicit offline composition and keep paid calls separately gated.
- Shared model/CPL managers must use target-owned isolated state; native memory and effect journals cannot share storage namespace accidentally.
- Durable state ordering must cover effect committed but projection not persisted; reconcile from independent readback before retry.
- Worker count must not turn into independent schedulers or duplicate approval issuers. Existing local target durability does not prove distributed fencing.
- Current private preference memory persists privately; public projection/receipts must not. CPL advisory and independent verification have different evidence scopes.
- Reapplying intermediate fixture marker ea6b953 breaks the fixture even without a textual conflict. Use final9289d9a behavior only.
- HTTPS transport in628f9cc is a runtime fix despite a docs subject. Mixed commits cannot be classified by title alone.
- Main has no target-side changes while frozen; any forecast about the future active base is unconfirmed until captured and tested.
