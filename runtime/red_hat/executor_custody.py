"""Fail-closed startup checks for a supervisor-issued, broker-only signer FD."""

import ctypes
import fcntl
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key

from runtime.mobile_gateway.wire import Identity
from runtime.red_hat.broker_protocol import require
from runtime.red_hat.enrollment import ExecutorEnrollment


@dataclass(frozen=True, slots=True)
class ExecutorRoles:
    core_uid: int
    broker_uid: int
    verifier_uid: int
    broker_gid: int

    def __post_init__(self):
        uids = (self.core_uid, self.broker_uid, self.verifier_uid)
        require(all(type(value) is int and 0 < value < 2**32 - 1
                    for value in (*uids, self.broker_gid)) and len(set(uids)) == 3,
                "RH07_DISTINCT_ROLE_UIDS")


def _broker_process(roles):
    require(type(roles) is ExecutorRoles
            and os.getresuid() == (roles.broker_uid,) * 3
            and os.getresgid() == (roles.broker_gid,) * 3
            and set(os.getgroups()) <= {roles.broker_gid}, "RH07_BROKER_ROLE")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    require(status["NoNewPrivs"].strip() == "1" and all(
        int(status[field], 16) == 0 for field in ("CapEff", "CapPrm", "CapAmb", "CapInh")
    ), "RH07_BROKER_PRIVILEGES")
    # Linux PR_GET_DUMPABLE. The supervisor must set the restrictive process
    # policy after the final exec/identity transition.
    pr_get_dumpable = 3
    require(ctypes.CDLL(None).prctl(pr_get_dumpable, 0, 0, 0, 0) == 0,
            "RH07_BROKER_DUMPABLE")


def _read_signer_fd(fd, uid):
    require(type(fd) is int and fd >= 3 and not os.get_inheritable(fd)
            and fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY,
            "RH07_SIGNER_FD")
    first = os.fstat(fd)
    require(stat.S_ISREG(first.st_mode) and stat.S_IMODE(first.st_mode) == 0o400
            and first.st_uid == uid and first.st_nlink == 1
            and 0 < first.st_size <= 4096, "RH07_SIGNER_STORAGE")
    raw = os.pread(fd, 4097, 0)
    last = os.fstat(fd)
    # The read itself may legitimately change atime.
    stable = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
              "st_size", "st_mtime_ns", "st_ctime_ns")
    require(len(raw) == first.st_size
            and all(getattr(first, name) == getattr(last, name) for name in stable),
            "RH07_SIGNER_MOVED")
    return raw


def load_broker_signer(fd, roles, enrollment, *, key_epoch, now, enabled=False):
    """Validate the supervisor's FD and return a signer only in the broker role."""
    require(enabled is True, "RH07_DISABLED")
    _broker_process(roles)
    require(type(enrollment) is ExecutorEnrollment and not enrollment.revoked
            and enrollment.executor.uid == roles.broker_uid
            and type(key_epoch) is int and key_epoch == enrollment.key_epoch
            and type(now) is int and enrollment.valid_from <= now < enrollment.valid_until,
            "RH07_SIGNER_ENROLLMENT")
    try:
        signer = Identity(load_pem_private_key(_read_signer_fd(fd, roles.broker_uid), password=None))
    except (TypeError, ValueError):
        raise ValueError("RH07_SIGNER_INVALID") from None
    require(signer.spki == enrollment.executor.spki, "RH07_SIGNER_KEY")
    return signer
