# Q15: existing offline S1, cloud remains gated

AIOA spArkHAT uses one Core and its existing CoreDualGovernor. Do not create
another queue, budget store, signer or execution authority.

The existing runtime/mission/job_contracts.py JobEnvelope binds owner scope,
task/request digest, exact model, deadline and paired money/risk ceilings.
runtime/mission/jobs.py persists immutable native OPERATION/AUDIT/OUTBOX records
through the same governor transaction port. CLAIM/START, lease renewal, fencing,
expired-lease takeover, duplicate result and UNKNOWN are tested in
 tests/test_advisory_jobs.py. A START receipt permits one synthetic fixture step;
it never authorizes a real provider request or ServiceGuard effect. START after
restart returns fixture_step_now=false; an ambiguous takeover retains UNKNOWN
and its full governor exposure. A recorded DONE remains UNVERIFIED advice.

Local acceptance command (trusted isolated host, no secrets or external egress):

    PYTHONPATH=.:runtime:tests python3 -B -m unittest test_advisory_jobs test_dual_governor -v

Run this through the queue host acceptance wrapper, with private receipts outside
source. Test factory storage is repository-durable JSON, not CockroachDB/cloud.
A passing synthetic restart is not a running long-lived cloud worker.

## Deployment decision for the operator

Token Factory inference alone supplies no always-running worker host. AI Cloud
would introduce a separate compute/IAM/credit/billing/terms gate. Choose neither
from this queue. Before any future deployment, review an exact SHA-bound plan
covering service identity, secret injection on the server only, private network,
read-only advisory worker, request/input/output/deadline/rate/cost/risk caps,
leases/epochs, durable governor/journal/receipt backend and independent readback.
Record existing resources and current prices; unknown resource/balance is BLOCKED.
No credit redemption, billing activation, terms, production keys or provisioning
is authorized. Teardown must target only resources actually recorded by a future
separately authorized deployment; this document is not deletion permission.

G9 remains BLOCKED_HUMAN: no deployment, fresh authorized real inference or cloud
restart receipt was observed. G2/G3/G4/G6/G7 full runtime integration is not
promoted by this skeleton. Q16/S2 remains BLOCKED_DEPENDENCY until real G9 proof.
PUBLIC_JUDGE_DEMO_EXECUTION=HUMAN_ONLY; VIDEO_RECORD_UPLOAD=HUMAN_ONLY.
