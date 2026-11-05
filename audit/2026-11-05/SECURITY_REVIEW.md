# Security and authority review

Baseline main: `2be99da7aa07f7eb5faa9459fe8a78c5d0b6653a`. Live source remains `16fcfeed477f92f2ec65bd235e0b1cd98f87e7fd`; this integration has not been deployed.

- Native retains its existing OS/PolicyKit owner admission, exact source/capsule, host identity, TLS, HTTP cookie/origin/CSRF, private socket UID checks and one Core transaction/audit path. No production database, identity, token, pairing or UNKNOWN record was edited.
- Chat retains the PR44 owner-session contract and v3 money-policy reader. Sending is still an intentional owner action with a bounded request reservation and one attempt. A session does not grant GitHub/worker authority. Real uncertain requests remain readback-only; recovering a stale banner does not settle an UNKNOWN cost liability.
- GitHub retains typed create-only branch/commit/draft-PR scope, exact review digest, owner warrant, durable START, scoped installation credential, independent GET and signed receipt. No direct-to-main, merge, force push, delete, CLI-token fallback or automatic uncertain retry is added. `enabled` remains false and qualification NOT_LIVE_VERIFIED.
- Proposal preflight failure happens before any WRITE or credential mint. Terminal refusal preserves the Muse-turn binding and cannot be approved or silently retried. Expired/restarted preflight has a read-only failed projection. Owner expiration can still prevent a final journal save; that never grants permission.
- Command/email previews reuse current operator admission and Core audit. They have zero provider/external calls, no command execution, account connection or sending. Email body/addresses are not persisted in the preview record; only exact hashes, size and status. Full MIME/proposal binding is verified, not just a self-consistent hash. Invalid mail input is an explicit signed refusal; uncertain audit persistence still follows normal error handling.
- The command grammar is advisory, not a security parser. `$()`, backticks, process substitution and multiline input now receive suspicious/unknown classification; grammar matches still grant no authority. The older historical Bash classifier with a write-redirection misclassification is not imported.
- Existing Native CPL, worker, semantic memory, Cockroach and unbound orchestration controls remain honestly blocked. No second runtime, memory store, actor identity or alternate governor is created to make a button appear functional.
- New launcher templates require an explicit qualified HTTPS origin and chosen interpreter. The template function installs or starts nothing; existing production launchers are unchanged.

## Independent source review

Read-only Core review of the chat/status/preflight delta found no blocking defect or expanded authority. A second read-only preview review found two actionable problems: shell evaluation misclassified as read-only, and ordinary mail input errors invalidating the whole panel. Both were corrected and covered by new Native tests. Review did not run tests; coordinator test results are recorded separately.

## External blockers

1. No local repository-scoped GitHub App credential configuration/key was found in the retained runtime. ChatGPT installation ID alone is not a local token. Broad owner CLI OAuth is not suitable as runtime fallback.
2. Existing unresolved owner UNKNOWN liabilities remain; no reset, fabricated usage reconciliation or new scope was used to bypass them.
3. No current exact live Muse proposal and owner WRITE warrant has been approved for this integration.
4. Native semantic knowledge requires explicit HAT/scope/consent and compatible persistence binding. Native CPL/worker require reviewed provider/governor/approval composition. Historical guards were retained.
5. Two external working directories are unavailable. Their locally committed refs are backed up; external uncommitted contents and cleanup safety remain unknown.

The existing changed-file secret scanner runs against the frozen base and all untracked candidate files. A PR45 test-token literal was a known synthetic false positive; it was replaced by an explicitly constructed low-entropy fixture, without changing scanner rules or reading a real credential. Current scan outcome is in TEST_RESULTS.md.

## Final implementation review, bb48d794

Two independent READ-ONLY reviewers assessed implementation `bb48d7940f1e759adce4ff8b24c9a296819dc461` against `41aa47e57e5c8e875f0a67d87108cba62d1d623c`:

| Review | Result | Scope / limits |
| --- | --- | --- |
| Architecture and one Core | NO P0/P1 | Actual installed Native/Core/SQLite object sharing, host lock, source-byte pins, durable signed preview/restart/readback, disabled capabilities and offline composite flow |
| Security, ledger and rollback | NO P0/P1 | Conservative command syntax, input refusals, ACK/source fences, no authority expansion, official RO SQLite snapshot and versioned reader method |

Both reviewers also checked the final source matrix, state evidence and rollback documentation: NO P0/P1. The minor report-tense finding was corrected; candidate CI is recorded only after completion. Review does not substitute for tests. Installed acceptance has `chat=False` and synthetic OS/TLS/source admission; the WebRuntimeService object is bound but this installed test does not perform a browser roundtrip. Muse fixture and isolated Chrome acceptance are separate tests. Hosted packaging uses isolated Python/venvs without checkout imports; the local `--isolate-filesystem` run additionally hides the checkout and isolates network/PID namespaces. Neither certifies production restart.

The security reviewer identified two evidence improvements, now applied to the private validator: verify each exported Python file against the claimed commit blob and constrain imported module origins; report the three CHAT_UNKNOWN records separately from the two governor UNKNOWN reservations. All three pinned readers pass with identical state projections. Old-main refusal and the initial validator's MappingProxy harness error remain preserved.

Runtime policy delta from the live version is **none** for money-policy/v3, CoreAdmission, warrant readers, pairing or audit contracts. Relative to old main, PR44's owner-session/v3 behavior was already active in the retained prototype; this code release preserves it. PR45 adds the typed remote-zero intent contract, but remote execution remains disabled/unqualified. This sprint only tightens advisory classification and makes capability status explicit. No production policy/configuration/scopes were changed.

Rollback is code-only with a newly validated current journal, never replacement by an old SQLite snapshot. `16fcfeed` is conditional on understanding every retained intent; old `2be99da7` refuses the copied v3 state and is prohibited. State and source evidence are in [STATE_COMPATIBILITY.json](STATE_COMPATIBILITY.json) and [rollback instructions](../../docs/ROLLBACK_AND_RECOVERY.md).
