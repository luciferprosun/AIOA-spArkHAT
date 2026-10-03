# Cloud activation report — 2026-10-03

## Scope and branch safety

- Repository: `/media/l/LSC_DATA1/NVIDIA_NEBIUS/AIOA-spArkHAT-nebius`
- Branch: `nebius-personal-ai`
- Starting HEAD: `1949ccf712a5088c422f0263fbfaee35ed220c85`
- `main` stayed at `d26266e54ee940d7ada30aa02783dc697618a72c`; no merge, rebase, push, deployment, or long-running cloud resource was performed.
- No model output, private transcript, or API key was recorded in the new receipts or report.

## Phase A — live Token Factory validation

- Catalog-only probe: **PASS**, 25 models returned. The catalog contained the exact IDs `nvidia/Nemotron-3_5-Lightning`, `nvidia/nemotron-3-super-120b-a12b`, and `nvidia/Nemotron-3-Ultra-550b-a55b`. Lightning was selected from the returned catalog.
- Exactly one authorized paid inference was attempted with a 32-token output ceiling. It failed with `INCOMPLETE_COMPLETION`; the requested ID was in the catalog, but the completion did not meet the provider's accepted finish condition. The paid path was stopped and not retried.
- Phase A inference criterion: **FAIL**. The failure receipt does not claim validation and does not contain response content. The provider may have billed the attempt; the probe did not preserve usage, latency, or provider request ID on this error path.
- Redacted, non-overwriting receipts (local permissions `0600`):
  - `evidence/cloud_activation/catalog_20261003T061407Z.json`
  - `evidence/cloud_activation/live_smoke_20261003T061504Z.json`

## Phase B — competition routing

- Added `NebiusModelRouter`, which only resolves roles from a recent PASS catalog receipt and retains the exact advertised ID. Missing or ambiguous roles fail closed. ULTRA requires an explicit `OPERATOR_REQUEST`, `EVIDENCE_AMBIGUITY`, or `CPL_CONFLICT` condition; the provider cannot select its own escalation.
- Added a Nebius `ProviderPort` adapter for existing LITE requests. It checks exact provider/model/response identity, a fresh exact-model USD quote, UTF-8 input bound, output ceiling, timeout, and the per-request USD ceiling before provider transport. It has no provider/model fallback.
- Added explicit Nebius profile configuration. The CLI requires host-supplied catalog receipt, price-quote file, and USD ceiling; it loads the API key from the established secret environment without printing it. Existing NVIDIA profile identity and digest remain compatible.
- `ProviderResponse` now carries fixed `ADVISORY_ONLY` metadata, and LITE, chat, and ServiceGuard boundaries reject responses with any other authority marker. Existing CPL result views continue to mark provider output advisory.

## Phases C–D — serverless target contract and package

- Added a typed cloud effect target below the existing ServiceGuard and a narrow serverless worker contract for `READ_STATE`, `READ_RECEIPT`, and `APPLY_SET_MAINTENANCE`. No shell action or local-effect fallback exists.
- The current Core authorization object remains one-use. A cloud timeout goes through receipt/state reconciliation, and independent post-effect readback remains in Core. The worker requires a deployment-owned atomic durable store for revision fencing and receipt persistence.
- Static package metadata and operator requirements are in `deploy/nebius_serverless/`. The adapter can be exercised with the in-memory fixture transport, but this is **not a live Nebius endpoint package yet**: no Nebius serverless CLI, project/region, endpoint, platform credentials, or durable-store implementation is available in this environment. Deployment status is `BLOCKED_BY_CREDENTIALS`; separate deployment approval is still required before creating a paid long-running service. No endpoint/job or image was created or built.
- Tavily integration was not enabled: no key or entitlement configuration was present.

## Verification

- Main targeted regression command: **122 tests, PASS**.
  `HOME=/tmp/aoia-tdd-home-20261003 PYTHONPATH=runtime:tests python3 -m unittest tests/test_nebius_routing.py tests/test_serverless_effect_transport.py tests/test_nebius_live_probe.py tests/test_nebius_provider.py tests/test_nebius_cpl.py tests/test_nv02_lite.py tests/test_nv09_service_guard.py tests/test_nv10_guard.py -v`
- Private chat regression: **35 tests, PASS**.
  `HOME=/tmp/aoia-tdd-home-20261003 PYTHONPATH=runtime:tests python3 -m unittest tests/test_nv07_chat.py -v`
- Static checks: `git diff --check`, `python3 -m py_compile` over changed Python source/tests, and `python3 -m json.tool deploy/nebius_serverless/deployment.json` all passed.
- Secret-pattern scan found no credential in changed files. Its three matches were in the existing `.env.example` and test/fixture files; no secret values were printed. The configured Nebius API key remained outside the repository. No Tavily or serverless deployment credential was present.
