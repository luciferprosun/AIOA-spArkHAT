# Generative-AI Transparency

**Effective project checkpoint:** 2026-09-22

## Purpose

AIOA spArkHAT uses generative-AI tools during engineering. This document makes that use explicit for reviewers, users, and contributors.

The project follows a simple rule:

**AI may assist with engineering; the human maintainer remains responsible for architecture, correctness, licensing, review, and publication.**

## Tools and roles

### ChatGPT

Used for:

- architecture review;
- repository inspection;
- test planning;
- failure analysis;
- documentation;
- reviewer preparation;
- bounded terminal operations on an explicitly authorised Linux machine;
- small/medium code changes with tests.

### Codex CLI

Current local configuration at this checkpoint:

- Codex CLI: 0.155.1
- configured model: `gpt-5.6-luna`
- configured reasoning effort: `medium`

Used for:

- larger repository implementation batches;
- refactoring;
- regression-driven repair;
- code/test integration.

Configuration can change over time. Future logs should record the model actually configured for the relevant session instead of assuming this snapshot remains current.

### Other model providers

OpenRouter, NVIDIA/Nemotron and other model providers may be used only where explicitly configured.

Their outputs are advisory/data inputs. They do not obtain execution authority merely by producing a response.

## Human responsibility

The human maintainer:

- chooses project goals and architecture;
- decides what is in scope;
- approves consequential actions;
- reviews accepted diffs;
- validates claims against tests/evidence;
- determines publication/submission;
- remains accountable for licensing and originality.

Pure model output is never considered sufficient proof that a feature is correct.

## Repository acceptance rule

A substantive AI-assisted change should be accepted only when:

1. the intended behavior is understood by the human maintainer;
2. the diff is reviewable;
3. relevant tests pass;
4. authority/security invariants are preserved;
5. provenance/limitations are recorded where material.

## Provenance policy from this checkpoint forward

For substantive AI-assisted code or architecture changes, prefer one or both of:

### Commit metadata

Include a short trailer or body note such as:

```text
AI-Assisted: yes
Tool: Codex CLI
Model: gpt-5.6-luna
Human-Reviewed: yes
Prompt-Summary: harden reviewer evidence parser against scalar type confusion
Validation: 21 focused / 141 adversarial / 401 broader PASS
```

Do not place secrets, credentials, private prompts, or account identifiers in commit messages.

### Project log

Where a commit needs more context, append a bounded summary to:

`docs/provenance/GENAI_LOG.md`

The log should contain:

- date/time;
- tool/model when known;
- task/prompt summary;
- files materially affected;
- human review/decision;
- validation evidence;
- output/result summary.

Full raw private conversations are not automatically published. If NLnet requires a specific prompt-log format for a milestone, provide the requested material through the appropriate review channel after redaction of secrets/personal data.

## Historical limitation

Older commits predate this repository-level disclosure convention and do not uniformly record every model/prompt interaction.

The project will not fabricate retroactive per-commit provenance.

Existing evidence remains available through:

- Git history;
- tests;
- reports;
- source import maps;
- provenance maps;
- reviewer documents;
- preserved project conversations where separately available.

## Safety relationship

GenAI use does not bypass the AIOA authority model.

In the current competition architecture:

- providers are advisory;
- CPL critics are advisory;
- memory is advisory/contextual;
- DVM/pheromone is SHADOW;
- explicit human approval remains the consequential boundary;
- Service Guard is the bounded competition effect executor;
- replay/idempotency checks remain independent of model opinion.

## NLnet policy reference

Current public NLnet GenAI policy:

https://nlnet.nl/foundation/policies/generativeAI/

This project disclosure is intended to make substantive use visible without overstating historical logging precision.
