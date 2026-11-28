"""Noble S1 one-aperture supervisor. Broker remains an unreaped direct child."""

import errno
import fcntl
import json
import os
import pwd
import re
import secrets
import select
import socket
import stat
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from runtime.mobile_gateway.wire import Identity
from runtime.red_hat.broker_protocol import Peer, require
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.execution_binding import NativeExecutionBindingV1
from runtime.red_hat.native_services import await_broker_completion, await_service_ready
from runtime.red_hat.role_storage import CoreTargetStorage, RoleStorage, StorageActor
from runtime.red_hat.witness import RegisteredExecutor
from runtime.red_hat.writer_lifecycle import OneShotWriter, _start_ticks
from scripts.unification.native_role_supervisor import installed_tree, trusted
from scripts.unification.native_s1 import host, policy, roles
from scripts.unification.native_s1.probes import SIBLING, verifier_writable_control

MANDATORY = ("H0", "P1", "C1", "C2", "C3", "C4", "C5", "R1", "R2",
             "N1", "N2", "N3", "N4", "N5", "F1", "F2", "F3", "F4",
             "B1", "B2", "B3", "Q1", "Q2", "Q3", "D1", "D2", "D3", "D4", "E1", "S1B", "I1")
SCENARIOS = frozenset(roles.CRASHES) | {'N5'}


def _mkdir(path, uid, gid, mode):
    path.mkdir(mode=0o700)
    os.chown(path, uid, gid)
    path.chmod(mode)


def _key_bytes(key):
    from cryptography.hazmat.primitives import serialization

    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def _keys(root, actors, *, persistent=False):
    from cryptography.hazmat.primitives.asymmetric import ec

    _mkdir(root / "keys", 0, 0, 0o700)
    if persistent:
        from scripts.unification.native_s2.guest import volatile_dir
        volatile_dir(root / "keys", 0, 0o700)
    ids = {}
    for role, file in roles.KEY_FILES.items():
        key = ec.generate_private_key(ec.SECP256R1())
        actor = actors[role]
        host.write_new(root / "keys" / file, _key_bytes(key), uid=actor.uid, gid=actor.gid, mode=0o400)
        ids[role] = Identity(key).spki
    return ids


def _tls(root, uid, gid):
    """One local trust root scoped to this process tree and this session."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    ca_key = ec.generate_private_key(ec.SECP256R1())
    server_key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    ca = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Native S1 disposable TLS")])

    def certificate(subject, issuer, key):
        return (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=2)))

    root_cert = certificate(ca, ca, ca_key).add_extension(x509.BasicConstraints(ca=True, path_length=0),
                                                          critical=True).sign(ca_key, hashes.SHA256())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (certificate(name, ca, server_key)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    host.write_new(root / "tls-ca.pem", root_cert.public_bytes(serialization.Encoding.PEM), mode=0o444)
    host.write_new(root / "core/server.pem", cert.public_bytes(serialization.Encoding.PEM), uid=uid, gid=gid)
    host.write_new(root / "core/server.key", _key_bytes(server_key), uid=uid, gid=gid)


def _repo(root, broker, core, reader_gid):
    """A deterministic, inert Git base, with only the mutable aperture broker-owned."""
    import shutil

    source = root / "core/source.git"
    git = ("/usr/bin/git", "--no-replace-objects", "--git-dir=" + str(source))
    host.run((*git, "init", "--bare", "--initial-branch=main", "--object-format=sha1", "--template="))
    blob = host.run((*git, "hash-object", "-w", "--stdin"), data=b"def slug(text):\n    return text.strip()\n").strip()
    sub = host.run((*git, "mktree"), data=b"100644 blob " + blob + b"\ttextutil.py\n").strip()
    tree = host.run((*git, "mktree"), data=b"040000 tree " + sub + b"\tsrc\n").strip()
    author = b"Native S1 <owned@example.invalid> 100 +0000\n"
    commit = (b"tree " + tree + b"\nauthor " + author + b"committer " + author + b"\nDisposable Native S1 base\n")
    base = host.run((*git, "hash-object", "-w", "-t", "commit", "--stdin"), data=commit).decode().strip()
    require(re.fullmatch("[0-9a-f]{40}", base), "NATIVE_S1_BASE")
    host.run((*git, "update-ref", "refs/heads/main", base))
    repo = root / "repo"
    shutil.copytree(source, repo, symlinks=False)
    for path in (source, *source.rglob("*")):
        os.chown(path, core.uid, core.gid)
        path.chmod(0o700 if path.is_dir() else 0o600)
    (repo / "refs/heads/aioa").mkdir()
    host.write_new(repo / SIBLING, (base + "\n").encode("ascii"))
    host.write_new(repo / ".aioa-disposable-bare", b"AIOA_DISPOSABLE_BARE_PATCH_V1\n")
    host.write_new(repo / ".redhat-disposable", b"AIOA_RED_HAT_FIXTURE_V1\n")
    for path in (repo, *repo.rglob("*")):
        name = path.relative_to(repo).as_posix()
        writable = (name in ("objects", "refs/heads/aioa")
                    or bool(re.fullmatch(r"objects/[0-9a-f]{2}(?:/[0-9a-f]{38})?", name)))
        os.chown(path, broker.uid if writable else 0, reader_gid)
        path.chmod((0o2750 if writable else 0o750) if path.is_dir() else 0o440)
    return base


def _console(uid):
    try:
        output = host.run(("/usr/bin/loginctl", "show-session", "self", "-p", "Id", "-p", "User",
                           "-p", "Active", "-p", "Remote", "-p", "Seat")).decode().splitlines()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ValueError("BLOCKED_HOST:CORE_ACTIVE_LOCAL_SEAT0") from error
    values = dict(line.split("=", 1) for line in output)
    cg = Path("/proc/self/cgroup").read_text().strip()
    require(values.get("User") == str(uid) and values.get("Active") == "yes" and values.get("Remote") == "no"
            and values.get("Seat") == "seat0" and re.fullmatch("[A-Za-z0-9]+", values.get("Id", ""))
            and cg.endswith(f"/session-{values['Id']}.scope"), "BLOCKED_HOST:CORE_ACTIVE_LOCAL_SEAT0")
    require(int(os.environ.get("SUDO_UID", "0")) == uid, "BLOCKED_HOST:ADMITTED_CONSOLE_CALLER")
    try:
        manager = host.run(("/usr/bin/systemctl", "show", f"user@{uid}.service",
                            "-p", "ActiveState", "-p", "Delegate")).decode().splitlines()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ValueError("BLOCKED_HOST:CORE_USER_MANAGER_DELEGATION") from error
    require(set(manager) == {"ActiveState=active", "Delegate=yes"}, "BLOCKED_HOST:CORE_USER_MANAGER_DELEGATION")
    return pwd.getpwuid(uid).pw_gid, cg


def _airgap():
    links = json.loads(host.run(("/usr/sbin/ip", "-json", "link", "show", "up")))
    require([item["ifname"] for item in links] == ["lo"], "BLOCKED_HOST:DISPOSABLE_GUEST_EGRESS")


def _actors(session, uid, gid, console_cgroup, cgroups, *, existing=False):
    # Per-aperture system accounts are deliberately never recycled by this kit.
    reader = f"n69-r-{session[:16]}"
    if not existing:
        host.run(("/usr/sbin/groupadd", "--system", reader))
    import grp

    reader_gid = grp.getgrnam(reader).gr_gid
    actors = {"core": StorageActor(uid, gid, policy.label(session, "core") + " (enforce)", console_cgroup)}
    for role in ("broker", "sequencer", "verifier"):
        name = f"n69-{role[0]}-{session[:16]}"
        if not existing:
            host.run(("/usr/sbin/useradd", "--system", "--user-group", "--no-create-home",
                      "--shell", "/usr/sbin/nologin", name))
        account = pwd.getpwnam(name)
        actors[role] = StorageActor(account.pw_uid, account.pw_gid, policy.label(session, role) + " (enforce)",
            "0::/" + str(cgroups[role].relative_to("/sys/fs/cgroup")))
    require(len({role.uid for role in actors.values()}) == len({role.gid for role in actors.values()}) == 4
            and reader_gid not in {role.gid for role in actors.values()}, "NATIVE_S1_ROLE_IDENTITIES")
    return actors, reader_gid


def _cgroups(stack, session):
    unit = "aioa-native-s1-cgroup@" + session + ".service"
    host.run(("/usr/bin/systemctl", "start", unit))
    stack.callback(host.run, ("/usr/bin/systemctl", "stop", unit))
    group = host.run(("/usr/bin/systemctl", "show", unit, "--property=ControlGroup", "--value")).decode().strip()
    require(group.startswith("/system.slice/") and group.endswith("/" + unit) and ".." not in Path(group).parts,
            "NATIVE_S1_CONTROL_GROUP")
    base = Path("/sys/fs/cgroup") / group[1:]
    trusted(base, directory=True)
    leaves = {role: base / role for role in ("broker", "sequencer", "verifier")}
    for path in leaves.values():
        path.mkdir(mode=0o755)
        trusted(path, directory=True)
    return leaves


def _install_policy(root, role, rendered, *, retained=False):
    if role == "core":
        require(not os.path.lexists(f"/.aioa-s1-worker-{root.name}"), "NATIVE_S1_WORKER_ALIAS_PATH")
    profile = root / "operator" / f"{role}.apparmor"
    if retained:
        trusted(profile)
        require(profile.read_bytes() == rendered.encode("ascii"), "NATIVE_S2_RETAINED_POLICY")
    else:
        host.write_new(profile, rendered.encode("ascii"))
    host.run(("/usr/sbin/apparmor_parser", "--add", "--skip-cache", str(profile)), timeout=15)
    label = policy.label(root.name, role) + " (enforce)"
    require(label in Path("/sys/kernel/security/apparmor/profiles").read_text().splitlines(),
            "NATIVE_S1_APPARMOR_ENFORCEMENT")
    return host.sha(profile.read_bytes())


def _stop_child(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class Child:
    def __init__(self, stack, root, role, actor, reader_gid, namespace, *, label=None):
        self.name, self.actor = role, actor
        self.label = label or role
        self.root, self.reader_gid, self.namespace = root, reader_gid, namespace
        pairs = [socket.socketpair(), socket.socketpair()]
        if role == "broker":
            pairs.append(socket.socketpair())
        self.control, self.ready = (stack.enter_context(pair[0]) for pair in pairs[:2])
        self.completion = stack.enter_context(pairs[2][0]) if role == "broker" else None
        env = dict(host.ENV)
        env["XDG_RUNTIME_DIR"] = f"/run/user/{actor.uid}"
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="safe.directory", GIT_CONFIG_VALUE_0=str(host.SOURCE))
        args = [str(host.INSTALL), "_role", role]
        fds = [pair[1].fileno() for pair in pairs]
        try:
            with (root / "operator" / f"{self.label}.log").open("xb") as log:
                self.process = subprocess.Popen([*args, *map(str, fds)], env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=log, pass_fds=tuple(fds), close_fds=True,
                    umask=0o027 if role == "broker" else 0o077)
        finally:
            for _, child in pairs:
                child.close()
        stack.callback(_stop_child, self.process)
        self.peer = Peer(self.process.pid, actor.uid, actor.gid)

    def move(self, cgroup):
        (cgroup / "cgroup.procs").write_text(str(self.peer.pid), encoding="ascii")

    def release(self, **extra):
        roles.tell(self.control, session=self.root.name, actor=asdict(self.actor),
                   reader_gid=self.reader_gid, mount=self.namespace, **extra)
        proof = roles.hear(self.control, 10)
        expected = {"status": "CONFINED", "pid": self.peer.pid, "uid": self.peer.uid,
                    "gid": self.peer.gid, "profile": self.actor.apparmor, "cgroup": self.actor.cgroup,
                    "groups": [self.reader_gid], "dumpable": 0, "no_new_privileges": True, "caps": 0}
        require(proof == expected, "NATIVE_S1_CHILD_PROOF")
        proc = Path(f"/proc/{self.peer.pid}")
        require((proc / "attr/current").read_text().strip() == self.actor.apparmor
                and (proc / "cgroup").read_text().strip() == self.actor.cgroup
                and (proc / "ns/mnt").stat().st_ino == self.namespace, "NATIVE_S1_CHILD_KERNEL_IDENTITY")
        return proof

    def ready_listener(self, *, role=None, timeout=None):
        name = role or self.name
        await_service_ready(self.process, self.ready, name, timeout=timeout)
        if name != "core":
            path = Path(roles.endpoint(self.root, name))
            info = path.lstat()
            require(stat.S_ISSOCK(info.st_mode) and (info.st_uid, info.st_gid) == (self.actor.uid, self.reader_gid)
                    and stat.S_IMODE(info.st_mode) == 0o660, "NATIVE_S1_SOCKET_MODE")


def _polkit(stack, child, root):
    read, write = os.pipe2(os.O_CLOEXEC)
    try:
        with (root / "operator" / f"polkit-{child.label}.log").open("xb") as log:
            agent = subprocess.Popen(("/usr/bin/pkttyagent", "--process",
                f"{child.peer.pid},{_start_ticks(child.peer.pid)}", "--notify-fd", str(write)),
                env=host.ENV, stderr=log, pass_fds=(write,), user=child.peer.uid, group=child.peer.gid,
                extra_groups=(), close_fds=True)
        stack.callback(_stop_child, agent)
        os.close(write)
        write = -1
        require(select.select([read], [], [], 10)[0] and os.read(read, 1) == b"" and agent.poll() is None,
                "BLOCKED_HOST:POLKIT_TTY_AGENT")
    finally:
        os.close(read)
        if write >= 0:
            os.close(write)


def _observe_broker(child, denials):
    seen = []
    while select.select([child.control], [], [], 0)[0]:
        try:
            event = roles.hear(child.control, 1)
        except ValueError as error:
            require(str(error) == "BROKER_FRAME_TRUNCATED", "NATIVE_S1_TELEMETRY")
            break
        if event.get('status') == 'DENIALS':
            denials.update(_denials(event))
            continue
        require(event.get("status") == "PUBLISH_EVENT"
                and event.get("point") in ("before_ref_link", "after_ref_link", "ack_sent"),
                "NATIVE_S1_TELEMETRY")
        seen.append(event["point"])
    return seen


def _denials(event):
    require(event.get('status') == 'DENIALS' and type(event.get('result')) is dict
            and bool(event['result']) and all(value in (errno.EACCES, errno.EPERM)
                                              for value in event['result'].values()), 'NATIVE_S1_ROLE_PROBE')
    return event['result']


def _live_writable_descriptors(pid, ref):
    node = ref.stat()
    proc = Path(f'/proc/{pid}')
    retained = []
    for descriptor in (proc / 'fd').iterdir():
        try:
            if not os.path.samestat(descriptor.stat(), node):
                continue
            info = (proc / 'fdinfo' / descriptor.name).read_text().splitlines()
        except FileNotFoundError:
            continue
        flags = next(line for line in info if line.startswith('flags:')).split()[1]
        if int(flags, 8) & os.O_ACCMODE in (os.O_RDWR, os.O_WRONLY):
            retained.append(int(descriptor.name))
    require(retained, 'NATIVE_S1_LIVE_WRITABLE_ALIAS_REQUIRED')
    return retained


def _closure_fault():
    raise OSError(errno.EIO, "NATIVE_S1_INJECTED_CLOSURE_DIRECTORY_FSYNC")


def _hold_injected_fd(stack, directory, target):
    # A supervisor-injected diagnostic holder models a leaked capability.
    # The authorized broker was separately denied fork and SCM_RIGHTS.
    fd = os.open(target, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        holder = subprocess.Popen(('/usr/bin/sleep', '240'), env=host.ENV, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(fd,))
    finally:
        os.close(fd)
    stack.callback(_stop_child, holder)
    (directory / 'cgroup.procs').write_text(str(holder.pid), encoding='ascii')
    _live_writable_descriptors(holder.pid, target)
    return holder


def _probe_control(root):
    control = root / 'operator' / 'probe-control'
    control.mkdir(mode=0o700)
    directory = roles.directory(control)
    fd = os.open('.', os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC, 0o440, dir_fd=directory)
    try:
        os.link(f'/proc/self/fd/{fd}', 'sibling', dst_dir_fd=directory, follow_symlinks=True)
        os.rename('sibling', 'foreign', src_dir_fd=directory, dst_dir_fd=directory)
        os.unlink('foreign', dir_fd=directory)
    finally:
        os.close(fd)
        os.close(directory)
    return {'scope': 'SEPARATE_UNCONFINED_POSITIVE_CONTROL', 'link': 1, 'rename': 1, 'unlink': 1}


def _orchestrate_race(case, broker, core, seq):
    events = []
    if case in ('Q1', 'Q2'):
        if case == 'Q2':
            for point in ('before_ref_link', 'after_ref_link'):
                require(roles.hear(broker.control, 10) == {'status': 'PUBLISH_EVENT', 'point': point},
                        'NATIVE_S1_Q2_PUBLICATION')
                events.append(point)
        position = 'attempt_consumed' if case == 'Q1' else 'after_ref_link'
        require(roles.hear(broker.control, 12) == {'status': 'STOP_POSITION', 'point': position},
                'NATIVE_S1_STOP_POSITION')
        roles.tell(core.control, action='stop')
        if case == 'Q2':
            require(roles.hear(seq.control, 8) == {'status': 'STOP_WAITING'}
                    and not select.select([core.control], [], [], 0)[0], 'NATIVE_S1_STOP_BYPASSED_SLOT')
            roles.tell(broker.control, action='finish-writer')
        require(roles.hear(core.control, 10) == {'status': 'STOP_COMMITTED', 'kill': True},
                'NATIVE_S1_DURABLE_STOP')
        if case == 'Q1':
            roles.tell(broker.control, action='finish-writer')
    if case in roles.CLOSED_FAULTS:
        require(roles.hear(seq.control, 15) == {'status': 'CLOSED_FAULT', 'point': roles.CLOSED_FAULTS[case]},
                'NATIVE_S1_CLOSE_FAULT_NOT_REACHED')
    if case == 'D4':
        require(roles.hear(seq.control, 15) == {'status': 'CLOSED_SENT'}, 'NATIVE_S1_CLOSE_SEND_NOT_REACHED')
        roles.tell(broker.control, action='discard-closed')
    return events


def _reject_sequence_restart(stack, seq, directory, actor, root, group, namespace, *, core, broker):
    _stop_child(seq.process)
    os.unlink(roles.endpoint(root, 'sequencer'))  # Only the dead role's socket, never fencing state.
    restart = Child(stack, root, 'sequencer', actor, group, namespace, label='sequencer-restart')
    restart.move(directory)
    restart.release(core=asdict(core.peer), broker=asdict(broker.peer), case='Q3',
                    state=asdict(roles.pinned_directory(root / 'sequencer')))
    require(restart.process.wait(timeout=10) != 0, 'NATIVE_S1_SEQUENCE_RESTART_ALLOWED')
    log = (root / 'operator/sequencer-restart.log').read_text().splitlines()
    require(bool(log) and json.loads(log[-1])['reason'] == 'RH07_SEQUENCE_OUTSTANDING',
            'NATIVE_S1_SEQUENCE_RESTART_PROOF')


def _substitute(root, binding, case):
    """A privileged fault in a fresh aperture, after the original writer exited."""
    if case == 'B3':
        evidence = root / 'evidence'
        original = evidence.stat()
        evidence.rename(root / 'operator/original-evidence')
        _mkdir(evidence, original.st_uid, original.st_gid, stat.S_IMODE(original.st_mode))
        require(original.st_ino != evidence.stat().st_ino, 'NATIVE_S1_SUBSTITUTION_INODE')
        return {'changed': 'evidence-directory-inode', 'original_inode': original.st_ino,
                'substitute_inode': evidence.stat().st_ino}
    path = (root / 'repo' / binding.request.exact_ref if case == 'B1'
            else root / 'evidence' / binding.request.witness_binding().witness_id)
    original = path.stat()
    data = path.read_bytes()
    after = data
    changed = 'ref-inode-same-oid'
    if case in roles.B2_CASES:
        corrupted = json.loads(data)
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes

        field = roles.B2_FIELDS.get(case)
        if field is None:
            corrupted['signature'] = 'AAAA'
            changed = 'witness-signature'
        else:
            original_value = corrupted['payload'][field]
            if field == 'epoch':
                invalid_value = original_value + 1
            elif field == 'ref':
                invalid_value = original_value + '-foreign'
            else:
                invalid_value = ('1' if original_value[0] == '0' else '0') + original_value[1:]
            corrupted['payload'][field] = invalid_value
            changed = 'witness-' + field
        after = canonical_json_bytes(corrupted)
    local = root / 'operator/substitution'
    host.write_new(local, after, uid=original.st_uid, gid=original.st_gid, mode=stat.S_IMODE(original.st_mode))
    os.replace(local, path)
    require(original.st_ino != path.stat().st_ino, 'NATIVE_S1_SUBSTITUTION_INODE')
    return {'changed': changed,
            'original_sha256': host.sha(data), 'substitute_sha256': host.sha(after),
            'original_inode': original.st_ino, 'substitute_inode': path.stat().st_ino}


def _cold_roles(stack, root, actors, group, namespace, cgroups, config, proof, *, closure, cut=False,
                observe_only=False, repeat=False):
    suffix = '-repeat' if repeat else '-lost-reply' if cut else '-observe' if observe_only else ''
    cold = Child(stack, root, 'cold', actors['core'], group, namespace, label='cold' + suffix)
    verifier = Child(stack, root, 'verifier', actors['verifier'], group, namespace, label='verifier' + suffix)
    verifier.move(cgroups['verifier'])
    if closure:
        proof['verifier' + suffix] = verifier.release(**config, core=asdict(cold.peer),
            reads=1 if cut or config['case'] == 'B2-challenge' else 2)
        if config['case'] in ('N2', 'N3'):
            proof['verifier-writable-control'] = verifier_writable_control(root / 'operator', config['case'])
            if config['case'] == 'N3':
                require(stat.S_ISREG((root / 'state/lock').lstat().st_mode), 'NATIVE_S1_PROBE_ATTEMPT_LOCK')
        verifier.ready_listener()
    proof['cold' + suffix] = cold.release(**config, verifier=asdict(verifier.peer), cut_after_settlement=cut,
                                         observe_only=observe_only)
    _polkit(stack, cold, root)
    roles.tell(cold.control, action='start-core')
    result = roles.hear(cold.control, 140)
    if config.get("s2_read") and result.get("status") == "COLD_DENIED":
        return cold, verifier, result
    if closure:
        require(result == {'status': 'RECOVERY_READY'}, 'NATIVE_S1_COLD_READY')
        cold.ready_listener(role='core', timeout=10)
        roles.tell(cold.control, action='reconcile')
        result = roles.hear(cold.control, 20)
        if config['case'] in ('N2', 'N3'):
            event = roles.hear(verifier.control, 10)
            denials = _denials(event)
            expected = set(proof['verifier-writable-control'])
            if config['case'] == 'N3':
                expected.add('attempt-state')
            require(set(denials) == expected, 'NATIVE_S1_VERIFIER_PROBE_COVERAGE')
            observation = event['observation']
            role = observation['role']
            require(role['pid'] == verifier.peer.pid and role['uid'] == [verifier.peer.uid] * 3
                    and role['gid'] == [verifier.peer.gid] * 3 and role['groups'] == [group]
                    and role['profile'] == verifier.actor.apparmor and role['cgroup'] == verifier.actor.cgroup
                    and role['no_new_privileges'] == 1 and role['dumpable'] == 0
                    and role['namespaces']['mnt'] == namespace and not any(role['capabilities'].values()),
                    'NATIVE_S1_VERIFIER_PROBE_ROLE')
            require(set(observation['reads']) == {'ref', 'commit', 'witness', 'completion'}
                    and all(row['before'] == row['after'] for row in observation['reads'].values()),
                    'NATIVE_S1_VERIFIER_READBACK')
            proof['verifier-denials'] = denials
            proof['verifier-readback'] = observation
        if cut:
            require(result == {'status': 'COMMIT_RETURNED', 'dispatch': {'handoffs': 0, 'routes': 0}},
                    'NATIVE_S1_C5_COMMIT_TELEMETRY')
            try:
                roles.hear(cold.control, 8)
            except ValueError as error:
                require(str(error) == 'BROKER_FRAME_TRUNCATED', 'NATIVE_S1_RECOVERY_CHANNEL')
            else:
                raise ValueError('NATIVE_S1_C5_REPLY_PRESENT')
            result = {'status': 'REPLY_LOST'}
    return cold, verifier, result


def _predecessor(session, observed_host):
    require(type(session) is str and re.fullmatch('[0-9a-f]{32}', session), 'NATIVE_S1_PREDECESSOR_SESSION')
    root = host.BASE / session
    trusted(root, directory=True)
    case_path = root / 'operator/case.json'
    trusted(case_path)
    case = json.loads(case_path.read_bytes())
    require(case['case'] == 'F4' and case['session'] == session and case['status'] == 'PASS'
            and case['old_writer_restart_denied'] is True
            and all(case['host'][field] == observed_host[field] for field in ('source', 'tree', 'boot_sha256')),
            'NATIVE_S1_PREDECESSOR_CASE')
    request = NativeExecutionBindingV1.from_wire(case['original_binding']).request
    witness = request.witness_binding().witness_id
    return {'prior-ref': str(root / 'repo' / request.exact_ref),
            'prior-object': str(root / 'repo/objects' / request.new_oid[:2] / request.new_oid[2:]),
            'prior-witness': str(root / 'evidence' / witness),
            'prior-completion': str(root / 'evidence' / ('completion-' + witness))}


def _predecessor_snapshot(paths):
    result = {}
    for name, path in paths.items():
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC), 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 65536,
                    'NATIVE_S1_PREDECESSOR_FILE')
            result[name] = (info.st_dev, info.st_ino, info.st_ctime_ns, host.sha(stream.read(65537)))
    return result


def run_case(case, digest, *, predecessor=None, power=None):
    require(case in SCENARIOS and os.getresuid() == (0, 0, 0), "NATIVE_S1_RUN_CONFIGURATION")
    require((case == 'F4-FOLLOWUP') == (predecessor is not None), 'NATIVE_S1_PREDECESSOR_CONFIGURATION')
    manifest, observed = host.host_pins(host.CONFIG / "manifest.json", digest, host.CONFIG / "management.json",
                                       system=True)
    host.trusted(host.INSTALL)
    host.trusted(host.UNIT)
    require(host.INSTALL.samefile(Path(os.path.abspath(sys.argv[0])))
            and installed_tree(host.SOURCE) == observed["tree"]
            and host.UNIT.read_bytes() == (host.SOURCE / "scripts/unification/native_s1" / host.UNIT.name).read_bytes(),
            "NATIVE_S1_INSTALLED_SOURCE")
    uid = manifest["s1"]["core_uid"]
    gid, console_group = _console(uid)
    _airgap()
    os.umask(0o077)
    if power is not None:
        from runtime.red_hat.role_storage import PersistentVolume
        from scripts.unification.native_s2.guest import boot_hash, require_mount
        require(case == ("C4" if power["case"] in ("C4a", "C4b") else power["case"])
                and power["source_sha"] == observed["source"] and power["tree"] == observed["tree"]
                and power["boot_sha256"] == boot_hash(), "NATIVE_S2_PLAN_PINS")
        require_mount(PersistentVolume(**power["volume"]))
    if not host.BASE.exists():
        _mkdir(host.BASE, 0, 0, 0o755)
    require(stat.S_IMODE(host.BASE.lstat().st_mode) == 0o755, "NATIVE_S1_BASE_MODE")
    trusted(host.BASE, directory=True)
    session = secrets.token_hex(16) if power is None else power["session"]
    root = host.BASE / session
    report = {"schema": "aioa.native-s1.case-result.v2", "case": case, "host": observed,
              "session": session, "status": "FAIL", "role_proofs": {}, "policy_sha256": {},
              "metrics": {"link_attempts": None, "publications": None, "settlements": None,
                          "automatic_redispatches": None, "replay_requests": 0, "replay_rejected": 0}}
    with ExitStack() as stack:
        lock = os.open(host.BASE / '.native-s1-coordinator.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                       0o600)
        stack.callback(os.close, lock)
        info = os.fstat(lock)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600, 'NATIVE_S1_COORDINATOR_LOCK')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cgroups = _cgroups(stack, session)
        actors, reader_gid = _actors(session, uid, gid, console_group, cgroups)
        namespace = os.stat("/proc/self/ns/mnt").st_ino
        _mkdir(root, 0, reader_gid, 0o750)
        _mkdir(root / "operator", 0, 0, 0o700)
        try:
            if case == 'N5':
                report.update(control=_probe_control(root), status='PASS')
            else:
                _exercise(stack, root, report, manifest, actors, reader_gid, namespace, cgroups, predecessor, power=power)
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
            report["reason"] = str(error)
        finally:
            host.write_new(root / "operator/case.json", host.canonical(report))
    return report


def _exercise(stack, root, report, manifest, actors, group, namespace, cgroups, predecessor, *, power=None):
    case = report["case"]
    source = manifest["host"]["source"]
    _mkdir(root / "core", actors["core"].uid, actors["core"].gid, 0o700)
    _mkdir(root / "io", 0, group, 0o750)
    if power is not None:
        from scripts.unification.native_s2 import guest
        guest.volatile_dir(root / "io", group, 0o750)
    for role, name in policy.SOCKETS.items():
        _mkdir(root / "io" / name, actors[role].uid, group, 0o2750)
    _mkdir(root / "state", actors["broker"].uid, actors["broker"].gid, 0o700)
    _mkdir(root / "sequencer", actors["sequencer"].uid, actors["sequencer"].gid, 0o700)
    _mkdir(root / "evidence", actors["broker"].uid, group, 0o2750)
    _mkdir(root / "staging", actors["broker"].uid, group, 0o2700)
    base = _repo(root, actors["broker"], actors["core"], group)
    _tls(root, actors["core"].uid, actors["core"].gid)
    spki = _keys(root, actors, persistent=power is not None)
    now = int(time.time())
    enrollment = ExecutorEnrollment(RegisteredExecutor(
        "native-s1-broker", actors["broker"].uid, spki["broker"]), 1, now - 1, now + 1500)
    host.stage_runtime(root / "runtime", host.CONFIG / "runtime.json", manifest["s1"]["runtime_sha256"])
    for role, profile in policy.profiles(root.name, source, actors["core"].uid, persistent=power is not None).items():
        report["policy_sha256"][role] = _install_policy(root, role, profile)

    pin = roles.pinned_directory
    reader = CoreTargetStorage(actors["core"], actors["broker"].uid, group, namespace,
                              pin(root), pin(root / "repo"), pin(root / "repo/refs/heads/aioa"))
    broker = Child(stack, root, "broker", actors["broker"], group, namespace)
    core = Child(stack, root, "foreground", actors["core"], group, namespace)
    seq = Child(stack, root, "sequencer", actors["sequencer"], group, namespace)
    seq.move(cgroups["sequencer"])
    report["role_proofs"]["sequencer"] = seq.release(core=asdict(core.peer), broker=asdict(broker.peer),
                                                    case=case, state=asdict(pin(root / "sequencer")))
    seq.ready_listener()
    options = {} if power is None else {"power_case": power["case"]}
    report["role_proofs"]["foreground"] = core.release(reader=asdict(reader), sequencer=asdict(seq.peer), base=base, **options)
    _polkit(stack, core, root)
    roles.tell(core.control, action="start-core")
    core.ready_listener(role="core", timeout=150)
    offered = roles.hear(core.control, 210)
    require(offered["status"] == "REVIEW_REQUIRED" and offered["source"] == source
            and re.fullmatch("[0-9a-f]{64}", offered["capsule"]),
            "NATIVE_S1_NORMAL_REVIEW")
    ref = "refs/heads/aioa/nz11-" + offered["capsule"][:32]
    profile = policy.profiles(root.name, source, actors["core"].uid, exact_ref=ref, persistent=power is not None)["broker"]
    policy_hash = _install_policy(root, "broker", profile)
    report["policy_sha256"]["broker"] = policy_hash
    host.write_new(root / "writer-policy", profile.encode("ascii"), gid=group, mode=0o440)
    storage = RoleStorage(actors["core"], actors["broker"], actors["verifier"], group, namespace, ref,
        reader.anchor, reader.repository, reader.ref_parent, pin(root / "evidence"), staging=pin(root / "staging"),
        policy_sha256=policy_hash, state=pin(root / "state"), writer_cgroup=pin(cgroups["broker"]))
    if power is not None:
        from runtime.red_hat.role_storage import PersistentVolume
        storage = replace(storage, persistent=PersistentVolume(**power["volume"]))
    root_fd = roles.directory(root)
    stack.callback(os.close, root_fd)
    cgroup_fd = roles.directory(cgroups["broker"])
    stack.callback(os.close, cgroup_fd)
    writer = stack.enter_context(OneShotWriter(root_fd, storage, cgroup_fd,
                    before_closure_sync=_closure_fault if case == "E1" else None))
    broker.move(cgroups["broker"])
    writer.register(broker.process)
    broker_info = {"storage": storage.to_dict(), "enrollment": asdict(enrollment), "case": case,
                   "core": asdict(core.peer), "sequencer": asdict(seq.peer),
                   "core_spki": offered["core_spki"], "epoch": offered["epoch"]}
    if power is not None:
        broker_info.update(power_case=power["case"], authority_spki=power["authority_spki"])
    if predecessor is not None:
        prior_files = _predecessor(predecessor, report['host'])
        before = _predecessor_snapshot(prior_files)
        broker_info['predecessor_files'] = prior_files
    report["role_proofs"]["broker"] = broker.release(**broker_info)
    broker.ready_listener()
    roles.tell(core.control, storage=storage.to_dict(), enrollment=asdict(enrollment), broker=asdict(broker.peer))
    approved = roles.hear(core.control, 30)
    require(approved["status"] == "APPROVED", "NATIVE_S1_APPROVAL")
    if power is not None:
        original = {"storage": storage.to_dict(), "enrollment": asdict(enrollment), "core_spki": offered["core_spki"],
                    "origin": offered["origin"], "task_id": offered["task_id"], "case": case,
                    "trial": power["case"], "vm_uuid": power["vm_uuid"], "source": source, "tree": power["tree"],
                    "predecessor_boot": power["boot_sha256"]}
        guest.keep_original(root, original)
    roles.tell(core.control, action="apply", case=case)
    if power is not None:
        guest.control_trial(root, power, core, broker, writer, enrollment, original)
        raise ValueError("NATIVE_S2_TRIAL_RESUMED")
    if case == 'N1':
        report['denials'] = _denials(roles.hear(core.control, 10))
    events = _orchestrate_race(case, broker, core, seq)
    produced = roles.hear(core.control, 40)
    require(produced["status"] == "DURABLE_START" and produced["initial"]["intent"] == "Unknown"
            and produced["initial"]["outbox"] == "HELD" and produced["initial"]["reservation"] == "UNKNOWN",
            "NATIVE_S1_HELD_START_REQUIRED")
    binding = NativeExecutionBindingV1.from_wire(produced["binding"])
    zero_dispatch = {"handoffs": 0, "routes": 0}
    require(produced["applied"] == {"handoffs": 1, "routes": 1}
            and produced["replayed"] == zero_dispatch and produced["replay_denied"] == (case in roles.REPLAYS),
            "NATIVE_S1_CORE_DISPATCH_COUNT")
    report["metrics"]["replay_requests"] = int(case in roles.REPLAYS)
    report["metrics"]["replay_rejected"] = int(produced["replay_denied"])
    report.update(original_binding=binding.to_wire(), initial=produced["initial"],
                  executor_enrollment=asdict(enrollment), core_spki=offered["core_spki"],
                  verifier_spki=spki["verifier"])
    no_close = case in roles.CLOSED_FAULTS or case in ('Q1', 'D4')
    interrupted = roles.CRASHES[case] in ('after_ref_link', 'effect_synced', 'before_completion') or no_close
    expect_closure = not interrupted and case not in ('E1', 'F2')
    holder = None
    if case in ('F1', 'F2'):
        report['live_writable_descriptors'] = _live_writable_descriptors(broker.peer.pid, root / 'repo' / ref)
        try:
            writer.close_writer(binding, {}, enrollment)
        except ValueError as error:
            require(str(error) == 'NATIVE_S1_WRITER_STILL_LIVE', 'NATIVE_S1_F1_CLOSURE')
        else:
            raise ValueError('NATIVE_S1_F1_CLOSURE_ACCEPTED')
        require(not (root / 'writer-closed').exists(), 'NATIVE_S1_F1_VISIBLE_CLOSURE')
        if case == 'F2':
            holder = _hold_injected_fd(stack, cgroups['broker'], root / 'repo' / ref)
            report['injected_fd_holder_pid'] = holder.pid
        roles.tell(broker.control, action='finish-writer')
    try:
        await_broker_completion(writer, broker.completion, binding, enrollment, deadline=time.monotonic() + 15)
    except ValueError as error:
        require((interrupted and str(error) == "BROKER_FRAME_TRUNCATED")
                or (case == 'F2' and str(error) == 'NATIVE_S1_WRITER_STILL_LIVE'
                    and holder.poll() is None and not (root / 'writer-closed').exists()),
                "NATIVE_S1_PRODUCER_COMPLETION")
    except OSError as error:
        require(case == "E1" and error.errno == errno.EIO
                and (root / "writer-closed").exists() and not (root / "writer-closed-synced").exists(),
                "NATIVE_S1_SUPERVISOR_BARRIER")
    else:
        require(expect_closure, "NATIVE_S1_UNEXPECTED_CLOSURE")
    code = broker.process.wait(timeout=6)
    allowed_exit = (3,) if no_close else (0, 3) if roles.CRASHES[case] is None else (74,)
    require(code in allowed_exit, "NATIVE_S1_BROKER_EXIT")
    report["broker_exit"] = code
    events += _observe_broker(broker, report.setdefault('denials', {}))
    if case == 'N4':
        require(len(report['denials']) == 6, 'NATIVE_S1_N4_PROBE_COUNT')
    if case == 'F2':
        require(len(report['denials']) == 7 and holder.poll() is None, 'NATIVE_S1_F2_FD_PROOF')
    if predecessor is not None:
        require(set(report['denials']) == set(prior_files) and _predecessor_snapshot(prior_files) == before,
                'NATIVE_S1_PREDECESSOR_CHANGED')
        report['predecessor'] = {'session': predecessor, 'snapshot': before}
    report["metrics"]["link_attempts"] = events.count("before_ref_link")
    report["metrics"]["publications"] = events.count("after_ref_link")
    report["metrics"]["broker_ack_send_completed"] = "ack_sent" in events
    report["metrics"]["core_ack_consumed"] = None  # The ACK is informational and deliberately not interpreted.
    # A separate observation corroborates the real return of the link syscall.
    target = root / 'repo' / ref
    if case == 'Q1':
        require(not events and not target.exists(), 'NATIVE_S1_STOP_WON_NO_EFFECT')
    else:
        expected_events = ["before_ref_link", "after_ref_link"] + (["ack_sent"] if code == 0 else [])
        require(events == expected_events and target.read_bytes() == (binding.request.new_oid + "\n").encode(),
                "NATIVE_S1_PHYSICAL_EFFECT")
    require(core.process.wait(timeout=15) == 75, "NATIVE_S1_PRODUCER_CORE_EXIT")
    if case == 'Q3':
        _reject_sequence_restart(stack, seq, cgroups['sequencer'], actors['sequencer'], root, group, namespace,
                                 core=core, broker=broker)
        report['sequencer_restart_denied'] = True
    if case == "F4":
        try:
            with OneShotWriter(root_fd, storage, cgroup_fd):
                raise ValueError("NATIVE_S1_OLD_WRITER_WAS_RELAUNCHED")
        except FileExistsError:
            report["old_writer_restart_denied"] = True
    if case == 'B2-challenge':
        report['injected_substitution'] = {'changed': 'signed-readback-challenge'}
    elif case in roles.SUBSTITUTIONS:
        report['injected_substitution'] = _substitute(root, binding, case)

    cfg = {"storage": storage.to_dict(), "enrollment": asdict(enrollment), "core_spki": offered["core_spki"],
           "task_id": offered["task_id"], "origin": offered["origin"], "verifier_spki": spki["verifier"],
           "case": case}
    if case == 'S1B':
        changed = replace(storage, writer_cgroup=replace(storage.writer_cgroup, mount=storage.writer_cgroup.mount + 1))
        cfg['storage'] = changed.to_dict()
        report['mount_pin_disagrees'] = changed.digest != storage.digest
    proofs = report['role_proofs']
    if case == 'C5':
        first, first_verifier, lost = _cold_roles(stack, root, actors, group, namespace, cgroups, cfg,
                                                proofs, closure=True, cut=True)
        require(first.process.wait(timeout=5) == 76 and first_verifier.process.wait(timeout=5) == 0
                and lost == {'status': 'REPLY_LOST'}, 'NATIVE_S1_SETTLEMENT_REPLY_LOSS')
        os.unlink(roles.endpoint(root, 'verifier'))
        report['first_settlement_reply'] = lost
    verify_effect = expect_closure and case != 'S1B'
    cold, verifier, recovered = _cold_roles(stack, root, actors, group, namespace, cgroups, cfg,
                                           proofs, closure=verify_effect)
    if verify_effect:
        if case in roles.SUBSTITUTIONS:
            verifier_exit = 0 if case == 'B2-challenge' else 1
            require(cold.process.wait(timeout=5) == 3 and verifier.process.wait(timeout=5) == verifier_exit
                    and recovered['status'] == 'RECOVERY_REJECTED' and recovered['before'] == produced['initial']
                    and recovered['before'] == recovered['after'], 'NATIVE_S1_SUBSTITUTION_REJECTION')
            if case == 'B2-challenge':
                require(recovered['reason'] == 'RH06_VERIFIER_REPLAY_OR_BINDING', 'NATIVE_S1_CHALLENGE_DENIAL_REASON')
            else:
                log = (root / 'operator/verifier.log').read_text().splitlines()
                require(log and json.loads(log[-1])['reason'] == 'NATIVE_S1_COMPLETION_CHANGED',
                        'NATIVE_S1_SUBSTITUTION_VERIFIER_REASON')
            report['metrics']['settlements'] = 0
        else:
            require(cold.process.wait(timeout=5) == 0 and verifier.process.wait(timeout=5) == 0
                and recovered["status"] == "RECOVERED" and recovered["first"] == recovered["second"]
                and recovered["before"] == (recovered['after'] if case == 'C5' else produced['initial'])
                and recovered["after"] == recovered["repeated"]
                and recovered["after"]["intent"] == "Applied" and recovered["after"]["task"] == "VERIFIED"
                and recovered["after"]["reservation"] == "COMMITTED"
                and recovered["after"]["intent_revision"] == produced["initial"]["intent_revision"] + 1
                and recovered["verifier_pid"] == verifier.peer.pid, "NATIVE_S1_EXACT_SETTLEMENT")
            report["metrics"]["settlements"] = 1
    else:
        expected_error = 'NATIVE_ROLE_RECOVERY_START' if case == 'S1B' else 'NATIVE_S1_WRITER_CLOSURE_UNAVAILABLE'
        require(cold.process.wait(timeout=5) == 3 and recovered == {
            "status": "COLD_DENIED", "reason": expected_error, "dispatch": zero_dispatch,
            "original": None if case == 'S1B' else produced['initial']},
            "NATIVE_S1_HELD_RECOVERY")
        if case == 'S1B':
            original, _, observation = _cold_roles(stack, root, actors, group, namespace, cgroups,
                {**cfg, 'storage': storage.to_dict()}, proofs, closure=False, observe_only=True)
            require(original.process.wait(timeout=5) == 0 and observation == {
                'status': 'ORIGINAL_OBSERVED', 'original': produced['initial'], 'dispatch': zero_dispatch},
                'NATIVE_S1_ORIGINAL_OBSERVATION')
            report['original_after_pin_denial'] = observation['original']
        report["metrics"]["settlements"] = 0
    require(recovered["dispatch"] == zero_dispatch, "NATIVE_S1_UNAUTHORIZED_RECOVERY_DISPATCH")
    if holder is not None:
        require(holder.poll() is None, 'NATIVE_S1_F2_HOLDER_EXITED_EARLY')
        _stop_child(holder)
    report["metrics"]["automatic_redispatches"] = recovered["dispatch"]["handoffs"]
    report["recovery"] = recovered
    report["status"] = "PASS"
