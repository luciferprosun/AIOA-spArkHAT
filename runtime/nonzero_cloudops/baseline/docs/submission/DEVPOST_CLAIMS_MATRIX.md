# Devpost claims matrix

Status: local B6 candidate claim audit. Every major claim below must remain reproducible without
private repository material. “Local” means offline/mock execution unless a row explicitly says
otherwise.

| ID | Public claim | Reproducible proof in the public candidate | Allowed wording |
| --- | --- | --- | --- |
| C01 | AIOA uses one Strands agent with five bounded tools | `tests/unit/test_strands_agent.py`; `tests/integration/test_local_provider_strands_compatibility.py`; `src/aioa_cloudops_agent/agent/factory.py` | “One Strands agent with five bounded tools” |
| C02 | Model output is not execution authority | `tests/unit/test_nz_authority.py`; `tests/unit/test_safety_hardening.py`; `src/aioa_cloudops_agent/nz/authority.py` | “The model may propose; deterministic code grants or rejects authority” |
| C03 | Approval is bound to the exact proposal and evidence | `tests/unit/test_identifiers_and_approval.py`; `tests/integration/test_local_hitl_execution.py`; portable receipt fields `proposal_sha256`, `evidence_sha256`, `decision_sha256` | “Exact evidence-bound approval” |
| C04 | An approved local scenario performs one mock mutation only after decision | `python -m aioa_cloudops_agent.portable`; `tests/integration/test_portable_judge_sandbox.py`; `docs/evidence/release/portable-b5-container-gate.json` | “One approved mock mutation after explicit approval” |
| C05 | Denial is terminal and causes zero mutation | same portable command; `tests/integration/test_human_approved_remediation_e2e.py`; B5 container-gate receipt | “Deny is terminal with zero mock mutation” |
| C06 | Replay and binding tamper fail closed with zero mutation delta | same portable command; `tests/unit/test_recovery_reconciliation.py`; `tests/integration/test_portable_judge_sandbox.py` | “Conflicting replay and changed bindings are rejected” |
| C07 | Pending approval and interrupted execution are recoverable | portable receipt recovery fields; `tests/unit/test_recovery_reconciliation.py`; `tests/integration/test_durable_hitl_approval_flow.py` | “Restart-safe local recovery and reconciliation” |
| C08 | Provider acknowledgement alone is not success | `tests/unit/test_verification_closure.py`; `src/aioa_cloudops_agent/verification/service.py` | “Independent read-back is required for success” |
| C09 | The deterministic portable flow makes no external network or AWS calls | portable receipt counters; `docs/evidence/release/portable-b5-container-gate.json`; socket-guard tests in `tests/integration/test_portable_judge_sandbox.py` | “Certified offline/mock path: zero external connections and zero AWS calls” |
| C10 | The B5 image runs non-root with a hardened container contract | `Dockerfile`; `docs/evidence/release/portable-b5-nonroot-runtime.json`; `docs/evidence/release/portable-b5-image-privacy-scan.json` | “Locally certified non-root OCI runtime” |
| C11 | Source and dependency inputs are pinned and locally reproducible | `Dockerfile`; `requirements/build.lock`; `requirements/portable.lock`; `docs/evidence/release/portable-b5-artifact-manifest.json` | “Digest/hash-pinned local container build” |
| C12 | The browser experience is local and authenticated | `tests/integration/test_portable_judge_experience.py`; `tests/unit/test_judge_console_ui.py`; `docs/JUDGE_EXPERIENCE.md` | “Authenticated loopback operator console” |
| C13 | AWS and Bedrock are optional adapters, not portable dependencies | `tests/unit/test_portable_runtime_boundary.py`; `src/aioa_cloudops_agent/providers/factory.py`; `docs/architecture/provider-neutral-strands-runtime.md` | “Portable-first, with optional AWS/Bedrock integration” |
| C14 | The project is MIT-licensed and discloses prior art | `LICENSE`; `PRIOR-ART.md`; `docs/submission/PRIOR_ART_DISCLOSURE.md`; initial commit `d813290727b89017bd348c04f68a7f07156652f7` | “MIT; prior concepts disclosed, implementation newly authored in this repository” |
| C15 | The public package is sanitized and locally reproducible | `PUBLICATION_MANIFEST.json`; `PUBLICATION_EXCLUSIONS.md`; `SHA256SUMS`; B6 report when present | “Local publication candidate passed deterministic export and privacy gates” |

## Forbidden promotions

Do not replace the allowed wording with claims of live AWS use, live Bedrock use, production
readiness, public availability, deployed IAM effectiveness, a real cloud mutation, registry
publication, video publication, or Devpost submission. None of those receipts exists in B6.

## Audit rule

If a claim changes, update this matrix and run the referenced proof before publication. A missing,
excluded, or failing proof removes the claim; it does not become a caveat hidden elsewhere.
