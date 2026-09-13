#!/usr/bin/env python3
"""Local AOIA-Core web interface and JSON API."""

from __future__ import annotations

import argparse
import json
import os
import traceback
import hmac
import secrets
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from evidence_review import ReviewInputError, bundled_scenario, review_candidate
from main import (
    DEBUG_RAW_RESPONSE,
    PROMPT_FILE,
    AgentRuntime,
    ProviderManager,
    load_prompt_template,
    create_runtime,
)
from providers.exact import ExactCallError, _unique_object


RUNTIME_DIR = Path(__file__).resolve().parent
REPOSITORY_DIR = RUNTIME_DIR.parent
WEB_DIR = REPOSITORY_DIR / "web"
if not (WEB_DIR / 'index.html').is_file():
    WEB_DIR = Path(sys.prefix) / 'share/aioa-sparkhat/web'
HOST = os.getenv("AOIA_WEB_HOST", "127.0.0.1")
PORT = int(os.getenv("AOIA_WEB_PORT", "4311"))
MAX_REQUEST_BYTES = 24_000
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


class WebRuntimeService:
    """Shared runtime adapter used by the local AOIA-Core UI."""

    def __init__(self, *, cpl_fixture=False, cpl_cost_policy=None, runtime=None) -> None:
        self.runtime = runtime or create_runtime(cpl_fixture=cpl_fixture, cpl_cost_policy=cpl_cost_policy)
        self.lock = Lock()
        self.csrf_token = secrets.token_urlsafe(32)

    def close(self):
        self.runtime.close()

    def status_payload(self) -> dict:
        payload = self.runtime.snapshot_status()
        payload["available_models"] = self.runtime.provider_manager.available_models()
        payload["evidence_review"] = {
            "enabled": True,
            "provider_call": False,
            "authority": "METADATA_ONLY_NO_AUTHORITY",
        }
        payload['critical_loop'] = self.runtime.critical_loop.status()
        payload['assistant'] = {'default_mode': 'cpl', 'plain_chat': 'EXPLICIT_BYPASS_ONLY'}
        return payload

    def switch_model(self, model_name: str) -> dict:
        with self.lock:
            selected = self.runtime.provider_manager.switch_model(model_name)
            return {
                "ok": True,
                "model": selected,
                "notice": self.runtime.provider_manager.model_notice(selected),
                "status": self.status_payload(),
            }

    def run_prompt(self, prompt: str, *, mode='cpl', plan_options=None) -> dict:
        with self.lock:
            result = self.runtime.assistant_request(prompt, mode=mode, plan_options=plan_options)
            result['status'] = self.status_payload()
            return result


_SERVICE: WebRuntimeService | None = None
_SERVICE_LOCK = Lock()


def get_service() -> WebRuntimeService:
    """Initialize the model runtime only when an endpoint needs it."""

    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = WebRuntimeService()
    return _SERVICE


class AOIAWebHandler(SimpleHTTPRequestHandler):
    """Serve one static AOIA-Core UI and its bounded local APIs."""

    server_version = "AOIA-Core/1.0"

    def __init__(self, *args, service: WebRuntimeService | None = None, **kwargs):
        self.runtime_service = service
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _service(self) -> WebRuntimeService:
        return self.runtime_service or get_service()

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if not self._check_local_request():
            return
        if parsed.path.startswith("/api/memory-patch"):
            if self._check_memory_patch_operator():
                self._handle_memory_patch("GET", parsed, {})
            return
        if parsed.path == '/api/session':
            self._write_json(HTTPStatus.OK, {'token': self._service().csrf_token,
                                           'product_name': 'AIOA spArkHAT'})
            return
        if parsed.path.startswith('/api/nonzero/'):
            if not self._check_token():
                return
            self._handle_nonzero('GET', parsed, None)
            return
        if parsed.path.startswith('/api/cpl/'):
            if not self._check_token():
                return
            try:
                service = self._service().runtime.critical_loop
                if parsed.path == '/api/cpl/status':
                    payload = service.status()
                elif parsed.path == '/api/cpl/fixture':
                    from critical_loop.fixture import FIXTURE_PROMPT, FIXTURE_EVIDENCE
                    payload = {'prompt': FIXTURE_PROMPT, 'evidence': FIXTURE_EVIDENCE,
                               'scope': 'SYNTHETIC_TEST_DATA', 'model': 'fixture/synthetic'}
                elif parsed.path.startswith('/api/cpl/runs/'):
                    tail = parsed.path.removeprefix('/api/cpl/runs/')
                    payload = service.verify(tail[:-6]) if tail.endswith('/trace') else service.get(tail)
                else:
                    self._write_json(HTTPStatus.NOT_FOUND, {'ok': False, 'error': 'not_found'})
                    return
                self._write_json(HTTPStatus.OK, payload)
            except ExactCallError as error:
                self._write_cpl_error(error)
            return
        if parsed.path == "/api/health":
            self._write_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "system": "AOIA-Core",
                    "product_name": "AIOA spArkHAT",
                    "network": "local-only",
                    "evidence_review": "enabled",
                },
            )
            return
        if parsed.path == "/api/status":
            self._write_json(HTTPStatus.OK, self._service().status_payload())
            return
        if parsed.path == "/api/models":
            service = self._service()
            self._write_json(
                HTTPStatus.OK,
                {
                    "current_model": service.runtime.provider_manager.describe(),
                    "available_models": service.runtime.provider_manager.available_models(),
                },
            )
            return
        if parsed.path == "/api/review/scenario":
            self._write_json(HTTPStatus.OK, bundled_scenario())
            return
        if parsed.path in {"/", "/index.html"}:
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if not self._check_local_request():
            return
        if parsed.path.startswith("/api/memory-patch"):
            if not self._check_memory_patch_operator():
                return
            payload = self._read_json_body()
            if payload is not None:
                self._handle_memory_patch("POST", parsed, payload)
            return
        if (parsed.path.startswith(('/api/cpl/', '/api/nonzero/')) or parsed.path in {'/api/chat', '/api/model'}) and not self._check_token():
            return
        if parsed.path.startswith('/api/nonzero/') and self.headers.get('X-AIOA-Intent') != 'nonzero-operator-v1':
            self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'NONZERO_OPERATOR_INTENT_REQUIRED'})
            return
        payload = self._read_json_body()
        if payload is None:
            return
        if parsed.path.startswith('/api/nonzero/'):
            self._handle_nonzero('POST', parsed, payload)
            return

        try:
            if parsed.path == '/api/cpl/plan':
                self._write_json(HTTPStatus.CREATED, self._service().runtime.plan_critical_loop(payload))
                return
            if parsed.path == '/api/cpl/start':
                if set(payload) != {'run_id', 'plan_hash', 'nonce'}:
                    raise ExactCallError('INVALID_START_FIELDS')
                result = self._service().runtime.critical_loop.start(
                    payload['run_id'], payload['plan_hash'], payload['nonce'], approval_source='LOCAL_HTTP_NONCE')
                self._write_json(HTTPStatus.ACCEPTED, result)
                return
            if parsed.path == '/api/cpl/cancel':
                if set(payload) != {'run_id'}:
                    raise ExactCallError('INVALID_CANCEL_FIELDS')
                self._write_json(HTTPStatus.OK, self._service().runtime.critical_loop.cancel(payload['run_id']))
                return
            if parsed.path == '/api/cpl/verify':
                if set(payload) != {'run_id', 'manifest'}:
                    raise ExactCallError('INVALID_VERIFY_FIELDS')
                self._write_json(HTTPStatus.OK, self._service().runtime.critical_loop.verify(payload['run_id'], payload['manifest']))
                return
            if parsed.path == "/api/chat":
                options = {key: value for key, value in payload.items() if key not in {'prompt', 'mode'}}
                result = self._service().run_prompt(payload.get('prompt'),
                    mode=payload.get('mode', 'cpl'), plan_options=options)
                self._write_json(HTTPStatus.CREATED if result['mode'] == 'cpl' else HTTPStatus.OK, result)
                return

            if parsed.path == "/api/model":
                model_name = str(payload.get("model", "")).strip()
                if not model_name:
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {"ok": False, "error": "model is required"},
                    )
                    return
                self._write_json(HTTPStatus.OK, self._service().switch_model(model_name))
                return

            if parsed.path == "/api/review":
                try:
                    result = review_candidate(payload.get("candidate_answer"))
                except ReviewInputError as error:
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {"ok": False, "error": "invalid_request", "detail": str(error)},
                    )
                    return
                self._write_json(HTTPStatus.OK, result)
                return

            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        except ExactCallError as error:
            self._write_cpl_error(error)
        except Exception as error:  # pragma: no cover - local debugging path
            if DEBUG_RAW_RESPONSE:
                traceback.print_exc()
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "internal_error"},
            )

    def _handle_nonzero(self, method, parsed, payload):
        from nonzero_cloudops import NonZeroError
        try:
            if parsed.query or parsed.fragment:
                raise NonZeroError('NONZERO_QUERY_NOT_ALLOWED', 400)
            if method == 'GET' and parsed.path == '/api/nonzero/status':
                self._write_json(HTTPStatus.OK, self._service().runtime.nonzero_status())
                return
            service = self._service().runtime.nonzero_cloudops
            if method == 'GET' and parsed.path == '/api/nonzero/trace':
                self._write_json(HTTPStatus.OK, service.trace(operator=True))
                return
            path = '/ready' if parsed.path == '/api/nonzero/ready' else parsed.path.replace('/api/nonzero/', '/api/', 1)
            status, result = service.request(method, path, payload, operator=True)
            self._write_json(status, result)
        except NonZeroError as error:
            self._write_json(error.status, {'ok': False, 'error': error.code})
        except Exception:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {'ok': False, 'error': 'NONZERO_STATE_OR_DEPENDENCY_UNAVAILABLE'})

    def _check_memory_patch_operator(self):
        from runtime.memory_patch.contract import OPERATOR_INTENT

        if not self._check_token():
            return False
        if self.headers.get_all("X-AIOA-Intent", []) != [OPERATOR_INTENT]:
            self._write_json(
                HTTPStatus.FORBIDDEN, {"ok": False, "error": "operator_intent_required"}
            )
            return False
        return True

    def _handle_memory_patch(self, method, parsed, payload):
        from runtime.memory_patch.contract import OPERATION_CAPABILITIES
        from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
        from runtime.memory_patch.views import error_response

        operation = "invalid"
        try:
            if (
                parsed.query
                or parsed.fragment
                or parsed.params
                or not parsed.path.startswith("/api/memory-patch/")
            ):
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
            operation = parsed.path.removeprefix("/api/memory-patch/")
            if operation != "status" and operation not in OPERATION_CAPABILITIES:
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
            if method == "GET" and operation not in {"status", "list", "review-queue"}:
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
            status, result = self._service().runtime.memory_patch_operator_request(
                operation, payload
            )
        except Exception as error:
            status, result = error_response(operation, error)
        self._write_json(status, result)

    def _check_local_request(self):
        port = self.server.server_address[1]
        allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        hosts = self.headers.get_all('Host', [])
        origins = self.headers.get_all('Origin', [])
        valid_origin = not origins or (len(origins) == 1 and origins[0] in {'http://' + host for host in allowed_hosts})
        if (len(hosts) != 1 or hosts[0].lower() not in allowed_hosts or not valid_origin
                or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
            self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'local_origin_required'})
            return False
        return True

    def _check_token(self):
        values = self.headers.get_all('X-AIOA-Session-Token', [])
        if len(values) != 1 or not hmac.compare_digest(values[0].encode('utf-8'), self._service().csrf_token.encode('ascii')):
            self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'session_token_required'})
            return False
        return True

    def _write_cpl_error(self, error):
        conflicts = {'AUTHORIZATION_ALREADY_CONSUMED', 'CPL_WORKER_BUSY', 'PLAN_EXPIRED', 'RUN_TERMINAL'}
        status = HTTPStatus.CONFLICT if error.code in conflicts else HTTPStatus.BAD_REQUEST
        if error.code in {'RUN_NOT_FOUND', 'PLAN_NOT_AVAILABLE'}:
            status = HTTPStatus.NOT_FOUND
        self._write_json(status, {'ok': False, 'error': error.code})

    def log_message(self, format: str, *args: object) -> None:
        # Request bodies and candidate answers are never logged.
        return

    def _read_json_body(self) -> dict | None:
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            self._write_json(HTTPStatus.BAD_REQUEST, {'ok': False, 'error': 'invalid_body_framing'})
            return None
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_content_length"},
            )
            return None
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._write_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"ok": False, "error": "request_size_out_of_bounds"},
            )
            return None
        self.connection.settimeout(5)
        try:
            raw_body = self.rfile.read(length)
        except (TimeoutError, OSError):
            self._write_json(HTTPStatus.REQUEST_TIMEOUT, {'ok': False, 'error': 'request_body_timeout'})
            return None
        if len(raw_body) != length:
            self._write_json(HTTPStatus.BAD_REQUEST, {'ok': False, 'error': 'incomplete_request_body'})
            return None
        try:
            payload = json.loads(raw_body.decode("utf-8"), object_pairs_hook=_unique_object,
                                 parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
        except (UnicodeDecodeError, ValueError, RecursionError):
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_json_body"},
            )
            return None
        if not isinstance(payload, dict):
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "request_body_must_be_an_object"},
            )
            return None
        return payload

    def _write_json(self, status: HTTPStatus, payload: object) -> None:
        if urlparse(self.path).path.startswith("/api/memory-patch") and (
            not isinstance(payload, dict)
            or set(payload) != {"ok", "module", "operation", "result", "error"}
        ):
            # Shared Core admission/framing failures also use the closed native
            # envelope. No raw Core exception or request echo crosses this route.
            from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
            from runtime.memory_patch.views import error_response

            code = (
                ErrorCode.ADMISSION_DENIED
                if status == HTTPStatus.FORBIDDEN
                else ErrorCode.INVALID_REQUEST
            )
            _, payload = error_response("invalid", MemoryPatchError(code))
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(
    host: str = HOST,
    port: int = PORT,
    service: WebRuntimeService | None = None,
) -> ThreadingHTTPServer:
    """Create the single local AOIA-Core server."""

    if host not in LOOPBACK_HOSTS:
        raise ValueError("AOIA-Core web UI may bind only to a loopback interface")
    handler = partial(AOIAWebHandler, service=service)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local AIOA spArkHAT web interface (formerly AOIA-Core).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--cpl-fixture', action='store_true', help='Explicit local synthetic HTTP transport; no model API')
    mode.add_argument('--cpl-live-policy', help='Operator-authored price/budget policy JSON; still requires per-plan approval')
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", default=PORT, type=int)
    return parser


def main() -> None:
    args = _parser().parse_args()
    from critical_loop.policy import load_cost_policy
    policy = load_cost_policy(args.cpl_live_policy) if args.cpl_live_policy else None
    service = WebRuntimeService(cpl_fixture=args.cpl_fixture, cpl_cost_policy=policy)
    server = make_server(args.host, args.port, service)
    address, bound_port = server.server_address[:2]
    print(f"AIOA spArkHAT web UI running on http://{address}:{bound_port}")
    print("One local runtime | dated evidence review | human authority retained")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__":
    main()
