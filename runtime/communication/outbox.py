"""Crash-conservative, metadata-only SQLite outbox. No Gmail or Core authority."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from .contracts import MailProposalV1, PreparedMimeV1


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class MailLedgerError(ValueError):
    def __init__(self, reason: str = "MAIL_LEDGER_DENIED") -> None:
        self.reason = reason
        super().__init__(reason)


class OutboxState(str, Enum):
    PREPARED = "PREPARED"
    SENDING = "SENDING"
    SENT_ACCEPTED_BY_API = "SENT_ACCEPTED_BY_API"
    UNKNOWN_SEND = "UNKNOWN_SEND"


@dataclass(frozen=True, slots=True)
class OutboxReceipt:
    proposal_id: str
    task_id: str
    proposal_fingerprint: str
    mime_sha256: str
    state: OutboxState
    provider_message_id: str | None
    provider_thread_id: str | None
    created_utc: str
    updated_utc: str


_COLUMNS = ("proposal_id", "task_id", "proposal_fingerprint", "mime_sha256", "state",
            "provider_message_id", "provider_thread_id", "created_utc", "updated_utc")


def _require(condition: bool, code: str = "MAIL_LEDGER_DENIED") -> None:
    if not condition:
        raise MailLedgerError(code)


def _clock() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(
        {"domain": "aioa.mail.outbox.row.v1", **data}, sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()


def _reference(value: object) -> str:
    _require(type(value) is str and _REF.fullmatch(value) is not None,
             "MAIL_PROVIDER_REFERENCE_DENIED")
    return value


class OutboxLedger:
    """One metadata-only durable attempt per immutable proposal.

    This is NOT an effect authorization service. Calls to begin()/accepted()
    are bookkeeping primitives and cannot contact a provider. A future
    production dispatcher must first consume the EXISTING AIOA Core warrant
    and verify the final MIME bytes, STOP and scoped owner principal.

    Parent directory must already exist with mode 0700 (or stricter).
    """

    def __init__(self, path: Path):
        _require(isinstance(path, Path) and path.name.endswith(".sqlite3"),
                 "MAIL_LEDGER_LOCATION_DENIED")
        parent = path.parent
        _require(parent.is_dir() and not parent.is_symlink()
                 and stat.S_IMODE(parent.stat().st_mode) & 0o077 == 0,
                 "MAIL_LEDGER_DIRECTORY_UNSAFE")
        self._path = path
        if path.is_symlink():
            raise MailLedgerError("MAIL_LEDGER_SYMLINK_DENIED")
        if path.exists():
            props = path.stat()
            _require(stat.S_ISREG(props.st_mode)
                     and stat.S_IMODE(props.st_mode) & 0o077 == 0,
                     "MAIL_LEDGER_FILE_UNSAFE")
        else:
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(path, flags, 0o600)
            os.close(fd)
        self._db = sqlite3.connect(str(path), isolation_level=None, timeout=3.0)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA busy_timeout=3000")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS gmail_outbox_v1 (
                proposal_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                proposal_fingerprint TEXT NOT NULL,
                mime_sha256 TEXT NOT NULL,
                state TEXT NOT NULL,
                provider_message_id TEXT,
                provider_thread_id TEXT,
                created_utc TEXT NOT NULL,
                updated_utc TEXT NOT NULL,
                row_digest TEXT NOT NULL
            )
        """)
        verdict = self._db.execute("PRAGMA quick_check").fetchone()[0]
        _require(verdict == "ok", "MAIL_LEDGER_INTEGRITY_FAILED")

    @contextmanager
    def _transaction(self):
        try:
            self._db.execute("BEGIN IMMEDIATE")
            yield
            self._db.execute("COMMIT")
        except Exception:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def _read(self, proposal_id: str) -> dict | None:
        _reference(proposal_id)
        row = self._db.execute(
            "SELECT * FROM gmail_outbox_v1 WHERE proposal_id=?", (proposal_id,)
        ).fetchone()
        if row is None:
            return None
        data = {key: row[key] for key in _COLUMNS}
        _require(_hash(data) == row["row_digest"], "MAIL_LEDGER_RECORD_CHANGED")
        _require(data["state"] in {x.value for x in OutboxState}, "MAIL_LEDGER_STATE_DENIED")
        _require(all(type(data[k]) is str and _SHA.fullmatch(data[k])
                     for k in ("proposal_fingerprint", "mime_sha256")),
                 "MAIL_LEDGER_DIGEST_DENIED")
        return data

    def _view(self, data: dict) -> OutboxReceipt:
        return OutboxReceipt(
            proposal_id=data["proposal_id"], task_id=data["task_id"],
            proposal_fingerprint=data["proposal_fingerprint"],
            mime_sha256=data["mime_sha256"],
            state=OutboxState(data["state"]),
            provider_message_id=data["provider_message_id"],
            provider_thread_id=data["provider_thread_id"],
            created_utc=data["created_utc"], updated_utc=data["updated_utc"],
        )

    def read(self, proposal_id: str) -> OutboxReceipt | None:
        data = self._read(proposal_id)
        return self._view(data) if data is not None else None

    def prepare(self, proposal: MailProposalV1, mime: PreparedMimeV1) -> OutboxReceipt:
        _require(type(proposal) is MailProposalV1 and type(mime) is PreparedMimeV1,
                 "MAIL_LEDGER_INPUT_DENIED")
        proposal.__post_init__()
        mime.__post_init__()
        _require(proposal.fingerprint == mime.proposal_fingerprint,
                 "MAIL_LEDGER_PROPOSAL_MISMATCH")
        _reference(proposal.proposal_id)
        _reference(proposal.task_id)
        stamp = _clock()
        data = dict(
            proposal_id=proposal.proposal_id, task_id=proposal.task_id,
            proposal_fingerprint=proposal.fingerprint, mime_sha256=mime.mime_sha256,
            state=OutboxState.PREPARED.value,
            provider_message_id=None, provider_thread_id=None,
            created_utc=stamp, updated_utc=stamp,
        )
        with self._transaction():
            try:
                self._db.execute(
                    "INSERT INTO gmail_outbox_v1 (" + ",".join(_COLUMNS) +
                    ",row_digest) VALUES (" + ",".join("?" for _ in range(len(_COLUMNS)+1)) + ")",
                    tuple(data[key] for key in _COLUMNS) + (_hash(data),),
                )
            except sqlite3.IntegrityError as exc:
                raise MailLedgerError("MAIL_DUPLICATE_PROPOSAL") from exc
        return self._view(data)

    def _transition(self, proposal_id: str, from_state: OutboxState,
                    to_state: OutboxState, *, message_id=None, thread_id=None) -> OutboxReceipt:
        with self._transaction():
            data = self._read(proposal_id)
            _require(data is not None and data["state"] == from_state.value,
                     "MAIL_STATE_TRANSITION_DENIED")
            if message_id is not None:
                data["provider_message_id"] = _reference(message_id)
            if thread_id is not None:
                data["provider_thread_id"] = _reference(thread_id)
            data["state"] = to_state.value
            data["updated_utc"] = _clock()
            self._db.execute(
                "UPDATE gmail_outbox_v1 SET state=?,provider_message_id=?,"
                "provider_thread_id=?,updated_utc=?,row_digest=? WHERE proposal_id=?",
                (data["state"], data["provider_message_id"],
                 data["provider_thread_id"], data["updated_utc"],
                 _hash(data), proposal_id),
            )
            return self._view(data)

    def begin_attempt(self, proposal_id: str) -> OutboxReceipt:
        """Durably mark the attempt BEFORE a hypothetical external call."""
        return self._transition(proposal_id, OutboxState.PREPARED, OutboxState.SENDING)

    def provider_accepted(self, proposal_id: str, message_id: str,
                          thread_id: str) -> OutboxReceipt:
        """A reported API acceptance is not recipient delivery proof."""
        _reference(message_id)
        _reference(thread_id)
        return self._transition(proposal_id, OutboxState.SENDING,
                                OutboxState.SENT_ACCEPTED_BY_API,
                                message_id=message_id, thread_id=thread_id)

    def mark_unknown(self, proposal_id: str) -> OutboxReceipt:
        return self._transition(proposal_id, OutboxState.SENDING,
                                OutboxState.UNKNOWN_SEND)

    def recover_interrupted(self) -> tuple[OutboxReceipt, ...]:
        """Conservatively latch all unfinished SENDING entries to UNKNOWN.

        The caller MUST NOT resume sending those messages automatically.
        """
        results = []
        with self._transaction():
            ids = [row[0] for row in self._db.execute(
                "SELECT proposal_id FROM gmail_outbox_v1 WHERE state=? ORDER BY proposal_id",
                (OutboxState.SENDING.value,),
            )]
            for proposal_id in ids:
                data = self._read(proposal_id)
                data["state"] = OutboxState.UNKNOWN_SEND.value
                data["updated_utc"] = _clock()
                self._db.execute(
                    "UPDATE gmail_outbox_v1 SET state=?,updated_utc=?,row_digest=? "
                    "WHERE proposal_id=?",
                    (data["state"], data["updated_utc"], _hash(data), proposal_id),
                )
                results.append(self._view(data))
        return tuple(results)

    def close(self) -> None:
        self._db.close()
