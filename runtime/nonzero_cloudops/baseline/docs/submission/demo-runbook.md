# AIOA Non-Zero CloudOps — Portable Local Jury Demo Runbook

Status: `PORTABLE_B4_HARDENED`; historical Phase 3 status `DEPLOYMENT_READY_LOCAL_RC`;
`MOCK/OFFLINE`; not deployed or live verified.

## Fast executable proof

From the repository root after the documented install, run the single jury path:

```bash
.venv/bin/python scripts/phase3/run_jury_demo.py
```

The command executes the complete story against fresh local state and prints a machine-readable
receipt. It must report all of the following:

- mode `MOCK_OFFLINE_NEVER_LIVE` and `within_target: true`;
- approved `RELEASE_ELASTIC_IP` ending in `SUCCESS_WITH_EVIDENCE` with exactly one protected mock
  mutation and an independent verification hash;
- denied `REVOKE_PUBLIC_INGRESS` ending in `DENIED_BY_HUMAN`, zero mock mutations, and no receipt;
- persisted `AWAITING_APPROVAL` recovered after a runtime restart;
- conflicting approval replay rejected with mutation delta zero;
- terminal restart reconciled without a second mutation;
- invalid identity, missing approval, resource-binding mismatch, invalid model access, and invalid
  verification evidence all fail closed; and
- zero provider calls, external network connections, AWS mutations, and live receipts.

The observed local execution is comfortably below five minutes; the exact measured duration is in
each receipt and is rechecked by the final Phase 3 gate.

For two short standalone views of the primary decision outcomes:

```bash
.venv/bin/python scripts/run_local_hitl_demo.py \
  --scenario elastic-ip \
  --decision approved
.venv/bin/python scripts/run_local_hitl_demo.py \
  --scenario security-group \
  --decision denied
```

Both commands explicitly label their output `MOCK_OFFLINE_NEVER_LIVE`. The approve path must show
`SUCCESS_WITH_EVIDENCE`, one mock mutation, pending-approval restart recovery, replay rejection,
terminal reconciliation, and zero network/AWS activity. The deny path must show `DENIED_BY_HUMAN`,
zero mock mutations, no receipt or verification hash, and the same zero network/AWS activity.

## Five-minute jury narrative

1. State the problem: a useful remediation agent must not silently acquire authority or equate a
   provider acknowledgement with success.
2. Run `scripts/phase3/run_jury_demo.py` and point to `MOCK_OFFLINE_NEVER_LIVE` before discussing
   results.
3. Show read/query evidence and the exact inert EIP release proposal. Explain that
   `PLAN_AND_CONFIRM` halts at durable `AWAITING_APPROVAL` and that a restart preserves the halt.
4. Show the exact human approval, one protected mock mutation, independent read-back hash, and
   `SUCCESS_WITH_EVIDENCE`.
5. Show the conflicting replay rejection and the restart reconciliation: both have mutation delta
   zero.
6. Show the Security Group denial: `DENIED_BY_HUMAN`, zero mutation, no execution receipt.
7. Show the five fail-closed probes and close on the explicit counts: network `0`, AWS mutations `0`,
   live receipts `0`.

## Primary B3 judge experience

1. Start `.venv/bin/python scripts/run_local_hitl_api.py --open-browser`.
2. Confirm `DEMO SANDBOX`, `PORTABLE / MOCK`, `STRANDS`, zero real-cloud writes, and zero external
   network calls. The server refuses public binding; the fragment-only token bootstrap is removed
   immediately after exchange for an `HttpOnly` loopback session.
3. Choose **Release an unattached Elastic IP**. Show the evidence-bound
   `PLAN_AND_CONFIRM` proposal, expiry, hashes, and `authorizes_execution: false`.
4. Review and approve its exact challenge, then explicitly execute. Show the independent
   verification and `SUCCESS_WITH_EVIDENCE`.
5. Select **Test replay protection** and show reconciliation rather than a second action.
6. Start **Deny a public-ingress change**, request its challenge, and deny it. Show
   `DENIED_BY_HUMAN` without execution evidence.

The UI is the human-facing product demonstration. The CLI jury receipt remains the deterministic,
automated proof. Do not use a private/public tunnel or change the loopback bind during this phase.

## Honest narration

Say “AWS-shaped deterministic local inventory,” “protected mock mutation,” and
“reliability-hardened portable local candidate.” Do not say live AWS deployment, effective IAM proof,
Bedrock invocation, production availability, or real EC2 change. Local tests prove control-flow and
contract properties; they do not prove an external account or deployed service.

## Verification before recording

Run only from a clean committed tree. The final all-in-one gate is:

```bash
.venv/bin/python scripts/run_b4_hardening_gate.py
```

This B4 gate does not replace the complete project regression. The retained Phase 3 all-in-one gate
can also be run against the exact clean head:

```bash
HEAD_SHA="$(git rev-parse HEAD)"
.venv/bin/python scripts/phase3/run_local_gate.py --expected-head "$HEAD_SHA"
```

For a quick pre-recording check that does not replace the final gate:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python scripts/phase3/scan_secrets.py
.venv/bin/python scripts/phase3/run_post_deploy_verifier.py --check
.venv/bin/python scripts/phase3/run_jury_demo.py
```

Use fresh generated local state for each recording attempt. Do not place tokens, credentials,
account IDs, private host paths, raw prompts, or provider responses in screenshots or submission
artifacts.
