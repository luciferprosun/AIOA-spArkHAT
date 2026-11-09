"""Prepared real confinement matrix using the one existing Core/kernel flow.

Do not run while another qualification owns the broker. This fixed fixture is
not model inference: source bytes and host oracles are operator controlled.
Each OS probe reports success only for the expected permission error; missing
paths and unsupported primitives cannot silently count as a denial proof.
"""

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import nz11_kernel_acceptance as kernel
from nz13_worker_acceptance import WireFixtureWorker
from test_nz13_locked_wheels import FILENAME, wheel_bytes

from runtime.mission.dependency_lock import LockedWheel, PythonWheelLock
from runtime.mission.project_recipe import PythonFunctionCase
from runtime.mission.worker import CandidateFile, CandidatePatch

PROBES = (
    ('parent-proc-fd', 'DENIED'),
    ('own-proc-status', 'DENIED'),
    ('read-input-oracle-context', 'DENIED'),
    ('write-parent-artifacts', 'DENIED'),
    ('write-source', 'DENIED'),
    ('write-installed-package', 'DENIED'),
    ('hardlink-source-into-tmp', 'DENIED'),
    ('symlink-in-tmp', 'DENIED'),
    ('inet-socket', 'DENIED'),
    ('unix-socket', 'DENIED'),
    ('signal-parent', 'DENIED'),
    ('private-tmp-roundtrip', 'ALLOWED'),
    ('locked-package-import', 7),
)

# This exact source is a trusted adversarial test fixture. It is never imported
# by the host. SIGCONT is a real signal with no stop/kill effect on the parent.
SOURCE = '''import errno
import os
import signal
import ctypes
import fixture_math

def fixed_socket_probe(family):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.socket.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    libc.socket.restype = ctypes.c_int
    fd = libc.socket(family, 1, 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "fixed confined socket probe")
    os.close(fd)

def slug(probe):
    try:
        if probe == "parent-proc-fd":
            fd = os.open("/proc/" + str(os.getppid()) + "/fd/1", os.O_WRONLY)
            os.close(fd)
        elif probe == "own-proc-status":
            fd = os.open("/proc/self/status", os.O_RDONLY)
            os.close(fd)
        elif probe == "read-input-oracle-context":
            fd = os.open("/inputs/context.json", os.O_RDONLY)
            os.close(fd)
        elif probe == "write-parent-artifacts":
            fd = os.open("/artifacts/child-must-not-write.txt", os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
        elif probe == "write-source":
            fd = os.open("/work/project/src/textutil.py", os.O_WRONLY)
            os.close(fd)
        elif probe == "write-installed-package":
            fd = os.open("/work/dependencies/fixture_math/__init__.py", os.O_WRONLY)
            os.close(fd)
        elif probe == "hardlink-source-into-tmp":
            os.link("/work/project/src/textutil.py", "/tmp/denied-source-link")
        elif probe == "symlink-in-tmp":
            os.symlink("/work/project/src/textutil.py", "/tmp/denied-source-symlink")
        elif probe == "inet-socket":
            fixed_socket_probe(2)
        elif probe == "unix-socket":
            fixed_socket_probe(1)
        elif probe == "signal-parent":
            os.kill(os.getppid(), signal.SIGCONT)
        elif probe == "private-tmp-roundtrip":
            fd = os.open("/tmp/allowed-child-only.txt", os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            try:
                os.write(fd, b"bounded fixture")
                os.lseek(fd, 0, os.SEEK_SET)
                actual = os.read(fd, 32)
            finally:
                os.close(fd)
                os.unlink("/tmp/allowed-child-only.txt")
            return "ALLOWED" if actual == b"bounded fixture" else "WRONG"
        elif probe == "locked-package-import":
            return fixture_math.identity(7)
        else:
            return "UNKNOWN_PROBE"
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EPERM, errno.EXDEV):
            return "DENIED"
        return "INCONCLUSIVE_ERRNO_" + str(error.errno)
    return "UNEXPECTEDLY_ALLOWED"
'''


def main(manifest_path, output):
    assert 'fixture_math' not in sys.modules, 'HOST_PACKAGE_EXECUTION_FORBIDDEN'
    raw = wheel_bytes(package=b'def identity(value):\n    return value\n')
    lock = PythonWheelLock((LockedWheel(
        'fixture-math', '1.0.0', FILENAME, hashlib.sha256(raw).hexdigest(), raw,
    ),))
    profiles = []
    stage_names = []
    workers = []

    def profile_factory(profile):
        cases = tuple(PythonFunctionCase(
            name, 'textutil', 'slug', json.dumps([name], separators=(',', ':')).encode(),
            json.dumps(expected, separators=(',', ':')).encode(),
        ) for name, expected in PROBES)
        value = replace(
            profile, execution_profile='ISOLATED_PYTHON_FUNCTIONS_V1',
            wheel_lock=lock,
            stages=tuple((stage, cases) for stage, _ in profile.stages),
        )
        profiles.append(value.digest)
        stage_names.append([stage for stage, _ in value.stages])
        return value

    def candidates(original):
        repaired = CandidatePatch((
            CandidateFile('src/textutil.py', SOURCE),
            *tuple(item for item in original[1].files if item.path != 'src/textutil.py'),
        ))
        return original[0], repaired

    def worker_factory(values, *, clock):
        worker = WireFixtureWorker(values, clock=clock)
        workers.append(worker)
        return worker

    kernel.main(manifest_path, output, worker_factory=worker_factory,
                profile_factory=profile_factory, candidate_transform=candidates)
    assert len(profiles) == len(workers) == 1 and workers[0].messages == 2
    assert 'fixture_math' not in sys.modules, 'HOST_PACKAGE_EXECUTION_FORBIDDEN'
    proof = {
        'schema': 'aioa.nz13.function-confinement-acceptance.v1',
        'status': 'PASS_REAL_CORE_BROKER_FIXED_ADVERSARIAL_FIXTURE_ONLY',
        'profile_digest': profiles[0], 'fixture_source_sha256':
            hashlib.sha256(SOURCE.encode()).hexdigest(),
        'probes_per_stage': len(PROBES), 'probes': [
            {'id': name, 'expected': value} for name, value in PROBES
        ], 'stages': stage_names[0],
        'combined_kernel_confinement': True, 'individual_LSM_attribution': False,
        'permission_errors_only': True, 'missing_path_is_not_a_denial_proof': True,
        'same_core_and_local_git_flow': True, 'host_package_imported': False,
        'model_calls': 0, 'remote_calls': 0, 'production_changes': 0,
        'unrun_separate_cases': [
            'real old-Landlock-ABI host', 'crash/timeout/flood protocol negatives',
            'real model WorkerPort turn',
        ],
    }
    with (output / 'NZ13_FUNCTION_CONFINEMENT_ACCEPTANCE.json').open('x') as stream:
        json.dump(proof, stream, indent=2)
    print(json.dumps(proof), flush=True)


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
