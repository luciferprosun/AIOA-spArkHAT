"""Probe a provisioned disposable Native policy domain under its actual UID.

Each role must run this from its real supervisor service and confinement. The
only write probes are exclusive empty sentinel creations in the reserved
disposable namespace. An unexpected success leaves the sentinel as evidence.
"""
import argparse
import ctypes
import fcntl
import errno
import json
import os
import re
import stat
from pathlib import Path

from scripts.unification.noble_preflight import compare_manifest, host_gaps, observe, pinned_json, require


ROOT = Path('/run/aioa-qualification')
ROLES = ('core', 'broker', 'verifier')


def try_open(root, relative, flags, directory_pins=None):
    directory = os.open(root, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        prefix = Path()
        reached_parent = False
        for component in relative.parts[:-1]:
            prefix /= component
            child = os.open(component, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
            if directory_pins and prefix in directory_pins:
                info = os.fstat(directory)
                require((info.st_dev, info.st_ino) == directory_pins[prefix],
                        'NATIVE_PINNED_DIRECTORY_REQUIRED')
        reached_parent = True
        fd = os.open(relative.name, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                     0o600, dir_fd=directory)
    except OSError as exc:
        if directory_pins and not reached_parent:
            raise
        if exc.errno in (errno.EPERM, errno.EACCES):
            return 'DENIED'
        raise
    finally:
        os.close(directory)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), 'PROBE_REQUIRES_REGULAR_FILE')
        return 'OPENED'
    finally:
        os.close(fd)


def probe_paths(root, native, role):
    match = re.fullmatch(r'refs/heads/aioa/(nz11-([a-f0-9]{32}))', native['exact_ref'])
    require(match is not None, 'NATIVE_PLAN_REF_REQUIRED')
    leaf, suffix = match.groups()

    # These distinct names obey the identical Native ref grammar. A probe
    # outside this ref parent would measure a different filesystem policy.
    def sibling(delta):
        return 'nz11-' + format(int(suffix, 16) ^ delta, '032x')

    parent = root / 'repo' / 'refs' / 'heads' / 'aioa'
    create = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    probes = {
        'signer_read': (root / 'broker' / 'test-signing-key', os.O_RDONLY, 'DENIED'),
        'signer_write': (root / 'broker' / 'test-signing-key', os.O_WRONLY, 'DENIED'),
        'sibling_write': (parent / sibling(1), os.O_WRONLY, 'DENIED'),
        'sibling_create': (parent / sibling(2 + ROLES.index(role)), create, 'DENIED'),
        'foreign_write': (root / 'foreign' / 'existing', os.O_WRONLY, 'DENIED'),
        'foreign_create': (root / 'foreign' / ('probe-' + role), create, 'DENIED'),
    }
    if role != 'broker':
        probes['exact_create'] = (parent / leaf, create, 'DENIED')
        probes['exact_lock_create'] = (parent / (leaf + '.lock'), create, 'DENIED')
    return probes


def check_role(root, role, native):
    probes = probe_paths(root, native, role)
    pins = {
        Path('repo'): (native['repository_dev'], native['repository_ino']),
        Path('repo/refs/heads/aioa'): (native['ref_directory_dev'], native['ref_directory_ino']),
    }
    rows = {}
    for name, (path, mode, expected) in probes.items():
        try:
            relative = path.relative_to(root)
            observed = try_open(root, relative, mode, pins if relative.parts[0] == 'repo' else None)
            rows[name] = {'observed': observed, 'expected': expected}
        except OSError as exc:
            rows[name] = {'observed': 'ERROR_' + errno.errorcode.get(exc.errno, 'UNKNOWN'), 'expected': expected}
        if rows[name]['observed'] != expected:
            break
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=ROLES, required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--management-receipt', required=True)
    parser.add_argument('--signer-fd', type=int)
    args = parser.parse_args()
    require((args.signer_fd is not None) == (args.role == 'broker'), 'SIGNER_FD_SCOPE')
    if args.signer_fd is not None:
        require(args.signer_fd >= 3, 'BAD_SIGNER_FD')
        os.set_inheritable(args.signer_fd, False)
    libc = ctypes.CDLL(None, use_errno=True)
    require(libc.prctl(4, 0, 0, 0, 0) == 0, 'NON_DUMPABLE_REQUIRED')  # PR_SET_DUMPABLE
    obs = observe()
    require(not host_gaps(obs, system_service=True), 'BLOCKED_HOST')
    manifest = pinned_json(args.manifest, args.manifest_sha256)
    compare_manifest(manifest, obs, args.management_receipt)
    native = manifest['native']
    require(re.fullmatch(r'[a-f0-9]{32}', native['session']), 'BAD_EPHEMERAL_SESSION')
    roles = native['uids']
    require(set(roles) == set(ROLES) and all(type(uid) is int and uid > 0 for uid in roles.values())
            and len(set(roles.values())) == len(ROLES) and os.getuid() == os.geteuid() == roles[args.role],
            'ROLE_UID_MISMATCH')
    gids = native['gids']
    require(set(gids) == set(ROLES) and all(type(gid) is int and gid > 0 for gid in gids.values())
            and len(set(gids.values())) == len(ROLES) and os.getgid() == os.getegid() == gids[args.role],
            'ROLE_GID_MISMATCH')
    signer_fd_matched = False
    if args.signer_fd is not None:
        info = os.fstat(args.signer_fd)
        require(stat.S_ISREG(info.st_mode) and info.st_mode & 0o777 == 0o400 and info.st_nlink == 1
                and info.st_uid == os.getuid() and info.st_dev == native['signer_dev']
                and info.st_ino == native['signer_ino'] and info.st_size > 0
                and fcntl.fcntl(args.signer_fd, fcntl.F_GETFL) & (os.O_ACCMODE | os.O_PATH) == os.O_RDONLY,
                'SIGNER_FD_IDENTITY')
        os.close(args.signer_fd)
        signer_fd_matched = True
    root = ROOT / native['session']
    for path in (ROOT, root):
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                'SUPERVISOR_ROOT_REQUIRED')
    cgroup = Path('/proc/self/cgroup').read_text().strip()
    label = Path('/proc/self/attr/current').read_text().strip()
    expected = native['domains'][args.role]
    require(cgroup.startswith('0::/') and cgroup == expected['cgroup']
            and label == expected['apparmor'] and label.endswith(' (enforce)'), 'DOMAIN_MISMATCH')
    rows = check_role(root, args.role, native)
    ok = all(row['observed'] == row['expected'] for row in rows.values())
    print(json.dumps({'result': 'ACCESS_PROBES_MATCHED' if ok else 'FAIL', 'role': args.role,
                      'uid': os.getuid(), 'boot_sha256': obs['boot_sha256'],
                      'session': native['session'], 'exact_ref': native['exact_ref'], 'cgroup': cgroup, 'profile': label, 'probes': rows,
                      'signer_fd_matched': signer_fd_matched, 'cas_attempts': 0, 'settlements': 0}, sort_keys=True))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
