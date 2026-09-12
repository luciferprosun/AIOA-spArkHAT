# Historical Phase 1 QueryResource Experiment

> Status: preserved by the immutable `phase1-foundation-green` tag; not part of the active canonical tool surface on `main`.

The first CloudOps capability observes allocated Elastic IP addresses through only `ec2:DescribeAddresses`. It is classified `READ_ONLY` under the `AUTO` authority gate and has no remediation method.

An address is reported as unattached only when the response contains a valid address identity and no association, instance, network-interface, or private-IP relationship field. Missing, empty, malformed, or otherwise uncertain association evidence is recorded as ambiguous instead of being promoted to a finding.

Results are typed rather than exposing raw provider responses. Each finding contains only allowlisted non-secret evidence and a SHA-256 digest over canonical JSON. A completed query can be materialized as an append-only `CLOUDOPS_QUERY_COMPLETED` provenance event under the original UUIDv7 correlation ID.

The operation allowlist contains only `ec2:DescribeAddresses`. Mutation requests fail before the provider client is called. Finding a potentially unattached Elastic IP is not authorization to release it.

The active Phase 2 implementation removes EIP-specific executable code, tests, and IAM authority. It is not registered as a Strands tool. The reusable Non-Zero evidence and authority contracts remain independent of this historical experiment.

No AWS resource mutation, live AWS query, live DynamoDB write, Bedrock invocation, Strands execution, or deployment occurred in the historical implementation step.
