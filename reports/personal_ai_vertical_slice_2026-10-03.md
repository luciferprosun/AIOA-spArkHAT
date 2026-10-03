# Personal AI vertical slice operator report — 2026-10-03

1. **Starting branch / SHA and ending SHA**

   Started on `nebius-personal-ai` at
   `5871f254b13dda6e1a26801747bcff0f3bb495f1`. The completed implementation
   before this evidence commit is
   `54a161c3959c633dd08b05e4ae83537657570875`; the final evidence commit is
   reported by the operator response after commit so the report does not claim
   a self-referential SHA.

2. **`main` and `origin/main`**

   Both remain `d26266e54ee940d7ada30aa02783dc697618a72c`. No merge, rebase,
   reset, push, tag, release, or deployment was performed.

3. **Files changed**

   Added or changed: `.env.example`, `deploy/nebius_serverless/README.md`, the
   Prompt 02 plan, `scripts/nebius_live_probe.py`, the HTTPS transport,
   ServiceGuard exports, Personal AI coordinator, Nebius competition routing,
   competition projection, web server, Operator Console HTML/JS/CSS, six
   focused test files, this report, the runbook, one Prompt 02 live receipt,
   and one redacted evidence manifest. `git diff --stat` from the Prompt 01 SHA
   is the authoritative path list.

4. **Live Lightning smoke**

   **FAIL — `INCOMPLETE_COMPLETION`.** Exactly one Prompt 02 paid attempt was
   made with a 256 output-token bound and 20 second request timeout. It was not
   retried. The sanitized receipt is
   `evidence/cloud_activation/live_smoke_20261003T092018Z.json`.

5. **Exact live model and safe provider metadata**

   Requested model: `nvidia/Nemotron-3_5-Lightning`; provider: `nebius`;
   fallback: `false`; catalog validation: `true`; live inference validation:
   `false`. Request ID, usage, finish reason, and latency were not safely
   available on this exception path and are therefore absent rather than
   invented. Response content and API credentials were not persisted.

6. **Personal AI vertical slice**

   **PASS in explicit `FIXTURE` mode.** The coordinator composes the existing
   private HAT, exact Nebius ProviderPort, ServiceGuard, target client, receipt,
   and readback paths. Provider output remains `ADVISORY_ONLY`. The verified
   fixture sequence is `ADVISORY`, `VERIFIED`, `APPROVAL_REQUIRED`, `APPROVED`,
   `EXECUTED`, `RECONCILED`, `REPLAY_BLOCKED`. A separate test proves the
   `ZERO_WRITE` path.

7. **Memory persistence restart proof**

   A private maintenance constraint was activated in the existing owner-scoped
   HAT, the runtime was closed and recreated, and retrieval returned bounded
   references. Only counts/statuses and a context hash reached demo state; the
   private text did not appear in status, receipts, logs, UI projection, or the
   manifest.

8. **Approval → ServiceGuard → effect → receipt proof**

   Prepare stopped at `APPROVAL_REQUIRED` with effect count zero. Exact
   approval changed state to `APPROVED` and still left effect count zero. A
   separately intended resume passed through ServiceGuard, emitted the typed
   `APPLY_SET_MAINTENANCE`, stored a durable receipt, then independently read
   target state before marking the result verified.

9. **Replay and lost-ack proof**

   The lost-ack test applied once, returned `UNKNOWN/EXECUTED`, recreated the
   runtime, read the existing receipt and state, and reached `RECONCILED`
   without another apply. A later resume reached `REPLAY_BLOCKED`. Fixture
   evidence recorded `target_apply_count=1` and `transport_apply_calls=1`.

10. **Cloud HTTPS adapter**

    **IMPLEMENTED AND OFFLINE-VERIFIED.** The one-attempt adapter accepts only
    the typed target contract, injects bearer auth from the environment,
    rejects unsafe endpoints, follows no redirects, bounds responses, and maps
    ambiguous transport outcomes to `TargetUnknown` for read-only
    reconciliation.

11. **Live Nebius Serverless deployment**

    **`BLOCKED_BY_CREDENTIALS`.** No project/region, deployed HTTPS endpoint,
    platform auth secret, approved durable store, or separate deployment
    authorization is present. No endpoint, image, job, or recurring resource
    was created.

12. **UI/demo**

    **IMPLEMENTED.** The existing Operator Console has a compact Nebius
    Personal AI panel and four session-token-protected routes. Provider/model,
    `LIVE|FIXTURE`, HAT status without private text, CPL, verification,
    `ZERO_WRITE`, approval, ServiceGuard, receipt hashes, reconciliation, and
    replay are visible. Prepare, approve, and resume are separate controls with
    distinct intent headers. The default web runtime reports not configured
    until the host injects the Personal AI composition; it never creates or
    relabels a fixture silently.

13. **Tests executed**

    Final Task 7 matrix, all without timeout:

    - New Prompt 02 tests: **61 PASS, 0 FAIL** in 13.524s.
    - Additional Nebius/CPL/serverless regression: **16 PASS, 0 FAIL** in 0.891s.
    - LITE/HTTP/ServiceGuard regression: **78 PASS, 0 FAIL** in 27.820s.
    - NV10 guard/memory/recovery: **31 PASS, 0 FAIL** in 38.453s.
    - Private chat and owner isolation: **43 PASS, 0 FAIL** in 55.548s.
    - Final matrix total: **229 PASS, 0 FAIL, 0 timeout**.

    Earlier task gates also passed: Task 1 16/16; Task 2 12/12; Task 3 5/5;
    Task 4 26/26 plus 31/31 adjacent regression; Task 5 7/7 plus 38 tests
    with 13 expected skips for an uninstalled optional Non-Zero extra. Some of
    those runs overlap the final matrix and are not added to the 229 total.

14. **Secret scan**

    **PASS.** The final changed-file scan examined 23 paths for private-key
    markers, Nebius token assignments, literal bearer credentials, and common
    API-key prefixes. It reported categories and paths only and found zero
    candidates. The live receipt is mode `0600`. No real secret was committed.

15. **Blockers**

    The Prompt 02 acceptance target of one successful real Token Factory call
    remains unmet because the single authorized Lightning attempt ended in
    `INCOMPLETE_COMPLETION` at 256 tokens. Live Serverless deployment remains
    blocked as described in item 11. The fixture panel requires explicit host
    composition injection for a runnable web session.

16. **Recommended Prompt 03**

    Authorize one diagnostic phase before any further paid request: confirm
    current Lightning completion behavior with Nebius documentation/support,
    add safe provider metadata propagation for incomplete completions, and
    decide whether a separately authorized 512-token bounded probe is justified.
    In parallel, add a production fixture launcher for the panel. Deploy the
    serverless target only after project credentials, durable-store fencing,
    cost ceiling, and separate operator approval exist.

17. **MAIN TOUCHED = NO**

    `main` and `origin/main` are unchanged at
    `d26266e54ee940d7ada30aa02783dc697618a72c`.
