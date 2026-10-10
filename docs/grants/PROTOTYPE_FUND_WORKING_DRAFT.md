# Prototype Fund — project working draft

**NOT SUBMITTED.** This is a technical project description for human review, not an eligibility declaration or completed application. Current official form, call dates, applicant identity, eligibility, work duration and budget remain unverified. No funding request, legal acceptance or participant commitment is made here.

## Short description — English

AIOA spArkHAT is an open-source, human-governed AI runtime. It keeps owner-scoped context, model advice, evidence and permission to act separate. Optional providers can propose bounded actions, while an exact human decision, a cost/risk governor and ServiceGuard control effects. Durable receipts, independent readback and replay checks make uncertainty visible rather than treating a model response as successful execution.

The project will investigate how these boundaries can remain understandable and testable as optional memory and MCP transport capabilities are integrated into one canonical system. Existing local fixtures provide a reproducible starting point. They do not establish production deployment, independent live-model correctness or legal clearance.

## Kurzbeschreibung — Deutsch

AIOA spArkHAT ist eine quelloffene, durch Menschen gesteuerte KI-Laufzeitumgebung. Sie trennt privaten, eigentümergebundenen Kontext, Modellvorschläge, Nachweise und Handlungsbefugnis. Optionale Modelle schlagen begrenzte Aktionen vor. Eine konkrete menschliche Freigabe, Kosten- und Risikogrenzen sowie ServiceGuard kontrollieren deren Ausführung. Dauerhafte Belege, unabhängiges Auslesen des Zielzustands und Wiederholungsschutz machen Unsicherheit sichtbar.

Das Vorhaben untersucht, wie diese Grenzen bei der Integration optionaler Speicherfunktionen und eines MCP-Transports in einem gemeinsamen System verständlich und prüfbar bleiben. Reproduzierbare lokale Tests bilden die Ausgangsbasis; sie sind kein Nachweis einer produktiven Bereitstellung oder rechtlichen Freigabe.

## Existing evidence and proposed work

| Area | Existing bounded capability | Proposed work, subject to audit |
| --- | --- | --- |
| Human authority | Native Core/ServiceGuard, exact approval and replay fixtures | Close remaining typed outcome/liability integration without adding another authority core |
| Context and evidence | Owner/HAT-scoped native memory, context capsules and receipt projections | Improve understandable evidence inspection and explicit uncertainty handling |
| Advice and resources | Optional exact-model ports and local paired cost/risk governor | Preserve bounded advice, explicit admission and truthful fixture/live labels |
| MCP boundary | Typed bounded READ transport and policy tests | Verify transport integration while keeping WRITE/EXEC behind separate exact local authorization |
| Usability and reproducibility | Unified offline reviewer and active CI contracts | Improve canonical documentation and evaluate whether users can distinguish advice, approval, effects and UNKNOWN |

These are draft technical work packages, not promised milestones or claims of novelty over specific external products. Compare alternatives using verified sources before making an innovation claim. Preserve already accepted local work and audit the remaining ARCHAIOA roadmap before estimating effort.

## Evidence to attach after human review

- Exact canonical source SHA, PR/CI receipts and license/provenance pointers.
- Reproducible offline commands with explicit prerequisites and fixture limitations.
- Open security queue: 30 fixture provenance observations, 10 historical binary/IP questions, transitive notices and historical secret findings.
- Human-reviewed applicant information, current official requirements, proposed schedule and justified budget.
- Any demonstration or video created personally by the operator; this preparation contains no such receipt.

## Human completion gates

Confirm the official call and form before transferring this draft. The applicant must personally verify eligibility, consent, identity, availability, rights and all legal declarations. Costs and duration stay blank until the relevant rules and engineering estimates are confirmed. Submission remains outside this engineering task.

## Q20 evidence baseline — 10 October 2026

Preparation status: **DRAFT / NOT SUBMITTED / HUMAN REVIEW PENDING**.
This dossier supplements the existing abstracts above; it does not start another product.

- Project: **AIOA spArkHAT**, repository `luciferprosun/AIOA-spArkHAT`, package `aioa-sparkhat`.
- Audited task base and HEAD: `8f455ae2183883f15ba578de196e6955cd2eb2e3` on `queue/ioar-auto-20261010-q20`. Draft edits remain uncommitted.
- Cached `origin/main`: `14d148bd85df90c1c631cedc584480fdca866f38`, an ancestor of the task base. This is not fresh remote verification: network/fetch is forbidden by this work order.
- Policy and roadmap read from the local `CODEX_IOAR_QUEUE_20261009` directory. The original 30-page PDF was unavailable.
- Q07–Q09 reports describe local primitives with incomplete G2/G3/G4 host integration. This independent documentation does not promote those gates.
- Official call, application fields, funding ceiling, cost categories, duration, deadlines and eligibility: **[OPERATOR: independently verify official current requirements and record URL, retrieval date and relevant rule]**. No official call was retrieved in this offline task. The hackathon timetable in the roadmap is not a Prototype Fund deadline.

## Problem and proposed research contribution — English

An agent may receive model advice, lose an acknowledgement, or restart while an operation's outcome remains uncertain. Users need evidence that separates permission, attempted execution and verified outcome. The proposed research asks whether a single human-governed runtime can keep that distinction durable across transport and recovery boundaries, while exposing only the minimum context required for a decision.

PCAF (Proof-Carrying Authority Fabric) is the project's reference architecture. Candidate contributions are the composition of typed UNKNOWN with dependency blocking; one-use human-rooted warrants bound to a DecisionDependencyRoot; and recovery that reserves both cost and risk while requiring independent readback. MCP carries bounded requests and evidence; it cannot create authority. These are research hypotheses, not established first-of-kind claims, mathematical proofs or production guarantees. Compare published alternatives and measure reproducible counterexamples before claiming novelty.

## Problem und Forschungsbeitrag — Deutsch

Ein Agent kann Modellvorschläge erhalten, eine Bestätigung verlieren oder neu starten, während das Ergebnis einer Operation unklar bleibt. Nutzende benötigen nachvollziehbare Nachweise, die Freigabe, Ausführungsversuch und verifiziertes Ergebnis unterscheiden. Das Vorhaben untersucht, ob eine gemeinsame, menschlich kontrollierte Laufzeit diese Unterscheidung über Transport- und Wiederherstellungsgrenzen hinweg dauerhaft erhalten und dabei den benötigten Kontext minimieren kann.

PCAF ist die Referenzarchitektur des Projekts. Untersucht werden die Verbindung typisierter UNKNOWN-Ergebnisse mit abhängigen Zuständen, einmalige menschliche Handlungsfreigaben mit gebundenen Entscheidungsnachweisen sowie Wiederherstellung mit Kosten- und Risikoreservierung und unabhängiger Zustandsprüfung. MCP transportiert begrenzte Anfragen und Nachweise, erteilt aber keine Befugnis. Dies sind Forschungshypothesen; wissenschaftliche Neuheit, Produktionsreife und universelle Sicherheitsgarantien werden nicht behauptet.

## Novelty hypotheses and evaluation

| Candidate contribution | Existing starting point | Research still needed | Evidence required before a novelty claim |
| --- | --- | --- | --- |
| Durable uncertainty blocks dependent completion | Liability ledger and lab taint contracts | Bind mission/ServiceGuard completion and cross-task dependencies | Published comparison matrix; fault traces showing retained UNKNOWN and blocked completion |
| Exact decision survives transport without amplifying authority | Warrant ledger and DDR contracts | Trusted host refreshes relevant evidence, revision, epoch and reservations | Comparison against documented approval/replay approaches; changed-context denial measurements |
| Recovery preserves resources and authority | Intent journal and paired governor | Independent verifier, host fencing, production storage semantics | Reproducible crash/ACK/lease race campaign with explicit assumptions and counterexamples |
| Useful evidence with minimized disclosure | MCP READ admission and privacy gate | Minimal worker status projection and operator comprehension study | Verified schema, disclosure inventory and consented evaluation protocol |

**[OPERATOR/RESEARCHER: add independently retrieved primary literature, framework versions, dates and comparison criteria.]** No external framework was reviewed here. A negative result is acceptable and must be documented.

## Grant evidence map at the exact task SHA

All paths below are relative to repository root. Fresh Q20 test output is stored in `reports/Q20_OFFLINE_TESTS.log`; prior task reports are background evidence, not substitute test receipts.

| Draft statement | Source and deterministic test | Bounded interpretation / open gate |
| --- | --- | --- |
| Typed UNKNOWN persists and denies completion in the ledger | `runtime/mission/liability.py`; `tests/test_core_liability.py` | Owner-scoped fixture storage; full mission completion and cross-task integration open (G2) |
| Warrant consumption is one-use and attenuation cannot escalate scope | `runtime/mission/warrant.py`; `lab/archaioa/warrant.py`; `lab/archaioa/decision_root.py`; `tests/test_core_warrant.py` | Consumption receipt is not proof of effect; no live signer/executor (G3 open) |
| START, reservations and outbox are recorded together; lost ACK requires inspection | `runtime/mission/intent.py`; `tests/test_core_intent.py` | Offline fixture step; no atomic database/target guarantee; host verifier and boundary wiring open (G4) |
| Untrusted inbound reads are revalidated and approval status is denied | `runtime/mcp_bridge/policy.py`; `runtime/mcp_bridge/read_ops.py`; `tests/test_mcp_read_admission.py` | `approval.status` remains **BLOCKED_PRIVACY_PROJECTION** because the verified worker schema exposes the full approval record; remote operation disabled |
| Canonical project declares MIT licensing | `LICENSE`; `pyproject.toml` | Does not clear embedded content, transitive rights or historical secret findings |
| PCAF scope is a research roadmap | `lab/archaioa/README.md`; `docs/architecture/UNIFICATION_2026-10-09.md` | Reference architecture, not certification or live readiness |

Packaging remains an open deliverable: mission primitives import `lab.archaioa`, while current package discovery excludes `lab`. Source-checkout tests do not certify installed-wheel use. Security/rights review remains open: 30 fixture provenance observations, 10 historical binary/rights objects, transitive notices and historical secret findings. Do not attach private HAT data, EagleEYE core, worker approval records or credentials to a dossier.

## Proposed FOSS deliverables and work packages

Estimates below are initial engineering planning ranges in **person-weeks**, not salary, funded duration, availability or a participant commitment. They require operator review against team capacity and verified call rules. Work can remain offline; live infrastructure is outside these estimates and needs a separate exact approval.

| Package | Proposed work and public deliverable after rights review | Acceptance milestone | Estimate / dependency |
| --- | --- | --- | --- |
| WP1 — baseline and comparison | Versioned evidence map, threat model, literature comparison and installed-package gap audit | Every claim has a source/version and fixture/live classification; novelty claims reviewed | 1–2 person-weeks; prerequisite to all packages |
| WP2 — PCAF host integration | Integrate existing liability, warrant/DDR and intent primitives into the single Core; package contracts | Deterministic changed-evidence, crash, lost-ACK and dependency tests pass; unresolved UNKNOWN blocks completion; effects remain gated | 3–5 person-weeks; WP1 and reviewed G2–G4 contracts |
| WP3 — MCP privacy boundary | Minimal READ projection specification, bounded adapter fixtures and redaction tests | Full approval payload cannot cross the boundary; remote status remains disabled until safe schema is verified | 1–2 person-weeks; WP1; safe worker projection is an external dependency |
| WP4 — recovery evaluation | Reproducible offline fault/lease/resource campaign, documented counterexamples and limits | No blind replay; stale epoch denied; UNKNOWN retains resources; logs reproducible from a clean checkout | 2–3 person-weeks; WP2, WP3 safe fixtures |
| WP5 — operator understanding and release dossier | Evidence-console copy, consented evaluation plan, contributor guide and FOSS release candidate | Human reviewers can distinguish advice, approval, attempted effect and UNKNOWN; privacy/rights/packaging review completed | 1–2 person-weeks; WP4; recruitment and publication separately approved |

Sequential planning envelope: **8–14 person-weeks**, excluding recruitment delays, rights review dependencies, official-call preparation and any live/cloud work. No calendar start/end dates assigned. If capacity or call rules differ, reduce scope before promising dates. Each milestone is a review gate; failure blocks its dependent package. Proposed release material stays in the canonical AIOA spArkHAT repository with MIT-compatible licensing subject to rights review; this task publishes nothing.

## Budget worksheet — no financial request made

Currency: **[OPERATOR: confirm from current official call]**. Funding ceiling and eligible expense rules: **[OFFICIAL VERIFICATION REQUIRED]**. No numeric salary, grant amount or spending authorization is asserted.

| Cost item | Quantity/effort basis | Rate and justification | Draft amount | Eligibility |
| --- | --- | --- | --- | --- |
| Applicant development effort | Reviewed WP1–WP5 allocation: [TBD person-days] | [TBD permitted basis; applicant confirms] | [TBD] | [Verify official rule] |
| Collaborator effort, if applicable | [TBD scope and consented allocation] | [TBD permitted basis] | [TBD] | [Verify team/collaborator rules] |
| Accessibility / evaluation support | [TBD consented method and units] | [TBD quote or justified basis] | [TBD] | [Verify official rule] |
| Equipment or other direct costs, if allowed | [TBD demonstrably necessary units] | [TBD quote] | [TBD] | [Verify official rule; omit if ineligible] |
| Requested total | Sum only confirmed eligible items | Reconcile to verified ceiling | [TBD] | Human review required |

Do not include paid model/cloud credits as a presumed prerequisite: the proposed baseline and campaign are offline. Any later paid experiment requires an independently justified budget and exact operator authorization. Avoid double-counting existing completed work as proposed funded work; explain the distinction in the final schedule. Tax treatment, other funding, overhead and applicant financial declarations remain **[OPERATOR: verify]**.

## Applicant, team consent and transfer checklist

- [ ] Applicant identity and preferred contact: [OPERATOR TO COMPLETE PRIVATELY]; do not populate from repository metadata.
- [ ] Current official call URL, retrieval date, form fields, deadline/timezone, permitted language and word limits recorded; adapt bilingual copy to actual limits.
- [ ] Applicant personally confirms eligibility, residence/status and any employment or other-funding constraints under verified rules. No eligibility determination is made here.
- [ ] Each proposed participant explicitly confirms role, availability, effort, attribution and consent. No contributor or employer commitment is inferred.
- [ ] Ownership, FOSS licensing, embedded-content rights, dependency notices and historical secret findings reviewed; private material excluded.
- [ ] Existing completed work separated from proposed work; capacity, calendar milestones, costs and permitted categories justified by real data.
- [ ] Novelty comparison completed with primary sources; claims softened or removed where unsupported.
- [ ] Technical reviewer checks exact source SHA, original logs, assumptions and still-open G2–G4 integration gates.
- [ ] Human language reviewer approves German/English abstracts and application-specific text. Current human review: **PENDING**.
- [ ] Applicant reviews privacy notice, attestations, terms and all legal/financial statements personally. No automated acceptance.
- [ ] Final handoff records reviewer, date and approved dossier revision: [TBD]. Application submission remains a separate human action; **NOT SUBMITTED**.
