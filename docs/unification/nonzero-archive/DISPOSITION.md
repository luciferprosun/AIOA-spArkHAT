# Historical material disposition — no runtime duplication

| Category | Decision | Rationale / next action |
| --- | --- | --- |
| `src/` (143 files at pinned legacy main) | **DO NOT COPY** | Implement/accept current behavior through AIOA Core and parity ledger, not a duplicate executable package |
| `tests/` (94) | **DO NOT BULK COPY** | Active behavior tests belong in AIOA test suite; historical cases remain accessible through signed Git bundles |
| `scripts/` (45), `requirements/` (17), `infra/` (5), Dockerfile, pyproject | **DO NOT ACTIVATE** | These may contain old deployment semantics, AWS assumptions or obsolete dependencies |
| `docs/` (99), README, PRIOR-ART | **PRESERVE EVIDENCE** | Exact source snapshot inventory records all paths/OIDs; only selected non-executable documents are copied verbatim here |
| Licence and prior-art records | **COPY SELECTED** | Preserve original MIT attribution and clean-room competition boundary |
| Old receipts, manifests and reports | **INDEX; REVIEW BEFORE IMPORT** | They may contain mock-only scope, historic blockers, private environment data or dated claims; inventory is not a content backup |
| `docs/assets/` images | **INDEX; NO RE-ENCODE** | Need original binary bytes/rights and archival integrity proof before deletion |
| Git history and 13 refs | **SEPARATE BUNDLE COPIES** | A file tree snapshot is not a history or repository backup; never represent it as one |
| Render/Devpost/hackathon GitHub metadata | **INDEPENDENT EXPORT** | Repository links alone cannot preserve external records after deletion |

## Important scope distinctions
- The legacy `docs/PROJECT_CHARTER.md` describes an earlier AWS Agents for Humans bounded EC2 project, single Strands Agent and mock-first runtime. It **must not** be treated as the current AIOA product charter.
- The legacy `PRIOR-ART.md` and `docs/submission/PRIOR_ART_DISCLOSURE.md` document independent origins and clean-room assertions during the historic hackathon. Preserve them without rewriting history.
- The `ARCHIVE_ONLY` category in the current 69-row parity ledger records migration scope, **not** preservation of arbitrary GitHub metadata or absence of external consumers.
- No file move or deletion has been performed in either repository.

## Active source of truth
- `docs/unification/cloud-consolidation/PARITY69_UPDATED.csv`
- `docs/unification/cloud-consolidation/EXTERNAL_CONTRACT_DECISIONS.md`
- `docs/unification/cloud-consolidation/LIVE_QUALIFICATION.json`
- `docs/unification/cloud-consolidation/NATIVE69_FINAL_ACCEPTANCE.md`
- `docs/unification/cloud-consolidation/NONZERO_RETIREMENT_GATE.md`

**Further audit required:** Compare the preserved 13-ref bundle (including W7A and judge freeze) against the 412-file `main` inventory, establish missing historical files/branches and approved retention of external metadata.