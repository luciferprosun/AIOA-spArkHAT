"""Trusted parent for one opt-in function profile in LinuxSandboxBroker.

Only the isolated child executes repository or installed package code. Returned
values are untrusted observations; expected answers remain outside the guest.
This file cannot run a recipe on the host.
"""
import hashlib
import importlib.util
import json
import os
import runpy
import selectors
import stat
import subprocess
import sys
import time
from pathlib import Path


def require(value, code):
    if not value:
        raise ValueError(code)


def confined():
    status = Path('/proc/self/status').read_text()
    require('NoNewPrivs:\t1' in status and 'Seccomp:\t2' in status
            and Path('/bootstrap').is_file()
            and os.statvfs('/inputs/recipe.py').f_flag & os.ST_RDONLY, 'SANDBOX_ONLY_RECIPE')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def strict(raw):
    def pairs(items):
        require(len(items) == len(dict(items)), 'FUNCTION_JSON_DUPLICATE')
        return dict(items)
    require(type(raw) is bytes and 0 < len(raw) <= 8192, 'FUNCTION_JSON_BOUND')
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _value: require(False, 'FUNCTION_JSON_NUMBER'))
    canonical(value)
    return value


def wheel_lock():
    path = '/inputs/wheel_policy.py'
    spec = importlib.util.spec_from_file_location('aioa_pinned_wheel_policy', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    raw = Path('/inputs/python-wheel-lock.json').read_bytes()
    if raw == b'null':
        return None
    manifest = strict(raw)
    require(type(manifest) is dict and type(manifest.get('wheels')) is list
            and 1 <= len(manifest['wheels']) <= 3, 'FUNCTION_LOCK_SCHEMA')
    wheels = []
    for row in manifest['wheels']:
        require(type(row) is dict and set(row) == {'distribution', 'version', 'filename', 'sha256', 'bytes'}
                and type(row['filename']) is str and '/' not in row['filename']
                and '\\' not in row['filename'] and row['filename'].endswith('-py3-none-any.whl'),
                'FUNCTION_LOCK_SCHEMA')
        content = Path('/inputs', row['filename']).read_bytes()
        require(type(row['bytes']) is int and row['bytes'] == len(content), 'FUNCTION_LOCK_BYTES')
        wheels.append(module.LockedWheel(distribution=row['distribution'], version=row['version'],
                                         filename=row['filename'], sha256=row['sha256'], content=content))
    lock = module.PythonWheelLock(tuple(wheels))
    require(lock.manifest_bytes() == raw, 'FUNCTION_LOCK_MISMATCH')
    return lock


def install(lock, support):
    root = Path('/work/dependencies')
    root.mkdir(mode=0o700)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    installed = []
    try:
        if lock is not None:
            for wheel in lock.wheels:
                for name, data in wheel.members():
                    parts = support['path_parts'](name)
                    parent = support['parent'](directory, parts, create=True)
                    try:
                        support['write_new'](parent, parts[-1], data, 0o600)
                        observed, _ = support['read_regular'](parent, parts[-1])
                        require(observed == data, 'FUNCTION_INSTALL_READBACK')
                    finally:
                        os.close(parent)
                    installed.append((name, hashlib.sha256(data).hexdigest(), len(data)))
    finally:
        os.close(directory)
    return installed


def verify_installed(installed, support):
    directory = os.open('/work/dependencies', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    actual = []

    def scan(fd, prefix):
        for name in sorted(os.listdir(fd)):
            path = prefix + name
            support['path_parts'](path)
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                try:
                    scan(child, path + '/')
                finally:
                    os.close(child)
            else:
                require(len(actual) < 768, 'FUNCTION_INSTALL_BOUND')
                data, mode = support['read_regular'](fd, name)
                require(mode == 0o600, 'FUNCTION_INSTALL_MODE')
                actual.append((path, hashlib.sha256(data).hexdigest(), len(data)))

    try:
        scan(directory, '')
        require(sorted(actual) == sorted(installed), 'FUNCTION_INSTALL_CHANGED')
    finally:
        os.close(directory)


def stage_workspace(archive, support):
    root = Path('/work/project')
    root.mkdir(mode=0o700)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        require(type(archive) is dict and set(archive) == {'schema', 'files'}
                and archive['schema'] == 'aioa.validation-workspace.v1'
                and type(archive['files']) is list and len(archive['files']) <= 256,
                'FUNCTION_WORKSPACE_SCHEMA')
        for item in archive['files']:
            parts = support['path_parts'](item['path'])
            parent = support['parent'](directory, parts, create=True)
            try:
                require(item['mode'] in (0o600, 0o644), 'FUNCTION_WORKSPACE_MODE')
                support['write_new'](parent, parts[-1], item['text'].encode(), item['mode'])
            finally:
                os.close(parent)
        require(support['inspect_tree'](directory) == archive, 'FUNCTION_WORKSPACE_DRIFT')
    finally:
        os.close(directory)


def one_call(index):
    # Fixed child, argv, environment and ceiling. No command is read from code,
    # package metadata or a model. The outer broker also kills all descendants.
    process = subprocess.Popen(['/usr/bin/python3.12', '-I', '-S', '-B',
                                '/inputs/function_child.py', str(index)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, close_fds=True,
                               env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                               cwd='/work/project')
    output = bytearray()
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + 1
    try:
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            require(time.monotonic() < deadline, 'FUNCTION_CHILD_TIMEOUT')
            for key, _ in selector.select(max(0, deadline - time.monotonic())):
                data = os.read(key.fd, 4096)
                if not data:
                    selector.unregister(key.fileobj)
                output.extend(data)
                require(len(output) <= 8192, 'FUNCTION_CHILD_OUTPUT_BOUND')
        require(process.wait(timeout=max(.001, deadline - time.monotonic())) == 0,
                'FUNCTION_CHILD_EXIT')
        reply = strict(bytes(output))
        require(type(reply) is dict and reply.get('schema') == 'aioa.python-function-return.v1',
                'FUNCTION_CHILD_SCHEMA')
        if reply.get('kind') == 'returned':
            require(set(reply) == {'schema', 'kind', 'value'}, 'FUNCTION_CHILD_SCHEMA')
            return {'kind': 'returned', 'value': reply['value']}
        require(set(reply) == {'schema', 'kind', 'type'} and reply.get('kind') == 'raised'
                and type(reply['type']) is str and reply['type'].isascii()
                and reply['type'].isalnum() and len(reply['type']) <= 64, 'FUNCTION_CHILD_SCHEMA')
        return {'kind': 'raised', 'type': reply['type']}
    finally:
        selector.close()
        process.stdout.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)


def observe():
    confined()
    require(json.loads(Path('/inputs/mode.json').read_bytes())
            == {'mode': 'observe', 'profile': 'ISOLATED_PYTHON_FUNCTIONS_V1'}, 'FUNCTION_MODE')
    support = runpy.run_path('/inputs/repository_support.py')
    archive = json.loads(Path('/inputs/workspace.json').read_bytes())
    calls = json.loads(Path('/inputs/calls.json').read_bytes())
    context = json.loads(Path('/inputs/context.json').read_bytes())
    require(type(calls) is list and 1 <= len(calls) <= 16, 'FUNCTION_CALL_BOUND')
    stage_workspace(archive, support)
    installed = install(wheel_lock(), support)
    results = []
    for index, call in enumerate(calls):
        verify_installed(installed, support)
        # Missing isolation, malformed protocol, crash and timeout remain
        # UNKNOWN at Core. Only a well-formed candidate return is repairable.
        result = one_call(index)
        results.append({'case_id': call['case_id'], **result})
        directory = os.open('/work/project', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            require(support['inspect_tree'](directory) == archive, 'FUNCTION_SOURCE_CHANGED')
        finally:
            os.close(directory)
        verify_installed(installed, support)
    report = {'schema': 'aioa.python-observation.v2', 'profile_digest': context['profile_digest'],
              'patchset_sha256': context['patchset_sha256'], 'stage': context['stage'], 'results': results}
    raw = canonical(report)
    require(len(raw) <= 16384, 'FUNCTION_OBSERVATION_BOUND')
    print(raw.decode(), flush=True)
    # A marker proves no test outcome. Core's external oracle checks every value.
    Path('/artifacts/calls-complete.txt').write_bytes(b'PYTHON_CALLS_FINISHED\n')


if __name__ == '__main__':
    observe()
