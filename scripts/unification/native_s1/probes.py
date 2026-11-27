"""Actual denial probes inside the same restricted role used for the effect."""

import array
import errno
import os

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


def _open(path, flags):
    fd = os.open(path, flags | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
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


def verifier_denials(root, ref, case):
    repo = root / "repo"
    result = {}
    actual = repo / ref
    present = repo / SIBLING
    if case == "N2":
        for subject, path in (("ref", actual), ("sibling", present)):
            _deny(subject + "-write", lambda: _open(path, os.O_WRONLY), result)
            _deny(subject + "-rename", lambda: os.rename(path, path.with_suffix(".new")), result)
            _deny(subject + "-unlink", lambda: os.unlink(path), result)
        _deny("sibling-create", lambda: _open(present.with_suffix(".new"),
              os.O_WRONLY | os.O_CREAT | os.O_EXCL), result)
    if case == "N3":
        for name in ("packed-refs", "packed-refs.lock", ref + ".lock"):
            _deny(name + "-create", lambda: _open(repo / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL), result)
        files = sorted(item for item in (repo / "objects").glob("??/*") if item.is_file())
        require(files, "NATIVE_S1_PROBE_OBJECTS")
        _deny("object-write", lambda: _open(files[0], os.O_WRONLY), result)
        evidence = sorted(item for item in (root / "evidence").iterdir() if item.is_file())
        require(evidence, "NATIVE_S1_PROBE_EVIDENCE")
        _deny("evidence-write", lambda: _open(evidence[0], os.O_WRONLY), result)
        _deny("attempt-state", lambda: _open(root / "state/lock", os.O_WRONLY), result)
    return result


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
