"""Lazy Lambda Function URL entry point for the bounded public judge surface."""

from __future__ import annotations

from collections.abc import Mapping
from threading import Lock

from .application import JudgeFunctionUrlApplication, JudgeRequestServices
from .composition import (
    JudgeProcessResources,
    build_process_resources,
    build_request_services,
)

_PROCESS_RESOURCES: JudgeProcessResources | None = None
_PROCESS_LOCK = Lock()


def _resources() -> JudgeProcessResources:
    global _PROCESS_RESOURCES
    if _PROCESS_RESOURCES is None:
        with _PROCESS_LOCK:
            if _PROCESS_RESOURCES is None:
                _PROCESS_RESOURCES = build_process_resources()
    return _PROCESS_RESOURCES


def _services() -> JudgeRequestServices:
    return build_request_services(_resources())


_APPLICATION = JudgeFunctionUrlApplication(_services)


def lambda_handler(event: object, context: object) -> dict[str, object]:
    """Handle one strict Function URL event without retaining request authority."""

    response = _APPLICATION.handle(event, context)
    if (
        _PROCESS_RESOURCES is not None
        and isinstance(event, Mapping)
        and event.get("rawPath") == "/judge/investigate"
    ):
        _PROCESS_RESOURCES.telemetry.force_flush()
    return response
