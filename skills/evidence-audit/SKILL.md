---
name: evidence-audit
version: "0.2.0"
description: Use when reviewing AIOA spArkHAT NVIDIA replay safety, authority boundaries, or deterministic evidence claims.
license: MIT
compatibility: Python 3.12+ and an AIOA spArkHAT checkout with scripts/nvidia_reviewer_preflight.py
metadata:
  author: LuciferSOL <42999854+luciferprosun@users.noreply.github.com>
  tags:
    - nvidia
    - reviewer
    - evidence
    - safety
---

# AIOA Evidence Audit

## Purpose

Perform a deterministic, read-only NVIDIA reviewer audit of an AIOA spArkHAT
source checkout. The skill wraps the repository's existing reviewer preflight
and emits a compact summary without granting new authority or changing runtime
state.

Use it for questions about the competition trajectory, replay safety, execution
authority, fixture/live boundaries, or submission-facing evidence claims.
## Prerequisites

- Python 3.12 or newer.
- An AIOA spArkHAT source checkout.
- The checkout must contain `scripts/nvidia_reviewer_preflight.py`.
- No API key is required.
- Hosted-provider credentials are intentionally removed from the wrapper's
  subprocess environment.

## Instructions

1. Confirm the target is an AIOA spArkHAT source checkout.
2. Run the bundled read-only evidence-audit wrapper.
3. Parse the JSON result from stdout.
4. Report only claims supported by that result.
5. If status is not PASS, preserve the failure and list the failed gates.
6. Do not repair, deploy, enable LIVE providers, or change authority boundaries
   unless the user separately requests a different workflow.

If the agent host exposes a `run_script` helper, use:

`run_script("scripts/audit_aioa.py", args=["--repo", "."])`

Otherwise, from the repository root run:

`python3 skills/evidence-audit/scripts/audit_aioa.py --repo .`
## Available Scripts

| Script | Purpose | Arguments |
| --- | --- | --- |
| `scripts/audit_aioa.py` | Runs the deterministic evidence preflight with provider credentials removed and returns a claim-safe JSON summary. | `--repo PATH`, optional `--timeout-s SECONDS` |

## Safety contract

This skill is read-only with respect to the repository and competition target.

It must never:

- enable or call a hosted model provider;
- load OpenRouter, NVIDIA, AWS, Gemini, xAI, or DeepSeek credentials;
- perform a production Service Guard effect;
- rewrite historical FAIL or UNKNOWN evidence;
- claim `24H_PASS_CLOSED` from this deterministic preflight;
- present TEST_FIXTURE evidence as LIVE;
- promote DVM or pheromone mechanisms beyond SHADOW;
- grant execution authority to provider output, critics, memory, or the skill.

The existing deterministic preflight may exercise only disposable local TEST_FIXTURE effects inside an isolated temporary directory. It must not perform an external or production effect, and its temporary artifacts are deleted when the wrapper exits.
## Required PASS evidence

A PASS requires all of the following:

- preflight scope is `DETERMINISTIC_TEST_FIXTURE_ONLY`;
- competition evaluation status is PASS;
- trajectory stage count is 14;
- duplicate effects equals 0;
- restart replay dispatches equals 0;
- competition effect executor is ServiceGuard;
- provider mode is TEST_FIXTURE;
- memory mode is TEST_FIXTURE;
- DVM / pheromone mode is SHADOW;
- the read-only trajectory sidecar is emitted as `ATIF-v1.7`;
- all LIVE claims emitted by this run are false.

For exact claim wording, read `references/CLAIM_BOUNDARIES.md`.

## What a PASS does not prove

A PASS from this skill does not prove LIVE NVIDIA/Nemotron inference, LIVE
OpenRouter CPL execution, LIVE CockroachDB, LIVE AWS Non-Zero, a contiguous
24-hour certification, production DVM/pheromone authority, or arbitrary
production deployment.
## Examples

Review the default checkout:

```bash
python3 skills/evidence-audit/scripts/audit_aioa.py --repo .
```

Review another checkout with a bounded timeout:

```bash
python3 skills/evidence-audit/scripts/audit_aioa.py --repo /path/to/aioa --timeout-s 120
```

Expected successful output includes `"status": "PASS"`, stage count 14,
zero duplicate effects, zero restart redispatches, ServiceGuard as executor,
and explicit TEST_FIXTURE labels.

## Limitations

- The skill validates only the deterministic reviewer path.
- It does not merge separate LIVE evidence into its result.
- It does not certify `24H_PASS_CLOSED`.
- It does not inspect arbitrary production infrastructure.
- It does not repair failed gates automatically.
- It does not prove that an external provider was reachable at review time.

## Troubleshooting

| Error | Likely cause | Action |
| --- | --- | --- |
| `TARGET_NOT_AIOA_CHECKOUT` | The target does not contain the reviewer preflight. | Point `--repo` at the AIOA spArkHAT checkout. |
| `PREFLIGHT_FAILED` | A deterministic reviewer gate failed. | Preserve the failure; inspect the repository preflight output separately. |
| `PREFLIGHT_OUTPUT_INVALID` | The preflight did not return valid JSON. | Treat the review as failed; do not infer PASS. |
| `PREFLIGHT_TIMEOUT` | The local deterministic preflight exceeded the allowed runtime. | Investigate local test/runtime health; do not switch to a LIVE provider. |

## Output expectations

Return status, scope, stage count, duplicate effects, restart redispatches,
effect executor, provider mode, memory mode, DVM/pheromone mode, ATIF trajectory
schema/digest, whether this run validates any LIVE provider, and a concise list
of claims still unproven.

Do not expose secrets, hidden chain-of-thought, credential paths, or unrelated
repository content.
