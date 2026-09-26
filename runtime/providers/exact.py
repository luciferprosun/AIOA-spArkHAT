"""Bounded, one-attempt exact provider transport; independent of agent actions.

The ordinary provider path retains its existing policy. This module never
retries, follows redirects, uses proxies, chooses a model, or supplies a
missing response identity. Cancellation cannot revoke provider-side billing.
"""
from __future__ import annotations

import http.client
import json
import math
import re
import socket
import ssl
import threading
import time
from dataclasses import asdict, dataclass, replace
from urllib.parse import urlsplit

from .messages import ChatMessage


class ExactCallError(RuntimeError):
    """Public-safe error code; never includes provider body or credentials."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._connection: http.client.HTTPConnection | None = None
        self._socket = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self, deadline: float) -> None:
        if self.cancelled:
            raise ExactCallError('CANCELLED')
        if time.monotonic() >= deadline:
            raise ExactCallError('DEADLINE_EXCEEDED')

    def attach(self, connection):
        with self._lock:
            if self.cancelled:
                raise ExactCallError('CANCELLED')
            self._connection = connection

    def detach(self):
        with self._lock:
            self._connection = None
            self._socket = None

    def track_socket(self, sock):
        with self._lock:
            self._socket = sock
        if self.cancelled:
            self.cancel()

    def cancel(self):
        self._event.set()
        self.interrupt_transport()

    def interrupt_transport(self):
        with self._lock:
            connection = self._connection
            sock = self._socket
        # No worker/service lock is held while a socket is interrupted.
        if connection is not None:
            try:
                active_socket = sock if sock is not None else connection.sock
                if active_socket is not None:
                    active_socket.shutdown(socket.SHUT_RDWR)
                connection.close()
            except OSError:
                pass


@dataclass(frozen=True)
class ExactRequest:
    provider_connection_id: str
    requested_model: str
    messages: tuple[ChatMessage, ...]
    max_output_tokens: int
    max_input_tokens: int = 32768
    max_response_bytes: int = 65536
    timeout_seconds: float = 20.0
    response_schema_json: str | None = None
    transport_scope: str = 'LIVE'

    def validate(self):
        if self.provider_connection_id not in {'openrouter', 'nebius'}:
            raise ExactCallError('UNSUPPORTED_STRICT_CPL')
        if (not isinstance(self.requested_model, str)
                or len(self.requested_model) > 180
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*', self.requested_model)
                or (self.provider_connection_id == 'openrouter'
                    and self.requested_model.lower() in {'openrouter/auto', 'openrouter/free', 'openrouter/router', 'free/router'})):
            raise ExactCallError('EXACT_MODEL_REQUIRED')
        for value, maximum in [(self.max_output_tokens, 4096),
                               (self.max_input_tokens, 65536), (self.max_response_bytes, 262144)]:
            if type(value) is not int or not 1 <= value <= maximum:
                raise ExactCallError('INVALID_REQUEST_LIMIT')
        if (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (float, int))
                or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 30):
            raise ExactCallError('INVALID_TIMEOUT')
        if self.transport_scope not in {'TEST', 'LIVE'}:
            raise ExactCallError('INVALID_TRANSPORT_SCOPE')
        if not isinstance(self.messages, tuple) or not 1 <= len(self.messages) <= 8:
            raise ExactCallError('INVALID_MESSAGES')
        for message in self.messages:
            if (not isinstance(message, ChatMessage) or message.role not in {'system', 'user', 'assistant'}
                    or not isinstance(message.content, str) or not message.content.strip()):
                raise ExactCallError('INVALID_MESSAGES')
        # Conservative admission units, including framing, never a claim of
        # measured usage. Live policy must explicitly acknowledge this bound.
        if self.input_bound() > self.max_input_tokens:
            raise ExactCallError('INPUT_LIMIT_EXCEEDED')

    def input_bound(self) -> int:
        schema_bound = len(self.response_schema_json.encode('utf-8')) + 128 if self.response_schema_json else 0
        return 32 + schema_bound + sum(len(m.content.encode('utf-8')) + 64 for m in self.messages)


@dataclass(frozen=True)
class ProviderResult:
    content: str
    provider_connection_id: str
    requested_model: str
    reported_model: str
    identity_status: str
    request_id: str | None
    usage: dict[str, int] | None
    finish_reason: str
    transport_scope: str
    latency_ms: int | None = None

    def metadata(self):
        payload = asdict(self)
        payload.pop('content')
        return payload


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def decode_response(raw: bytes, request: ExactRequest) -> ProviderResult:
    try:
        payload = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                             parse_constant=lambda _x: (_ for _ in ()).throw(ValueError('non-finite JSON')))
        if not isinstance(payload, dict):
            raise ValueError('object required')
        reported = payload.get('model')
        if not isinstance(reported, str) or not reported.strip():
            raise ExactCallError('MISSING_REPORTED_MODEL')
        if reported != request.requested_model:
            raise ExactCallError('MODEL_IDENTITY_MISMATCH')
        choices = payload.get('choices')
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError('one choice required')
        choice = choices[0]
        content = choice['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise ValueError('content required')
        if choice.get('finish_reason') != 'stop':
            raise ExactCallError('INCOMPLETE_COMPLETION')
        if len(content.encode('utf-8')) > request.max_output_tokens * 16:
            raise ExactCallError('OUTPUT_SIZE_EXCEEDED')
        usage = payload.get('usage')
        if usage is not None:
            if not isinstance(usage, dict):
                raise ValueError('usage must be an object')
            # Missing usage stays missing, including missing individual fields.
            usage = {key: usage[key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens') if key in usage}
            if any(type(value) is not int or value < 0 for value in usage.values()):
                raise ValueError('invalid usage')
            if (usage.get('completion_tokens', 0) > request.max_output_tokens
                    or usage.get('prompt_tokens', 0) > request.max_input_tokens):
                raise ExactCallError('USAGE_LIMIT_EXCEEDED')
        request_id = payload.get('id')
        if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 256):
            raise ValueError('invalid request id')
        return ProviderResult(content.strip(), request.provider_connection_id, request.requested_model,
                              reported, 'EXACT_MATCH', request_id, usage, 'stop', request.transport_scope)
    except ExactCallError:
        raise
    except (UnicodeError, ValueError, KeyError, TypeError, IndexError, RecursionError) as error:
        raise ExactCallError('INVALID_PROVIDER_RESPONSE') from None


def generate_http_exact(adapter, request: ExactRequest, cancel: CancellationToken,
                        deadline: float, *, fixture: bool = False) -> ProviderResult:
    request.validate()
    cancel.check(deadline)
    if (adapter.provider != request.provider_connection_id
            or adapter.model != request.requested_model):
        raise ExactCallError('CONNECTION_BINDING_MISMATCH')
    parsed = urlsplit(adapter.base_url)
    if fixture:
        if (request.transport_scope != 'TEST' or parsed.scheme != 'http'
                or parsed.hostname != '127.0.0.1' or not parsed.port):
            raise ExactCallError('FIXTURE_LOOPBACK_ONLY')
    elif request.transport_scope != 'LIVE' or parsed.scheme != 'https':
        raise ExactCallError('UNSUPPORTED_STRICT_ENDPOINT')
    elif request.provider_connection_id == 'openrouter':
        if parsed.netloc != 'openrouter.ai' or parsed.path.rstrip('/') != '/api/v1':
            raise ExactCallError('UNSUPPORTED_STRICT_ENDPOINT')
    elif request.provider_connection_id == 'nebius':
        host = (parsed.hostname or '').lower()
        official_host = host == 'api.tokenfactory.nebius.com'
        regional_host = host.startswith('api.tokenfactory.') and host.endswith('.nebius.com')
        if (not (official_host or regional_host) or parsed.port is not None
                or parsed.path.rstrip('/') != '/v1'):
            raise ExactCallError('UNSUPPORTED_STRICT_ENDPOINT')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ExactCallError('INVALID_ENDPOINT')
    started = time.monotonic()
    payload = {'model': request.requested_model,
               'messages': [asdict(m) for m in request.messages],
               'temperature': 0, 'max_tokens': request.max_output_tokens,
               'stream': False, 'n': 1}
    if request.response_schema_json is not None:
        try:
            schema = json.loads(request.response_schema_json)
            if not isinstance(schema, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise ExactCallError('INVALID_RESPONSE_SCHEMA') from None
        payload['response_format'] = {'type': 'json_schema', 'json_schema': schema}
    body = json.dumps(payload, allow_nan=False).encode('utf-8')
    timeout = min(request.timeout_seconds, deadline - time.monotonic())
    call_deadline = min(deadline, time.monotonic() + timeout)
    connection_class = http.client.HTTPConnection if fixture else http.client.HTTPSConnection
    kwargs = {} if fixture else {'context': ssl.create_default_context()}
    connection = connection_class(parsed.hostname, parsed.port, timeout=max(.001, timeout), **kwargs)
    connection.auto_open = 0  # A cancelled connection must never silently reconnect.
    cancel.attach(connection)
    expired = threading.Event()

    def expire_transport():
        expired.set()
        cancel.interrupt_transport()

    watchdog = threading.Timer(max(.001, call_deadline - time.monotonic()), expire_transport)
    watchdog.daemon = True
    watchdog.start()

    def check_call():
        cancel.check(call_deadline)
        if expired.is_set():
            raise ExactCallError('TRANSPORT_TIMEOUT')

    try:
        check_call()
        # Resolve/connect before sending any generation body. If system DNS or
        # TLS finishes after cancellation/deadline, no request may be sent.
        connection.connect()
        transport_socket = connection.sock
        cancel.track_socket(transport_socket)
        check_call()
        if transport_socket is not None:
            transport_socket.settimeout(max(.001, call_deadline - time.monotonic()))
        connection.request('POST', parsed.path.rstrip('/') + '/chat/completions', body,
                           {'Authorization': 'Bearer ' + adapter.api_key,
                            'Content-Type': 'application/json', 'Accept': 'application/json'})
        check_call()
        response = connection.getresponse()
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdigit() or int(length) > request.max_response_bytes):
            raise ExactCallError('HTTP_BODY_LIMIT_EXCEEDED')
        chunks = []
        received = 0
        while True:
            check_call()
            if response.isclosed():
                break
            if transport_socket is not None:
                transport_socket.settimeout(max(.001, call_deadline - time.monotonic()))
            chunk = response.read1(min(8192, request.max_response_bytes + 1 - received))
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
            if received > request.max_response_bytes:
                raise ExactCallError('HTTP_BODY_LIMIT_EXCEEDED')
        check_call()
        if length is not None and received != int(length):
            raise ExactCallError('INCOMPLETE_HTTP_BODY')
        if response.status != 200:
            # The error body has already been bounded. Do not expose it at all.
            raise ExactCallError(f'PROVIDER_HTTP_{response.status}')
        result = decode_response(b''.join(chunks), request)
        return replace(result, latency_ms=max(0, int((time.monotonic() - started) * 1000)))
    except ExactCallError:
        raise
    except (TimeoutError, socket.timeout):
        raise ExactCallError('CANCELLED' if cancel.cancelled else 'TRANSPORT_TIMEOUT') from None
    except (OSError, http.client.HTTPException, ValueError):
        raise ExactCallError('CANCELLED' if cancel.cancelled else 'TRANSPORT_TIMEOUT' if expired.is_set() else 'TRANSPORT_ERROR') from None
    finally:
        watchdog.cancel()
        cancel.detach()
        connection.close()
