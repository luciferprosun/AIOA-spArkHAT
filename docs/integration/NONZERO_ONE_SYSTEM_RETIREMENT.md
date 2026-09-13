# AIOA spArkHAT — NonZero one-system retirement

Phase 4 is local only, on `integration/nonzero-cloudops-one-system-v1`, descended
from Phase 3 `6563f93e2b895d494063161b438d05209e2655ca`. The active tree and
installed package now contain only the native capability, not the embedded
second project. No push, PR, main merge, release or deployment is authorized.

## What was retired, and what survives

The exact 412-file imported reference at `runtime/nonzero_cloudops/baseline`
was removed from this local child branch in an ordinary deletion commit.
No source history was rewritten. The Phase 2 import
`119a8ba12e54a2fbea42a43d62725e25fb5bc380`, the full reachable source lineage,
Phase 3 branch and frozen source repositories remain intact.

Jury repository `luciferprosun/AIOA-NonZero-CloudOps-Agent` stays immutable at
`4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a`. The private
`luciferprosun/AIOA-Integration-Sandbox` is also unchanged and is not a runtime
or final-test dependency. The historical source tree SHA is
`a6587b72b4f7d1365ef7de7cab107ea6578f4567`.

Retained in the active tree:

- Native domain implementation, Core admission/service integration and tests.
- Verbatim `runtime/nonzero_cloudops/LICENSE-NONZERO.txt` MIT attribution.
- The byte-identical [native source map](../provenance/NONZERO_CLOUDOPS_NATIVE_MAP.json).
- Small digest-only `tests/fixtures/nonzero_parity_v1.json` (five scenarios).
- [Hash-only retirement lock](../provenance/NONZERO_CLOUDOPS_RETIREMENT_LOCK.json).
- Clearly labelled historical Phase 2 import/ADR and Phase 3 design records.

The last read-only oracle run passed 1447 tests, P0 (15 gates / 136 proof-test
occurrences), P1 (6 / 93), B4 (11 scenarios / 43 proof tests), portable demo,
Ruff, reviewer evidence build/check and validation, and secret scan. P1 used its
supported `local-no-local` clone mode with remote Git transports prohibited.
The full final reference manifest, command results, timestamps and hashes are
sealed outside the repository. No owner runtime state or credentials are in
the lock. The lock's hashes prove integrity/linkage, not factual truth or an
independent attestation that tests ran.

## Retirement reference classification

The complete pre-retirement repository search recorded 1763 matching lines,
each with path, line, matched terms, line digest and reason, in external JSON
and Markdown evidence. The search included all exact paths/identities, original
launchers, clone/fetch, subprocess and path-injection terms requested for Phase 4.

| Classification | Lines | Resolution |
|---|---:|---|
| REMOVE | 1283 | All hits inside the exact 412-file embedded source tree; remove only that tree |
| REPOINT_NATIVE | 22 | Update active install/test/runtime docs and preserve/extend native negative assertions |
| KEEP_ATTRIBUTION | 30 | Retain original SHA comments, source-map hashes and digest-only parity identity |
| PROVENANCE_ONLY | 159 | Preserve historical import/ADR/design records, with explicit superseded/retired scope |
| BLOCKER | 0 | No active native dependency on the old application remained |
| Unrelated existing Core | 269 | Generic Git/subprocess/path terms unrelated to NonZero retirement; leave unchanged |

The last row is not a baseline dependency classification: those hits belong to
existing Core functionality and were explicitly excluded from retirement rather
than mislabelled or deleted. The source-map `source_root` denotes a historical
path at Phase 3, not a path that current execution or tests resolve.

## Current one-system boundary

```text
one aioa-sparkhat[nonzero] package
  -> existing Core AgentRuntime / commands / authenticated WebRuntimeService
  -> discovery + Core operator admission + Core kill switch
  -> native NonZero domain workflow
     -> inert proposal -> exact human decision -> explicit confirmed resume
     -> bounded synthetic mutation -> independent persisted verification
  -> typed result / receipt / existing Core AppendOnlyProvenanceStore
```

No second server, session/credential manager, provider manager, launcher,
repository, runtime Git operation or separate CloudOps distribution is needed.
The original Core `runtime` package facade is unchanged: its legacy sibling
import bootstrap searches only its own package. Native execution adds no
`sys.path`/`PYTHONPATH` setting or external source path. Installed certification
imports the normal Core package without source checkout access.

## Baseline-free acceptance

Run the commands in [native operation](../NONZERO_CORE_INTEGRATION.md), using the
Core optional extra on Python 3.11 or 3.12. Do not restore the retired directory
to run final tests. `runtime.tools.nonzero_architecture` checks physical absence,
nested Git/manifests, native imports/calls, Core ownership seams, packaging and
the offline provenance lock. It does not invoke Git or read retired source.
Negative tests ensure that architectural backsliding is detected.

The original 55 native/integration tests remain. Phase 4 adds six architecture
tests and thirteen public-Core-API authority scenarios: approve, deny, proposal
swap, stale/expired approval, concurrent replay, full Core restart, post-mutation
checkpoint failure, uncertain execution, source tampering, wrong independent
verification identity, disabled module, explicit unavailable AWS, invalid config.
Fault injection observes or interrupts dependencies; it never bypasses the
public Core boundary to start, approve or resume a run.

Whole Core regression runs on both interpreters, with the same four historical
optional Playwright/Textual skips. The native subset permits no skips when the
extra is installed. The exact clean-HEAD wheel is installed into fresh 3.11/3.12
environments and repeats all 74 native/integration/architecture tests, pip check,
discovery, CLI help and Web CLI help. No source-tree oracle, baseline masking,
source overlay or PYTHONPATH injection is used for post-retirement acceptance.

## Guarantee boundary and stop

Portable/synthetic is the only certified executable backend. Explicit AWS
selection remains typed unavailable even with its enable flag. No live AWS or
paid model calls are part of this phase. Real-model advisory, public multi-user
hosting, native live AWS and Phase 2 state migration remain deferred.

Recovery is available through the preserved Git objects/frozen source, not by
keeping a second project in the current package. Do not restore it into the
active tree as a normal runtime prerequisite. Operator review must precede any
remote branch publication or PR; this phase stops at local certification.
