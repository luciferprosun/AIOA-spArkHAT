# AIOA spArkHAT × NonZero: retirement-readiness audit

## Bieżący stan bramki

Wynik `RETIREMENT_HOLD` przy kodzie `d2fc4cb88c1777e572c099c8082b93e6b7a6c0b1`. Dwie kopie odtworzono w różnych środowiskach: na laptopie i w odizolowanym workspace Cloud. Każde odtworzenie objęło 13 zgodnych refów, 179 commitów i 2674 osiągalne obiekty, fsck exit 0. Długoterminowa retencja Cloud i druga niezależna kopia pod trwałą kontrolą właściciela pozostają niepotwierdzone. Wszystkie 1312 osiągalnych blobów sprawdzono pod kątem wskaźników Git LFS v1. Wynik zero. Publiczny odczyt GitHuba pokazuje 1 PR, 0 issues, 0 releases i 0 przebiegów Actions. Uwierzytelniony odczyt .wiki.git zwrócił repository not found mimo włączonej flagi wiki. Zawartość wiki i Projects pozostaje niepotwierdzona. Ostatni z 20 zapisów Render to udane wdrożenie 6378024487 z 10 września 2026 r. Aktualny stan Render i jego odbiorcy pozostają UNKNOWN.

Poniższy spis traktujemy jako historyczny, przypięty do jego oryginalnych SHA. Archiwum dokumentacji nie przechowuje obiektów Git ani danych usług GitHub. Pełne odtworzenie wymaga dwóch niezależnych i zweryfikowanych kopii oraz spisu danych poza Git. [Aktualna bramka](../cloud-consolidation/NONZERO_RETIREMENT_GATE.md)

Status: **HOLD — do not archive or delete the legacy repository yet.**

## Observations at pinned GitHub checkpoint (2026-11-24)
- Canonical active repository: `luciferprosun/AIOA-spArkHAT`, protected `main` at `9d8b61c6dce9cccbf32ce8dfc2dc87682567dd9c` (PR #64 merged).
- Legacy repository: `luciferprosun/AIOA-NonZero-CloudOps-Agent`, repository ID `1342916553`, `main` `4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a`.
- Legacy `main` Git tree has 412 blobs, including 99 docs paths, 143 src, 94 tests, 45 scripts, 17 requirements and 5 infra entries. This is a **single branch snapshot**, not the full history.
- PR #65 READY / unmerged and PR #66 DRAFT / unmerged at the audit checkpoint; verify again before making decisions.
- AIOA One-Core and source-provenance/packaging gates passed in earlier qualified scopes; current `main` is not certified for FULL_PARITY.
- Authoritative parity distribution remains **38 scoped or archived/accepted, 7 PARTIAL, 1 BLOCKED, 23 UNKNOWN_EXTERNAL** (69 source rows). `ARCHIVE_ONLY` means out-of-scope runtime with retained provenance, not full feature equivalence.
- Four required LIVE lanes A/B/C/D remain `NOT_RUN` without valid approvals.
- Native #69 historical action remains `UNKNOWN / HELD`, with replay prohibited. A newer offline test cannot reconstruct missing historical attribution.
- 23 external contracts retain `UNKNOWN_EXTERNAL`; current consumers and historical Render deployment activity are not independently established.
- A prior Cloud report marked second backup `BLOCKED_BACKUP`. A separate **operator-supplied** LOCAL-L2 screenshot reported two verified physical-media copies and 13 refs; this archive has not ingested authenticated private manifests, so do not promote Cloud verification automatically.
- Earlier retirement gate records historical Render deployments (latest reported 2026-09-10) and unresolved live consumers, GitHub repo metadata, service bindings and owner permissions.

## Required gates for safe retirement
| Gate | Present finding | Required next evidence |
| --- | --- | --- |
| PR stack | #65, #66 outstanding at checkpoint | Normal protected merges, checks/CodeQL, exact-main regression |
| Runtime independence | Scoped One-Core PASS | Final SHA import/build/deployment/reference audit across supported products |
| 7 PARTIAL features | OPEN | Acceptance per row: #2, #3, #17, #18, #19, #41, #63 |
| Native historical #69 | UNKNOWN / HELD | Retain immutable evidence/reservations and an independently accepted custody/retention decision; never replay |
| LIVE A–D | NOT_RUN | Qualified test or explicit approved scope reduction with proof |
| External contracts (23) | UNKNOWN | Confirm consumers or document separately approved retirement/adapters by ID |
| Render service | UNKNOWN | Owner confirms current service, repo/ref, webhooks, domain, actual traffic and rollback |
| Git backups | Cloud previous 1 PASS / second unknown; operator reports 2 | Import signed/hashed manifests proving 13 refs, two physical copies, restore and fsck |
| Non-Git GitHub data | Not fully exported | Inventory/export PR discussion, issues, wiki/projects, deployments/statuses, releases, assets and actions evidence as applicable |
| Historic software licence/provenance | Original MIT and prior-art recorded | Preserve notices, source OIDs and competition provenance in final deliverable |
| Final owner decision | NOT_GRANTED | Explicit, separate, targeted approval for **archive** or **permanent deletion**, never inferred from this PR |

## Decision
1. **Now safe:** add reference-only documentation archive on an isolated branch, without modifying existing active code.
2. **After #65/#66:** update evidence and dependencies and repeat the final clean-clone install from AIOA alone.
3. **Before any retirement:** satisfy and independently review all gates above; a decision to preserve historical UNKNOWN is not permission to replay it.
4. **Prefer archive over deletion** as an initial step when all gates pass. Permanent deletion is irreversible for GitHub identity, URLs, settings and metadata that Git bundles do not capture.

This PR is **not an approval to retire legacy**, not an import of production code, and not a replacement for a complete verified source archive.