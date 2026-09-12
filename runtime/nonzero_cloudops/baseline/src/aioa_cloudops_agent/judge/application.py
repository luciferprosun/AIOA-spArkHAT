"""Strict Lambda Function URL router for the read-only Day 15 judge surface."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol
from uuid import UUID

from pydantic import ValidationError

from aioa_cloudops_agent.config import AwsSettings
from aioa_cloudops_agent.config.settings import DEFAULT_DEPLOYMENT_STAGE
from aioa_cloudops_agent.deployment.config import (
    JUDGE_REQUEST_BODY_MAX_BYTES,
    JudgeInvestigationRequest,
)
from aioa_cloudops_agent.domain.identifiers import validate_correlation_id
from aioa_cloudops_agent.handlers.health import SERVICE_IDENTIFIER

from .contracts import (
    JudgeErrorCode,
    JudgeErrorResponse,
    JudgeInvestigationOutcome,
    JudgeReadinessResponse,
)
from .logging import StructuredJudgeLogger

_STATUS_PATH = re.compile(r"^/judge/status/([^/]+)$")
_SAFE_METHODS: Final = frozenset(
    {"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"}
)
_JSON_HEADERS: Final[dict[str, str]] = {
    "cache-control": "no-store",
    "content-security-policy": "default-src 'none';base-uri 'none';frame-ancestors 'none'",
    "content-type": "application/json",
    "permissions-policy": "camera=(),geolocation=(),microphone=()",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}
_UI_SCRIPT: Final = """const f=document.getElementById('judge');const o=document.getElementById('output');f.addEventListener('submit',async(e)=>{e.preventDefault();const t=document.getElementById('token');try{const r=await fetch('/judge/investigate',{method:'POST',headers:{'Authorization':'Bearer '+t.value,'Content-Type':'application/json'},body:JSON.stringify({intent:'investigate_idle_sandbox'})});o.textContent=JSON.stringify(await r.json(),null,2);}catch(_){o.textContent='Request failed.';}finally{t.value='';}});"""
_UI_SCRIPT_HASH: Final = base64.b64encode(
    hashlib.sha256(_UI_SCRIPT.encode("utf-8")).digest()
).decode("ascii")
_UI_HEADERS: Final[dict[str, str]] = {
    **_JSON_HEADERS,
    "content-security-policy": (
        "default-src 'none';base-uri 'none';connect-src 'self';frame-ancestors 'none';"
        "form-action 'self';"
        f"script-src 'sha256-{_UI_SCRIPT_HASH}'"
    ),
    "content-type": "text/html; charset=utf-8",
}
_UI_BODY: Final = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>AIOA CloudOps Judge</title></head><body><main>"
    "<h1>AIOA CloudOps Judge</h1><p>Read-only sandbox investigation.</p>"
    "<form id='judge'><label>Judge token <input id='token' type='password' "
    "autocomplete='off' required></label><button type='submit'>Investigate</button></form>"
    "<pre id='output' aria-live='polite'></pre></main><script>"
    + _UI_SCRIPT
    + "</script></body></html>"
)


class _Authorizer(Protocol):
    def authorize(self, headers: Mapping[str, object]) -> object | None: ...


class _QuotaRepository(Protocol):
    def reserve(self) -> object | None: ...


class _InvestigationRuntime(Protocol):
    def investigate(self, request: JudgeInvestigationRequest) -> JudgeInvestigationOutcome: ...


class _StatusService(Protocol):
    def get(self, run_id: UUID) -> object | None: ...


@dataclass(frozen=True, slots=True)
class JudgeRequestServices:
    """Per-request adapters; none are constructed for rejected public input."""

    authorizer: _Authorizer
    investigation_quota: _QuotaRepository
    status_quota: _QuotaRepository
    investigation: _InvestigationRuntime
    status: _StatusService
    readiness: Callable[[], bool]


@dataclass(frozen=True, slots=True)
class _Request:
    method: str
    path: str
    headers: Mapping[str, object]
    body: str | None
    query: str
    base64_encoded: bool


class _RequestRejected(ValueError):
    def __init__(self, code: JudgeErrorCode, http_status: int) -> None:
        super().__init__(code.value)
        self.code = code
        self.http_status = http_status


def _json_body(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _response(status: int, body: object, *, headers: Mapping[str, str] = _JSON_HEADERS) -> dict[str, object]:
    rendered = body if isinstance(body, str) else _json_body(body)
    return {
        "statusCode": status,
        "headers": dict(headers),
        "body": rendered,
        "isBase64Encoded": False,
    }


def _headers(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400)
    normalized: dict[str, object] = {}
    for raw_name, header_value in value.items():
        if not isinstance(raw_name, str) or not raw_name or raw_name != raw_name.strip():
            raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400)
        name = raw_name.casefold()
        if name in normalized:
            raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400)
        normalized[name] = header_value
    return normalized


def _request(event: object) -> _Request:
    if not isinstance(event, Mapping):
        raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400)
    request_context = event.get("requestContext")
    http = request_context.get("http") if isinstance(request_context, Mapping) else None
    method = http.get("method") if isinstance(http, Mapping) else None
    path = event.get("rawPath")
    query = event.get("rawQueryString", "")
    encoded = event.get("isBase64Encoded", False)
    body = event.get("body")
    if (
        not isinstance(method, str)
        or method not in _SAFE_METHODS
        or not isinstance(path, str)
        or not path.startswith("/")
        or len(path) > 256
        or not isinstance(query, str)
        or not isinstance(encoded, bool)
        or (body is not None and not isinstance(body, str))
    ):
        raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400)
    if body is not None:
        try:
            body_size = len(body.encode("utf-8"))
        except UnicodeError as error:
            raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400) from error
        if body_size > JUDGE_REQUEST_BODY_MAX_BYTES:
            raise _RequestRejected(JudgeErrorCode.PAYLOAD_TOO_LARGE, 413)
    return _Request(
        method=method,
        path=path,
        headers=_headers(event.get("headers")),
        body=body,
        query=query,
        base64_encoded=encoded,
    )


def _require_empty_request(request: _Request) -> None:
    if request.query or request.base64_encoded or request.body not in (None, ""):
        raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400)


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


def _investigation_request(request: _Request) -> JudgeInvestigationRequest:
    if request.query or request.base64_encoded:
        raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400)
    content_type = request.headers.get("content-type")
    if content_type != "application/json":
        raise _RequestRejected(JudgeErrorCode.UNSUPPORTED_MEDIA_TYPE, 415)
    if request.body is None:
        raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400)
    try:
        body_size = len(request.body.encode("utf-8"))
    except UnicodeError as error:
        raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400) from error
    if body_size > JUDGE_REQUEST_BODY_MAX_BYTES:
        raise _RequestRejected(JudgeErrorCode.PAYLOAD_TOO_LARGE, 413)
    try:
        return JudgeInvestigationRequest.model_validate(_strict_json(request.body))
    except (RecursionError, TypeError, ValueError, ValidationError) as error:
        raise _RequestRejected(JudgeErrorCode.BAD_REQUEST, 400) from error


def _request_id(context: object) -> str | None:
    value = getattr(context, "aws_request_id", None)
    return value if isinstance(value, str) else None


class JudgeFunctionUrlApplication:
    """Expose only public liveness/UI and two token-protected read-only APIs."""

    def __init__(
        self,
        services: Callable[[], JudgeRequestServices],
        *,
        logger: StructuredJudgeLogger | None = None,
    ) -> None:
        if not callable(services):
            raise TypeError("services must be callable")
        self._services = services
        self._logger = logger or StructuredJudgeLogger()

    def handle(self, event: object, context: object) -> dict[str, object]:
        request_id = _request_id(context)
        try:
            request = _request(event)
        except _RequestRejected as rejection:
            return self._error(
                rejection.code,
                rejection.http_status,
                method="UNKNOWN",
                route="invalid",
                request_id=request_id,
            )

        if request.path == "/health":
            return self._health(request, request_id=request_id)
        if request.path == "/":
            return self._public_get(
                request,
                route="root",
                request_id=request_id,
                response=_response(200, _UI_BODY, headers=_UI_HEADERS),
            )
        if request.path == "/ready":
            return self._readiness(request, request_id=request_id)
        if request.path == "/judge/investigate":
            return self._investigate(request, request_id=request_id)
        status_match = _STATUS_PATH.fullmatch(request.path)
        if status_match is not None:
            return self._status(
                request,
                raw_run_id=status_match.group(1),
                request_id=request_id,
            )
        return self._error(
            JudgeErrorCode.NOT_FOUND,
            404,
            method=request.method,
            route="unknown",
            request_id=request_id,
        )

    def _health(self, request: _Request, *, request_id: str | None) -> dict[str, object]:
        if request.method != "GET":
            return self._error(
                JudgeErrorCode.METHOD_NOT_ALLOWED,
                405,
                method=request.method,
                route="health",
                request_id=request_id,
            )
        try:
            _require_empty_request(request)
            settings = AwsSettings(
                stage=os.environ.get("APP_STAGE", DEFAULT_DEPLOYMENT_STAGE)
            )
        except _RequestRejected as rejection:
            return self._error(
                rejection.code,
                rejection.http_status,
                method=request.method,
                route="health",
                request_id=request_id,
            )
        except Exception:
            return self._error(
                JudgeErrorCode.NOT_READY,
                503,
                method=request.method,
                route="health",
                request_id=request_id,
            )
        response = _response(
            200,
            {
                "service": SERVICE_IDENTIFIER,
                "stage": settings.stage,
                "status": "ok",
            },
        )
        self._emit("health", request.method, 200, "success", request_id=request_id)
        return response

    def _public_get(
        self,
        request: _Request,
        *,
        route: str,
        request_id: str | None,
        response: dict[str, object],
    ) -> dict[str, object]:
        if request.method != "GET":
            return self._error(
                JudgeErrorCode.METHOD_NOT_ALLOWED,
                405,
                method=request.method,
                route=route,
                request_id=request_id,
            )
        try:
            _require_empty_request(request)
        except _RequestRejected as rejection:
            return self._error(
                rejection.code,
                rejection.http_status,
                method=request.method,
                route=route,
                request_id=request_id,
            )
        self._emit(route, request.method, 200, "success", request_id=request_id)
        return response

    def _readiness(self, request: _Request, *, request_id: str | None) -> dict[str, object]:
        if request.method != "GET":
            return self._error(
                JudgeErrorCode.METHOD_NOT_ALLOWED,
                405,
                method=request.method,
                route="ready",
                request_id=request_id,
            )
        try:
            _require_empty_request(request)
            ready = self._services().readiness()
        except _RequestRejected as rejection:
            return self._error(
                rejection.code,
                rejection.http_status,
                method=request.method,
                route="ready",
                request_id=request_id,
            )
        except Exception:
            ready = False
        if not ready:
            return self._error(
                JudgeErrorCode.NOT_READY,
                503,
                method=request.method,
                route="ready",
                request_id=request_id,
            )
        response = _response(200, JudgeReadinessResponse(status="ready"))
        self._emit("ready", request.method, 200, "success", request_id=request_id)
        return response

    def _investigate(self, request: _Request, *, request_id: str | None) -> dict[str, object]:
        if request.method != "POST":
            return self._error(
                JudgeErrorCode.METHOD_NOT_ALLOWED,
                405,
                method=request.method,
                route="investigate",
                request_id=request_id,
            )
        try:
            typed_request = _investigation_request(request)
        except _RequestRejected as rejection:
            return self._error(
                rejection.code,
                rejection.http_status,
                method=request.method,
                route="investigate",
                request_id=request_id,
            )
        try:
            services = self._services()
        except Exception:
            return self._error(
                JudgeErrorCode.DEPENDENCY_UNAVAILABLE,
                503,
                method=request.method,
                route="investigate",
                request_id=request_id,
                retryable=True,
            )
        try:
            principal = services.authorizer.authorize(request.headers)
        except Exception:
            principal = None
        if principal is None:
            return self._error(
                JudgeErrorCode.UNAUTHORIZED,
                401,
                method=request.method,
                route="investigate",
                request_id=request_id,
            )
        quota_error = self._reserve_quota(
            services.investigation_quota,
            request,
            "investigate",
            request_id,
        )
        if quota_error is not None:
            return quota_error
        try:
            result = services.investigation.investigate(typed_request)
        except Exception:
            return self._error(
                JudgeErrorCode.INTERNAL_ERROR,
                500,
                method=request.method,
                route="investigate",
                request_id=request_id,
            )
        status = self._investigation_http_status(result)
        self._emit(
            "investigate",
            request.method,
            status,
            "success" if result.succeeded else "closed_non_success",
            request_id=request_id,
            run_id=result.run_id,
            error_code=result.error_code,
        )
        return _response(status, result)

    def _status(
        self,
        request: _Request,
        *,
        raw_run_id: str,
        request_id: str | None,
    ) -> dict[str, object]:
        if request.method != "GET":
            return self._error(
                JudgeErrorCode.METHOD_NOT_ALLOWED,
                405,
                method=request.method,
                route="status",
                request_id=request_id,
            )
        try:
            _require_empty_request(request)
            run_id = validate_correlation_id(raw_run_id)
        except Exception:
            return self._error(
                JudgeErrorCode.BAD_REQUEST,
                400,
                method=request.method,
                route="status",
                request_id=request_id,
            )
        try:
            services = self._services()
        except Exception:
            return self._error(
                JudgeErrorCode.DEPENDENCY_UNAVAILABLE,
                503,
                method=request.method,
                route="status",
                request_id=request_id,
                run_id=run_id,
                retryable=True,
            )
        try:
            principal = services.authorizer.authorize(request.headers)
        except Exception:
            principal = None
        if principal is None:
            return self._error(
                JudgeErrorCode.UNAUTHORIZED,
                401,
                method=request.method,
                route="status",
                request_id=request_id,
            )
        quota_error = self._reserve_quota(
            services.status_quota,
            request,
            "status",
            request_id,
        )
        if quota_error is not None:
            return quota_error
        try:
            status = services.status.get(run_id)
        except Exception:
            return self._error(
                JudgeErrorCode.DEPENDENCY_UNAVAILABLE,
                503,
                method=request.method,
                route="status",
                request_id=request_id,
                run_id=run_id,
                retryable=True,
            )
        if status is None:
            return self._error(
                JudgeErrorCode.NOT_FOUND,
                404,
                method=request.method,
                route="status",
                request_id=request_id,
                run_id=run_id,
            )
        self._emit(
            "status",
            request.method,
            200,
            "success",
            request_id=request_id,
            run_id=run_id,
        )
        return _response(200, status)

    def _reserve_quota(
        self,
        quota: _QuotaRepository,
        request: _Request,
        route: str,
        request_id: str | None,
    ) -> dict[str, object] | None:
        try:
            reservation = quota.reserve()
        except Exception:
            return self._error(
                JudgeErrorCode.DEPENDENCY_UNAVAILABLE,
                503,
                method=request.method,
                route=route,
                request_id=request_id,
                retryable=True,
            )
        if reservation is None:
            return self._error(
                JudgeErrorCode.QUOTA_EXHAUSTED,
                429,
                method=request.method,
                route=route,
                request_id=request_id,
            )
        return None

    @staticmethod
    def _investigation_http_status(result: JudgeInvestigationOutcome) -> int:
        if result.succeeded:
            return 200
        if result.error_code is JudgeErrorCode.DEPENDENCY_UNAVAILABLE:
            return 503
        if result.error_code is JudgeErrorCode.RECOVERY_REQUIRED:
            return 409
        if result.error_code is JudgeErrorCode.INTERNAL_ERROR:
            return 500
        return 422

    def _error(
        self,
        code: JudgeErrorCode,
        status: int,
        *,
        method: str,
        route: str,
        request_id: str | None,
        run_id: UUID | None = None,
        retryable: bool = False,
    ) -> dict[str, object]:
        self._emit(
            route,
            method,
            status,
            "error",
            request_id=request_id,
            run_id=run_id,
            error_code=code,
        )
        return _response(
            status,
            JudgeErrorResponse(error=code, run_id=run_id, retryable=retryable),
        )

    def _emit(
        self,
        route: str,
        method: str,
        status: int,
        outcome: str,
        *,
        request_id: str | None,
        run_id: UUID | None = None,
        error_code: JudgeErrorCode | None = None,
    ) -> None:
        self._logger.emit(
            "judge_http_result",
            route=route,
            method=method,
            http_status=status,
            outcome=outcome,
            request_id=request_id,
            run_id=run_id,
            error_code=error_code,
        )
