# Quick Start for Grant Reviewers

## 1. What AOIA-Core is

AOIA-Core is a local-first deterministic and rule-based runtime prototype for
AI-assisted technical workflows. It focuses on provenance, evidence boundaries,
contradiction tracking, controlled retrieval, and human operator approval for
risky actions.

The deterministic/local-first claim applies to local Linux/RHCSA retrieval and
the epistemic gating layer. External model providers, including optional
xAI/Grok, are non-deterministic and are not claimed as deterministic runtime
results.

## 2. What AOIA-Core is not

AOIA-Core is not:

- AGI
- an autonomous production agent
- a truth engine
- a scientific validation system
- an LSC or neutrino validation project
- a production GUI, mobile, or frontend product

## 3. What to inspect first

Start with:

- `docs/governance/IMPLEMENTED_CAPABILITIES.md`
- `docs/reviewer/PROJECT_OVERVIEW_FOR_REVIEWERS.md`
- `docs/reviewer/ONE_CONCRETE_EXAMPLE.md`
- `docs/nms/GLOSSARY.md`
- `docs/nms/ROADMAP_4_MONTHS.md`

Then inspect representative runtime files:

- `runtime/tools/provenance.py`
- `runtime/retrieval/facade.py`
- `runtime/evidence_review/engine.py`
- `runtime/webapp.py`

## 4. How to run validation

From the repository root:

```bash
python3 -m compileall runtime tests
PYTHONPATH=runtime:. python3 -m unittest discover -s tests -p "test*.py" -v
```

## 5. Expected validation result

`compileall` is syntax validation only. It does not prove runtime correctness,
security, scientific validity, or production readiness.

The known current savepoint result is:

- `163` tests run
- `4` optional UI/Textual tests skipped
- `OK`

## 6. Capability evidence map

Use `docs/governance/IMPLEMENTED_CAPABILITIES.md` as the conservative capability
map. It separates implemented, partial, planned, and documentation-only claims.
Do not infer production readiness from documentation presence alone.

## 7. Scope warnings

LSC appears only as a historical research origin and high-claim-density neutrino
archive stress-test corpus. It is not validated physics, not AOIA-Core
scientific output, and not runtime authority.

SCEMDA, HNC, Gary-related, and other external collaborator material remain
external and non-canonical unless explicitly promoted through governed
human-approved processes.

Provenance verifies local lineage and chain integrity only. It does not validate
truth, external source authenticity, scientific claims, or model output.

The evidence boundary is a controlled write path and audit-support mechanism,
not a complete immutable content-addressed evidence store.

Runtime safety contracts are strong design and governance contracts with partial
runtime enforcement today. Full enforcement remains roadmap work.

`AOIAEpistemicKernel` is the canonical epistemic gate. `KnowledgeRouter` is a
legacy/compatibility transition surface, not a second canonical authority.

The loopback-only web console is an implemented operator surface over the same
runtime. The TUI is optional. Neither changes authority semantics. Generated
state artifacts are runtime data, not canonical source authority.

The dated-evidence module is deterministic and provider-independent, but it is
bounded to one curated scenario. Its findings and hashes are metadata only and
always require human review; they are not legal advice or proof of truth.

## 8. Recommended reading order

1. `docs/reviewer/QUICK_START_FOR_GRANT_REVIEWERS.md`
2. `docs/nms/GLOSSARY.md`
3. `docs/reviewer/PROJECT_OVERVIEW_FOR_REVIEWERS.md`
4. `docs/governance/IMPLEMENTED_CAPABILITIES.md`
5. `docs/reviewer/ONE_CONCRETE_EXAMPLE.md`
6. `docs/modules/DATED_EVIDENCE_REVIEW.md`
7. `docs/nms/ROADMAP_4_MONTHS.md`
