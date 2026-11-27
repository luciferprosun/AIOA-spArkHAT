# Filesystem effect, watcher observation, and Native69 settlement

## Scope

This is a standalone reproduction of the paired Windows Chokidar experiment
requested in [AIOA issue #14](https://github.com/luciferprosun/AIOA-spArkHAT/issues/14#issuecomment-7211138488).
It records a physical filesystem effect separately from delivery of a watcher
event. It does not change the Native runtime, its production activation guard,
or the historical operation #69.

The original request is in [Qwen issue #17489](https://github.com/QwenLM/qwen-code/issues/17489#issuecomment-7174526550).
The comparator fix is proposed by [Qwen PR #17491](https://github.com/QwenLM/qwen-code/pull/17491),
inspected at `1a7a77bc50e7d091137915c85d329abe8e0b4bec`. That PR fixes bootstrap
watcher root admission. Its separate intermittent whole-directory deletion
problem is outside this creation-only experiment.

## Running the pair

Use Node 24 and the diagnostic directory's committed dependency lock:

```sh
cd tests/diagnostics/qwen_watcher
npm ci --ignore-scripts --no-audit --no-fund
node probe.cjs --output /absolute/path/result.json --window-ms 5000 --pairs 3 --credit LuciferSun
```

On Windows, supply a native absolute output path such as
`C:\scratch\aioa-probe\result.json`. The dedicated GitHub workflow runs on
`windows-2025` and `ubuntu-24.04` with Node `24.20.0`, Chokidar `4.0.3`, and the
same locked transitive dependency. Dependencies belong only to this standalone
diagnostic; they are not added to the Python runtime or installed package.

Each pair uses two fresh absolute temporary parents. The raw comparison runs
first and the normalized comparison second. Both keep the same basename
clause, watcher options, creation sequence, and full observation window.

The receipt separates:

1. **Effect on disk:** an independent `fs.stat` proves the exact `.qwen` child
   is absent beforehand and is a directory after creation.
2. **Watcher observation:** original callback path spellings, ignore decisions,
   `ready`, events, errors, and the intended and actual monotonic observation
   interval. Creation starts only after `ready`. Both arms retain the full
   interval, including events that arrive before `mkdir` or the following stat
   completes.
3. **AIOA evaluator:** explicitly `UNIMPLEMENTED`. This harness does not invoke
   an AIOA evaluator for Chokidar transcripts. The harness's own classification
   is not an AIOA verdict or an authorization to settle a Native operation.

The JSON receipt and adjacent raw JSONL transcript include environment and
harness identity. The workflow retains these files and console output even
when the probe fails. Windows build and the measured temporary-volume
filesystem are recorded by the runner; Node also records its native platform
and filesystem observations. Use the recorded platform, not a claim that
Windows Server is the first reporter's Windows 11 workstation.

## Predictions, not fabricated results

| Native platform | Raw root ignored | Raw child event | Normalized root ignored | Normalized child event |
| --- | --- | --- | --- | --- |
| Windows | Expected true | Expected absent within the fixed window | Expected false | Expected `addDir` |
| Linux control | Expected false | Expected `addDir` | Expected false | Expected `addDir` |

In every valid arm, separate stat evidence must show the child was created.
An unexpected event trace remains a useful result. A setup failure or incomplete
capture is reported as such and cannot be classified as the expected missing
event. In particular, `ready` alone does not prove the root was admitted.

Do not normalize the stored parent before the raw comparison, simulate Windows
with `path.win32` on Linux, end a successful arm early, count cleanup events, or
infer disk existence from `mkdir` success. Preserve the original path strings
and exact child matching in the evidence.

## Existing Native coverage

The methodological lesson is already represented in the Native regression
suite. These tests use disposable fixtures; they do not qualify different UIDs.

| Existing test | Independent facts checked |
| --- | --- |
| `RedHatCoreRecoveryTests.test_lost_ack_fresh_verifier_and_idempotent_original_core_settlement` | Exact ref bytes after producer death; actual truncated IPC response; original Core remains held without its witness; fresh verification supports one settlement and no extra CAS. |
| `RedHatCoreRecoveryTests.test_same_oid_inode_replacement_before_core_callback_stays_held` | Matching OID on a substituted inode does not settle the original operation. |
| `AuthenticatedBoundaryTests.test_crash_before_witness_stays_held_after_cold_recovery` | A physical ref without settlement-grade evidence stays UNKNOWN/HELD after restart. |
| `SequencedBoundaryTests.test_postwitness_lost_ack_settles_in_fresh_core_once` | Sequenced publication and durable evidence permit one original settlement after ACK loss. |

Sources: `tests/test_redhat_core_recovery.py`,
`tests/test_redhat_native_cas_broker.py`,
`tests/test_redhat_rh06_authenticated_boundary.py`,
`tests/test_redhat_rh07_sequence.py`, and `runtime/red_hat/verifier.py`.
The prepared Native port deliberately treats ACK as informational; its deferred
settlement test alone is not a measurement of a dropped ACK.

## Remaining Native69 implementation

The Windows comparator fix does not establish Linux authority. Native still
needs a supervisor-bound storage-access contract throughout preparation,
publication and cold readback; broker-private signing material; read-only
verification; and enforceable publication to the one approved ref under the
same STOP/CAS ordering. Actual cross-UID qualification must exercise that full
composition on the pinned Noble host.

Production remains disabled. Historical #69 remains UNKNOWN/HELD with no replay.
Neither a successful watcher probe nor a new disposable Native test supplies
missing historical evidence.
