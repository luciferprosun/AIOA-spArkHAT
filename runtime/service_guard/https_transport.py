"""One-attempt typed HTTPS transport for the Nebius Serverless target.

The transport has no retry or redirect path.  It is injected below the
existing ServiceGuard through ``CloudEffectTargetClient`` and has no authority
to create or change an effect command.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import math
import os
import ssl
from urllib.parse import urlsplit

from runtime.service_guard.contracts import GuardError
from runtime.service_guard.target import TargetUnknown


_SCHEMA = "aioa.nebius-serverless-target.v1"
_ACTIONS = frozenset({"READ_STATE", "READ_RECEIPT", "APPLY_SET_MAINTENANCE"})


def validate_serverless_endpoint(value: str, *, transport_scope: str = "LIVE") -> str:
    if type(value) is not str or not value.strip() or len(value) > 2048:
        raise GuardError("INVALID_SERVERLESS_ENDPOINT")
    if transport_scope not in {"LIVE", "TEST"}:
        raise GuardError("INVALID_SERVERLESS_TRANSPORT_SCOPE")
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        raise GuardError("INVALID_SERVERLESS_ENDPOINT") from None
    host = (parsed.hostname or "").lower()
    path = parsed.path
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not host
        or not path.startswith("/")
        or path == "/"
        or "\\" in path
        or "%" in path
        or "//" in path
        or any(segment in {".", ".."} for segment in path.split("/"))
    ):
        raise GuardError("INVALID_SERVERLESS_ENDPOINT")
    if transport_scope == "TEST":
        if parsed.scheme != "http" or host != "127.0.0.1" or port is None or not 1024 <= port <= 65535:
            raise GuardError("INVALID_SERVERLESS_ENDPOINT")
        return f"http://127.0.0.1:{port}{path}"
    if parsed.scheme != "https" or port not in {None, 443}:
        raise GuardError("INVALID_SERVERLESS_ENDPOINT")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise GuardError("INVALID_SERVERLESS_ENDPOINT")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise GuardError("INVALID_SERVERLESS_ENDPOINT")
    if address is None and ("." not in host or host.startswith(".") or host.endswith(".")):
        raise GuardError("INVALID_SERVERLESS_ENDPOINT")
    authority = host if port is None else f"{host}:443"
    return f"https://{authority}{path}"


def _unique_object(pairs):
    result = {}
    for key, item in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = item
    return result


class NebiusHttpsEffectTransport:
    """Environment-composed typed transport with exactly one HTTP attempt."""

    __slots__ = (
        "endpoint_url", "_auth_token", "timeout_seconds", "max_response_bytes",
        "transport_scope", "_parsed",
    )

    def __init__(
        self,
        *,
        endpoint_url: str,
        auth_token: str,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 16384,
        transport_scope: str = "LIVE",
    ):
        endpoint = validate_serverless_endpoint(
            endpoint_url, transport_scope=transport_scope
        )
        if type(auth_token) is not str or not auth_token.strip() or len(auth_token) > 4096:
            raise GuardError("SERVERLESS_AUTH_REQUIRED")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0.01 <= timeout_seconds <= 30
        ):
            raise GuardError("INVALID_SERVERLESS_TIMEOUT")
        if type(max_response_bytes) is not int or not 512 <= max_response_bytes <= 65536:
            raise GuardError("INVALID_SERVERLESS_RESPONSE_LIMIT")
        self.endpoint_url = endpoint
        self._auth_token = auth_token.strip()
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = max_response_bytes
        self.transport_scope = transport_scope
        self._parsed = urlsplit(endpoint)

    @classmethod
    def from_environment(cls, environ=None):
        values = os.environ if environ is None else environ
        if not hasattr(values, "get"):
            raise GuardError("INVALID_SERVERLESS_ENVIRONMENT")
        endpoint = values.get("NEBIUS_SERVERLESS_ENDPOINT_URL", "")
        token = values.get("NEBIUS_SERVERLESS_AUTH_TOKEN", "")
        return cls(endpoint_url=endpoint, auth_token=token, transport_scope="LIVE")

    def invoke(self, request: dict):
        if (
            type(request) is not dict
            or request.get("schema") != _SCHEMA
            or request.get("action") not in _ACTIONS
        ):
            raise GuardError("TARGET_OPERATION_DENIED")
        try:
            body = json.dumps(
                request, ensure_ascii=False, allow_nan=False,
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            raise GuardError("TARGET_OPERATION_DENIED") from None
        if len(body) > 32768:
            raise GuardError("TARGET_OPERATION_DENIED")

        parsed = self._parsed
        connection_class = (
            http.client.HTTPConnection
            if self.transport_scope == "TEST"
            else http.client.HTTPSConnection
        )
        kwargs = {} if self.transport_scope == "TEST" else {"context": ssl.create_default_context()}
        connection = connection_class(
            parsed.hostname,
            parsed.port,
            timeout=self.timeout_seconds,
            **kwargs,
        )
        try:
            connection.request(
                "POST",
                parsed.path,
                body=body,
                headers={
                    "Authorization": "Bearer " + self._auth_token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            length = response.getheader("Content-Length")
            content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
            if (
                response.status != 200
                or content_type != "application/json"
                or (length is not None and (not length.isdigit() or int(length) > self.max_response_bytes))
            ):
                raise TargetUnknown()
            raw = response.read(self.max_response_bytes + 1)
            if len(raw) > self.max_response_bytes:
                raise TargetUnknown()
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
            if value is None and request["action"] == "READ_RECEIPT":
                return None
            if type(value) is not dict:
                raise ValueError("response object required")
            return value
        except GuardError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException, UnicodeError,
                ValueError, json.JSONDecodeError, RecursionError):
            raise TargetUnknown() from None
        finally:
            connection.close()

