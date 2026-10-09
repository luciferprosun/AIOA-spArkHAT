# CockroachDB Memory Patch - migration and source retention

AIOA contains the *native selected* Memory Patch implementation under `runtime/memory_patch/`, including optional CockroachDB adapter. The original competition code remains a distinct historical source until proper retirement checks pass.

Original GitHub repo: https://github.com/luciferprosun/Memory-Patch-for-AIOA-Hackathon-CockroachDB

Original main SHA: `1098c35024ac78d6ad7b4bd70c6138028c26c5e9`.

The source map at [memory_patch_source_map.json](../../../provenance/memory_patch_source_map.json) classifies all **847** original tracked files: 231 mapped to native contracts and 616 intentionally excluded. Source-level parity is **not** asserted, since exclusions cover original fixture, forensic, jury infrastructure and archive-only material.

A verified full-ref Git bundle on the operator's USB drive is a recovery copy, not evidence that every original tracked file has been published into the AIOA repository.

**DO NOT DELETE** the original repo until all acceptance conditions are met:
1. Full tracked-source archive available in the private `projects-for-future` repository, pinned to the exact old HEAD and independent blob-parity verified.
2. Full Git mirror and verified bundle; restore into a fresh checkout succeeds.
3. Independent review of public links, provenance, licenses and judging deadlines.
4. Named maintainer acknowledges irreversible deletion.
5. Post-change public README and registry references are updated.

Prefer GitHub archive/read-only state over deletion when in doubt. The AIOA native integration and the standalone frozen competition are separate historical entities.
