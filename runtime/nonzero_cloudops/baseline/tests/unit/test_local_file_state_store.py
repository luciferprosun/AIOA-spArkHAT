import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

import aioa_cloudops_agent.persistence.local_integrity as local_integrity
from aioa_cloudops_agent.nz import (
    AuditEvent,
    AuditEventType,
    BudgetCounters,
    Run,
    StorageConflictError,
    StorageDependencyError,
    WorkflowState,
)
from aioa_cloudops_agent.persistence import LocalFileDurableTruthRepository

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def _run() -> Run:
    return Run.new(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key="local/store/0001",
        created_at=NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=2_048),
    )


def _event(event_id: UUID, event_type: AuditEventType) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        run_id=RUN_ID,
        type=event_type,
        timestamp=NOW,
        source="b4-integrity-test",
        redacted_payload_hash="a" * 64,
    )


class FailingWriteStore(LocalFileDurableTruthRepository):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.fail_next_write = False

    def _write(self, repository: object) -> None:
        if self.fail_next_write:
            self.fail_next_write = False
            raise StorageDependencyError("injected local write failure")
        super()._write(repository)


def test_local_store_crud_and_restart_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = LocalFileDurableTruthRepository(path)
    created = store.create_run(_run())
    running = store.transition_run(
        created.run_id,
        WorkflowState.INVESTIGATING,
        expected_state=WorkflowState.RECEIVED,
        expected_version=created.version,
        updated_at=NOW,
    )

    reopened = LocalFileDurableTruthRepository(path)
    assert reopened.get_run(RUN_ID) == running
    assert path.stat().st_mode & 0o777 == 0o600


def test_local_store_rejects_stale_writer_without_changing_state(tmp_path: Path) -> None:
    store = LocalFileDurableTruthRepository(tmp_path / "state.json")
    created = store.create_run(_run())
    running = store.transition_run(
        created.run_id,
        WorkflowState.INVESTIGATING,
        expected_state=WorkflowState.RECEIVED,
        expected_version=created.version,
        updated_at=NOW,
    )

    with pytest.raises(StorageConflictError, match="version"):
        store.transition_run(
            created.run_id,
            WorkflowState.INVESTIGATING,
            expected_state=WorkflowState.RECEIVED,
            expected_version=created.version,
            updated_at=NOW,
        )
    assert store.get_run(RUN_ID) == running


def test_failed_transition_write_leaves_persisted_state_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = FailingWriteStore(path)
    created = store.create_run(_run())
    store.fail_next_write = True

    with pytest.raises(StorageDependencyError, match="injected"):
        store.transition_run(
            created.run_id,
            WorkflowState.INVESTIGATING,
            expected_state=WorkflowState.RECEIVED,
            expected_version=created.version,
            updated_at=NOW,
        )

    reopened = LocalFileDurableTruthRepository(path)
    assert reopened.get_run(RUN_ID) == created


def test_atomic_replace_failure_preserves_previous_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "state.json"
    store = LocalFileDurableTruthRepository(path)
    created = store.create_run(_run())
    before = path.read_bytes()

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("injected atomic replace failure")

    monkeypatch.setattr(local_integrity.os, "replace", fail_replace)
    with pytest.raises(StorageDependencyError, match="write failed"):
        store.transition_run(
            created.run_id,
            WorkflowState.INVESTIGATING,
            expected_state=WorkflowState.RECEIVED,
            expected_version=created.version,
            updated_at=NOW,
        )

    assert path.read_bytes() == before
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


@pytest.mark.parametrize(
    "content",
    [
        "{not-json",
        json.dumps({"format_version": 999}),
        json.dumps(
            {
                "format_version": 1,
                "runs": [{"state": "UNKNOWN"}],
                "proposals": [],
                "approvals": [],
                "idempotency": [],
                "checkpoints": [],
                "audit_events": [],
                "verification_evidence": [],
            }
        ),
    ],
)
def test_corrupt_or_unknown_local_state_fails_closed(tmp_path: Path, content: str) -> None:
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(StorageDependencyError):
        LocalFileDurableTruthRepository(path).get_run(RUN_ID)


def test_duplicate_run_creation_is_typed_conflict(tmp_path: Path) -> None:
    store = LocalFileDurableTruthRepository(tmp_path / "state.json")
    store.create_run(_run())

    with pytest.raises(StorageConflictError, match="already exists"):
        store.create_run(_run())


def test_local_snapshot_is_integrity_bound_and_read_atomically(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = LocalFileDurableTruthRepository(path)
    store.create_run(_run())
    store.append_audit_event(
        _event(UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d"), AuditEventType.RUN_CREATED)
    )
    store.append_audit_event(
        _event(
            UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3e"),
            AuditEventType.STATE_TRANSITIONED,
        )
    )

    raw = json.loads(path.read_text(encoding="utf-8"))
    snapshot = store.read_run_snapshot(RUN_ID)

    assert set(raw) == {
        "integrity_version",
        "payload",
        "payload_sha256",
        "payload_type",
    }
    assert raw["payload_type"] == "AIOA_DURABLE_TRUTH"
    assert snapshot.run == _run()
    assert snapshot.audit_event_count == len(snapshot.audit_events) == 2
    assert snapshot.integrity_status == "VERIFIED"
    assert snapshot.snapshot_sha256 == raw["payload_sha256"]


@pytest.mark.parametrize(
    "tamper",
    [
        "edit_run",
        "delete_event",
        "reorder_events",
        "inject_field",
        "alter_digest",
    ],
)
def test_local_snapshot_tampering_is_detected(tmp_path: Path, tamper: str) -> None:
    path = tmp_path / "state.json"
    store = LocalFileDurableTruthRepository(path)
    store.create_run(_run())
    for suffix, event_type in (("3d", AuditEventType.RUN_CREATED), ("3e", AuditEventType.CHECKPOINT_SAVED)):
        store.append_audit_event(
            _event(UUID(f"01890f6c-3311-7abc-8f4a-6e4f7f0b9b{suffix}"), event_type)
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    payload = raw["payload"]
    if tamper == "edit_run":
        payload["runs"][0]["idempotency_key"] = "tampered/request"
    elif tamper == "delete_event":
        payload["audit_events"].pop()
    elif tamper == "reorder_events":
        payload["audit_events"].reverse()
    elif tamper == "inject_field":
        payload["audit_events"][0]["injected"] = True
    else:
        raw["payload_sha256"] = "0" * 64
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(StorageDependencyError, match="corrupt or unreadable"):
        store.get_run(RUN_ID)


def test_local_state_rejects_symlink_permissive_mode_and_oversize(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "linked.json"
    link.symlink_to(target)
    with pytest.raises(StorageDependencyError):
        LocalFileDurableTruthRepository(link)
    assert target.read_text(encoding="utf-8") == "preserve"

    permissive = tmp_path / "permissive.json"
    safe = LocalFileDurableTruthRepository(permissive)
    safe.create_run(_run())
    permissive.chmod(0o644)
    with pytest.raises(StorageDependencyError, match="corrupt or unreadable"):
        safe.get_run(RUN_ID)

    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as handle:
        handle.truncate(8 * 1024 * 1024 + 1)
    oversized.chmod(0o600)
    with pytest.raises(StorageDependencyError, match="corrupt or unreadable"):
        LocalFileDurableTruthRepository(oversized).get_run(RUN_ID)


def test_local_state_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"integrity_version":1,"integrity_version":1,"payload":{},'
        '"payload_sha256":"' + "0" * 64 + '","payload_type":"AIOA_DURABLE_TRUTH"}',
        encoding="utf-8",
    )
    path.chmod(0o600)

    with pytest.raises(StorageDependencyError, match="corrupt or unreadable"):
        LocalFileDurableTruthRepository(path).get_run(RUN_ID)
