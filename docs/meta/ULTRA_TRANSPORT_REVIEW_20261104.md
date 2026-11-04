# Ultra transport correction — independent review

Reviewed against `9e7dd3f1ea7f03a61b7aac9e67e93f605b74e7e1` on 2026-11-04.
The exact 11-file snapshot is sealed in
`ULTRA_TRANSPORT_REVIEW_SOURCE_MANIFEST_20261104.json`:
`5621643fee6d1602b196220b70b220ac6f023cf79765f504f141f2cc857e14a6`.

Two independent read-only Codex reviewers inspected the runtime and Chrome
changes. This is engineering review, not owner approval to merge or spend.

## Observed defects and corrections

- Actual Chrome startup could stall on an initial direct HTTPS target. The
  launcher now performs a browser handshake, creates a blank target, attaches,
  and navigates before checking the exact secure document. The one-use bootstrap
  rechecks href/origin/security in the same JavaScript turn as its single POST.
  It uses an absolute expected URL and rejects redirects. `mode: cors` preserves
  the existing closed `Sec-Fetch-Mode` receiver; widening that receiver is
  unnecessary. No debug TCP port, TLS bypass or token-bearing URL was added.
- A real GitHub branch GET exceeded its four-second child limit. Six sequential
  children could also exceed the browser's eight-second transport deadline.
  One twenty-second monotonic recipe deadline now includes native admission and
  lock waiting. GET children have an eight-second cap; config/Git remain four
  seconds. Every child is capped by remaining recipe time. Only `tool_read`
  receives a thirty-second browser/private-socket response budget.
- Timeout diagnostics use the existing pending Core record and AUDIT/OUTBOX.
  They contain a closed code/stage/time, keep UNKNOWN, and never authorize replay.
  Review found that final signing/commit expiry initially escaped diagnostic
  persistence. A failing real-Core test reproduced it; the centralized handler
  now covers that path. Only a known `TRANSACTION_FAILED` immediate timeout
  cause is decoded. An uncertain commit ACK is not recast as definite failure,
  and VERIFIED records cannot be downgraded.

The first contained browser run of the correction failed because the proposed
`same-origin` fetch mode conflicted with the existing receiver's `cors` contract.
The original receiver was preserved. The corrected contained test passed in
36.607 seconds, including a changed-document negative execution with zero fetch
calls, navigation/focus/large-text assertions and empty credential-profile scans.
This uses synthetic TLS/Core, not a physical phone or live model.

## Independent result and local validation

The runtime reviewer independently ran three isolated tests: final-phase timeout
evidence, persisted success after lost commit ACK without redispatch, and two
simulated five-second GETs sharing one budget. All three passed. No remaining
Critical or Important finding was established in the sealed snapshot. The Chrome
reviewer confirmed source sealing, same-Core one-use admission and owned-process
cleanup. Root separately ran 52 transport tests and 40 JavaScript tests, all PASS
with no skips, plus the contained browser gate above.

The corrected Core/chat/authority invocation passed 51 tests in 31.128 seconds.
Its first invocation supplied only a relative tests PYTHONPATH; five process
tests failed to import `lab`. That failed log is retained. Re-running with the
absolute repository and tests paths fixed the invocation without source changes.

The active Native host remains immutable `9e7dd3f`; these source changes were
not deployed into it. Its actual read-only receipt is historical evidence for
that source. Final candidate CI, owner merge, renewed native admission and fresh
physical readback remain separate gates.

Private evidence retained outside Git:
`READ_DEADLINE_RED.log`, `READ_TIMER_RED.log`, `CHROME_DELIVERY_RED.log`,
`FINAL_COMMIT_TIMEOUT_RED.log`, `READ_DEADLINE_GREEN_REVIEWED.log`,
`TRANSPORT_RELEASE_FINAL.log`, `JS_SUITE_RELEASE_FINAL.log`,
`CHROME_STAGED_CONTAINED_GREEN.log` (failed attempt), and
`CHROME_STAGED_CONTAINED_CORS.log` (PASS).
