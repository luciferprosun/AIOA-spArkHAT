# Judge deployment package — local preparation only

Candidate: e7a0a747e2e9fea8f75416ec6d6d3a35a5152ae0

Profiles:
1. LOCAL_FIXTURE — fixture provider + fixture target.
2. PUBLIC_FIXTURE — public UI, fixture provider + fixture target.
3. PUBLIC_LIVE_PROVIDER_FIXTURE_TARGET — server-side Nebius provider, fixture target only.

Required invariants:
- /api/health distinguishes FIXTURE / BLOCKED_PROVIDER / actually live-validated state.
- Provider secrets remain server-side only.
- No arbitrary shell, generic live write or private HAT plaintext.
- Hard request/token/response/time/cost/risk limits.
- No automatic retry or silent provider fallback.
- Restart/replay barriers and UNKNOWN reconciliation preserved.
- Human consequential approval remains separate from visitor advisory requests.

PUBLIC_DEPLOYMENT_PERFORMED=NO
