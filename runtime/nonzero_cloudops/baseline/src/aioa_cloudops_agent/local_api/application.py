"""Loopback-only Local-2 HTTP application with an embedded operator console."""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel, TypeAdapter, ValidationError

from aioa_cloudops_agent.agent.local_composition import LocalHitlRuntime
from aioa_cloudops_agent.agent.local_hitl import (
    LocalDecisionRequest,
    LocalOperatorPrincipal,
)
from aioa_cloudops_agent.cloudops import CloudAdapterUnavailableError
from aioa_cloudops_agent.nz import (
    BudgetCounters,
    FailureDetail,
    FailureKind,
    ResultStatus,
    Run,
    Uuid7Identifier,
    generate_run_id,
    generate_trace_id,
)
from aioa_cloudops_agent.nz.errors import StorageDependencyError

from .auth import LOCAL_API_SESSION_COOKIE, LocalApiTokenAuthorizer
from .contracts import (
    LOCAL_API_BODY_MAX_BYTES,
    LOCAL_API_HEADER_MAX_COUNT,
    LOCAL_API_HEADER_VALUE_MAX_LENGTH,
    LocalApiErrorCode,
    LocalApiErrorResponse,
    LocalBrowserSessionView,
    LocalReadyView,
    LocalResumeRequest,
    LocalStartRunRequest,
)
from .judge_ui import JUDGE_UI_BODY, judge_ui_headers
from .views import run_view, runtime_view

_RUN_PATH = re.compile(r"^/api/runs/([^/]+)$")
_APPROVAL_PATH = re.compile(r"^/api/runs/([^/]+)/approval-request$")
_DECISION_PATH = re.compile(r"^/api/runs/([^/]+)/decision$")
_RESUME_PATH = re.compile(r"^/api/runs/([^/]+)/resume$")
_SESSION_COOKIE = (
    f"{LOCAL_API_SESSION_COOKIE}={{value}}; HttpOnly; SameSite=Strict; Path=/"
)
_CLEAR_SESSION_COOKIE = (
    f"{LOCAL_API_SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
)
_UUID7_ADAPTER = TypeAdapter(Uuid7Identifier)
_JSON_HEADERS: Final[dict[str, str]] = {
    "cache-control": "no-store",
    "content-security-policy": "default-src 'none';base-uri 'none';frame-ancestors 'none'",
    "content-type": "application/json",
    "permissions-policy": "camera=(),geolocation=(),microphone=()",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}
_UI_HEADERS: Final[dict[str, str]] = judge_ui_headers(_JSON_HEADERS)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _Request:
    method: str
    path: str
    headers: Mapping[str, object]
    body: str | None
    query: str


class _Rejected(ValueError):
    def __init__(self, code: LocalApiErrorCode, status: int) -> None:
        super().__init__(code.value)
        self.code = code
        self.status = status


def _response(
    status: int,
    body: object,
    *,
    headers: Mapping[str, str] = _JSON_HEADERS,
) -> dict[str, object]:
    if isinstance(body, BaseModel):
        body = body.model_dump(mode="json", exclude_none=True)
    rendered = body if isinstance(body, str) else json.dumps(
        body,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return {
        "statusCode": status,
        "headers": dict(headers),
        "body": rendered,
    }


def _ok(
    status: int,
    value: BaseModel,
    *,
    headers: Mapping[str, str] = _JSON_HEADERS,
) -> dict[str, object]:
    return _response(
        status,
        {"ok": True, "result": value.model_dump(mode="json", exclude_none=True)},
        headers=headers,
    )


def _headers(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400)
    if len(value) > LOCAL_API_HEADER_MAX_COUNT:
        raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400)
    normalized: dict[str, object] = {}
    for raw_name, header_value in value.items():
        if not isinstance(raw_name, str) or not raw_name or raw_name != raw_name.strip():
            raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400)
        if (
            len(raw_name) > 128
            or not isinstance(header_value, str)
            or len(header_value) > LOCAL_API_HEADER_VALUE_MAX_LENGTH
        ):
            raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400)
        name = raw_name.casefold()
        if name in normalized:
            raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400)
        normalized[name] = header_value
    return normalized


def _parse_request(event: object) -> _Request:
    if not isinstance(event, Mapping):
        raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400)
    method = event.get("method")
    path = event.get("path")
    query = event.get("query", "")
    body = event.get("body")
    if (
        not isinstance(method, str)
        or re.fullmatch(r"[A-Z]{3,16}", method) is None
        or not isinstance(path, str)
        or not path.startswith("/")
        or len(path) > 256
        or not isinstance(query, str)
        or (body is not None and not isinstance(body, str))
    ):
        raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400)
    if body is not None:
        try:
            body_size = len(body.encode("utf-8"))
        except UnicodeError as error:
            raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400) from error
        if body_size > LOCAL_API_BODY_MAX_BYTES:
            raise _Rejected(LocalApiErrorCode.PAYLOAD_TOO_LARGE, 413)
    return _Request(
        method=method,
        path=path,
        headers=_headers(event.get("headers")),
        body=body,
        query=query,
    )


def _strict_json(value: str) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, item in values:
            if name in result:
                raise ValueError("duplicate JSON key")
            result[name] = item
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite JSON value")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=reject_constant)


def _json_model[Model: BaseModel](request: _Request, model: type[Model]) -> Model:
    if request.query:
        raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400)
    if request.headers.get("content-type") != "application/json":
        raise _Rejected(LocalApiErrorCode.UNSUPPORTED_MEDIA_TYPE, 415)
    if request.body is None:
        raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400)
    try:
        return model.model_validate(_strict_json(request.body))
    except (RecursionError, TypeError, ValueError, ValidationError) as error:
        raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400) from error


class LocalApiApplication:
    """Expose public liveness/UI and authenticated Local-2 workflow endpoints."""

    def __init__(
        self,
        runtime: LocalHitlRuntime,
        authorizer: LocalApiTokenAuthorizer,
        *,
        clock: Callable[[], datetime] = _utc_now,
        run_id_factory: Callable[[], UUID] = generate_run_id,
        trace_id_factory: Callable[[], UUID] = generate_trace_id,
    ) -> None:
        if not isinstance(runtime, LocalHitlRuntime):
            raise TypeError("runtime must be LocalHitlRuntime")
        if not isinstance(authorizer, LocalApiTokenAuthorizer):
            raise TypeError("authorizer must be LocalApiTokenAuthorizer")
        if not all(callable(value) for value in (clock, run_id_factory, trace_id_factory)):
            raise TypeError("clock and identifier factories must be callable")
        self._runtime = runtime
        self._authorizer = authorizer
        self._clock = clock
        self._run_id_factory = run_id_factory
        self._trace_id_factory = trace_id_factory

    def handle(self, event: object) -> dict[str, object]:
        try:
            request = _parse_request(event)
        except _Rejected as rejection:
            return self._error(rejection.code, rejection.status)

        if request.path == "/health":
            return self._public_get(
                request,
                _response(200, {"mode": "mock", "service": "aioa-local-hitl", "status": "ok"}),
            )
        if request.path == "/ready":
            return self._ready(request)
        if request.path == "/":
            return self._public_get(
                request,
                _response(200, JUDGE_UI_BODY, headers=_UI_HEADERS),
            )
        if request.path == "/api/session":
            return self._session(request)
        if request.path == "/api/runs":
            return self._start(request)
        for pattern, handler in (
            (_APPROVAL_PATH, self._approval_request),
            (_DECISION_PATH, self._decision),
            (_RESUME_PATH, self._resume),
            (_RUN_PATH, self._status),
        ):
            match = pattern.fullmatch(request.path)
            if match is not None:
                return handler(request, match.group(1))
        return self._error(LocalApiErrorCode.NOT_FOUND, 404)

    def _ready(self, request: _Request) -> dict[str, object]:
        if request.method != "GET":
            return self._error(LocalApiErrorCode.METHOD_NOT_ALLOWED, 405)
        if request.query or request.body not in (None, ""):
            return self._error(LocalApiErrorCode.BAD_REQUEST, 400)
        try:
            view = runtime_view(self._runtime)
            self._runtime.repository.assert_ready()
            self._runtime.cloud_state.assert_ready()
        except (
            CloudAdapterUnavailableError,
            StorageDependencyError,
            TypeError,
            ValueError,
        ):
            return self._error(
                LocalApiErrorCode.DEPENDENCY_UNAVAILABLE,
                503,
                retryable=True,
            )
        return _response(200, LocalReadyView(runtime=view))

    def _public_get(
        self,
        request: _Request,
        response: dict[str, object],
    ) -> dict[str, object]:
        if request.method != "GET":
            return self._error(LocalApiErrorCode.METHOD_NOT_ALLOWED, 405)
        if request.query or request.body not in (None, ""):
            return self._error(LocalApiErrorCode.BAD_REQUEST, 400)
        return response

    def _principal(self, request: _Request) -> LocalOperatorPrincipal | None:
        try:
            return self._authorizer.authorize(request.headers)
        except Exception:
            return None

    def _protected(
        self,
        request: _Request,
        *,
        method: str,
    ) -> LocalOperatorPrincipal | dict[str, object]:
        if request.method != method:
            return self._error(LocalApiErrorCode.METHOD_NOT_ALLOWED, 405)
        principal = self._principal(request)
        if principal is None:
            return self._error(LocalApiErrorCode.UNAUTHORIZED, 401)
        if (
            method != "GET"
            and "authorization" not in request.headers
            and request.headers.get("x-aioa-intent") != "judge-console-v1"
        ):
            return self._error(LocalApiErrorCode.UNAUTHORIZED, 401)
        return principal

    def _session(self, request: _Request) -> dict[str, object]:
        if request.method == "GET":
            if request.query or request.body not in (None, ""):
                return self._error(LocalApiErrorCode.BAD_REQUEST, 400)
            if self._principal(request) is None:
                return self._error(LocalApiErrorCode.UNAUTHORIZED, 401)
            return _ok(
                200,
                LocalBrowserSessionView(
                    authenticated=True,
                    storage="http_only_session_cookie",
                ),
            )
        if request.method == "DELETE":
            if request.query or request.body not in (None, ""):
                return self._error(LocalApiErrorCode.BAD_REQUEST, 400)
            return _ok(
                200,
                LocalBrowserSessionView(authenticated=False),
                headers={**_JSON_HEADERS, "set-cookie": _CLEAR_SESSION_COOKIE},
            )
        if request.method != "POST":
            return self._error(LocalApiErrorCode.METHOD_NOT_ALLOWED, 405)
        session = self._authorizer.issue_browser_session(request.headers)
        if session is None:
            return self._error(LocalApiErrorCode.UNAUTHORIZED, 401)
        try:
            _json_model(request, _EmptyRequest)
        except _Rejected as rejection:
            return self._error(rejection.code, rejection.status)
        return _ok(
            200,
            LocalBrowserSessionView(
                authenticated=True,
                storage="http_only_session_cookie",
            ),
            headers={
                **_JSON_HEADERS,
                "set-cookie": _SESSION_COOKIE.format(value=session),
            },
        )

    def _start(self, request: _Request) -> dict[str, object]:
        protected = self._protected(request, method="POST")
        if isinstance(protected, dict):
            return protected
        try:
            start = _json_model(request, LocalStartRunRequest)
            now = self._clock()
            run_id = self._run_id_factory()
            run = Run.new(
                run_id=run_id,
                trace_id=self._trace_id_factory(),
                correlation_id=self._trace_id_factory(),
                idempotency_key=f"local/api/{run_id}",
                created_at=now,
                budget=BudgetCounters(
                    max_turns=8,
                    max_tokens=2_048,
                    max_elapsed_seconds=60,
                ),
            )
            result = self._runtime.phase_one.execute(run, start.to_query())
        except _Rejected as rejection:
            return self._error(rejection.code, rejection.status)
        except Exception:
            return self._error(LocalApiErrorCode.INTERNAL_ERROR, 500)
        if result.status is ResultStatus.FAILURE or result.value is None:
            return self._flow_failure(result.failure)
        return _ok(201, result.value)

    def _status(self, request: _Request, raw_run_id: str) -> dict[str, object]:
        protected = self._protected(request, method="GET")
        if isinstance(protected, dict):
            return protected
        if request.query or request.body not in (None, ""):
            return self._error(LocalApiErrorCode.BAD_REQUEST, 400)
        run_id = self._run_id(raw_run_id)
        if run_id is None:
            return self._error(LocalApiErrorCode.BAD_REQUEST, 400)
        try:
            snapshot = self._runtime.repository.read_run_snapshot(run_id)
        except (StorageDependencyError, TypeError, ValueError):
            return self._error(LocalApiErrorCode.DEPENDENCY_UNAVAILABLE, 503, retryable=True)
        if snapshot.run is None:
            return self._error(LocalApiErrorCode.NOT_FOUND, 404)
        try:
            view = run_view(self._runtime, snapshot)
        except (TypeError, ValueError, ValidationError):
            return self._error(LocalApiErrorCode.INTERNAL_ERROR, 500)
        return _ok(200, view)

    def _approval_request(
        self,
        request: _Request,
        raw_run_id: str,
    ) -> dict[str, object]:
        protected = self._protected(request, method="POST")
        if isinstance(protected, dict):
            return protected
        run_id = self._run_id(raw_run_id)
        if run_id is None:
            return self._error(LocalApiErrorCode.BAD_REQUEST, 400)
        try:
            _json_model(request, _EmptyRequest)
            result = self._runtime.phase_two.request_approval(run_id, protected)
        except _Rejected as rejection:
            return self._error(rejection.code, rejection.status)
        except Exception:
            return self._error(LocalApiErrorCode.INTERNAL_ERROR, 500)
        if result.status is ResultStatus.FAILURE or result.value is None:
            return self._flow_failure(result.failure)
        return _ok(200, result.value)

    def _decision(self, request: _Request, raw_run_id: str) -> dict[str, object]:
        protected = self._protected(request, method="POST")
        if isinstance(protected, dict):
            return protected
        run_id = self._run_id(raw_run_id)
        if run_id is None:
            return self._error(LocalApiErrorCode.BAD_REQUEST, 400)
        try:
            decision = _json_model(request, LocalDecisionRequest)
            if decision.run_id != run_id:
                raise _Rejected(LocalApiErrorCode.BAD_REQUEST, 400)
            result = self._runtime.phase_two.decide(decision, protected)
        except _Rejected as rejection:
            return self._error(rejection.code, rejection.status)
        except Exception:
            return self._error(LocalApiErrorCode.INTERNAL_ERROR, 500)
        if result.status is ResultStatus.FAILURE or result.value is None:
            return self._flow_failure(result.failure)
        return _ok(200, result.value)

    def _resume(self, request: _Request, raw_run_id: str) -> dict[str, object]:
        protected = self._protected(request, method="POST")
        if isinstance(protected, dict):
            return protected
        run_id = self._run_id(raw_run_id)
        if run_id is None:
            return self._error(LocalApiErrorCode.BAD_REQUEST, 400)
        try:
            _json_model(request, LocalResumeRequest)
            result = self._runtime.phase_two.resume(run_id, protected)
        except _Rejected as rejection:
            return self._error(rejection.code, rejection.status)
        except Exception:
            return self._error(LocalApiErrorCode.INTERNAL_ERROR, 500)
        if result.status is ResultStatus.FAILURE or result.value is None:
            return self._flow_failure(result.failure)
        return _ok(200, result.value)

    @staticmethod
    def _run_id(value: str) -> UUID | None:
        try:
            return _UUID7_ADAPTER.validate_python(value)
        except (TypeError, ValueError, ValidationError):
            return None

    def _flow_failure(self, failure: FailureDetail | None) -> dict[str, object]:
        if failure is None:
            return self._error(LocalApiErrorCode.INTERNAL_ERROR, 500)
        if failure.kind is FailureKind.NOT_FOUND:
            error, status = LocalApiErrorCode.NOT_FOUND, 404
        elif failure.kind is FailureKind.VALIDATION_FAILURE:
            error, status = LocalApiErrorCode.BAD_REQUEST, 400
        elif failure.kind is FailureKind.POLICY_DENIAL:
            error, status = LocalApiErrorCode.POLICY_DENIED, 403
        elif failure.kind in {
            FailureKind.IDEMPOTENCY_CONFLICT,
            FailureKind.RECOVERY_REQUIREMENT,
            FailureKind.ILLEGAL_STATE_TRANSITION,
        }:
            error, status = LocalApiErrorCode.CONFLICT, 409
        elif failure.kind in {
            FailureKind.DEPENDENCY_UNAVAILABLE,
            FailureKind.STORAGE_FAILURE,
            FailureKind.PROVIDER_FAILURE,
            FailureKind.TOOL_ADAPTER_FAILURE,
        }:
            error, status = LocalApiErrorCode.DEPENDENCY_UNAVAILABLE, 503
        else:
            error, status = LocalApiErrorCode.WORKFLOW_FAILED, 422
        return self._error(
            error,
            status,
            failure_kind=failure.kind,
            failure_code=failure.code,
            retryable=failure.retryable,
        )

    @staticmethod
    def _error(
        code: LocalApiErrorCode,
        status: int,
        *,
        failure_kind: FailureKind | None = None,
        failure_code: str | None = None,
        retryable: bool = False,
    ) -> dict[str, object]:
        return _response(
            status,
            LocalApiErrorResponse(
                error=code,
                failure_kind=failure_kind,
                failure_code=failure_code,
                retryable=retryable,
            ),
        )


class _EmptyRequest(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}
