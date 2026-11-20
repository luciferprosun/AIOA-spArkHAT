"""Provider-neutral, bounded coding advice under the existing Core.

Adapted from NonZero W7A agent/coding_worker.py at
392487849eddc7444f5159994b66b72e73f15934. MIT notice:
runtime/nonzero_cloudops/LICENSE-NONZERO.txt. No executor or authority store.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Protocol, runtime_checkable

from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.contracts import bounded_int, logical_id
from runtime.secret_redaction import contains_sensitive_material


class WorkerError(ValueError):
    """Stable, value-free boundary failure."""


class WorkerOutcomeUnknown(WorkerError):
    """A bound transport outcome is uncertain; this is never retry permission."""

    def __init__(self):
        super().__init__("WORKER_OUTCOME_UNKNOWN")


def require(value, code):
    if not value:
        raise WorkerError(code)


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    run_id: str
    workspace_id: str
    repository_id: str
    source_base_sha: str
    instruction: str = field(repr=False)
    deadline_at: int
    max_events: int = 64
    max_output_tokens: int = 1024

    def __post_init__(self):
        for value in (self.task_id, self.run_id, self.workspace_id, self.repository_id):
            logical_id(value)
        require(
            type(self.source_base_sha) is str
            and re.fullmatch(r"[0-9a-f]{40}", self.source_base_sha) is not None,
            "SOURCE_SHA",
        )
        bounded_int(self.deadline_at, 1, 2**53)
        bounded_int(self.max_events, 1, 256)
        bounded_int(self.max_output_tokens, 1, 4096)
        require(
            type(self.instruction) is str
            and 1 <= len(self.instruction.encode("utf-8")) <= 8192
            and not contains_sensitive_material(self.instruction),
            "TASK_CONTENT_DENIED",
        )

    def to_dict(self):
        value = asdict(self)
        # The v1 task format predates transport budgets. Its fixed legacy
        # default remains implicit to preserve every signed receipt digest.
        if self.max_output_tokens == 1024:
            value.pop("max_output_tokens")
        return value

    @property
    def digest(self):
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class CandidateFile:
    path: str
    text: str | None = field(repr=False)

    def __post_init__(self):
        require(
            type(self.path) is str
            and 1 <= len(self.path.encode("utf-8")) <= 512
            and not any(ord(c) < 32 for c in self.path),
            "CANDIDATE_PATH_BOUNDS",
        )
        require(self.text is None or type(self.text) is str, "CANDIDATE_TEXT_REQUIRED")
        require(
            self.text is None or len(self.text.encode("utf-8")) <= 65536,
            "CANDIDATE_CONTENT_BOUNDS",
        )
        require(
            not contains_sensitive_material(self.path)
            and not contains_sensitive_material(self.text or ""),
            "CANDIDATE_SECRET_DENIED",
        )


@dataclass(frozen=True, slots=True)
class CandidatePatch:
    files: tuple[CandidateFile, ...] = field(repr=False)

    def __post_init__(self):
        require(
            type(self.files) is tuple
            and 1 <= len(self.files) <= 3
            and all(type(f) is CandidateFile for f in self.files),
            "CANDIDATE_FILE_BOUNDS",
        )
        require(
            len({f.path for f in self.files}) == len(self.files),
            "CANDIDATE_DUPLICATE_PATH",
        )
        require(
            sum(len((f.text or "").encode("utf-8")) for f in self.files) <= 65536,
            "CANDIDATE_CONTENT_BOUNDS",
        )

    @property
    def digest(self):
        return canonical_sha256(
            tuple(
                (
                    f.path,
                    None
                    if f.text is None
                    else hashlib.sha256(f.text.encode("utf-8")).hexdigest(),
                )
                for f in self.files
            )
        )


@dataclass(frozen=True, slots=True)
class WorkerSession:
    session_id: str
    task_id: str
    run_id: str
    task_digest: str
    worker_id: str

    def __post_init__(self):
        for value in (self.session_id, self.task_id, self.run_id, self.worker_id):
            logical_id(value)
        require(
            type(self.task_digest) is str
            and re.fullmatch(r"[0-9a-f]{64}", self.task_digest),
            "SESSION_DIGEST",
        )


@dataclass(frozen=True, slots=True)
class WorkerEvent:
    session_id: str
    task_id: str
    run_id: str
    sequence: int
    kind: str
    evidence_digest: str

    def __post_init__(self):
        for value in (self.session_id, self.task_id, self.run_id):
            logical_id(value)
        bounded_int(self.sequence, 1, 256)
        require(
            self.kind in ("STARTED", "PROGRESS", "CANDIDATE", "COMPLETED"), "EVENT_KIND"
        )
        require(
            type(self.evidence_digest) is str
            and re.fullmatch(r"[0-9a-f]{64}", self.evidence_digest),
            "EVENT_DIGEST",
        )


@dataclass(frozen=True, slots=True)
class WorkerResult:
    session_id: str
    task_id: str
    run_id: str
    candidate: CandidatePatch
    worker_id: str

    def __post_init__(self):
        for value in (self.session_id, self.task_id, self.run_id, self.worker_id):
            logical_id(value)
        require(type(self.candidate) is CandidatePatch, "CANDIDATE_REQUIRED")

    @property
    def status(self):
        return "SUCCEEDED"

    @property
    def authority(self):
        return "NONE"

    @property
    def verified(self):
        return False


@dataclass(frozen=True, slots=True)
class WorkerFailure:
    session_id: str
    task_id: str
    run_id: str
    code: str

    def __post_init__(self):
        for value in (self.session_id, self.task_id, self.run_id):
            logical_id(value)
        require(
            self.code
            in (
                "TIMEOUT",
                "WORKER_CRASH",
                "CANCELLED",
                "INTERRUPTED",
                "CLOSED",
                "NOT_CERTIFIED",
                "PROTOCOL",
                "OUTCOME_UNKNOWN",
                "LATE_EVENT",
                "EVENT_LIMIT",
            ),
            "FAILURE_CODE",
        )

    @property
    def status(self):
        if self.code == "OUTCOME_UNKNOWN":
            return "UNKNOWN"
        return (
            "CANCELLED"
            if self.code in ("CANCELLED", "INTERRUPTED", "CLOSED")
            else "FAILED"
        )

    @property
    def authority(self):
        return "NONE"


@runtime_checkable
class WorkerPort(Protocol):
    def start(self, task: Task) -> WorkerSession: ...
    def poll(self, session: WorkerSession) -> tuple[WorkerEvent, ...]: ...
    def result(self, session: WorkerSession) -> WorkerResult | WorkerFailure | None: ...
    def cancel(self, session: WorkerSession) -> None: ...
    def interrupt(self, session: WorkerSession) -> None: ...
    def close(self) -> None: ...


class WorkerMailbox:
    """Host-owned event normalization; bounded across all drains, never a ledger."""

    def __init__(self, task, *, worker_id="synthetic", clock=time.time):
        require(type(task) is Task and callable(clock), "WORKER_TASK_REQUIRED")
        self.task, self.clock = task, clock
        self.session = WorkerSession(
            "worker-" + uuid.uuid4().hex,
            task.task_id,
            task.run_id,
            task.digest,
            logical_id(worker_id),
        )
        self._lock = threading.RLock()
        self._events, self._count, self._terminal = [], 0, None
        self._append("STARTED", digest=task.digest)

    def _check(self, session):
        require(
            type(session) is WorkerSession and session == self.session,
            "SESSION_BINDING",
        )

    def _fail(self, code):
        if not isinstance(self._terminal, WorkerFailure):
            s = self.session
            self._terminal = WorkerFailure(s.session_id, s.task_id, s.run_id, code)

    def _ready(self):
        if isinstance(self._terminal, WorkerFailure):
            return False
        if self._terminal is not None:
            self._fail("LATE_EVENT")
            return False
        if self.clock() >= self.task.deadline_at:
            self._fail("TIMEOUT")
            return False
        return True

    def _append(self, *kinds, digest):
        """Admit the whole event group before extending the queue."""
        if not self._ready():
            return False
        count = self._count + len(kinds)
        if count > self.task.max_events:
            self._fail("EVENT_LIMIT")
            return False
        s = self.session
        events = [
            WorkerEvent(s.session_id, s.task_id, s.run_id, self._count + offset, kind, digest)
            for offset, kind in enumerate(kinds, start=1)
        ]
        self._events.extend(events)
        self._count = count
        return True

    def progress(self, session):
        with self._lock:
            self._check(session)
            return self._append("PROGRESS", digest=self.task.digest)

    def complete(self, session, candidate):
        with self._lock:
            self._check(session)
            require(type(candidate) is CandidatePatch, "CANDIDATE_REQUIRED")
            if self._append("CANDIDATE", "COMPLETED", digest=candidate.digest):
                self._terminal = WorkerResult(
                    session.session_id,
                    session.task_id,
                    session.run_id,
                    candidate,
                    session.worker_id,
                )
            return self._terminal

    def complete_json(self, session, raw, *, completion_tokens):
        """Admit one inert, budgeted transport message into this owned mailbox.

        Usage is attested separately by the trusted transport, never by fields
        in model JSON. This launches nothing and grants no effect authority.
        Cancellation, stale handles and late messages use the same lifecycle.
        """
        with self._lock:
            self._check(session)
            if not self._ready():
                return self._terminal

            def unique_fields(pairs):
                result = {}
                for key, value in pairs:
                    require(key not in result, "CANDIDATE_DUPLICATE_FIELD")
                    result[key] = value
                return result

            def no_constant(_value):
                raise WorkerError("CANDIDATE_NONFINITE_JSON")

            try:
                bounded_int(completion_tokens, 1, self.task.max_output_tokens)
                require(
                    type(raw) is bytes
                    and 1 <= len(raw) <= min(65536, self.task.max_output_tokens * 16),
                    "CANDIDATE_MESSAGE_BOUNDS",
                )
                payload = json.loads(
                    raw.decode("utf-8"), object_pairs_hook=unique_fields,
                    parse_constant=no_constant,
                )
                require(
                    type(payload) is dict and set(payload) == {
                        "schema", "task_id", "run_id", "session_id", "task_digest", "files",
                    }
                    and payload["schema"] == "aioa.worker-candidate.v1"
                    and payload["task_id"] == self.task.task_id
                    and payload["run_id"] == self.task.run_id
                    and payload["session_id"] == session.session_id
                    and payload["task_digest"] == self.task.digest,
                    "CANDIDATE_MESSAGE_BINDING",
                )
                files = payload["files"]
                require(
                    type(files) is list and 1 <= len(files) <= 3
                    and all(type(item) is dict and set(item) == {"path", "text"} for item in files),
                    "CANDIDATE_FILE_SCHEMA",
                )
                candidate = CandidatePatch(tuple(CandidateFile(**item) for item in files))
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self._fail("PROTOCOL")
                return self._terminal
            return self.complete(session, candidate)

    def fail(self, session, code):
        with self._lock:
            self._check(session)
            require(
                code
                in (
                    "TIMEOUT",
                    "WORKER_CRASH",
                    "CANCELLED",
                    "INTERRUPTED",
                    "CLOSED",
                    "NOT_CERTIFIED",
                    "PROTOCOL",
                    "OUTCOME_UNKNOWN",
                ),
                "FAILURE_CODE",
            )
            if self._terminal is None:
                self._fail(code)

    def drain(self, session):
        with self._lock:
            self._check(session)
            if self._terminal is None:
                self._ready()
            result = tuple(self._events)
            self._events.clear()
            return result

    def result(self, session):
        with self._lock:
            self._check(session)
            if self._terminal is None:
                self._ready()
            return self._terminal


class SyntheticWorker:
    """Finite offline adapter. It proposes data and runs no process or tool."""

    def __init__(self, candidates, *, model_id="synthetic", clock=time.time):
        require(
            type(candidates) is tuple
            and len(candidates) <= 32
            and all(type(c) is CandidatePatch for c in candidates),
            "CANDIDATES_REQUIRED",
        )
        self.model_id = logical_id(model_id)
        self._candidates, self._clock = iter(candidates), clock
        self._box, self._pending, self._closed = None, False, False
        self._lock = threading.RLock()

    def start(self, task):
        with self._lock:
            require(not self._closed, "WORKER_CLOSED")
            require(
                self._box is None or self._box.result(self._box.session) is not None,
                "WORKER_BUSY",
            )
            self._box = WorkerMailbox(
                task, worker_id="synthetic-" + self.model_id, clock=self._clock
            )
            self._pending = True
            return self._box.session

    def _mailbox(self, session):
        require(self._box is not None, "WORKER_SESSION_REQUIRED")
        self._box._check(session)
        return self._box

    def poll(self, session):
        with self._lock:
            box = self._mailbox(session)
            if self._pending and box.result(session) is None:
                self._pending = False
                try:
                    candidate = next(self._candidates)
                except StopIteration:
                    box.fail(session, "WORKER_CRASH")
                else:
                    box.complete(session, candidate)
            return box.drain(session)

    def result(self, session):
        return self._mailbox(session).result(session)

    def cancel(self, session):
        self._mailbox(session).fail(session, "CANCELLED")

    def interrupt(self, session):
        self._mailbox(session).fail(session, "INTERRUPTED")

    def close(self):
        with self._lock:
            self._closed = True
            if self._box is not None:
                self._box.fail(self._box.session, "CLOSED")
