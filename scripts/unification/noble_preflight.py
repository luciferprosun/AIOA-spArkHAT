"""Read-only Noble host checks for a disposable operator-run qualification.

An external image receipt must be matched by the operator at the hypervisor.
A guest cannot attest its own image. This program never grants execution.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2]
SHA256 = re.compile(r'[0-9a-f]{64}')
SHA1 = re.compile(r'[0-9a-f]{40}')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pinned_json(path, expected, maximum=65536):
    require(isinstance(expected, str) and SHA256.fullmatch(expected), 'INVALID_DOCUMENT_PIN')
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum and digest(raw) == expected, 'DOCUMENT_PIN_MISMATCH')
    return json.loads(raw)


def command(*args):
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'GIT_OPTIONAL_LOCKS': '0',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'XDG_RUNTIME_DIR': '/run/user/%d' % os.getuid()}
    return subprocess.run(args, cwd=SOURCE, env=env, timeout=8, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
                          text=True).stdout.strip()


def observe():
    osinfo = platform.freedesktop_os_release()
    manager = 'unavailable'
    delegation = ''
    try:
        manager = command('/usr/bin/systemctl', '--user', 'is-active', 'default.target')
        delegation = command('/usr/bin/systemctl', 'show', 'user@%d.service' % os.getuid(),
                             '--property=Delegate', '--value')
    except (OSError, subprocess.SubprocessError):
        pass
    aa = Path('/sys/module/apparmor/parameters/enabled')
    restrict = Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns')
    cg = Path('/sys/fs/cgroup/cgroup.controllers')
    caps = re.search(r'^CapEff:\s*(\w+)$', Path('/proc/self/status').read_text(), re.M)
    return {
        'os': osinfo['ID'], 'release': osinfo['VERSION_ID'], 'codename': osinfo.get('VERSION_CODENAME'),
        'architecture': platform.machine(), 'kernel': platform.release(),
        'boot_sha256': digest(Path('/proc/sys/kernel/random/boot_id').read_bytes().strip()),
        'uid': os.getuid(), 'pid1': Path('/proc/1/comm').read_text().strip(),
        'effective_caps': int(caps[1], 16), 'user_manager': manager, 'delegate': delegation,
        'controllers': sorted(cg.read_text().split()) if cg.is_file() else [],
        'apparmor': aa.is_file() and aa.read_text().strip() == 'Y',
        'restricted_userns': restrict.is_file() and restrict.read_text().strip() == '1',
        'source': command('/usr/bin/git', '-c', 'safe.directory=' + str(SOURCE), 'rev-parse', 'HEAD'),
        'tree': command('/usr/bin/git', '-c', 'safe.directory=' + str(SOURCE), 'rev-parse', 'HEAD^{tree}'),
        'source_clean': not command('/usr/bin/git', '-c', 'safe.directory=' + str(SOURCE), 'status', '--porcelain', '--untracked-files=all'),
    }


def host_gaps(obs, *, system_service=False):
    requirements = {
        'UBUNTU_24_04_NOBLE': (obs['os'], obs['release'], obs['codename']) == ('ubuntu', '24.04', 'noble'),
        'X86_64': obs['architecture'] == 'x86_64',
        'SYSTEMD_PID1': obs['pid1'] == 'systemd',
        'SYSTEMD_USER': obs['user_manager'] == 'active',
        'CGROUP_DELEGATION': obs['delegate'] == 'yes' and {'cpu', 'memory', 'pids'} <= set(obs['controllers']),
        'UNPRIVILEGED_ROLE': obs['uid'] != 0 and obs['effective_caps'] == 0,
        'APPARMOR': obs['apparmor'] and obs['restricted_userns'],
        'CLEAN_SOURCE': obs['source_clean'],
    }
    if system_service:
        # The operator's interactive preflight covers the delegated user manager.
        # The system service is measured in its own pinned cgroup by its role probe.
        del requirements['SYSTEMD_USER']
        requirements['CGROUP_DELEGATION'] = {'cpu', 'memory', 'pids'} <= set(obs['controllers'])
    return [name for name, matched in requirements.items() if not matched]


def compare_manifest(manifest, obs, external_receipt):
    require(manifest['schema'] == 'aioa.noble-operator-pins.v1', 'MANIFEST_SCHEMA')
    host = manifest['host']
    for field, pattern in (('source', SHA1), ('tree', SHA1), ('boot_sha256', SHA256)):
        require(isinstance(host.get(field), str) and pattern.fullmatch(host[field])
                and host[field] == obs[field], 'PIN_' + field.upper())
    require(isinstance(host.get('kernel'), str) and host['kernel'] == obs['kernel'], 'PIN_KERNEL')
    require(bool(SHA256.fullmatch(host['image_sha256'])), 'PIN_IMAGE')
    # The receipt comes from the operator's independently authenticated management plane.
    receipt = pinned_json(external_receipt, host['management_receipt_sha256'])
    require(bool(SHA256.fullmatch(host['signed_package_manifest_sha256'])), 'PIN_PACKAGE_PROVENANCE')
    require(receipt == {'schema': 'aioa.disposable-host-receipt.v1', 'disposable': True,
                        'image_sha256': host['image_sha256'], 'boot_sha256': host['boot_sha256'],
                        'signed_package_manifest_sha256': host['signed_package_manifest_sha256']},
            'MANAGEMENT_PLANE_BINDING')
    from runtime.mission.git_publish import LOCAL_GIT_SHA256
    from runtime.mission.sandbox_linux import GIT_RUNTIME_PINS
    for name, pin in {'/usr/bin/git': LOCAL_GIT_SHA256, **GIT_RUNTIME_PINS}.items():
        path = Path(name).resolve(strict=True)
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            meta = os.fstat(fd)
            require(stat.S_ISREG(meta.st_mode) and meta.st_uid == 0 and not meta.st_mode & 0o022
                    and 0 < meta.st_size <= 32 * 1024 * 1024, 'HOST_RUNTIME_FILE')
            require(digest(stream.read(meta.st_size + 1)) == pin, 'HOST_RUNTIME_PIN_' + path.name)
    packages = {
        'bubblewrap': '0.9.0-1ubuntu0.3', 'python3-cryptography': '41.0.7-4ubuntu0.4',
        'git': '1:2.43.0-1ubuntu7.4', 'git-man': '1:2.43.0-1ubuntu7.4',
        'util-linux': '2.39.3-9ubuntu6.6', 'zlib1g': '1:1.3.dfsg-3.1ubuntu2.3',
        'libc6': '2.39-0ubuntu8.9', 'libpcre2-8-0': '10.42-4ubuntu2.1',
    }
    for package, pin in packages.items():
        value = command('/usr/bin/dpkg-query', '--show', '--showformat=${db:Status-Status} ${Version}', package)
        require(value == 'installed ' + pin, 'NOBLE_PACKAGE_' + package)
    return host


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--management-receipt', type=Path)
    args = parser.parse_args()
    observed = observe()
    gaps = host_gaps(observed)
    if not (args.manifest and args.manifest_sha256 and args.management_receipt):
        gaps.append('EXTERNAL_OPERATOR_PINS_AND_MANAGEMENT_RECEIPT')
    if not gaps:
        try:
            compare_manifest(pinned_json(args.manifest, args.manifest_sha256), observed,
                             args.management_receipt)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            gaps.append(str(exc) if type(exc) is ValueError else type(exc).__name__)
    print(json.dumps({'result': 'BLOCKED_HOST' if gaps else 'HOST_PINS_MATCHED',
                      'observed': observed, 'missing': gaps, 'live_sessions': 0}, sort_keys=True))
    return 2 if gaps else 0


if __name__ == '__main__':
    sys.exit(main())
