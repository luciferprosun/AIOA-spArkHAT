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

from .contracts import MailContractError, MailProposalV1, PreparedMimeV1, _timestamp
from .canonical_mime import verify_prepared_mime


MAX_OUTBOX_RECORDS = 1024

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
    """One metadata-only durable attempt per task in a single-owner ledger.

    This is NOT an effect authorization service. Calls to begin()/accepted()
    are bookkeeping primitives and cannot contact a provider. A future
    production dispatcher must first consume the EXISTING AIOA Core warrant
    and verify the final MIME bytes, STOP and scoped owner principal.

    Parent directory must already exist with mode 0700 (or stricter).
    """

    def __init__(self, path: Path):
        _require(isinstance(path, Path) and path.name.endswith(".sqlite3"),
                 "MAIL_LEDGER_LOCATION_DENIED")
        self._db = None
        self._path = path.absolute()
        try:
            parent = self._path.parent
            _require(parent.resolve(strict=True) == parent and parent.is_dir(),
                     "MAIL_LEDGER_DIRECTORY_UNSAFE")
            info = parent.lstat()
            _require(stat.S_IMODE(info.st_mode) & 0o077 == 0
                     and info.st_uid == os.geteuid(), "MAIL_LEDGER_DIRECTORY_UNSAFE")
            self._parent_identity = (info.st_dev, info.st_ino)
            # Validate auxiliary paths BEFORE SQLite or main-file creation.
            for suffix in ("-wal", "-shm", "-journal"):
                self._safe_file(Path(str(self._path) + suffix), optional=True)
            props = self._safe_file(self._path, optional=True)
            created = props is None
            if created:
                flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(self._path, flags, 0o600)
                try:
                    props = os.fstat(fd)
                finally:
                    os.close(fd)
            self._file_identity = (props.st_dev, props.st_ino)
            # mode=rw never silently creates a new DB if the checked file vanishes.
            self._db = sqlite3.connect(self._path.as_uri() + "?mode=rw", uri=True,
                                       isolation_level=None, timeout=3.0)
            self._db.row_factory = sqlite3.Row
            self._check_location()
            if not created:
                columns = [row[1] for row in self._db.execute(
                    "PRAGMA table_info(gmail_outbox_v1)")]
                _require(columns == list(_COLUMNS) + ["row_digest"],
                         "MAIL_LEDGER_SCHEMA_UNRECOGNIZED")
                triggers = self._db.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' "
                    "AND tbl_name='gmail_outbox_v1'").fetchall()
                _require(not triggers, "MAIL_LEDGER_SCHEMA_UNRECOGNIZED")
                # Check existing history before altering journal mode or writing.
                self._snapshot_rows()
            verdict = self._db.execute("PRAGMA quick_check").fetchone()[0]
            _require(verdict == "ok", "MAIL_LEDGER_INTEGRITY_FAILED")
            _require(self._db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal",
                     "MAIL_LEDGER_JOURNAL_UNAVAILABLE")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute("PRAGMA busy_timeout=3000")
            if created:
                self._db.execute("""
                    CREATE TABLE gmail_outbox_v1 (
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
            self._check_location()
        except MailLedgerError:
            self.close()
            raise
        except (OSError, sqlite3.Error, ValueError, RuntimeError):
            self.close()
            raise MailLedgerError("MAIL_LEDGER_STORAGE_DENIED") from None

    @staticmethod
    def _safe_file(path: Path, *, optional: bool = False):
        try:
            props = path.lstat()
        except FileNotFoundError:
            _require(optional, "MAIL_LEDGER_LOCATION_CHANGED")
            return None
        _require(stat.S_ISREG(props.st_mode) and props.st_nlink == 1
                 and props.st_uid == os.geteuid()
                 and stat.S_IMODE(props.st_mode) & 0o077 == 0,
                 "MAIL_LEDGER_FILE_UNSAFE")
        return props

    def _check_location(self) -> None:
        """Detect changed names, links and permissions at each local operation.

        This is defense in depth on a trusted, owner-only directory, NOT a
        sandbox against a malicious process with that same OS identity/root.
        """
        _require(self._db is not None, "MAIL_LEDGER_CLOSED")
        try:
            parent = self._path.parent
            props = parent.lstat()
            _require(parent.resolve(strict=True) == parent
                     and stat.S_ISDIR(props.st_mode)
                     and props.st_uid == os.geteuid()
                     and stat.S_IMODE(props.st_mode) & 0o077 == 0
                     and (props.st_dev, props.st_ino) == self._parent_identity,
                     "MAIL_LEDGER_DIRECTORY_UNSAFE")
            main = self._safe_file(self._path)
            _require((main.st_dev, main.st_ino) == self._file_identity,
                     "MAIL_LEDGER_LOCATION_CHANGED")
            for suffix in ("-wal", "-shm", "-journal"):
                self._safe_file(Path(str(self._path) + suffix), optional=True)
        except (OSError, ValueError, RuntimeError) as exc:
            if isinstance(exc, MailLedgerError):
                raise
            raise MailLedgerError("MAIL_LEDGER_LOCATION_CHANGED") from None

    @contextmanager
    def _transaction(self):
        self._check_location()
        try:
            self._db.execute("BEGIN IMMEDIATE")
            yield
            self._check_location()
            self._db.execute("COMMIT")
        except BaseException as exc:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if isinstance(exc, sqlite3.Error):
                raise MailLedgerError("MAIL_LEDGER_STORAGE_DENIED") from None
            raise

    @staticmethod
    def _decode(row) -> dict:
        try:
            data = {key: row[key] for key in _COLUMNS}
            _require(_hash(data) == row["row_digest"], "MAIL_LEDGER_RECORD_CHANGED")
            _reference(data["proposal_id"])
            _reference(data["task_id"])
            _require(data["state"] in {x.value for x in OutboxState},
                     "MAIL_LEDGER_STATE_DENIED")
            _require(all(type(data[k]) is str and _SHA.fullmatch(data[k])
                         for k in ("proposal_fingerprint", "mime_sha256")),
                     "MAIL_LEDGER_DIGEST_DENIED")
            _require(_timestamp(data["created_utc"]) <= _timestamp(data["updated_utc"]),
                     "MAIL_LEDGER_TIME_DENIED")
            if data["state"] == OutboxState.SENT_ACCEPTED_BY_API.value:
                _reference(data["provider_message_id"])
                _reference(data["provider_thread_id"])
            else:
                _require(data["provider_message_id"] is None
                         and data["provider_thread_id"] is None, "MAIL_LEDGER_STATE_DENIED")
            return data
        except MailLedgerError:
            raise
        except (TypeError, ValueError, KeyError, IndexError):
            raise MailLedgerError("MAIL_LEDGER_RECORD_CHANGED") from None

    def _snapshot_rows(self) -> list[dict]:
        self._check_location()
        rows = self._db.execute(
            "SELECT * FROM gmail_outbox_v1 ORDER BY proposal_id LIMIT ?",
            (MAX_OUTBOX_RECORDS + 1,)).fetchall()
        _require(len(rows) <= MAX_OUTBOX_RECORDS, "MAIL_LEDGER_CAPACITY")
        data = [self._decode(row) for row in rows]
        _require(len({row["task_id"] for row in data}) == len(data),
                 "MAIL_LEDGER_DUPLICATE_HISTORY")
        return data

    def _read(self, proposal_id: str) -> dict | None:
        _reference(proposal_id)
        self._check_location()
        try:
            row = self._db.execute(
                "SELECT * FROM gmail_outbox_v1 WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        except sqlite3.Error:
            raise MailLedgerError("MAIL_LEDGER_STORAGE_DENIED") from None
        return self._decode(row) if row is not None else None

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
        try:
            verify_prepared_mime(proposal, mime)
        except MailContractError:
            raise MailLedgerError("MAIL_LEDGER_MIME_BINDING_DENIED") from None
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
            history = self._snapshot_rows()
            _require(len(history) < MAX_OUTBOX_RECORDS, "MAIL_LEDGER_CAPACITY")
            # This single-owner ledger permits one message intent per logical
            # task. A new proposal ID/nonce must not create another send budget.
            _require(all(row["task_id"] != proposal.task_id for row in history),
                     "MAIL_DUPLICATE_TASK")
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
            self._snapshot_rows()
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
            # Validate ALL rows before filtering. Corruption that changed a
            # SENDING state must not disappear from the recovery inventory.
            history = self._snapshot_rows()
            for data in history:
                if data["state"] != OutboxState.SENDING.value:
                    continue
                proposal_id = data["proposal_id"]
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
        if self._db is not None:
            self._db.close()
            self._db = None
