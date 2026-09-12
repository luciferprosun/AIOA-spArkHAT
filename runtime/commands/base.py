from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class CommandResult:
    handled: bool
    message: str = ""
    exit_code: int = 0


CommandHandler = Callable[[str, Any], CommandResult]


class CommandRegistry:
    """Simple slash-command registry executed before any model request."""

    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, name: str, handler: CommandHandler) -> None:
        self._handlers[name] = handler

    def names(self) -> list[str]:
        return sorted(self._handlers)

    def execute(self, raw_input: str, runtime: Any) -> CommandResult:
        stripped = raw_input.strip()
        if not stripped.startswith("/"):
            return CommandResult(False)

        command_text = stripped[1:]
        name, _, args = command_text.partition(" ")
        handler = self._handlers.get(name)
        if handler is None:
            return CommandResult(True, f"Unknown command: /{name}. Use /help.")
        return handler(args.strip(), runtime)
