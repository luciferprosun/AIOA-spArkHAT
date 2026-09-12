# Five-minute demo script draft

Status: local rehearsal copy only. No video has been recorded or published in B6.

## 0:00–0:35 — Stakes

“An infrastructure agent should not turn a plausible model sentence into a cloud action. AIOA is a
Non-Zero CloudOps agent: ambiguity, missing authority, replay, and unverified success are explicit
failures.”

Show the architecture diagram. Point out one Strands agent, five bounded tools, the separate human
authority plane, and independent verification.

## 0:35–1:05 — Portable setup

Show `PUBLICATION_MANIFEST.json`, `SHA256SUMS`, and the digest-pinned `Dockerfile`. Say:

“This is the sanitized local publication candidate. It needs no AWS credential or paid model. AWS
and Bedrock are optional adapters outside this reproducible path. Nothing here has been deployed or
uploaded.”

Run the checksum command and show only its success lines.

## 1:05–2:15 — Approve

Run the isolated container command from `REPRODUCIBILITY.md`. In the JSON receipt highlight:

- `status: PASS` and `provider: mock`;
- zero external network, AWS call, and AWS mutation counters;
- the exact proposal, evidence, and decision hashes;
- zero mutations before the decision;
- exactly one approved mock mutation; and
- `SUCCESS_WITH_EVIDENCE` plus an independent verification hash.

Narration: “The Strands agent can investigate and propose. Only the exact human-bound decision gives
authority. Provider acknowledgement is still not success; independent read-back closes the run.”

## 2:15–2:55 — Deny

Highlight `DENIED_BY_HUMAN`, `execution_receipt_absent: true`, and zero mutation.

Narration: “Deny is terminal. It is not an error that can be retried into execution.”

## 2:55–3:45 — Recovery and replay

Highlight pending-approval restart recovery, reconciliation, receipt-hash match, replay rejection,
and zero recovery/replay mutation deltas.

Narration: “Authority survives a restart without becoming transferable. If execution may have
happened, AIOA reconciles durable truth before considering a retry. A changed replay fails closed.”

## 3:45–4:25 — Human experience

Show the checked-in judge-console screenshots or start the loopback-only console if time permits.
State clearly that the console is authenticated, same-origin, local-only, and not a hosted public
service. Do not expose the operator token on screen.

## 4:25–5:00 — Proof and limits

Show `DEVPOST_CLAIMS_MATRIX.md`, the B5 build-complete reference, and the public privacy scan result.

Close with: “AIOA proves locally that a professional agent can remain useful while authority and
truth stay deterministic. The next step is a separately authorized live-demo phase. Today we claim
no live AWS, no production deployment, and no external publication.”

## Recording safety checklist

- Use only the sanitized candidate directory.
- Hide terminal history, host paths, profiles, account identifiers, and notification panels.
- Never display a token, cookie, credential file, browser profile, or private receipt.
- Do not call the mock action a real AWS mutation.
- Do not call local certification production readiness.
- Stop recording before any login, upload, deployment, or submission action.
