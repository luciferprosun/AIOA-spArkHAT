# Final local candidate freeze

Preparation basis / rollback: `238336a10bcbf7991d7d6735ae692e4437f694e3`.
Main: `d26266e54ee940d7ada30aa02783dc697618a72c`.
Branch: `integration/nebius-unified-prototype-20261008`.

This document defines the local freeze; it cannot contain its own future commit SHA. Acceptance is established only by the external post-commit receipt at:

`/media/l/LSC_DATA1/MCP_Commander/data/artifacts/nebius-full-day-sprint/20261008T034855Z/convergence-to-main/20261008T162045Z/final-local-freeze/20261009T151053Z/EXACT_POST_COMMIT_CANDIDATE_RECEIPT.json`

That receipt binds the final committed HEAD, parent/main/rollback, source hashes, exact targeted/focused/full test counts, static/import/diff/changed-file secret gates, fresh review, isolated checkout reviewer, preserved prior evidence and detached ff-only rehearsal. Read it before treating the candidate as locally frozen. Missing or failing evidence means FINAL_LOCAL_FREEZE=BLOCKED.

## Security classification

All 30 remaining fixture observations reviewed: 0 CONFIRMED_FIXTURE, 30 LIKELY_FIXTURE_WITH_LIMITATION, 0 UNKNOWN. Synthetic origin remains independently unestablished for all 30. See `docs/security/FIXTURE_PROVENANCE_REVIEW.json` for exact object/path/line references and evidence hashes. Historical raw FAIL/findings and semantic counts are preserved. Ten binary objects are path/type inventoried; embedded content and rights remain human-gated. No blanket security or rights clearance is claimed.

## Validation and external gates

Exactly one final full native regression is required because preflight source/tests changed after the prior sealed 1553-test run. Source/runtime/tests remain unchanged during this freeze. Only the four exact previously approved optional UI skips are allowed. Exact observed counts live in the external receipt. Fresh review must be C0/I0/M0.

Submission preflight is expected to return BLOCKED; the external dry-run wrapper classifies missing real receipts as BLOCKED_EXTERNAL. It never asserts READY_TO_SUBMIT. Release preparation must remain PASS_LOCAL_PREPARATION. The external exact-candidate matrix is a current-SHA copy of preparation statuses, with no invented receipts.

MAIN_INTEGRATION_CANDIDATE=YES (mechanics only).
MAIN_INTEGRATION_READY=NO.
LIVE_PROVIDER_VALIDATION_READY=YES (prepared operator plan only; zero calls authorized); PERFORMED=NO.
PUBLIC_JUDGE_PACKAGE_READY=YES (local package only); DEPLOYED=NO.
DEVPOST_PACKAGE_READY=NO (mandatory real receipts missing); SUBMITTED=NO.

Rights/security/legal review, current authorized live proof, pinned install/transitive notices, public repo/demo/hosting/DNS/video/uptime and Devpost receipt remain open. No merge, push, PR, tag, release, deploy, upload, provider inference, billing/credit redemption or legal acceptance is performed.

Next action: WAIT_FOR_OPERATOR_EXACT_SHA_AUTHORIZATION. No main operation is authorized by this local freeze.
