"""Canonical container entrypoint for the credential-free AIOA judge runtime."""

import json
import signal
import sys
from types import FrameType

from aioa_cloudops_agent.agent import create_local_hitl_runtime
from aioa_cloudops_agent.config import PortableServerSettings
from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.local_api import (
    LocalApiApplication,
    LocalApiTokenAuthorizer,
    create_local_http_server,
    load_or_create_local_token,
)


class _ShutdownRequested(Exception):
    """Leave serve_forever through its cleanup boundary."""


def _request_shutdown(_signal: int, _frame: FrameType | None) -> None:
    raise _ShutdownRequested


def main() -> int:
    try:
        settings = PortableServerSettings.from_environment()
        token = load_or_create_local_token(settings.token_path)
        runtime = create_local_hitl_runtime(
            settings.local,
            runtime_settings=settings.runtime,
        )
        application = LocalApiApplication(runtime, LocalApiTokenAuthorizer(token))
        server = create_local_http_server(
            application,
            host=settings.host,
            port=settings.port,
            allow_container_binding=True,
        )
    except (ContractValidationError, OSError, RuntimeError, ValueError):
        print("AIOA portable server configuration invalid", file=sys.stderr)
        return 2

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_number, _request_shutdown)
    print(
        json.dumps(
            {
                "application_version": settings.application_version,
                "authority_mode": settings.authority_mode,
                "aws_calls_allowed": False,
                "host": settings.host,
                "model_provider": settings.runtime.model_provider.value,
                "port": settings.port,
                "public_mode_label": settings.public_mode_label,
                "runtime_mode": settings.runtime.mode.value,
                "sandbox_mode": settings.sandbox_mode,
                "source_commit": settings.source_commit,
                "status": "READY",
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    except (_ShutdownRequested, KeyboardInterrupt):
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
