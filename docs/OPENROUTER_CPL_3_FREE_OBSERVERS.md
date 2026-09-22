# AIOA spArkHAT — OpenRouter CPL 3 Free Observers

Date: 2026-09-21
Status: PREPARED / LIVE KEY NOT PRESENT

## Existing contract

The existing Critical Prompt Loop already implements the exact sequence:

1. primary draft
2. observer-1 — Logic & Claims
3. observer-2 — Safety & Authority
4. observer-3 — Evidence & Consistency
5. primary revision

Contract: `cpl-1plus3plus1-v1`.
All observer output is advisory metadata only and has no execution, approval,
memory-promotion or write authority. A run is planned first and requires an
explicit local plan-hash + nonce authorization before any LIVE provider calls.

## Prepared free-model binding

Use exact OpenRouter model identifiers, not `openrouter/free` or an auto router.
The strict CPL contract rejects non-exact routing aliases because response-model
identity must match the approved plan.

Primary draft + revision:
- `minimax/minimax-m3:free`

Observers:
- Logic & Claims: `google/gemma-4-26b-a4b-it:free`
- Safety & Authority: `google/gemma-4-31b-it:free`
- Evidence & Consistency: `qwen/qwen3.8-27b:free`

Example plan payload:

```json
{
  "prompt": "QUESTION OR BOUNDED DEMO TASK",
  "evidence": "NON-CONFIDENTIAL BOUNDED EVIDENCE",
  "models": [
    "minimax/minimax-m3:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "qwen/qwen3.8-27b:free"
  ],
  "roles": [
    "Logic & Claims",
    "Safety & Authority",
    "Evidence & Consistency"
  ],
  "run_budget_usd": "0.01"
}
```

## Verification already completed

The exact binding above was exercised through the existing local CPL HTTP
fixture. Result:

- execution_status = COMPLETED
- generation_requests = 5
- observer reviews = 3
- final revision = present
- observer models are distinct
- shared_model_for_roles = false
- no external API call
- no execution authority

## Live prerequisites

LIVE OpenRouter is intentionally fail-closed until an operator provides
`OPENROUTER_API_KEY`. Approved local secret paths already supported by the
runtime include:

- `~/.config/aoia/secrets/openrouter.env`
- `~/.config/openrouter/api.env`

Do not commit or print the key.

The live CPL cost policy still requires an operator-authored positive session
and run budget plus fresh price quotes, even when the selected endpoint prices
are zero. This preserves explicit admission and avoids silently treating
"free" as unlimited authority.

## Privacy rule for free endpoints

Use free OpenRouter observers only on bounded, non-confidential review
material. Never send credentials, private repository dumps, personal data or
jury secrets. The CPL secret-shaped input redaction remains enabled, but it is
not a substitute for data classification.

## Live acceptance gate

After a key is installed:

1. ProviderManager strict status must report configured=true.
2. Run one bounded live observer/CPL smoke only.
3. Require exact reported model identity for all five calls.
4. Require all 3 observer results COMPLETED.
5. Require no authority/write promotion from observer output.
6. Preserve provider errors/UNKNOWN; do not automatically retry an ambiguous
   call.
7. The competition UI may expose the exact preset and fail-closed readiness blockers before LIVE validation, but must not claim LIVE readiness. Only after this gate passes may the UI present the preset as LIVE-validated.
