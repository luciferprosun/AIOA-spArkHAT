"""META-P1-02 offline browser agent package (stdlib only, no live browser)."""

from .offline_adapter import (
    FIXTURE_CAPTURED_AT_UTC,
    FIXTURE_ORIGIN,
    FIXTURE_TEXT,
    FIXTURE_URL,
    OfflineAdapterDenied,
    OfflineFixtureAdapter,
    preview_task,
    read_fixture,
)

__all__ = [
    "FIXTURE_CAPTURED_AT_UTC",
    "FIXTURE_ORIGIN",
    "FIXTURE_TEXT",
    "FIXTURE_URL",
    "OfflineAdapterDenied",
    "OfflineFixtureAdapter",
    "preview_task",
    "read_fixture",
]
