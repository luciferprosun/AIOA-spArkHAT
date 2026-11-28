"""Unprivileged off-guest export test. Uses a new temp disk and an actual NBD wire client."""

import argparse
import errno
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import nbd

from scripts.unification.native_s2.storage import advance, initialize


def connect(endpoint, export):
    handle = nbd.NBD()
    handle.set_export_name(export)
    handle.connect_unix(str(endpoint))
    return handle


def refusal(call, *, expected_errno=None):
    try:
        call()
    except nbd.Error as error:
        if expected_errno is not None and error.errnum != expected_errno:
            raise
        return
    raise AssertionError("stale NBD operation succeeded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nbdkit", default="nbdkit")
    parser.add_argument("--python-plugin", default="python")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        disk = root / "disk.raw"
        with disk.open("xb") as raw:
            os.fchmod(raw.fileno(), 0o600)
            raw.truncate(1024 * 1024)
        volume = hashlib.sha256(os.urandom(32)).hexdigest()
        initialize(root, volume)
        predecessor = advance(root, volume, 0)
        endpoint = root / "data.sock"
        plugin = repo / "scripts/unification/native_s2/nbd_export.py"
        env = {**os.environ, "PYTHONPATH": str(repo) + os.pathsep + os.environ.get("PYTHONPATH", "")}
        with subprocess.Popen([args.nbdkit, "-f", "--exit-with-parent", "-U", str(endpoint),
                               args.python_plugin, str(plugin), "root=" + temp], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as server:
            try:
                deadline = time.monotonic() + 10
                while not endpoint.exists():
                    if server.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("NBD startup failed")
                    time.sleep(0.02)
                old = connect(endpoint, predecessor)
                old.pwrite(b"A" * 512, 0)
                old.flush()
                assert disk.read_bytes()[:512] == b"A" * 512
                refusal(lambda: connect(endpoint, predecessor))
                successor = advance(root, volume, 1)
                refusal(lambda: old.pwrite(b"B" * 512, 0), expected_errno=errno.EPERM)
                refusal(lambda: connect(endpoint, predecessor))
                new = connect(endpoint, successor)
                assert new.pread(512, 0) == b"A" * 512
                new.pwrite(b"C" * 512, 512)
                new.flush()
                assert disk.read_bytes()[:1024] == b"A" * 512 + b"C" * 512
                new.shutdown()
                old.shutdown()
            finally:
                server.terminate()
                server.wait(timeout=10)
    print(json.dumps({"transport": "NBD_UNIX", "old_handle_write": "EPERM",
                      "old_reattach": "DENIED", "duplicate_attach": "DENIED", "successor_io": "PASS"}))


if __name__ == "__main__":
    main()
