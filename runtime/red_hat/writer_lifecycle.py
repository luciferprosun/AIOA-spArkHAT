"""S1 one-shot writer closure records in a root-owned operation aperture."""

import json
import os
import stat
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.red_hat.broker_protocol import digest, read_record, require
from runtime.red_hat.execution_binding import NativeExecutionBindingV1

_LAUNCH = "writer-launch"
_PROCESS = "writer-process"
_CLOSED = "writer-closed"
_CLOSED_SYNCED = "writer-closed-synced"
COMPLETION_STAGE = "aioa.redhat.s1.writer-completion-stage.v1"


def _boot():
    return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()


def _launch(storage, boot=None):
    require(storage.writer_cgroup is not None, "NATIVE_S1_WRITER_PINS")
    return {"schema": "aioa.redhat.s1.writer-launch.v1", "boot": _boot() if boot is None else boot,
            "storage": storage.digest, "cgroup": asdict(storage.writer_cgroup)}


def _read(root_fd, name, storage):
    raw = read_record(root_fd, name, 0, reader_gid=storage.reader_gid)
    value = json.loads(raw)
    require(type(value) is dict and canonical_json_bytes(value) == raw, "NATIVE_S1_WRITER_RECORD")
    return value


def _publish(root_fd, name, value, storage, *, sync_directory=True, before_directory_sync=None):
    # The pinned root anchor is intentionally 0750, without setgid inheritance.
    fd = os.open(".", os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC, 0o440, dir_fd=root_fd)
    try:
        os.fchown(fd, 0, storage.reader_gid)
        os.fchmod(fd, 0o440)
        raw = canonical_json_bytes(value)
        require(os.write(fd, raw) == len(raw), "NATIVE_S1_WRITER_RECORD")
        os.fsync(fd)
        os.link(f"/proc/self/fd/{fd}", name, dst_dir_fd=root_fd, follow_symlinks=True)
        if sync_directory:
            if before_directory_sync is not None:
                before_directory_sync()
            os.fsync(root_fd)
    finally:
        os.close(fd)


def _start_ticks(pid):
    status = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    return int(status.rsplit(")", 1)[1].split()[19])


def _empty(cgroup_fd):
    fd = os.open("cgroup.events", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=cgroup_fd)
    try:
        raw = os.read(fd, 4097)
        require(len(raw) <= 4096 and raw.endswith(b"\n"), "NATIVE_S1_CGROUP_EVENTS")
        events = raw.splitlines()
        return [line for line in events if line.startswith(b"populated ")] == [b"populated 0"]
    finally:
        os.close(fd)


def _cgroup(storage, cgroup_fd):
    root = Path("/sys/fs/cgroup")
    path = root / storage.broker.cgroup[4:]
    require(path.is_relative_to(root) and path != root and ".." not in path.parts,
            "NATIVE_S1_CGROUP")
    row = storage.writer_cgroup.require_fd(cgroup_fd)
    require(os.readlink(f"/proc/self/fd/{cgroup_fd}") == str(path), "NATIVE_S1_CGROUP")
    for entry in (path, *(parent for parent in path.parents if parent.is_relative_to(root))):
        info = entry.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                "NATIVE_S1_CGROUP")
        for name in ("cgroup.procs", "cgroup.threads"):
            control = (entry / name).lstat()
            require(stat.S_ISREG(control.st_mode) and control.st_uid == 0 and not control.st_mode & 0o022,
                    "NATIVE_S1_CGROUP_CONTROL")
    mount = str(storage.writer_cgroup.mount)
    require(any(line.split(" - ", 1)[0].split()[0] == mount
                and line.split(" - ", 1)[1].split()[0] == "cgroup2"
                for line in Path("/proc/self/mountinfo").read_text().splitlines()), "NATIVE_S1_CGROUP_TYPE")
    named = path.lstat()
    require((named.st_dev, named.st_ino) == (row.st_dev, row.st_ino), "NATIVE_S1_CGROUP")


def _process(root_fd, storage, boot=None):
    launch = _launch(storage, boot)
    require(_read(root_fd, _LAUNCH, storage) == launch, "NATIVE_S1_WRITER_LAUNCH")
    process = _read(root_fd, _PROCESS, storage)
    require(set(process) == {"schema", "launch", "pid", "start_ticks"}
            and process["schema"] == "aioa.redhat.s1.writer-process.v1"
            and process["launch"] == digest(launch)
            and all(type(process[k]) is int and process[k] > 0 for k in ("pid", "start_ticks")),
            "NATIVE_S1_WRITER_PROCESS")
    return process


def require_launched_writer(root_fd, storage):
    process = _process(root_fd, storage)
    require(process["pid"] == os.getpid() and process["start_ticks"] == _start_ticks(os.getpid()),
            "NATIVE_S1_WRITER_PROCESS")
    try:
        os.stat(_CLOSED, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ValueError("NATIVE_S1_WRITER_ALREADY_CLOSED")


def _closure(binding, storage, process, completion, *, boot=None):
    require(type(binding) is NativeExecutionBindingV1 and binding.storage_digest == storage.digest
            and binding.boot_id == (_boot() if boot is None else boot) and binding.request.exact_ref == storage.exact_ref,
            "NATIVE_S1_WRITER_BINDING")
    from runtime.red_hat.execution_binding import digest_string

    require(digest_string(completion), "NATIVE_S1_COMPLETION_STAGE")
    return {"schema": "aioa.redhat.s1.writer-closed.v2", "process": digest(process),
            "binding": digest(binding.to_wire()), "completion_sha256": completion}


def _closure_synced(binding, closure):
    return {"schema": "aioa.redhat.s1.writer-closure-synced.v1",
            "boot": binding.boot_id, "closure": digest(closure)}


def _publish_closure(root_fd, storage, binding, closure, *, before_directory_sync=None):
    _publish(root_fd, _CLOSED, closure, storage, before_directory_sync=before_directory_sync)
    # A same-boot completion signal. Its fsynced bytes can be linked only
    # after the primary directory barrier returned to this supervisor.
    _publish(root_fd, _CLOSED_SYNCED, _closure_synced(binding, closure), storage,
             sync_directory=getattr(storage, "persistent", None) is not None)


def _closed_records(root_fd, storage, binding, *, boot):
    """Read immutable supervisor evidence for the explicitly bound predecessor."""
    try:
        recorded = _read(root_fd, _CLOSED, storage)
        expected = _closure(binding, storage, _process(root_fd, storage, boot), recorded.get("completion_sha256"),
                            boot=boot)
        require(recorded == expected, "NATIVE_S1_WRITER_CLOSURE")
        require(_read(root_fd, _CLOSED_SYNCED, storage) == _closure_synced(binding, expected),
                "NATIVE_S1_WRITER_CLOSURE_SYNC")
        return recorded
    except OSError as exc:
        raise ValueError("NATIVE_S1_WRITER_CLOSURE_UNAVAILABLE") from exc


def require_writer_closed(root_fd, storage, binding):
    """Authenticate the current boot's records before the first effect read and at commit."""
    storage.require_anchor(root_fd)
    return _closed_records(root_fd, storage, binding, boot=_boot())["completion_sha256"]


class OneShotWriter:
    """Supervisor handoff. Retain the cgroup and child identities until closure.

    The caller owns the isolated, non-delegated cgroup and must keep the
    child at a startup barrier until register succeeds. The loaded policy
    must prevent cgroup migration, descriptor export and other writers.
    """

    def __init__(self, root_fd, storage, cgroup_fd, *, before_closure_sync=None):
        require(os.geteuid() == 0 and storage.writer_cgroup is not None, "NATIVE_S1_SUPERVISOR")
        storage.require_anchor(root_fd)
        _cgroup(storage, cgroup_fd)
        require(_empty(cgroup_fd), "NATIVE_S1_CGROUP_POPULATED")
        _publish(root_fd, _LAUNCH, _launch(storage), storage)
        self.root_fd = root_fd
        self.storage = storage
        self.cgroup_fd = cgroup_fd
        self.pidfd = None
        self.before_closure_sync = before_closure_sync

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.pidfd is not None:
            os.close(self.pidfd)
            self.pidfd = None

    def register(self, child):
        require(type(child) is subprocess.Popen and self.pidfd is None, "NATIVE_S1_WRITER_PROCESS")
        pidfd = os.pidfd_open(child.pid)
        try:
            require(os.waitid(os.P_PIDFD, pidfd, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None
                    and Path(f"/proc/{child.pid}/cgroup").read_text().strip() == self.storage.broker.cgroup,
                    "NATIVE_S1_WRITER_PROCESS")
            for namespace in ("mnt", "cgroup", "pid"):
                require(os.path.samestat(os.stat(f"/proc/{child.pid}/ns/{namespace}"),
                                         os.stat(f"/proc/self/ns/{namespace}")), "NATIVE_S1_WRITER_NAMESPACE")
            process = {"schema": "aioa.redhat.s1.writer-process.v1",
                       "launch": digest(_launch(self.storage)), "pid": child.pid,
                       "start_ticks": _start_ticks(child.pid)}
            _publish(self.root_fd, _PROCESS, process, self.storage)
            self.pidfd = pidfd
        finally:
            if self.pidfd is None:
                os.close(pidfd)

    def close_writer(self, binding, completion_report, enrollment):
        """Observe the original unreaped child's exit and the empty subtree."""
        require(self.pidfd is not None, "NATIVE_S1_WRITER_PROCESS")
        process = _process(self.root_fd, self.storage)
        _cgroup(self.storage, self.cgroup_fd)
        status = os.waitid(os.P_PIDFD, self.pidfd, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        require(status is not None and status.si_pid == process["pid"] and _empty(self.cgroup_fd),
                "NATIVE_S1_WRITER_STILL_LIVE")
        from runtime.red_hat.authenticated_boundary import _open_seal
        from runtime.red_hat.enrollment import ExecutorEnrollment

        require(type(enrollment) is ExecutorEnrollment and enrollment.executor.uid == self.storage.broker.uid
                and enrollment.permits(binding.request, int(time.time())),
                "NATIVE_S1_COMPLETION_STAGE")
        stage = _open_seal(completion_report, enrollment.executor.spki, COMPLETION_STAGE)
        completion = stage.get("completion_sha256")
        closure = _closure(binding, self.storage, process, completion)
        require(stage == {"schema": COMPLETION_STAGE, "binding": closure["binding"],
                          "completion_sha256": completion}, "NATIVE_S1_COMPLETION_STAGE")
        if getattr(self.storage, "persistent", None) is not None:
            _publish(self.root_fd, "writer-completion-stage", completion_report, self.storage)
        _publish_closure(self.root_fd, self.storage, binding, closure,
                         before_directory_sync=self.before_closure_sync)
