"""Single-request Native CAS executor for separately launched disposable fixtures."""

import os
import socket
import time
from contextlib import ExitStack, nullcontext

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.red_hat.broker_protocol import (
    AttemptGuard, _no_fault, file_identity, receive_request, require,
    require_admission, send_frame,
)
from runtime.red_hat.fixture_repository import (
    open_dir, open_repository, require_named_directory, require_private,
)
from runtime.red_hat.verifier import persist_completion, sign
from runtime.red_hat.witness import persist_witness, witness_payload


def _publish(target, request, guard, authorize, clock, fault, stack, final_check):
    staging = target.ref_parent
    reader_gid = None
    if target.writer:
        staging = open_dir(target.root, "staging", stack)
        require_named_directory(target.root, "staging", staging)
        target.storage.require_staging(staging)
        reader_gid = target.storage.reader_gid
    fd = os.open(".", os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC,
                 0o400 if reader_gid is None else 0o440, dir_fd=staging)
    stack.callback(os.close, fd)
    data = request.new_oid.encode("ascii") + b"\n"
    require(os.write(fd, data) == len(data), "BROKER_REF_WRITE")
    os.fsync(fd)
    original = os.fstat(fd)
    require(original.st_nlink == 0, "BROKER_REF_NOT_UNNAMED")
    if reader_gid is not None:
        import stat
        require(original.st_uid == target.uid and original.st_gid == reader_gid
                and stat.S_IMODE(original.st_mode) == 0o440, "BROKER_SHARED_REF_MODE")
    fault("before_release")
    with guard.locked():
        fault("release_acquired")
        target.check(request, publishing=True)
        target.check_commit(request)
        guard.require_running()
        released_at = clock()
        authorize(released_at)
        final_check()
        if target.writer:
            require_named_directory(target.root, "staging", staging)
            target.storage.require_staging(staging)
        # The exclusive create is the sole irreversible CAS attempt.
        fault("before_ref_link")
        os.link(f"/proc/self/fd/{fd}", target.leaf(request), dst_dir_fd=target.ref_parent,
                follow_symlinks=True)
        fault("after_ref_link")
        os.fsync(target.ref_parent)
        published = os.fstat(fd)
        stamp = (*file_identity(original), published.st_ctime_ns)
        require(published.st_nlink == 1 and target.observe(request) == stamp,
                "BROKER_REF_MOVED")
        published_at = clock()
        require(published_at >= released_at, "BROKER_CLOCK_MOVED")
        request.require_permit(published_at)
    return stamp, published_at


def serve_once(listener, *, root_fd, expected, enrollment, identity, core_peer, core_epoch,
               broker_epoch, clock=lambda: int(time.time()), fault=_no_fault):
    """Serve the RH-02 fixture protocol under launch-time trusted configuration."""
    def receive(peer):
        return receive_request(peer, core_peer, expected, enrollment, now=clock(),
                               core_epoch=core_epoch, broker_epoch=broker_epoch)

    return _serve_fixture(listener, root_fd=root_fd, receive=receive,
                          enrollment=enrollment, identity=identity, core_epoch=core_epoch,
                          broker_epoch=broker_epoch, clock=clock, fault=fault)


def _serve_fixture(listener, *, root_fd, receive, enrollment, identity, core_epoch,
                   broker_epoch, clock, fault, check_context=_no_fault,
                   sequence=nullcontext, revalidate=_no_fault, prepare=None, storage=None, completed=None):
    """Shared single-attempt fixture executor. Authentication precedes consumption."""
    require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM,
            "BROKER_LISTENER")
    executor = enrollment.executor
    require(identity.spki == executor.spki and os.geteuid() == executor.uid,
            "BROKER_SIGNER_BINDING")
    with listener.accept()[0] as peer:
        ok = False
        try:
            request = receive(peer)

            with open_repository(root_fd, request, executor.uid, storage=storage,
                                 role=None if storage is None else "broker",
                                 writer=storage is not None) as target, ExitStack() as stack:
                check_context(target)
                target.check(request, publishing=True)
                if prepare is None:
                    target.check_commit(request)
                state = open_dir(root_fd, "state", stack)
                evidence = open_dir(root_fd, "evidence", stack)
                reader_gid = None
                if storage is None:
                    require_private(evidence, executor.uid)
                else:
                    storage.require_evidence(evidence)
                    storage.require_state(state)
                    reader_gid = storage.reader_gid
                require(len({file_identity(os.fstat(directory))
                             for directory in (state, evidence, target.repo)}) == 3,
                        "BROKER_DIRECTORY_ALIAS")
                guard = AttemptGuard(state)

                def authorize(now):
                    check_context(target)
                    require_named_directory(root_fd, "state", state)
                    require_named_directory(root_fd, "evidence", evidence)
                    if storage is not None:
                        storage.require_evidence(evidence)
                        storage.require_state(state)
                    require_admission(request, enrollment, now=now, core_epoch=core_epoch,
                                      broker_epoch=broker_epoch)

                fault("before_permit")
                guard.consume(request, fault, authorize=lambda: authorize(clock()))
                fault("attempt_consumed")
                if prepare is not None:
                    prepare(target)
                with sequence() as token:
                    def final_check():
                        revalidate(token)
                        if token is not None:
                            target.check(request, publishing=True)
                            target.check_commit(request)
                            authorize(clock())

                    stamp, published_at = _publish(
                        target, request, guard, authorize, clock, fault, stack, final_check)
                    inode = stamp[:2]
                    fault("effect_synced")
                    binding = request.witness_binding()
                    payload = witness_payload(binding, published_inode=inode, published_at=published_at)
                    signature = sign(identity, payload)
                    persist_witness(evidence, binding, executor, signature=signature,
                                    published_inode=inode, published_at=published_at, reader_gid=reader_gid)
                    raw = target.record(evidence, binding.witness_id, executor.uid)
                    require(raw == canonical_json_bytes({"payload": payload, "signature": signature}),
                            "BROKER_WITNESS_MOVED")
                    fault("before_completion")
                    persist_completion(evidence, request, identity, raw, stamp, reader_gid=reader_gid)
                    require_named_directory(root_fd, "evidence", evidence)
                    target.check(request)
                    require(target.observe(request) == stamp, "BROKER_REF_MOVED")
                    if completed is not None:
                        completion = target.record(evidence, "completion-" + binding.witness_id, executor.uid)
                if completed is not None:
                    completed(completion)
                fault("witness_durable")
                ok = True
        except (OSError, ValueError):
            # Negative or interrupted ACK does not say whether the ref was published.
            pass
        try:
            send_frame(peer, {"ack": ok})
        except OSError:
            return False
        if ok:
            fault("ack_sent")
        return ok
