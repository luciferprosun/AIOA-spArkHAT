"""CLI readout for advisory RHCSA command-shape classification.

This is a local demonstration readout for advisory command-shape classification.
It does not execute commands and is not executor policy.
"""

from __future__ import annotations

import json
import sys
from typing import Sequence

try:
    from runtime.tools.command_grammar import validate_command_shape
except ModuleNotFoundError:  # Allows direct file execution from the repo root.
    from command_grammar import validate_command_shape


def classify_commands(commands: Sequence[str]) -> list[dict]:
    results = []
    for command in commands:
        classification = validate_command_shape(command)
        results.append({"input": command, **classification})
    return results


def _usage() -> str:
    return (
        "Usage: python3 -m runtime.tools.command_grammar_cli "
        '"<command string>" ["<command string>" ...]\n'
        "       python3 -m runtime.tools.command_grammar_cli --stdin"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--stdin"]:
        commands = [line.strip() for line in sys.stdin if line.strip()]
        print(json.dumps(classify_commands(commands), indent=2, sort_keys=True))
        return 0

    if not args:
        print(_usage(), file=sys.stderr)
        return 2

    print(json.dumps(classify_commands(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
