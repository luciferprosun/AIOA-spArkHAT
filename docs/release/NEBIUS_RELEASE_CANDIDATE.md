# Nebius release candidate — canonical local manifest

Preparation basis: e7a0a747e2e9fea8f75416ec6d6d3a35a5152ae0
Branch: integration/nebius-unified-prototype-20261008
Main: d26266e54ee940d7ada30aa02783dc697618a72c
Rollback: dceafec638b36417cb99c56f810d84e3555a7c61

Exact post-commit candidate binding is intentionally external to avoid a self-referential Git SHA.

## Current result
- CG0-CG4: PASS_LOCAL
- Main integration mechanics: candidate YES / ready NO
- Final native: 1549 PASS + 4 approved optional skips; 0 fail/error/timeout
- Fresh review: C0 / I0 / M0
- Provider: no current live validation
- Effect target: fixture only

## Blocks
- 01 Provider Foundation + Provenance Port: PASS_IMPLEMENTED
- 02 Typed Outcome + Liability Core: PARTIAL_BY_DESIGN
- 03 Linear Effect Warrant + DecisionDependencyRoot: PARTIAL_BY_DESIGN
- 04 Intent Journal / Outbox / Epoch Fencing: PARTIAL_BY_DESIGN
- 05 Causal Receipt Graph + Bi-temporal Evidence: PASS_IMPLEMENTED
- 06 Context Capsules / HAT Minimization: PASS_IMPLEMENTED
- 07 Dual Cost/Risk Governor / Hysteresis: PASS_LOCAL_FIXTURE
- 08 Commit-Select-Reveal / covariance verification: PASS_LOCAL_SEALED
- 09 Shadow Delta fixture: PASS_LOCAL_SEALED
- 10 Nebius Cloud Worker S1: BLOCKED_EXTERNAL
- 11 Multi-worker S2 fencing: BLOCKED_EXTERNAL
- 12 Formal/Fault/Endurance: PASS_LOCAL
- 13 Operator Evidence Console: PASS_LOCAL
- 14 Final demo / Devpost / release hardening: PARTIAL_BY_DESIGN

## What this candidate does not claim
- production certification
- distributed exactly-once
- production signer custody
- current public judge uptime
- completed current live provider proof
- completed Devpost submission
- blanket legal/IP clearance

## External gates
- one separately authorized live Nebius/NVIDIA validation
- public Judge Mode hosting and availability
- human security/IP/legal review
- rights-reviewed video publication
- Devpost attestations and real Submitted receipt
- separate exact-SHA main integration authorization
