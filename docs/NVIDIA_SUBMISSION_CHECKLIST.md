# NVIDIA Berlin submission checklist

Checked on 22 September 2026 against the organizer's brief linked from the approved Berlin Luma event, and its official rules. This is a release checklist, not a submitted entry or a legal-compliance certification.

## Organizer sources

- [Berlin challenge brief](https://concrete-panther-c83.notion.site/nvidia-claw-agent-challenge-berlin)
- [Official rules](https://concrete-panther-c83.notion.site/3c8f567d17cc8068b674f0dadf723bad)
- [Project submission form](https://airtable.com/appv9LCenF1eosKL7/pagLOxwVLzgiOaunm/form)

The rules specify **2 October 2026, 11:59 PM Pacific Standard Time** as the close. Do not silently replace the source's timezone wording with local time: our operational target remains to submit during 2 October in Germany, leaving a buffer. Recheck the live form/rules before submission. The 17 October Luma event is not the entry deadline.

## Entry and deliverables

- [ ] Confirm the entrant satisfies the rules: an individual, age 18+, resident of Germany, and not within an excluded sponsor-related group. Do not submit a corporate/institutional entry or claim a team's eligibility from one person's registration.
- [ ] Complete the actual project form. Luma approval, a public repository and a merged PR are not proof of project submission.
- [ ] Provide the working-demo video or site link. The brief recommends **60–90 seconds**.
- [ ] Supply a short description of the task, intended user and motivation.
- [ ] Check the actual form fields, current rules, media rights and link accessibility before sending; save the submission confirmation privately.

## Scope control

The brief allows any long-running agent that performs a real task over time without constant supervision. OpenClaw/NemoClaw are listed as resources, not as a mandatory framework in the fetched brief. A mandatory continuous 24-hour run is not stated there. Do not introduce an unneeded architecture migration to satisfy an invented requirement.

Human approval at a consequential action boundary is deliberate; show autonomous observation, bounded planning and recovery between those boundaries. Do not remove the approval gate merely to make the video look more autonomous.

## Match the three judging criteria

| Criterion | Available evidence | Remaining delivery gate |
| --- | --- | --- |
| Working deployment / technical execution | Reproducible 14-stage local replay, read-only ATIF-v1.7 trajectory sidecar, fresh-process tests, CI and separately pinned 3x8 evidence | Show an actual useful task in the final deployed prototype. A fixture-only replay is engineering evidence, not proof that an arbitrary real task is solved. |
| Innovation and creativity | CPL advisory review, verified-delta reuse, ZERO_WRITE, stale-source revalidation, separated execution authority | Explain one differentiator in plain language; do not promote SHADOW mechanisms without measured benefit. |
| Real-world value | Receipt/verification/replay example for operators of long-running maintenance agents | Name the user and show the before/after result, rather than only test counts or architecture terms. |

## Suggested description — draft, not submitted

AIOA spArkHAT is a local-first prototype for running AI-assisted maintenance workflows without letting model suggestions become permission to act. It combines evidence-aware review, advisory critics, verified memory updates and a guarded execution path. The reviewer demo shows one bounded local effect, its receipt, an independent read-back and recovery without repeating the effect. We built it to make long-running agents easier for an operator to inspect and control when providers fail, evidence changes or a process restarts. The public replay is clearly labelled TEST_FIXTURE; live-provider evidence and the frozen-version 3x8 endurance result are documented separately.

Adapt the draft to the actual recorded deployment before submitting. Never replace the fixture label with a live claim.

## Next execution priorities

1. Keep the published main and isolated reviewer launch green; preserve the exact tested version.
2. Preserve the completed reviewer-dashboard clarity: TEST_FIXTURE/LIVE, ZERO_WRITE, Core + human authority, ServiceGuard, receipt, independent verification, replay safety and SHADOW dynamics must remain visible.
3. Record the useful end-to-end result using [the demo runbook](NVIDIA_DEMO_RUNBOOK.md) and [submission pack](NVIDIA_SUBMISSION_PACK.md); keep live/fixture and human-approval labels visible.
4. Complete and verify the official project form before the operational cutoff. No submission is made by this checklist.

OpenRouter can be configured later. Additional grant drafting is not a prerequisite. The optional Gold24h is reserved for the **final frozen candidate after ordinary release gates**, using the [context-continuity plan](NVIDIA_GOLD24H_CONTEXT_CONTINUITY.md); it must not consume the recording/submission safety buffer. Existing frozen hackathon repositories and NLnet history remain preserved.
