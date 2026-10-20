# AIOA Gmail Gateway — G3 security hardening, batch 1

Date: 2026-10-20. Target: `feature/aioa-gmail-gateway` only.
Input branch head: `d53e96f4e124ccafa79d3e64996c163730be55e2`.
Code commit: `cfb4551b67757aaf1ff80840ddc74da9cc57c987`.

## Verdict

**64 unique module tests PASS, 0 FAIL, 0 ERROR, 0 SKIP.** This comprises the
original 36 methods and 28 new G3 methods. This is a focused OFFLINE result,
not full AIOA regression, independent review, real Gmail, or a production
owner-approval qualification. **G3 external review PENDING; LIVE remains BLOCKED.**

Implementation and tests were performed in a separate ChatGPT execution
container, not on the owner's PC. No Codex process, Linux sprint, GOLD72 store,
OAuth credentials, Gmail account, package installation or paid model call was
used. The container could not clone GitHub through DNS; a byte-verified source
slice was assembled from the connected repository evidence instead. Its 13
baseline files match their recorded Git blob IDs. No replacement Core was made.

## Changes backed by counterexamples

1. **Exact MIME binding.** Outbox preparation now regenerates the canonical
   message and compares bytes, digest, proposal fingerprint and correlation ID.
   A self-consistent hash of substituted content is not sufficient.
2. **Logical-task replay.** In a single-owner ledger, one task has at most one
   mail intent. A new proposal ID or nonce cannot reset that task's send budget.
   Check and insert run in the same BEGIN IMMEDIATE transaction. Two spawned
   processes racing different proposal IDs for the same task produce one
   acceptance and one denial. This is not global/provider exactly-once.
3. **Fixture validity.** Synthetic admissions validate hex digests and canonical
   UTC expiry; both not-before and expiry are enforced and fields are rechecked
   at use. A fixture claiming effect authority is denied. It is still only a
   fake, never a real human signature.
4. **Unambiguous text.** Surrogates, hidden Unicode controls and paragraph/line
   separators cannot escape validation or become misleading header text. Plain
   LF/tab remain accepted in bodies. Narrow Unicode support is intentional.
5. **ACK honesty.** A response containing both IDs and an error is not success.
   Nonfinite JSON constants are rejected. The receipt type cannot claim delivery
   to a recipient. The codec still has no HTTP client or access token.
6. **Storage paths.** Owner-only permissions/ownership, canonical parent chain,
   single-link regular files, auxiliary WAL/SHM/journal paths and pinned parent/
   DB inode identities are checked. Existing unrelated SQLite files are refused
   without initialization. Filesystem/SQLite failures use fixed error codes.
7. **Corrupt recovery.** All stored rows are validated before preparation,
   transitions or recovery. Changing a row out of SENDING no longer hides it
   from integrity validation. Recovery is capped at 1,024 records; excess data
   blocks rather than evicts history or resets a budget.
8. **Uncertain transport.** The offline simulator maps unexpected OS-level
   failure after fake acceptance to UNKNOWN_SEND without another fake call.
   A child exiting via os._exit after durable SENDING is reopened and recovered
   as UNKNOWN; another proposal for that task is denied.
9. **Test hygiene.** Explicit SQLite connection closure removes Python 3.13
   ResourceWarnings without changing the previous test assertions.

## Verification and preserved failures

- Baseline: 36/36 PASS on the unchanged source slice; existing tests produced
  SQLite ResourceWarnings. Original source remains archived in the evidence.
- First G3 RED: 25 methods, 23 failing methods and 2 controls PASS; unittest
  reported 27 failure entries because one method has multiple subtests. No ERROR.
- Focused input repairs: 29/29 PASS (not a distinct inventory to add to 64).
- First integrated GREEN: 61/61 PASS, with test resource cleanup warnings retained.
- Review regressions: two additional negative tests failed before their fixes.
- Final normal unittest run: **64/64 PASS**; no resource warnings.
- Bare pytest over all available tests in the source slice: **64 PASS**, with
  49 subtests reported separately. Subtests are not counted as extra methods.
- Actual environment: CPython 3.13.5/Linux. New-code execution on the owner's
  Python 3.12 and full repository integration remain required before merge.
- `git diff --check` passed. The source manifest binds every tested Python file;
  fresh bundle-restore verified all 14 Python files unchanged and again passed
  64 unittest methods (2.239s) and 64 pytest cases (2.54s). The 49 pytest
  subtests remain separate. See `g3_evidence/TEST_RECEIPT.json`.

## Explicit trust and compatibility limits

The database belongs to ONE trusted OS owner and ONE mail namespace. Task IDs
must be host-issued operation IDs, not arbitrary model-generated retries. A new
legitimate message needs a new host-approved mail task. Existing databases with
duplicate task history are blocked, not silently migrated or pruned.

Inode/permission checks are defense in depth, not isolation from malicious
same-UID/root writers racing between checks and SQLite operations. Row digests
are unkeyed corruption detectors, not authenticity signatures. File deletion,
rollback to an older entire database, changing stores/accounts, disk/power-loss
behavior, and privileged tampering need independent production defenses.

The caller-supplied STOP flag remains a synthetic pre-call check. Persistent
Core STOP, in-flight cancellation, authentic owner identity, source-bound Core
warrants, account binding and real token custody are NOT implemented by this
batch. Protocol declarations are not implementations. No new signer or second
Core was introduced, and no permission was derived from a public fixture key.

## Next gate — independent C1 review, without invoking Codex automatically

Review the exact diff and source manifest using `GMAIL_G3_REVIEW_REQUEST.md`.
Do not certify the original roadmap's full 24-case matrix from these tests:
see `GMAIL_G3_MATRIX.md` for tested, partial and unimplemented cases. After a
separate review, continue the offline broker/transport work; real OAuth and
one-message Gmail tests still need the owner's separate exact authorization.

## Reference documents (not evidence of executed Gmail operations)

- SQLite transaction semantics: https://www.sqlite.org/lang_transaction.html
- Gmail message resource: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages
- Approved project roadmap: `AIOA_spArkHAT_Gmail_Gateway_MASTER_Roadmap_Android_First_2026-10-20.md`
