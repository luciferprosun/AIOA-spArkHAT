# Day 5 — Scoped Instance Inspection

`inspect_instance` is the first canonical `AUTO`/`READ_ONLY` CloudOps tool. Its application scope is one configured `SANDBOX_INSTANCE_ID` in `eu-central-1`, proven by the configured `SANDBOX_TAG_KEY` and `SANDBOX_TAG_VALUE`. Production configuration fails closed when the target is missing, malformed, in another region, absent from `DescribeInstances`, or lacks exactly one matching tag.

The provider adapter always calls `ec2:DescribeInstances` with `InstanceIds=[configured_instance_id]`; it exposes no account-wide enumeration or mutation method. Raw boto3 responses, owner metadata, credentials, user data, console output, and unrelated tags are not part of the public contract.

The Strands tool returns a Pydantic `ControlResult[InstanceInspection]`. Success contains normalized evidence and UUIDv7 `run_id`, `trace_id`, and `correlation_id`; failures retain explicit validation, policy-denial, ambiguous-evidence, or dependency-unavailable categories. Model-supplied extra scope fields cannot enter the tool schema.

No AWS resource was created, updated, deleted, tagged, started, stopped, or otherwise mutated for this checkpoint. A live read-only smoke requires an already configured and tagged sandbox target; the implementation never creates one as a workaround.
