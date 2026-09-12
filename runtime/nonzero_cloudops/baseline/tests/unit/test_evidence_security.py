from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from aioa_cloudops_agent.nz import (
    REDACTION_MARKER,
    AuditEvent,
    AuditEventType,
    contains_sensitive_material,
    redact_sensitive_text,
)

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
EVENT_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3e")
NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def _event(value: str) -> AuditEvent:
    return AuditEvent(
        event_id=EVENT_ID,
        run_id=RUN_ID,
        type=AuditEventType.MODEL_OBSERVED,
        timestamp=NOW,
        source="b4-evidence-test",
        redacted_payload_hash="a" * 64,
        metadata={"detail": value},
    )


@pytest.mark.parametrize(
    "secret",
    [
        "sk" + "-proj-abcdefghijklmnop",
        "A" + "KIAABCDEFGHIJKLMNOP",
        "A" + "SIAABCDEFGHIJKLMNOP",
        "Bearer abcdefghijklmnop",
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "gh" + "p_1234567890abcdef",
        "github" + "_pat_1234567890abcdef",
        "password=hunter2-value",
        "token=opaque-token-value",
        "secret=opaque-secret-value",
        "https://operator:private-password@example.invalid/path",
        "-----BEGIN " + "PRIVATE KEY-----",
        "/home/operator/.aws/credentials",
        "/home/operator/.ssh/id_ed25519",
        "/workspace/private/.env",
    ],
)
def test_audit_event_rejects_provider_neutral_sensitive_values(secret: str) -> None:
    with pytest.raises(ValidationError, match="sensitive audit metadata values"):
        _event(secret)


def test_benign_evidence_metadata_remains_valid() -> None:
    event = _event("proposal rejected by exact target policy")

    assert event.metadata == {"detail": "proposal rejected by exact target policy"}
    assert contains_sensitive_material(event.metadata) is False


@pytest.mark.parametrize(
    "secret",
    [
        "prefix Bearer abcdefghijklmnop suffix",
        "prefix Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "prefix ghp_1234567890abcdef suffix",
        "prefix password=hunter2-value suffix",
        "prefix sk" + "-proj-abcdefghijklmnop suffix",
        "prefix A" + "KIAABCDEFGHIJKLMNOP suffix",
        "prefix https://operator:private-password@example.invalid suffix",
    ],
)
def test_redaction_removes_secret_material_without_echo(secret: str) -> None:
    redacted = redact_sensitive_text(secret)

    assert REDACTION_MARKER in redacted
    assert contains_sensitive_material(redacted) is False
    assert "hunter2" not in redacted
    assert "abcdefghijklmnop" not in redacted
    assert "private-password" not in redacted


def test_non_serializable_evidence_is_never_assumed_public_safe() -> None:
    assert contains_sensitive_material(object()) is True
    with pytest.raises(TypeError):
        redact_sensitive_text(object())  # type: ignore[arg-type]
