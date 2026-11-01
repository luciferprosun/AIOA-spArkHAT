# META-P2-01 Handoff — Offline Muse Model API provider plan/contract

Status: PARTIAL (targeted suite green; full suite not run — step budget).

## Source

- Checkout: `/home/l/projects/AIOA-spArkHAT-META`, branch `meta`
- Source SHA: `22ca2e7869d903287ab5a53f831b6892b3db24dd`
- Origin: `https://github.com/luciferprosun/AIOA-spArkHAT.git`

## Changed files (WRITE ONLY scope respected)

1. `runtime/meta_hackathon/provider_offline.py` (new)
2. `tests/test_meta_p2_provider.py` (new)
3. `docs/meta/META_P2_01_HANDOFF.md` (this file)

## Source package reuse (no Core duplication)

- `runtime/providers/openai_compatible.py` — `OpenAICompatibleProvider`
  subclassed; network `generate()` overridden to always raise
  `META_OFFLINE_DENIED`.
- `runtime/providers/base.py` — provider interface shape.
- `runtime/meta_hackathon/muse_plan.py` — `parse_muse_plan`,
  `MUSE_MODEL_ID` reused for all plan parsing/binding.
- `runtime/meta_hackathon/contracts.py` — `BrowserTaskV1`,
  `MetaContractError` reused; no contract reimplementation.

## Contract pins

- Model `muse-spark-1.3`, base URL `https://api.meta.ai/v1` (labels only).
- No token, no Authorization header, no urllib/urlopen/sockets.
- Owner scope digest, source SHA, task digest bound from trusted host args.
- `max_output_tokens <= 512`, `timeout <= 15s`, input `<= 2000` chars.
- Budget field is DESCRIPTIVE ONLY, not a billing cap. No API spend.
- `dispatch_allowed` is always `False`.

## Test results

- Targeted: `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover
  -s tests -p 'test_meta_p2_*.py' -q` → Ran 12 tests, OK.
- Full `test_meta_*.py` suite: NOT RUN (budget). Must run before P2-02.
- Cases: valid mock, prompt injection, forged approval/owner, off-allowlist
  URL, overbudget, stop/timeout, model mismatch, malformed, offline-only,
  error redaction (no untrusted bytes in errors).

## Explicit declarations

- NO LIVE AIOA Model API call was made or is enabled by this change.
- Cost: UNKNOWN (no spend performed; budget field descriptive only).
- No Muse Code CLI authentication is claimed as runtime integration proof.
- Chromium LIVE P1-05 untouched. No Core/authorization changes.

## Next gate

P2-02 only after independent ChatGPT QA of this handoff plus a full
`test_meta_*.py` green run.

## Independent ChatGPT QA addendum — 26 October 2026

The section above is the **original Muse-authored handoff**, recorded before subsequent security corrections. Its statement that the full suite was not run is historically accurate for that initial Muse session, but no longer describes the final verified state.

- Initial P2-01 Muse output: 12/12 targeted PASS, full suite not yet run, status PARTIAL.
- Independent QA uncovered inherited `generate_exact()` (HTTP dispatch) exposed by the subclass. Muse QA1 **overrode that entrypoint with a constant offline denial**, but hit a model-step limit before finalizing tests.
- QA1 introduced a finite descriptive budget cap of USD 1.00; one earlier test supplied USD 1.50, causing exactly one full-suite error. Muse QA2 updated the test to valid USD 0.50 and added negative `NaN`, infinity and `generate_exact()` tests.
- Muse QA2 exceeded a bounded wall-clock review interval without a terminal reply. The session was terminated. **Do not label that agent run completed or its report verified.**
- ChatGPT independently verified exact three-file scope, no fallback through `generate()` or `generate_exact()`, no real network calls, `dispatch_allowed=False`, finite budget metadata, and then ran `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_*.py' -q`: **113/113 OFFLINE PASS**, 0 FAIL/ERROR.

**Final decision:** QA PASS for P2-01 OFFLINE provider contract only. Next `META-P2-02` requires its own bounded Muse prompt and QA. P2-03 live product API probe, P1-05 Chromium LIVE, OAuth, spending cap changes, and external effects remain unapproved. Billing cost of Muse coding sessions remains UNKNOWN.
