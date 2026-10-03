# Nebius Personal AI demo runbook

This runbook exercises the `nebius-personal-ai` branch without modifying
`main`, creating a cloud deployment, or presenting fixture activity as LIVE.
The scenario uses the existing private HAT, exact Nebius ProviderPort,
ServiceGuard, one typed target effect, durable receipts, and the Operator
Console adapter.

## 1. Verify the checkout

```bash
cd /media/l/LSC_DATA1/NVIDIA_NEBIUS/AIOA-spArkHAT-nebius
test "$(git branch --show-current)" = nebius-personal-ai
test "$(git rev-parse main)" = d26266e54ee940d7ada30aa02783dc697618a72c
test "$(git rev-parse origin/main)" = d26266e54ee940d7ada30aa02783dc697618a72c
git status --short
```

The fixture paths below are local test data. They never claim live inference or
live cloud execution.

## 2. Run the complete restart-safe fixture proof

```bash
mkdir -p /tmp/aioa-personal-ai-home
chmod 700 /tmp/aioa-personal-ai-home
HOME=/tmp/aioa-personal-ai-home \
PYTHONPATH=runtime:tests \
python3 -m unittest tests/test_nebius_personal_ai.py -v
```

The five tests prove:

- private owner-scoped HAT context survives closing and recreating the runtime;
- preparation stops at `APPROVAL_REQUIRED` with zero target effects;
- approval alone still leaves the effect count at zero;
- execution produces a receipt and independent readback;
- a lost acknowledgement is reconciled after restart with one apply call;
- replay becomes `REPLAY_BLOCKED`; and
- conflicting reuse of an idempotency key fails closed.

Expected fixture state sequence:

```text
ADVISORY → VERIFIED → APPROVAL_REQUIRED → APPROVED → EXECUTED → RECONCILED → REPLAY_BLOCKED
```

The separate `ZERO_WRITE` test covers the no verified memory delta path.

## 3. Exercise the local API and panel contract

```bash
HOME=/tmp/aioa-personal-ai-home \
PYTHONPATH=runtime:tests \
python3 -m unittest tests/test_webapp.py -v
```

The test launches the real loopback HTTP server with an explicitly injected
`FIXTURE` Personal AI service. It checks the four routes:

```text
POST /api/personal-ai/prepare
GET  /api/personal-ai/status
POST /api/personal-ai/approve
POST /api/personal-ai/resume
```

All routes require the local session token. Each POST also requires its exact
`X-AIOA-Intent` value. The prepare response must show
`APPROVAL_REQUIRED`; the browser never calls approve or resume from that
action. The panel reads only the redacted competition projection.

The ordinary console can be started with:

```bash
PYTHONPATH=runtime python3 -m webapp --host 127.0.0.1 --port 4311
```

Open `http://127.0.0.1:4311`. The Personal AI panel reports that it is not
configured until a host composes `WebRuntimeService(personal_ai=...,
personal_ai_catalog=..., personal_ai_cost_quote=...)`. The HTTP fixture test is
the reproducible reference composition; default startup never silently creates
a fixture or labels it LIVE.

## 4. Inspect restart and replay evidence

```bash
HOME=/tmp/aioa-personal-ai-home \
PYTHONPATH=runtime:tests \
python3 -m unittest \
  tests.test_nebius_personal_ai.NebiusPersonalAITests.test_lost_ack_restart_reconciles_without_second_apply \
  tests.test_nebius_personal_ai.NebiusPersonalAITests.test_approval_executes_once_reconciles_and_blocks_replay \
  -v
```

Both cases require `target_apply_count == 1` and exactly one
`APPLY_SET_MAINTENANCE` transport call.

## 5. Inspect the live provider evidence

The Prompt 02 cost authorization has been consumed. Do not run another paid
probe without new operator authorization. Inspect the preserved receipt:

```bash
python3 -m json.tool \
  evidence/cloud_activation/live_smoke_20261003T092018Z.json
```

It truthfully records `FAIL`, `INCOMPLETE_COMPLETION`, exact Lightning identity,
no fallback, no persisted response content, and
`live_inference_validated=false`.

For a future separately authorized attempt, use a new non-existing receipt
path and keep the exact model, bounds, and no-retry rule:

```bash
PYTHONPATH=runtime:. python3 scripts/nebius_live_probe.py \
  --allow-live-network \
  --allow-live-provider-cost \
  --model nvidia/Nemotron-3_5-Lightning \
  --timeout-seconds 20 \
  --max-output-tokens 256 \
  --receipt evidence/cloud_activation/live_smoke_<NEW_UTC>.json
```

## 6. Validate the HTTPS adapter without deployment

```bash
HOME=/tmp/aioa-personal-ai-home \
PYTHONPATH=runtime:tests \
python3 -m unittest \
  tests/test_nebius_https_transport.py \
  tests/test_serverless_effect_transport.py \
  -v
```

Live Nebius Serverless deployment is `BLOCKED_BY_CREDENTIALS`. Required inputs
remain a separately approved Nebius project/region, HTTPS endpoint, injected
auth token, and an atomic durable store implementing revision fencing and
receipt persistence. Do not deploy or create recurring cost from this runbook.

## 7. Read the operator evidence

```bash
python3 -m json.tool \
  evidence/personal_ai_vertical_slice/manifest_20261003T092636Z.json
sed -n '1,260p' reports/personal_ai_vertical_slice_2026-10-03.md
```

The manifest contains hashes, counts, identities, and bounded statuses. It does
not contain private HAT text, prompts, responses, credentials, or hidden
reasoning.
