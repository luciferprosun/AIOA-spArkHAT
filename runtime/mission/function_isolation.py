"""Mandatory extra child domain inside the existing Linux sandbox.

The fixed caller loads its arguments before applying this irreversible policy.
Repository code never sees /proc, trusted inputs, or writable dependency files.
No best-effort fallback or host invocation is supported.

ABI reference: https://docs.kernel.org/userspace-api/landlock.html
"""
import ctypes
import os
import platform
import sys
from pathlib import Path

EXECUTE = 1 << 0
WRITE_FILE = 1 << 1
READ_FILE = 1 << 2
READ_DIR = 1 << 3
REMOVE_DIR = 1 << 4
REMOVE_FILE = 1 << 5
MAKE_CHAR = 1 << 6
MAKE_DIR = 1 << 7
MAKE_REG = 1 << 8
MAKE_SOCK = 1 << 9
MAKE_FIFO = 1 << 10
MAKE_BLOCK = 1 << 11
MAKE_SYM = 1 << 12
REFER = 1 << 13
TRUNCATE = 1 << 14
IOCTL_DEV = 1 << 15
HANDLED_FS = (1 << 16) - 1
SCOPED = 3  # ABI 6: abstract Unix sockets and signals outside this domain.


def require(condition, code):
    if not condition:
        raise ValueError(code)


def _require_confined_single_thread():
    require(sys.platform == 'linux' and platform.machine() == 'x86_64', 'FUNCTION_CONFINEMENT_REQUIRED')
    status = Path('/proc/self/status').read_text()
    require('NoNewPrivs:\t1' in status and 'Seccomp:\t2' in status
            and Path('/bootstrap').is_file()
            and os.statvfs('/inputs/function_child.py').f_flag & os.ST_RDONLY
            and len(os.listdir('/proc/self/task')) == 1, 'FUNCTION_CONFINEMENT_REQUIRED')


class _Ruleset(ctypes.Structure):
    _fields_ = [('handled_access_fs', ctypes.c_uint64),
                ('handled_access_net', ctypes.c_uint64), ('scoped', ctypes.c_uint64)]


class _PathBeneath(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]


class _LandlockKernel:
    def __init__(self):
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.syscall.restype = ctypes.c_long
        self.abi = self.libc.syscall(ctypes.c_long(444), ctypes.c_void_p(0), ctypes.c_size_t(0), ctypes.c_uint(1))

    def create(self, rights, scoped):
        attr = _Ruleset(rights, 0, scoped)
        return self.libc.syscall(ctypes.c_long(444), ctypes.byref(attr), ctypes.sizeof(attr), ctypes.c_uint(0))

    def add(self, ruleset, parent, rights):
        attr = _PathBeneath(rights, parent)
        return self.libc.syscall(ctypes.c_long(445), ctypes.c_int(ruleset), ctypes.c_int(1),
                                 ctypes.byref(attr), ctypes.c_uint(0))

    def restrict(self, ruleset):
        return self.libc.syscall(ctypes.c_long(446), ctypes.c_int(ruleset), ctypes.c_uint(0))


def _kernel():
    return _LandlockKernel()


def restrict_function_process():
    _require_confined_single_thread()
    kernel = _kernel()
    require(kernel.abi >= 6, 'FUNCTION_LANDLOCK_ABI_REQUIRED')
    read = READ_FILE | READ_DIR
    temporary = (read | WRITE_FILE | TRUNCATE | MAKE_REG | MAKE_DIR
                 | REMOVE_FILE | REMOVE_DIR | REFER)
    paths = (
        ('/usr/lib/python3.12', read), ('/lib', read), ('/lib64', read),
        ('/usr/bin/python3.12', READ_FILE | EXECUTE),
        ('/work/project', read), ('/work/dependencies', read), ('/tmp', temporary),
        ('/dev/null', READ_FILE | WRITE_FILE), ('/dev/urandom', READ_FILE),
    )
    ruleset = kernel.create(HANDLED_FS, SCOPED)
    require(ruleset >= 0, 'FUNCTION_LANDLOCK_RULESET_REQUIRED')
    try:
        for path, rights in paths:
            fd = os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                require(kernel.add(ruleset, fd, rights) == 0, 'FUNCTION_LANDLOCK_RULE_REQUIRED')
            finally:
                os.close(fd)
        require(kernel.restrict(ruleset) == 0, 'FUNCTION_LANDLOCK_ENFORCEMENT_REQUIRED')
    finally:
        os.close(ruleset)
    return {'schema': 'aioa.function-child-isolation.v1', 'landlock_abi': kernel.abi,
            'parent_proc_access': 'DENIED', 'workspace_access': 'READ_ONLY',
            'signal_scope': 'DESCENDANTS_ONLY', 'inherited_by_descendants': True}
