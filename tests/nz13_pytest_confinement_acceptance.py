"""Adversarial real domain probes, using only the existing Core/kernel flow.

Candidate code below is inert on the host. Expected permission errors are the
only denials accepted; ENOENT, unsupported primitives and fake PASS are errors.
Independent coding review must deny this diagnostic patch, so Git stays put.
"""
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import nz11_kernel_acceptance as kernel
from nz13_pytest_acceptance import load_public_lock
from nz13_worker_acceptance import WireFixtureWorker

from runtime.mission.project_recipe import PytestSuite, PythonFunctionCase
from runtime.mission.repair import TEST_STAGES
from runtime.mission.worker import CandidateFile, CandidatePatch

PROBES = (
    ('test-views', ['DENIED', 'DENIED']),
    ('scratch-others', ['DENIED', 'DENIED']),
    ('host-views', ['DENIED', 'DENIED', 'DENIED']),
    ('no-writes', ['DENIED', 'DENIED', 'DENIED']),
    ('no-sockets', ['DENIED', 'DENIED']),
    ('no-signal', 'DENIED'),
    ('private-scratch', 'ALLOWED'),
    ('public-package', '26.3'),
)

ORACLE_GROUPS = (
    ('filesystem-denials', ('test-views', 'scratch-others', 'host-views', 'no-writes')),
    ('process-denials', ('no-sockets', 'no-signal')),
    ('allowed-controls', ('private-scratch', 'public-package')),
)

SOURCE = '''import ctypes
import errno
import os
import signal
import packaging

def denied(action):
    try:
        action()
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EPERM):
            return "DENIED"
        return "INCONCLUSIVE_ERRNO_" + str(error.errno)
    return "UNEXPECTEDLY_ALLOWED"

def open_close(path, flags):
    fd = os.open(path, flags, 0o600)
    os.close(fd)

def socket_probe(family):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.socket.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    libc.socket.restype = ctypes.c_int
    fd = libc.socket(family, 1, 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "fixed confined socket probe")
    os.close(fd)

def slug(probe):
    if probe == "framework-control":
        return "framework-control"
    if probe == "test-views":
        paths = ("/work/project/tests/test_domains.py", "/work/tests/tests/test_domains.py")
        return [denied(lambda path=path: open_close(path, os.O_RDONLY)) for path in paths]
    if probe == "scratch-others":
        paths = ("/tmp/pytest-framework", "/tmp/oracle-1")
        return [denied(lambda path=path: open_close(path, os.O_RDONLY)) for path in paths]
    if probe == "host-views":
        paths = ("/inputs/context.json", "/proc/self/status", "/proc/" + str(os.getppid()) + "/fd/1")
        return [denied(lambda path=path: open_close(path, os.O_RDONLY)) for path in paths]
    if probe == "no-writes":
        paths = ("/work/oracle-project/src/textutil.py", "/work/dependencies/packaging/__init__.py")
        return [denied(lambda path=path: open_close(path, os.O_WRONLY)) for path in paths] + [
            denied(lambda: open_close("/artifacts/forbidden.txt", os.O_CREAT | os.O_WRONLY))]
    if probe == "no-sockets":
        return [denied(lambda family=family: socket_probe(family)) for family in (2, 1)]
    if probe == "no-signal":
        return denied(lambda: os.kill(os.getppid(), signal.SIGCONT))
    if probe == "private-scratch":
        path = "/tmp/oracle-2/fresh-private.txt"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        try:
            os.write(fd, b"bounded fixture")
            os.lseek(fd, 0, os.SEEK_SET)
            value = os.read(fd, 32)
        finally:
            os.close(fd)
            os.unlink(path)
        return "ALLOWED" if value == b"bounded fixture" else "WRONG"
    if probe == "public-package":
        return packaging.__version__
    return "UNKNOWN_PROBE"

def group(probes):
    return [slug(probe) for probe in probes]
'''

TEST_TEXT = '''import errno
import os
import pytest
from textutil import slug

def test_framework_domain():
    assert slug("framework-control") == "framework-control"
    for path in ("/work/oracle-project/src/textutil.py", "/tmp/oracle-0"):
        with pytest.raises(OSError) as caught:
            fd = os.open(path, os.O_RDONLY)
            os.close(fd)
        assert caught.value.errno in (errno.EACCES, errno.EPERM)
    path = "/tmp/pytest-framework/fresh-framework.txt"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    try:
        os.write(fd, b"framework-only")
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, 32) == b"framework-only"
    finally:
        os.close(fd)
        os.unlink(path)
'''


def main(manifest, wheel_directory, output):
    assert not any(name in sys.modules for name in ('pytest', '_pytest', 'packaging'))
    lock = load_public_lock(wheel_directory)
    node = 'tests/test_domains.py::test_framework_domain'
    suite = PytestSuite((('tests/test_domains.py', TEST_TEXT),),
                        tuple((stage, (node,)) for stage in TEST_STAGES))
    workers = []

    def profile_factory(profile):
        cases = tuple(PythonFunctionCase(group, 'textutil', 'group',
            json.dumps([list(names)], separators=(',', ':')).encode(),
            json.dumps([dict(PROBES)[name] for name in names], separators=(',', ':')).encode())
            for group, names in ORACLE_GROUPS)
        return replace(profile, execution_profile='ISOLATED_PYTEST_FUNCTIONS_V1', wheel_lock=lock,
            pytest_suite=suite, oracle_paths=('src/domain_probe.py', 'src/extra.py', 'src/textutil.py'),
            stages=tuple((stage, cases) for stage in TEST_STAGES))

    def candidates(original):
        # The unchanged source fixture owns the adversarial implementation.
        # Keep the normal PatchSet anti-test-mutation policy in full force.
        wrapper = 'from domain_probe import group\n\ndef slug(text):\n    return "framework-control"\n'
        return original[0], CandidatePatch((CandidateFile('src/textutil.py', wrapper),
            *tuple(item for item in original[1].files if item.path != 'src/textutil.py')))

    def worker_factory(values, *, clock):
        worker = WireFixtureWorker(values, clock=clock)
        workers.append(worker)
        return worker

    source_files = {'README.md': b'# Domain fixture\n',
        'src/domain_probe.py': SOURCE.encode(),
        'src/textutil.py': b'def slug(text):\n    return text.strip()\n',
        'tests/test_domains.py': TEST_TEXT.encode()}
    denial = kernel.main(manifest, output, worker_factory=worker_factory,
        profile_factory=profile_factory, candidate_transform=candidates, source_files=source_files,
        expected_review_denial='REVIEW_FIXTURE_BYPASS')
    assert denial['status'] == 'EXPECTED_REVIEW_DENIAL' and denial['target_refs_unchanged'] is True
    assert denial['git_actuation'] is False and len(workers) == 1 and workers[0].messages == 2
    assert not any(name in sys.modules for name in ('pytest', '_pytest', 'packaging'))
    proof = {'schema': 'aioa.nz13.pytest-domains-acceptance.v1',
        'status': 'PASS_REAL_DOMAIN_PROBES_WITH_EXPECTED_CODING_REVIEW_DENIAL',
        'source_sha256': hashlib.sha256(SOURCE.encode()).hexdigest(),
        'probe_fixture_path': 'src/domain_probe.py', 'probe_fixture_unchanged': True,
        'direct_probe_patch': 'PATCHSET_TEST_WEAKENING_DENIED_PRESERVED',
        'probes': [{'id': name, 'expected': expected} for name, expected in PROBES],
        'oracle_denials_per_stage': 13, 'oracle_allowed_controls_per_stage': 2,
        'oracle_calls_per_stage': 3, 'oracle_groups': [[name, list(probes)] for name, probes in ORACLE_GROUPS],
        'framework_denials_per_stage': 2, 'framework_private_control_per_stage': 1,
        'stages': list(TEST_STAGES), 'missing_path_is_not_a_denial_proof': True,
        'same_core_broker': True, 'coding_review_guard': 'PRESERVED_DENIAL',
        'coding_git_actuation': False, 'host_framework_imported': False,
        'model_calls': 0, 'remote_calls': 0, 'production_changes': 0, 'full_qualification': False}
    with (output / 'NZ13_PYTEST_DOMAINS_ACCEPTANCE.json').open('x') as stream:
        json.dump(proof, stream, indent=2)
    print(json.dumps(proof), flush=True)


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
