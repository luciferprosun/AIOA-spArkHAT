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


def _input_policy(filename):
    confined()
    modules = {'wheel_policy.py': 'aioa_pinned_wheel_policy',
               'test_policy.py': 'aioa_pinned_test_policy'}
    require(type(filename) is str and filename in modules, 'FUNCTION_INPUT_POLICY')
    path = '/inputs/' + filename
    spec = importlib.util.spec_from_file_location(modules[filename], path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def decode_wheel_lock(module, raw, read_wheel, *, framework=False):
    # Pure bounded data dispatch. Only the trusted confined caller supplies the
    # fixed policy module/readonly input loader; no resolver or package imports.
    require(type(framework) is bool and callable(read_wheel), 'FUNCTION_LOCK_PROFILE')
    if raw == b'null' and not framework:
        return None
    manifest = strict(raw)
    schema = 'aioa.pytest-wheel-lock.v1' if framework else 'aioa.python-wheel-lock.v1'
    require(type(manifest) is dict and manifest.get('schema') == schema
            and type(manifest.get('wheels')) is list
            and (len(manifest['wheels']) == 5 if framework else 1 <= len(manifest['wheels']) <= 3),
            'FUNCTION_LOCK_SCHEMA')
    wheels = []
    wheel_class = module.FrameworkWheel if framework else module.LockedWheel
    lock_class = module.PytestWheelLock if framework else module.PythonWheelLock
    for row in manifest['wheels']:
        require(type(row) is dict and set(row) == {'distribution', 'version', 'filename', 'sha256', 'bytes'}
                and type(row['filename']) is str and 0 < len(row['filename']) <= 192
                and '/' not in row['filename'] and '\\' not in row['filename']
                and '\0' not in row['filename'] and row['filename'].endswith('-py3-none-any.whl'),
                'FUNCTION_LOCK_SCHEMA')
        content = read_wheel(row['filename'])
        require(type(content) is bytes and type(row['bytes']) is int and row['bytes'] == len(content),
                'FUNCTION_LOCK_BYTES')
        wheels.append(wheel_class(distribution=row['distribution'], version=row['version'],
                                  filename=row['filename'], sha256=row['sha256'], content=content))
    lock = lock_class(tuple(wheels))
    require(lock.manifest_bytes() == raw, 'FUNCTION_LOCK_MISMATCH')
    return lock


def wheel_lock(*, framework=False):
    module = _input_policy('wheel_policy.py')
    raw = Path('/inputs/python-wheel-lock.json').read_bytes()
    return decode_wheel_lock(module, raw, lambda name: Path('/inputs', name).read_bytes(), framework=framework)

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


def _workspace_root(target):
    require(type(target) is str and target in ('project', 'tests', 'oracle-project'), 'FUNCTION_WORKSPACE_TARGET')
    return Path('/work', target)


def stage_workspace(archive, support, *, target='project'):
    root = _workspace_root(target)
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


def verify_workspace(archive, support, *, target='project'):
    root = _workspace_root(target)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        require(support['inspect_tree'](directory) == archive, 'FUNCTION_SOURCE_CHANGED')
    finally:
        os.close(directory)


def _observation_profile(mode, calls):
    legacy = {'mode': 'observe', 'profile': 'ISOLATED_PYTHON_FUNCTIONS_V1'}
    framework = {'mode': 'observe', 'profile': 'ISOLATED_PYTEST_FUNCTIONS_V1'}
    require(type(mode) is dict and mode in (legacy, framework), 'FUNCTION_MODE')
    selected = mode == framework
    require(type(calls) is list and 1 <= len(calls) <= (8 if selected else 16), 'FUNCTION_CALL_BOUND')
    return selected


def child_call_config(index, *, framework_profile=False):
    require(type(framework_profile) is bool and (
        framework_profile and (type(index) is str and index == 'pytest'
                               or type(index) is int and 0 <= index < 8)
        or not framework_profile and type(index) is int and 0 <= index < 16), 'FUNCTION_CHILD_SELECTOR')
    framework = framework_profile and index == 'pytest'
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
    cwd = '/work/project'
    if framework_profile:
        env.update(HOME='/nonexistent', TMPDIR=('/tmp/pytest-framework' if framework else '/tmp/oracle-' + str(index)),
                   PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
        if not framework:
            cwd = '/work/oracle-project'
    return {'argv': ['/usr/bin/python3.12', '-I', '-S', '-B', '/inputs/function_child.py', str(index)],
            'env': env, 'cwd': cwd, 'seconds': 5 if framework else 1,
            'schema': ('aioa.pytest-framework-observation.v1' if framework else 'aioa.python-function-return.v1')}


def one_call(index, *, framework_profile=False):
    selected = child_call_config(index, framework_profile=framework_profile)
    confined()
    # One existing child path, fresh trusted exec, closed env and no inherited
    # descriptors. No model, project file or package metadata chooses argv.
    process = subprocess.Popen(selected['argv'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, close_fds=True, shell=False,
                               env=selected['env'], cwd=selected['cwd'])
    output = bytearray()
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + selected['seconds']
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
        if selected['schema'] == 'aioa.pytest-framework-observation.v1':
            require(type(reply) is dict and reply.get('schema') == selected['schema'], 'PYTEST_CHILD_SCHEMA')
            return reply
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
    mode = json.loads(Path('/inputs/mode.json').read_bytes())
    calls = json.loads(Path('/inputs/calls.json').read_bytes())
    framework_profile = _observation_profile(mode, calls)
    support = runpy.run_path('/inputs/repository_support.py')
    archive = json.loads(Path('/inputs/workspace.json').read_bytes())
    context = json.loads(Path('/inputs/context.json').read_bytes())
    stage_workspace(archive, support)
    installed = install(wheel_lock(framework=framework_profile), support)
    suite, tests, oracle = None, None, None
    if framework_profile:
        policy = _input_policy('test_policy.py')
        suite = policy.PytestSuite.from_manifest(Path('/inputs/pytest-suite.json').read_bytes())
        tests = json.loads(suite.workspace_archive_bytes())
        oracle = json.loads(Path('/inputs/oracle-workspace.json').read_bytes())
        stage_workspace(tests, support, target='tests')
        stage_workspace(oracle, support, target='oracle-project')
        Path('/tmp/pytest-framework').mkdir(mode=0o700)
        for index in range(len(calls)):
            Path('/tmp/oracle-' + str(index)).mkdir(mode=0o700)

    def verify_views():
        verify_workspace(archive, support)
        if framework_profile:
            verify_workspace(tests, support, target='tests')
            verify_workspace(oracle, support, target='oracle-project')
        verify_installed(installed, support)

    verify_views()
    framework = None
    if framework_profile:
        framework = one_call('pytest', framework_profile=True)
        # Malformed facts abort; a well-formed failure remains repairable. Neither
        # is an independent oracle or approval, and no missing event becomes PASS.
        suite.check_observation(framework, context['stage'])
        verify_views()
    results = []
    for index, call in enumerate(calls):
        verify_views()
        result = one_call(index, framework_profile=framework_profile)
        results.append({'case_id': call['case_id'], **result})
        verify_views()
    report = {'schema': 'aioa.python-observation.v2', 'profile_digest': context['profile_digest'],
              'patchset_sha256': context['patchset_sha256'], 'stage': context['stage'], 'results': results}
    if framework_profile:
        report.update(schema='aioa.python-observation.v3', framework=framework)
        # Match the host preflight budget, including escaped Unicode and LF.
        raw = json.dumps(report, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode()
        require(len(raw) + 1 <= 16384, 'FUNCTION_OBSERVATION_BOUND')
        dependencies = canonical({'schema': 'aioa.python-dependencies.v1', 'files': sorted(installed)})
        Path('/artifacts/dependencies.json').write_bytes(dependencies)
    else:
        raw = canonical(report)
        require(len(raw) <= 16384, 'FUNCTION_OBSERVATION_BOUND')
    print(raw.decode(), flush=True)
    # This completion marker alone cannot establish a test outcome at Core.
    Path('/artifacts/calls-complete.txt').write_bytes(b'PYTHON_CALLS_FINISHED\n')

if __name__ == '__main__':
    observe()
