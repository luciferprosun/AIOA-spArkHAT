# Linux installation and controlled release

Python 3.11+ is required. Use one complete source checkout at a reviewed release SHA. Native host deployment needs existing OS authorization, qualified TLS and the original private state/identity. An installed wheel by itself is not proof of a production Native deployment.

## Reproducible local evaluation

From a fresh checkout, prepare an isolated environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[native,nonzero]'
.venv/bin/python -B -m unittest discover -s tests -p 'test_native_advisory.py'
node --test tests/mobile_chat.test.cjs tests/mobile_devices.test.cjs
```

These tests use explicitly synthetic owner/provider fixtures and temporary state. They do not call Muse, connect Gmail or write GitHub. Native's `native` extra declares the crypto and YAML versions already used by project CI. A full source checkout remains necessary for source-capsule checks and qualified Native launcher behavior.

For the existing local demonstration profile, on a host with its required Linux sandbox dependencies:

```bash
.venv/bin/python -B -m runtime.webapp --unified-offline --host 127.0.0.1 --port 0
```

It prints a loopback URL and uses explicit fixture admission. Its supported recipe can create local fixture files only after exact review. This is not a production Muse session or evidence of Native worker qualification. The production Native endpoint remains `127.0.0.1:4317` behind its existing qualified HTTPS delivery path.

## Existing production profile

Do not point a fresh/old checkout at the owner's production state just to test it. The launcher refuses a source/capsule mismatch, missing history, altered host identity, uncertain startup or another process holding the runtime lock. It does not create replacement SQLite or TLS state to bypass a failed check.

`runtime.mobile_gateway.desktop.launcher_files(checkout, state_dir, origin=..., direct_chat=..., python_executable=...)` creates **templates only**. Supply the exact qualified HTTPS origin, existing state directory and installed Python interpreter. There is no personal-hostname default. Direct chat is an explicit preference; the function installs nothing and does not start a process or model call.

Before an approved release: identify the exact CI-tested source SHA, confirm no active effect worker, capture a verified consistent state backup, preserve signer/TLS/pairing and UNKNOWN, review policy compatibility, then obtain the owner's separate deployment approval. Replace the launcher/source only in that controlled release. Do not run two Native hosts against the same state.

After approval and deployment, check source/capsule, process/port, local admission, Overview/chat session projection, read-only tool receipt and audit. Paid/live effect tests need their own exact approvals. Keep the known-good checkout and state recovery materials until acceptance; see [rollback](ROLLBACK_AND_RECOVERY.md).
