"""Manual-only request command for quarantined provider outcomes."""

from __future__ import annotations

import argparse
from pathlib import Path

from runtime.providers.safety import UnknownQuarantine


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Record a new manual replay attempt; this command never dispatches network I/O."
    )
    parser.add_argument("--quarantine", required=True, type=Path)
    parser.add_argument("--unknown-id", required=True)
    parser.add_argument("--new-operation-id", required=True)
    parser.add_argument("--confirm-manual-replay", action="store_true", required=True)
    args = parser.parse_args(argv)
    attempt = UnknownQuarantine(args.quarantine.resolve()).request_manual_replay(
        args.unknown_id, args.new_operation_id, confirmed=args.confirm_manual_replay
    )
    print(attempt)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
