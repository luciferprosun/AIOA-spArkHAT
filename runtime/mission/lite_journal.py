"""Core-owned operational watch journal; never domain memory or authority.

One host/state root is a deployment namespace. All AgentRuntime instances in
that namespace must use the same Core-injected root. Leases span revisions;
neither a manifest nor model output can choose a different journal location.
"""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import uuid
from pathlib import Path

from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.contracts import MissionError


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


class LiteJournal:
    def __init__(self, root: Path, profile, now: int):
        self.profile, self._closed = profile, False
        root = Path(root).resolve()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        identity = canonical_sha256({"owner": profile.owner_scope, "watch": profile.watch_id})
        self.path = root / (identity + ".sqlite3")
        self._lock = os.open(root / (identity + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._lock)
            raise MissionError("SCHEDULER_ALREADY_OWNED") from None
        self.db = None
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
            self.db = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS watch (singleton INTEGER PRIMARY KEY CHECK(singleton=1), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY, watch_id TEXT NOT NULL, trace_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL, model_id TEXT NOT NULL, created_at INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('RESERVED','COMMITTED','UNKNOWN','RELEASED')),
                    estimated_units INTEGER NOT NULL, actual_units INTEGER, reason TEXT);
                CREATE TABLE IF NOT EXISTS evidence (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL,
                    reason TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS actor_repairs (
                    trace_id TEXT PRIMARY KEY, reservation_id TEXT UNIQUE NOT NULL);
            ''')
            previous = self.db.execute("SELECT data FROM watch WHERE singleton=1").fetchone()
            if previous:
                state = json.loads(previous["data"])
                if state["manifest_digest"] != profile.digest:
                    if profile.manifest_revision <= state["manifest_revision"]:
                        raise MissionError("MANIFEST_REVISION_CONFLICT")
                    if state["queue"] or self.has_uncertain():
                        raise MissionError("RECONCILE_READONLY_REQUIRED")
                uncertain = state.get("reconciliation_required", False) or bool(state["queue"]) or self.has_uncertain() or state["state"] in {
                    "INFERENCE_RUNNING", "INFERENCE_QUEUED", "PROBING", "RECONCILE_READONLY_REQUIRED"}
                with self.db:
                    self.db.execute("UPDATE reservations SET status='UNKNOWN', reason='RESTART_UNCERTAIN' WHERE status='RESERVED'")
                state.update(state="RECONCILE_READONLY_REQUIRED" if uncertain else "IDLE",
                             reason="RECONCILE_READONLY_REQUIRED" if uncertain else "READONLY_RESTART",
                             coordinator_epoch=state["coordinator_epoch"] + 1, shutdown_requested=False,
                             next_check_at=now, manifest_digest=profile.digest,
                             manifest_revision=profile.manifest_revision, reconciliation_required=uncertain)
            else:
                state = dict(watch_id=profile.watch_id, manifest_digest=profile.digest,
                             manifest_revision=profile.manifest_revision, coordinator_epoch=1,
                             next_check_at=now, last_check_at=None, freshness_deadline=None,
                             state="IDLE", reason="WATCH_CREATED", queue=[], shutdown_requested=False,
                             last_digest=None, last_admitted_key=None, last_inference_at=now,
                             model_calls=0, probes=0, evidence_count=0, reconciliation_required=False)
            state["lease_id"] = uuid.uuid4().hex
            self.state = state
            self.record(now, state["reason"], {"coordinator_epoch": state["coordinator_epoch"]})
        except Exception:
            if self.db is not None:
                self.db.close()
            os.close(self._lock)
            raise

    def save(self):
        self.db.execute("INSERT OR REPLACE INTO watch VALUES (1,?)", (encode(self.state),))

    def record(self, now, reason, data=None):
        with self.db:
            self.state["evidence_count"] += 1
            self.db.execute("INSERT INTO evidence(created_at,reason,data) VALUES (?,?,?)", (now, reason, encode(data or {})))
            self.db.execute("DELETE FROM evidence WHERE sequence NOT IN (SELECT sequence FROM evidence ORDER BY sequence DESC LIMIT ?)",
                            (self.profile.cadence.max_evidence_events,))
            self.save()

    def has_uncertain(self):
        return bool(self.db.execute("SELECT 1 FROM reservations WHERE status IN ('UNKNOWN','RESERVED') LIMIT 1").fetchone())

    def reserve(self, reservation_id, trace_id, estimated_units, now):
        return self._reserve(reservation_id, trace_id, estimated_units, now, repair=False)

    def reserve_actor_repair(self, reservation_id, trace_id, estimated_units, now):
        """Claim the episode's sole repair and its budget atomically before transport.

        Released, failed and UNKNOWN attempts still consume the one-repair bound.
        A fresh process cannot replay a previously claimed episode.
        """
        return self._reserve(reservation_id, trace_id, estimated_units, now, repair=True)

    def _reserve(self, reservation_id, trace_id, estimated_units, now, *, repair):
        if type(estimated_units) is not int or estimated_units < 1:
            raise MissionError("INVALID_BUDGET_UNITS")
        policy = self.profile.budget
        with self.db:
            if repair and self.db.execute("SELECT 1 FROM actor_repairs WHERE trace_id=?", (trace_id,)).fetchone():
                raise MissionError("ACTOR_REPAIR_LIMIT")
            if self.has_uncertain():
                raise MissionError("RECONCILE_READONLY_REQUIRED")
            count = self.db.execute("SELECT count(*) FROM reservations").fetchone()[0]
            if count >= policy.max_reservations:
                raise MissionError("BUDGET_JOURNAL_FULL")
            recent = self.db.execute("SELECT count(*), coalesce(sum(CASE WHEN status='RELEASED' THEN 0 ELSE max(estimated_units,coalesce(actual_units,0)) END),0) FROM reservations WHERE created_at > ?",
                                     (now - 3600,)).fetchone()
            # Rejected requests still consume an attempt slot, including 429.
            if recent[0] >= policy.max_requests_per_hour or recent[1] + estimated_units > policy.max_hourly_units:
                raise MissionError("BUDGET_EXHAUSTED")
            self.db.execute("INSERT INTO reservations VALUES (?,?,?,?,?,?,'RESERVED',?,NULL,NULL)",
                            (reservation_id, self.profile.watch_id, trace_id, self.profile.provider_id,
                             self.profile.model_id, now, estimated_units))
            if repair:
                self.db.execute("INSERT INTO actor_repairs VALUES (?,?)", (trace_id, reservation_id))
            self.save()
        # Transaction is durably committed before caller enters the transport.

    def settle(self, reservation_id, status, *, actual_units=None, reason):
        if status not in {"COMMITTED", "UNKNOWN", "RELEASED"}:
            raise MissionError("INVALID_RESERVATION_TRANSITION")
        with self.db:
            changed = self.db.execute("UPDATE reservations SET status=?, actual_units=?, reason=? WHERE reservation_id=? AND status='RESERVED'",
                                      (status, actual_units, reason, reservation_id)).rowcount
            if changed != 1:
                raise MissionError("INVALID_RESERVATION_TRANSITION")
            self.save()

    def reserve_cpl_group(self, trace_id, models, estimates, now):
        """Atomically reserve the exact OpenRouter 1+3+1 group before transport.

        Existing actor attempts and this group share the hourly durable budget.
        A crash with any outstanding slot triggers existing UNKNOWN recovery.
        """
        if (type(models) is not tuple or type(estimates) is not tuple
                or len(models) != 5 or len(estimates) != 5 or models[0] != models[-1]
                or any(type(m) is not str or not m or len(m) > 256 for m in models)
                or any(type(e) is not int or not 1 <= e <= 100000 for e in estimates)):
            raise MissionError("INVALID_CPL_RESERVATION")
        policy = self.profile.budget
        ids = tuple(uuid.uuid4().hex for _ in models)
        with self.db:
            if self.has_uncertain():
                raise MissionError("RECONCILE_READONLY_REQUIRED")
            count = self.db.execute("SELECT count(*) FROM reservations").fetchone()[0]
            recent = self.db.execute("SELECT count(*),coalesce(sum(CASE WHEN status='RELEASED' THEN 0 ELSE max(estimated_units,coalesce(actual_units,0)) END),0) FROM reservations WHERE created_at > ?", (now - 3600,)).fetchone()
            if count + 5 > policy.max_reservations:
                raise MissionError("BUDGET_JOURNAL_FULL")
            if recent[0] + 5 > policy.max_requests_per_hour or recent[1] + sum(estimates) > policy.max_hourly_units:
                raise MissionError("BUDGET_EXHAUSTED")
            self.db.executemany("INSERT INTO reservations VALUES (?,?,?,?,?,?,'RESERVED',?,NULL,NULL)",
                [(identifier, self.profile.watch_id, trace_id, "openrouter", model, now, estimate)
                 for identifier, model, estimate in zip(ids, models, estimates)])
            self.save()
        return ids

    def reservations(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM reservations ORDER BY created_at,rowid")]

    def evidence(self):
        return [dict(row, data=json.loads(row["data"])) for row in self.db.execute("SELECT * FROM evidence ORDER BY sequence")]

    def close(self):
        if not self._closed:
            self._closed = True
            self.db.close()
            os.close(self._lock)
