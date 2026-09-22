# Repository Cleanup Audit — NLnet + NVIDIA

Date: 2026-09-22

## Decision

**No historical or grant-facing material should be deleted while NLnet and NVIDIA review are active.**

The correct cleanup strategy is navigation + classification now, destructive cleanup only after both reviews finish.

## Inventory

- tracked files: **1028**
- tracked bytes: **36,422,214**
- archive files: **337** (16,346,859 bytes)
- forensic-export files: **323** (16,301,656 bytes)
- files marked for post-review reconsideration: **345**

Full per-file classification: docs/reviewer/REPOSITORY_FILE_CLASSIFICATION_20260922.csv.

## Classification counts

| Classification | Files |
|---|---:|
| HISTORICAL_FORENSIC_EXPORT | 323 |
| CURRENT_RUNTIME | 321 |
| CURRENT_TESTS | 111 |
| CURRENT_OR_REFERENCE_DOC | 88 |
| HISTORICAL_AUDIT | 50 |
| RESEARCH_CONTEXT | 33 |
| NVIDIA_CURRENT_EVIDENCE | 15 |
| HISTORICAL_ARCHIVE | 14 |
| HISTORICAL_MIGRATION_REPORT | 14 |
| CURRENT_UI | 14 |
| CORE_REFERENCE | 13 |
| GRANT_NLNET_CONTEXT | 11 |
| HISTORICAL_RUNTIME_REPORT | 7 |
| ROOT_PROJECT_METADATA | 4 |
| CURRENT_SCRIPTS | 4 |
| REVIEWER_NLNET_CURRENT | 2 |
| PUBLIC_SAFE_DEFAULT_STATE | 2 |
| CI_CONFIG | 1 |
| INTERNAL_WORKFLOW_DRAFT | 1 |

## What should stay visible now

- root README / license / packaging metadata;
- current runtime, tests, scripts and reviewer UI;
- NLnet/grant reviewer documentation;
- NVIDIA reviewer documentation and accepted evidence;
- provenance/source maps;
- historical audit/migration reports where they explain architectural decisions.

## Post-review cleanup candidates — do not delete now

1. archive/forensic_exports/ — largest duplicate historical export. After reviews, consider moving it to a versioned release archive or external public archive while preserving SHA-256 and Git/tag references.
2. older phase/migration/audit snapshots — consolidate into an index after NLnet/NVIDIA review; preserve Git history and hashes.
3. docs/OPENAI_WORKFLOW_FEEDBACK_DRAFT.md — operational feedback draft, not product documentation; move to a project-operations archive after review if no longer needed.
4. generated/forensic tree inventories — keep until review completes, then retain only canonical inventory + hashes if redundancy is proven.

## Stale-document handling

Old documents must not silently become current instructions. Add a historical-snapshot notice and link to the current reviewer guide instead of rewriting old results.

## Reviewer safety

This audit does not authorize deletion, history rewriting, force-push, visibility changes, or modification of frozen upstream hackathon repositories.
