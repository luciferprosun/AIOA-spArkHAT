# Local context capsule — block 06

The existing reviewer command is unchanged:

```bash
python3 -I -B scripts/nvidia_reviewer_preflight.py
```

`NativeRetrieval.context_capsule(READ principal, request, admitted_lanes, selected_refs=...)` projects an immutable metadata snapshot. It reuses `HybridRetrievalRequest.request_hash`, `FrozenEvidenceBundle.bundle_hash`, Core owner/HAT READ checks, current native source binding, temporal selection and native personal retrieval. It owns no store, retrieval engine, evidence admission or authority core. Nothing imports it into an effect path or the external MCP worker.

The capsule binds the exact request and bundle hashes, hashed owner scope and HAT, and selected reference/source-binding digests. Construction and export share a closed schema: digest-only bindings, two fixed lanes, matching canonical flags, unique bounded references, fixed labels and a bounded integer budget. Rehashed extra payload or changed authority labels cannot pass export. It contains no content text, query text, owner identifiers, raw approval/signer/warrant material, commands or hidden reasoning. Canonical source context and owner-private context remain separate lanes. A personal reference is never canonical evidence. Authority is fixed to `NONE`; purpose is `ADVISORY_CONTEXT_ONLY`. Digests are references, never permissions.

Least-context behavior is explicit: the caller may choose a strict subset of already-admitted references. The default contains only the original applicable canonical items and admitted personal entries. Sorting is stable; duplicate/unknown references fail closed. The complete serialized capsule, including framing and digest, must fit `context_budget_bytes`; overflow fails closed without truncation, fallback or context expansion. The selection also respects the native request limit. New source availability never adds context to an existing capsule.

Admission must still be valid at projection: native request construction bounds and derived identity, cached request/bundle hashes, every native contribution's integrity and `upstream_request_hash`, source lineage, owner/HAT binding, original CURRENT temporal selection and current freshness are checked using native primitives. Relabeling an outer bundle for a changed request cannot bypass its existing contribution lineage. Personal entries must match current owner-scoped native retrieval, retaining their revision, content and non-authorizing flags. Revoked/changed personal records, stale/withdrawn sources, tampered metadata and changed requests are denied. Construction or a matching digest alone never proves admission.

This bounded implementation supports native `CURRENT` selections and the native personal memory port. AS_OF/FUTURE capsule projection is not claimed. Payload remains in the existing retrieval/personal lane; this metadata view does not fetch additional context or replace the existing LITE prompt path. Learning deltas, DVM/pheromone and their policies are unchanged.

The existing demo exposes `context_capsule` from episode 1 and validates it again after closing and reconstructing the native runtime with the same admitted inputs. This local restart/replay check retains the admitted values in the test process; it does not claim separate-process recovery or an atomic snapshot across concurrent native mutations. The later stale-source episode is retained separately; the capsule is explicitly an episode-1 admission snapshot, not a claim that its source is still current after that later revision. The demo uses explicit canonical-only intake because its learning fixture has no native personal-memory slot. Separate native lifecycle tests exercise owner preference, revocation, tampering, read-only state preservation and restart.

All demo inputs are `TEST_FIXTURE`; MCP stays external with its unchanged 400-byte / 12-line planner artifact boundary. Production signer custody remains OPEN. Block 07, main integration, SmartRouter, provider/cloud calls and live effects are not started.
