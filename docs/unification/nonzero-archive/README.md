# NonZero migration archive — reference-only, not a runtime

This directory records migration audit evidence and selected historical documents from `luciferprosun/AIOA-NonZero-CloudOps-Agent`. It is an ordinary directory **inside the AIOA spArkHAT repository**, not a Git submodule, package, source checkout, executable mirror or replacement for a verified legacy Git bundle.

## Pinned sources
- AIOA protected main at audit start: `9d8b61c6dce9cccbf32ce8dfc2dc87682567dd9c` (merged PR #64).
- Legacy `main`: `4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a`, pinned snapshot of 412 Git blobs, including 99 under `docs/`.
- Historical W7A comparison ref: `392487849eddc7444f5159994b66b72e73f15934` (different snapshot; do not confuse with legacy main).
- Authoritative *current* migration ledger remains `../cloud-consolidation/PARITY69_UPDATED.csv`; open issues in `../cloud-consolidation/NONZERO_RETIREMENT_GATE.md`.

## Contents
- [Complete 412-file snapshot inventory](LEGACY_MAIN_FILE_INVENTORY.md): paths, blob SHA and sizes from the pinned legacy main.
- [Retirement audit and decision gate](RETIREMENT_AUDIT.md): what is still blocked and the specific exit conditions.
- [Non-code migration disposition](DISPOSITION.md): classification and duplication policy.
- [Historical prior-art disclosure](historical/PRIOR-ART.md), [project charter](historical/PROJECT_CHARTER.md), [decision register](historical/DECISIONS.md), [submission prior-art disclosure](historical/SUBMISSION_PRIOR_ART_DISCLOSURE.md), and [original LICENSE](historical/LICENSE): copied verbatim from legacy main `4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a`. Historical statements describe the original hackathon scope and are **not** assertions about current AIOA behavior.

Other historic documents are discoverable via their exact path and Git blob OID in the inventory. They have **not** been copied into this directory; an inventory link alone does not protect their content against source deletion.

## Operating policy
- No executable files, Docker/AWS deployment manifests, credentials, model weights, live data or test adapters are imported here.
- Do not import this directory from runtime, build it as a package, or use archived documents as current operational instructions.
- Keep the legacy repository available. **Status: RETIREMENT_HOLD**, NOT FULL_PARITY.
- For deletion-level preservation, verify offline backups on independent physical media, all 13 Git refs, checksums, full `git fsck`, non-Git GitHub metadata exports and dependencies before separately approving any deletion.
- Codex Cloud owns shared implementation and PRs #65–#66. This isolated documentation-only PR must not alter those branches or existing ledgers.

*Audit prepared 2026-11-24 using the connected GitHub integration.*