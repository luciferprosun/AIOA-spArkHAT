# Bounded coding candidate messages

The existing WorkerPort and WorkerMailbox carry advisory data into the existing
Core. Candidate messages cannot execute a command, approve a change, select a
destination, grant credentials, or claim verified status.

## Wire admission

`WorkerMailbox.complete_json(session, raw, completion_tokens=...)` accepts one
UTF-8 JSON object with exactly these fields:

```json
{
  "schema": "aioa.worker-candidate.v1",
  "task_id": "task-1",
  "run_id": "run-1",
  "session_id": "worker-session",
  "task_digest": "<canonical task SHA-256>",
  "files": [{"path": "src/calc.py", "text": "<candidate source>"}]
}
```

All identifiers must match the admitted mailbox. The host transport supplies
measured completion tokens separately; a model-supplied usage or authority field
is refused. The closed format rejects duplicate fields, nonfinite JSON, invalid
UTF-8, excessive nesting, secrets, repeated paths and more than three files.
Task output tokens are bounded to 1..4096. Wire bytes are bounded to
`min(65536, max_output_tokens * 16)`; file content retains its separate bound.

Admission returns an unverified CandidatePatch with authority NONE. The existing
materializer, PatchSet policy, LinuxSandboxBroker, independent oracle, signed
capsule, exact owner approval and CoreRemoteGitRoute remain mandatory.

## Durable compatibility and uncertainty

The fixed legacy output limit of 1024 remains implicit in the v1 task digest.
The original eight-field task and its signed receipts remain readable without
rewriting or resigning. Nondefault limits are explicit and hash-bound. Both
closed task shapes are accepted; unknown fields and altered signatures deny.

An explicitly bound WorkerFailure with code OUTCOME_UNKNOWN has status UNKNOWN.
The producer verifies session/task/run before propagating that uncertainty. The
existing coordinator stops before materialization and does not attempt repair
or resend. Core records its normal signed UNKNOWN state, retains the run slot,
and refuses a replacement run after restart. STOP, close and a late candidate
do not turn an already unknown outcome into an acknowledged cancellation or a
successful result. A cleanup acknowledgement failure also preserves uncertainty.
On STOP or poll timeout, the producer reads the transport's bound cancellation
result before reporting cancellation or failure. An uncertain cancellation ACK
therefore remains UNKNOWN even when the shared cancellation token is set.

Cancellation is claimed once in the existing producer. A missing, mismatched or
uncertain terminal ACK, or an exception while cancelling/reading it, is sticky
UNKNOWN through close, signed Core readback and restart. STOP/poll/close never
resend that cancellation. The short lifecycle lock is released before port I/O.

Repair start atomically checks STOP and the shared token and detaches the old
completed handle before calling the worker. STOP before admission prevents
dispatch; STOP during an admitted start applies to the new returned session.
An old session's ACK never acknowledges a new session's cancellation.

## Verification and remaining model boundary

Focused regressions cover message validation, legacy signed receipts, budgets,
late/stale events, STOP, uncertainty, restart and replay refusal. The offline
wire acceptance injects an explicitly synthetic WorkerPort into the existing
kernel acceptance. It exercises a failing candidate, repair, independent
validation, capsule, owner decision, local bare-Git ADD/MODIFY and readback.
Synthetic usage and zero paid calls describe that fixture only.

The real Codex App Server protocol diagnostic remains network-isolated and
does not perform inference. CodexWorker remains NOT_CERTIFIED. This decoder and
the offline fixture are not a real model backend or a production deployment.
There is no enable-live flag, fallback provider, new executor or approval store.

A real coding turn requires the owner's provider/model/endpoint selection and
an exact GO_MODEL_TEST with call, token, timeout and cost bounds. A future Meta
adapter must reuse the existing Meta provider, Core spend admission, governor
and receipt records. The provider receipt must be bound through the candidate,
capsule and local-Git readback. Until that test is implemented and authorized,
the real-model gate is MODEL_TEST_BLOCKED_OWNER and retirement remains NO_GO.
