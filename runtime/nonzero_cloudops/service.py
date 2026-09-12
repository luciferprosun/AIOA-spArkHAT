"""Thin operator-only adapter over the original portable LocalApiApplication."""
from __future__ import annotations

import fcntl
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import secrets
import stat
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from tools.provenance import AppendOnlyProvenanceStore, verify_provenance_chain

JUDGE_SHA = '4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a'
BASELINE = Path(__file__).resolve().parent / 'baseline'
_SOURCE = BASELINE / 'src'
_IMPORT_LOCK = threading.Lock()
_DEPENDENCIES = {'pydantic': '2.13.4', 'strands-agents': '1.53.0', 'uuid6': '2025.0.1'}
_RUN = r'[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'
_READ = re.compile(r'/api/runs/' + _RUN)
_WRITE = re.compile(r'/api/runs/' + _RUN + r'/(approval-request|decision|resume)')
_PRIVATE_FIELDS = {'decision_nonce', 'decision_nonce_hash', 'actor_session_id', 'authorization', 'token'}


class NonZeroError(RuntimeError):
    """Fixed public error code; never include raw exception or secret values."""
    def __init__(self, code: str, status: int = 503):
        super().__init__(code)
        self.code, self.status = code, status


def module_descriptor() -> dict:
    missing = []
    if sys.version_info < (3, 12):
        missing.append('python>=3.12')
    for package, expected in _DEPENDENCIES.items():
        try:
            if importlib.metadata.version(package) != expected:
                missing.append(package + '==' + expected)
        except importlib.metadata.PackageNotFoundError:
            missing.append(package + '==' + expected)
    if not (_SOURCE / 'aioa_cloudops_agent/local_api/application.py').is_file():
        missing.append('bundled-baseline')
    return {'module': 'nonzero-cloudops-agent', 'product_name': 'AIOA spArkHAT',
            'registered': True, 'available': not missing, 'missing_requirements': missing,
            'source_sha': JUDGE_SHA, 'mode': 'portable', 'provider': 'mock',
            'authority': 'EXPLICIT_HUMAN_APPROVAL_SYNTHETIC_ONLY',
            'live_aws_enabled': False, 'external_models_enabled': False,
            'command': '/nonzero', 'api_prefix': '/api/nonzero'}


def _load_baseline():
    if not module_descriptor()['available']:
        raise NonZeroError('NONZERO_OPTIONAL_DEPENDENCIES_UNAVAILABLE')
    with _IMPORT_LOCK:
        # Follow Core's existing facade, limited to THIS bundled source.
        for name, module in tuple(sys.modules.items()):
            if name == 'aioa_cloudops_agent' or name.startswith('aioa_cloudops_agent.'):
                origin = getattr(module, '__file__', None)
                if origin is not None and not Path(origin).resolve().is_relative_to(_SOURCE):
                    raise NonZeroError('NONZERO_SOURCE_IDENTITY_MISMATCH')
        if str(_SOURCE) not in sys.path:
            sys.path.insert(0, str(_SOURCE))
        return importlib.import_module('aioa_cloudops_agent.local_api.application')


def _private_file(path: Path, *, create: bool = False) -> int:
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0), 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        os.close(fd)
        raise NonZeroError('NONZERO_UNSAFE_STATE_FILE')
    return fd


def _public_evidence(value):
    if isinstance(value, dict):
        return {k: _public_evidence(v) for k, v in value.items() if k not in _PRIVATE_FIELDS}
    if isinstance(value, list):
        return [_public_evidence(v) for v in value]
    return value


class NonZeroCloudOpsService:
    """One leased local workflow; no cloud, shell, URL or path selection in API.

    operator=True is supplied by the local CLI or by the Core HTTP boundary
    after Host/Origin/session-token/intent checks, never from JSON or a model.
    """
    def __init__(self, state_dir: Path, *, guard: Callable[[], bool] | None = None):
        self._lock = threading.RLock()
        self._lease = None
        self._closed = False
        self._guard = guard or (lambda: False)
        app_module = _load_baseline()
        root = Path(state_dir).absolute()
        if '..' in root.parts or any(p.is_symlink() for p in (root, *root.parents)):
            raise NonZeroError('NONZERO_UNSAFE_STATE_PATH')
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if root.stat().st_uid != os.getuid() or stat.S_IMODE(root.stat().st_mode) & 0o077:
            raise NonZeroError('NONZERO_UNSAFE_STATE_DIRECTORY')
        try:
            self._lease = _private_file(root / 'service.lock', create=True)
            try:
                fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise NonZeroError('NONZERO_STATE_ALREADY_OWNED', 409) from error
            token_path = root / 'operator.credential'
            try:
                fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                fd = _private_file(token_path)
                with os.fdopen(fd, 'r') as stored:
                    token = stored.read(257)
            else:
                token = secrets.token_urlsafe(32)
                with os.fdopen(fd, 'w') as stored:
                    stored.write(token)
                    stored.flush()
                    os.fsync(stored.fileno())
            if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
                raise NonZeroError('NONZERO_INVALID_STATE_CREDENTIAL')
            from aioa_cloudops_agent.agent.local_composition import (
                create_local_hitl_runtime,
            )
            from aioa_cloudops_agent.config import LocalHitlSettings, RuntimeSettings
            from aioa_cloudops_agent.local_api.auth import LocalApiTokenAuthorizer
            # Environment variables can NEVER select AWS: explicit constructors.
            self._runtime = create_local_hitl_runtime(LocalHitlSettings(
                state_path=root / 'durable-truth.json', inventory_path=root / 'mock-inventory.json'),
                runtime_settings=RuntimeSettings())
            self._application = app_module.LocalApiApplication(self._runtime, LocalApiTokenAuthorizer(token))
            self._authorization = 'Bearer ' + token
            self.provenance = AppendOnlyProvenanceStore(root)
            if not verify_provenance_chain(self.provenance.read_all()).ok:
                raise NonZeroError('NONZERO_PROVENANCE_CORRUPT', 409)
        except Exception:
            self.close()
            raise

    def status(self):
        return {**module_descriptor(), 'initialized': True, 'closed': self._closed}

    def trace(self, *, operator: bool = False):
        if operator is not True:
            raise NonZeroError('NONZERO_OPERATOR_REQUIRED', 403)
        with self._lock:
            entries = self.provenance.read_all()
            result = verify_provenance_chain(entries)
            return {'ok': result.ok, 'entry_count': result.entry_count,
                    'terminal_hash': result.terminal_hash, 'entries': entries,
                    'meaning': 'Integrity/linkage only; hashes do not prove factual truth.'}

    def request(self, method: str, path: str, payload=None, *, operator: bool = False):
        if operator is not True:
            raise NonZeroError('NONZERO_OPERATOR_REQUIRED', 403)
        if not isinstance(path, str) or not ((method == 'GET' and (path == '/ready' or _READ.fullmatch(path)))
                or (method == 'POST' and (path == '/api/runs' or _WRITE.fullmatch(path)))):
            raise NonZeroError('NONZERO_ROUTE_NOT_ALLOWED', 404)
        if (method == 'GET' and payload is not None) or (method == 'POST' and not isinstance(payload, dict)):
            raise NonZeroError('NONZERO_INVALID_REQUEST', 400)
        try:
            body = None if payload is None else json.dumps(payload, allow_nan=False)
        except (TypeError, ValueError, RecursionError) as error:
            raise NonZeroError('NONZERO_INVALID_REQUEST', 400) from error
        if body is not None and len(body.encode()) > 16384:
            raise NonZeroError('NONZERO_REQUEST_TOO_LARGE', 413)
        with self._lock:
            if self._closed:
                raise NonZeroError('NONZERO_SERVICE_CLOSED')
            if self._guard() and method == 'POST':
                raise NonZeroError('EPISTEMIC_KILL_SWITCH', 403)
            if not verify_provenance_chain(self.provenance.read_all()).ok:
                raise NonZeroError('NONZERO_PROVENANCE_CORRUPT', 409)
            operation_id = secrets.token_hex(16)
            if method == 'POST':
                # Durable intent before delegation, without request bodies/nonces.
                self.provenance.append_event('nonzero_operator_request', {
                    'operation_id': operation_id, 'method': method, 'path': path, 'source_sha': JUDGE_SHA})
            response = self._application.handle({'method': method, 'path': path, 'body': body,
                'headers': {'authorization': self._authorization, 'content-type': 'application/json'}})
            result = json.loads(response['body'])
            if method == 'POST':
                evidence = _public_evidence(result)
                self.provenance.append_event('nonzero_operator_result', {
                    'operation_id': operation_id, 'source_sha': JUDGE_SHA,
                    'status_code': response['statusCode'], 'evidence': evidence,
                    'evidence_sha256': hashlib.sha256(json.dumps(evidence, sort_keys=True,
                        separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()})
            return response['statusCode'], result

    def close(self):
        with self._lock:
            self._closed = True
            if self._lease is not None:
                os.close(self._lease)
                self._lease = None
