# AOIA/NMS Four-Month Roadmap

## Month 1: Documentation, Governance, and Reviewer Entry Points

Focus:

- establish `docs/nms/` as a grant-facing documentation layer
- align AOIA/NMS, MHLM/MDLH, and LSC boundaries
- cross-reference existing stress-test documents
- prepare review-facing status material
- keep validation commands reproducible

Expected outputs:

- NMS README
- stress-test protocol summary
- failure-mode registry
- LSC case-study protocol
- model audit matrix

## Month 2: Stress-Test Harness and Reproducible Audit Protocol

Focus:

- design a reproducible stress-test harness
- define input capture and output classification formats
- document replay requirements
- keep model outputs separate from evidence
- plan local/private audit workflows

Expected outputs:

- harness design notes
- sample audit input format
- sample claim classification format
- provenance-gap reporting format

## Month 3: Model Comparison Workflow and Contradiction/Provenance Reporting

Focus:

- compare model behavior under the same bounded prompts
- classify hallucination, overvalidation, uncertainty, and contradiction behavior
- document provenance drift cases
- produce reviewer-facing summaries

Expected outputs:

- model comparison workflow
- contradiction report template
- provenance report template
- reviewer checklist

## Month 4: Public Demo Package, Documentation Cleanup, and Sustainability

Focus:

- prepare a public open-source demo package
- clean up documentation entry points
- separate public materials from local runtime artifacts
- document sustainability and maintenance needs
- prepare final grant-facing summary

Expected outputs:

- public demo documentation
- updated reviewer entry points
- reproducibility notes
- sustainability summary

## Deliverables

- grant-facing AOIA/NMS documentation
- stress-test protocol and failure-mode registry
- LSC epistemic-audit case-study protocol
- model audit matrix
- roadmap and review summary
- later harness design material, if approved

## Out of Scope

- iOS work
- Android/PWA implementation in this step
- frontend or GUI build work
- ML training
- production deployment
- autonomous agents
- claims that LSC is validated physics
- claims that AOIA/NMS proves LSC
- merging SCEMDA, HNC, or Gary into canonical LSC neutrino evidence
- runtime architecture, provider, provenance, Evidence Memory, or Contradiction Registry changes

## Validation Gates

Current gate:

- `python3 -m compileall runtime tests`
- `PYTHONPATH=runtime:. python3 -m unittest discover -s tests -p "test*.py" -v`

Future gates may include:

- documentation link review
- claim-boundary checklist
- stress-test artifact schema review
- reproducibility dry run
- public package review

## Relationship to Existing Roadmap

This roadmap is grant-facing and should be read alongside `docs/ROADMAP_4_MONTHS.md`. It narrows the next four months toward AOIA/NMS documentation, reproducibility, stress-test planning, and public open-source demo preparation.
