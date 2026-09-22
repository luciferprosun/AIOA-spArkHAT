# NV06 / G06: isolate functional test scratch from storage contention

The G06 harness previously bound every test's `TMPDIR` to the report drive
(`/media/l/LSC_DATA1`, ext4). CPL's real trace writer makes 26 `fsync` calls
for the normal plan and five-generation execution. Its functional web test
has a five-second completion bound. Sharing scratch with a contended storage
device made that test depend on unrelated filesystem latency.

## Measured reproduction

The unchanged test passed alone and after the same 146-test discovery prefix.
An observation-only diagnostic recorded monotonic timestamps for planning,
nonce generation, workers, completion signals, trace writes and cleanup.
Eight relevant CPL/provider/web/test files were byte-identical to accepted
NV05 `f994ca442891bd727223b146ea86f6b7bd7f9456`.

Under a bounded local I/O workload, the unchanged test raised `WAIT_TIMEOUT`
while the run was still in `REVIEWING_3`, writing trace evidence. `run.done`
had not been set; this was not a wait for post-completion worker cleanup.
The same four-writer workload with fresh scratch on a private tmpfs completed
the run in approximately 0.10 seconds, preserving the original five-second
wait, actual HTTP requests, trace writes, `fsync` calls and all assertions.

The diagnosis establishes a reproducible storage interaction. The original
September 15 failure did not include per-phase timing, so its exact transient
device load cannot be reconstructed from that old traceback alone.

## Acceptance harness repair

Use a new network-isolated namespace and a private tmpfs for disposable
`TMPDIR` contents. In the existing bwrap harness, replace the physical scratch
bind mount with `--tmpfs <scratch-path>`. Keep source and interpreter read-only
and keep test results, logs and required retained state on the report drive.
Child processes share this namespace, allowing process-restart tests to use
the same temporary state during the run.

The timeout, nonce checks, same-plan checks and production durability code
are unchanged. No `fsync` is mocked or removed. This is functional acceptance;
tmpfs results do not certify power-loss durability or live CockroachDB.

`tests/test_cpl_wait_contract.py` additionally verifies that both completion
signals are necessary, one finite budget covers completion plus cleanup,
an exhausted budget cannot restart, and a missing signal raises `WAIT_TIMEOUT`.
The asynchronous check uses event synchronization and finite thread joins;
there are no arbitrary sleeps.

Diagnostic and acceptance evidence is retained under the separate
`NV06-G06-CPL-20260916-042759` repair run. Instrumented diagnostics are distinct
from the uninstrumented complete G06 gate. NV07 requires a later operator
instruction even if this gate passes.
