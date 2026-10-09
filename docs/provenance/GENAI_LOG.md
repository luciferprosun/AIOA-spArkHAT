# GenAI Disclosure Log

This log starts at the 2026-09-22 reviewer checkpoint. It does not fabricate retroactive per-commit prompt history.


## 2026-09-22 — Public reviewer release preparation

- Tool: ChatGPT
- Model: GPT-5.6 Sol
- Use: reviewer-navigation correction, public-release preparation, GitHub PR orchestration
- Human direction: explicit authorization to publish the prepared AIOA spArkHAT integration to GitHub
- Material outputs: README reviewer navigation and publication-status clarification
- Validation: deterministic NVIDIA reviewer preflight PASS; git diff --check PASS; PR mergeability CLEAN
- Authority: no force-push, no frozen-upstream mutation, no secret publication

## 2026-09-22 — NVIDIA reviewer portability and release hardening

- Tool: ChatGPT via an authorized remote terminal; exact model identifier not independently logged.
- Human direction: focus exclusively on NVIDIA and execute bounded preparation; preserve existing grant/frozen evidence.
- Human line-by-line review: not attested by this automated session. Authorization and human diff review are different facts.
- Reproduced failures: reviewer target import from foreign cwd; existing artifact overwrite; missing published-main CI trigger.
- Scope: reviewer script, controlled target fixture, negative boundary/portability tests, read-only CI triggers and NVIDIA navigation/runbook.
- Local validation: 12 NVIDIA tests PASS; supported offline regression 1027 PASS / 4 expected UI skips, exit 0 (565.26 s). Separately provisioned Cockroach integration tests are outside this offline run. Remote CI remains an independent required release gate.
- No provider credentials read; no live model call, live AWS effect, DVM promotion or EU proposal mutation.
