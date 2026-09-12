# Phase 3 Post-Deployment Verification Contract

Status: complete offline fixture verifier; future live mode is disabled by default and has no shipped AWS adapter.

## Ordered chain

1. `AUTHORIZED_IDENTITY`
2. `ACCOUNT_REGION_MATCH`
3. `API_HEALTH`
4. `AGENT_REQUEST`
5. `DURABLE_PROVENANCE`
6. `HITL_PAUSE`
7. `EXPLICIT_DECISION`
8. `APPROVED_REMEDIATION`
9. `INDEPENDENT_EVIDENCE`
10. `REPLAY_REJECTION`
11. `RECOVERY_RECONCILIATION`

The offline chain invokes the loopback application's handler directly, so it exercises the strict API boundary without opening a socket. Durable local JSON stands in for the same repository contract intended for DynamoDB; the receipt labels it local and does not claim a deployed table. One approved protected mock mutation is independently read back, a conflicting replay is rejected, and a fresh runtime reconciles the persisted result without another mutation.

## Required fail-closed probes

- `INVALID_IDENTITY`
- `MISSING_APPROVAL`
- `RESOURCE_BINDING_MISMATCH`
- `MODEL_ACCESS_INVALID`
- `VERIFICATION_EVIDENCE_INVALID`

The deny path is separate and must end `DENIED_BY_HUMAN` with no receipt, no independent verification claim, and zero mutation. Every probe records zero AWS mutations and zero additional mock mutations.

## Live boundary

Selecting `LIVE_AWS` returns `LIVE_POST_DEPLOY_VERIFIER_DISABLED` before adapter use. A future authorized implementation must preserve the same order, bind identity/account/region and deployment provenance, use separate explicit approval for remediation, and emit actual live evidence. A local PASS can never set `live_receipts` above zero.
