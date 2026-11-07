"""Finite coding coordination under the existing Core; no executor or store.

Selective adaptation of NonZero W7A repair_loop/{contracts,coordinator}.py,
392487849eddc7444f5159994b66b72e73f15934. MIT notice:
runtime/nonzero_cloudops/LICENSE-NONZERO.txt. Host-injected test profiles are
not model input. Even a passing result remains an inert patch proposal.
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.contracts import bounded_int, logical_id
from runtime.mission.patchset import BoundedPatchSetPolicy, PatchSet, SourceIdentity
from runtime.mission.worker import Task, WorkerResult, WorkerSession

TEST_STAGES = ("FAST_TESTS", "TARGETED_TESTS", "FINAL_TESTS")
OUTCOMES = ("PASS", "FAIL", "TIMEOUT", "CRASH", "UNKNOWN", "DENIED", "CANCELLED")


def require(value, code):
    if not value:
        raise ValueError(code)


def digest(value):
    require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "REPAIR_DIGEST"
    )


class RepairBoundaryError(RuntimeError):
    """A host callback failed; only the bounded public code crosses the port."""


@contextmanager
def failure_boundary(code):
    """Preserve typed denials and process signals; wrap foreign callback errors."""
    require(
        type(code) is str and re.fullmatch(r"[A-Z0-9_]{1,96}", code),
        "REPAIR_BOUNDARY_CODE",
    )
    try:
        yield
    except ValueError:
        raise
    except Exception as error:
        raise RepairBoundaryError(code) from error


@dataclass(frozen=True, slots=True)
class CandidateWorkspace:
    root: Path = field(repr=False)
    session: WorkerSession
    worker_result: WorkerResult

    def __post_init__(self):
        require(
            isinstance(self.root, Path) and self.root.is_absolute(), "CANDIDATE_ROOT"
        )
        require(
            type(self.session) is WorkerSession
            and type(self.worker_result) is WorkerResult,
            "WORKER_SUCCESS_REQUIRED",
        )


@dataclass(frozen=True, slots=True)
class ValidationStep:
    stage: str
    status: str
    exit_code: int | None
    patchset_sha256: str
    profile_digest: str
    evidence_digest: str
    core_warrant_digest: str | None = None

    def __post_init__(self):
        require(
            self.stage in TEST_STAGES and self.status in OUTCOMES, "VALIDATION_CONTRACT"
        )
        for value in (self.patchset_sha256, self.profile_digest, self.evidence_digest):
            digest(value)
        if self.core_warrant_digest is not None:
            digest(self.core_warrant_digest.removeprefix("sha256:"))
        require(
            self.exit_code is None or type(self.exit_code) is int,
            "VALIDATION_EXIT_CODE",
        )
        require(self.status != "PASS" or self.exit_code == 0, "FALSE_TEST_PASS")
        require(
            self.status != "FAIL"
            or (type(self.exit_code) is int and self.exit_code != 0),
            "FALSE_TEST_FAILURE",
        )


@dataclass(frozen=True, slots=True)
class AttemptReceipt:
    attempt: int
    worker_session_id: str
    patchset_sha256: str | None
    status: str
    steps: tuple[ValidationStep, ...]
    cleanup_orphans: int

    def __post_init__(self):
        bounded_int(self.attempt, 0, 2)
        logical_id(self.worker_session_id)
        require(self.status in OUTCOMES, "ATTEMPT_STATUS")
        if self.patchset_sha256 is not None:
            digest(self.patchset_sha256)
        require(
            type(self.steps) is tuple
            and len(self.steps) <= 3
            and all(type(s) is ValidationStep for s in self.steps),
            "ATTEMPT_STEPS",
        )
        bounded_int(self.cleanup_orphans, 0, 1024)


@dataclass(frozen=True, slots=True)
class RepairLoopResult:
    task_id: str
    run_id: str
    status: str
    history: tuple[str, ...]
    attempts: tuple[AttemptReceipt, ...]
    final_patchset: PatchSet | None
    failure_code: str | None
    receipt_sha256: str = field(init=False, default="")

    def __post_init__(self):
        logical_id(self.task_id)
        logical_id(self.run_id)
        require(
            self.status
            in ("PATCH_READY", "EXHAUSTED", "DENIED", "FAILED", "CANCELLED", "UNKNOWN"),
            "LOOP_STATUS",
        )
        require(
            type(self.history) is tuple
            and len(self.history) <= 32
            and type(self.attempts) is tuple
            and len(self.attempts) <= 3,
            "LOOP_BOUND",
        )
        require(
            (self.status == "PATCH_READY") == (self.final_patchset is not None),
            "LOOP_FALSE_SUCCESS",
        )
        if self.status == "PATCH_READY":
            self.final_patchset.verify_digest()
            require(
                self.failure_code is None
                and self.attempts
                and self.attempts[-1].status == "PASS"
                and tuple(s.stage for s in self.attempts[-1].steps) == TEST_STAGES
                and all(s.status == "PASS" for s in self.attempts[-1].steps)
                and all(a.cleanup_orphans == 0 for a in self.attempts)
                and self.history[-2:] == ("INDEPENDENT_REVIEW", "PATCH_READY"),
                "LOOP_FALSE_SUCCESS",
            )
        data = asdict(self)
        data.pop("receipt_sha256", None)
        object.__setattr__(self, "receipt_sha256", canonical_sha256(data))

    @property
    def authority(self):
        return "NONE"


class CandidateProducer(Protocol):
    def produce(
        self, attempt_number: int, feedback_code: str | None
    ) -> CandidateWorkspace: ...
    def close(self) -> int: ...


class ValidationSession(Protocol):
    def run(self, stage: str) -> ValidationStep: ...
    def close(self) -> int: ...


class ValidationBackend(Protocol):
    def open(self, root: Path, patchset: PatchSet) -> ValidationSession: ...


def semantic_review(patchset):
    """Conservative independent host review, distinct from test execution."""
    patchset.verify_digest()
    for line in patchset.canonical_diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            if re.search(
                r"(?i)\b(?:monkeypatch|mock)\b|#\s*noqa|type:\s*ignore|"
                r"(?:disable|skip)[_-]?(?:test|check)|os\._exit|sys\.exit",
                line,
            ):
                return "REVIEW_TEST_BYPASS"
            if re.fullmatch(
                r"\+\s*return\s+(?:[-+]?\d+(?:\.\d+)?|True|False|None|[\"\'].*[\"\'])\s*",
                line,
            ):
                return "REVIEW_FIXTURE_BYPASS"
        if (
            line.startswith("-")
            and not line.startswith("---")
            and re.search(r"\b(?:assert|raise)\b", line)
        ):
            return "REVIEW_ASSERTION_WEAKENING"
    return None


class BoundedRepairLoopCoordinator:
    def __init__(self, *, clock=time.time):
        require(callable(clock), "LOOP_CLOCK_REQUIRED")
        self.clock = clock
        self.policy = BoundedPatchSetPolicy()

    def run(
        self,
        *,
        task,
        source,
        base_root,
        producer,
        validator,
        max_repairs=2,
        cancelled=None,
    ):
        bounded_int(max_repairs, 0, 2)
        require(type(task) is Task and type(source) is SourceIdentity, "LOOP_CONTEXT")
        require(cancelled is None or callable(cancelled), "LOOP_CANCEL_BINDING")
        history, attempts, seen = [], [], set()
        final, failure, status = None, None, "FAILED"
        feedback = None

        def stop_reason():
            if cancelled is not None and cancelled():
                return "CANCELLED", "CANCELLED"
            if self.clock() >= task.deadline_at:
                return "TIMEOUT", "TASK_DEADLINE"
            return None

        try:
            for attempt in range(max_repairs + 1):
                if cancelled is not None and cancelled():
                    status, failure = "CANCELLED", "CANCELLED"
                    break
                if self.clock() >= task.deadline_at:
                    status, failure = "FAILED", "TASK_DEADLINE"
                    break
                if attempt:
                    history.append("REPAIRING")
                try:
                    with failure_boundary("WORKER_PRODUCER_FAILED"):
                        candidate = producer.produce(attempt, feedback)
                        require(type(candidate) is CandidateWorkspace, "WORKER_CONTEXT")
                        result, session = candidate.worker_result, candidate.session
                        require(
                            session.task_digest == task.digest
                            and session.task_id == task.task_id
                            and session.run_id == task.run_id
                            and result.task_id == task.task_id
                            and result.run_id == task.run_id
                            and result.session_id == session.session_id,
                            "WORKER_CONTEXT",
                        )
                except (ValueError, RepairBoundaryError):
                    status, failure = "FAILED", "WORKER_PRODUCER_FAILED"
                    break
                patchset, steps, session, cleanup = None, [], None, 0
                attempt_status, attempt_failure = "CRASH", "VALIDATION_BACKEND_FAILURE"
                try:
                    with failure_boundary("VALIDATION_BACKEND_FAILURE"):
                        history.append("PATCH_POLICY")
                        patchset = self.policy.evaluate(
                            base_root,
                            candidate.root,
                            source=source,
                            task=task,
                            worker_session_id=result.session_id,
                        )
                        self.policy.recheck(
                            patchset,
                            base_root=base_root,
                            final_root=candidate.root,
                            source=source,
                            task=task,
                            worker_session_id=result.session_id,
                        )
                        if patchset.final_tree_sha256 in seen:
                            attempt_status, attempt_failure = (
                                "DENIED",
                                "REPAIR_CONTENT_NOT_NEW",
                            )
                        else:
                            seen.add(patchset.final_tree_sha256)
                            session = validator.open(candidate.root, patchset)
                            attempt_status, attempt_failure = "PASS", None
                            for stage in TEST_STAGES:
                                if cancelled is not None and cancelled():
                                    attempt_status, attempt_failure = (
                                        "CANCELLED",
                                        "CANCELLED",
                                    )
                                    break
                                if self.clock() >= task.deadline_at:
                                    attempt_status, attempt_failure = (
                                        "TIMEOUT",
                                        "TASK_DEADLINE",
                                    )
                                    break
                                history.append(stage)
                                observed = session.run(stage)
                                require(
                                    type(observed) is ValidationStep
                                    and observed.stage == stage
                                    and observed.patchset_sha256
                                    == patchset.patchset_sha256,
                                    "VALIDATION_BINDING",
                                )
                                require(
                                    not steps
                                    or observed.profile_digest
                                    == steps[0].profile_digest,
                                    "VALIDATION_PROFILE_CHANGED",
                                )
                                steps.append(observed)
                                stopped = stop_reason()
                                if stopped is not None:
                                    attempt_status, attempt_failure = stopped
                                    break
                                if observed.status != "PASS":
                                    attempt_status, attempt_failure = (
                                        observed.status,
                                        "TEST_" + observed.status,
                                    )
                                    break
                            if attempt_status == "PASS":
                                self.policy.recheck(
                                    patchset,
                                    base_root=base_root,
                                    final_root=candidate.root,
                                    source=source,
                                    task=task,
                                    worker_session_id=result.session_id,
                                )
                                history.append("INDEPENDENT_REVIEW")
                                rejected = semantic_review(patchset)
                                if rejected:
                                    attempt_status, attempt_failure = "DENIED", rejected
                except ValueError as error:
                    attempt_status = "DENIED" if patchset is None else "CRASH"
                    attempt_failure = (
                        str(error)
                        if re.fullmatch(r"PATCHSET_[A-Z0-9_]+", str(error))
                        else "VALIDATION_BINDING_FAILED"
                    )
                except RepairBoundaryError:
                    attempt_status, attempt_failure = (
                        "CRASH",
                        "VALIDATION_BACKEND_FAILURE",
                    )
                finally:
                    if session is not None:
                        try:
                            with failure_boundary("SANDBOX_CLEANUP_FAILED"):
                                cleanup = session.close()
                                if type(cleanup) is not int or not 0 <= cleanup <= 1024:
                                    cleanup = 1
                        except (ValueError, RepairBoundaryError):
                            cleanup = 1
                if cleanup:
                    attempt_status, attempt_failure = "CRASH", "SANDBOX_CLEANUP_FAILED"
                elif (
                    attempt_status == "PASS" and (stopped := stop_reason()) is not None
                ):
                    attempt_status, attempt_failure = stopped
                attempts.append(
                    AttemptReceipt(
                        attempt,
                        result.session_id,
                        None if patchset is None else patchset.patchset_sha256,
                        attempt_status,
                        tuple(steps),
                        cleanup,
                    )
                )
                if attempt_status == "PASS":
                    final, status, failure = patchset, "PATCH_READY", None
                    history.append("PATCH_READY")
                    break
                failure = attempt_failure
                if attempt_status == "FAIL":
                    feedback = attempt_failure
                    if attempt < max_repairs:
                        continue
                    status = "EXHAUSTED"
                elif attempt_status == "DENIED":
                    status = "DENIED"
                elif attempt_status == "UNKNOWN":
                    status = "UNKNOWN"
                elif attempt_status == "CANCELLED":
                    status = "CANCELLED"
                else:
                    status = "FAILED"
                break
        finally:
            try:
                with failure_boundary("WORKER_CLEANUP_FAILED"):
                    cleanup = producer.close()
                    if cleanup is not None and (
                        type(cleanup) is not int or cleanup != 0
                    ):
                        final, status, failure = None, "FAILED", "WORKER_CLEANUP_FAILED"
            except (ValueError, RepairBoundaryError):
                final, status, failure = None, "FAILED", "WORKER_CLEANUP_FAILED"
        if status == "PATCH_READY" and (stopped := stop_reason()) is not None:
            final, failure = None, stopped[1]
            status = "CANCELLED" if stopped[0] == "CANCELLED" else "FAILED"
            history.append(status)
        return RepairLoopResult(
            task.task_id,
            task.run_id,
            status,
            tuple(history),
            tuple(attempts),
            final,
            failure,
        )
