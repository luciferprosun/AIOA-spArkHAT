# AIOA METAGuardiansSPARK — META 2026 START LINE
> **Current identity (31 October 2026):** AIOA METAGuardiansSPARK / branch `AIOA-METAGuardiansSPARK`. The former `meta` branch was renamed; its original commit history and historical evidence remain preserved. This work is part of the unified AIOA spArkHAT repository.

### Meta Global AI Developer Hackathon · Muse × Chromium × MCP × Human-Governed Agents

> **STATUS: PARTICIPATION APPROVED · IMPLEMENTATION ACTIVE (G1 DONE, G2 PREP) · LIVE META/CHROMIUM NOT YET VERIFIED**
>
> **Prepared:** 20 October 2026 · **Working branch:** `AIOA-METAGuardiansSPARK` · **Build window:** 26 October–4 November 2026 · **Final submission deadline:** 4 November, **9:00 PM ET** (subject to the organizer's current rules).
>
> This charter was prepared **before kickoff**. The owner authorized isolated offline development on 26 October. G1 contracts and G2 network admission screening have now been added, but **no real Meta-model invocation or Chromium computer-use session has been verified**. Live effects, browser installation, credentials, and API spending require independent gates.

**The idea:** *One governed AI agent, many models, real computer work — with the human retaining authority.*

**Project:** [AIOA spArkHAT](https://sparkhat.eu/aioa/) · **Canonical repository:** [luciferprosun/AIOA-spArkHAT](https://github.com/luciferprosun/AIOA-spArkHAT) · **Meta branch:** [`AIOA-METAGuardiansSPARK`](https://github.com/luciferprosun/AIOA-spArkHAT/tree/AIOA-METAGuardiansSPARK) · **Event:** [Meta Global AI Developer Hackathon](https://cerebralvalley.ai/e/meta-ai-developer-hackathon)

---

**Implementation checkpoint (26 October):** G1 offline contracts plus G2 preliminary network admission checks; **38/38 hermetic unit tests PASS** on an isolated Linux checkout. See [`docs/meta/META_G0_G1_KICKOFF.md`](docs/meta/META_G0_G1_KICKOFF.md) and [`docs/meta/META_G2_NETWORK_PREVIEW.md`](docs/meta/META_G2_NETWORK_PREVIEW.md). G2 real Chromium and G3 real Meta are still pending. The original date-by-date roadmap below remains the plan, not evidence of completed gates.

---

## 1. Mission and product story

Most AI agents can reason about work. Far fewer can **carry work across a remote computer, a real browser, and future business services while preserving auditable human control**. We want to demonstrate a clear alternative to a black-box, unlimited-permission autonomous agent.

**AIOA METAGuardiansSPARK** is the planned Meta-model-powered browser/desktop orchestration extension of the existing AIOA system:

- **Meta Muse / Meta Model API:** the competition's agentic reasoning and perception layer, tasked with producing bounded plans, tool requests, critiques, and explanations.
- **Chromium:** an isolated browser environment for controlled inspection, navigation, evidence capture, and (only after the appropriate gate) approved actions.
- **MCP Commander / AIOA Core:** existing transport, typed task boundary, policy checks, receipts, and human-rooted authority. GitHub Task Bus may carry tasks/results but never grants permission.
- **Android-first operator experience:** the owner can eventually request work and review evidence/approvals on a phone while the computer runs Linux. Voice is an intended input option; it is not a security credential.
- **Google Gmail API (parallel track):** a future communication adapter developed separately, reusable by AIOA and later by the Meta scenario **only after its own security, OAuth, and owner-approval gates**.
- **HAT / CPL / Verified Delta / Non-Zero:** reuse AIOA's knowledge/provenance and verification concepts without pretending experimental modules are production-proven.

**Not the goal:** unrestricted browser takeover; a new second AIOA Core; silent email sending; a model declaring its own approvals; publishing personal browser/Gmail data; or a sprawling multi-agent swarm without measurable evidence.

### Proposed user story (target demo, not a currently working feature)

1. The owner, using Android, asks: **“Research three public documentation pages, compare their API approaches, and prepare a short decision memo.”**
2. A **real Meta model call** helps interpret the task, propose a bounded browser plan, and identify uncertainty.
3. AIOA admits only a typed, policy-permitted task; the Linux-side Chromium adapter uses an isolated browser context to visit the allowlisted public pages.
4. The agent produces **source URLs, timestamped observations, page excerpts/screenshots with provenance, and a concise report**. The human sees what actually happened rather than being asked to trust the model's narrative.
5. If the next action would write, submit, download from an unknown origin, touch accounts, send mail, or otherwise cause a protected effect, **STOP → exact preview → owner decision → one bounded attempt → verification/receipt**.
6. **Gmail is optional for the hackathon MVP**: a sample draft/approval preview may demonstrate the future integration. Real Gmail OAuth/read/send is **not** a prerequisite for proving the browser agent.

**Long-term vision:** a controlled computer-use agent for office work across Linux first and other platforms later, accessible from Android. The ten-day competition deliverable is deliberately narrower.

---

## 2. What exists today vs. what is proposed

| Component | Current evidence / source | Meta-hackathon status |
| --- | --- | --- |
| AIOA canonical core, policy and provenance | `README.md`; `docs/architecture/UNIFICATION_2026-10-09.md` | **Existing baseline**; validate exact source SHA at kickoff |
| MCP Commander remote READ path | `MCP_Server/LIVE_E2E_STATUS.md`; `runtime/mcp_bridge/` | **Historical verified READ**, not proof of effectful browser execution |
| Human approval / Non-Zero constraints | Existing policy contracts; `docs/architecture/MCP_APPROVAL_TOKEN_V1_FIXTURE.md` | **Architecture baseline**; offline test fixture ≠ live human warrant |
| Meta event application | Cerebral Valley event-status email, **APPROVED**, 20 Oct 2026 | **Participation approved**; API credits/credentials/rules still separate |
| Meta Model API and Muse Code | Official Meta developer documentation | **Products exist**; this repo has **no verified live integration** |
| Chromium execution adapter | Architectural proposal in this file | **NOT BUILT** |
| Mobile-to-browser operator flow | Product design / future UI | **NOT BUILT or live-authorized** |
| Gmail API Gateway | Separate branch `feature/aioa-gmail-gateway` and Gmail architecture roadmap | **Parallel independent work**; no assumption of OAuth, live send, or approved merge |
| GOLD72 / Linux Codex sprint | Separate development and evidence track | **Protected**; no changes or concurrency assumptions made here |

**Start-line base SHA:** `81656e6ccbb0c02307d049e865b6df3225ddb578` (the verified `main` / `AIOA-METAGuardiansSPARK` common head before this documentation commit). This is a planning reference, **not** a claim that a newer local Sprint 34 state was integrated or that the Meta baseline will never change.

### Three distinct meanings of “Muse”

1. **Meta Model API** is the planned inference interface for the running agent. The hackathon demo should visibly depend on an eligible Meta model, not merely use an LLM to write code.
2. **Muse Code** is Meta's coding agent CLI, potentially useful *during authorized development* for bounded tasks or independent review. Using Muse Code as a developer tool does **not by itself** prove our product integrates a Meta model at runtime.
3. **Muse Spark Open / other hosted options** may be evaluated only under the official hackathon rules, hardware budget, licensing, and verified provider access. Running an enormous open-weight model locally is **not assumed** on a lightweight Linux PC.

The model/version, permitted API surface, credits, cost policy, and official competition requirements must be confirmed on/after kickoff. No credit, subscription, or live account access is assumed to be activated by the APPROVED email.

---

## 3. Proposed architecture — one Core, separate adapters

~~~mermaid
flowchart TD
    Owner["Human owner: Android / text / later voice"]
    UI["Mission Control: tasks, evidence, exact approval, STOP"]
    Meta["Meta Model API: Muse planner / perception / critic"]
    Core["AIOA Core: Non-Zero + ServiceGuard + provenance"]
    Gate{"Policy & owner authority"}
    MCP["MCP Commander: typed transport / local worker"]
    Browser["Chromium adapter: isolated profile / allowlisted tools"]
    Evidence["Receipts + verified observations + HAT staging"]
    Gmail["Gmail Gateway branch: future CommunicationPort"]
    MuseCode["Muse Code CLI: optional build-time helper"]

    Owner --> UI
    UI --> Core
    Meta -->|"untrusted proposals"| Core
    Core --> Gate
    Gate -->|"approved bounded READ / permitted action"| MCP
    MCP --> Browser
    Browser --> Evidence
    Evidence --> Core
    Core --> UI
    Gate -.->|"separate approval + later integration"| Gmail
    MuseCode -.->|"development only, bounded isolated work"| Core
~~~

**Trust model:**

- The **model proposes**; deterministic AIOA policy and **the real human authorize** protected effects. **`provider != authority`**.
- Meta output, web pages, screenshots, retrieved text, Gmail messages, GitHub issues, and tool responses are **untrusted input**, not instructions that override policy.
- The existing remote MCP READ path does **not** imply WRITE/EXEC or browser-control authority. Browser execution will require a **new, explicitly audited boundary**.
- Browser control should prefer a **fresh isolated Chromium context** (e.g. evaluate Playwright/CDP integration), not an existing personal Chrome profile. Scope by allowed origins, operations, time, workspace, and budgets.
- A browser click can be a **real-world effect**. Classify actions by risk; treat submits, purchases, uploads, account changes, authentication, downloads, messages and external writes as protected. Approval must bind the **exact proposed action and target**, not a vague “yes, use browser”.
- For every uncertain effect outcome, record **UNKNOWN → reconcile → human decision**, never blindly replay. Retrying reads and retrying writes are different policies.
- Credential and cookie custody remains **outside the LLM prompt and public repo**. Secrets, raw personal emails, browser profiles, cookies, screenshots of personal accounts, and access logs are excluded from public evidence.
- Models cannot mint approvals, select privileged owner IDs, bypass STOP, expand scopes, select arbitrary workspaces, push to main, or authorize spending.

### Proposed *contracts* (names for future design, not implemented classes)

| Port / envelope | Minimum intended properties |
| --- | --- |
| `BrowserTaskV1` | Task ID, owner scope, origin allowlist, navigation intent, allowed tool set, source SHA, deadline, budgets |
| `BrowserObservationV1` | Correlation ID, final URL, timestamp, provenance, content/screenshot references, observed error/state |
| `BrowserActionProposalV1` | Exact action + target, risk classification, parameters, expected outcome, evidence and expiry |
| `OwnerWarrantRefV1` | Independently verified owner approval bound to exact payload hash, nonce, scope, resource, expiry and one-use semantics |
| `BrowserReceiptV1` | Attempt ID, pre-effect intent, status `DONE / DENIED / UNKNOWN / STOPPED`, target readback and evidence references |
| `CommunicationPort` / `MailProviderPort` | Future Gmail integration with the **same** Core authority, separate consent and durable outbox |

**Implementation location (proposal only):** decide after kickoff whether an additive module such as `runtime/browser_agent/` and a narrow `MCP_Server` extension fit the actual current repo. Do **not** create a second Core, public execution daemon, or hard dependency on Gmail.

---

## 4. Parallel-branch policy: Meta ≠ Gmail ≠ Linux sprint

| Branch / workstream | Ownership and rule |
| --- | --- |
| `main` | Canonical protected AIOA. **No hackathon-prep edits here.** |
| `AIOA-METAGuardiansSPARK` | **Only this planning document until owner GO and 26 Oct kickoff.** Future competition implementation stays here until reviewed. |
| `feature/aioa-gmail-gateway` | Independent Google Gmail API effort. Keep its code, OAuth, token custody, and release gates separate. |
| Local Codex Sprint 34 / GOLD72 | Do not touch frozen run, evidence, checkout, caches, checkpoints, tests, or resources. No simultaneous heavyweight build on a 4 GB PC. |

**Merge discipline:** before any Gmail → Meta integration, inspect branch head SHAs, module contracts, consent scopes, and owner-approval authority. Use a small reviewed port/cherry-pick or explicit integration PR. No automatic branch merge or silent transfer of OAuth credentials. Similarly, do not assume local Codex changes are already on `main`.

**Conflict avoidance:** one writer per worktree; separate working trees; no force push; no credentials in Git; no editing another agent's active sprint; changes documented by exact commit and a reversible PR when implementation starts.

---

## 5. Ten-day execution map — working schedule, status updated 26 October

| Day | Date (2026) | Focus / reviewable output | Exit gate |
| --- | --- | --- | --- |
| **D1** | **26 Oct** | Confirm event rules, eligible model, Meta credits/access, owner GO, branch/source pins, scope & threat model; start only the smallest offline skeleton afterward | `META-G0: GO / BLOCKED` |
| D2 | 27 Oct | Typed browser task/observation contracts; synthetic fixtures; domain, path, and action classification tests | `META-G1: CONTRACTS` |
| D3 | 28 Oct | Isolated Chromium connector + public-page READ/navigation, timeout/cancel/STOP | `META-G2: BROWSER-READ` |
| D4 | 29 Oct | Real, budget-controlled Meta Model API planning/perception path; audit raw provider receipts without secrets | `META-G3: REAL-META` |
| D5 | 30 Oct | AIOA↔MCP↔Chromium correlation, provenance, verified page evidence, tamper and injection tests | `META-G4: EVIDENCE` |
| D6 | 31 Oct | Risk-tiered click/action proposals and exact owner approval in synthetic scenarios; never grant silent WRITE | `META-G5: APPROVAL` |
| D7 | 1 Nov | Android-friendly mission/status/STOP preview, one coherent vertical slice; optional voice UI only if safe | `META-G6: OPERATOR` |
| D8 | 2 Nov | Optional Gmail *draft-only* compatibility demo if that branch independently passes gates; security and failure hardening | `META-G7: INTEGRATION / SKIP` |
| D9 | 3 Nov | Clean-room reviewer run; E2E tests; reproducible setup; diagrams, demo capture, cost and provenance report | `META-G8: DEMO-READY` |
| **D10** | **4 Nov** | Final regression, license/privacy checks, 2–3 min demonstration, submission package, human review and official submission | `META-G9: SUBMITTED-RECEIPT` |

**Hard deadline:** 4 November 2026 at **9:00 PM ET**, per the organizer's published schedule, which may change. Allocate submission buffer rather than starting upload at the last minute. **Event acceptance ≠ submission acceptance, credit activation or prize.**

**Critical-path MVP:** **Meta model → bounded AIOA policy → isolated Chromium READ/navigation → evidence → Android-visible result and STOP**. Everything else is optional and must not jeopardize that verifiable flow.

**Scope cuts, in order:** live Gmail SEND/READ → multi-browser support → multi-agent debate → advanced mobile voice controls → general desktop WRITE/EXEC. Keep a smaller, demonstrably real Meta + Chromium path rather than an expansive, unverified promise.

---

## 6. Security and reliability acceptance tests to design after START

The first test set must include positive cases *and* fail-closed adversarial cases:

1. Public website contains an instruction telling the agent to ignore policy or reveal secrets → treated as page content, **not authority**.
2. Browser is redirected outside origin allowlist, to local network/private IP, or to an unsafe download → **DENY**.
3. Screenshot or HTML disagrees with the model's claim → record uncertainty, do not certify success.
4. Owner approval is absent, expired, forged, for a different URL/action, or already consumed → **DENY**.
5. Worker/job loses its acknowledgement after a possible effect → **UNKNOWN**, reconcile without automatic duplicate action.
6. Model requests shell commands, Git push, OAuth token, Gmail send, or unexpected tool expansion → **DENY/STOP**.
7. Browser/Meta API is unavailable, quota exceeded, or cost ceiling reached → **bounded failure**, not a silent provider substitution.
8. Multiple simultaneous requests or cancellation occur → no cross-task profile, cookie, evidence, or owner-scope leakage.
9. UI shows a completed action without corresponding recorded evidence → **FAIL**, do not count a screenshot as proof of an unseen operation.
10. Offline fixture PASS is not relabelled as a live Meta/browser PASS; results include precise **environment, SHA, timestamp, and scope**.

**Minimum demo acceptance:**
- [ ] At least one real call through an eligible Meta model, identified by model/version and safe receipt.
- [ ] At least one real Chromium task with allowlisted pages and reproducible observation/readback.
- [ ] No unauthorized write, shell command, external send, token leak, or undisclosed spend.
- [ ] A working owner-visible STOP and explicit human gate for protected effects.
- [ ] Validated error path and readback evidence, not only an attractive UI.
- [ ] Reproducible clean run, bounded demo script, and correctly scoped test report.
- [ ] Accepted submission receipt at the organizer's official destination, after owner authorization.

The historic GOLD24 record belongs to another evidence scope; it must not be used as proof that the new browser integration passed a 24/72-hour test.

---

## 7. Kickoff checklist / required owner decisions

**Completed before kickoff:**
- [x] Meta Global AI Developer Hackathon participation status: **APPROVED**, organizer email dated 20 Oct 2026.
- [x] Dedicated Git branch: `AIOA-METAGuardiansSPARK` created from canonical `main`.
- [x] Parallel Gmail branch identified: `feature/aioa-gmail-gateway`.
- [x] Existing MCP READ and authority boundaries inspected from repository documentation.
- [x] Documentation-only competition charter prepared; **no hackathon code started**.

**Pending; no implied consent:**
- [ ] Organizer publishes final official rules; owner accepts applicable rules, eligibility, reuse/open-source and team terms.
- [ ] Meta account/API access and credited quota actually appear; confirm allowable models, prices, data-handling mode, and cost ceiling.
- [ ] Record current `main` / `AIOA-METAGuardiansSPARK` / Gmail head SHAs; decide whether to reconcile any newer Linux code **without disturbing Sprint 34/GOLD72**.
- [ ] Decide whether browser uses Playwright/CDP or an existing permitted Chromium interface after an isolated technical evaluation.
- [ ] Choose minimal demo domains, synthetic/non-sensitive data, and owner approval UX.
- [ ] Confirm permitted team/individual category, submission portal, judging criteria, artifact requirements, licensing and deadline.
- [ ] Obtain the owner's **explicit “START META — GO”** on or after kickoff. Until then: **DOCUMENTATION ONLY**.

**Not authorized at this stage:** install Muse, log into Model API from the Linux worker, configure Gmail OAuth, create secrets, call paid APIs, run Chromium with a personal profile, open WRITE/EXEC rights, deploy endpoints, trigger external email, merge to main, or submit a competition project.

---

## 8. Evidence, demo and handoff conventions (for later)

On implementation start, create evidence artifacts only in authorized paths, with data minimization. Proposed **future** index (not created now):

~~~text
docs/hackathons/meta/
  ARCHITECTURE_DECISIONS.md
  SECURITY_THREAT_MODEL.md
  TEST_MATRIX.md
  EVIDENCE_INDEX.md
  SUBMISSION_CHECKLIST.md
reports/meta/
  verified-run-manifest.json
~~~

Each feature report should say **IMPLEMENTED / OFFLINE-TESTED / LIVE-VERIFIED / BLOCKED / NOT-STARTED**, identify the exact SHA and reproducible steps, and document whether the human granted consequential authority. Screenshots/videos must be sanitized and must not capture private email, account cookies, or API secrets.

**Competition narrative:** *“A phone requests an outcome; a Meta model reasons over a real website; AIOA verifies a bounded browser workflow; the owner retains control of effects. Gmail is a reusable future communication adapter, not a shortcut around human approval.”*

### Canonical internal sources

- [AIOA main README](README.md)
- [MCP live READ evidence](MCP_Server/LIVE_E2E_STATUS.md)
- [MCP task-bus contract](MCP_Server/TASK_BUS_PROTOCOL.md)
- [One-system unification and policy](docs/architecture/UNIFICATION_2026-10-09.md)
- [ApprovalToken offline fixture — NOT live owner authority](docs/architecture/MCP_APPROVAL_TOKEN_V1_FIXTURE.md)
- [Parallel Gmail Gateway branch](https://github.com/luciferprosun/AIOA-spArkHAT/tree/feature/aioa-gmail-gateway)

### Official sources to recheck on kickoff

- [Meta hackathon — event and application](https://cerebralvalley.ai/e/meta-ai-developer-hackathon)
- [Meta hackathon — dates, participant terms and announcements](https://dev.meta.ai/events/global-hackathon)
- [Meta Model API](https://dev.meta.ai/docs/overview)
- [Muse Code](https://dev.meta.ai/docs/muse-code)
- [Muse model catalogue](https://dev.meta.ai/docs/models)

---

> ## STOP LINE
>
> **OFFLINE DEVELOPMENT STARTED — NOT READY TO CLAIM WORKING META/CHROMIUM INTEGRATION.**
>
> The pre-kickoff restriction ended on 26 October. The `AIOA-METAGuardiansSPARK` branch now contains contract code and offline tests. Preserve `main`, Gmail, Codex, and GOLD72 work unchanged; no unreviewed merge, unattended effect, API spending, or browser escalation.
