# One paid WorkerPort qualification

The prepared B/C inputs and fixed estimates are in [B_C_OWNER_PAYLOADS.json](B_C_OWNER_PAYLOADS.json). No paid call, repair, installation-token mint or target mutation was performed while developing this candidate. The tests use disposable keys, synthetic account statements and a loopback provider or an emulated transport.

## Operator prerequisites

Use the existing qualified owner, source-pinned Native state and existing Core/governor. The v1 host-composition profile for this single campaign is `OWNED_WORKER_MODEL_B_V1`. It adds the single model binding for this qualification. The old offline proof profile excludes all three worker operations. The required operator state includes a real TLS/owner session, current accepted suite evidence for the executing checkout, an active unfenced lifecycle, money and risk headroom and no unresolved owner liabilities. Never initialize another scope to evade a liability.

The established host process must already have the configured `NEBIUS_API_KEY` for the approved account. Only that variable is read. The model and HTTPS endpoint are fixed. Keep the provider credential, account evidence and operator socket private. A mode-0600 credential file on the laptop alone does not establish that this process can use the account.

Within the existing owner state, create a private `worker-model/` directory (0700). Place a redacted copy of current account evidence in `account-review.bin` (0600, at most 65536 bytes). Check that the account can actually spend the stated amount and the effective rate includes every billable charge. The admitted owner attests that inspection. Core verifies the file hash and the limits. The public price page alone cannot establish an account balance.

Write `billing.json` (0600) with the following exact fields. Substitute actual verified values. `reviewed_at` is UTC Unix seconds, at most 24 hours old. Both rates are in nanoUSD per token. A fixed fee, surcharge, expired quote or insufficient balance blocks the attempt.

```json
{
  "schema": "aioa.worker-account-review.v1",
  "provider": "nebius",
  "model": "nvidia/Nemotron-3_5-Lightning",
  "currency": "USD",
  "source_url": "https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference",
  "input_nano_per_token": 60,
  "output_nano_per_token": 240,
  "additional_fees": false,
  "available_nano_usd": "<integer from account evidence>",
  "reviewed_at": "<current verified timestamp as an integer>",
  "account_evidence_sha256": "<SHA-256 of account-review.bin>"
}
```

The source-specific TestGate evidence must exist in the canonical Git directory at `aioa/accepted-test-evidence.json` and pass `RepositorySourceStateReader`. A prior SHA's passing checks cannot grant this call. The source tree, full test result digest, local adapter bytes, request body, session, task, workspace, Core epoch, owner scope, warrant and paired reservation are bound before transport. The private workspaces project the pinned LICENSE from the executing repository; the independent oracle expects exactly one newly added text file.

## One review and release

```sh
umask 077
python3 -B scripts/unification/worker_model_qualification.py prepare --state-dir "$qualified_state" > "$private_evidence/review.json"
python3 -B scripts/unification/worker_model_qualification.py approve --state-dir "$qualified_state" --review-digest "$reviewed_digest" > "$private_evidence/result.json"
python3 -B scripts/unification/worker_model_qualification.py readback --state-dir "$qualified_state" > "$private_evidence/readback.json"
```

Read the complete review before supplying its digest. The 60-second qualification window and 20-second provider limit are enforced separately. The fixed campaign nonce prevents a second paid START in this scope. The Core receipt is the host's signed observation of the API response, usage and candidate message. It identifies the provider request by digest. It is neither a provider invoice nor model authority.

The actual patch must match the permitted bytes and pass both the projected PatchSet policy and a separately observed disposable directory. The Core stores the independent readback and commits the original reservation in the same transaction. Governor accounting commits the conservative reservation of 184320 nanoUSD; the receipt reports estimated usage at the approved account rate separately. On ambiguous dispatch, missing usage or a failed oracle, use only readback. If a crash occurs before the independent evidence commits, the original intent remains UNKNOWN. There is no automatic settlement from expected content and no second inference.

## Separate #41 and C

B allows no repair. The separate #41 proposal requires an original independently failed oracle, a bounded TEST_FAIL feedback message, a different paid reservation for the repair and an independent final PatchSet validation. Preserve uncertainty without another attempt. The B entry never releases either #41 call.

For C, Actions permissions were read as enabled/all on the isolated target. The owner must establish a disabled-Actions exclusive window before any dispatch. Recheck the target ID, base, new branch absence, unchanged tree and the real installation token's narrowed scope at launch. Provenance must come from an authenticated, retained Native Muse reply and its live READ receipt; an offline proposal cannot replace either. Without such an existing reply, any extra inference needs separate authorization. The current plan provides four create-only mutations; a successful REST receipt cannot resolve a downstream Git HTTPS requirement without consumer evidence. Account for the token mint and installation/repositories proof in the 48-request and 120-second session totals in addition to the four repository mutations.
