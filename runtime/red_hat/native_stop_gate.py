"""Opt-in, fail-closed serialization candidate for Core STOP and Native ref CAS.

This is not installed by default. Relevant Core STOP/revoke/kill writers and
the Native publisher must use the same gate; the publisher holds it from its
final Core authorization transaction through the exclusive ref link. A gate
used by only one side provides no ordering guarantee.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import threading
import time
from contextlib import contextmanager


class StopGateUnavailable(RuntimeError):
    """A gate could not be safely acquired; the caller must fail closed."""


class NativeStopCasGate:
    """Bounded advisory flock with process-local thread serialization.

    The directory must already be a private, owner-controlled directory. The
    file is never removed or replaced by this class. Linux releases the flock
    on process death. This does not protect against non-cooperating writers.
    """

    def __init__(self, directory, *, name="native-stop-cas.lock", timeout=2.0,
                 contention_observer=None):
        if (type(directory) is not str or not os.path.isabs(directory)
                or type(name) is not str or not name or "/" in name
                or type(timeout) not in (int, float) or not 0 < timeout <= 30
                or (contention_observer is not None and not callable(contention_observer))):
            raise StopGateUnavailable("STOP_GATE_CONFIGURATION")
        self.directory = os.path.realpath(directory)
        info = os.stat(self.directory, follow_symlinks=False)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise StopGateUnavailable("STOP_GATE_DIRECTORY")
        self._dir_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY |
                               os.O_NOFOLLOW | os.O_CLOEXEC)
        self._dir_identity = (info.st_dev, info.st_ino)
        self.name, self.timeout = name, float(timeout)
        self._contention_observer = contention_observer
        try:
            try:
                self._fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL |
                                   os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                                   dir_fd=self._dir_fd)
            except FileExistsError:
                self._fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                                   dir_fd=self._dir_fd)
            self._identity = self._validate_file()
        except BaseException:
            os.close(self._dir_fd)
            raise
        self._threads = threading.RLock()
        self._local = threading.local()
        self._closed = False

    def _validate_file(self):
        fd_info = os.fstat(self._fd)
        try:
            named = os.stat(self.name, dir_fd=self._dir_fd, follow_symlinks=False)
            directory = os.fstat(self._dir_fd)
        except OSError as error:
            raise StopGateUnavailable("STOP_GATE_PATH") from error
        if ((directory.st_dev, directory.st_ino) != self._dir_identity
                or not stat.S_ISREG(fd_info.st_mode)
                or fd_info.st_uid != os.geteuid()
                or stat.S_IMODE(fd_info.st_mode) != 0o600
                or fd_info.st_nlink != 1
                or (fd_info.st_dev, fd_info.st_ino) != (named.st_dev, named.st_ino)):
            raise StopGateUnavailable("STOP_GATE_IDENTITY")
        return fd_info.st_dev, fd_info.st_ino

    @contextmanager
    def hold(self):
        if self._closed:
            raise StopGateUnavailable("STOP_GATE_CLOSED")
        depth = getattr(self._local, "depth", 0)
        if depth:
            self._local.depth = depth + 1
            try:
                yield
            finally:
                self._local.depth -= 1
            return
        observed_contention = False
        acquired_thread = self._threads.acquire(blocking=False)
        if not acquired_thread:
            self._observe_contention()
            observed_contention = True
            acquired_thread = self._threads.acquire(timeout=self.timeout)
        if not acquired_thread:
            raise StopGateUnavailable("STOP_GATE_THREAD_TIMEOUT")
        locked = False
        try:
            if self._validate_file() != self._identity:
                raise StopGateUnavailable("STOP_GATE_REPLACED")
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError as error:
                    if error.errno not in (errno.EAGAIN, errno.EACCES):
                        raise StopGateUnavailable("STOP_GATE_LOCK_ERROR") from error
                    if not observed_contention:
                        self._observe_contention()
                        observed_contention = True
                    if time.monotonic() >= deadline:
                        raise StopGateUnavailable("STOP_GATE_TIMEOUT") from None
                    time.sleep(min(0.01, max(0, deadline - time.monotonic())))
            if self._validate_file() != self._identity:
                raise StopGateUnavailable("STOP_GATE_REPLACED")
            self._local.depth = 1
            yield
        finally:
            self._local.depth = 0
            if locked:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                except OSError as error:
                    raise StopGateUnavailable("STOP_GATE_UNLOCK_ERROR") from error
            self._threads.release()

    def _observe_contention(self):
        if self._contention_observer is not None:
            try:
                self._contention_observer()
            except Exception as error:
                raise StopGateUnavailable("STOP_GATE_OBSERVER_FAILED") from error

    def close(self):
        if self._closed:
            return
        if getattr(self._local, "depth", 0):
            raise StopGateUnavailable("STOP_GATE_CLOSE_WHILE_HELD")
        acquired = self._threads.acquire(timeout=self.timeout)
        if not acquired:
            raise StopGateUnavailable("STOP_GATE_CLOSE_WHILE_HELD")
        try:
            if self._closed:
                return
            self._closed = True
            os.close(self._fd)
            os.close(self._dir_fd)
        finally:
            self._threads.release()


def bind_transaction_runner(runner, gate):
    """Install one explicit gate on an existing Core runner; never replace it."""
    from runtime.memory_patch.persistence.ports import TransactionRunner

    if type(runner) is not TransactionRunner or type(gate) is not NativeStopCasGate:
        raise StopGateUnavailable("STOP_GATE_BINDING")
    existing = getattr(runner, "execution_gate", None)
    if existing is not None and existing is not gate:
        raise StopGateUnavailable("STOP_GATE_ALREADY_BOUND")
    admission = getattr(runner, "_admission", None)
    if admission is None:
        raise StopGateUnavailable("STOP_GATE_BINDING")
    admission_gate = getattr(admission, "execution_gate", None)
    if admission_gate is not None and admission_gate is not gate:
        raise StopGateUnavailable("STOP_GATE_ALREADY_BOUND")
    runner.execution_gate = gate
    admission.execution_gate = gate
    return gate
