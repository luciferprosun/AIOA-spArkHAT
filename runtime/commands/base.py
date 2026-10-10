from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from runtime.tools.admission import legacy_command_allowed


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
        if not legacy_command_allowed(name, args):
            if name == 'memory-patch':
                import json
                from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
                from runtime.memory_patch.views import error_response
                _, view = error_response('invalid', MemoryPatchError(ErrorCode.ADMISSION_DENIED))
                view['error']['safe_message'] = 'UNSUPPORTED_EFFECT_ROUTE: native authority and containment required.'
                return CommandResult(True, json.dumps(view), 1)
            return CommandResult(True, 'UNSUPPORTED_EFFECT_ROUTE: native authority and containment required.', 1)
        return handler(args.strip(), runtime)
