# AIOA SparkHub - one-system unification record (2026-10-09)

## Objective and scope

Make **AIOA SparkHub** the canonical public product repository and integrate the entire *unique* functionality of the Nebius Personal AI development branch without replacing current AIOA modules. Nebius Token Factory / NVIDIA Nemotron remain optional model providers inside AIOA, not a separate deployed application or brand. Maintain **one product architecture**, one default branch, source provenance and explicit human authority.

This record is a *technical integration record*, not an assertion of current live/provider/submission/rights compliance. All statuses require exact evidence and current SHA checks.

## Repository ownership

| Repository | Intended status | Rule |
| --- | --- | --- |
| AIOA SparkHub (formerly `AIOA-spArkHAT`) | One canonical public product | Main must include all accepted Nebius + MCP modules; no force pushes |
| `AIOA-NonZero-CloudOps-Agent` | Standalone frozen competition submission | **DO NOT MODIFY**, rename, archive, delete, or rebase during judging |
| `Memory-Patch-for-AIOA-Hackathon-CockroachDB` | Frozen provenance / historical source | Native AIOA migration is selective; do not delete until separate exact-source archive + restore evidence |
| `projects-for-future` | Private archive for unrelated future/paused projects | Never make private projects public by default |
| `LSC-Research` | Separate science/research asset pending archive planning | Not part of AIOA product runtime |
| `EagleEYE-DArc-showcase` | Public showcase only | Never upload the local-only sensitive EagleEYE core |
| `MCP-Commander-Control` | Private task-transport control | **Not** a public product repository or an authorization surface |

## Audited Git facts at start

- Canonical original repo: `luciferprosun/AIOA-spArkHAT`, default `main`, SHA `cd1419f0062bb5ea5ca3da06254fce0daa1cd4d5`.
- `nebius-final-candidate-20261009` is identical to `main` (0 ahead/0 behind); no second merge is necessary.
- `nebius-personal-ai` diverged from `main` (44 ahead/52 behind). The three-way no-ff integration on an isolated copy staged **26 additive paths** (MCP transport, local worker contracts, tests, CI) without conflicts.
- Prior integrated `integration/memory-patch-cockroach-one-system-v1` and `integration/nonzero-cloudops-one-system-v1` contain no unique commits compared with `main`. This does **not** imply their original standalone GitHub repositories are disposable.
- The standalone CockroachDB main was `1098c35024ac78d6ad7b4bd70c6138028c26c5e9` and tracked **847 files**. The complete provenance matrix maps all 847: **231 NATIVE_CONTRACT_MAPPING**, **616 FINAL_EXCLUSION** (including fixture/archive/blocked cases). The native AIOA module under `runtime/memory_patch` is intentionally selective. Full CockroachDB source equivalence is **not claimed**.

## Architecture invariants

1. Operator authority > gates; GitHub and LLMs are transports/advisors, never policy authority.
2. `Non-Zero` remains fail closed; preserve exact human approval and provenance rules.
3. `MCP Commander` GitHub Task Bus is READ-only in unattended remote mode; WRITE_LOCAL/EXEC_LOCAL require a separate local authorization bound to exact payload hash, and are not activated by this merge.
4. Nebius provider must be explicitly authorized, cost-bound and prevented from silently falling back to fixtures or different models.
5. Memory Patch / CockroachDB adapter is optional and must not become an unreviewed network or database dependency of deterministic offline tests.
6. HAT and owner-scoped context are private. Do not commit secrets, browser profiles, raw personal context or logs.
7. Preserve historical raw findings, author/source metadata, competition reports and original code hashes; never fake live PASS from fixture PASS.
8. No automatic model calls, deployment, paid inference, public submission or rights attestation in the source unification task.

## Merge procedure

1. Capture full-ref Git bundles of original AIOA and standalone CockroachDB to a private USB directory and run `git bundle verify`.
2. Use isolated clone (not live development checkout). Record base and head SHA.
3. Test no-ff merge of `origin/nebius-personal-ai` into AIOA `main`; inspect every staged path and ensure no unexpected deletions or conflicts.
4. Run scoped MCP contract tests and official unified deterministic reviewer. Collect true failure results from broader test collection without hiding them.
5. Rebrand README and index; create legacy-documentation pointer. Keep Nebius provider names in required code/official competition evidence.
6. Update MCP CI so it runs on `main` and incoming integration PRs.
7. Commit on `unification/sparkhub-20261009`, push to the original repository and review PR against `main`. Integrate only after required checks and no external authority regression.
8. Once final `main` SHA and branch ancestry are verified, simplify stale **fully merged** branches only after the full-ref backup; preserve non-merged refs and original source repositories.
9. Recheck README links and all provider/core launch paths after final repo rename.

## Evidence and test scope

Supported local reviewer:

```bash
python3 -I -B scripts/nvidia_reviewer_preflight.py --unified
python3 -m pytest -q tests/test_mcp_authority_projection.py tests/test_mcp_bridge_contract.py tests/test_mcp_github_issue_transport.py tests/test_mcp_read_payloads.py tests/test_mcp_task_bus.py tests/test_mcp_transport_claim.py
```

A blanket `python3 -m pytest -q` also recursively collects historical forensic export tests under `archive/` with incompatible imports; that result does not mean the production AIOA reviewer failed. Nevertheless, any active-test errors must be separately investigated and truthfully recorded.

## Unresolved external gates

The original Nebius candidate documents report `MAIN_INTEGRATION_READY=NO` at the time they were written: they separately require exact operator SHA authorization (now superseded only for the explicitly authorized integration scope), human security and 10 binary rights reviews, 30 independently unverified synthetic fixtures, live Nebius/NVIDIA validation, public judge availability, video, final dependency notices and Devpost receipt. They are historical evidence and must **not** be silently edited to PASS.

## Rollback and restoration

- Preserve immutable full-ref backups on external disk; note SHA-256 for each.
- Undo any integration by reverting its merge commit via a new commit; never `git push --force` to erase history.
- Use `git clone <backup.bundle>` for independent restore verification before deleting any source repository.
- Preserve the separate Non-Zero repo and its source SHA throughout the evaluation window.

## Prototype Fund

Only after the canonical codebase stabilizes, use `docs/grants/PROTOTYPE_FUND_HANDOFF.md` as a preparation checklist. Preparing application materials does not submit any grant application.
