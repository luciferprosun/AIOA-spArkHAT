"""Fixed synthetic Git recipe, executed only by unchanged Core/U06 START gate."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

# This immutable contract file is part of the reviewed read-only recipe inputs.
if __name__ == '__main__':
    sys.path.insert(0, '/inputs')
    from contract import (SyntheticGitPlan, BASE_BRANCH, BASE_MESSAGE, COMMIT_MESSAGE,
                          GIT_BINARY, GIT_SHA256, require, canonical, sha256, objects)


def environment():
    return {'PATH': '/nonexistent', 'HOME': '/nonexistent', 'XDG_CONFIG_HOME': '/nonexistent',
            'LANG': 'C.UTF-8', 'TMPDIR': '/tmp', 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_SYSTEM': '/dev/null', 'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_EXEC_PATH': '/nonexistent', 'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0',
            'GIT_PAGER': 'cat', 'GIT_EDITOR': '/nonexistent',
            'GIT_AUTHOR_NAME': 'AIOA Offline Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
            'GIT_COMMITTER_NAME': 'AIOA Offline Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
            'GIT_AUTHOR_DATE': '946684800 +0000', 'GIT_COMMITTER_DATE': '946684800 +0000'}


def git(*arguments):
    options = ('--no-pager', '-c', 'core.hooksPath=/nonexistent', '-c', 'core.fsmonitor=false',
               '-c', 'commit.gpgsign=false', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false',
               '-c', 'credential.helper=', '-c', 'protocol.allow=never')
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen((GIT_BINARY, *options, *arguments), cwd='/work/repo', env=environment(),
                                 stdin=subprocess.DEVNULL, stdout=out, stderr=err, close_fds=True)
        try:
            child.wait(timeout=2)
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=2)
        out.seek(0); err.seek(0)
        stdout, stderr = out.read(16385), err.read(16385)
        require(len(stdout) <= 16384 and len(stderr) <= 16384, 'GIT_OUTPUT_LIMIT')
        require(child.returncode == 0, 'GIT_COMMAND_FAILED:' + stderr.decode(errors='replace')[:1024])
        return stdout


def regular(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'GIT_FILE_TYPE_DENIED')
    return info


def inspect_tree(root):
    count = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in (*dirs, *files):
            path = Path(directory) / name; info = path.lstat(); count += 1
            require(count <= 128 and not stat.S_ISLNK(info.st_mode) and
                    (stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)),
                    'GIT_FILE_TYPE_DENIED')
    for name in ('objects/info/alternates', 'info/grafts', 'shallow', 'modules'):
        require(not (root / '.git' / name).exists(), 'GIT_FOREIGN_METADATA_DENIED')
    hooks = root / '.git/hooks'
    require(not hooks.exists() or not any(hooks.iterdir()), 'GIT_HOOKS_DENIED')


def main():
    raw = Path('/inputs/plan.json').read_bytes(); meta = json.loads(raw)
    require(type(meta) is dict, 'INVALID_GIT_PLAN')
    base = Path('/inputs/approved-base.txt').read_bytes(); after = Path('/inputs/after.txt').read_bytes()
    plan = SyntheticGitPlan(meta.get('repo_ref'), meta.get('expected_revision'), base, after, meta.get('branch'))
    require(plan.plan_bytes() == raw, 'GIT_PLAN_CHANGED')
    seed_raw = Path('/inputs/seed.json').read_bytes(); seed = json.loads(seed_raw)
    require(type(seed) is dict and set(seed) == {'repo_ref', 'revision', 'branch', 'source_sha256'} and
            canonical(seed) == seed_raw, 'INVALID_GIT_SEED')
    before = Path('/inputs/before.txt').read_bytes()
    require(seed['repo_ref'] == plan.repo_ref and type(seed['revision']) is int and seed['revision'] == 1 and
            seed['branch'] == BASE_BRANCH, 'GIT_TARGET_DENIED')
    require(seed['source_sha256'] == sha256(before) and before == base, 'GIT_BASE_DENIED')
    require(Path('/inputs/base-message.txt').read_bytes() == BASE_MESSAGE and
            Path('/inputs/commit-message.txt').read_bytes() == COMMIT_MESSAGE, 'GIT_MESSAGE_CHANGED')
    require(sha256(Path(GIT_BINARY).read_bytes()) == GIT_SHA256, 'PINNED_GIT_CHANGED')
    root = Path('/work/repo'); root.mkdir(mode=0o700)
    template = Path('/work/empty-template'); template.mkdir(mode=0o700)
    root_id = root.stat().st_dev, root.stat().st_ino
    git('init', '--object-format=sha1', '--template=/work/empty-template', '--initial-branch=' + BASE_BRANCH, '.')
    (root / 'src').mkdir(mode=0o700)
    source = root / 'src/app.py'; source.write_bytes(before); source.chmod(0o600)
    git('add', '--', 'src/app.py')
    git('commit', '--no-verify', '--no-gpg-sign', '--cleanup=verbatim', '-F', '/inputs/base-message.txt')
    # preflight boundary: trusted fault fixtures may alter their own repository.
    require(not root.is_symlink() and (root.stat().st_dev, root.stat().st_ino) == root_id, 'GIT_ROOT_CHANGED')
    require((root / '.git').is_dir() and not (root / '.git').is_symlink(), 'GIT_FOREIGN_METADATA_DENIED')
    inspect_tree(root); regular(source)
    require(source.read_bytes() == before, 'GIT_BASE_DENIED')
    config = {}
    for row in git('config', '--local', '--null', '--list').split(b'\0'):
        if row:
            key, value = row.decode().split('\n', 1)
            require(key not in config, 'GIT_CONFIG_DENIED'); config[key] = value
    allowed = {'core.repositoryformatversion': '0', 'core.filemode': 'true',
               'core.bare': 'false', 'core.logallrefupdates': 'true'}
    require(config == allowed, 'GIT_CONFIG_DENIED')
    require(git('rev-parse', '--show-toplevel') == b'/work/repo\n' and
            git('rev-parse', 'HEAD') == (plan.base_head + '\n').encode() and
            git('branch', '--show-current') == (BASE_BRANCH + '\n').encode() and
            git('for-each-ref', '--format=%(refname)') == ('refs/heads/' + BASE_BRANCH + '\n').encode(),
            'GIT_HEAD_BRANCH_DENIED')
    require(git('status', '--porcelain=v1', '-z', '--untracked-files=all') == b'', 'GIT_DIRTY_DENIED')
    require(git('log', '-1', '--format=%H') == (plan.base_head + '\n').encode(), 'GIT_HEAD_BRANCH_DENIED')
    git('checkout', '-b', plan.branch)
    observed = regular(source)
    require(source.read_bytes() == before, 'GIT_BASE_DENIED')
    temporary = root / 'src/.approved.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(after); stream.flush(); os.fsync(stream.fileno())
    last = regular(source)
    require((last.st_dev, last.st_ino) == (observed.st_dev, observed.st_ino) and source.read_bytes() == before,
            'GIT_BASE_DENIED')
    os.rename(temporary, source)
    actual_diff = git('diff', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames', '--full-index', '--', 'src/app.py')
    require(actual_diff == plan.diff_bytes(), 'GIT_DIFF_DENIED')
    git('add', '--', 'src/app.py')
    git('commit', '--no-verify', '--no-gpg-sign', '--cleanup=verbatim', '-F', '/inputs/commit-message.txt')
    # committed boundary: ACK loss or interruption never grants another commit.
    inspect_tree(root); regular(source)
    require(source.read_bytes() == after and git('rev-parse', 'HEAD') == (plan.commit_head + '\n').encode() and
            git('rev-parse', 'HEAD^{tree}') == (objects(after, COMMIT_MESSAGE, plan.base_head)['tree'] + '\n').encode(),
            'GIT_COMMIT_READBACK_DENIED')
    require(git('status', '--porcelain=v1', '-z', '--untracked-files=all') == b'' and
            git('branch', '--show-current') == (plan.branch + '\n').encode(), 'GIT_COMMIT_READBACK_DENIED')
    require(git('for-each-ref', '--format=%(refname:short)') == ''.join(x + '\n' for x in sorted((BASE_BRANCH, plan.branch))).encode() and
            git('log', '-2', '--format=%H') == (plan.commit_head + '\n' + plan.base_head + '\n').encode(),
            'GIT_COMMIT_READBACK_DENIED')
    for name, data in {'source.py': source.read_bytes(), 'diff.patch': actual_diff,
                       'git-result.json': plan.result_bytes(), 'github-preview.json': canonical(plan.github_preview())}.items():
        fd = os.open('/artifacts/' + name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())


if __name__ == '__main__':
    main()
