"""Minimal standard-library HTTP server for the loopback Local-2 application."""

import json
import os
import secrets
import stat
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore

from .application import LocalApiApplication
from .auth import LocalApiTokenAuthorizer
from .contracts import (
    LOCAL_API_BODY_MAX_BYTES,
    LOCAL_API_HEADER_MAX_COUNT,
    LOCAL_API_MAX_CONCURRENT_REQUESTS,
    LOCAL_API_SOCKET_TIMEOUT_SECONDS,
    LocalApiErrorCode,
)

_LOOPBACK_HOST = "127.0.0.1"
_ERROR_HEADERS = {
    "cache-control": "no-store",
    "content-security-policy": "default-src 'none';base-uri 'none';frame-ancestors 'none'",
    "content-type": "application/json",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


class _BoundedLocalHttpServer(ThreadingHTTPServer):
    """Bound handler threads and socket waits for the resource-constrained judge host."""

    daemon_threads = True
    block_on_close = True
    request_queue_size = LOCAL_API_MAX_CONCURRENT_REQUESTS
    max_concurrent_requests = LOCAL_API_MAX_CONCURRENT_REQUESTS

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._request_slots = BoundedSemaphore(self.max_concurrent_requests)
        super().__init__(*args, **kwargs)

    def get_request(self) -> tuple[object, object]:
        connection, address = super().get_request()
        connection.settimeout(LOCAL_API_SOCKET_TIMEOUT_SECONDS)
        return connection, address

    def process_request(self, request: object, client_address: object) -> None:
        self._request_slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request: object, client_address: object) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


def load_or_create_local_token(
    path: str | Path,
    *,
    token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(48),
) -> str:
    """Load an owner-only token or create it once without following symlinks."""

    resolved = Path(path) if isinstance(path, (str, Path)) else None
    if resolved is None or not str(resolved).strip():
        raise ValueError("local API token path must be a non-empty path")
    if ".." in resolved.parts or len(os.fsencode(resolved)) > 4_096:
        raise ValueError("local API token path contains unsafe traversal or length")
    if not callable(token_factory):
        raise TypeError("token_factory must be callable")
    if resolved.is_symlink() or any(
        parent.is_symlink() for parent in resolved.parents if parent.exists()
    ):
        raise RuntimeError("local API token must be a regular file")
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RuntimeError("local API token directory is unavailable") from error

    def load() -> str:
        descriptor = -1
        try:
            if resolved.is_symlink():
                raise RuntimeError("local API token must be a regular file")
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(resolved, flags)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError("local API token must be a regular file")
            if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
                raise RuntimeError("local API token must be owner-only (mode 0600)")
            if metadata.st_size > 1_024:
                raise RuntimeError("local API token file is invalid")
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                descriptor = -1
                token = handle.read(1_025).removesuffix("\n")
            LocalApiTokenAuthorizer(token)
            return token
        except (OSError, UnicodeError, ValueError) as error:
            raise RuntimeError("local API token is unavailable or invalid") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    if resolved.exists() or resolved.is_symlink():
        return load()
    token = token_factory()
    LocalApiTokenAuthorizer(token)
    descriptor = -1
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved, flags, 0o600)
        payload = f"{token}\n".encode()
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        directory_descriptor = os.open(resolved.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except FileExistsError:
        if descriptor >= 0:
            os.close(descriptor)
        return load()
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise RuntimeError("local API token could not be created") from error
    return token


def _direct_error(status_code: int, code: LocalApiErrorCode) -> dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": dict(_ERROR_HEADERS),
        "body": json.dumps(
            {"error": code.value, "ok": False, "retryable": False},
            separators=(",", ":"),
            sort_keys=True,
        ),
    }


def create_local_http_server(
    application: LocalApiApplication,
    *,
    host: str = _LOOPBACK_HOST,
    port: int = 8765,
    allow_container_binding: bool = False,
) -> ThreadingHTTPServer:
    """Create a bounded server; non-loopback binding requires explicit container intent."""

    if not isinstance(application, LocalApiApplication):
        raise TypeError("application must be LocalApiApplication")
    if host != _LOOPBACK_HOST and not (
        allow_container_binding and host == "0.0.0.0"
    ):
        raise ValueError("local API may bind only to 127.0.0.1")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65_535:
        raise ValueError("port must be between 0 and 65535")

    class LocalRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "AIOALocal/1"
        sys_version = ""

        def _dispatch(self) -> None:
            if not self.path.startswith("/") or "#" in self.path:
                self._send(_direct_error(400, LocalApiErrorCode.BAD_REQUEST))
                return
            path, separator, query = self.path.partition("?")
            normalized_headers: dict[str, str] = {}
            for name in self.headers:
                values = self.headers.get_all(name, failobj=[])
                normalized = name.casefold()
                if len(values) != 1 or normalized in normalized_headers:
                    self._send(_direct_error(400, LocalApiErrorCode.BAD_REQUEST))
                    return
                normalized_headers[normalized] = values[0]
            if len(normalized_headers) > LOCAL_API_HEADER_MAX_COUNT:
                self._send(_direct_error(400, LocalApiErrorCode.BAD_REQUEST))
                return
            if "transfer-encoding" in normalized_headers:
                self.close_connection = True
                self._send(_direct_error(400, LocalApiErrorCode.BAD_REQUEST))
                return
            raw_length = normalized_headers.get("content-length")
            length = 0
            if raw_length is not None:
                try:
                    length = int(raw_length)
                except ValueError:
                    self.close_connection = True
                    self._send(_direct_error(400, LocalApiErrorCode.BAD_REQUEST))
                    return
                if length < 0:
                    self.close_connection = True
                    self._send(_direct_error(400, LocalApiErrorCode.BAD_REQUEST))
                    return
            if length > LOCAL_API_BODY_MAX_BYTES:
                self.close_connection = True
                self._send(_direct_error(413, LocalApiErrorCode.PAYLOAD_TOO_LARGE))
                return
            body: str | None = None
            if length:
                try:
                    body = self.rfile.read(length).decode("utf-8", errors="strict")
                except TimeoutError:
                    self.close_connection = True
                    self._send(_direct_error(408, LocalApiErrorCode.REQUEST_TIMEOUT))
                    return
                except OSError:
                    self.close_connection = True
                    return
                except UnicodeError:
                    self._send(_direct_error(400, LocalApiErrorCode.BAD_REQUEST))
                    return
            response = application.handle(
                {
                    "method": self.command,
                    "path": path,
                    "headers": normalized_headers,
                    "body": body,
                    "query": query if separator else "",
                }
            )
            self._send(response)

        def _send(self, response: dict[str, object]) -> None:
            status_code = response.get("statusCode")
            body = response.get("body")
            headers = response.get("headers")
            if (
                not isinstance(status_code, int)
                or not isinstance(body, str)
                or not isinstance(headers, dict)
            ):
                status_code = 500
                body = str(_direct_error(500, LocalApiErrorCode.INTERNAL_ERROR)["body"])
                headers = dict(_ERROR_HEADERS)
            payload = body.encode("utf-8")
            self.send_response(status_code)
            for name, value in headers.items():
                if isinstance(name, str) and isinstance(value, str):
                    self.send_header(name, value)
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        do_DELETE = _dispatch
        do_GET = _dispatch
        do_HEAD = _dispatch
        do_OPTIONS = _dispatch
        do_PATCH = _dispatch
        do_POST = _dispatch
        do_PUT = _dispatch

        def log_message(self, _format: str, *args: object) -> None:
            """Suppress default logging so authorization values cannot leak."""

    return _BoundedLocalHttpServer((host, port), LocalRequestHandler)
