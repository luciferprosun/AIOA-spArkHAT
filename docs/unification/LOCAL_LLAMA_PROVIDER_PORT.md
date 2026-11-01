# Optional Local LLaMA port — design only

The only model selector and invocation evidence remain in the existing provider
catalog/MissionService. No phone runtime, model weights, NDK, GGUF or llama.cpp
have been installed or invoked.

A future `LocalProviderMessageV1` must contain provider/model identity, exact
task and context digests, source SHA, device/session, nonce, expiry, prompt/input
hashes and resource limits. Its signed response must bind the same request,
tool_call_id, schema and result digest, with `authority=ADVISORY_ONLY`.

The existing mobile wire authenticates transport, not owner approval. Linux Core
must independently admit the principal and approve each exact bounded operation.
Model output cannot set approval, cost permission, native execution or receipts.
No automatic fallback from Muse/Nebius to a phone model is permitted.

Status: DESIGN_ONLY_NO_INFERENCE. Production owner, mobile TLS, physical device
performance, model license and inference provenance are unverified future gates.
