# Nebius Serverless target package

This package defines the serverless **target transport contract** used below
the existing Core `ServiceGuard`. The laptop stays an operator/controller. It
does not execute local shell commands for model output, and this package adds
no scheduler, approval authority, or second executor.

## Current state

The typed client, worker contract, and fixture tests are implemented. Live
deployment is `BLOCKED_BY_CREDENTIALS`: this workspace has no
Nebius serverless project/endpoint credentials or deployment approval. No job,
endpoint, container image, or recurring cloud resource was created.

## Request contract

`runtime.service_guard.target.CloudEffectTargetClient` invokes only
`READ_STATE`, `READ_RECEIPT`, and `APPLY_SET_MAINTENANCE`. The worker entry
contract is `runtime.service_guard.serverless_worker.handle_target_request`.
Requests bind the exact target and owner scope; effects carry the existing
ServiceGuard command, including the expected revision, policy/approval digests,
and idempotency key. The client consumes the existing one-use authorization
before transport. Model text cannot construct that authorization.

The deployment adapter must authenticate the host through cloud-injected
credentials and pass only this JSON contract to the worker. Never put a model
provider key or cloud credential in a manifest, receipt, source file, or job
argument. Do not expose a shell operation.

## Durable state and fencing requirements

The Nebius deployment must provide an external durable store implementing
`read_state`, `read_receipt`, and `apply_once`. `apply_once` must be one atomic
transaction: return an existing receipt for the same idempotency key and
matching request digest; otherwise check expiry, mode, expected revision and
effect count, update state, and persist the receipt together. Conflicting reuse
of a key must fail. A store that cannot do this is not an acceptable target.

Run one owner and one concurrent invocation until the backing store's atomic
fencing behavior has been independently verified. The worker is stateless and
has no background loop. Startup requires an explicit `AOIA_HOME` state root
for the existing Core runtime. Shutdown is request-scoped; no inference or
effect is retried on shutdown. After an ambiguous result, Core reads the
receipt and state before it can record an outcome; it never blindly dispatches
again. Verified state comes from a separate read after the receipt.

## Packaging and deployment

`deployment.json` is the static package manifest. This repository intentionally
does not include a Dockerfile or an assumed Nebius job API shim: the exact job
invocation format and durable-store service are not configured here. Wire the
platform adapter to the handler contract, inject secrets at the platform, and
validate the store's transaction/fencing semantics before requesting a live
deployment review. No local image build is needed for these Python modules.
