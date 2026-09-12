# Public-candidate reproducibility

These instructions start from the extracted sanitized candidate only. They do not require the
private development repository, AWS credentials, a paid model key, or a live service.

## Prerequisites

- Linux host with Docker or Podman and enough space for a Python 3.12 image;
- `python3` for reading the manifest;
- `sha256sum` for payload verification; and
- network access only when the digest-pinned base image or hash-pinned packages are not cached.

The certified image platform is `linux/amd64`. Other platforms are not claimed.

## 1. Verify the sanitized source

From the extracted bundle root:

```bash
sha256sum -c SHA256SUMS
python3 - <<'PY'
import json
from pathlib import Path

manifest = json.loads(Path("PUBLICATION_MANIFEST.json").read_text(encoding="utf-8"))
assert manifest["status"] == "SANITIZED_PUBLIC_CANDIDATE"
assert manifest["aws_mutations"] == 0
assert manifest["publication_actions"] == 0
print(manifest["source_ref"])
PY
```

Expected: every listed file is `OK`, all assertions pass, and the exact 40-character public-source
commit is printed. `SHA256SUMS` intentionally does not list itself.

## 2. Build the canonical container

Choose `docker` or set `ENGINE=podman` explicitly:

```bash
ENGINE="${ENGINE:-docker}"
SOURCE_REF="$(python3 -c 'import json; print(json.load(open("PUBLICATION_MANIFEST.json", encoding="utf-8"))["source_ref"])')"
"$ENGINE" build \
  --build-arg SOURCE_COMMIT="$SOURCE_REF" \
  --tag localhost/aioa-portable:b6-public \
  .
"$ENGINE" image inspect localhost/aioa-portable:b6-public >/dev/null
```

Expected: the build succeeds from `Dockerfile`, the exact digest-pinned base is selected, all runtime
packages satisfy their hashes, and the image config declares user `aioa` plus entry point
`python -m aioa_cloudops_agent.portable_server`.

## 3. Run approve, deny, recovery, and replay

```bash
"$ENGINE" run --rm \
  --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
  --cap-drop ALL --security-opt no-new-privileges \
  --entrypoint python \
  localhost/aioa-portable:b6-public \
  -m aioa_cloudops_agent.portable --output /tmp/portable-receipt.json \
  > portable-receipt.json
python3 - <<'PY'
import json
from pathlib import Path

r = json.loads(Path("portable-receipt.json").read_text(encoding="utf-8"))
a = r["nonzero_verification"]["approved_path"]
d = r["nonzero_verification"]["deny_path"]
assert r["status"] == "PASS"
assert r["external_network_connections"] == r["aws_calls"] == r["aws_mutations"] == 0
assert a["final_state"] == "SUCCESS_WITH_EVIDENCE"
assert a["mock_mutation_count"] == 1
assert a["mock_mutations_before_explicit_decision"] == 0
assert a["pending_approval_recovered_after_restart"] is True
assert a["recovery_reconciled"] is True and a["recovery_mock_mutation_count"] == 0
assert a["replay_rejected"] is True and a["replay_mutation_delta"] == 0
assert d["final_state"] == "DENIED_BY_HUMAN"
assert d["mock_mutation_count"] == 0 and d["execution_receipt_absent"] is True
print(r["receipt_sha256"])
PY
```

Expected: assertions pass and the deterministic receipt SHA-256 is printed. The output file is local
test evidence and should not be committed or published as a live receipt.

## 4. Check health and readiness

```bash
"$ENGINE" run --detach --name aioa-public-check \
  --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
  --tmpfs /var/lib/aioa:rw,nosuid,nodev,noexec,size=64m,mode=0770,uid=65532,gid=65532 \
  --cap-drop ALL --security-opt no-new-privileges \
  localhost/aioa-portable:b6-public
"$ENGINE" exec aioa-public-check python -c \
  'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2); assert r.status == 200; print(r.read().decode())'
"$ENGINE" exec aioa-public-check python -c \
  'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8765/ready", timeout=2); assert r.status == 200; print(r.read().decode())'
"$ENGINE" stop --time 10 aioa-public-check
"$ENGINE" rm aioa-public-check
```

Expected: both endpoints return HTTP 200, and the application stops gracefully.

## 5. Optional native test path

If Python 3.12 development tooling is available:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
.venv/bin/python -m pytest -q \
  tests/unit/test_portable_cli.py \
  tests/unit/test_portable_container_runtime.py \
  tests/integration/test_portable_judge_sandbox.py
```

This optional install may use package indexes. Container execution above remains the canonical B6
clean-room path.

## Rootless UID-map note

The image intentionally declares UID/GID 65532. A rootless engine configured with only one mapped
host identity may reject that user before the application starts. This is a host configuration
limitation, not permission to run the public deployment as root. The B5 evidence records a separate
exact-rootfs OCI proof for the constrained certification host.

## Truth boundary

Success here proves reproducibility of the sanitized local/offline candidate. It does not prove a
public deployment, registry upload, live AWS account binding, live Bedrock inference, real cloud
mutation, production readiness, or hackathon submission.
