# Container judge certification

## Supported clean-room path

Build the image from a clean checkout of the exact source commit. The build may contact only the
package indexes needed to retrieve hash-pinned dependencies; the resulting judge runs use an
engine-enforced network namespace with no interfaces beyond loopback.

```bash
SOURCE_COMMIT="$(git rev-parse HEAD)"
test -z "$(git status --porcelain)"
docker build --platform linux/amd64 \
  --build-arg APPLICATION_VERSION=0.2.0rc1 \
  --build-arg SOURCE_COMMIT="$SOURCE_COMMIT" \
  --tag aioa-portable:0.2.0rc1 .
python scripts/run_b5_container_gate.py \
  --engine docker \
  --image aioa-portable:0.2.0rc1 \
  --expected-source-commit "$SOURCE_COMMIT"
```

The gate first inspects the image identity and requires Linux/amd64, the exact source label, MIT
license label, non-root `aioa` user, and canonical server entrypoint. It then checks the configured
image user under `--cap-drop ALL`, `--security-opt no-new-privileges`, a read-only root filesystem,
a no-exec `/tmp` tmpfs, and `--network none`.

The gate executes `python -m aioa_cloudops_agent.portable` twice with `docker run --rm`. Each
invocation gets a fresh container and fresh `/tmp/aioa-workspace`; no volume, bind mount, host port,
credential, or state is shared. Both validated receipts must prove:

- approved path reaches `SUCCESS_WITH_EVIDENCE`, with zero pre-decision mutation and exactly one
  bounded mock mutation after explicit approval;
- denial reaches `DENIED_BY_HUMAN`, with no execution receipt and zero mutation;
- pending approval is recovered after restart and committed execution is reconciled without a
  second mutation;
- replay and resource-binding tamper are rejected with zero mutation delta; and
- provider network, external network, AWS calls, and AWS mutations are all zero.

The owner-only local receipt is written to `.local/b5-b6/container-judge-gate.json`. It is evidence
for the operator who ran the gate, not a live-cloud receipt and not proof of a public deployment.

## Rootless engine compatibility

Some rootless Podman installations have only a single host UID/GID mapping and cannot translate the
image's configured UID/GID 65532. This is a limitation of that local engine setup, not permission to
weaken the image. In that specific environment, the gate accepts a root-user engine override only
when it is paired with a private, image-ID/digest/source-bound OCI runtime receipt proving that the
same image actually ran as UID/GID 65532, with zero effective capabilities, `NoNewPrivs=1`, the
canonical server as PID 1, healthy/readiness responses, and a `0600` generated token.

The compatibility invocation is explicit:

```bash
python scripts/run_b5_container_gate.py \
  --engine /absolute/path/to/rootless-engine-wrapper \
  --engine-run-arg=--cgroups=disabled \
  --engine-run-arg=--log-driver=k8s-file \
  --image localhost/aioa-portable:0.2.0rc1 \
  --expected-source-commit "$SOURCE_COMMIT" \
  --user-override 0:0 \
  --skip-engine-nonroot-probe \
  --nonroot-receipt /absolute/private/path/nonroot-server-receipt.json
```

The gate rejects arbitrary extra engine arguments, so this compatibility path cannot add a host
network, privileged mode, mount, port publication, or capability. A normal Docker/Podman judge
environment must use the supported clean-room path and the image's configured user directly.

## Direct packaged command

The compatibility script and packaged module call the same implementation:

```bash
AIOA_RUNTIME_MODE=portable \
AIOA_MODEL_PROVIDER=mock \
AIOA_AWS_INTEGRATION_ENABLED=false \
python -m aioa_cloudops_agent.portable \
  --workspace .local/portable/workspace-001 \
  --output .local/portable/receipt-001.json
```

The reviewed offline deployment contract and synthetic verifier fixture are package data. The
command therefore works from an installed wheel and inside the minimal image; it does not depend on
the repository's `tests/` tree at runtime.
