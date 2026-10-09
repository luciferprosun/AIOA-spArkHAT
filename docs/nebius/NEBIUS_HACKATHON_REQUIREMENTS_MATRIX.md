# Nebius brief — requirement-to-evidence matrix

Scope: same-repository local candidate, no publication authority. Machine-readable companion: `NEBIUS_HACKATHON_REQUIREMENTS_MATRIX.json`. Its baseline SHA is preparation provenance, not a future accepted submission SHA. Mandatory evidence references remain empty until externally reviewed, candidate-bound receipts exist. Refresh an external matrix against the exact accepted SHA before submission.

Day-shift refresh: the checked-in matrix binds code checkpoint `dceafec638b36417cb99c56f810d84e3555a7c61` (bounded CSR reviewer acceptance). Subsequent documentation commits do not claim self-referential SHA binding. The day-shift external final package supplies a matrix bound to its exact final HEAD and records BLOCKED on all 13 missing mandatory receipts. No status is promoted because local tests passed.

[Official rules](https://nebiusglobalaihackathon.devpost.com/rules) require a working Nebius-powered application, an NVIDIA open model, public source/license/setup, track fit, working demo, public video, feedback, significant-update disclosure when applicable, and judge access. [FAQ](https://nebiusglobalaihackathon.devpost.com/details/faqs) confirms Token Factory usage can satisfy hosting; frontend Nebius hosting is not mandatory. [Organizer guidance](https://nebiusglobalaihackathon.devpost.com/updates/46205-how-to-build-a-winning-project) asks for concrete tool feedback and explicit Nebius/NVIDIA presentation. Retrieved 2026-10-08. These references are not eligibility/legal attestation.

| Requirement | Status | Evidence scope / missing proof |
|---|---|---|
| nebius_runtime | PARTIAL | Historical Oct3 stop receipt only; current unified flow is fixture. Fresh integrated LIVE proof required. |
| nvidia_model | PARTIAL | Exact Lightning identity known; current fixture must not be relabeled NVIDIA inference. |
| personal_ai_track | PARTIAL | Owner-scoped memory, human-gated maintenance, replay/readback local tests. Live judged product remains open. |
| significant_update | PARTIAL | Local statement and provenance; maintainer must confirm eligibility and actual significant update. |
| public_repo_mit | BLOCKED_EXTERNAL | Local MIT notices present; accepted integration candidate not published. |
| readme_setup | PARTIAL | Current reviewer and bounded judge setup documented; final installation/validation evidence pending. |
| demo_url | BLOCKED_EXTERNAL | Loopback is not a judge-accessible URL. No deployment performed. |
| video | BLOCKED_EXTERNAL | 165-second script only; no verified public YouTube artifact. |
| feedback | PARTIAL | Factual experience draft only; no unsupported ratings. |
| judging_availability | UNKNOWN | Local plan only; unrestricted access through judging not established. |
| ip_license | UNKNOWN | Dependency/model/media and packaged PDF redistribution rights unresolved. No legal attestation. |
| secret_audit | PARTIAL | Changed files gate plus tracked/history inventory; historical findings require separate triage. |
| devpost_receipt | UNKNOWN | No Submitted receipt supplied; drafts/send intent cannot prove platform receipt. |

Run `python3 -B scripts/nebius_submission_preflight.py`. Expected current result: BLOCKED. The fixed mandatory set cannot be reduced by an input flag. Duplicate/unknown requirements, changed candidate, missing/hash-tampered/symlink evidence, fixture LIVE claims, incomplete responses, loopback demo, 180-second video, unresolved rights/secrets and Draft receipt fail closed. Receipt hashes establish local integrity; external facts still require independent human review. READY_TO_SUBMIT never submits or approves effects.

Historical LIVE source: `evidence/cloud_activation/live_smoke_20261003T130702Z.json`; exact Lightning, stop, no fallback. Later incomplete-completion evidence remains rejected. Existing fixture: `evidence/personal_ai_vertical_slice/manifest_final_20261003T135440Z.json`, not public deployment. Current unified fixture: `docs/integration/ONE_SYSTEM_VERTICAL_SLICE.md`. Model identity/license source: [NVIDIA model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16), OpenMDW-1.1; hosted-service terms remain human review.
