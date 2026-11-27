"""Session-specific AppArmor policy and post-bootstrap seccomp for S1 roles."""

import ctypes
import errno
import re
import socket

from runtime.red_hat.broker_protocol import require
from scripts.unification.native_writer_policy import storage_rules

ROLES = ("core", "broker", "verifier", "sequencer")
SOCKETS = {"core": "r", "broker": "b", "verifier": "v", "sequencer": "s"}
PEERS = {
    "core": ("broker", "verifier", "sequencer"),
    "broker": ("core", "sequencer"),
    "verifier": (),
    "sequencer": (),
}


def label(session, role):
    require(type(session) is str and re.fullmatch("[0-9a-f]{32}", session)
            and role in ROLES, "NATIVE_S1_POLICY_ROLE")
    return f"aioa-n69-{session}-{role}"


def profiles(session, source_sha, core_uid, *, exact_ref=None):
    require(type(source_sha) is str and re.fullmatch("[0-9a-f]{40}", source_sha)
            and type(core_uid) is int and 0 < core_uid < 2**31, "NATIVE_S1_POLICY_SOURCE")
    source = f"/opt/aioa/native-qualification/{source_sha}"
    root = f"/run/aioa-qualification/{session}"
    labels = {role: label(session, role) for role in ROLES}
    endpoints = {role: f"{root}/io/{name}/s" for role, name in SOCKETS.items()}
    common = (
        f"{source}/ r,",
        f"{source}/** mr,",
        f"/opt/aioa/native-s1-deps/{source_sha}/** mr,",
        "/usr/bin/python3.12 mr,",
        "/usr/lib/python3.12/** mr,",
        "/usr/lib/python3/dist-packages/** mr,",
        "/{,usr/}lib{,64}/** mr,",
        "/etc/{ld.so.cache,nsswitch.conf,localtime,passwd,group,hosts} r,",
        "/usr/share/{locale,zoneinfo}/** r,",
        "/dev/{null,urandom,random} rw,",
        "@{PROC}/sys/kernel/random/boot_id r,",
        "@{PROC}/@{pid}/{stat,status,cgroup,attr/current} r,",
        "@{PROC}/@{pid}/{fd,fdinfo,ns}/{,**} r,",
        "/sys/devices/system/cpu/** r,",
        # Anonymous socketpairs are inherited from the trusted launcher.
        'unix (send, receive) type=stream addr=none peer=(label=unconfined),',
        'unix (create, getattr, getopt, setopt, shutdown) type=stream,',
        'signal (receive) peer=unconfined,',
        'deny ptrace,',
        'deny /sys/fs/cgroup/** w,',
        "/ r,",
        "/run/ r,",
        "/run/aioa-qualification/ r,",
        f"{root}/ r,",
    )
    rendered = {}
    for role in ROLES:
        if role == "broker" and exact_ref is None:
            continue
        endpoint = endpoints[role]
        rules = list(common)
        rules += [
            f'{endpoint} rw,',
            f'{endpoint.rsplit("/", 1)[0]}/ r,',
        ]
        # Pathname sockets are mediated by file rules; accepted messages
        # are additionally authenticated by the existing SO_PEERCRED checks.
        for peer in PEERS[role]:
            rules.append(f'{endpoints[peer]} rw,')
        if role in ("core", "verifier"):
            rules.extend((
                f"{root}/repo/{{,**}} r,",
                f"{root}/evidence/{{,**}} r,",
                f"{root}/{{writer-launch,writer-process,writer-closed,writer-closed-synced}} r,",
            ))
        if role == "broker":
            rules.extend((f"{root}/keys/signer.pem r,", f"{root}/operator/broker.log w,"))
            rules.append(storage_rules(session, exact_ref).rstrip())
        elif role == "verifier":
            rules.extend((f"{root}/keys/verifier.pem r,", f"{root}/operator/{{verifier,verifier-lost-reply}}.log w,"))
        elif role == "sequencer":
            rules.extend((f"{root}/sequencer/ rw,", f"{root}/sequencer/** rwlk,",
                          f"{root}/operator/{{sequencer,sequencer-restart}}.log w,"))
        elif role == "core":
            system_bus = "/run/dbus/system_bus_socket"
            user_bus = f"/run/user/{core_uid}/{{bus,systemd/private}}"
            # The foreground Core uses the existing local TLS challenge and
            # delegates its already-pinned validation worker to the user manager.
            rules.extend((
                "network inet stream,",
                f"{root}/core/{{,**}} rwkl,",
                f'{root}/core/** mr,',
                f'{root}/core/tmp/**/cc* rw,',
                f"{root}/runtime/{{,**}} r,",
                f"{root}/tls-ca.pem r,",
                f'{system_bus} rw,',
                f'{user_bus} rw,',
                "/usr/bin/{git,loginctl,pkcheck,systemctl,systemd-run,prlimit,x86_64-linux-gnu-gcc*,x86_64-linux-gnu-as,x86_64-linux-gnu-ld*,gcc*,as,ld*,cc} rix,",
                "/usr/bin/bwrap rix,",
                "userns,",
                "capability sys_admin,",
                "mount options=(ro, bind) -> /**,",
                "mount options=(ro, remount, bind) -> /**,",
                "mount fstype=tmpfs -> /{,**},",
                "mount fstype=proc -> /proc/,",
                "umount /**,",
                f'{root}/operator/{{foreground,cold,cold-lost-reply}}.log w,',
                "/usr/lib/gcc/** rix,",
                "/usr/include/** r,",
                "/usr/share/dpkg/** r,",
                "/etc/ssl/certs/** r,",
                "/sys/fs/cgroup/** r,",
                "@{PROC}/@{pid}/{cmdline,mountinfo} r,",
                "@{PROC}/@{pid}/task/** r,",
            ))
        profile = labels[role]
        rendered[role] = ("#include <tunables/global>\n"
                          f"profile {profile} flags=(mediate_deleted) {{\n"
                          + "\n".join(rules) + "\n}\n")
    return rendered


class _Arg(ctypes.Structure):
    _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_int),
                ("datum_a", ctypes.c_uint64), ("datum_b", ctypes.c_uint64)]


def install_worker_filter(role):
    """Deny descriptor export and new processes after the final role transition."""
    require(role in ("broker", "verifier", "sequencer"), "NATIVE_S1_FILTER_ROLE")
    lib = ctypes.CDLL("libseccomp.so.2")
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                         ctypes.c_uint, ctypes.POINTER(_Arg)]
    context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    require(context, "NATIVE_S1_FILTER_INIT")

    def reject(name, error=errno.EPERM, compare=None):
        number = lib.seccomp_syscall_resolve_name(name.encode("ascii"))
        require(number >= 0 and lib.seccomp_rule_add_array(
            context, 0x00050000 | error, number, int(compare is not None),
            ctypes.byref(compare) if compare is not None else None) == 0, "NATIVE_S1_FILTER_RULE")

    try:
        for name in ("sendmsg", "sendmmsg", "execve", "execveat", "fork", "vfork",
                     "ptrace", "process_vm_readv", "process_vm_writev", "pidfd_getfd",
                     "setns", "unshare", "mount", "umount2", "pivot_root", "fsopen", "fsmount",
                     "fsconfig", "move_mount", "mount_setattr", "open_tree",
                     "io_uring_setup", "io_uring_enter", "io_uring_register", "bpf"):
            reject(name)
        # Only the sequencer needs threads. Force glibc to use inspectable clone.
        reject("clone3", errno.ENOSYS)
        clone_thread = 0x00010000
        reject("clone", compare=_Arg(0, 7, clone_thread, 0) if role == "sequencer" else None)
        if role == "sequencer":
            for flag in (0x00020000, 0x02000000, 0x04000000, 0x08000000, 0x10000000,
                         0x20000000, 0x40000000):
                reject("clone", compare=_Arg(0, 7, flag, flag))  # SCMP_CMP_MASKED_EQ
        reject("socket", compare=_Arg(0, 1, socket.AF_UNIX, 0))  # SCMP_CMP_NE
        reject("socketpair", compare=_Arg(0, 1, socket.AF_UNIX, 0))
        reject("prctl", compare=_Arg(0, 4, 4, 0))  # SCMP_CMP_EQ: PR_SET_DUMPABLE
        require(lib.seccomp_load(context) == 0, "NATIVE_S1_FILTER_LOAD")
    finally:
        lib.seccomp_release(context)
