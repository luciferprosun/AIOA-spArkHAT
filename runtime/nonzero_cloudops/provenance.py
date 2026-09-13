"""Native linkage through Core's existing append-only provenance facility."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from tools.provenance import AppendOnlyProvenanceStore, verify_provenance_chain

from .contract import CONTRACT_VERSION, JUDGE_SHA, MODULE_ID, NonZeroError
from .state.files import (
    atomic_write_private_json,
    open_local_payload,
    read_private_json,
    seal_local_payload,
)

PRIVATE_FIELDS = {
    "decision_nonce",
    "decision_nonce_hash",
    "actor_session_id",
    "authorization",
    "token",
    "credential",
}


def public_evidence(value):
    if isinstance(value, dict):
        return {
            key: public_evidence(item)
            for key, item in value.items()
            if key not in PRIVATE_FIELDS
        }
    if isinstance(value, (tuple, list)):
        return [public_evidence(item) for item in value]
    return value


def source_identity() -> dict:
    return {
        "module": MODULE_ID,
        "contract_version": CONTRACT_VERSION,
        "source_sha": JUDGE_SHA,
    }


def private_file(path: Path, *, create: bool = False) -> int:
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0), 0o600)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        os.close(fd)
        raise NonZeroError("NONZERO_UNSAFE_STATE_FILE")
    return fd


class CoreEvidenceLink:
    """Adapter over Core ledger, not a replacement global chain implementation."""

    def __init__(self, root: Path, *, max_bytes: int, clock, create: bool = False):
        directory = root / "provenance"
        if directory.is_symlink():
            raise NonZeroError("NONZERO_UNSAFE_STATE_PATH")
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise NonZeroError("NONZERO_UNSAFE_STATE_DIRECTORY")
        self.store = AppendOnlyProvenanceStore(root, clock=clock)
        self.max_bytes = max_bytes
        self.head_path = directory / "chain-head.json"
        # Only a newly admitted empty namespace may establish an anchor. Never
        # silently trust/anchor an existing or truncated unanchored log.
        if create:
            os.close(private_file(self.store.log_path, create=True))
            if self.store.read_all() or self.head_path.exists():
                raise NonZeroError("NONZERO_PROVENANCE_CORRUPT", 409)
            self._write_head(verify_provenance_chain([]))
        self.check()

    @staticmethod
    def _head(result):
        return {**source_identity(), "entry_count": result.entry_count,
                "terminal_hash": result.terminal_hash}

    def _write_head(self, result):
        atomic_write_private_json(
            self.head_path,
            seal_local_payload(self._head(result), payload_type="NONZERO_CORE_CHAIN_HEAD"),
        )

    def check(self, *, reserve: int = 0):
        try:
            if any(path.is_symlink() for path in self.store.log_path.parents):
                raise NonZeroError("NONZERO_UNSAFE_STATE_PATH", 409)
            fd = private_file(self.store.log_path)
            try:
                size = os.fstat(fd).st_size
            finally:
                os.close(fd)
            if size + reserve > self.max_bytes:
                raise NonZeroError("NONZERO_EVIDENCE_QUOTA_EXCEEDED", 409)
            entries = self.store.read_all()
            result = verify_provenance_chain(entries)
            if not result.ok:
                raise NonZeroError("NONZERO_PROVENANCE_CORRUPT", 409)
            expected = source_identity()
            if any(
                any(
                    event["payload"].get(key) != value
                    for key, value in expected.items()
                )
                for event in entries
            ):
                raise NonZeroError("NONZERO_SOURCE_IDENTITY_MISMATCH", 409)
            os.close(private_file(self.head_path))
            head, _ = open_local_payload(
                read_private_json(self.head_path), payload_type="NONZERO_CORE_CHAIN_HEAD",
            )
            if head != self._head(result):
                raise NonZeroError("NONZERO_PROVENANCE_HEAD_MISMATCH", 409)
            return entries, result
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
            raise NonZeroError("NONZERO_PROVENANCE_CORRUPT", 409) from error

    def append(self, kind: str, payload: dict):
        entries, _ = self.check()
        try:
            record = self.store.append_event(
                kind, {**public_evidence(payload), **source_identity()}
            )
            # Core owns the chain format. Flush intent before protected dispatch.
            fd = private_file(self.store.log_path)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            result = verify_provenance_chain([*entries, record])
            if not result.ok:
                raise NonZeroError("NONZERO_PROVENANCE_CORRUPT", 409)
            # A crash between log fsync and atomic head replacement fails closed
            # on the next check. There is no automatic adoption or rollback.
            self._write_head(result)
        except (OSError, TypeError, ValueError) as error:
            raise NonZeroError("NONZERO_PROVENANCE_WRITE_FAILED", 503) from error
