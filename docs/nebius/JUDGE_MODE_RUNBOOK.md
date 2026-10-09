# Bounded local judge mode

Product: AIOA Arch spArk, Personal AI maintenance assistant. Existing PersonalAIDemoService, native ProviderPort, owner HAT, Core governor, ServiceGuard and receipt/readback remain the sole product path; external MCP Commander is a READ-only control plane, not a second application.

On the approved integration checkout run:

```bash
./scripts/start_nebius_personal_ai_demo.sh --fixture
```

Open the displayed loopback URL. Python 3.11+; use the repository's documented optional dependencies. This command does not install or load provider keys. `GET /api/health` returns bounded readiness: Provider FIXTURE, Target FIXTURE_ONLY, model authority ADVISORY_ONLY, effect authority NONE. Personal HAT plaintext is absent. Scenario: request maintenance advice, separately inspect/approve the exact fixture action, resume, restart, then replay/readback. One effect, zero duplicate effects; UNKNOWN stays pending reconciliation. Arbitrary chat/model/CPL endpoints are denied in this explicit demo session. Only the fixed maintenance query is admitted.

Caps: eight advisory requests/hour, one call per prepare, no retry/fallback, 4096 input bytes, 128 output tokens, 16384 response bytes, 20 seconds, USD0.001 conservative per-call ceiling plus same-Core aggregate money/risk limits. The distinct existing CPL demo is five local synthetic calls; it is not five Nebius calls or independent model consensus.

`--live-provider` is preparation only: Provider LIVE_NEBIUS_TOKEN_FACTORY / provider state NOT_LIVE / BLOCKED_PROVIDER, Target FIXTURE_ONLY. No key is read. An explicitly supplied host policy can instantiate the existing native port and run exact catalog/quote/cost admission offline, with a metadata-only admitted capsule. It cannot send. LIVE calls remain blocked by separate cost/operator authorization, and no fixture fallback occurs. Native exact-model/finish_reason=stop checks remain unchanged.

For the one-Core full reviewer path run `python3 -I -B scripts/nvidia_reviewer_preflight.py --unified`. It composes capsule/governor/commit-select-reveal/guard/shadow/console over controlled fixture ports. This is separate reproducibility evidence, not current public judge hosting or live provider proof.

Before deployment: separately authorize one bounded integrated LIVE validation, close rights/security review, choose a controlled public frontend, preserve safe fixture target and human-only approval access, validate access/caps/readiness, and record exact candidate/URL receipts. Do not expose the generic action runtime or private HAT. No cloud/publishing action is performed by this runbook.

Badge vocabulary: FIXTURE_PROVIDER or configured LIVE_PROVIDER (NOT_LIVE until validated), plus FIXTURE_TARGET. The exact backend provider labels remain FIXTURE / LIVE_NEBIUS_TOKEN_FACTORY; target policy remains FIXTURE_ONLY. The Judge readiness capsule is a separate metadata-only admitted projection, not a claim that its digest binds the fixture prepare request; that path retains native quoted_advisory_context. The separate --unified reviewer proves the full capsule-to-provider binding. Offline submission URLs use standard HTTPS on default/443 only and do not resolve DNS; independent public access evidence remains required.
