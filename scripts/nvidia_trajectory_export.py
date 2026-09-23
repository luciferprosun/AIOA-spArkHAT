#!/usr/bin/env python3
"""Export an existing deterministic AIOA competition artifact as ATIF-v1.7."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from runtime.nvidia_trajectory import (  # noqa: E402
    TrajectoryExportError,
    competition_demo_to_atif,
)


EXIT_SUCCESS = 0
EXIT_FAILURE = 1


def _load_source(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrajectoryExportError("SOURCE_ARTIFACT_INVALID") from exc
    if not isinstance(value, dict):
        raise TrajectoryExportError("SOURCE_NOT_OBJECT")
    return value


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        payload = competition_demo_to_atif(_load_source(args.input))
    except TrajectoryExportError as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}), file=sys.stderr)
        return EXIT_FAILURE

    if args.output is not None:
        _atomic_write(args.output, payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
