# NZ13-C: bounded GitHub observations on the existing Native plane

This candidate adds four fixed recipes: repository metadata, issues, pull
requests and Actions run metadata. They reuse `native_read._github_json`, its
pinned `gh` process, one deadline and the existing Core READ receipt journal.
No URL, repository, pagination endpoint or command is accepted from the model.

Each observation binds the fixed public repository identity to a verified main
commit, complete root tree and README blob. A final ref read detects drift.
Lists read at most two fixed pages of ten rows. The six list endpoints have a
256 KiB transport cap per page and a 32 KiB cap on the signed list projection.
Duplicates, invalid identities,
foreign URLs, malformed digests, expired authority and ambiguous outcomes deny;
403/404/429 never cause an automatic retry or disclosure of error bodies.

The context inventory describes the actual fixed Native GET adapter. It does
not claim that the historical MCP server version is installed. Old NonZero
Repo/Issue/PR/Actions fields are mapped to inert data; missing PR detail counts
remain `null`. Actions conclusions are remote observations, never Core task
completion. Job logs and check summaries are not fetched or certified.

The same signed Core READ receipt can be supplied to advisory Muse chat. Its
closed context shape and digest are checked before payload construction. It
enters a user-data message, with no tools or approval authority. The existing
4 KiB context and 16 KiB payload limits remain; oversized reads are refused
for chat rather than silently truncated into a different signed observation.
This path is not the coding WorkerPort and grants no model execution right.

Recognized sensitive text suppresses the entire public field. A README is
checked before excerpting, including credentials spanning or following the
excerpt boundary. A redacted projection retains the verified original blob
SHA, SHA-256 and byte count; the mask is never represented as the raw file.
Clean legacy file shapes remain unchanged. Credential-shaped branch names deny.
The canonical redaction implementation is stdlib-only; its old NonZero import
remains a compatibility re-export. It retains the original MIT attribution.

Provider callback handling uses the existing value-free failure boundary,
relocated to a small stdlib module and re-exported by Core repair. Process
signals, exact approvals, UNKNOWN holds and no-retry behavior remain. Both new
shared policy files are in the Native source seal and protected from PatchSet
changes, alongside the original protected policy file.

Local bare-Git ADD/MODIFY is separate from GitHub App WRITE. The existing remote
create-only actuator, scoped App credential, exact owner warrant, lease, target,
no-main-overwrite, no-force, no-DELETE and lost-ACK rules remain. A broader
remote MODIFY profile and real remote WRITE are NOT_CERTIFIED/OFF. Read context
and successful local Git cannot authorize them. No hosted CI, model inference,
remote write, deployment or retirement is certified by local fixture results.

Qualification must bind the final candidate SHA/tree, all local gates, installed
artifacts and independent review. Historical NZ12 source/role assessments are
retained; updated current blob/AST locations alone do not certify full parity.
