"""Host-only fixed READ recipes. No shell, arbitrary API path or write method.

Authority belongs to the caller's existing Native Core. This module owns no
session, database, credential or approval; it never reads a token value.
"""
import base64
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
CONTEXT_REPOSITORIES = {
    'github.code_context': (REPOSITORY, REPOSITORY_ID),
    'github.demo_context': ('luciferprosun/AIOA-spArkHAT-Meta-Hackathon-2026', 1445911975),
}
OPERATIONS = frozenset(('github.repository', 'github.issues', 'git.status', 'git.log', 'git.branches',
                        *CONTEXT_REPOSITORIES))
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
    legacy = (endpoint == prefix or endpoint == prefix+'/issues?state=all&per_page=5'
              or re.fullmatch(re.escape(prefix)+r'/branches/[A-Za-z0-9%_.-]{1,768}', endpoint))
    context = any(endpoint in ('repos/'+repo, 'repos/'+repo+'/git/ref/heads/main') or
        re.fullmatch(re.escape('repos/'+repo)+r'/git/(?:commits|trees|blobs)/[a-f0-9]{40}', endpoint)
        for repo, _ in CONTEXT_REPOSITORIES.values())
    _require(legacy or context)
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


def validate_context_data(operation, data):
    """Closed context shapes shared by receipt resolution and provider input.

    Validation grants no authority: the Native caller also verifies the signed
    receipt, owner/source/instance, freshness and the complete data digest.
    """
    code = 'CHAT_READ_DATA_MISMATCH'
    target = (REPOSITORY, REPOSITORY_ID) if operation == 'github.repository' else CONTEXT_REPOSITORIES.get(operation)
    _require(target is not None and type(data) is dict, code)
    fields = {'repository', 'repository_id', 'url', 'branch', 'commit_sha'}
    if operation in CONTEXT_REPOSITORIES: fields |= {'read_source', 'tree_sha', 'files'}
    _require(set(data) == fields and data['repository'] == target[0]
        and type(data['repository_id']) is int and data['repository_id'] == target[1]
        and data['url'] == 'https://github.com/'+target[0] and data['branch'] == 'main'
        and type(data['commit_sha']) is str and re.fullmatch('[a-f0-9]{40}', data['commit_sha']), code)
    if operation == 'github.repository': return
    _require(data['read_source'] == 'GITHUB_API' and type(data['tree_sha']) is str
        and re.fullmatch('[a-f0-9]{40}', data['tree_sha']) and type(data['files']) is list
        and len(data['files']) == 1, code)
    file = data['files'][0]
    _require(type(file) is dict and set(file) == {'path', 'git_blob_sha', 'sha256', 'bytes', 'excerpt', 'truncated'}
        and file['path'] == 'README.md' and type(file['git_blob_sha']) is str
        and re.fullmatch('[a-f0-9]{40}', file['git_blob_sha']) and type(file['sha256']) is str
        and re.fullmatch('[a-f0-9]{64}', file['sha256']) and type(file['bytes']) is int
        and 0 < file['bytes'] <= 32768 and type(file['excerpt']) is str and type(file['truncated']) is bool, code)
    raw = file['excerpt'].encode('utf-8')
    _require(0 < len(raw) <= min(1536, file['bytes']) and len(json.dumps(file['excerpt']).encode()) <= 1800
        and file['truncated'] == (len(raw) < file['bytes']) and '\0' not in file['excerpt'], code)
    if not file['truncated']:
        from runtime.mission.git_recipe import git_object
        _require(hashlib.sha256(raw).hexdigest() == file['sha256']
            and git_object('blob', raw) == file['git_blob_sha'], code)


def _repository_context(operation, check, deadline):
    """Six GETs, two fixed public repos, one regular file; no model URL input."""
    from runtime.mission.git_recipe import git_object
    repo, repo_id = CONTEXT_REPOSITORIES[operation]
    prefix = 'repos/'+repo
    def get(suffix=''):
        check()
        value = _github_json(prefix+suffix, check=check, deadline=deadline)
        check()
        _require(type(value) is dict, 'GITHUB_CONTEXT_INVALID')
        return value
    metadata = get()
    _require(type(metadata.get('id')) is int and metadata['id'] == repo_id
        and metadata.get('full_name') == repo and metadata.get('default_branch') == 'main'
        and all(metadata.get(k) is False for k in ('private', 'archived', 'disabled')), 'GITHUB_REPOSITORY_MISMATCH')
    ref = get('/git/ref/heads/main');obj = ref.get('object')
    _require(ref.get('ref') == 'refs/heads/main' and type(obj) is dict and obj.get('type') == 'commit'
        and type(obj.get('sha')) is str and re.fullmatch('[a-f0-9]{40}', obj['sha']), 'GITHUB_REVISION_MISMATCH')
    commit_sha = obj['sha'];commit = get('/git/commits/'+commit_sha);tree_ref = commit.get('tree')
    _require(commit.get('sha') == commit_sha and type(tree_ref) is dict and type(tree_ref.get('sha')) is str
        and re.fullmatch('[a-f0-9]{40}', tree_ref['sha']), 'GITHUB_REVISION_MISMATCH')
    tree = get('/git/trees/'+tree_ref['sha']);entries = tree.get('tree')
    _require(tree.get('sha') == tree_ref['sha'] and tree.get('truncated') is False
        and type(entries) is list and 0 < len(entries) <= 256, 'GITHUB_CONTEXT_TREE_INVALID')
    modes = {'100644': 'blob', '100755': 'blob', '120000': 'blob', '040000': 'tree', '160000': 'commit'}
    names = set();encoded = []
    for entry in entries:
        _require(type(entry) is dict, 'GITHUB_CONTEXT_TREE_INVALID')
        path, mode, kind, sha = (entry.get(k) for k in ('path', 'mode', 'type', 'sha'))
        _require(type(path) is str and 0 < len(path.encode()) <= 255 and path not in names
            and path not in ('.', '..') and not any(c in path for c in '/\0') and type(mode) is str
            and modes.get(mode) == kind and type(sha) is str and re.fullmatch('[a-f0-9]{40}', sha), 'GITHUB_CONTEXT_TREE_INVALID')
        names.add(path)
        encoded.append((path.encode()+(b'/' if kind == 'tree' else b'\0'),
            ('40000' if kind == 'tree' else mode).encode()+b' '+path.encode()+b'\0'+bytes.fromhex(sha)))
    _require(git_object('tree', b''.join(value for _, value in sorted(encoded))) == tree_ref['sha'], 'GITHUB_CONTEXT_TREE_INVALID')
    matches = [e for e in entries if e['path'] == 'README.md' and e['mode'] == '100644' and e['type'] == 'blob']
    _require(len(matches) == 1, 'GITHUB_CONTEXT_REGULAR_FILE_REQUIRED')
    blob_sha = matches[0]['sha'];blob = get('/git/blobs/'+blob_sha)
    _require(blob.get('sha') == blob_sha and blob.get('encoding') == 'base64' and type(blob.get('content')) is str
        and type(blob.get('size')) is int and 0 < blob['size'] <= 32768, 'GITHUB_CONTEXT_BLOB_INVALID')
    try:
        raw = base64.b64decode(blob['content'].replace('\n', ''), validate=True)
        _require(len(raw) == blob['size'] and git_object('blob', raw) == blob_sha, 'GITHUB_CONTEXT_BLOB_INVALID')
        raw.decode('utf-8')
        _require(b'\0' not in raw, 'GITHUB_CONTEXT_BLOB_INVALID')
    except (ValueError, UnicodeError): raise ValueError('GITHUB_CONTEXT_BLOB_INVALID') from None
    excerpt = raw[:1536].decode('utf-8', errors='ignore')
    while len(json.dumps(excerpt).encode()) > 1800: excerpt = excerpt[:-1]
    final = get('/git/ref/heads/main')
    _require(final.get('ref') == ref['ref'] and final.get('object') == obj, 'GITHUB_CONTEXT_BASE_CHANGED')
    data = {'repository': repo, 'repository_id': repo_id, 'url': 'https://github.com/'+repo,
        'branch': 'main', 'commit_sha': commit_sha, 'tree_sha': tree_ref['sha'], 'read_source': 'GITHUB_API',
        'files': [{'path': 'README.md', 'git_blob_sha': blob_sha, 'sha256': hashlib.sha256(raw).hexdigest(),
                  'bytes': len(raw), 'excerpt': excerpt, 'truncated': len(excerpt.encode()) < len(raw)}]}
    validate_context_data(operation, data)
    return {'operation': operation, 'data': data, 'transport': 'LIVE_GITHUB_GET'}


def read(operation, project_root, *, check=lambda: None, deadline=None):
    """Fixed READ recipes; all returned text remains untrusted data."""
    _require(type(operation) is str and operation in OPERATIONS, 'TOOL_OPERATION_DENIED')
    if deadline is None:deadline=time.monotonic()+READ_TIMEOUT_SECONDS
    authority_check=check
    def check():
        _remaining(deadline)
        authority_check()
        _remaining(deadline)
    check()
    if operation in CONTEXT_REPOSITORIES:
        return _repository_context(operation, check, deadline)
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
