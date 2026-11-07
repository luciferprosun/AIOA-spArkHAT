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

The local Git profile requires an explicitly marked private disposable bare
repository, exact parent SHA, target identity, canonical controller/capsule
proofs, and a distinct exact owner effect warrant. The production create-only
GitHub profile remains closed to PatchSet conversion. The SAME registered
`CoreRemoteGitRoute` traverses the existing ServiceGuard and local-zero START;
then only fixed object writes and create-ref CAS are allowed. It cannot update
main, force-push, create a PR, run hooks, select argv, use credentials or network.
ACK loss retains the canonical UNKNOWN intent. Only independent readback of the
actual commit, parent, tree and blobs can resolve it; no write is retried.

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
