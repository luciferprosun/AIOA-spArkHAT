# AIOA spArkHAT — Product Hunt professional launch kit
Last updated: 2026-10-14. **Product Hunt launch is scheduled by the maker**, according to their Pre-Launch Dashboard seen on 2026-10-14: **November 13, 2026 at 00:01 PST** (shown by Product Hunt; recheck the site's displayed timezone and any changes before launch). The announcement/report here is live on GitHub, but does **not** itself publish Product Hunt early.

**Current public announcement:** [GOLD24 — engineering update](../announcements/GOLD24_24H_ENDURANCE_2026-10-14.md) · [Community feedback and hardware collaboration issue #20](https://github.com/luciferprosun/AIOA-spArkHAT/issues/20).

## Positioning

**One public product:** AIOA spArkHAT — the canonical open-source runtime. NVIDIA/Nebius, CockroachDB Memory Patch, Critical Prompt Loop (CPL), AWS Non-Zero and MCP READ are *modules/milestones*, not five unrelated products. Other Spark Hub research projects are portfolio context, not features of this runtime.

**One differentiator:** Models provide advice, not authority. Human approval is explicit, and durable records let the system distinguish a suggestion from a verified effect after a restart.

**The hero proof point:** September 28–29, 2026 **local GOLD24 endurance run**. A later checkpoint-chain review verified **722/722** compact-json checkpoint digests and **721/721** predecessor links. The local final report recorded `GOLD24_PASS`, **86,426 seconds of active time**, zero duplicate effects/redispatches and `fresh_process_reconstruction: VERIFIED`. Critical scope: replay attempts **0**, NVIDIA LIVE **UNAVAILABLE**, exact candidate SHA presently absent from public main, and raw checkpoints/harness not yet published. This is evidence of *local runtime endurance and checkpoint integrity*, not 24 hours of live AI inference or independently certified autonomous execution. [Technical limitations and checks](GOLD24_LOCAL_EVIDENCE_REVIEW_20261013.md).

This local GOLD24 report is DIFFERENT from the earlier [3×8-hour segmented PASS](../../reports/SEGMENTED_ENDURANCE_3X8_MANIFEST.json); keep both records intact.

## Personal Product Hunt maker profile

Product Hunt asks people to create a **personal account**, not a corporate/multi-account proxy. Keep the account's existing identity; do not create duplicate Product Hunt accounts or attempt to merge third-party identities automatically.

**Display name proposal:** Łukasz Żuchowski (or the already-verified personal account name; do not rename automatically)

**Maker headline:** Open-source AI safety builder · AIOA spArkHAT

**About / bio:** Independent AI safety and open-source builder. Building AIOA spArkHAT: human-governed agents, verifiable memory, and evidence-based recovery.

**Website:** https://sparkhat.eu/
**Professional profile:** https://www.linkedin.com/in/%C5%82ukasz-%C5%BCuchowski-807160316/
**GitHub:** https://github.com/luciferprosun
**Contact:** https://sparkhat.eu/contact/

Public aliases on the website include LuciferSOL / LuciferSun. Present them as **project or creator labels**, not separate Product Hunt maker accounts. Don't claim other collaborators' consent or roles without checking with them.

## Product Hunt submission — copy-ready fields

**Name:** AIOA spArkHAT

**Tagline (56/60):**
AI agents with human approval and 24h endurance evidence

**Short description (240/260):**
AIOA spArkHAT is a local-first, open-source runtime for human-governed AI agents. A Sept 2026 endurance run recorded 86,426 active seconds and 722 hash-linked checkpoints. Models advise; people approve; durable state supports safe recovery.

**Main product URL:** https://sparkhat.eu/aioa/
**Code / GitHub:** https://github.com/luciferprosun/AIOA-spArkHAT
**Demo video:** https://youtu.be/ABJijoNKmYM
**Evidence:** https://github.com/luciferprosun/AIOA-spArkHAT/blob/main/docs/launch/GOLD24_LOCAL_EVIDENCE_REVIEW_20261013.md
**Hardware and collaboration support:** https://sparkhat.eu/sponsorship/
**Suggested topics:** AI Agents, Open Source, Developer Tools (verify actual options and select up to three in the live form).

Use the existing site logo if usage rights and sizing are suitable. Product Hunt guidelines expect a clear product thumbnail and gallery, not artificially generated result screenshots.

### Maker's first comment — recommended

Hi Product Hunt! I'm an independent builder working on AIOA spArkHAT, an open-source runtime for AI agents that keeps one important boundary explicit: **a model can recommend an action, but it cannot authorize its own effects.**

We built AIOA through several hackathon milestones: Critical Prompt Loop for model critique, Memory Patch for reviewable memory, Non-Zero for fail-closed action control, and the NVIDIA Claw/GO24 resilience work. These are modules in **one** evolving runtime, with explicit approval, guarded execution, independent verification, and audit receipts.

One of our strongest engineering milestones was a **local, 24-hour GOLD24 endurance run on September 28–29, 2026**. Its final report recorded **86,426 active seconds and 722 checkpoints**. We subsequently checked every checkpoint digest (722/722) and predecessor link (721/721). The reported execution observed **zero duplicate redispatches**. The scope matters: it was not a live NVIDIA inference test, there were **zero replay attempts**, and the historical tested source commit still needs a public reproducibility package. We're publishing these limitations along with the positive result.

We're developing with limited hardware: much of the work has been done on a **4 GB RAM computer without a dedicated GPU**. What would make the next round possible? A used Linux-compatible workstation or mini PC, more RAM/SSD storage, GPU time, cloud/API credits, and above all rigorous feedback from people experienced with agent reliability, security, distributed state, and testing.

If this problem interests you, explore the [demo and architecture](https://sparkhat.eu/aioa/), [review the code](https://github.com/luciferprosun/AIOA-spArkHAT), or read our [practical hardware-support request](https://sparkhat.eu/sponsorship/). Please try to find the failure cases we haven't found yet. We welcome collaborators and independent critics.

### Long-form technical overview (for launch post, website FAQ, or comments)

AIOA starts from a risk: in long-running agents, fluent model output can be mistaken for reliable evidence or permission. Our design separates these layers:

1. **Advice:** Nebius/NVIDIA and other optional providers propose; no provider grants permission.
2. **Evidence and criticism:** HAT provenance, verification, CPL critic candidates and Verified Delta preserve scope and contradictions.
3. **Memory:** Native Memory Patch / optional CockroachDB supports controlled, inspectable state; retrieved text never automatically becomes truth.
4. **Non-Zero and human authority:** Consequential writes/actions require exact operator approval and bounded policy.
5. **Execution:** ServiceGuard mediates effects, independent readback checks the result and a durable receipt helps prevent blind re-dispatch.
6. **Transport:** MCP Commander GitHub bus is bounded READ-only in unattended remote mode; automatic WRITE/EXEC is not enabled by this launch.
7. **Resilience:** Checkpoints are explicit durable evidence, rather than relying on an endlessly open model chat or unfounded memory.

**GOLD24 chronology:** A local run began on 2026-09-28 04:13:17 UTC and ended 2026-09-29 04:14:05 UTC (86,448 wall seconds); its report claims 86,426 active seconds. A collection of 722 JSON checkpoint records from 000000 to 000721 passed local cryptographic chain rechecking on October 13. The harness had a 120-second heartbeat and a 300-second lease; the report recorded CockroachDB READY, fresh-process reconstruction VERIFIED and zero duplicate effects. No live NVIDIA calls were made. It does not demonstrate 24h of user-task throughput or validated replay fault-injection. The tested candidate SHA `2b0443fe1e60b8497da1923b7fc860f6c2f8c5cb` is not accessible through this repository at time of review. The source and sanitized raw evidence need an operator-reviewed release for independent reproduction.

### Feature tiles / gallery captions

- **Model advice ≠ permission** — advisory providers stay outside the execution authority.
- **Human-gated effects** — ServiceGuard enforces explicit scope and controlled actions.
- **Receipts and restart-aware state** — persist what happened, then check before retrying.
- **GOLD24 local endurance** — 86,426 active seconds, 722 hash-linked checkpoints (technical scope disclosed).
- **One modular open-source system** — CPL, Memory Patch/CockroachDB, Non-Zero, NVIDIA/Nebius, MCP READ.

## Image and video gallery to prepare

1. Cover: existing AIOA GO24 branded visual from https://sparkhat.eu/aioa/ — verify rights and avoid suggesting independent certification.
2. Real screenshot of AIOA console and exact `TEST_FIXTURE` label; use new, operator-reviewed screenshot.
3. Architecture flow diagram made from current README or real current diagrams.
4. GOLD24 evidence graphic with observed numbers AND footnote `local endurance; no NVIDIA LIVE; no replay attempts` — not a fake log screenshot.
5. Link the existing NVIDIA demo (https://youtu.be/ABJijoNKmYM) and optionally refer to prior milestones via the public AIOA page.

## Verified public link inventory from sparkhat.eu

These links were observed on the public website. **This unifies discovery/navigation, not account ownership or third-party authentication.**

| Role | Verified public URL | Where to use |
| --- | --- | --- |
| Product / GO24 presentation | https://sparkhat.eu/aioa/ | Primary PH product URL |
| Research hub | https://sparkhat.eu/ | Maker's website |
| Repository (canonical) | https://github.com/luciferprosun/AIOA-spArkHAT | PH code link |
| GitHub creator portfolio | https://github.com/luciferprosun | Maker/creator links |
| Sponsorship | https://sparkhat.eu/sponsorship/ | First comment/support CTA |
| Contact | https://sparkhat.eu/contact/ | Contact route |
| LinkedIn (percent encoded) | https://www.linkedin.com/in/%C5%82ukasz-%C5%BCuchowski-807160316/ | Maker's professional social, if accepted by field |
| Devpost portfolio | https://devpost.com/tonystarrkarc | Prior public hackathons |
| NVIDIA/Claw AIOA video | https://youtu.be/ABJijoNKmYM | Main PH demo |
| CPL video | https://youtu.be/4pqGT7QawkQ | Milestone history |
| CockroachDB Memory video | https://youtu.be/FWHA8iBbMEQ | Milestone history |
| Non-Zero video | https://youtu.be/f_b__0U2wu8 | Milestone history |
| Facebook creator | https://www.facebook.com/LuciferSun333/ | Optional social context |
| Facebook Proxima Centauri | https://www.facebook.com/ProximaCentauri333/ | Separate research theme, not PH primary |
| Manifund public profile | https://manifund.org/tonystarrkarc | Support context only |
| Manifund AIOA proposal | https://manifund.org/projects/aioa | **Access denied when checked**: avoid primary CTA |
| Grantmaking.ai AIOA page | https://app.grantmaking.ai/projects/5f6fe49a-ba80-4840-a86b-81afcebf5dd3 | Research funding reference, not grant awarded |
| DoraHacks | https://dorahacks.io/hacker/U_ee54ffd52262 | Listed on site; external access not verified |
| Historical research record | https://zenodo.org/records/21233163 | Prior AOIA-Core snapshot, not current AIOA release |

GitBook and Hugging Face were discussed previously but **no verified direct public profile URLs were found in the site's reviewed link inventory**; do not invent them or add arbitrary account URLs. The live site's AIOA/contact sections still point at historical `AOIA-Core` in places: fix those pointers to the canonical `AIOA-spArkHAT` repository on the website before the launch.

## Support pitch — suitable, specific and non-pushy

**Short CTA:** “We're seeking donated or loaned Linux-compatible computers, RAM/SSDs, GPU/cloud credits and independent technical reviewers to continue transparent, human-governed agent research. Evidence and details: https://sparkhat.eu/sponsorship/.”

**Why here:** Product Hunt is a maker community, not a grants portal. Keep the product/problem/demo the focus; support is a natural, secondary invitation. Do not fabricate sponsor logos, hackathon rankings, grants, partnerships or awards.

## Pending launch-specific finishing tasks (as seen in the maker's Pre-Launch Dashboard)

- Confirm name and full description are correct after the maker's latest edits.
- Add/select *Product categories* as allowed by the live Product Hunt form.
- Review and, if needed, complete the *Video / Loom* section using the verified NVIDIA demo: https://www.youtube.com/watch?v=ABJijoNKmYM.
- Check thumbnail, gallery visuals, GitHub/source links and release status.
- The maker's first comment and additional-maker completion were marked complete on the screenshot; verify they remain correct.
- Check the sponsorship CTA does not displace the actual product/value proposition.
- Ensure public website URL points to the canonical repo and scope-qualified GOLD24 evidence page; the home.pl HTML patch was staged but not independently verified as deployed.
- Keep the scheduled date unless the owner specifically directs a change; do not start unauthorized marketing or artificial engagement.

## Remaining release and account actions

- [x] Maker logged in and launch has been scheduled in Product Hunt; check account eligibility and the dashboard again before the date.
- [x] Maker signed in to Product Hunt; no credentials or authentication bypasses used.
- [ ] Save a **draft**, check actual public identity, name, URLs, thumbnails and category choices.
- [ ] Review user-facing AIOA site, especially historical `AOIA-Core` links.
- [ ] Complete current-source and raw GOLD24 evidence/provenance publishing gates before claiming independently reproducible proof.
- [ ] Confirm third-party media/image rights and remove sensitive details from uploads.
- [ ] Review preview, release date, and account ownership; publish only with explicit operator confirmation.
- [ ] Ask visitors for a test or comment, **never request or trade upvotes**.

Official Product Hunt guidance: https://www.producthunt.com/launch and https://help.producthunt.com/en/articles/17350772-launch-guide
