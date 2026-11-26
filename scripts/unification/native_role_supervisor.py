"""Launch one pinned Native qualification role on a preprovisioned disposable host.

The reviewed operator installs this exact file at INSTALL. Each external root
service supplies its preconfigured cgroup/AppArmor domain, role, and the digest
of its root-controlled manifest. Use /usr/bin/python3.12 -IBS. This command
does not install policy, provision identities, make a release decision or retry.
"""

import sys

if __name__ == '__main__' and not (sys.flags.isolated and sys.flags.no_site):
    raise SystemExit('use the installed supervisor with /usr/bin/python3.12 -IBS')

import argparse
import ctypes
import fcntl
import hashlib
import json
import os
import platform
import re
import signal
import stat
import subprocess
from contextlib import ExitStack
from pathlib import Path

INSTALL = Path('/usr/local/libexec/aioa-native-role-supervisor.py')
PYTHON = Path('/usr/bin/python3.12')
CONFIG = Path('/etc/aioa-native-qualification')
CHECKOUT = Path('/opt/aioa/native-qualification')
SESSIONS = Path('/run/aioa-qualification')
ROLES = ('core', 'broker', 'verifier')
PROBE_MODULE = 'scripts.unification.noble_role_probe'

# Runs only as the assigned role in an isolated interpreter. No .pth files,
# inherited Python paths, user-site modules or privileged project imports.
_BOOTSTRAP = """
import ctypes, fcntl, os, runpy, sys
from pathlib import Path
libc = ctypes.CDLL(None)
if libc.prctl(4, 0, 0, 0, 0) != 0 or libc.prctl(3, 0, 0, 0, 0) != 0:
    raise SystemExit('ROLE_DUMPABLE')
checkout, module, uid, gid, label, group, fd, *args = sys.argv[1:]
uid, gid = int(uid), int(gid)
if os.getresuid() != (uid,)*3 or os.getresgid() != (gid,)*3 or os.getgroups():
    raise SystemExit('ROLE_IDENTITY')
s = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
if s['NoNewPrivs'].strip() != '1' or any(int(s[f],16) for f in ('CapEff','CapPrm','CapInh','CapAmb')):
    raise SystemExit('ROLE_PRIVILEGES')
if Path('/proc/self/attr/current').read_text().strip() != label or Path('/proc/self/cgroup').read_text().strip() != group:
    raise SystemExit('ROLE_DOMAIN')
if fd != '-':
    k = int(fd)
    os.set_inheritable(k, False)
    if fcntl.fcntl(k, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY:
        raise SystemExit('ROLE_FD')
sys.path[:0] = [checkout, '/usr/lib/python3/dist-packages']
sys.argv = [module, *args]
runpy.run_module(module, run_name='__main__', alter_sys=True)
"""


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def pin(value, digits):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % digits, value) is not None


def trusted(path, *, directory=False):
    """Only resolve under root-controlled directories. Reject links at each step."""
    require(path.is_absolute() and '..' not in path.parts, 'UNTRUSTED_PATH')
    for parent in reversed(path.parents):
        meta = parent.lstat()
        require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == 0
                and not meta.st_mode & 0o022, 'UNTRUSTED_PARENT')
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    require(kind(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o7022,
            'UNTRUSTED_OPERATOR_FILE')
    return info


def pinned_bytes(path, expected):
    require(pin(expected, 64), 'BAD_DIGEST')
    info = trusted(path)
    require(info.st_nlink == 1 and 0 < info.st_size <= 65536, 'BAD_CONTROL_FILE')
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, 'CONTROL_PIN_MISMATCH')
    return data


def installed_tree(checkout, *, owner=0):
    """Measure the complete installed source, including importable ignored files."""
    budget = [8192, 512 * 1024 * 1024]

    def object_id(kind, raw):
        return hashlib.sha1(kind + b' ' + str(len(raw)).encode() + b'\0' + raw).digest()

    def walk(directory, depth):
        require(depth <= 32, 'CHECKOUT_DEPTH')
        records = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if depth == 0 and entry.name == '.git':
                    continue
                budget[0] -= 1
                require(budget[0] >= 0 and entry.name != '.git', 'CHECKOUT_LIMIT')
                info = entry.stat(follow_symlinks=False)
                require(info.st_uid == owner and not info.st_mode & 0o7022, 'WRITABLE_CHECKOUT')
                name = os.fsencode(entry.name)
                if stat.S_ISDIR(info.st_mode):
                    key, mode, oid = name+b'/', b'40000', walk(entry.path, depth+1)
                else:
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                            and info.st_size <= 32 * 1024 * 1024, 'UNTRUSTED_CHECKOUT_MEMBER')
                    budget[1] -= info.st_size
                    require(budget[1] >= 0, 'CHECKOUT_LIMIT')
                    raw = Path(entry.path).read_bytes()
                    require(len(raw) == info.st_size, 'CHECKOUT_MOVED')
                    key, mode = name, b'100755' if info.st_mode & stat.S_IXUSR else b'100644'
                    oid = object_id(b'blob', raw)
                records.append((key, mode + b' ' + name + b'\0' + oid))
        return object_id(b'tree', b''.join(item for _, item in sorted(records)))

    return walk(checkout, 0).hex()


def distinct_ids(mapping):
    require(type(mapping) is dict and set(mapping) == set(ROLES)
            and all(type(value) is int and 0 < value < 2**31 for value in mapping.values())
            and len(set(mapping.values())) == len(ROLES), 'DISTINCT_NONROOT_ROLES')


def role_config(manifest, role):
    require(role in ROLES and manifest['schema'] == 'aioa.noble-operator-pins.v1', 'ROLE_MANIFEST')
    native, host = manifest['native'], manifest['host']
    require(pin(host['source'], 40) and pin(host['tree'], 40) and pin(native['session'], 32),
            'SOURCE_OR_SESSION_PIN')
    distinct_ids(native['uids'])
    distinct_ids(native['gids'])
    domains = native['domains']
    require(set(domains) == set(ROLES), 'ROLE_DOMAINS')
    for value in domains.values():
        require(set(value) == {'cgroup','apparmor'}
                and re.fullmatch(r'0::/(?:[A-Za-z0-9_.@:-]+/)*[A-Za-z0-9_.@:-]+', value['cgroup'])
                and re.fullmatch(r'[A-Za-z0-9_./:-]+ \(enforce\)', value['apparmor'])
                and value['apparmor'] != 'unconfined (enforce)', 'ROLE_DOMAIN_PIN')
    require(len({d['cgroup'] for d in domains.values()}) == len(ROLES)
            and len({d['apparmor'] for d in domains.values()}) == len(ROLES), 'DISTINCT_ROLE_DOMAINS')
    return native, host, domains[role]


def broker_fd(session, native):
    key_dir = session/'broker'
    require(stat.S_IMODE(trusted(key_dir, directory=True).st_mode) == 0o700, 'BROKER_KEY_PARENT')
    fd = os.open(key_dir/'test-signing-key', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        require(all(type(native[name]) is int and native[name] > 0 for name in ('signer_dev','signer_ino'))
                and (info.st_dev, info.st_ino) == (native['signer_dev'], native['signer_ino'])
                and stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_uid == native['uids']['broker'] and 0 < info.st_size <= 4096
                and stat.S_IMODE(info.st_mode) == 0o400, 'BROKER_SIGNER_CUSTODY')
        return fd
    except BaseException:
        os.close(fd)
        raise


def mark(session, role, kind='probe'):
    # Only the root supervisor can create this marker in the test session.
    # Uncertain startup consumes the launch and preserves the evidence.
    directory = os.open(session, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(f'started-{kind}-{role}', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory)
    finally:
        os.close(directory)


def no_new_privileges():
    # The supervisor is a single-threaded standalone executable. CPython drops
    # supplementary groups, GID and UID before this pre-exec child callback.
    if ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) != 0:
        os._exit(126)


def run(role, digest):
    require(os.getresuid() == (0,)*3 and Path(__file__).absolute() == INSTALL
            and Path(sys.executable) == PYTHON and sys.flags.isolated and sys.flags.no_site,
            'INSTALLED_OPERATOR_SUPERVISOR_ONLY')
    manifest_path = CONFIG/'manifest.json'
    receipt = CONFIG/'management-receipt.json'
    manifest = json.loads(pinned_bytes(manifest_path, digest))
    native, host, domain = role_config(manifest, role)
    require(pin(native['supervisor_sha256'], 64), 'SUPERVISOR_DIGEST_REQUIRED')
    pinned_bytes(INSTALL, native['supervisor_sha256'])
    management = json.loads(pinned_bytes(receipt, host['management_receipt_sha256']))
    boot = hashlib.sha256(Path('/proc/sys/kernel/random/boot_id').read_bytes().strip()).hexdigest()
    release = platform.freedesktop_os_release()
    require(release.get('ID') == 'ubuntu' and release.get('VERSION_ID') == '24.04'
            and release.get('VERSION_CODENAME') == 'noble' and platform.machine() == 'x86_64'
            and platform.release() == host['kernel'] and host['boot_sha256'] == boot,
            'PINNED_NOBLE_HOST_REQUIRED')
    require(pin(host['image_sha256'], 64) and pin(host['signed_package_manifest_sha256'], 64)
            and management == {'schema':'aioa.disposable-host-receipt.v1', 'disposable':True,
                               'image_sha256':host['image_sha256'], 'boot_sha256':boot,
                               'signed_package_manifest_sha256':host['signed_package_manifest_sha256']},
            'DISPOSABLE_HOST_REQUIRED')
    require(Path('/proc/self/attr/current').read_text().strip() == domain['apparmor']
            and Path('/proc/self/cgroup').read_text().strip() == domain['cgroup'],
            'START_FROM_PINNED_ROLE_UNIT')
    checkout = CHECKOUT/host['source']
    trusted(checkout, directory=True)
    trusted(checkout/'.git', directory=True)
    trusted(checkout/'.git/config')
    require(installed_tree(checkout) == host['tree'], 'INSTALLED_SOURCE_TREE_MISMATCH')
    pinned_bytes(checkout/'scripts/unification/noble_role_probe.py', native['role_probe_sha256'])
    pinned_bytes(checkout/'scripts/unification/noble_preflight.py', native['preflight_sha256'])
    trusted(PYTHON)
    require('security.capability' not in os.listxattr(PYTHON), 'INTERPRETER_CAPABILITIES')
    session = SESSIONS/native['session']
    trusted(session, directory=True)
    uid, gid = native['uids'][role], native['gids'][role]
    env = {'PATH':'/usr/bin:/bin', 'HOME':'/nonexistent', 'LANG':'C',
           'XDG_RUNTIME_DIR':f'/run/user/{uid}', 'GIT_CONFIG_NOSYSTEM':'1',
           'GIT_CONFIG_GLOBAL':'/dev/null', 'GIT_CONFIG_COUNT':'3', 'GIT_CONFIG_KEY_0':'safe.directory',
           'GIT_CONFIG_VALUE_0':str(checkout), 'GIT_CONFIG_KEY_1':'core.fsmonitor',
           'GIT_CONFIG_VALUE_1':'false', 'GIT_CONFIG_KEY_2':'core.hooksPath',
           'GIT_CONFIG_VALUE_2':'/dev/null', 'GIT_OPTIONAL_LOCKS':'0', 'GIT_ALLOW_PROTOCOL':'',
           'GIT_NO_LAZY_FETCH':'1'}
    with ExitStack() as stack:
        descriptors = ()
        args = ['--role', role, '--manifest', str(manifest_path), '--manifest-sha256', digest,
                '--management-receipt', str(receipt)]
        if role == 'broker':
            fd = broker_fd(session, native)
            stack.callback(os.close, fd)
            descriptors = (fd,)
            args += ['--signer-fd', str(fd)]
        mark(session, role)
        argv = [str(PYTHON), '-IBS', '-c', _BOOTSTRAP, str(checkout), PROBE_MODULE, str(uid), str(gid),
                domain['apparmor'], domain['cgroup'], str(descriptors[0]) if descriptors else '-', *args]
        # Output goes to the external operator unit's evidence stream.
        with subprocess.Popen(argv, cwd=checkout, env=env, user=uid, group=gid, extra_groups=(),
                              umask=0o077, stdin=subprocess.DEVNULL, pass_fds=descriptors,
                              close_fds=True, start_new_session=True, preexec_fn=no_new_privileges) as child:
            try:
                return child.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                raise ValueError('ROLE_TIMEOUT') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', required=True, choices=ROLES)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    return run(args.role, args.manifest_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
