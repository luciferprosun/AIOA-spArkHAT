"""Neutral subset of the Oct 2026 AIOA/Nebius tool-message contract.

Adapted from the dirty nebius-nemotron-integration-20261028 worktree, not
authored by a live Meta call. See docs/meta/migration/IMPORT_LEDGER_20261031.md.
Transport-specific ToolExactRequest/ToolProviderResult remain deferred.
This codec decodes proposals; it grants no authority and executes no tool.
"""
from dataclasses import dataclass
import json
import math
import re

from .exact import ExactCallError, _unique_object


def strict_json(value):
    def finite_float(raw):
        result = float(raw)
        if not math.isfinite(result):
            raise ValueError('non-finite JSON')
        return result
    return json.loads(value, object_pairs_hook=_unique_object,
                      parse_float=finite_float,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON')))


def checked(condition, code='INVALID_TOOL_REQUEST'):
    if not condition:
        raise ExactCallError(code)


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments_json: str

    def validate(self):
        checked(type(self.call_id) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', self.call_id), 'INVALID_TOOL_CALL')
        checked(type(self.name) is str and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,63}', self.name), 'INVALID_TOOL_CALL')
        checked(type(self.arguments_json) is str and len(self.arguments_json.encode()) <= 4096, 'INVALID_TOOL_CALL')
        try:
            checked(type(strict_json(self.arguments_json)) is dict, 'INVALID_TOOL_CALL')
        except (ValueError, TypeError, RecursionError):
            raise ExactCallError('INVALID_TOOL_CALL') from None

    def to_wire(self):
        self.validate()
        return {'id': self.call_id, 'type': 'function',
                'function': {'name': self.name, 'arguments': self.arguments_json}}


@dataclass(frozen=True)
class ToolMessage:
    role: str
    content: str | None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def to_wire(self):
        value = {'role': self.role, 'content': self.content}
        if self.tool_call_id is not None:
            value['tool_call_id'] = self.tool_call_id
        if self.tool_calls:
            value['tool_calls'] = [c.to_wire() for c in self.tool_calls]
        return value
