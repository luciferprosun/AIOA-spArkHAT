"""Immutable task-list recipe v1; execute only behind Core/U06 durable START.

Fresh owned project, fixed paths and subprocess argv. This is a reviewed
template contract, separate from the unchanged U08 arithmetic AST validator.
"""
import hashlib
import json
import os
from pathlib import Path
import py_compile
import re
import stat
import subprocess


TEMPLATE_ID = 'aioa-tasklist-cli-v1'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_text(value):
    require(type(value) is str and 1 <= len(value) <= 128, 'TASKLIST_TEXT_REQUIRED')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError:
        raise ValueError('TASKLIST_TEXT_REQUIRED') from None
    require(1 <= size <= 128 and value.strip() and all(c.isprintable() for c in value),
            'TASKLIST_TEXT_REQUIRED')


def validate_request(template_id, title, labels):
    require(type(template_id) is str and template_id == TEMPLATE_ID, 'TASKLIST_TEMPLATE_DENIED')
    validate_text(title)
    require(type(labels) is tuple and 1 <= len(labels) <= 8, 'TASKLIST_LABEL_LIMIT')
    for label in labels:
        validate_text(label)


def validate_plan(raw, template, checks, worker):
    require(type(raw) is bytes and 0 < len(raw) <= 8192, 'TASKLIST_PLAN_LIMIT')
    plan = json.loads(raw)
    require(type(plan) is dict and set(plan) == {'schema', 'project_ref', 'path',
        'expected_revision', 'preimage_sha256', 'template_id', 'source_sha256',
        'checks_sha256', 'worker_sha256', 'title', 'labels'} and canonical(plan) == raw,
        'INVALID_TASKLIST_PLAN')
    require(plan['schema'] == 'aioa.tasklist-plan.v1' and plan['path'] == 'src/tasklist.py',
            'TASKLIST_PATH_DENIED')
    require(type(plan['project_ref']) is str and
            re.fullmatch(r'fixture:[A-Za-z0-9][A-Za-z0-9_-]{0,47}', plan['project_ref']),
            'FIXTURE_PROJECT_REQUIRED')
    require(type(plan['expected_revision']) is int and plan['expected_revision'] == 0
            and plan['preimage_sha256'] is None, 'TASKLIST_FRESH_PROJECT_REQUIRED')
    require(type(plan['labels']) is list, 'TASKLIST_LABEL_LIMIT')
    validate_request(plan['template_id'], plan['title'], tuple(plan['labels']))
    for key, data in (('source_sha256', template), ('checks_sha256', checks), ('worker_sha256', worker)):
        require(type(data) is bytes and 0 < len(data) <= 65536 and
                type(plan[key]) is str and plan[key] == digest(data), 'TASKLIST_SOURCE_DIGEST_DENIED')
    return plan


def identity(info):
    return info.st_dev, info.st_ino


def read_file(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 65536,
                'TASKLIST_FILE_TYPE_DENIED')
        data = os.read(fd, 65537)
        require(len(data) == info.st_size and
                identity(os.stat(name, dir_fd=directory, follow_symlinks=False)) == identity(info),
                'TASKLIST_FILE_CHANGED')
        return data, info
    finally:
        os.close(fd)


def write_file(directory, name, data):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def main():
    raw = Path('/inputs/plan.json').read_bytes()
    template = Path('/inputs/template.py').read_bytes()
    checks = Path('/inputs/checks.py').read_bytes()
    worker = Path('/inputs/recipe.py').read_bytes()
    plan = validate_plan(raw, template, checks, worker)
    seed_raw = Path('/inputs/seed.json').read_bytes()
    seed = json.loads(seed_raw)
    require(type(seed) is dict and set(seed) == {'project_ref', 'revision', 'content_sha256'}
            and canonical(seed) == seed_raw, 'INVALID_TASKLIST_SEED')
    require(seed['project_ref'] == plan['project_ref'] and type(seed['revision']) is int
            and seed['revision'] == 0 and seed['content_sha256'] is None
            and Path('/inputs/before.py').read_bytes() == b'', 'TASKLIST_PREIMAGE_DENIED')
    fds = []
    try:
        work = os.open('/work', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW); fds.append(work)
        os.mkdir('project', 0o700, dir_fd=work)
        root = os.open('project', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=work); fds.append(root)
        os.mkdir('src', 0o700, dir_fd=root)
        source = os.open('src', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root); fds.append(source)
        root_identity, source_identity = identity(os.fstat(root)), identity(os.fstat(source))
        write_file(root, 'revision.json', seed_raw)
        write_file(source, 'tasklist.py', template)
        # mutation boundary: trusted security fixtures may alter their own files.
        require(identity(os.stat('project', dir_fd=work, follow_symlinks=False)) == root_identity
                and identity(os.stat('src', dir_fd=root, follow_symlinks=False)) == source_identity,
                'TASKLIST_DIRECTORY_CHANGED')
        actual, installed = read_file(source, 'tasklist.py')
        require(actual == template and read_file(root, 'revision.json')[0] == seed_raw,
                'TASKLIST_POSTIMAGE_DENIED')
        py_compile.compile('/work/project/src/tasklist.py', cfile='/work/tasklist.pyc', doraise=True)
        # applied boundary: interruption never authorizes an automatic retry.
        result = subprocess.run(['/usr/bin/python3.12', '-I', '-S', '-B', '/inputs/checks.py'],
            cwd='/work/project', stdin=subprocess.DEVNULL, capture_output=True,
            timeout=10, close_fds=True, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                                         'HOME': '/nonexistent', 'TMPDIR': '/tmp'})
        require(result.returncode == 0 and result.stdout == b'TASKLIST_CHECKS_V1 PASS 16\n'
                and result.stderr == b'', 'TASKLIST_TEST_FAILED')
        require(identity(os.stat('project', dir_fd=work, follow_symlinks=False)) == root_identity
                and identity(os.stat('src', dir_fd=root, follow_symlinks=False)) == source_identity,
                'TASKLIST_DIRECTORY_CHANGED')
        actual, final = read_file(source, 'tasklist.py')
        require(identity(installed) == identity(final) and actual == template
                and read_file(root, 'revision.json')[0] == seed_raw, 'TASKLIST_POSTIMAGE_DENIED')
        data_dir = os.open('data', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root); fds.append(data_dir)
        require(set(os.listdir(data_dir)) == {'tasks.json'}, 'TASKLIST_UNEXPECTED_DATA')
        data, _ = read_file(data_dir, 'tasks.json')
        listing, _ = read_file(root, 'list.txt')
        outcome = canonical({'schema': 'aioa.tasklist-result.v1', 'plan_digest': digest(raw),
            'project_ref': plan['project_ref'], 'path': plan['path'], 'revision': 1,
            'source_sha256': digest(actual), 'checks_sha256': digest(checks),
            'worker_sha256': digest(worker), 'data_sha256': digest(data), 'list_sha256': digest(listing),
            'build': 'PASS', 'test': 'PASS', 'test_checks': 16, 'completed_ids': [1],
            'task_count': len(plan['labels'])})
        artifacts = {'tasklist.py': actual, 'tasklist-tests.py': checks, 'plan.json': raw,
            'tasks.json': data, 'list.txt': listing, 'test-log.txt': result.stdout,
            'tasklist-result.json': outcome}
        manifest = canonical({'schema': 'aioa.tasklist-manifest.v1', 'plan_digest': digest(raw),
            'files': {name: {'sha256': digest(content), 'bytes': len(content)}
                      for name, content in artifacts.items()}})
        artifacts['manifest.json'] = manifest
        revision = canonical({'project_ref': plan['project_ref'], 'revision': 1, 'content_sha256': digest(actual)})
        write_file(root, '.revision.tmp', revision)
        os.rename('.revision.tmp', 'revision.json', src_dir_fd=root, dst_dir_fd=root); os.fsync(root)
        destination = os.open('/artifacts', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW); fds.append(destination)
        for name, content in artifacts.items():
            write_file(destination, name, content)
    finally:
        for fd in reversed(fds):
            os.close(fd)


if __name__ == '__main__':
    main()
