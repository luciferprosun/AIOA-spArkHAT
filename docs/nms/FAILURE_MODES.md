# AOIA/NMS Failure-Mode Registry

## Purpose

This document lists reviewer-facing failure modes for AOIA/NMS stress testing. It summarizes the existing `docs/stress_tests/FAILURE_MODES.md` material and adds grant-facing boundaries for model evaluation, LSC case-study use, and evidence discipline.

## Failure-Mode Taxonomy

AOIA/NMS should be reviewed against failures in these areas:

- model hallucination and overvalidation
- model consensus without evidence
- evidence and reasoning mixing
- provenance drift
- contradiction blindness
- documentation density mistaken for validation
- operator workflow risks

## Model Hallucination / Overvalidation

Failure pattern:

- a model states an unsupported claim as fact
- a model upgrades a hypothesis into a conclusion
- a model presents LSC material as validated physics
- a model treats fluent explanation as external validation

Mitigation:

- classify claims before reuse
- require source references for evidence-like statements
- preserve uncertainty language
- mark model-generated claims as model-generated only unless separately validated

## Model Consensus Without Evidence

Failure pattern:

- multiple models repeat a claim
- reviewer treats agreement as confirmation
- consensus is used to bypass provenance review

Mitigation:

- record consensus as model behavior, not evidence
- require independent evidence for promotion
- identify shared prompt bias and shared training-data risk
- keep unresolved consensus claims in review state

## Evidence/Reasoning Mixing

Failure pattern:

- model reasoning is stored or described as evidence
- reviewer notes become canonical without approval
- stress-test output is treated as runtime authority

Mitigation:

- label evidence, reasoning, reviewer notes, and model output separately
- preserve source classes in summaries
- route any evidence promotion through explicit governance
- keep this documentation layer separate from runtime state

## Provenance Drift

Failure pattern:

- source lineage becomes unclear
- claims are copied without origin
- archive excerpts, model commentary, and reviewer summaries collapse into one text layer

Mitigation:

- require source labels
- maintain links back to existing stress-test documents
- include provenance gaps in expected outputs
- avoid rewriting uncertain claims as settled facts

## Contradiction Blindness

Failure pattern:

- contradictory claims are ignored
- a cleaner narrative replaces unresolved disagreement
- disagreement between models is treated as noise instead of audit signal

Mitigation:

- preserve contradictions in review notes
- classify unresolved claims explicitly
- require reviewer escalation for conflict resolution
- do not claim automatic contradiction resolution

## Documentation Density Mistaken for Validation

Failure pattern:

- a large documentation package is interpreted as proof
- extensive reports imply scientific validation
- roadmap language overstates implementation state

Mitigation:

- state implementation, partial, planned, and documentation-only status clearly
- separate protocol from execution results
- use conservative funding language
- avoid claims such as "first ever" or exclusive capability claims

## Operator Workflow Risks

Failure pattern:

- operator accepts model framing without source review
- review shortcuts bypass evidence classification
- funding or deadline pressure weakens uncertainty boundaries

Mitigation:

- require checklist-style review
- keep non-goals visible in each grant-facing document
- record open questions rather than forcing closure
- use validation gates before public summaries

## Mitigations

Core mitigations across all failure modes:

- evidence/reasoning separation
- provenance tracking
- contradiction exposure
- conservative claim classification
- human reviewer escalation
- documentation-only scope for this step
- no runtime, provider, memory, provenance, or registry changes in this documentation-only step
