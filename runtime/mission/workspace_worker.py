"""One registered fresh-workspace recipe for the existing Linux sandbox.

No HTTP input, generic shell, dependency installation or user directory access.
All effect bytes/paths/tests are pinned before exact human approval.
"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess

helpers = runpy.run_path('/inputs/fs_helpers.py')
read_file, write_file, require = (helpers[n] for n in ('read_file', 'write_file', 'require'))


def sha(data): return hashlib.sha256(data).hexdigest()


def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def main():
    raw = Path('/inputs/plan.json').read_bytes(); plan = json.loads(raw)
    require(canonical(plan) == raw and plan['schema'] == 'aioa.sensorbridge-plan.v1'
            and plan['revision'] == 0 and set(plan['files']) == {
                'sensorbridge.py', 'test_sensorbridge.py', 'README.md'}, 'WORKSPACE_PLAN_DENIED')
    root = os.open('/work', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory = artifacts = None
    try:
        os.mkdir('project', 0o700, dir_fd=root)
        directory = os.open('project', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
        identity = os.fstat(directory)
        for name in ('sensorbridge.py', 'test_sensorbridge.py'):
            content = Path('/inputs', name).read_bytes()
            require(sha(content) == plan['files'][name]['sha256'], 'WORKSPACE_SOURCE_CHANGED')
            write_file(directory, name, content)
        # Exercise bounded create + append + rename on this fresh fixture only.
        before, tail = b'# SensorBridge\n', b'\nDeterministic Python simulator. No hardware or network.\n'
        write_file(directory, 'README.tmp', before)
        fd = os.open('README.tmp', os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=directory)
        try:
            metadata = os.fstat(fd)
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and metadata.st_size == len(before),
                    'WORKSPACE_PREIMAGE_CHANGED')
            require(os.write(fd, tail) == len(tail), 'WORKSPACE_SHORT_WRITE'); os.fsync(fd)
        finally: os.close(fd)
        require(read_file(directory, 'README.tmp')[0] == before+tail, 'WORKSPACE_APPEND_CHANGED')
        os.rename('README.tmp', 'README.md', src_dir_fd=directory, dst_dir_fd=directory); os.fsync(directory)
        observed = {name: read_file(directory, name)[0] for name in plan['files']}
        require({name: {'sha256': sha(data), 'bytes': len(data)} for name, data in observed.items()}
                == plan['files'], 'WORKSPACE_MANIFEST_CHANGED')
        result = subprocess.run(['/usr/bin/python3.12', '-I', '-S', '-B', '/work/project/test_sensorbridge.py'],
                                capture_output=True, stdin=subprocess.DEVNULL, close_fds=True, timeout=5)
        require(result.returncode == 0 and result.stdout == b'SENSORBRIDGE_CHECKS_V1 PASS 5\n'
                and result.stderr == b'', 'WORKSPACE_TESTS_FAILED')
        final = os.stat('project', dir_fd=root, follow_symlinks=False)
        require((final.st_dev, final.st_ino) == (identity.st_dev, identity.st_ino), 'WORKSPACE_ROOT_CHANGED')
        require(set(os.listdir(directory)) == set(plan['files']), 'WORKSPACE_UNEXPECTED_FILE')
        artifacts = os.open('/artifacts', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for name, expected in observed.items():
            actual = read_file(directory, name)[0]
            require(actual == expected, 'WORKSPACE_POSTIMAGE_CHANGED')
            write_file(artifacts, name, actual)
        write_file(artifacts, 'test-log.txt', result.stdout)
        write_file(artifacts, 'manifest.json', canonical(plan['files']))
        write_file(artifacts, 'result.json', canonical({'schema': 'aioa.sensorbridge-result.v1',
            'project_ref': plan['project_ref'], 'plan_digest': sha(raw), 'revision': 1,
            'tests_passed': 5, 'files_sha256': sha(canonical(plan['files']))}))
    finally:
        for fd in (artifacts, directory, root):
            if fd is not None: os.close(fd)


if __name__ == '__main__': main()
