# NVIDIA competition demo runbook

## Purpose and scope

Show one auditable maintenance workflow in AIOA spArkHAT, not a collection of unrelated modules. The organizer brief and official rules are mapped in [the submission checklist](NVIDIA_SUBMISSION_CHECKLIST.md). They ask for a useful long-running agent and a short working-demo video or site link. This runbook is a rehearsal, not a submission or proof of prize eligibility.

## Reproduce first

Use Python 3.11+ and a complete source checkout, including `tests/`:

```bash
python3 -I -B scripts/nvidia_reviewer_preflight.py
```

The script also supports invocation by absolute path from another working directory. No provider credential, paid inference, external database or Codex session is needed. It returns the artifact path, SHA-256 and individual checks. Default output is a fresh temporary directory. An explicit `--root` must be fresh and must not be a symlink; existing artifact files are never overwritten.

Expected summary: `status=PASS`, `stage_count=14`, `effect_executor=ServiceGuard`, `duplicate_effects=0`, `restart_replay_dispatches=0`, provider and memory `TEST_FIXTURE`, dynamics `SHADOW`.

## Four distinctions that must stay on screen

- Model replies and approval are controlled fixtures in this replay; the human-approval contract is exercised, not a new live human decision.
- The effect is real only inside a disposable loopback service, not on an AWS resource or the user's operating system.
- This demo tears down and recreates the runtime. Separate NV09/NV10 tests prove operating-system process-crash recovery; do not present a runtime recreation as a filmed OS crash.
- This short replay is not endurance evidence. The accepted `3x8h` result belongs to its recorded frozen SHA, not automatically to each later commit.

## Planned 90-second recording

Keep `TEST_FIXTURE` visible throughout the offline sequence. Timing below is an editorial target, not measured execution time.

| Time | Show | Say / prove |
| --- | --- | --- |
| 0–10 s | One mission and visible fixture label | "A long-running agent must keep advice separate from permission to act." |
| 10–25 s | Evidence/HAT, CPL and first verified delta | "The runtime records a verified correction, not critic agreement as truth." |
| 25–40 s | ZERO_WRITE reuse and stale-source revalidation | "Reuse avoids duplicate learning. Changed evidence forces revalidation." |
| 40–55 s | Approval contract and Service Guard | "In this controlled replay, a fixture exercises the explicit human-bound gate before one local maintenance effect." |
| 55–70 s | Receipt and independent measurement | "A receipt alone is not the result: the target is read back and checked independently." |
| 70–82 s | Runtime recreation and replay | "The same operation is reconciled without another effect." |
| 82–90 s | Separate CI and endurance evidence | "The replay is reproducible; the long-duration evidence is separately labelled 3x8 hours on its frozen version." |

## Evidence to keep distinct

| Evidence | Source | What it does not establish |
| --- | --- | --- |
| Short deterministic replay | Generated artifact and preflight summary | Current NVIDIA availability, live Cockroach, live OpenRouter or live AWS |
| Human-gate semantics | Service Guard tests and approval-bound receipt | That a person clicked approval during the automated fixture run |
| Fresh-process recovery | `tests/test_nv09_service_guard.py`, `tests/test_nv10_guard.py`, `tests/test_nv10_recovery.py` | Production-wide exactly-once guarantees across arbitrary external systems |
| Segmented endurance | [Closure](ENDURANCE_3X8_CLOSURE.md) and its manifest | A continuous 24-hour test or recertification of later code |
| NVIDIA adapter | Existing bounded live-validation evidence | An inference made during the offline replay |
| CI | Workflow run pinned to PR/commit SHA | Live-provider or separately provisioned Cockroach certification |

## Optional negative scene

Show a revoked/stale approval being refused using the existing NV09 tests. Do not add an auto-approve UI or bypass policy for the recording. Demonstrate only a controlled local target; do not use a real cloud resource for presentation optics.

## Release and recording gates

1. Confirm the exact recording candidate SHA and a clean checkout.
2. Require the supported offline suite, isolated preflight and both Python CI jobs to pass on that candidate. Do not merge while checks are pending or failing.
3. Label any separately captured live inference with its actual provider, timestamp, scope and outcome. A missing key means unavailable, never a silent fixture substitution.
4. Prepare the existing dashboard, record the sequence, then confirm the video is accessible to judges without exposing credentials or private state.
5. Verify the official submission brief/form, mandatory fields, deadline/timezone and rights before the final submit. The rules specify 2 October 2026 at 11:59 PM Pacific Standard Time; the operational target is earlier that day in Germany. Recheck the exact source wording and form before sending.

## Remaining focused sprint

- Before Codex returns on 24 September at approximately 15:00 Europe/Berlin: keep the reviewer path reproducible, preserve evidence and finish only bounded defects with tests.
- Codex sprint: take the remaining CDB-003 fixture-layout decision and CDB-004 dashboard clarity work from [the backlog](CODEX_BACKLOG.md). No new Core or authority route.
- Backend target freeze: 29 September; 30 September–2 October reserved for frontend, video and submission checks.
- OpenRouter live CPL waits for the operator's local setup and explicit bounded acceptance. It does not block this offline reviewer path.
- Gold 24h remains optional on a final frozen candidate only; never displace the recording/submission buffer.

## Related reviewer material

- [NVIDIA start here](reviewer/NVIDIA_REVIEWER_START_HERE.md)
- [Reviewer quickstart](REVIEWER_QUICKSTART.md)
- [Roadmap 2.1 closure](ROADMAP_2_1_CLOSURE.md)
- [Codex handoff](CODEX_HANDOFF_20260924.md)

NLnet/grant history and frozen hackathon repositories remain preserved. No EU proposal content is changed by this sprint.
