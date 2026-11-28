"""Actual denial probes inside the same restricted role used for the effect."""

import array
import ctypes
import errno
import fcntl
import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from runtime.mission.sandbox_linux import mountid
from runtime.red_hat.broker_protocol import require

SIBLING = "refs/heads/aioa/n69-denial-sibling"
FOREIGN = "refs/heads/n69-denial-foreign"


def _deny(name, action, results):
    try:
        action()
    except OSError as exc:
        require(exc.errno in (errno.EACCES, errno.EPERM), "NATIVE_S1_PROBE_INCONCLUSIVE:" + name)
        results[name] = exc.errno
    else:
        raise ValueError("NATIVE_S1_PROBE_UNEXPECTED_SUCCESS:" + name)


def _open(path, flags, *, parent=None):
    fd = os.open(path, flags | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    os.close(fd)


def core_denials(root, ref):
    result = {}
    _deny("signer-read", lambda: _open(root / "keys/signer.pem", os.O_RDONLY), result)
    _deny("ref-create", lambda: _open(root / "repo" / ref, os.O_WRONLY | os.O_CREAT | os.O_EXCL), result)
    return result


def predecessor_write_denials(files):
    names = {'prior-ref', 'prior-object', 'prior-witness', 'prior-completion'}
    require(type(files) is dict and set(files) == names, "NATIVE_S1_PREDECESSOR_FILES")
    result = {}
    for name, path in files.items():
        _deny(name, lambda: _open(path, os.O_WRONLY), result)
    return result


@dataclass(frozen=True, slots=True)
class Mutation:
    label: str
    operation: str
    name: str
    destination: str | None = None

    def names(self):
        return (self.name, self.destination) if self.destination is not None else (self.name,)

    def run(self, parent):
        if self.operation == "replace":
            os.replace(self.name, self.destination, src_dir_fd=parent, dst_dir_fd=parent)
        elif self.operation == "unlink":
            os.unlink(self.name, dir_fd=parent)
        else:
            flags = os.O_WRONLY
            if self.operation == "create":
                flags |= os.O_CREAT | os.O_EXCL
            _open(self.name, flags, parent=parent)


def verifier_mutations(case, leaf, object_leaf, witness, completion):
    sibling = SIBLING.rsplit("/", 1)[1]
    if case == "N2":
        return ("ref", Mutation("ref-write", "open", leaf)), (
            "ref", Mutation("ref-replace", "replace", sibling, leaf)), (
            "ref", Mutation("ref-unlink", "unlink", leaf)), (
            "ref", Mutation("sibling-write", "open", sibling)), (
            "ref", Mutation("sibling-replace", "replace", leaf, sibling)), (
            "ref", Mutation("sibling-unlink", "unlink", sibling)), (
            "ref", Mutation("sibling-create", "create", sibling + "-new"))
    require(case == "N3", "NATIVE_S1_VERIFIER_PROBE_CASE")
    new_object = ("f" if object_leaf == "0" * 38 else "0") * 38
    return ("ref", Mutation("ref-lock-create", "create", leaf + ".lock")), (
        "repo", Mutation("packed-refs-create", "create", "packed-refs")), (
        "repo", Mutation("packed-refs-lock-create", "create", "packed-refs.lock")), (
        "commit", Mutation("object-write", "open", object_leaf)), (
        "commit", Mutation("object-create", "create", new_object)), (
        "witness", Mutation("witness-write", "open", witness)), (
        "completion", Mutation("completion-write", "open", completion))


def _identity(fd):
    info = os.fstat(fd)
    return {"dev": info.st_dev, "ino": info.st_ino, "mnt_id": mountid(fd),
            "mode": info.st_mode, "uid": info.st_uid, "gid": info.st_gid,
            "ctime_ns": info.st_ctime_ns}


def _contents(fd, parent, name, maximum):
    info = os.fstat(fd)
    named = os.stat(name, dir_fd=parent, follow_symlinks=False)
    require(stat.S_ISREG(info.st_mode) and os.path.samestat(info, named)
            and info.st_ctime_ns == named.st_ctime_ns and info.st_size <= maximum
            and mountid(fd) == mountid(parent), "NATIVE_S1_PROBE_IDENTITY")
    raw = os.pread(fd, maximum + 1, 0)
    require(len(raw) == info.st_size, "NATIVE_S1_PROBE_SIZE")
    return raw


def _named(parent, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    except FileNotFoundError:
        return None
    try:
        raw = _contents(fd, parent, name, 1024 * 1024)
        return {**_identity(fd), "sha256": hashlib.sha256(raw).hexdigest()}
    finally:
        os.close(fd)


def _role_observation():
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    return {"pid": os.getpid(), "uid": list(os.getresuid()), "gid": list(os.getresgid()), "groups": os.getgroups(),
            "no_new_privileges": int(status["NoNewPrivs"]),
            "capabilities": {key: int(status[key], 16) for key in ("CapBnd", "CapInh", "CapPrm", "CapEff", "CapAmb")},
            "dumpable": ctypes.CDLL(None).prctl(3, 0, 0, 0, 0),
            "profile": Path("/proc/self/attr/current").read_text().strip(),
            "cgroup": Path("/proc/self/cgroup").read_text().strip(),
            "namespaces": {name: os.stat(f"/proc/self/ns/{name}").st_ino for name in ("mnt", "user", "pid")}}


class VerifierDenials:
    """Measure within the authorized verifier's real proof reads, before a reply exists."""

    def __init__(self, case, storage, report):
        self.case, self.storage, self.report = case, storage, report
        self.reads, self.denials = {}, {}

    def __call__(self, target, kind, parent, name, fd, raw):
        self.storage.require_role("verifier")
        require(kind not in self.reads and fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY,
                "NATIVE_S1_PROBE_READ_HANDLE")
        self.storage.repository.require_fd(target.repo)
        self.storage.ref_parent.require_fd(target.ref_parent)
        require(kind != "ref" or parent == target.ref_parent, "NATIVE_S1_PROBE_REF_HANDLE")
        before = {"parent": _identity(parent), "file": _identity(fd), "sha256": hashlib.sha256(raw).hexdigest()}
        require(_contents(fd, parent, name, len(raw)) == raw, "NATIVE_S1_PROBE_READ_BYTES")
        leaf = self.storage.exact_ref.rsplit("/", 1)[1]
        repo_before = _identity(target.repo)
        for subject, mutation in verifier_mutations(self.case, leaf, name, name, name):
            if subject == kind or (kind == "ref" and subject == "repo"):
                directory = target.repo if subject == "repo" else parent
                paths = mutation.names()
                identities = [_named(directory, path) for path in paths]
                require(all((item is None) == (mutation.operation == "create") for item in identities),
                        "NATIVE_S1_PROBE_PRECONDITION:" + mutation.label)
                _deny(mutation.label, lambda: mutation.run(directory), self.denials)
                require(identities == [_named(directory, path) for path in paths],
                        "NATIVE_S1_PROBE_CHANGED:" + mutation.label)
        after = {"parent": _identity(parent), "file": _identity(fd),
                 "sha256": hashlib.sha256(_contents(fd, parent, name, len(raw))).hexdigest()}
        require(before == after and repo_before == _identity(target.repo), "NATIVE_S1_PROBE_READ_MOVED")
        self.reads[kind] = {"before": before, "after": after}
        if kind == "ref":
            self.reads[kind]["ref_bytes"] = raw.decode("ascii")
        if kind == "completion":
            require(set(self.reads) == {"ref", "commit", "witness", "completion"}, "NATIVE_S1_PROBE_READS")
            if self.case == "N3":
                _deny("attempt-state", lambda: _open("state/lock", os.O_WRONLY, parent=target.root), self.denials)
            role = _role_observation()
            require(role["namespaces"]["mnt"] == self.storage.mount_namespace, "NATIVE_S1_PROBE_NAMESPACE")
            self.report(self.denials, {"role": role, "repository": repo_before, "reads": self.reads})


def verifier_writable_control(directory, case):
    """Each syscall starts with the same preconditions in an independent scratch target."""
    results = []
    for index, (_, mutation) in enumerate(verifier_mutations(case, "nz11-" + "c" * 32, "a" * 38,
                                                           "witness", "completion-witness")):
        with tempfile.TemporaryDirectory(dir=directory, prefix=f"probe-{index}-") as temp:
            fixture = Path(temp)
            if mutation.operation != "create":
                for name in mutation.names():
                    (fixture / name).write_bytes(name.encode("ascii"))
            parent = os.open(fixture, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                mutation.run(parent)
                if mutation.operation == "replace":
                    require((fixture / mutation.destination).read_bytes() == mutation.name.encode("ascii"),
                            "NATIVE_S1_PROBE_CONTROL_REPLACE")
                require((fixture / mutation.name).exists() == (mutation.operation in ("create", "open")),
                        "NATIVE_S1_PROBE_CONTROL_EFFECT")
            finally:
                os.close(parent)
        results.append(mutation.label)
    return results


def broker_before_link(root, control):
    repo = root / "repo"
    result = {}
    fd = os.open(root / "staging", os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC, 0o440)
    try:
        # Setup succeeded on precisely the same filesystem and in the same
        # AppArmor domain as the normal ref publication.
        for label, ref in (("sibling-link", SIBLING + "-new"), ("foreign-link", FOREIGN)):
            parent = os.open((repo / ref).parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                _deny(label, lambda: os.link(f"/proc/self/fd/{fd}", os.path.basename(ref), dst_dir_fd=parent,
                                            follow_symlinks=True), result)
            finally:
                os.close(parent)
        import socket
        rights = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))]
        _deny("writable-fd-export", lambda: control.sendmsg([b"x"], rights), result)
    finally:
        os.close(fd)
    return result


def broker_fork_denial():
    try:
        child = os.fork()
    except OSError as error:
        require(error.errno in (errno.EACCES, errno.EPERM), 'NATIVE_S1_FORK_PROBE_INCONCLUSIVE')
        return error.errno
    if child == 0:
        os._exit(77)
    os.waitpid(child, 0)
    raise ValueError('NATIVE_S1_FORK_PROBE_UNEXPECTED_SUCCESS')


def broker_after_link(root, ref):
    path = root / "repo" / ref
    result = {}
    _deny("ref-write-open", lambda: _open(path, os.O_WRONLY), result)
    _deny("ref-unlink", lambda: os.unlink(path), result)
    _deny("ref-rename", lambda: os.rename(path, path.with_suffix(".new")), result)
    return result
