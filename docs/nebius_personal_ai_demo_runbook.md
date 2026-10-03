# Nebius Personal AI — operator recording runbook

The default demo is **Provider: FIXTURE / Effect target: FIXTURE**. It needs no
cloud credentials or paid inference and uses the existing runtime, private
memory, CPL, verification, exact approval and ServiceGuard paths. Nothing is
approved or executed merely by starting the server.

## 1. Verify the checkout

```bash
cd /media/l/LSC_DATA1/NVIDIA_NEBIUS/AIOA-spArkHAT-nebius
test "$(git branch --show-current)" = nebius-personal-ai
test "$(git rev-parse main)" = d26266e54ee940d7ada30aa02783dc697618a72c
test "$(git rev-parse origin/main)" = d26266e54ee940d7ada30aa02783dc697618a72c
git status --short
```

Use Python 3 and the repository's existing runtime dependencies. The startup
script checks its dependencies and refuses `main`. A port conflict should be
resolved by stopping the previous demo or explicitly selecting another port.

## 2. Start the fixture demo with one command

```bash
./scripts/start_nebius_personal_ai_demo.sh
```

The default is `--fixture`. Read the printed banner and private state directory.
The server binds loopback only. Open:

```text
http://127.0.0.1:4311
```

For a repeatable recording with an explicit private directory, use:

```bash
DEMO_STATE_DIR=$(mktemp -d /tmp/aioa-nebius-demo.XXXXXX)
chmod 700 "$DEMO_STATE_DIR"
./scripts/start_nebius_personal_ai_demo.sh --fixture --state-dir "$DEMO_STATE_DIR"
```

Keep this terminal open. The state directory is local private demo data; do not
publish its memory store. A fresh directory gives a fresh scenario. Reusing a
completed operation should demonstrate replay blocking rather than reset its
receipt or conceal earlier effects.

## 3. Prepare the maintenance scenario

In the Operator Console's Personal AI panel, press **Prepare Maintenance Demo**.

Confirm the displayed provider and effect target modes are both `FIXTURE`, the
exact model is `nvidia/Nemotron-3_5-Lightning`, and model authority is
`ADVISORY_ONLY`. Preparation retrieves the private HAT constraint, demonstrates
the existing CPL's synthetic fixture 1+3+1 review, and independently verifies
the typed maintenance proposal. That synthetic CPL task is separate from the
maintenance advisory; it is not evidence that CPL verified the action.
The flow must stop at `APPROVAL_REQUIRED`.

Record:

- memory retrieved and HAT reference count, without opening private text;
- actual CPL state, which is advisory rather than proof;
- independent typed-proposal verification;
- Verified Delta state `ZERO_WRITE`;
- human approval `REQUIRED`; and
- effect count **0** and duplicate effect count **0**.

`ZERO_WRITE` means no canonical memory delta was admitted. Retrieving an
owner's preference does not turn it into canonical truth. It does not prevent
a separately verified typed action from being presented for human approval.

## 4. Approve the exact action

Review the displayed proposal identity and target. Press **Approve Exact Action**.
Confirm `APPROVED` and effect count **0**. Approval records consent for this
proposal; it does not execute the target effect.

Do not combine this with the execution click in the recording.

## 5. Execute and inspect evidence

Press **Execute / Resume**. Confirm ServiceGuard handled the effect boundary,
the receipt digest is present and independent readback is verified.

The state can progress from `EXECUTED` to `RECONCILED` within the same response
when receipt and readback agree. The timeline preserves the executed stage.
The target apply count must be **1**, duplicate effects **0**. A fixture effect
does not prove live Nebius Serverless execution.

If an acknowledgement is `UNKNOWN`, do not treat it as failure or success.
Resume only to reconcile existing receipt/readback evidence; do not create a
new operation to bypass uncertainty.

## 6. Prove restart reconciliation

Press **Simulate Restart / Reconcile**. This recreates the demo runtime and
service over their durable private files and reconciles the existing operation.
Confirm `RECONCILED`, receipt/readback evidence retained, apply count **1** and
duplicate count **0**.

For an additional real process restart, stop the server with **Ctrl+C**, then
restart with the same private directory:

```bash
./scripts/start_nebius_personal_ai_demo.sh --fixture --state-dir "$DEMO_STATE_DIR"
```

Open the same URL and inspect the existing scenario. Startup does not approve
or apply an effect. Do not delete state or receipts to manufacture a fresh
result.

## 7. Prove replay blocking

Press **Replay Same Operation**. Confirm `REPLAY_BLOCKED`, apply count **1** and
duplicate effects **0**. Replay reports durable evidence of the existing
operation; it must not make a second apply call.

Expected recording sequence:

```text
ADVISORY → VERIFIED → ZERO_WRITE → APPROVAL_REQUIRED
→ APPROVED → EXECUTED → RECONCILED → REPLAY_BLOCKED
```

`VERIFIED` identifies the independently checked typed proposal; `ZERO_WRITE`
identifies the canonical memory delta. These are separate scopes.

## 8. Run the automated fixture proof and inspect receipts

Use a separate fresh private directory for the self-test; it must not alter the
recording operation:

```bash
DEMO_TEST_DIR=$(mktemp -d /tmp/aioa-nebius-selftest.XXXXXX)
chmod 700 "$DEMO_TEST_DIR"
python3 -B -m runtime.personal_ai_demo_launcher \
  --fixture --self-test --state-dir "$DEMO_TEST_DIR"
python3 -m json.tool "$DEMO_TEST_DIR/demo-self-test.json"
```

The self-test provides redacted machine-readable evidence for preparation,
approval with zero effects, one execution, independent readback, restart
reconciliation and blocked replay. It must report one apply and zero duplicates,
`ADVISORY_ONLY`, memory execution authority false and fallback false. Private
memory is persisted in its private store; private text must not be copied into
public status, diagnostic receipts or evidence records.

Inspect the committed final evidence and live receipts without opening the
private memory store:

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path("evidence/personal_ai_vertical_slice")
for path in sorted(root.glob("manifest_final_*.json")):
    print(path)
    print(json.dumps(json.loads(path.read_text()), indent=2, sort_keys=True))
PY
```

Inspect the preserved live receipts and their hashes/modes:

```bash
python3 - <<'PY'
import hashlib
import json
import stat
from pathlib import Path

for path in sorted(Path("evidence/cloud_activation").glob("live_smoke_*.json")):
    raw = path.read_bytes()
    print(path, "sha256=" + hashlib.sha256(raw).hexdigest(),
          "mode=" + oct(stat.S_IMODE(path.stat().st_mode)))
    print(json.dumps(json.loads(raw), indent=2, sort_keys=True))
PY
```

Match the latest Prompt 03 receipt to the final manifest. Live receipts must be
`0600` and contain only sanitized allowlisted metadata. Do not display
`native-fixture.json` under the demo's `memory` directory: it is the private
fixture persistence store, not a public evidence artifact.

## 9. Optional live-provider composition

```bash
./scripts/start_nebius_personal_ai_demo.sh --live-provider
```

The banner and UI must show **Provider: LIVE / Effect target: FIXTURE**.
Startup performs no paid inference. This mode is a configured composition, not
evidence of successful live inference. Under Prompt 03, the demo's paid Prepare
path remains blocked because the only inference authorization is the single
bounded diagnostic probe. Do not use a demo click to spend that authorization
again. Additional live advisory execution requires separate explicit budget
authorization and valid cost admission; do not add a bypass or silent fixture
fallback.

Supply any required `NEBIUS_API_KEY` through the existing private environment
mechanism. Never paste its value into a command, screenshot, receipt or source
file. Missing credentials are a blocker for live mode, not for the fixture.
This runbook does not authorize more probes, credits, Serverless deployment or
recurring resources.

## 10. Stop safely

In the foreground launcher terminal press **Ctrl+C** and wait for shutdown.
The server releases its runtime resources. Keep the private state directory
for restart proof and inspect the redacted evidence before sharing it. No cloud
resource needs stopping because this demo does not create one.

## Recording claims and current limits

Use [the 165-second video script](nebius_personal_ai_video_script_180s.md).
The final Prompt 03 manifest is authoritative for test counts and blockers.
The single additional live smoke passed with exact Lightning identity and
`finish_reason=stop`; inspect
`evidence/cloud_activation/live_smoke_20261003T130702Z.json`. Earlier 32- and
256-token attempts failed with `INCOMPLETE_COMPLETION` and remain preserved.
The successful smoke does not change the recording's fixture provider/target
labels or authorize further paid calls. Nebius Serverless remains
`BLOCKED_BY_CREDENTIALS`. The recording demonstrates the local fixture
authority/recovery flow, with private HAT context and explicit human control.
