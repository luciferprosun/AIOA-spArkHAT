"""Run the credential-free Local-2 API and operator console on loopback."""

import argparse
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

from aioa_cloudops_agent.agent import create_local_hitl_runtime
from aioa_cloudops_agent.config import LocalHitlSettings
from aioa_cloudops_agent.local_api import (
    LocalApiApplication,
    LocalApiTokenAuthorizer,
    create_local_http_server,
    load_or_create_local_token,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--state-path",
        type=Path,
        default=Path(".local/aioa-local-hitl-state.json"),
    )
    parser.add_argument(
        "--inventory-path",
        type=Path,
        default=Path(".local/aioa-local-mock-inventory.json"),
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path(".local/aioa-local-api.token"),
    )
    parser.add_argument("--approval-ttl-seconds", type=int, default=600)
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="open the judge console with a fragment-only session bootstrap",
    )
    return parser.parse_args()


def _browser_bootstrap_url(address: str, port: int, token: str) -> str:
    """Keep the credential out of the HTTP request target and server logs."""

    if address != "127.0.0.1" or not 0 <= port <= 65_535:
        raise ValueError("judge console browser target must be loopback")
    return f"http://{address}:{port}/#{urlencode({'access_token': token})}"


def main() -> int:
    args = _arguments()
    settings = LocalHitlSettings(
        state_path=args.state_path,
        inventory_path=args.inventory_path,
        request_ttl_seconds=args.approval_ttl_seconds,
    )
    token = load_or_create_local_token(args.token_file)
    runtime = create_local_hitl_runtime(settings)
    application = LocalApiApplication(runtime, LocalApiTokenAuthorizer(token))
    server = create_local_http_server(application, host=args.host, port=args.port)
    address, port = server.server_address
    print(f"AIOA Local-2 ready at http://{address}:{port}")
    print("Local API token ready (owner-only; path omitted from judge-facing output).")
    print("DEMO_SANDBOX / portable / mock: no AWS credential discovery or cloud calls.")
    if args.open_browser:
        opened = webbrowser.open(
            _browser_bootstrap_url(address, port, token),
            new=1,
            autoraise=True,
        )
        print(
            "Judge console opened with a fragment-only session bootstrap."
            if opened
            else "Browser could not be opened; use the displayed loopback URL and token file."
        )
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("Local-2 server stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
