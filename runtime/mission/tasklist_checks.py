"""Fixed independent acceptance harness v1; runs only inside U06.

No code, commands, tests, paths or expected results are supplied by model text.
The harness calls the copied CLI as a process and examines durable JSON bytes.
"""
import json
import errno
import os
import resource
import socket
import subprocess
from pathlib import Path


ROOT = Path('/work/project')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def command(*arguments, ok=True):
    result = subprocess.run(['/usr/bin/python3.12', '-I', '-S', '-B',
        '/work/project/src/tasklist.py', *arguments], cwd=ROOT,
        stdin=subprocess.DEVNULL, capture_output=True, timeout=2, close_fds=True,
        env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/nonexistent', 'TMPDIR': '/tmp'})
    assert len(result.stdout) <= 16384 and len(result.stderr) <= 1024
    assert result.returncode == (0 if ok else 2), (result.returncode, result.stderr)
    assert result.stderr == (b'' if ok else b'TASKLIST_COMMAND_DENIED\n')
    return result.stdout


def main():
    # These are actual kernel checks in the same recipe, not mock containment.
    assert os.environ == {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                          'HOME': '/nonexistent', 'TMPDIR': '/tmp'}
    for outside in ('/home/l', '/media/l/LSC_DATA3', '/run/user', '/var/run/docker.sock'):
        try:
            os.open(outside, os.O_RDONLY)
        except OSError as exc:
            assert exc.errno in (errno.ENOENT, errno.EACCES, errno.EPERM)
        else:
            raise AssertionError('HOST_PATH_VISIBLE')
    for family in (socket.AF_INET, socket.AF_INET6, socket.AF_UNIX):
        try:
            socket.socket(family, socket.SOCK_STREAM)
        except OSError as exc:
            assert exc.errno == errno.EPERM
        else:
            raise AssertionError('NETWORK_ENABLED')
    assert resource.getrlimit(resource.RLIMIT_AS) == (536870912, 536870912)
    request = json.loads(Path('/inputs/plan.json').read_bytes())
    title, labels = request['title'], request['labels']
    empty = {'schema': 'aioa.tasklist-data.v1', 'title': title, 'next_id': 1, 'tasks': []}
    assert json.loads(command('init', title)) == empty                         # 1
    tasks = []
    for number, text in enumerate(labels, 1):
        tasks.append({'id': number, 'label': text, 'done': False})
        assert json.loads(command('add', text)) == {**empty, 'next_id': number + 1, 'tasks': tasks}
    assert len(tasks) == len(labels)                                          # 2
    assert json.loads(command('list'))['tasks'] == tasks                       # 3
    tasks[0]['done'] = True
    final = {**empty, 'next_id': len(labels) + 1, 'tasks': tasks}
    assert json.loads(command('complete', '1')) == final                       # 4
    data = ROOT / 'data/tasks.json'
    before = data.read_bytes()
    assert before == canonical(final)
    assert json.loads(command('complete', '1')) == final and data.read_bytes() == before  # 5
    text = (title + '\n' + ''.join(str(t['id']) + (' [x] ' if t['done'] else ' [ ] ')
        + t['label'] + '\n' for t in tasks)).encode('utf-8')
    assert command('list', '--text') == text                                  # 6
    for args in (('complete', '9'), ('shell', 'echo DONE'),
                 ('list', '../../HOME'), ('add', 'x' * 129), ('add', '\n')):
        command(*args, ok=False)
        assert data.read_bytes() == before                                   # 7..11
    assert json.loads(command('list')) == final
    assert set((ROOT / 'data').iterdir()) == {data}
    assert [t['id'] for t in final['tasks']] == list(range(1, len(labels) + 1))  # 12
    if len(labels) == 8:
        command('add', 'ninth task', ok=False)
        assert data.read_bytes() == before
    corrupt = canonical({**final, 'next_id': True})
    data.write_bytes(corrupt)
    command('list', ok=False)
    assert data.read_bytes() == corrupt                                      # 13
    data.write_bytes(before)
    data.unlink()
    data.symlink_to('/home/l/NO_HOME_ACCESS')
    command('list', ok=False)
    assert data.is_symlink()                                                  # 14
    data.unlink(); data.write_bytes(before)
    os.link(data, ROOT / 'data-twin')
    command('list', ok=False)
    assert data.read_bytes() == before and data.stat().st_nlink == 2           # 15
    (ROOT / 'data-twin').unlink()
    oversized = b'x' * 16385
    data.write_bytes(oversized)
    command('list', ok=False)
    assert data.read_bytes() == oversized                                     # 16
    data.write_bytes(before)
    assert json.loads(command('list')) == final and data.read_bytes() == before
    (ROOT / 'list.txt').write_bytes(text)
    print('TASKLIST_CHECKS_V1 PASS 16')


if __name__ == '__main__':
    main()
