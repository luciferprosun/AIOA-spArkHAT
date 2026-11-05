# Local critical prompt preview

The existing Mission Control **Critical Prompt Loop** page has a manual **Prepare local preview** action. It frames the supplied prompt for critical review; it neither calls a model nor starts the canonical five-call CPL. The existing chat input and Send flow are untouched.

## Source and integration

Five pure files were selectively recovered from `8f9b14b7ea0f7d5a963244c62d27d3f3dcbeb26c:runtime/cpt/` into `runtime/critical_loop/cpt/`: sanitizer, templates, schema, transformer and package initializer. The implementation is retained with import relocation and provenance headers. The historical JSONL audit writer, web composer, Orchestra provider/session stack and boolean provider approval helper are excluded.

The only new operation is `critic_transform_preview` on the existing private Native operator port:

```json
{"op":"critic_transform_preview","request_id":"cccccccccccccccccccccccccccccccc","payload":{"prompt":"Review the assumptions in this proposal."}}
```

It uses existing kernel peer identity, owner admission, source capsule, TLS qualification and the Core transaction/audit. It creates no new authority, database, server, provider or credential configuration. All new source dependencies participate in the existing capsule. The input is bounded to 8,000 UTF-8 bytes and output to 16,000 bytes. Unknown fields and authority claims are refused. Unusable text produces a signed `INPUT_REJECTED` result.

## Privacy, evidence and replay

The response contains `data`, `receipt`, `signature` and an ephemeral `preview`. Only the first three are stored in Core. Neither original nor transformed prompt text enters this operation's durable record, audit or outbox. Common secret-shaped text is redacted after normalization; this is best effort, not a comprehensive secret detector. The input field and output are cleared when the operator locks or leaves the page.

`input_sha256` hashes the exact supplied UTF-8 text. `review_input_sha256` hashes the normalized, redacted review input. This deliberately corrects the historical record's ambiguous `original_prompt_hash` label. The transformed text hash and byte count belong to the metadata covered by the signed receipt. Browser checks validate the request ID, status, metadata digest, text digest, byte count and receipt/signature shape before display. These are content-binding checks on the authenticated Native channel, **not an independent browser signature trust root**. Python acceptance independently verifies the host signature.

Repeating the same request ID and exact input reconstructs only the pure local preview and returns the existing receipt without another audit append. Changed input, source capsule or Core instance cannot reuse it. A lost commit acknowledgement is propagated; no automatic retry occurs. Explicit replay may read the committed receipt and reconstruct its text. The browser never sends the resulting prompt to chat automatically and renders it using `textContent`.

## Qualification

The original pure source passed 23 tests in an isolated filesystem/network namespace. Candidate tests cover real temporary Native/Core/SQLite admission, digest-only persistence, replay, lost acknowledgement, source drift, denial of forged authority, source sealing, installed wheel/sdist behavior and isolated headless Chrome. Current CI, including preserved chat/GitHub/Android contracts, must pass on the review commit before code merge. These fixture tests are not a production deployment, paid Muse call or GitHub WRITE proof.
