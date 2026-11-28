"""nbdkit Python API v2 adapter. Run only on the private controller Unix socket."""

import errno
from pathlib import Path

import nbdkit

from scripts.unification.native_s2.storage import Export, Fenced

API_VERSION = 2
root = None


def config(key, value):
    global root
    if key != "root" or root is not None or not Path(value).is_absolute():
        raise ValueError("expected one absolute controller root")
    root = Path(value)


def config_complete():
    if root is None:
        raise ValueError("missing controller root")


def list_exports(readonly, is_tls):
    return []


def open(readonly):
    return Export(root, nbdkit.export_name())


def close(handle):
    handle.close()


def get_size(handle):
    return handle.size


def pread(handle, buf, offset, flags):
    buf[:] = handle.read(len(buf), offset)


def pwrite(handle, buf, offset, flags):
    try:
        handle.write(buf, offset)
    except Fenced:
        nbdkit.set_error(errno.EPERM)
        raise


def flush(handle, flags):
    handle.flush()


def can_fua(handle):
    return nbdkit.FUA_NATIVE


def can_multi_conn(handle):
    return False
