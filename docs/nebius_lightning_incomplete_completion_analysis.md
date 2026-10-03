# Lightning incomplete-completion analysis — 2026-10-03

## OBSERVED

The preserved Token Factory receipts target the exact catalog identifier
`nvidia/Nemotron-3_5-Lightning`, provider `nebius`, with fallback disabled.

| Attempt | Configured output bound | Preserved result | Safe completion metadata |
| --- | --- | --- | --- |
| Prompt 01, `live_smoke_20261003T061504Z.json` | 32 tokens in the historical probe implementation | `FAIL / INCOMPLETE_COMPLETION` | Finish reason, usage, request ID and latency were not preserved |
| Prompt 02, `live_smoke_20261003T092018Z.json` | 256 tokens in the Prompt 02 operator report | `FAIL / INCOMPLETE_COMPLETION` | Finish reason, usage, request ID and latency were not preserved |
| Prompt 03, `live_smoke_20261003T130702Z.json` | `max_completion_tokens=512`, including reasoning, timeout 30 seconds | `PASS`, live inference validated | `stop`; request `chatcmpl-994b9c6e`; prompt/completion/total tokens `25/136/161`; latency `1157 ms` |

The older receipts do not themselves record the configured token limits.
Their limits come from the historical probe source and preserved Prompt 02
report. The old decoder raised `INCOMPLETE_COMPLETION` for a non-`stop` finish
reason. Its exception path omitted the actual provider metadata, so it is
not possible to recover whether that reason was specifically `length`, a
filter condition, or another non-stop value. The old receipts contain no raw
response or reasoning that could resolve this uncertainty.

The new request used the two tiny prompts specified by Prompt 03, temperature
zero, one choice, no streaming, no fallback and no retry. The exact requested
and reported model matched. Its receipt records a two-byte response and its
hash; the response content was not persisted. This is one successful advisory
transport smoke, not a demonstration of live target effects or broad model
reliability. The receipt creation time is **13:05:34 UTC**; its filename's
timestamp was selected earlier and is not the authoritative request time.

The production decoder still rejects every finish reason other than `stop`.
New failure metadata is independently sanitized to admit only typed provider,
model, finish, request ID, usage, latency and HTTP-status fields. It excludes
response/reasoning/prompt content, private HAT data, credentials and raw
provider payloads. Authenticated catalog requests now reject redirects and
environment proxies before the one-attempt inference transport is used.

### Official API contract and price evidence

Nebius documents `max_completion_tokens` as a bound on generated tokens that
includes visible output and reasoning. Its `max_tokens` description does not
state that same explicit distinction and supplies a default of 8192 when the
field is omitted. The Prompt 03 probe therefore explicitly sends only
`max_completion_tokens=512`; it does not depend on an omitted field's default.
The same API documentation distinguishes normal stopping from exhausting the
request token limit and from filtering. [Nebius Chat Completions API](https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion.md),
[live official OpenAPI schema](https://api.tokenfactory.nebius.com/openapi.json).

The official Lightning pricing page was checked on 2026-10-03 and listed
USD 0.06 per million input tokens and USD 0.24 per million output tokens.
The fresh quote is preserved in
`evidence/cloud_activation/price_quote_20261003T130309Z.json`.
With a conservative 2048-token input admission bound and the 512-token total
completion cap, the admitted upper bound is
`(2048 × 0.06 + 512 × 0.24) / 1,000,000 = USD 0.00024576`, below the single
attempt's USD 0.25 authorization. This is an admission calculation, not a
provider invoice or a measured billing claim. [Official Nebius NVIDIA Nemotron pricing](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference).

## INFERRED

Insufficient output budget is a plausible explanation for the earlier
32-token attempt. The later successful request reported 136 completion
tokens, which exceeds 32, and the documented completion budget includes
reasoning. However, its prompt and token-limit field also changed; this is
not a controlled comparison and does not establish why the earlier call
failed.

The new request's 136 completion tokens are below 256. Consequently, the
successful observation does not establish that raising 256 to 512 alone
resolved the Prompt 02 failure. Reducing the prompt, using the explicit total
completion field, timing or provider variation could have contributed. These
are hypotheses, not verified causes. No truncated response was accepted to
make the probe pass.

## UNCONFIRMED

- The exact finish reasons and usage of the first two requests.
- How many tokens in any request were hidden reasoning versus visible output;
  the diagnostic allowlist deliberately excludes reasoning content/details.
- Any undocumented Lightning-specific default reasoning behavior, provider
  routing change, model revision or infrastructure fault.
- Whether the previous `max_tokens` calls were capped or interpreted
  differently from `max_completion_tokens` by the provider.
- Whether the same settings will reliably complete future maintenance
  advisory requests, longer prompts or the full CPL review.
- Actual provider charges; only the documented-price admission bound is
  preserved here.

## Recommended future action

Keep the strict stop requirement and sanitized metadata path. Preserve all
three receipts; do not overwrite the older failures. For a future separately
authorized investigation, obtain a fresh price/catalog check, an explicit
total-token bound and budget, then compare one variable at a time with
allowlisted finish/usage/request metadata. Request IDs can be supplied to
Nebius support for investigation without sending private memory or reasoning.

**Prompt 03's single additional inference authorization has been consumed.**
Do not retry this probe or perform live demo generation under that
authorization. Continue recording with the fixture provider and fixture
target. Live advisory demo execution needs new explicit cost authorization;
live Serverless deployment remains `BLOCKED_BY_CREDENTIALS` and needs separate
deployment authority.
