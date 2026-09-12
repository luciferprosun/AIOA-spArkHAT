"""Allow-listed structured logs for the public judge boundary."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Final

_SAFE_FIELDS: Final = frozenset(
    {
        "error_code",
        "http_status",
        "method",
        "outcome",
        "request_id",
        "route",
        "run_id",
    }
)
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_./:{}-]{1,128}$")
_JUDGE_LOGGER = logging.getLogger("aioa.judge")
_JUDGE_LOGGER.setLevel(logging.INFO)


def _default_sink(payload: str) -> None:
    _JUDGE_LOGGER.info("%s", payload)


class StructuredJudgeLogger:
    """Emit canonical JSON from an allowlist instead of logging request objects."""

    def __init__(self, sink: Callable[[str], None] | None = None) -> None:
        self._sink = sink or _default_sink

    def emit(self, event: str, **fields: object) -> None:
        record: dict[str, object] = {
            "event": event if _SAFE_VALUE.fullmatch(event) is not None else "judge_event",
        }
        for name, value in fields.items():
            if name not in _SAFE_FIELDS or value is None:
                continue
            if isinstance(value, bool):
                record[name] = value
                continue
            if isinstance(value, int) and not isinstance(value, bool):
                record[name] = value
                continue
            rendered = str(value)
            if _SAFE_VALUE.fullmatch(rendered) is not None:
                record[name] = rendered
        payload = json.dumps(
            record,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            self._sink(payload)
        except Exception:
            return
