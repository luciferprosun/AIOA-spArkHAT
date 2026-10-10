"""Durable OFFLINE_PUBLIC_TEST_KEY replay simulation, never an executor.

Only synthetic markers in a local SQLite fixture database can be produced.
No callbacks, shell, transport, human-key loading or live effect authority.
The database is private fixture evidence and must not be published: bindings
are stored as hashes, but hashes are not a privacy-safe remote projection.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
from pathlib import Path
import sqlite3
from uuid import uuid4

from .approval import ApprovalToken, verify_fixture_approval
from .contracts import ContractError, TaskEnvelope


class ReplayState(str, Enum):
    APPLIED = 'APPLIED'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class FixtureReplayResult:
    state: ReplayState
    receipt_id: str | None = None
    liability_id: str | None = None
    provenance: str = 'OFFLINE_PUBLIC_TEST_KEY'
    grants_effect_authority: bool = False


class FixtureReplayJournal:
    """One-use synthetic START barrier with receipt-first restart recovery.

    Transactions serialize competing processes. START is committed before the
    simulated marker. Any consumed START without a receipt stays UNKNOWN until
    explicit readback reconciliation finds the marker; it is never reexecuted.
    Liabilities remain in the journal even after successful reconciliation.
    """

    def __init__(self, path: Path):
        if not isinstance(path, Path):
            raise ContractError('fixture journal requires a local Path')
        self.path = path
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS starts (
                    nonce TEXT PRIMARY KEY, binding TEXT NOT NULL UNIQUE,
                    liability_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS fixture_effects (
                    nonce TEXT PRIMARY KEY REFERENCES starts(nonce),
                    receipt_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS receipts (
                    nonce TEXT PRIMARY KEY REFERENCES starts(nonce),
                    receipt_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS liabilities (
                    liability_id TEXT PRIMARY KEY, resolved INTEGER NOT NULL
                        CHECK (resolved IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS denials (reason TEXT NOT NULL);
            ''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def _deny(self, reason: str):
        # Fixed codes only: never raw payloads, signatures, nonces or hashes.
        with self._connect() as db:
            db.execute('INSERT INTO denials VALUES (?)', (reason,))

    def _verify(self, token, task, *, scope, resource, now):
        try:
            verify_fixture_approval(token, task, scope=scope, resource=resource, now=now)
        except ContractError:
            self._deny('VERIFICATION_DENIED')
            raise
        # Bind every signed field, not merely the task fingerprint.
        return (hashlib.sha256(bytes.fromhex(token.nonce)).hexdigest(),
                hashlib.sha256(token.to_json()).hexdigest())

    @staticmethod
    def _recover(db, nonce, liability_id):
        receipt = db.execute('SELECT receipt_id FROM receipts WHERE nonce=?', (nonce,)).fetchone()
        if receipt is not None:
            return FixtureReplayResult(ReplayState.APPLIED, receipt_id=receipt[0])
        db.execute('INSERT OR IGNORE INTO liabilities VALUES (?, 0)', (liability_id,))
        return FixtureReplayResult(ReplayState.UNKNOWN, liability_id=liability_id)

    def simulate(self, token: ApprovalToken, task: TaskEnvelope, *, scope: str,
                 resource: str, now: datetime, fault: str = 'NONE') -> FixtureReplayResult:
        """Simulate a marker only. Faults model START crash and lost effect ACK."""
        if fault not in ('NONE', 'AFTER_START', 'LOST_ACK'):
            raise ContractError('unknown fixture fault')
        nonce, binding = self._verify(token, task, scope=scope, resource=resource, now=now)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT binding, liability_id FROM starts WHERE nonce=?', (nonce,)).fetchone()
            if existing is not None:
                if existing[0] != binding:
                    db.execute("INSERT INTO denials VALUES ('NONCE_COLLISION')")
                    db.commit()  # Retain denial even though the caller receives an error.
                    raise ContractError('fixture nonce collision denied')
                return self._recover(db, nonce, existing[1])
            liability_id = str(uuid4())
            db.execute('INSERT INTO starts VALUES (?, ?, ?)', (nonce, binding, liability_id))
        # This boundary is deliberate: a crash here must leave durable START.
        if fault == 'AFTER_START':
            with self._connect() as db:
                db.execute('BEGIN IMMEDIATE')
                return self._recover(db, nonce, liability_id)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            receipt_id = str(uuid4())
            db.execute('INSERT INTO fixture_effects VALUES (?, ?)', (nonce, receipt_id))
            if fault == 'NONE':
                db.execute('INSERT INTO receipts VALUES (?, ?)', (nonce, receipt_id))
                db.execute('UPDATE liabilities SET resolved=1 WHERE liability_id=?', (liability_id,))
                return FixtureReplayResult(ReplayState.APPLIED, receipt_id=receipt_id)
            return self._recover(db, nonce, liability_id)

    def reconcile(self, token: ApprovalToken, task: TaskEnvelope, *, scope: str,
                  resource: str, now: datetime) -> FixtureReplayResult:
        """Explicit fixture readback, never retry a missing simulated effect."""
        nonce, binding = self._verify(token, task, scope=scope, resource=resource, now=now)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT binding, liability_id FROM starts WHERE nonce=?', (nonce,)).fetchone()
            if existing is None:
                raise ContractError('no fixture START to reconcile')
            if existing[0] != binding:
                db.execute("INSERT INTO denials VALUES ('NONCE_COLLISION')")
                db.commit()
                raise ContractError('fixture nonce collision denied')
            result = self._recover(db, nonce, existing[1])
            if result.state is ReplayState.APPLIED:
                return result
            readback = db.execute('SELECT receipt_id FROM fixture_effects WHERE nonce=?', (nonce,)).fetchone()
            if readback is None:
                return result
            db.execute('INSERT INTO receipts VALUES (?, ?)', (nonce, readback[0]))
            db.execute('UPDATE liabilities SET resolved=1 WHERE liability_id=?', (existing[1],))
            return FixtureReplayResult(ReplayState.APPLIED, receipt_id=readback[0])
