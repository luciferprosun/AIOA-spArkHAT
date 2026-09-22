# AIOA spArkHAT — Troubleshooting

## `python3 -m venv .venv` fails with `ensurepip is not available`

This is an OS packaging issue, not an AIOA runtime failure. On Debian/Ubuntu the Python venv package may be separate.

Use the appropriate OS package for the installed Python version, then recreate the venv. If system package changes are not appropriate, the deterministic reviewer preflight can run directly from the source checkout with Python 3.11+ and no venv.

## Reviewer preflight says `TEST_FIXTURE`

That is expected for the default deterministic path. It intentionally performs no live provider call. Do not relabel this result as LIVE.

## Missing NVIDIA/OpenRouter credentials

The deterministic reviewer preflight does not require either credential. Live paths remain fail-closed. Missing credentials must not trigger automatic approval, provider substitution, or fixture-to-live claim promotion.

## Competition projection says `NOT_CONFIGURED`

The read-only dashboard projection needs an evidence artifact path. Run the reviewer preflight or raw competition demo first, then point `AIOA_COMPETITION_DEMO_EVIDENCE` at the generated artifact if manually exercising the projection.

## Competition projection says `INVALID_EVIDENCE`

Treat the artifact as untrusted. The projection rejects malformed JSON, symlinks, invalid schemas/types, inconsistent fixture/live claims, malformed digests, and invalid effect counters. Do not repair evidence in place merely to obtain PASS.

## Bare `pytest tests` reports Cockroach certification failures

Three Cockroach certification modules require explicit disposable certification inputs and intentionally fail closed without them:
- `tests/cockroach/test_migration_gate.py`
- `tests/cockroach/test_rls_and_transactions.py`
- `tests/cockroach/test_vector_temporal.py`

For the ordinary offline repository regression, exclude only those three modules. Run the Cockroach certification gate separately with its explicit disposable inputs; never fabricate them from defaults.

## Historical provider `UNKNOWN`

`UNKNOWN` is not PASS and must not be silently retried into a cleaner historical result. Preserve the original evidence. A later manual replay is a separate attempt.

## Restart/replay appears to create a second effect

Stop the demo path and preserve the state/evidence root. A valid reviewer run requires `duplicate_effects = 0` and `restart_replay_dispatches = 0`. Do not hide or overwrite a duplicate-effect observation.

## Cockroach is unavailable

The reviewer fixture path may use the repository durable test backend, and must label it `TEST_FIXTURE`. A Cockroach LIVE claim requires the separate certified Cockroach state; repository fallback must never be presented as live Cockroach.

## DVM/pheromone appears authoritative

That is a failure. Competition mode is SHADOW. Scores, tau values, critic agreement, or memory retrieval rank cannot approve, revive, or execute an effect.
