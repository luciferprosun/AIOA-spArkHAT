"""Real pinned pytest repair through the existing Core, broker and local Git.

Explicit operator CLI only. Public wheels are inert bytes on the host. The
existing mandatory sandbox is the only place that executes their code.
"""
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import nz11_kernel_acceptance as kernel
from nz13_worker_acceptance import WireFixtureWorker

from runtime.mission.dependency_lock import (
    _FRAMEWORK_PINS,
    FrameworkWheel,
    PytestWheelLock,
)
from runtime.mission.project_recipe import PytestSuite, PythonFunctionCase
from runtime.mission.repair import TEST_STAGES
from runtime.mission.sandbox_linux import read_evidence_file

TEST_FILES = {
    'tests/conftest.py': 'from pathlib import Path\nimport pytest\n\n'
        '@pytest.fixture\ndef owner_words():\n'
        '    return (Path(__file__).parent / "fixtures" / "words.txt").read_text().strip()\n',
    'tests/fixtures/words.txt': 'owner fixture data\n',
    'tests/test_textutil.py': 'import pytest\nfrom textutil import slug\nfrom extra import title\n\n'
        '@pytest.mark.parametrize("text,expected", [("  One   TWO ", "one-two"), (" ", "")], '
        'ids=("spaces", "empty"))\n'
        'def test_slug(text, expected, owner_words):\n'
        '    assert owner_words == "owner fixture data"\n'
        '    assert slug(text) == expected\n\n'
        'def test_title():\n    assert title("hello world") == "Hello World"\n',
}
SOURCE_FILES = {
    'README.md': b'# Text utilities\n',
    'docs/żółw.md': b'Documentation fixture.\n',
    'src/textutil.py': b'def slug(text):\n    return text.strip()\n',
    **{name: text.encode() for name, text in TEST_FILES.items()},
}
NODES = tuple(sorted((
    'tests/test_textutil.py::test_slug[empty]',
    'tests/test_textutil.py::test_slug[spaces]',
    'tests/test_textutil.py::test_title',
)))


def load_public_lock(directory):
    """Read the five fixed, reviewed public archives; never resolve or import."""
    return PytestWheelLock(tuple(FrameworkWheel(
        name, pin.version, pin.filename, pin.sha256,
        read_evidence_file(directory, pin.filename, 2 * 1024 * 1024),
    ) for name, pin in sorted(_FRAMEWORK_PINS.items())))


def main(manifest, wheel_directory, output):
    forbidden = ('pytest', '_pytest', 'pluggy', 'iniconfig', 'packaging', 'pygments')
    assert not any(name in sys.modules for name in forbidden), 'HOST_FRAMEWORK_EXECUTION_FORBIDDEN'
    lock = load_public_lock(wheel_directory)
    suite = PytestSuite(tuple(sorted(TEST_FILES.items())), tuple((stage, NODES) for stage in TEST_STAGES))
    profiles, workers = [], []

    def profile_factory(profile):
        value = replace(
            profile, execution_profile='ISOLATED_PYTEST_FUNCTIONS_V1', wheel_lock=lock,
            pytest_suite=suite, oracle_paths=('src/extra.py', 'src/textutil.py'),
            stages=tuple((stage, (*cases, PythonFunctionCase(
                'added-title', 'extra', 'title', b'["hello world"]', b'"Hello World"',
            ))) for stage, cases in profile.stages),
        )
        profiles.append(value)
        return value

    def worker_factory(values, *, clock):
        worker = WireFixtureWorker(values, clock=clock)
        workers.append(worker)
        return worker

    kernel.main(manifest, output, worker_factory=worker_factory,
                profile_factory=profile_factory, source_files=SOURCE_FILES)
    assert len(profiles) == len(workers) == 1 and workers[0].messages == 2
    assert not any(name in sys.modules for name in forbidden), 'HOST_FRAMEWORK_EXECUTION_FORBIDDEN'
    retained = json.loads((output / 'result.json').read_bytes())
    assert retained['status'] == 'PASS' and retained['same_core'] is True
    assert [item['status'] for item in retained['loop']['attempts']] == ['FAIL', 'PASS']
    proof = {
        'schema': 'aioa.nz13.pytest-profile-acceptance.v1',
        'status': 'PASS_REAL_LOCAL_KERNEL_ONLY',
        'execution_profile': 'ISOLATED_PYTEST_FUNCTIONS_V1',
        'profile_digest': profiles[0].digest, 'suite_digest': suite.digest,
        'wheel_lock_digest': lock.digest,
        'wheel_bytes': sum(len(wheel.content) for wheel in lock.wheels),
        'largest_pinned_input': max(len(wheel.content) for wheel in lock.wheels),
        'nodes_per_stage': list(NODES), 'stages': list(TEST_STAGES),
        'source_files': {name: hashlib.sha256(raw).hexdigest() for name, raw in SOURCE_FILES.items()},
        'real_parametrization': True, 'real_conftest_fixture': True, 'real_resource_read': True,
        'repair': ['FAIL', 'PASS'], 'worker_messages': workers[0].messages,
        'same_core_kernel_and_local_git': True,
        'host_framework_imported': False, 'model_calls': 0, 'remote_calls': 0,
        'production_changes': 0, 'real_model_certification': 'NOT_CERTIFIED',
        'full_qualification': False,
    }
    with (output / 'NZ13_PYTEST_PROFILE_ACCEPTANCE.json').open('x') as stream:
        json.dump(proof, stream, indent=2)
    print(json.dumps(proof), flush=True)


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
