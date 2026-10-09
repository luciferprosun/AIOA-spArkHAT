# One-call LIVE validation plan — PREPARED ONLY

Preparation basis: e7a0a747e2e9fea8f75416ec6d6d3a35a5152ae0. Bind the exact post-commit candidate externally before any live authorization.

This prepares one separately authorized Nebius Token Factory / NVIDIA advisory validation. It does not authorize or perform a provider call.

- Reuse existing native ProviderPort; no duplicate client.
- One call only; no retry; no fallback.
- Input <= 4096 bytes; output <= 128 tokens; response <= 16384 bytes; deadline 20s.
- Conservative per-call ceiling: USD 0.001 plus same-Core aggregate money/risk governor.
- Exact-model/catalog/quote checks must be current immediately before the call.
- Accept content only with native exact-model checks and finish_reason=stop.
- Incomplete completion => REJECTED.
- Ambiguity => UNKNOWN/REJECTED, never fabricated success.
- Effect target remains FIXTURE_ONLY; model authority remains ADVISORY_ONLY.

LIVE_VALIDATION_READY_FOR_OPERATOR=YES
LIVE_VALIDATION_PERFORMED=NO
