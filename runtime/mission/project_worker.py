"""Fixed standalone U08 fixture recipe. Execute only behind native Core/U06 START.

Fresh private single-writer project; fd pinning is not concurrent host-file CAS.
No commands, tests, dependencies or approval fields come from model proposals.
"""
import ast
import hashlib
import json
import os
import py_compile
import re
import stat
import subprocess
from pathlib import Path


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def validate_program(data):
    """A single value assignment; no calls/imports/control flow or test bypass."""
    require(type(data) is bytes and 0 < len(data) <= 8192, 'SAFE_PROJECT_PROGRAM_REQUIRED')
    try:
        tree = ast.parse(data)
    except (SyntaxError, UnicodeError, ValueError):
        raise ValueError('SAFE_PROJECT_PROGRAM_REQUIRED') from None
    require(len(list(ast.walk(tree))) <= 32 and len(tree.body) == 1 and
            type(tree.body[0]) is ast.Assign, 'SAFE_PROJECT_PROGRAM_REQUIRED')
    assignment = tree.body[0]
    require(len(assignment.targets) == 1 and type(assignment.targets[0]) is ast.Name and
            assignment.targets[0].id == 'value', 'SAFE_PROJECT_PROGRAM_REQUIRED')

    def evaluate(node, depth=0):
        require(depth <= 8, 'SAFE_PROJECT_PROGRAM_REQUIRED')
        if type(node) is ast.Constant:
            require(type(node.value) is int, 'SAFE_PROJECT_PROGRAM_REQUIRED')
            value = node.value
        elif type(node) is ast.BinOp and type(node.op) in (ast.Add, ast.Sub, ast.Mult):
            left, right = evaluate(node.left, depth + 1), evaluate(node.right, depth + 1)
            value = left + right if type(node.op) is ast.Add else left - right if type(node.op) is ast.Sub else left * right
        elif type(node) is ast.UnaryOp and type(node.op) in (ast.UAdd, ast.USub):
            value = evaluate(node.operand, depth + 1)
            if type(node.op) is ast.USub:
                value = -value
        else:
            raise ValueError('SAFE_PROJECT_PROGRAM_REQUIRED')
        require(-1000000 <= value <= 1000000, 'SAFE_PROJECT_PROGRAM_REQUIRED')
        return value

    return evaluate(assignment.value)


def identity(info):
    return info.st_dev, info.st_ino


def read_file(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 8192,
                'PROJECT_FILE_TYPE_DENIED')
        data = os.read(fd, 8193)
        require(len(data) == info.st_size and identity(os.stat(name, dir_fd=directory, follow_symlinks=False)) == identity(info),
                'PROJECT_FILE_CHANGED')
        return data, info
    finally:
        os.close(fd)


def write_file(directory, name, data):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def main():
    raw = Path('/inputs/project.json').read_bytes()
    plan = json.loads(raw)
    require(type(plan) is dict and set(plan) == {'schema', 'project_ref', 'path', 'expected_revision',
            'preimage_sha256', 'replacement_sha256', 'expected_value'} and canonical(plan) == raw,
            'INVALID_PROJECT_PLAN')
    require(plan['schema'] == 'aioa.python-project-plan.v1' and plan['path'] == 'src/app.py', 'FIXED_PROJECT_PATH_REQUIRED')
    require(type(plan['project_ref']) is str and re.fullmatch(r'fixture:[A-Za-z0-9][A-Za-z0-9_-]{0,47}', plan['project_ref']),
            'FIXTURE_PROJECT_REQUIRED')
    revision = plan['expected_revision']
    require(type(revision) is int and 0 <= revision <= 1000000 and
            type(plan['expected_value']) is int and -1000000 <= plan['expected_value'] <= 1000000, 'INVALID_PROJECT_REVISION')
    require((revision == 0 and plan['preimage_sha256'] is None) or
            (revision > 0 and type(plan['preimage_sha256']) is str and re.fullmatch('[0-9a-f]{64}', plan['preimage_sha256'])),
            'INVALID_PROJECT_PREIMAGE')
    seed_raw = Path('/inputs/seed.json').read_bytes()
    seed = json.loads(seed_raw)
    require(type(seed) is dict and set(seed) == {'project_ref', 'revision', 'content_sha256'} and canonical(seed) == seed_raw,
            'INVALID_PROJECT_SEED')
    before = Path('/inputs/before.py').read_bytes()
    after = Path('/inputs/after.py').read_bytes()
    require(seed['project_ref'] == plan['project_ref'] and type(seed['revision']) is int and seed['revision'] == revision,
            'PROJECT_REVISION_DENIED')
    require(seed['content_sha256'] == plan['preimage_sha256'] and
            ((revision == 0 and before == b'') or (revision > 0 and 0 < len(before) <= 8192 and digest(before) == seed['content_sha256'])),
            'PROJECT_PREIMAGE_DENIED')
    require(0 < len(after) <= 8192 and digest(after) == plan['replacement_sha256'], 'PROJECT_REPLACEMENT_DENIED')
    validate_program(after)
    fds = []
    try:
        work = os.open('/work', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW); fds.append(work)
        os.mkdir('project', 0o700, dir_fd=work)
        root = os.open('project', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=work); fds.append(root)
        os.mkdir('src', 0o700, dir_fd=root)
        source = os.open('src', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root); fds.append(source)
        root_identity, source_identity = identity(os.fstat(root)), identity(os.fstat(source))
        write_file(root, 'revision.json', seed_raw)
        if revision > 0:
            write_file(source, 'app.py', before)
        # mutation boundary: trusted fault fixtures may alter their own seed here.
        require(identity(os.stat('project', dir_fd=work, follow_symlinks=False)) == root_identity and
                identity(os.stat('src', dir_fd=root, follow_symlinks=False)) == source_identity, 'PROJECT_DIRECTORY_CHANGED')
        require(read_file(root, 'revision.json')[0] == seed_raw, 'PROJECT_REVISION_DENIED')
        if revision == 0:
            write_file(source, 'app.py', after)
        else:
            current, observed = read_file(source, 'app.py')
            require(current == before and digest(current) == plan['preimage_sha256'], 'PROJECT_PREIMAGE_DENIED')
            write_file(source, '.approved.tmp', after)
            current_again, last = read_file(source, 'app.py')
            require(identity(last) == identity(observed) and current_again == before, 'PROJECT_FILE_CHANGED')
            os.rename('.approved.tmp', 'app.py', src_dir_fd=source, dst_dir_fd=source)
            os.fsync(source)
        actual, installed = read_file(source, 'app.py')
        require(actual == after, 'PROJECT_REPLACEMENT_DENIED')
        # applied boundary: interruption here must remain UNKNOWN without a retry.
        py_compile.compile('/work/project/src/app.py', cfile='/work/build.pyc', doraise=True)
        result = subprocess.run(['/usr/bin/python3.12', '-I', '-S', '-B', '/inputs/check.py', str(plan['expected_value'])],
                                stdin=subprocess.DEVNULL, close_fds=True, check=False)
        require(result.returncode == 0, 'PROJECT_TEST_FAILED')
        require(identity(os.stat('project', dir_fd=work, follow_symlinks=False)) == root_identity and
                identity(os.stat('src', dir_fd=root, follow_symlinks=False)) == source_identity, 'PROJECT_DIRECTORY_CHANGED')
        actual, final = read_file(source, 'app.py')
        require(identity(final) == identity(installed) and actual == after and read_file(root, 'revision.json')[0] == seed_raw,
                'PROJECT_POSTIMAGE_CHANGED')
        outcome = {'schema': 'aioa.python-project-result.v1', 'plan_digest': digest(raw),
                   'project_ref': plan['project_ref'], 'path': plan['path'], 'revision': revision + 1,
                   'source_sha256': digest(actual), 'build': 'PASS', 'test': 'PASS', 'value': plan['expected_value']}
        write_file(root, '.revision.tmp', canonical({'project_ref': plan['project_ref'], 'revision': revision + 1,
                                                   'content_sha256': digest(actual)}))
        os.rename('.revision.tmp', 'revision.json', src_dir_fd=root, dst_dir_fd=root); os.fsync(root)
        artifacts = os.open('/artifacts', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW); fds.append(artifacts)
        write_file(artifacts, 'source.py', actual)
        write_file(artifacts, 'project-result.json', canonical(outcome))
    finally:
        for fd in reversed(fds):
            os.close(fd)


if __name__ == '__main__':
    main()
