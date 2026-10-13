"""Reviewed task-list CLI template v1; stdlib, fixed cwd/data, no environment input.

This source is copied verbatim by the Core-authorized task-list recipe. Labels
are data. Nothing in this program imports or executes a label or configuration.
"""
import json
import os
import stat
import sys


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def label(value):
    require(type(value) is str and 1 <= len(value.encode('utf-8')) <= 128
            and value.strip() and all(c.isprintable() for c in value), 'INVALID_LABEL')
    return value


def validate(value):
    require(type(value) is dict and set(value) == {'schema', 'title', 'next_id', 'tasks'}
            and value['schema'] == 'aioa.tasklist-data.v1', 'INVALID_DATA')
    label(value['title'])
    tasks = value['tasks']
    require(type(tasks) is list and len(tasks) <= 8 and type(value['next_id']) is int
            and value['next_id'] == len(tasks) + 1, 'INVALID_DATA')
    for number, task in enumerate(tasks, 1):
        require(type(task) is dict and set(task) == {'id', 'label', 'done'}
                and type(task['id']) is int and task['id'] == number
                and type(task['done']) is bool, 'INVALID_DATA')
        label(task['label'])
    return value


def read_data(directory):
    require(set(os.listdir(directory)) == {'tasks.json'}, 'UNEXPECTED_DATA_FILE')
    fd = os.open('tasks.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 16384,
                'INVALID_DATA_FILE')
        raw = os.read(fd, 16385)
        require(len(raw) == info.st_size, 'DATA_CHANGED')
        value = validate(json.loads(raw))
        require(canonical(value) == raw, 'NONCANONICAL_DATA')
        return value, info, raw
    finally:
        os.close(fd)


def save_data(directory, value, prior=None):
    raw = canonical(validate(value))
    require(len(raw) <= 16384, 'DATA_LIMIT')
    if prior is not None:
        _, observed, _ = read_data(directory)
        require((observed.st_dev, observed.st_ino) == (prior.st_dev, prior.st_ino), 'DATA_CHANGED')
    else:
        require(not os.listdir(directory), 'DATA_EXISTS')
    fd = os.open('.tasks.tmp', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
        if prior is not None:
            _, observed, _ = read_before_rename(directory)
            require((observed.st_dev, observed.st_ino) == (prior.st_dev, prior.st_ino), 'DATA_CHANGED')
        os.rename('.tasks.tmp', 'tasks.json', src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        os.close(fd)


def read_before_rename(directory):
    # The only additional entry here is our exclusive temporary file.
    require(set(os.listdir(directory)) == {'tasks.json', '.tasks.tmp'}, 'UNEXPECTED_DATA_FILE')
    fd = os.open('tasks.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 16384,
                'INVALID_DATA_FILE')
        raw = os.read(fd, 16385)
        value = validate(json.loads(raw))
        require(canonical(value) == raw and len(raw) == info.st_size, 'DATA_CHANGED')
        return value, info, raw
    finally:
        os.close(fd)


def text_list(value):
    return value['title'] + '\n' + ''.join(
        str(task['id']) + (' [x] ' if task['done'] else ' [ ] ') + task['label'] + '\n'
        for task in value['tasks'])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    require(type(argv) is list and 1 <= len(argv) <= 2
            and all(type(item) is str and len(item.encode('utf-8')) <= 256 for item in argv),
            'INVALID_COMMAND')
    action = argv[0]
    require((action in ('init', 'add', 'complete') and len(argv) == 2)
            or (action == 'list' and (len(argv) == 1 or argv[1] == '--text')), 'INVALID_COMMAND')
    if action in ('init', 'add'):
        label(argv[1])
    if action == 'complete':
        require(argv[1] in tuple(str(n) for n in range(1, 9)), 'INVALID_TASK_ID')
    if action == 'init':
        os.mkdir('data', 0o700)
    directory = os.open('data', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if action == 'init':
            value = {'schema': 'aioa.tasklist-data.v1', 'title': argv[1], 'next_id': 1, 'tasks': []}
            save_data(directory, value)
        else:
            value, info, _ = read_data(directory)
            if action == 'add':
                require(len(value['tasks']) < 8, 'TASK_LIMIT')
                value['tasks'].append({'id': value['next_id'], 'label': argv[1], 'done': False})
                value['next_id'] += 1
                save_data(directory, value, info)
            elif action == 'complete':
                number = int(argv[1])
                require(number < value['next_id'], 'TASK_NOT_FOUND')
                if not value['tasks'][number - 1]['done']:
                    value['tasks'][number - 1]['done'] = True
                    save_data(directory, value, info)
        if action == 'list' and len(argv) == 2:
            sys.stdout.buffer.write(text_list(value).encode('utf-8'))
        else:
            sys.stdout.buffer.write(canonical(value) + b'\n')
    finally:
        os.close(directory)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, UnicodeError):
        sys.stderr.write('TASKLIST_COMMAND_DENIED\n')
        raise SystemExit(2)
