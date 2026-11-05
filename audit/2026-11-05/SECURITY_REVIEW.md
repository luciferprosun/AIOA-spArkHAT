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
