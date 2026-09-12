"""Bounded CPL view over the runtime's existing append-only provenance store.

Hashes prove recorded integrity relative to a retained manifest, not truth,
trusted time, authorship, or protection against rewriting log AND manifest.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import uuid

from tools.provenance import AppendOnlyProvenanceStore, verify_provenance_chain
from providers.exact import ExactCallError
from .policy import BASE_IMPLEMENTATION_COMMIT, CONTRACT_VERSION, PROMPT_VERSION
from .redaction import redact_secret_data

MAX_TRACE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_RUNS = 64
MAX_EVENTS = 24
SCHEMA_VERSION = 'cpl-trace-v1'
REDACTION_VERSION = 'cpl-redaction-v1'
CANONICALIZATION = 'runtime-provenance-json-sort-keys-utf8-v1'


def valid_run_id(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r'cpl-[a-f0-9]{32}', run_id):
        raise ExactCallError('INVALID_RUN_ID')
    return run_id


class CPLTraceStore:
    def __init__(self, root: Path, known_secrets=()):
        self.root = Path(root)
        if any(path.is_symlink() for path in [self.root, *self.root.parents]):
            raise ExactCallError('UNSAFE_TRACE_ROOT')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = self.root.resolve()
        self.known_secrets = tuple(known_secrets)
        self._owner_fd = None

    def acquire_owner(self):
        """One runtime process per state root; never interrupt a live peer."""
        fd = os.open(self.root / '.owner.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise ExactCallError('CPL_STATE_ROOT_IN_USE') from None
        self._owner_fd = fd

    def release_owner(self):
        if self._owner_fd is not None:
            fcntl.flock(self._owner_fd, fcntl.LOCK_UN)
            os.close(self._owner_fd)
            self._owner_fd = None

    def _dir(self, run_id):
        path = self.root / valid_run_id(run_id)
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ExactCallError('UNSAFE_TRACE_PATH')
        for child in (path / 'provenance', path / 'provenance/provenance_log.jsonl', path / 'manifest.json'):
            if child.is_symlink():
                raise ExactCallError('UNSAFE_TRACE_PATH')
        return path

    def run_ids(self):
        runs = sorted(p.name for p in self.root.iterdir() if p.name.startswith('cpl-'))
        if len(runs) > MAX_RUNS:
            raise ExactCallError('TRACE_QUOTA_EXCEEDED')
        for run in runs:
            self._dir(run)
        return runs

    def create(self, run_id):
        if len(self.run_ids()) >= MAX_RUNS:
            raise ExactCallError('TRACE_QUOTA_EXCEEDED')
        total = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
        if total + MAX_TRACE_BYTES > MAX_TOTAL_BYTES:
            raise ExactCallError('TRACE_QUOTA_EXCEEDED')
        self._dir(run_id).mkdir(mode=0o700)

    def _store(self, run_id):
        directory = self._dir(run_id)
        if not directory.is_dir():
            raise ExactCallError('RUN_NOT_FOUND')
        store = AppendOnlyProvenanceStore(directory, clock=lambda: dt.datetime.now(dt.timezone.utc))
        if store.log_path.exists() and store.log_path.stat().st_size > MAX_TRACE_BYTES:
            raise ExactCallError('TRACE_SIZE_EXCEEDED')
        return store

    def append(self, run_id, phase, view):
        store = self._store(run_id)
        entries = store.read_all()
        if len(entries) >= MAX_EVENTS:
            raise ExactCallError('TRACE_EVENT_LIMIT')
        safe_view = redact_secret_data(view, known_secrets=self.known_secrets)
        payload = {'schema_version': SCHEMA_VERSION, 'run_id': run_id, 'trace_id': run_id,
                   'event_id': f'{run_id}:{len(entries) + 1}', 'sequence': len(entries) + 1,
                   'phase': phase, 'time_source': 'LOCAL_SYSTEM_CLOCK_UTC_UNATTESTED',
                   'contract_version': CONTRACT_VERSION, 'prompt_version': PROMPT_VERSION,
                   'base_implementation_commit': BASE_IMPLEMENTATION_COMMIT,
                   'canonicalization': CANONICALIZATION, 'redaction_version': REDACTION_VERSION,
                   'view': safe_view}
        # Reject NaN/Infinity before the shared historical canonicalizer sees it.
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        current_size = store.log_path.stat().st_size if store.log_path.exists() else 0
        if current_size + len(encoded) + 2048 > MAX_TRACE_BYTES:
            raise ExactCallError('TRACE_SIZE_EXCEEDED')
        entry = store.append_event('CPL_' + phase, payload)
        os.chmod(store.log_path, 0o600)
        with store.log_path.open('rb') as durable_log:
            os.fsync(durable_log.fileno())
        manifest = {'schema_version': SCHEMA_VERSION, 'run_id': run_id,
                    'event_count': len(entries) + 1, 'terminal_hash': entry['entry_hash'],
                    'canonicalization': CANONICALIZATION, 'redaction_version': REDACTION_VERSION}
        directory = self._dir(run_id)
        temporary = directory / ('.manifest-' + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(manifest, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / 'manifest.json')
        return manifest

    def verify(self, run_id, reference_manifest=None):
        if not (self._dir(run_id) / 'provenance/provenance_log.jsonl').is_file():
            raise ExactCallError('TRACE_LOG_MISSING')
        store = self._store(run_id)
        path = self._dir(run_id) / 'manifest.json'
        if not path.is_file() or path.stat().st_size > 8192:
            raise ExactCallError('INVALID_TRACE_MANIFEST')
        try:
            manifest = json.loads(path.read_text())
            entries = store.read_all()
            if len(entries) > MAX_EVENTS:
                raise ValueError()
            verification = verify_provenance_chain(entries)
            issues = list(verification.issues)
            for index, entry in enumerate(entries, 1):
                payload = entry.get('payload', {})
                if (payload.get('run_id') != run_id or payload.get('trace_id') != run_id
                        or payload.get('sequence') != index
                        or payload.get('event_id') != f'{run_id}:{index}'
                        or payload.get('schema_version') != SCHEMA_VERSION
                        or payload.get('view', {}).get('run_id') != run_id
                        or entry.get('event_type') != 'CPL_' + str(payload.get('phase'))):
                    issues.append('event_contract_mismatch')
            for point in [manifest] + ([reference_manifest] if reference_manifest is not None else []):
                if (not isinstance(point, dict) or point.get('run_id') != run_id
                        or point.get('event_count') != verification.entry_count
                        or point.get('terminal_hash') != verification.terminal_hash
                        or point.get('schema_version') != SCHEMA_VERSION):
                    issues.append('manifest_reference_mismatch')
            if not entries:
                issues.append('empty_trace')
            return {'ok': not issues, 'run_id': run_id, 'event_count': len(entries),
                    'terminal_hash': verification.terminal_hash, 'issues': issues,
                    'manifest': manifest, 'authority': 'INTEGRITY_ONLY_NOT_TRUTH',
                    'external_reference_checked': reference_manifest is not None}
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise ExactCallError('INVALID_TRACE_DATA') from None

    def reopen(self, run_id):
        verification = self.verify(run_id)
        if not verification['ok']:
            raise ExactCallError('TRACE_INTEGRITY_FAILED')
        entries = self._store(run_id).read_all()
        view = entries[-1]['payload']['view']
        view['evidence_chain'] = verification
        return view
