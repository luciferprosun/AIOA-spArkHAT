"""Core-native, operator-admitted CloudOps domain service; no embedded app."""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from .contract import ModuleConfig, NonZeroError, module_descriptor, parse_config
from .provenance import CoreEvidenceLink, private_file, public_evidence, source_identity

if TYPE_CHECKING:
    from .execution import (
        ApprovalChallengeResult,
        ApprovalResolutionResult,
        DecisionRequest,
        ExecutionResult,
    )
    from .planning import InvestigationResult
    from .views import LocalReadyView, LocalRunView, ResumeRequest, StartRunRequest

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_READ = re.compile(r"/api/runs/(" + _UUID + ")")
_WRITE = re.compile(r"/api/runs/(" + _UUID + r")/(approval-request|decision|resume)")


class NonZeroCloudOpsService:
    """One Core-owned leased workflow, portable-only in native contract v1.

    operator=True is an internal admission marker supplied by Core CLI/API,
    never from JSON or a model. This class is not a second authentication API.
    """

    def __init__(
        self,
        state_dir: Path,
        *,
        guard: Callable[[], bool] | None = None,
        config: ModuleConfig | dict | None = None,
        operator_id: str = "core-local-operator",
        clock: Callable[[], datetime] | None = None,
    ):
        self._config = parse_config(config)
        descriptor = module_descriptor(self.config)
        if not descriptor["available"]:
            raise NonZeroError(descriptor["availability_code"])
        self._lock = threading.RLock()
        self._lease = None
        self._closed = False
        self._guard = guard or (lambda: False)
        self._clock = clock or (lambda: datetime.now(UTC))
        from .execution import BoundExecutionWorkflow, CoreOperatorPrincipal
        from .state.files import atomic_write_private_json

        try:
            self._principal = CoreOperatorPrincipal(actor_session_id=operator_id)
        except (ValueError, TypeError) as error:
            raise NonZeroError("NONZERO_CONFIG_INVALID", 400) from error
        root = Path(state_dir).absolute()
        if ".." in root.parts or any(
            path.is_symlink() for path in (root, *root.parents)
        ):
            raise NonZeroError("NONZERO_UNSAFE_STATE_PATH")
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = root.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise NonZeroError("NONZERO_UNSAFE_STATE_DIRECTORY")
        self.root = root
        try:
            self._lease = private_file(root / "service.lock", create=True)
            try:
                fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise NonZeroError("NONZERO_STATE_ALREADY_OWNED", 409) from error
            self._identity_path = root / "native-identity.json"
            new_namespace = not self._identity_path.exists()
            if new_namespace:
                if any(path.name != "service.lock" for path in root.iterdir()):
                    raise NonZeroError("NONZERO_LEGACY_STATE_REQUIRES_MIGRATION", 409)
                atomic_write_private_json(self._identity_path, source_identity())
            self._check_identity()
            from .adapters.advisory import PortableAdvisor
            from .adapters.portable import (
                PortableExecutor,
                PortableResourceReader,
                PortableStateStore,
            )
            from .composition import NativeComponents
            from .investigation import QueryResource
            from .models import generate_event_id, generate_proposal_id
            from .planning import InvestigationWorkflow
            from .policy import PlanRemediation
            from .state.repository import DomainStateRepository

            inventory = PortableStateStore(root / "inventory.json")
            reader = PortableResourceReader(inventory)
            advisor = PortableAdvisor()
            repository = DomainStateRepository(root / "checkpoints.json")
            executor = PortableExecutor(inventory, clock=self._clock)
            self.components = NativeComponents(
                investigation=InvestigationWorkflow(
                    query_resource=QueryResource(reader),
                    plan_remediation=PlanRemediation(),
                    model_provider=advisor,
                    repository=repository,
                    clock=self._clock,
                    proposal_id_factory=generate_proposal_id,
                    event_id_factory=generate_event_id,
                ),
                execution=BoundExecutionWorkflow(
                    repository,
                    executor,
                    clock=self._clock,
                    request_id_factory=generate_event_id,
                    event_id_factory=generate_event_id,
                    nonce_factory=lambda: secrets.token_urlsafe(32),
                    request_ttl_seconds=self.config.request_ttl_seconds,
                ),
                repository=repository,
                reader=reader,
                advisor=advisor,
                executor=executor,
                inventory=inventory,
            )
            self._evidence = CoreEvidenceLink(
                root, max_bytes=self.config.max_trace_bytes, clock=self._clock,
                create=new_namespace,
            )
            self.provenance = self._evidence.store
            # Opening state only validates: no resume or execution on startup.
            repository.assert_ready()
            inventory.assert_ready()
        except Exception:
            self.close()
            raise

    def _check_identity(self):
        from .state.files import StateIntegrityError, read_private_json

        try:
            if read_private_json(self._identity_path) != source_identity():
                raise NonZeroError("NONZERO_SOURCE_IDENTITY_MISMATCH", 409)
        except (StateIntegrityError, OSError) as error:
            raise NonZeroError("NONZERO_SOURCE_IDENTITY_MISMATCH", 409) from error

    @property
    def config(self) -> ModuleConfig:
        """Effective configuration is immutable for this leased service lifetime."""
        return self._config

    def status(self) -> dict:
        with self._lock:
            result = {
                **module_descriptor(self.config),
                "initialized": True,
                "closed": self._closed,
            }
            if self._closed:
                result.update(available=False, availability_code="NONZERO_SERVICE_CLOSED")
            return result

    def _perform(
        self, operation: str, path: str, call, *, operator: bool, write: bool,
        preflight=None,
    ):
        if operator is not True:
            raise NonZeroError("NONZERO_OPERATOR_REQUIRED", 403)
        with self._lock:
            if self._closed:
                raise NonZeroError("NONZERO_SERVICE_CLOSED")
            if write and self._guard():
                raise NonZeroError("EPISTEMIC_KILL_SWITCH", 403)
            self._check_identity()
            # Reserve a bounded result before a protected operation can begin.
            self._evidence.check(
                reserve=2 * self.config.max_output_bytes if write else 0
            )
            if preflight is not None:
                try:
                    preflight()
                except NonZeroError:
                    raise
                except Exception as error:
                    raise NonZeroError("NONZERO_STATE_OR_OPERATION_UNAVAILABLE", 503) from error
            operation_id = secrets.token_hex(16)
            if write:
                self._evidence.append(
                    "nonzero_operator_request",
                    {
                        "operation_id": operation_id,
                        "operation": operation,
                        "path": path,
                    },
                )
            try:
                result = call()
            except NonZeroError:
                raise
            except Exception as error:
                # No raw storage/provider exception crosses the typed service
                # boundary. An unfinished intent remains visibly unfinished.
                raise NonZeroError("NONZERO_STATE_OR_OPERATION_UNAVAILABLE", 503) from error
            rendered = result.model_dump(mode="json", exclude_none=True)
            if (
                len(json.dumps(rendered, allow_nan=False).encode())
                > self.config.max_output_bytes
            ):
                raise NonZeroError("NONZERO_OUTPUT_LIMIT_EXCEEDED", 409)
            if write:
                self._evidence.append(
                    "nonzero_operator_result",
                    {
                        "operation_id": operation_id,
                        "operation": operation,
                        "path": path,
                        "evidence": public_evidence(rendered),
                    },
                )
            return result

    def _check_execution_output(self, run_id: UUID):
        from .execution import execution_result_upper_bound

        checkpoint = self.components.repository.get_checkpoint(run_id)
        if execution_result_upper_bound(checkpoint) > self.config.max_output_bytes:
            raise NonZeroError("NONZERO_EXECUTION_OUTPUT_BUDGET_INSUFFICIENT", 409)

    def start(
        self, request: StartRunRequest, *, operator: bool = False
    ) -> InvestigationResult:
        from .models import BudgetCounters, Run, generate_run_id, generate_trace_id
        from .views import StartRunRequest

        if not isinstance(request, StartRunRequest):
            raise NonZeroError("NONZERO_INVALID_REQUEST", 400)

        def investigate():
            if self.components.repository.run_count() >= self.config.max_runs:
                raise NonZeroError("NONZERO_RUN_LIMIT_EXCEEDED", 409)
            run_id = generate_run_id()
            run = Run.new(
                run_id=run_id,
                trace_id=generate_trace_id(),
                correlation_id=generate_trace_id(),
                idempotency_key=f"core/nonzero/{run_id}",
                created_at=self._clock(),
                budget=BudgetCounters(
                    max_turns=8, max_tokens=2048, max_elapsed_seconds=60
                ),
            )
            return self.components.investigation.execute(run, request.to_query())

        return self._perform(
            "investigate", "/api/runs", investigate, operator=operator, write=True
        )

    def inspect(self, run_id: UUID, *, operator: bool = False) -> LocalRunView:
        from .evidence import run_view

        self._validate_run_id(run_id)

        def view():
            snapshot = self.components.repository.read_run_snapshot(run_id)
            if snapshot.run is None:
                raise NonZeroError("NONZERO_RUN_NOT_FOUND", 404)
            return run_view(self.components, snapshot)

        return self._perform(
            "inspect", "/api/runs/" + str(run_id), view, operator=operator, write=False
        )

    def request_approval(
        self, run_id: UUID, *, operator: bool = False
    ) -> ApprovalChallengeResult:
        self._validate_run_id(run_id)
        return self._perform(
            "request-approval",
            f"/api/runs/{run_id}/approval-request",
            lambda: self.components.execution.request_approval(run_id, self._principal),
            operator=operator,
            write=True,
        )

    def decide(
        self, request: DecisionRequest, *, operator: bool = False
    ) -> ApprovalResolutionResult:
        from .execution import DecisionRequest

        if not isinstance(request, DecisionRequest):
            raise NonZeroError("NONZERO_INVALID_REQUEST", 400)
        return self._perform(
            "record-decision",
            f"/api/runs/{request.run_id}/decision",
            lambda: self.components.execution.decide(request, self._principal),
            operator=operator,
            write=True,
        )

    def resume(
        self, run_id: UUID, request: ResumeRequest, *, operator: bool = False
    ) -> ExecutionResult:
        from .views import ResumeRequest

        self._validate_run_id(run_id)
        if (
            not isinstance(request, ResumeRequest)
            or request.confirm_execution is not True
        ):
            raise NonZeroError("NONZERO_EXECUTION_CONFIRMATION_REQUIRED", 400)
        return self._perform(
            "execute-approved-portable",
            f"/api/runs/{run_id}/resume",
            lambda: self.components.execution.resume(run_id, self._principal),
            operator=operator,
            write=True,
            preflight=lambda: self._check_execution_output(run_id),
        )

    def ready(self, *, operator: bool = False) -> LocalReadyView:
        from .evidence import runtime_view
        from .views import LocalReadyView

        def readiness():
            self.components.repository.assert_ready()
            self.components.inventory.assert_ready()
            return LocalReadyView(runtime=runtime_view(self.components))

        return self._perform(
            "ready", "/ready", readiness, operator=operator, write=False
        )

    def trace(self, *, operator: bool = False) -> dict:
        if operator is not True:
            raise NonZeroError("NONZERO_OPERATOR_REQUIRED", 403)
        with self._lock:
            if self._closed:
                raise NonZeroError("NONZERO_SERVICE_CLOSED")
            self._check_identity()
            entries, verification = self._evidence.check()
            return {
                **source_identity(),
                "ok": verification.ok,
                "entry_count": verification.entry_count,
                "terminal_hash": verification.terminal_hash,
                "entries": entries,
                "meaning": "Integrity/linkage only; hashes do not prove factual truth.",
            }

    @staticmethod
    def _validate_run_id(run_id):
        if not isinstance(run_id, UUID) or not re.fullmatch(_UUID, str(run_id)):
            raise NonZeroError("NONZERO_INVALID_RUN_ID", 400)

    def request(self, method: str, path: str, payload=None, *, operator: bool = False):
        """Compatibility transport adapter for the existing Core CLI and HTTP routes."""
        if operator is not True:
            raise NonZeroError("NONZERO_OPERATOR_REQUIRED", 403)
        if not isinstance(path, str) or not (
            (method == "GET" and (path == "/ready" or _READ.fullmatch(path)))
            or (method == "POST" and (path == "/api/runs" or _WRITE.fullmatch(path)))
        ):
            raise NonZeroError("NONZERO_ROUTE_NOT_ALLOWED", 404)
        if (method == "GET" and payload is not None) or (
            method == "POST" and type(payload) is not dict
        ):
            raise NonZeroError("NONZERO_INVALID_REQUEST", 400)
        try:
            body = json.dumps(payload, allow_nan=False)
        except (ValueError, TypeError, RecursionError) as error:
            raise NonZeroError("NONZERO_INVALID_REQUEST", 400) from error
        if len(body.encode()) > 16384:
            raise NonZeroError("NONZERO_REQUEST_TOO_LARGE", 413)
        from pydantic import ValidationError

        from .execution import DecisionRequest
        from .models import FailureKind, ResultStatus
        from .views import ResumeRequest, StartRunRequest

        try:
            if path == "/ready":
                return 200, self.ready(operator=operator).model_dump(mode="json")
            if method == "GET":
                result = self.inspect(UUID(_READ.fullmatch(path)[1]), operator=operator)
            elif path == "/api/runs":
                result = self.start(
                    StartRunRequest.model_validate_json(body), operator=operator
                )
            else:
                match = _WRITE.fullmatch(path)
                run_id, action = UUID(match[1]), match[2]
                if action == "approval-request":
                    if payload:
                        raise NonZeroError("NONZERO_INVALID_REQUEST", 400)
                    result = self.request_approval(run_id, operator=operator)
                elif action == "decision":
                    request = DecisionRequest.model_validate_json(body)
                    if request.run_id != run_id:
                        raise NonZeroError("NONZERO_INVALID_REQUEST", 400)
                    result = self.decide(request, operator=operator)
                else:
                    result = self.resume(
                        run_id,
                        ResumeRequest.model_validate_json(body),
                        operator=operator,
                    )
            if hasattr(result, "status"):
                if result.status is ResultStatus.FAILURE:
                    failure = result.failure
                    status = {
                        FailureKind.NOT_FOUND: 404,
                        FailureKind.VALIDATION_FAILURE: 400,
                        FailureKind.POLICY_DENIAL: 403,
                        FailureKind.IDEMPOTENCY_CONFLICT: 409,
                        FailureKind.RECOVERY_REQUIREMENT: 409,
                        FailureKind.ILLEGAL_STATE_TRANSITION: 409,
                        FailureKind.DEPENDENCY_UNAVAILABLE: 503,
                        FailureKind.STORAGE_FAILURE: 503,
                        FailureKind.PROVIDER_FAILURE: 503,
                        FailureKind.TOOL_ADAPTER_FAILURE: 503,
                    }.get(failure.kind, 422)
                    return status, {
                        "ok": False,
                        "error": "NONZERO_WORKFLOW_FAILED",
                        "failure_kind": failure.kind.value,
                        "failure_code": failure.code,
                        "retryable": failure.retryable,
                        "provenance": source_identity(),
                    }
                result = result.value
            return (201 if path == "/api/runs" else 200), {
                "ok": True,
                "result": result.model_dump(mode="json", exclude_none=True),
                "provenance": source_identity(),
            }
        except ValidationError:
            return 400, {"ok": False, "error": "NONZERO_INVALID_REQUEST"}
        except NonZeroError as error:
            if error.status != 400:
                raise
            return error.status, {"ok": False, "error": error.code}

    def close(self):
        with self._lock:
            self._closed = True
            if self._lease is not None:
                os.close(self._lease)
                self._lease = None
