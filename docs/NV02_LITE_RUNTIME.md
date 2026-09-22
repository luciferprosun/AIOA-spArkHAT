# NV-02: opt-in read-only LITE runtime

`runtime.main.create_runtime(lite_profile=..., mission_context=..., lite_bindings=...)`
constructs the existing `AgentRuntime`. LITE uses its inspection guard to leave
all legacy execution, approval, Memory Patch, NonZero and CPL endpoints closed.
No second application, model manager, authority store or domain memory is added.
The legacy factory and NV-01 diagnostic profile retain their existing defaults.

## Composition and state ownership

| Path | State owner and explicit configuration | Fail-closed reason | Contract evidence |
| --- | --- | --- | --- |
| `main.create_runtime` → `LiteProfile` | Core injects existing `MissionContext`/`OwnerScope`; frozen version/revision/digest | `OWNER_SCOPE_MISMATCH`, `LITE_READONLY_REQUIRED` | N201, N202, N217 |
| `LiteScheduler` (`SchedulerPort.describe`) | `AgentRuntime`; Core supplies one persistent state root per deployment; lease spans watch revisions | `SCHEDULER_ALREADY_OWNED`, `SCHEDULER_BUSY` | N203, N206, N207 |
| `FileObservationProbe` (`ObservationPort`) | Core binds an explicit read-only file to a registered source ID; manifest contains no filesystem path | `OBSERVATION_UNAVAILABLE`, `STALE_QUEUE_ITEM` | N204, N205, stale/input tests |
| `LiteJournal.reserve` (budget gate) | Operational SQLite journal, `synchronous=FULL`; immutable `LiteBudget` | `BUDGET_EXHAUSTED`, `BUDGET_JOURNAL_FULL`, `RECONCILE_READONLY_REQUIRED` | N211, N212, N215, N216 |
| `NvidiaProvider` (`ProviderPort`) | Fixed NVIDIA TLS endpoint/model; host supplies secret, transport, clock; immutable request policy | Typed timeout, rate limit, model/schema/transport errors | N209, N210 live evidence, N213, N214 |
| `LiteJournal.record` | Bounded operational evidence, never a domain truth or approval record | Storage errors halt the caller; a durable in-flight marker forces reconciliation | Reserve-before-transport and crash tests |

All instances for a Core deployment **must share the same `state_root`**.
The root is trusted host configuration, never read from model/manifest data.
Moving/copying that root creates a different deployment and must not be used to
reset budgets or to start another owner for the same watch. The lease is local
to this host/state namespace, not a distributed coordinator.

## Manifest and CLI

The profile ID is `aioa-lite-agent-v1`, version 1. Unknown/duplicate JSON fields,
non-finite numbers, wrong numeric types and writable modes fail validation.
Configuration is immutable. A changed digest needs a strictly newer revision;
revisions preserve reservations, counters and watch identity. An uncertain watch
cannot be reconfigured into an automatic replay.

See `tests/fixtures/nv02_lite.json` and `nv02_observation.json` for explicit
synthetic inputs. Ownership flags are Core operator configuration; the profile
must match them. These synthetic IDs confer no authority over real resources.

```sh
aioa-sparkhat lite doctor --manifest tests/fixtures/nv02_lite.json \
  --tenant nv02-fixture --owner operator --space readonly-demo --slot lite \
  --source-id local-synthetic-observation --state-root /explicit/persistent/state --json
aioa-sparkhat lite watch --manifest tests/fixtures/nv02_lite.json \
  --tenant nv02-fixture --owner operator --space readonly-demo --slot lite \
  --source-id local-synthetic-observation --source-file tests/fixtures/nv02_observation.json \
  --state-root /explicit/persistent/state --json
```

`status` uses the same arguments as `doctor`, reads the persisted state without
acquiring the writer lease, and reports whether its digest matches the manifest.
Doctor/status never start a scheduler or open domain services. `watch` handles
SIGTERM/SIGINT cooperatively, persists STOPPED, and releases the lease.
For real CLI inference set the existing `NVIDIA_API_KEY` environment mechanism;
the program reports only `key_source=ENV` and a presence boolean. A trusted
composition can inject an existing protected secret-store loader instead.

## Cheap observation and recovery

The fixture JSON has exactly `source_revision`, `health` (OK/UNCERTAIN/DOWN),
and bounded string `value`. Only health/value contribute to its content digest.
The initial healthy snapshot establishes a baseline. Ten identical fresh probes
and revision-only changes produce zero inference. A material change queues one
request; explicit uncertainty and an opt-in interpretation deadline are the
other admitted triggers. This is ordinary change gating, not measured DVM saving.

States: IDLE → DUE → PROBING → WAIT for stable observations; material input
passes CHANGE_DETECTED → INFERENCE_QUEUED → INFERENCE_RUNNING → SETTLED.
Full queues report BACKPRESSURE; dependency failures report DEGRADED. Stale
queue items are dropped with an explicit reason. Shutdown records STOPPING and
STOPPED. Restart during queued/running/probing work records
RECONCILE_READONLY_REQUIRED and never replays it. The requirement survives
subsequent clean restarts. NV-02 intentionally supplies no automatic clearing
of UNKNOWN reservations; accounting/reconciliation needs an operator decision.
Do not delete journals or change watch IDs to defeat this condition.

## Budget and provider limits

Default policy is visible in doctor/status: 4 attempt reservations per rolling
hour per watch, 32768 conservative proxy units per hour, one active inference,
queue depth 2, one retry, 2 seconds between retries, 256 output tokens, 4096
serialized request bytes, 16384 response bytes, and 30-second request deadline.
The request-byte bound includes system instructions and JSON framing. Units
are request UTF-8 bytes plus maximum output tokens, not a USD price estimate.
Known usage is recorded; the conservative larger value remains charged.

Every attempt commits RESERVED before entering transport. Valid replies become
COMMITTED. Explicit rejections (including 429) become RELEASED but still consume
an hourly attempt slot. Only 429 may retry, with the configured delay and limit.
Timeout, connection loss, 5xx, pending/redirect responses, truncation, invalid
JSON/schema and model mismatch retain UNKNOWN and block further inference.
The provider never falls back to another model or service. Error bodies/headers
are discarded. Responses allow only a bounded summary and needs_attention;
tool calls, executable fields and policy changes fail closed.

The journal retains at most 256 evidence rows by default (with a lifetime event
counter), and at most 1024 reservations. At the reservation cap it stops new
inference instead of silently deleting accounting. Keep/rotate an audited copy
under operator control for longer deployments. Local disk failure propagates
and stops the caller; the pre-transport marker makes restart conservative.

NVIDIA documentation: [Nemotron 3.5 Lightning inference API](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-5-lightning-30b-a3b-infer).
The NV-02 live acceptance used this same product path with 128 output tokens,
one attempt per watch and no automatic retry. One 30-second call timed out and
remains UNKNOWN. A separately reviewed synthetic diagnostic with a 120-second
policy returned valid JSON in about 36 seconds. Both attempts are retained in
the external phase evidence. Hosted latency is not a local-loop benchmark.

## Deliberate limits of this phase

CadencePolicyPort and SalienceHintPort accept optional shadow signals; outputs
cannot alter scheduling, budget, ownership or truth status. Memory/CPL/DVM and
pheromones remain OFF/SHADOW, AUTO is DISABLED, and domain mutation count is zero.
No live memory integration, domain effect, OpenClaw/NemoClaw installation,
production rollout, local model or NV-03 implementation is included.
Gmail scheduling remains an external development controller, not this product
scheduler. Acceptance proves a read-only loop and provider path, not 24/7 uptime.
