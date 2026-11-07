# Bounded Python repository coding on the existing Core

NZ11 extends the existing `AgentRuntime` opt-in binding, `CoreCodingTasks`,
`CoreIntentJournal`, `CoreWarrantLedger`, `LinuxSandboxBroker` and
`CoreRemoteGitRoute`. It adds no composition root, server or effect store.
The production Native process and remote GitHub profile are unchanged.

The qualified programming profile is a real Git repository of UTF-8 Python
modules, tested with bounded JSON function-call cases. It is not an arbitrary
pytest/shell runner. An operator-owned 0600 static manifest fixes repository ID,
actual base Git SHA, allowed paths, import roots, three stages and the sole
supported Python argv. `PythonRepositoryRecipe.load_file()` rejects extra fields,
commands, links and public configuration. Credentials are never manifest fields.
Expected answers remain outside the guest; a guest PASS or test counter is not
accepted. Ordinary Python modules and packages can use the pinned stdlib.

A private read-only bare source snapshot is independently read through fixed Git
plumbing, with commit/tree/blob hashes recomputed. A plain export contains no
`.git`. Candidate ADD/MODIFY/DELETE data is bounded by the existing PatchSet
policy. A Core-admitted materialization job performs the actual edits inside the
Linux sandbox, without importing candidate code. The broker independently reads
back exact artifacts after teardown. New host mirrors use pinned directory
file descriptors; they never edit a host repository. Validation imports candidate
modules from read-only archived inputs, returns only advisory JSON values, and
compares them with the external oracle in the Core host.

The bounded coordinator permits at most two repairs. Test failure, malformed
output, timeout, cleanup failure and UNKNOWN stay distinct. A separate host
semantic review rejects test bypass patterns. Canonical validation and
materialization records join to actual Applied Core intents; the controller also
records the exact bounded loop in OPERATION/audit/outbox. Signed capsules bind
all those hashes. The existing calculator profile is retained for regression.

The controller records QUEUED, RUNNING, VALIDATING, REPAIRING, REVIEW_REQUIRED,
APPROVED, APPLYING, VERIFIED, DENIED, CANCELLED, FAILED and UNKNOWN in the same
signed receipt chain. Host callbacks are registered by the admitted composition,
never accepted from HTTP/model JSON. Two active WorkerPorts have independent
cancellation tokens. STOP reaches the worker and sandbox. A cancelled worker may
be CANCELLED only if no unresolved Core intent remains; otherwise it stays
UNKNOWN. Worker/sandbox cleanup failure is UNKNOWN even after a STOP request.
Uncertain owned handles keep their capacity quarantined, and canonical UNKNOWN
or unrecovered active claims block new starts, including after host restart.
Recovery never relaunches a claimed run. Re-registering an effect binding
after restart does not grant replay.

Every terminal classification checks the complete bounded canonical intent
history, including materializer exceptions without cancellation. An unresolved
intent dominates apparent FAILED/CANCELLED results. A quota-sized history scan
fails closed rather than treating its prefix as complete. STOP, review handoff,
effect-token publication and close share the controller's lifecycle lock.
APPROVED tasks can also be cancelled through the existing API and panel.

The local Git profile requires an explicitly marked private disposable bare
repository, exact parent SHA, target identity, canonical controller/capsule
proofs, and a distinct exact owner effect warrant. The production create-only
GitHub profile remains closed to PatchSet conversion. The SAME registered
`CoreRemoteGitRoute` traverses the existing ServiceGuard and local-zero START;
then only fixed object writes and create-ref CAS are allowed. It cannot update
main, force-push, create a PR, run hooks, select argv, use credentials or network.
ACK loss retains the canonical UNKNOWN intent. Only independent readback of the
actual commit, parent, tree and blobs can resolve it; no write is retried.

The broker's fixed Git profile checks the complete no-follow internal storage
tree (4096 entries, depth 16, 64 MiB), private 0700 root, single-link regular
files, mount identities and pinned critical storage directories. Alternates,
worktree redirection, symbolic refs and unsupported local configuration are
denied. Exact runtime hashes are copied into sealed memfds before use. Git runs
in an empty network-off namespace with only a read-only repository view, fixed
safe config, pinned Git/runtime bytes, seccomp, resource ceilings, bounded IO,
cancellation and owned-process cleanup. No host storage gets a writable mount.

Git validates object identities in that read-only view. The SAME broker creates
loose objects and new refs using descriptor-bound unnamed temporary files,
fsync and exclusive link publication. It never truncates, appends, chmods or
freshens existing files. Existing objects are verified without atime changes.
The ref operation is create-only CAS (old value zero), not a general update-ref
interface. The route passes the exact approved root/storage identity to the
opened descriptor before actuation. Its execution-profile hash is part of the
owner-reviewed operation. A filesystem without O_TMPFILE/exclusive publication
support is unsupported and denied; no less restrictive fallback is provided.

Owner-witness persistence and the signed APPROVED receipt commit atomically in
the existing Core transaction. Exact retries can reconcile a matching,
unconsumed, unrevoked witness; they cannot renew expiry or transfer a session.
After APPLYING/UNKNOWN/VERIFIED, a newly reconstructed route is historical and
read-only. It verifies immutable canonical proofs and existing dispatch/intent
provenance without requiring a fresh capsule or current source branch. Readback
still validates the actual approved target and full commit/tree/blob contents.
The original stored operation is shown after session restart. Such a binding
cannot approve, validate or dispatch a new effect, even with another nonce.

The existing HTTP service exposes `/api/agent/coding/` under its loopback origin,
session token and exact intent checks. The host must explicitly inject admitted
READ/MANAGE/COMMIT/OWNER_APPROVAL principals. No default principal is created.
The existing Mission Control panel uses those endpoints and renders real Core
states. Approval and execution are separate explicit buttons. The installed
client connects to that server rather than creating another runtime:

```text
aioa-sparkhat mission coding read_status --payload '{"task_id":"task-1"}' --connection-file /private/coding-connection.json
```

The private connection file is 0600 and contains only `port` (loopback) and the
existing `csrf_token`. It must not enter Git, logs or model input. A missing ACK
requires readback, never automatic resend. `create_task`, `start`, `get_receipts`,
`stop`, `review_effect`, `approve`, `deny`, `apply`, `recover` and `reconcile`
follow the same server/Core path. Deployment and operator-session renewal use
the existing Native host and require owner review; NZ11 does not deploy them.

Codex App Server diagnostics have initialize/thread-start/event/cancel/timeout/
crash tests, including the installed official binary in a network-off isolated
fixture with no host shell or credentials. `OwnedCodexProtocol` only handles
already-owned pipes; it has no process launcher or turn/start port. `CodexWorker`
remains NOT_CERTIFIED. A real inference turn and its CandidatePatch-to-Core
integration need separate owner approval and contained backend certification.
Protocol success is not model/tool-use certification.

Linux x86_64 sealing uses the stable Linux UAPI command numbers and verifies
F_GET_SEALS after F_ADD_SEALS. Python builds that omit the symbolic constants
remain supported; a kernel refusing any required seal is denied before exec,
with no unsealed fallback. This is covered on both supported interpreters.
