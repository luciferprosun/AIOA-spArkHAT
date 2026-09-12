# Reviewer evidence

The AU-3 manifest maps conservative project claims to the source, tests, gates, and immutable Git snapshot that support them. It is a reviewer index only; runtime policy, typed contracts, durable approval, and the private executor remain the authority boundaries.

## Rebuild and validate

From the repository root in the documented development environment:

```bash
.venv/bin/python scripts/build_reviewer_evidence_manifest.py
.venv/bin/python scripts/build_reviewer_evidence_manifest.py --check
.venv/bin/python scripts/validate_reviewer_evidence_manifest.py
```

The immutable Phase 1 / Day 14 baseline remains anchored to `fbb536400594306f2bb3abd31c7064a66735c82d`. Unchanged Day 15 M1 claims remain at their original reviewed commit `17d5f4637dbd69a33eff1cbb46282c36b19ce6ad`; recovered telemetry and runtime-guard claims use `f2ee79c09ba174ba72cb527b70c095f412151758`. Credential-free Local-First authority begins with the reviewed Phase 1 foundation `b5dba16a9af1bc979b2b96a50ddbf0e590e829a5` and Phase 2 implementation `7ffe0cf7c9ca4a5c7c311fd5394a245e80bb78e0`. The provider-neutral primary-agent topology, tool surface, and cold-resume factory authority are anchored to portable B1 commit `a2e16d0f1d625b34916440d6740a486f73cf2bb1`. The historical B3 judge surface is `1882089fbb41a3f7f3cbad821ed9d6d8c6c2e9a5`; four approval, execution, proposal, and model-authority claims changed by reliability/security hardening remain anchored to portable B4 commit `a455379eb3de73bf6c1780b3c4726b0778873dd4`. The container-aware judge-surface boundary is anchored to portable B5 container commit `d18f945a1484a1255339a3b4bcb1560c58d06d9b`. The three authority sources changed during Phase 3 are explicitly re-anchored: current Day 15 gate plus SAM release safety at `c16f6829e8b258af86523b0b1d61e34586702b63`, and the RC package/SDK pin at `5ac15d30a604434713490d77edb573d14a8f1dcd`. The preserved Day 15 recovery lineage, in order, is `aa941a989a8b8cd0e40367bb130472e9f3c082a7`, then `17d5f4637dbd69a33eff1cbb46282c36b19ce6ad`, `8e4583ac9341cb7b66de47cf0e7b2a442ac67b32`, `30c2a30cda0ac6d6e2003166daf6c29bf2c764f0`, `f2ee79c09ba174ba72cb527b70c095f412151758`, `36fd17df981dfa593d4e63f6a143410317410763`, `ce35a67f6491ea92aeef534d0dc4f5dc4a8da7ff`, `5a6127f43a9251a72203c0eb6c7a903d817599f7`, `3464bc869e7a11acb5aab61ae279cf196a1ebd0f`, `41ba5586180e9aa3a25fc5469d42815073a0bbf8`, `858770d5e5c7b59fa883cc56e06f4a9e915d70c1`, `5e1904408d402c1e6492d6b2e153a7f1a5c56b58`, `99f70c43a26ce9715e9b57fde81ca265382dd5f2`, and `197db56f828b8ab0b9139a1d3708fb8a58ca336a`. The candidate snapshot is deliberately `LOCAL_IMPLEMENTATION_CANDIDATE`; it records no live AWS observation, change set, or deployment. The builder never derives an anchor from changing `HEAD`; every claim anchor names a prior immutable implementation commit, avoiding a self-referential commit hash.

## Canonical model

Each claim contains the required `claim_id`, `claim`, `evidence_kind`, `authority_source`, `proof_nodes`, `commit_anchor`, `status`, `scope`, `limitations`, and `hash` fields. Python authority references use `path::symbol`; exact non-Python anchors use `path#text`; a path alone proves a tracked regular file. Pytest proof nodes use their exact `path::test_name`; P0/P1 and D15 nodes use exact gate IDs.

Claim hashes are SHA-256 over compact, key-sorted UTF-8 JSON with the derived `hash` removed and set-like source/proof lists sorted. `manifest_hash` covers the normalized complete document except itself. Canonical JSON uses sorted keys, two-space indentation, sorted claims, and one final newline. The Markdown view is generated from the same normalized model.

The validator resolves authority files and Python symbols at each claim's exact reviewed commit, resolves exact pytest nodes, and requires every referenced current source/test blob to remain byte-identical to that anchor. It admits only the frozen baseline, original M1, recovered M1, historical M2, current G10, Local-First Phase 1, and Local-First Phase 2 claim anchors; verifies their required ancestry plus the preserved Day 15 single-parent recovery chain; and extracts the Day 15 gate IDs independently from the immutable G10 Git object. It also checks the explicitly qualified frozen Phase 1 tag and requires every prior-art path to remain a tracked regular file with its immutable blob. Runtime one-agent/five-tool facts must match roots extracted directly from the immutable baseline object, so a synchronized five-for-five tool substitution or emptied provenance baseline cannot be regenerated into truth. Nova 2, its runtime region, and exact `strands-agents[otel]==1.53.0` pins are validated independently against frozen expectations.

## Live-proof boundary

Source, static checks, and mocked tests do not prove a live AWS event. The manifest therefore records the live EC2 claim as `NOT_YET_PROVEN` and contains no live receipt. A future positive live claim must use `LIVE_RECEIPT`, reference a separately reviewed and tracked sanitized receipt under `docs/evidence/live-receipts/`, and match its SHA-256.

A receipt has a closed schema: claim binding, exact `ec2:StopInstances` operation and region, distinct nonzero hashed target/request/verification identifiers, stopped observation, `SUCCESS_WITH_EVIDENCE`, explicit UTC event time, operator-attested sanitized-export provenance, the fixed affirmative attestation contract, and `sanitized: true`. The event time must fall deterministically between the L1 snapshot commit and the Git commit that introduced the receipt. Unknown or duplicate fields, noncanonical JSON, contradictory/synthetic attestation, raw provider responses, weak evidence hashes, and privacy material fail validation. Promotion also requires an intentional reviewed builder change; inserting a receipt only into generated JSON fails generator-drift validation.

The validator treats any unreviewed live-mutation statement as receipt-requiring, so relabeling it as a local test cannot bypass the proof boundary. It also rejects local paths, account identifiers, credentials, secret-like material, raw prompts, and private machine metadata.
