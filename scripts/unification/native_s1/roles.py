"""Private startup barrier and real S1 role entrypoints."""

import ctypes
import errno
import json
import os
import select
import socket
import stat
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from runtime.core_admission import Capability
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
from runtime.red_hat.broker_protocol import Peer, ProtocolError, authenticate, read_frame, require, send_frame
from runtime.red_hat.core_adapter import CoreIntentAdapter
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.execution_binding import capture_binding
from runtime.red_hat.native_bootstrap import ColdNativeBootstrap
from runtime.red_hat.native_services import (
    RoleEndpoint, bind_cold_verifier, bind_core_publication, run_broker, run_sequencer, run_verifier,
    start_core, start_listener,
)
from runtime.red_hat.role_storage import CoreTargetStorage, DirectoryPin, RoleStorage, StorageActor
from runtime.red_hat.sequencer import SequenceClient, SequencedCoreGate
from runtime.red_hat.witness import RegisteredExecutor
from scripts.unification.native_role_supervisor import drop_role_bounding_set
from scripts.unification.native_s1 import host, policy

EPOCH = 1
DEVICE = "native69-s1-owned"
KEY_FILES = {"broker": "signer.pem", "verifier": "verifier.pem"}
CRASHES = {"C1": "after_ref_link", "C2": "effect_synced", "C3": "before_completion",
           "C4": "witness_durable", "R1": "witness_durable",
           "E1": None, "F1": None, "F3": None, "F4": None, "F4-FOLLOWUP": None, "P1": None,
           "N1": None, "N2": None, "N3": None, "N4": None,
           "Q1": None, "Q2": None, "Q3": None, "D1": None, "D2": None, "D3": None, "D4": None,
           "B1": None, "B2": None, "B3": None, "C5": None, "F2": None, "S1B": None}
REPLAYS = tuple("R2-" + case for case in ("C1", "C2", "C3", "C4"))
CRASHES.update({case: CRASHES[case[3:]] for case in REPLAYS})
B2_FIELDS = {"B2-key": "key_id", "B2-epoch": "epoch", "B2-nonce": "nonce", "B2-start": "start_digest",
             "B2-warrant": "warrant_digest", "B2-ref": "ref", "B2-digest": "witness_id"}
B2_CASES = ("B2", *B2_FIELDS, "B2-challenge")
CRASHES.update(dict.fromkeys(B2_CASES))
CLOSED_FAULTS = {'Q3': 'done_missing', 'D1': 'done_missing', 'D2': 'before_slot_sync', 'D3': 'slot_closed'}
SUBSTITUTIONS = frozenset(('B1', 'B3', *B2_CASES))


def tell(channel, **fields):
    send_frame(channel, fields, finish=False)


def hear(channel, timeout):
    require(select.select([channel], [], [], timeout)[0], "NATIVE_S1_CONTROL_TIMEOUT")
    return read_frame(channel, finished=False)


@contextmanager
def observe_dispatch(counts=None):
    """Count the actual Core route and Native handoff; never authorize a call."""
    from runtime.mission.git_publish import CoreRemoteGitRoute
    from runtime.red_hat.native_qualification import NativeQualificationPort

    tracked = {NativeQualificationPort.dispatch.__code__: 'handoffs',
               CoreRemoteGitRoute._dispatch_local_patch.__code__: 'routes'}
    if counts is None:
        counts = {}
    counts.update(dict.fromkeys(tracked.values(), 0))

    def trace(frame, event, _arg):
        if event == 'call' and (name := tracked.get(frame.f_code)) is not None:
            counts[name] += 1

    current, threads = sys.getprofile(), threading.getprofile()
    sys.setprofile(trace)
    threading.setprofile(trace)
    try:
        yield counts
    finally:
        sys.setprofile(current)
        threading.setprofile(threads)


def directory(path):
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def pinned_directory(path):
    from runtime.mission.sandbox_linux import mountid

    fd = directory(path)
    try:
        item = os.fstat(fd)
        return DirectoryPin(item.st_dev, item.st_ino, mountid(fd))
    finally:
        os.close(fd)


def endpoint(root, role):
    return str(root / "io" / policy.SOCKETS[role] / "s")


def bound_listener(root, role):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        address = endpoint(root, role)
        listener.bind(address)
        os.chmod(address, 0o660)
    except BaseException:
        listener.close()
        raise
    return listener


def enrollment_of(wire):
    data = dict(wire)
    data["executor"] = RegisteredExecutor(**data["executor"])
    return ExecutorEnrollment(**data)


def reader_of(wire):
    pins = {key: DirectoryPin(**wire[key]) for key in ("anchor", "repository", "ref_parent")}
    return CoreTargetStorage(**{**wire, **pins, "core": StorageActor(**wire["core"])})


def _restrict_role(actor, reader_gid):
    require(Path("/proc/self/attr/current").read_text().strip() == "unconfined",
            "NATIVE_S1_BOOTSTRAP_PROFILE")
    security = ctypes.CDLL("libapparmor.so.1", use_errno=True)
    security.aa_change_profile.argtypes = [ctypes.c_char_p]
    libc = ctypes.CDLL(None, use_errno=True)
    drop_role_bounding_set()
    os.setgroups([reader_gid])
    os.setresgid(actor.gid, actor.gid, actor.gid)
    os.setresuid(actor.uid, actor.uid, actor.uid)
    name = actor.apparmor.removesuffix(" (enforce)").encode("ascii")
    require(security.aa_change_profile(name) == 0, "NATIVE_S1_APPARMOR_ATTACH")
    require(libc.prctl(38, 1, 0, 0, 0) == 0 and libc.prctl(4, 0, 0, 0, 0) == 0,
            "NATIVE_S1_ROLE_RESTRICTIONS")
    actor.require_process(reader_gid)


def _startup(role, control, ready, completion):
    require(role in ("foreground", "cold", "broker", "verifier", "sequencer")
            and os.getresuid() == (0, 0, 0), "NATIVE_S1_CHILD_START")
    expected_fds = {0, 1, 2, control.fileno(), ready.fileno()}
    if completion is not None:
        expected_fds.add(completion.fileno())
    require(all(int(name) in expected_fds or not Path(f"/proc/self/fd/{name}").exists()
                for name in os.listdir("/proc/self/fd")), "NATIVE_S1_INHERITED_FDS")
    authenticate(control, Peer(os.getppid(), 0, 0))
    spec = hear(control, 750)
    root = host.BASE / spec["session"]
    name = "core" if role in ("foreground", "cold") else role
    actor = StorageActor(**spec["actor"])
    require(actor.apparmor == policy.label(spec["session"], name) + " (enforce)"
            and (os.stat("/proc/self/ns/mnt").st_ino == spec["mount"]), "NATIVE_S1_START_DOMAIN")
    signer = None
    if role in KEY_FILES:
        # Parked roles initially hold no signer. Only the trusted bootstrap
        # of its exact role opens this read-only handle after the release.
        signer = os.open(root / "keys" / KEY_FILES[role], os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        meta = os.fstat(signer)
        require(stat.S_ISREG(meta.st_mode) and meta.st_uid == actor.uid and meta.st_nlink == 1
                and stat.S_IMODE(meta.st_mode) == 0o400, "NATIVE_S1_ROLE_KEY")
    if spec.get("s2_read"):
        from scripts.unification.native_s2.guest import load_cold_material
        spec["succession"] = load_cold_material(root, spec["s2_read"])
    _restrict_role(actor, spec["reader_gid"])
    if role in ("broker", "verifier", "sequencer"):
        policy.install_worker_filter(role)
    tell(control, status="CONFINED", pid=os.getpid(), uid=os.getuid(), gid=os.getgid(),
         profile=actor.apparmor, cgroup=actor.cgroup, groups=os.getgroups(), dumpable=0,
         no_new_privileges=True, caps=0)
    return spec, root, actor, signer


def child(role, control_fd, ready_fd, completion_fd):
    """Only the fixed installed launcher invokes this root-trusted bootstrap."""
    with socket.socket(fileno=control_fd) as control, socket.socket(fileno=ready_fd) as ready:
        control.set_inheritable(False)
        ready.set_inheritable(False)
        completion = socket.socket(fileno=completion_fd) if completion_fd is not None else None
        try:
            if completion is not None:
                completion.set_inheritable(False)
            cfg, root, actor, signer_fd = _startup(role, control, ready, completion)
            if role in ('foreground', 'cold'):
                require(hear(control, 30) == {'action': 'start-core'}, 'NATIVE_S1_CORE_START_COMMAND')
            if role == "foreground":
                return _foreground(root, cfg, control, ready)
            if role == "sequencer":
                with bound_listener(root, role) as listener:
                    fd = directory(root / "sequencer")
                    try:
                        run_sequencer(listener, endpoint(root, role), ready, directory=fd,
                                      directory_pin=DirectoryPin(**cfg["state"]),
                                      actor=actor, reader_gid=cfg["reader_gid"], mount_namespace=cfg["mount"],
                                      core_peer=Peer(**cfg["core"]), broker_peer=Peer(**cfg["broker"]),
                                      epoch=EPOCH, stop=None, fault=lambda point: _sequence_control(cfg, control, point),
                                      publication_fault=lambda point, peer: _sequence_fault(cfg, control, point, peer))
                    finally:
                        os.close(fd)
                return 0
            storage = RoleStorage.from_dict(cfg["storage"])
            enroll = enrollment_of(cfg["enrollment"])
            fd = directory(root)
            try:
                if role == "cold":
                    with observe_dispatch() as counts:
                        return _cold(root, cfg, control, ready, storage, enroll, fd, counts)
                with bound_listener(root, role) as listener:
                    if role == "broker":
                        return _broker(root, cfg, control, ready, completion, storage, enroll, fd, listener,
                                       signer_fd)
                    from cryptography.hazmat.primitives import serialization
                    from runtime.mobile_gateway.wire import Identity

                    try:
                        identity = Identity(serialization.load_pem_private_key(os.read(signer_fd, 4096), password=None))
                    finally:
                        os.close(signer_fd)
                    require(identity.spki == cfg["verifier_spki"], "NATIVE_S1_VERIFIER_KEY")
                    read_probe = None
                    if cfg['case'] in ('N2', 'N3'):
                        from scripts.unification.native_s1.probes import VerifierDenials

                        read_probe = VerifierDenials(cfg['case'], storage, lambda result, observation: tell(
                            control, status='DENIALS', result=result, observation=observation))
                    run_verifier(listener, endpoint(root, role), ready, root_fd=fd, storage=storage,
                                 enrollment=enroll, identity=identity, core_peer=Peer(**cfg["core"]),
                                 core_spki=cfg["core_spki"], reads=cfg["reads"],
                                 qualification_fault_challenge=cfg['case'] == 'B2-challenge',
                                 qualification_read=read_probe, succession=cfg.get("succession"))
                return 0
            finally:
                os.close(fd)
        finally:
            if completion is not None:
                completion.close()


def _foreground(root, cfg, control, ready):
    from scripts.unification.native_s1 import core

    files = root / "core"
    (files / "tmp").mkdir(mode=0o700, exist_ok=True)
    os.environ["TMPDIR"] = str(files / "tmp")
    os.environ["SSL_CERT_FILE"] = str(root / "tls-ca.pem")
    reader = reader_of(cfg["reader"])
    seq = SequenceClient(endpoint(root, "sequencer"), Peer(**cfg["sequencer"]), EPOCH)
    gate = SequencedCoreGate(seq, enabled=True)
    runtime_files = json.loads((root / "runtime/manifest.json").read_bytes())
    body, task, candidate, store = core.prepare(files, root / "repo", cfg["base"], runtime_files, reader)
    with core.tls_core(files, body, reader, gate=gate) as admin:
        core.authorize_adoption(admin, body, store)
    with core.tls_core(files, body, reader, gate=gate, candidates=(candidate,), existing_profile=True) as owner:
        send_frame(ready, {"schema": "aioa.redhat.service-ready.v1", "role": "core"})
        capsule = core.prepare_review(owner, body, task)
        governor = owner.foundation.governor
        epoch = owner.runner.run(TransactionContext(owner.core.local_operator(Capability.READ),
                Capability.READ), lambda tx: governor._load(tx)["epoch"])
        tell(control, status="REVIEW_REQUIRED", capsule=capsule, task_id=task.task_id,
             core_spki=owner.identity.spki, epoch=epoch, origin=owner.origin, source=owner.source[0])
        command = hear(control, 35)
        require(set(command) == {"storage", "enrollment", "broker"}, "NATIVE_S1_CORE_ATTACH")
        storage = RoleStorage.from_dict(command["storage"])
        enroll = enrollment_of(command["enrollment"])
        broker = RoleEndpoint(endpoint(root, "broker"), Peer(**command["broker"]))
        root_fd = directory(root)
        try:
            with bound_listener(root, "core") as release:
                start_listener(release, endpoint(root, "core"))
                power_case = cfg.get("power_case")
                power_counts = {}
                def before_dispatch(binding, grant):
                    tell(control, status="S2_AUTHORIZED", grant=grant, original=snapshot(owner, warrant), dispatch=power_counts.copy())
                    require(hear(control, 30) == {"action": "writer-armed"}, "NATIVE_S2_WRITER_NOT_ARMED")

                def hold_ack():
                    from scripts.unification.native_s2.guest import park
                    tell(control, status="S2_ACK_HELD")
                    park()

                bind_core_publication(owner, task.task_id, storage=storage, anchor=root_fd, sequencer=seq,
                                      broker=broker, release_listener=release, enrollment=enroll, device_id=DEVICE,
                                      before_dispatch=before_dispatch if power_case else None,
                                      hold_ack=hold_ack if power_case else None)
                result = core.task_request(owner, "review_effect", {"task_id": task.task_id})
                preview = result["effect_preview"]
                exact = {k: preview[k] for k in ("task_id", "capsule_digest", "operation_digest")}
                _, warrant, _ = owner.coding_tasks._effect(task.task_id, capsule)
                require(core.task_request(owner, "approve", exact)["state"] == "APPROVED",
                        "NATIVE_S1_OWNER_APPROVAL")
                if power_case:
                    from scripts.unification.native_s2.guest import save_spec
                    save_spec(files, body)
                tell(control, status="APPROVED", operation=exact["operation_digest"])
                command = hear(control, 30)
                require(set(command) == {"action", "case"} and command['action'] == 'apply'
                        and command['case'] in CRASHES, "NATIVE_S1_APPLY_COMMAND")
                if command['case'] == 'N1':
                    from scripts.unification.native_s1.probes import core_denials

                    tell(control, status='DENIALS', result=core_denials(root, storage.exact_ref))
                if command['case'] in ('Q1', 'Q2'):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        applying = pool.submit(_apply, owner, exact)
                        require(hear(control, 30) == {'action': 'stop'}, 'NATIVE_S1_STOP_COMMAND')
                        owner._require_qualified_operator()
                        governor.set_kill(owner.core.local_operator(Capability.MANAGE), True)
                        killed = governor.inspect(owner.core.local_operator(Capability.READ))['kill']
                        tell(control, status='STOP_COMMITTED', kill=killed)
                        applied = applying.result(timeout=12)
                else:
                    applied = _apply(owner, exact, counts=power_counts if power_case else None)
                require(not power_case, "NATIVE_S2_DISPATCH_RETURNED_BEFORE_CUT")
                with observe_dispatch() as replayed:
                    denied = False
                    if command["case"] in REPLAYS:
                        try:
                            core.task_request(owner, "apply", exact)
                        except ValueError:
                            denied = True
                from time import time
                principal = owner.core.local_operator(Capability.COMMIT)
                binding = capture_binding(CoreIntentAdapter(owner.intent_journal), principal, warrant, enroll,
                                          trusted_device_id=DEVICE, now=int(time()), broker_epoch=EPOCH)
                projection = snapshot(owner, warrant)
                config = files / "retained-spec.json"
                with config.open("xb") as stream:
                    stream.write(host.canonical(body))
                    stream.flush()
                    os.fsync(stream.fileno())
                tell(control, status="DURABLE_START", binding=binding.to_wire(), initial=projection,
                     applied=applied, replayed=replayed, replay_denied=denied)
                # Deliberate same-boot process loss once the snapshot was sent.
                # A close on an uncertain publisher could need a poisoned slot.
                os._exit(75)
        finally:
            os.close(root_fd)
    return 0


def _apply(owner, exact, *, counts=None):
    from scripts.unification.native_s1 import core

    with observe_dispatch(counts) as counts:
        try:
            core.task_request(owner, 'apply', exact)
        except CommitOutcomeUnknown:
            pass
    return counts


def _sequence_control(cfg, control, point):
    if cfg['case'] == 'Q2' and point == 'control_waiting':
        tell(control, status='STOP_WAITING')


def _sequence_fault(cfg, control, point, peer):
    if CLOSED_FAULTS.get(cfg['case']) == point:
        tell(control, status='CLOSED_FAULT', point=point)
        if point != 'done_missing':
            if point == 'slot_closed':
                peer.shutdown(socket.SHUT_RDWR)
            raise OSError(errno.EIO, 'NATIVE_S1_SEQUENCE_FAULT')
    if cfg['case'] == 'D4' and point == 'closed_sent':
        tell(control, status='CLOSED_SENT')


def _broker(root, cfg, control, ready, completion, storage, enroll, fd, listener, signer):
    point = CRASHES[cfg["case"]]

    def fault(mark):
        if cfg['case'] == 'F4-FOLLOWUP' and mark == 'before_ref_link':
            from scripts.unification.native_s1.probes import predecessor_write_denials

            tell(control, status='DENIALS', result=predecessor_write_denials(cfg['predecessor_files']))
        if cfg['case'] in ('N4', 'F2') and mark in ('before_ref_link', 'after_ref_link'):
            from scripts.unification.native_s1 import probes

            result = (probes.broker_before_link(root, control) if mark == 'before_ref_link'
                      else probes.broker_after_link(root, storage.exact_ref))
            if cfg['case'] == 'F2' and mark == 'before_ref_link':
                result['fork'] = probes.broker_fork_denial()
            tell(control, status='DENIALS', result=result)
        if mark in ("before_ref_link", "after_ref_link", "ack_sent"):
            tell(control, status="PUBLISH_EVENT", point=mark)
        if mark == 'after_ref_link' and cfg['case'] in ('F1', 'F2'):
            require(hear(control, 20) == {'action': 'finish-writer'}, 'NATIVE_S1_WRITER_PAUSE')
        if (cfg['case'], mark) in (('Q1', 'attempt_consumed'), ('Q2', 'after_ref_link')):
            tell(control, status='STOP_POSITION', point=mark)
            require(hear(control, 12) == {'action': 'finish-writer'}, 'NATIVE_S1_STOP_RACE')
        if point == mark:
            if cfg.get("power_case"):
                if cfg["power_case"] != "C4b":
                    from scripts.unification.native_s2.guest import park
                    tell(control, status="S2_BARRIER", point=mark)
                    park()
            else:
                os._exit(74)

    core = RoleEndpoint(endpoint(root, "core"), Peer(**cfg["core"]))
    def discard_closed():
        require(hear(control, 12) == {'action': 'discard-closed'}, 'NATIVE_S1_DISCARD_CLOSED')
        raise OSError(errno.EIO, 'NATIVE_S1_CLOSED_NOT_CONSUMED')

    def lose_done():
        raise OSError(errno.EIO, 'NATIVE_S1_DONE_NOT_SENT')

    seq = SequenceClient(endpoint(root, "sequencer"), Peer(**cfg["sequencer"]), EPOCH,
                         before_done=lose_done if cfg['case'] in ('D1', 'Q3') else None,
                         before_closed=discard_closed if cfg['case'] == 'D4' else None)
    admission = None
    before_ack = None
    if cfg.get("power_case"):
        from runtime.red_hat.s2_admission import WriterAdmission
        admission = WriterAdmission(control, cfg["authority_spki"].encode("ascii"))
        if cfg["power_case"] == "C4b":
            def before_ack():
                tell(control, status="S2_BROKER_EXIT_BEFORE_ACK")
                os._exit(0)

    applied = run_broker(listener, endpoint(root, "broker"), ready, root_fd=fd, storage=storage, device_id=DEVICE,
                         sequencer=seq, release=core, signer_fd=signer, enrollment=enroll, core_spki=cfg["core_spki"],
                         core_epoch=cfg["epoch"], completion=completion, fault=fault, writer_admission=admission, before_ack=before_ack)
    return 0 if applied else 3


def snapshot(owner, warrant):
    journal = owner.intent_journal

    def read(tx):
        row, state = journal._load(tx, warrant)
        require(row is not None, "NATIVE_S1_START_REQUIRED")
        outbox = tx.get(RecordKind.OUTBOX, journal._key(warrant))
        reservation = journal.governor._load(tx)["reservations"][warrant.risk_reservation_id]
        task = owner.coding_tasks._load(tx, warrant.task_id)
        return {"intent_revision": row.revision, "outbox_revision": outbox.revision,
                "intent": state["outcome"]["contract_type"], "outbox": outbox.payload["state"],
                "reservation": reservation["state"], "reservation_digest": state["reservation"],
                "task": owner.coding_tasks._view(task[1])["state"]}

    principal = owner.core.local_operator(Capability.READ)
    return journal._run(principal, Capability.READ, read)


def _cold(root, cfg, control, ready, storage, enroll, fd, counts):
    observed = {}
    try:
        spec = NativeHostCompositionConfig.load(root / "core/retained-spec.json").with_qualification_target(
            storage.core_target().pre_capsule())
        boot = ColdNativeBootstrap(cfg["task_id"], fd, storage, enroll, DEVICE, EPOCH, cfg["core_spki"],
                                   observe_original=observed.update, succession=cfg.get("succession"))
        owner = start_core(ready, root=root / "core/profile", origin=cfg["origin"], spec=spec,
                           candidates=None, existing_profile=True, cold_bootstrap=boot)
    except (ValueError, OSError, MemoryPatchError) as error:
        # The supervisor still checks the exact expected evidence gap.
        underlying = error.__cause__
        reason = (str(underlying) if type(underlying) is ProtocolError
                  and str(underlying) == 'NATIVE_ROLE_RECOVERY_START' else str(error))
        tell(control, status="COLD_DENIED", reason=reason, dispatch=counts, original=observed or None)
        return 3
    try:
        if cfg.get('observe_only'):
            require(cfg['case'] == 'S1B' and bool(observed), 'NATIVE_S1_ORIGINAL_OBSERVATION')
            tell(control, status='ORIGINAL_OBSERVED', original=observed, dispatch=counts)
            return 0
        port = RoleEndpoint(endpoint(root, "verifier"), Peer(**cfg["verifier"]))
        bind_cold_verifier(owner, port, cfg["verifier_spki"], control=ready)
        tell(control, status="RECOVERY_READY")
        require(hear(control, 20) == {"action": "reconcile"}, "NATIVE_S1_COLD_COMMAND")
        original = owner.coding_tasks.native_witness_recovery_port
        material = original._read_original(owner.core.local_operator(Capability.COMMIT), cfg["task_id"])
        warrant = material["warrant"]
        before = snapshot(owner, warrant)
        if cfg.get('cut_after_settlement'):
            owner.cold_task('reconcile')
            tell(control, status='COMMIT_RETURNED', dispatch=counts)
            os._exit(76)  # Commit returned. No reply crosses the private channel.
        if cfg['case'] in SUBSTITUTIONS:
            try:
                owner.cold_task('reconcile')
            except (OSError, ValueError, MemoryPatchError) as error:
                tell(control, status='RECOVERY_REJECTED', before=before, after=snapshot(owner, warrant),
                     reason=str(error), dispatch=counts)
                return 3
            raise ValueError('NATIVE_S1_SUBSTITUTION_WAS_ACCEPTED')
        if cfg['case'] == 'R1':
            barrier = threading.Barrier(2, timeout=5)

            def reconcile():
                barrier.wait()
                return owner.cold_task('reconcile')

            with ThreadPoolExecutor(max_workers=2) as pool:
                left, right = pool.submit(reconcile), pool.submit(reconcile)
                first, second = left.result(), right.result()
            after = snapshot(owner, warrant)
        else:
            first = owner.cold_task("reconcile")
            after = snapshot(owner, warrant)
            second = owner.cold_task("reconcile")
        repeated = snapshot(owner, warrant)
        tell(control, status="RECOVERED", before=before, after=after, repeated=repeated,
             first=first["intent"], second=second["intent"], verifier_pid=first["verification_process_pid"],
             dispatch=counts)
    finally:
        owner.close()
    return 0
