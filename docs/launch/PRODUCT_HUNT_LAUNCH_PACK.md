# AIOA spArkHAT — Product Hunt launch pack
Prepared: 2026-10-13. **Draft — not submitted or scheduled.**
This pack is for a truthful, evidence-scoped open-source early-access launch. Human operator must review final external claims, account identity and rights before publishing.

## Submission fields

**Product name:** AIOA spArkHAT

**Tagline (max 60 chars, actual 56):** Human-governed AI agents with receipts and replay safety

**Description (max 260 chars, actual 247):**
AIOA spArkHAT is an open-source runtime for long-running AI agents. It separates model advice from human authority, checks evidence, gates consequential effects behind explicit approval, and records durable receipts for auditing and replay safety.

**Primary URL:** https://sparkhat.eu/aioa/ (product explanation and four demonstrations)
**Source code:** https://github.com/luciferprosun/AIOA-spArkHAT
**Demo video:** https://youtu.be/ABJijoNKmYM
**Sponsorship / collaboration:** https://sparkhat.eu/#sponsorship (check anchor behavior prior to public linking)

**Suggested topics (select at most 3, exact taxonomy must be checked in form):** AI Agents, Open Source, Developer Tools.

## Maker's first comment

Hi Product Hunt! I'm one of the makers of AIOA spArkHAT. We built an open-source, human-governed runtime for agentic workflows after seeing how easy it is to mistake a model's suggestion for an approved action.

AIOA makes the boundaries explicit: provider output is advisory, evidence has provenance, consequential operations require exact human approval, and receipts plus independent readback help us reason about restarts and replay safety.

This is a research-stage, local-first prototype, **not** a production autonomous desktop operator. Our GitHub has reproducible offline reviewer steps and bounded MCP READ support. We also publish the limitations instead of hiding them: the recorded 3×8-hour endurance evidence is *segmented*, not a certified contiguous GOLD24 result; live provider certification and external rights review remain separate work.

We are looking for critical technical feedback, collaborators experienced in agent safety/testing, and practical support such as development hardware or cloud credits. If you try the reproducible demo, please tell us what breaks or seems unclear. Thank you!

## Gallery / assets checklist

1. Screenshot of the existing AIOA product overview at https://sparkhat.eu/aioa/ (check visible content before publishing).
2. Architecture diagram from the current README: provider advisory → CPL/evidence → human approval → ServiceGuard → receipt/readback.
3. Screenshot of a real offline reviewer run showing exact tested commit SHA and fixture label. **Capture a new run; never fabricate a screenshot.**
4. Optional screenshot of a real receipt/replay scenario with synthetic data only.
5. Existing YouTube demo above; verify captions, audio, accessibility, and rights.

Do not upload personally identifiable logs, browser profiles, credentials, private EagleEYE material, third-party media without rights or unsupported live-provider claims.

## GOLD24 claim gate

**GOLD24 is NOT currently evidenced by public main.** Existing [segmented test manifest](../../reports/SEGMENTED_ENDURANCE_3X8_MANIFEST.json) explicitly says `"contiguous_24h_pass_closed": false`. The [GOLD24 plan](../NVIDIA_GOLD24H_CONTEXT_CONTINUITY.md) explicitly disclaims `24H_PASS_CLOSED`.

User-supplied proposed metrics (86,426 s, 722 checkpoints, 0 replay) are **UNVERIFIED** pending an immutable report of the contiguous candidate run.

The following requested banner is held for later release; **do not copy it into the visible README until the validation gates below pass**:

```md
# AIOA spArkHAT 🐾
### Long-Running Agent | NVIDIA Claw Challenge Berlin 2026
![GOLD24](https://img.shields.io/badge/GOLD24-PASSED-00FF00)
![Uptime](https://img.shields.io/badge/Uptime-86%2C426s-blue)
![Checkpoints](https://img.shields.io/badge/Checkpoints-722-orange)
![Replay](https://img.shields.io/badge/Replay-0-red)
```

Required evidence before rendering PASSED:
- exact freeze SHA, immutable 24h manifest, harness revision and signed/hashed start/end checkpoints;
- declared *contiguous* clock policy and >= 86,400 attested elapsed/active seconds, including interpretation of claimed 86,426 seconds;
- 722 reconstructible checkpoints with hash-chain integrity and source/evidence digests;
- precise definition of "Replay 0" (e.g., zero duplicate dispatches, **not** zero replay tests), receipt/readback audit and failure/UNKNOWN accounting;
- scenario matrix and human-approval receipts, not simply a watchdog timer;
- human review of technical and legal/media claims plus link to verified artifacts.

## Before clicking publish

- [ ] Correct main/branch release SHA and evidence links verified
- [ ] Website no longer points to stale `AOIA-Core` as canonical source
- [ ] Run the official offline reviewer and preserve a SHA-bound result
- [ ] Confirm product title, thumbnail, gallery, demo rights and contact page
- [ ] Complete security/rights sweep and remove any confidential data
- [ ] Use a personal Product Hunt account; finish account onboarding
- [ ] Publish only after explicitly reviewing live page/preview
- [ ] Ask community for feedback or visits — **not for upvotes**
- [ ] If seeking sponsors, make a clear, legitimate route for donations/support; PH itself is not a grant approval

Official guide: https://www.producthunt.com/launch
