"""Normal Python and locked pure wheel on the existing Core/kernel/Git flow.

Fixture packages are inert bytes on the host. Only the existing broker runs
candidate/package code, with mandatory child Landlock and independent oracles.
"""
import hashlib
import io
import json
import sys
import zipfile
from dataclasses import replace
from pathlib import Path

import nz11_kernel_acceptance as kernel
from nz13_worker_acceptance import WireFixtureWorker
from test_nz13_locked_wheels import FILENAME, wheel_bytes

from runtime.mission.dependency_lock import LockedWheel, PythonWheelLock
from runtime.mission.worker import CandidateFile, CandidatePatch


def main(manifest, output):
    workers = []
    raw = wheel_bytes(package=b'def join_words(words):\n    return "-".join(words)\n')
    # Exercise the accepted compressed format in the actual fixed guest runtime,
    # not only ZIP_STORED in host codecs. No package member is imported here.
    output_bytes = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, \
            zipfile.ZipFile(output_bytes, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for info in source.infolist():
            archive.writestr(info, source.read(info.filename), compress_type=zipfile.ZIP_DEFLATED)
    raw = output_bytes.getvalue()

    lock = PythonWheelLock((LockedWheel('fixture-math', '1.0.0', FILENAME,
                                        hashlib.sha256(raw).hexdigest(), raw),))

    def profile_factory(profile):
        return replace(profile, execution_profile='ISOLATED_PYTHON_FUNCTIONS_V1', wheel_lock=lock)

    def candidates(original):
        # The failing source is the existing real RED case. Repair requires
        # normal Python imports/loops and an actually installed closed wheel.
        return (original[0], CandidatePatch((CandidateFile('src/textutil.py',
                'import fixture_math\n\ndef slug(text):\n    words = []\n'
                '    for word in text.split():\n        words.append(word.lower())\n'
                '    return fixture_math.join_words(words)\n'),
                *tuple(file for file in original[1].files if file.path != 'src/textutil.py'))))

    def worker_factory(values, *, clock):
        worker = WireFixtureWorker(values, clock=clock)
        workers.append(worker)
        return worker

    assert 'fixture_math' not in sys.modules, 'HOST_PACKAGE_EXECUTION_FORBIDDEN'
    kernel.main(manifest, output, worker_factory=worker_factory,
                profile_factory=profile_factory, candidate_transform=candidates)
    assert len(workers) == 1 and workers[0].messages == 2
    assert 'fixture_math' not in sys.modules, 'HOST_PACKAGE_EXECUTION_FORBIDDEN'
    proof = {'schema': 'aioa.nz13.function-profile-acceptance.v1',
             'status': 'PASS_REAL_LOCAL_KERNEL_ONLY',
             'execution_profile': 'ISOLATED_PYTHON_FUNCTIONS_V1',
             'wheel_archive_compression': 'DEFLATED', 'wheel_lock_sha256': lock.digest, 'wheel_sha256': hashlib.sha256(raw).hexdigest(),
             'child_policy': 'LANDLOCK_ABI6_MANDATORY_V1', 'repair': ['FAIL', 'PASS'],
             'candidate_messages': workers[0].messages, 'same_core_kernel_and_local_git': True,
             'host_package_imported': False, 'provider_calls': 0, 'remote_calls': 0,
             'real_model_certification': 'NOT_CERTIFIED'}
    with (output / 'NZ13_FUNCTION_PROFILE_ACCEPTANCE.json').open('x') as stream:
        json.dump(proof, stream, indent=2)
    print(json.dumps(proof), flush=True)


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
