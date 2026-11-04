"""Host-only fixed READ recipes. No shell, arbitrary API path or write method.

Authority belongs to the caller's existing Native Core. This module owns no
session, database, credential or approval; it never reads a token value.
"""
import json
import hashlib
import os
from pathlib import Path
import pwd
import re
import selectors
import stat
import subprocess
import time
from urllib.parse import quote

from .read_ops import validate_read_payload

REPOSITORY = 'luciferprosun/AIOA-spArkHAT'
REPOSITORY_ID = 1247349659
OPERATIONS = frozenset(('github.repository', 'github.issues', 'git.status', 'git.log', 'git.branches'))
READ_TIMEOUT_SECONDS = 20


def _require(condition, code='TOOL_READ_INVALID'):
    if not condition:
        raise ValueError(code)


def _remaining(deadline):
    remaining = deadline-time.monotonic()
    _require(remaining > 0, 'TOOL_READ_TIMEOUT')
    return remaining


def _bounded_command(argv, *, cwd, env, timeout=4, max_bytes=65536, deadline=None):
    """Kill only this child on timeout/overflow; never retain stderr/credentials."""
    now = time.monotonic()
    deadline = min(now+timeout, deadline) if deadline is not None else now+timeout
    _remaining(deadline)  # Expired recipes must not start another child.
    child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False)
    data = bytearray()
    selector = selectors.DefaultSelector()
    try:
        selector.register(child.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            _require(remaining > 0, 'TOOL_READ_TIMEOUT')
            events = selector.select(remaining)
            _require(bool(events), 'TOOL_READ_TIMEOUT')
            piece = os.read(child.stdout.fileno(), 4096)
            if not piece:
                break
            data.extend(piece)
            _require(len(data) <= max_bytes, 'TOOL_READ_OUTPUT_LIMIT')
        code = child.wait(timeout=max(.01, deadline - time.monotonic()))
        _require(code == 0, 'TOOL_READ_DENIED_OR_UNAVAILABLE')
        return bytes(data)
    except subprocess.TimeoutExpired:
        raise ValueError('TOOL_READ_TIMEOUT') from None
    finally:
        selector.close()
        child.stdout.close()
        if child.poll() is None:
            child.kill()
        child.wait()


def _environment():
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'LANG': 'C.UTF-8',
            'GH_CONFIG_DIR': str(home/'.config/gh'), 'GH_PROMPT_DISABLED': '1', 'GH_NO_UPDATE_NOTIFIER': '1',
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_ALLOW_PROTOCOL': '', 'GIT_NO_LAZY_FETCH': '1'}


def _binary(path):
    info = Path(path).lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
             'TOOL_BINARY_UNTRUSTED')


def _qualified_gh():
    _require(hashlib.sha256(Path('/usr/bin/gh').read_bytes()).hexdigest() ==
             '2fd925d68889746976958342fb749bf102bc7dc8bcba3abfa533a80ad7791673', 'GITHUB_CLI_NOT_QUALIFIED')


def _preferences(raw):
    """Reject ambiguous YAML BEFORE gh can migrate or resolve credentials."""
    try:
        import yaml
    except ImportError:
        raise ValueError('GITHUB_CONFIG_VERSION_UNVERIFIED') from None
    try:
        for token in yaml.scan(raw):
            _require(not isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken,
                                            yaml.tokens.TagToken, yaml.tokens.DirectiveToken)),
                     'GITHUB_CONFIG_AMBIGUOUS')
        document = yaml.compose(raw, Loader=yaml.SafeLoader)
        def validate(node, depth=0):
            _require(depth <= 4, 'GITHUB_CONFIG_AMBIGUOUS')
            if isinstance(node, yaml.MappingNode):
                keys = set()
                for key, value in node.value:
                    _require(isinstance(key, yaml.ScalarNode) and key.tag == 'tag:yaml.org,2002:str'
                             and key.value not in keys and key.value != '<<', 'GITHUB_CONFIG_AMBIGUOUS')
                    keys.add(key.value); validate(value, depth+1)
            else:
                _require(isinstance(node, yaml.ScalarNode), 'GITHUB_CONFIG_AMBIGUOUS')
        validate(document)
        _require(isinstance(document, yaml.MappingNode), 'GITHUB_CONFIG_VERSION_UNVERIFIED')
        versions = [v for k, v in document.value if k.value == 'version']
        _require(len(versions) == 1 and isinstance(versions[0], yaml.ScalarNode)
                 and versions[0].value == '1' and versions[0].tag in (
                     'tag:yaml.org,2002:str', 'tag:yaml.org,2002:int'), 'GITHUB_CONFIG_VERSION_UNVERIFIED')
        return yaml.safe_load(raw)
    except (yaml.YAMLError, RecursionError):
        raise ValueError('GITHUB_CONFIG_VERSION_UNVERIFIED') from None


def _github_json(endpoint, *, check=lambda: None, deadline=None):
    if deadline is None:deadline=time.monotonic()+READ_TIMEOUT_SECONDS
    _remaining(deadline)
    _binary('/usr/bin/gh')
    # This is an internal closed recipe, never an endpoint taken from a model.
    prefix = 'repos/' + REPOSITORY
    _require(endpoint == prefix or endpoint == prefix+'/issues?state=all&per_page=5'
             or re.fullmatch(re.escape(prefix)+r'/branches/[A-Za-z0-9%_.-]{1,768}', endpoint))
    env = _environment()
    directory = Path(env['GH_CONFIG_DIR'])
    _require(directory.resolve() == directory and directory.stat().st_uid == os.getuid()
             and not directory.stat().st_mode & 0o022, 'GITHUB_CONFIG_UNTRUSTED')
    config = directory/'config.yml'
    _require(config.exists() and not config.is_symlink(), 'GITHUB_CONFIG_VERSION_UNVERIFIED')
    if config.exists():
        info = config.lstat()
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and not info.st_mode & 0o022 and info.st_size <= 65536, 'GITHUB_CONFIG_UNTRUSTED')
        # Only preferences, never hosts.yml credential values. gh2.45 may migrate
        # legacy config using GraphQL; version1 is mandatory BEFORE any child.
        fd = os.open(config, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            raw = os.read(fd, 65537)
        finally:
            os.close(fd)
        preferences = _preferences(raw)
        allowed = {'version', 'git_protocol', 'editor', 'prompt', 'prefer_editor_prompt', 'pager',
                   'aliases', 'http_unix_socket', 'browser', 'color_labels', 'accessible_colors', 'accessible_prompter', 'spinner'}
        _require(type(preferences) is dict and set(preferences) <= allowed
                 and str(preferences.get('version')) == '1', 'GITHUB_CONFIG_VERSION_UNVERIFIED')
        _require(not preferences.get('http_unix_socket'), 'GITHUB_TRANSPORT_OVERRIDE_DENIED')
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode, s.st_uid)
        # A pinned installed CLI is necessary for the reviewed no-migration rule.
        _qualified_gh()
        for args in ([], ['--host', 'github.com']):
            check()
            _require(identity(config.lstat()) == identity(info), 'GITHUB_CONFIG_CHANGED')
            setting = _bounded_command(['/usr/bin/gh', 'config', 'get', 'http_unix_socket', *args],
                                       cwd=directory, env=env, max_bytes=1024, deadline=deadline)
            check()
            _require(not setting.strip(), 'GITHUB_TRANSPORT_OVERRIDE_DENIED')
        _require(identity(config.lstat()) == identity(info), 'GITHUB_CONFIG_CHANGED')
    check()
    raw = _bounded_command(['/usr/bin/gh', 'api', '--hostname', 'github.com', '--method', 'GET', endpoint],
                           cwd=directory, env=env, timeout=8, deadline=deadline)
    check()
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError('GITHUB_READ_INVALID_JSON') from None


def _repository(check, deadline):
    check()
    data = _github_json('repos/'+REPOSITORY, check=check, deadline=deadline)
    check()
    _require(type(data) is dict and data.get('id') == REPOSITORY_ID
             and type(data.get('id')) is int and data.get('full_name') == REPOSITORY,
             'GITHUB_REPOSITORY_MISMATCH')
    branch = data.get('default_branch')
    _require(type(branch) is str and 1 <= len(branch) <= 255)
    return data, branch


def read(operation, project_root, *, check=lambda: None, deadline=None):
    """One of five fixed READ recipes; all data remains untrusted display text."""
    _require(type(operation) is str and operation in OPERATIONS, 'TOOL_OPERATION_DENIED')
    if deadline is None:deadline=time.monotonic()+READ_TIMEOUT_SECONDS
    authority_check=check
    def check():
        _remaining(deadline)
        authority_check()
        _remaining(deadline)
    check()
    if operation.startswith('github.'):
        repo, branch = _repository(check, deadline)
        data = {'repository': REPOSITORY, 'repository_id': REPOSITORY_ID,
                'url': 'https://github.com/'+REPOSITORY, 'branch': branch}
        if operation == 'github.repository':
            check()
            revision = _github_json('repos/'+REPOSITORY+'/branches/'+quote(branch, safe=''), check=check, deadline=deadline)
            check()
            _require(type(revision) is dict and revision.get('name') == branch
                     and type(revision.get('commit')) is dict
                     and type(revision['commit'].get('sha')) is str
                     and re.fullmatch(r'[0-9a-f]{40}', revision['commit']['sha']), 'GITHUB_REVISION_MISMATCH')
            data['commit_sha'] = revision['commit']['sha']
        else:
            check()
            rows = _github_json('repos/'+REPOSITORY+'/issues?state=all&per_page=5', check=check, deadline=deadline)
            check()
            _require(type(rows) is list and len(rows) <= 5)
            issues = []
            for row in rows:
                _require(type(row) is dict and type(row.get('number')) is int and 0 < row['number'] < 2**31
                         and row.get('state') in ('open', 'closed') and type(row.get('title')) is str
                         and len(row['title']) <= 1024)
                if 'pull_request' not in row:
                    url = 'https://github.com/'+REPOSITORY+'/issues/'+str(row['number'])
                    _require(row.get('html_url') == url)
                    issues.append({'number': row['number'], 'title': row['title'], 'state': row['state'], 'url': url})
            data['issues'] = issues
        return {'operation': operation, 'data': data, 'transport': 'LIVE_GITHUB_GET'}
    root = Path(project_root).absolute()
    _require(root.resolve() == root and root.is_dir(), 'GIT_ROOT_DENIED')
    validate_read_payload(operation, {})
    _binary('/usr/bin/git')
    recipes = {'git.status': ['status', '--porcelain=v1', '--untracked-files=no'],
               'git.log': ['log', '--no-show-signature', '-5', '--format=%H %s'],
               'git.branches': ['branch', '--list', '--format=%(refname:short) %(objectname)']}
    check()
    output = _bounded_command(['/usr/bin/git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                              '-c', 'credential.helper=', '-c', 'protocol.allow=never',
                              '-c', 'core.untrackedCache=false', '-c', 'core.pager=cat', *recipes[operation]],
                             cwd=root, env=_environment(), max_bytes=32768, deadline=deadline)
    check()
    return {'operation': operation, 'data': {'text': output.decode('utf-8', 'replace')}, 'transport': 'LOCAL_GIT_READ'}
