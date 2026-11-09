"""Host-only fixed READ recipes. No shell, arbitrary API path or write method.

Authority belongs to the caller's existing Native Core. This module owns no
session, database, credential or approval; it never reads a token value.
"""
import base64
import hashlib
import json
import os
import pwd
import re
import selectors
import stat
import subprocess
import time
from pathlib import Path
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
    rich = any(endpoint == 'repos/' + REPOSITORY + '/' + kind + '?' +
               ('' if kind == 'actions/runs' else 'state=all&') + 'per_page=10&page=' + str(page)
               for kind in ('issues', 'pulls', 'actions/runs') for page in (1, 2))
    _require(legacy or context or rich)
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
    from runtime.secret_redaction import contains_sensitive_material
    check()
    data = _github_json('repos/'+REPOSITORY, check=check, deadline=deadline)
    check()
    _require(type(data) is dict and data.get('id') == REPOSITORY_ID
             and type(data.get('id')) is int and data.get('full_name') == REPOSITORY,
             'GITHUB_REPOSITORY_MISMATCH')
    branch = data.get('default_branch')
    _require(type(branch) is str and 1 <= len(branch) <= 255)
    _require(not contains_sensitive_material(branch), 'GITHUB_CONTEXT_REF')
    return data, branch




def _rich_public_text(value, maximum, *, empty=True):
    from runtime.secret_redaction import contains_sensitive_material
    _require(type(value) is str and (empty or value) and len(value.encode()) <= maximum
             and not contains_sensitive_material(value), 'CHAT_READ_DATA_MISMATCH')


def _validate_rich_context_data(operation, data):
    code = 'CHAT_READ_DATA_MISMATCH'
    fields = {'schema', 'repository', 'default_branch', 'requested_ref', 'observed_sha',
              'tree_sha', 'visibility', 'taint', 'authority', 'items', 'pagination'}
    _require(operation in RICH_CONTEXT_OPERATIONS and type(data) is dict and set(data) == fields, code)
    _require(data['schema'] in ('aioa.github-read-context.v1', 'aioa.github-read-context.v2')
             and data['default_branch'] == 'main'
             and data['requested_ref'] == 'main' and data['visibility'] == 'public'
             and data['taint'] == 'REMOTE_UNTRUSTED_DATA' and data['authority'] == 'NONE', code)
    identity = {'owner': 'luciferprosun', 'name': 'AIOA-spArkHAT',
                'canonical_url': 'https://github.com/' + REPOSITORY, 'repository_id': REPOSITORY_ID}
    _require(type(data['repository']) is dict and data['repository'] == identity
             and type(data['repository']['repository_id']) is int, code)
    _rich_sha(data['observed_sha'])
    _rich_sha(data['tree_sha'])
    pages, items = data['pagination'], data['items']
    _require(type(pages) is dict and set(pages) == {'per_page', 'page_limit', 'pages_read', 'truncated'}
             and type(pages['per_page']) is int and pages['per_page'] == 10
             and type(pages['page_limit']) is int and pages['page_limit'] == 2
             and type(pages['pages_read']) is int and 0 <= pages['pages_read'] <= 2
             and type(pages['truncated']) is bool and (not pages['truncated'] or pages['pages_read'] == 2)
             and type(items) is list and len(items) <= 20, code)
    if operation == 'github.repository_context':
        _require(not items and pages['pages_read'] == 0 and not pages['truncated'], code)
    else:
        _require(1 <= pages['pages_read'] <= 2 and len(items) <= pages['pages_read'] * 10, code)
    provenance_fields = {'text_provenance'} if data['schema'] == 'aioa.github-read-context.v2' else set()
    seen = set()
    for item in items:
        _require(type(item) is dict and item.get('taint') == 'REMOTE_UNTRUSTED_DATA', code)
        if operation == 'github.issue_contexts':
            _require(set(item) == {'number', 'title', 'body', 'state', 'labels',
                                   'labels_truncated', 'author', 'url', 'taint'} | provenance_fields, code)
            number = _rich_integer(item['number'], maximum=2**31-1)
            _require(item['state'] in ('OPEN', 'CLOSED') and type(item['labels']) is list
                     and len(item['labels']) <= 8 and type(item['labels_truncated']) is bool, code)
            for label in item['labels']:
                _rich_public_text(label, 64)
            if item['author'] is not None:
                _rich_public_text(item['author'], 64)
            _rich_public_text(item['title'], 256)
            _rich_public_text(item['body'], 768)
            _rich_url(item['url'], 'issues', number)
        elif operation == 'github.pull_requests':
            _require(set(item) == {'number', 'title', 'body', 'state', 'base_ref', 'base_sha',
                                   'head_ref', 'head_sha', 'changed_files', 'commits',
                                   'checks_summary', 'checks_verified', 'url', 'taint'} | provenance_fields, code)
            number = _rich_integer(item['number'], maximum=2**31-1)
            _require(item['state'] in ('OPEN', 'CLOSED', 'MERGED')
                     and item['checks_verified'] is False and item['checks_summary'] == '', code)
            for key in ('base_ref', 'head_ref'):
                _rich_ref(item[key])
            for key in ('base_sha', 'head_sha'):
                _rich_sha(item[key])
            for key in ('changed_files', 'commits'):
                _rich_optional_count(item[key])
            _rich_public_text(item['title'], 256)
            _rich_public_text(item['body'], 768)
            _rich_url(item['url'], 'pull', number)
        else:
            _require(set(item) == {'run_id', 'workflow_id', 'name', 'status', 'conclusion',
                                   'head_sha', 'head_branch', 'job_id', 'log_context',
                                   'logs_fetched', 'core_completion_verified', 'url', 'taint'} | provenance_fields, code)
            number = _rich_integer(item['run_id'])
            workflow = item['workflow_id']
            _require(type(workflow) is str and re.fullmatch('[1-9][0-9]{0,18}', workflow)
                     and int(workflow) < 2**63 and item['job_id'] is None
                     and item['log_context'] == '' and item['logs_fetched'] is False
                     and item['core_completion_verified'] is False, code)
            _rich_action({'id': number, 'workflow_id': int(workflow), 'name': item['name'],
                          'status': item['status'], 'conclusion': item['conclusion'],
                          'head_sha': item['head_sha'], 'head_branch': item['head_branch'],
                          'repository': {'id': REPOSITORY_ID, 'full_name': REPOSITORY},
                          'html_url': item['url']})
            _rich_public_text(item['name'], 256)
        if provenance_fields:
            _validate_text_provenance(operation, item)
        _require(number not in seen, code)
        seen.add(number)
    _require(len(json.dumps(data, sort_keys=True, separators=(',', ':'),
                            ensure_ascii=False, allow_nan=False).encode()) <= 32768, code)


def validate_context_data(operation, data):
    """Closed context shapes shared by receipt resolution and provider input.

    Validation grants no authority: the Native caller also verifies the signed
    receipt, owner/source/instance, freshness and the complete data digest.
    """
    if operation in RICH_CONTEXT_OPERATIONS:
        return _validate_rich_context_data(operation, data)
    code = 'CHAT_READ_DATA_MISMATCH'
    from runtime.secret_redaction import REDACTION_MARKER, contains_sensitive_material
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
    ordinary_fields = {'path', 'git_blob_sha', 'sha256', 'bytes', 'excerpt', 'truncated'}
    _require(type(file) is dict and set(file) in (ordinary_fields, ordinary_fields | {'redacted'})
        and file['path'] == 'README.md' and type(file['git_blob_sha']) is str
        and re.fullmatch('[a-f0-9]{40}', file['git_blob_sha']) and type(file['sha256']) is str
        and re.fullmatch('[a-f0-9]{64}', file['sha256']) and type(file['bytes']) is int
        and 0 < file['bytes'] <= 32768 and type(file['excerpt']) is str and type(file['truncated']) is bool, code)
    if 'redacted' in file:
        # These digests identify verified original bytes, never the public mask.
        # Full-source suppression is distinct from a partial, bounded excerpt.
        _require(file['redacted'] is True and file['excerpt'] == REDACTION_MARKER
                 and file['truncated'] is False, code)
        return
    raw = file['excerpt'].encode('utf-8')
    _require(0 < len(raw) <= min(1536, file['bytes']) and len(json.dumps(file['excerpt']).encode()) <= 1800
        and file['truncated'] == (len(raw) < file['bytes']) and '\0' not in file['excerpt']
        and not contains_sensitive_material(file['excerpt']), code)
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
    from runtime.secret_redaction import REDACTION_MARKER, contains_sensitive_material
    # Detect across the complete verified source, including a token split by the
    # excerpt boundary. Suppress the entire field to cover multiline key bodies.
    redacted = contains_sensitive_material(raw.decode('utf-8'))
    excerpt = REDACTION_MARKER if redacted else raw[:1536].decode('utf-8', errors='ignore')
    while len(json.dumps(excerpt).encode()) > 1800: excerpt = excerpt[:-1]
    final = get('/git/ref/heads/main')
    _require(final.get('ref') == ref['ref'] and final.get('object') == obj, 'GITHUB_CONTEXT_BASE_CHANGED')
    data = {'repository': repo, 'repository_id': repo_id, 'url': 'https://github.com/'+repo,
        'branch': 'main', 'commit_sha': commit_sha, 'tree_sha': tree_ref['sha'], 'read_source': 'GITHUB_API',
        'files': [{'path': 'README.md', 'git_blob_sha': blob_sha, 'sha256': hashlib.sha256(raw).hexdigest(),
                  'bytes': len(raw), 'excerpt': excerpt,
                  'truncated': False if redacted else len(excerpt.encode()) < len(raw)}]}
    if redacted:
        data['files'][0]['redacted'] = True
    validate_context_data(operation, data)
    return {'operation': operation, 'data': data, 'transport': 'LIVE_GITHUB_GET'}



RICH_CONTEXT_OPERATIONS = frozenset((
    'github.repository_context', 'github.issue_contexts',
    'github.pull_requests', 'github.actions',
))


def context_inventory():
    tools = []
    for operation in sorted(RICH_CONTEXT_OPERATIONS):
        schema = {'operation': operation, 'arguments': {}, 'repository': REPOSITORY,
                  'repository_id': REPOSITORY_ID, 'per_page': 10, 'page_limit': 2,
                  'output_schema': 'aioa.github-read-context.v2',
                  'text_provenance': 'SOURCE_UTF8_BYTES_SHA256_REDACTION_TRUNCATION_V1'}
        tools.append({'name': operation, 'read_only_hint': True,
                      'schema_sha256': hashlib.sha256(json.dumps(
                          schema, sort_keys=True, separators=(',', ':')).encode()).hexdigest()})
    inventory = {'schema': 'aioa.native-github-read-inventory.v2',
                 'adapter': 'native-fixed-github-get', 'runtime_write_tools': 0,
                 'repository': REPOSITORY, 'repository_id': REPOSITORY_ID,
                 'tools': tools, 'authority': 'NONE'}
    inventory['inventory_sha256'] = hashlib.sha256(json.dumps(
        inventory, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        allow_nan=False).encode()).hexdigest()
    return inventory


def _rich_integer(value, *, maximum=2**63-1, minimum=1):
    _require(type(value) is int and minimum <= value <= maximum, 'GITHUB_CONTEXT_NUMBER')
    return value


def _rich_text(value, maximum, *, nullable=False):
    if value is None and nullable:
        return ''
    _require(type(value) is str and len(value.encode()) <= 32768, 'GITHUB_CONTEXT_TEXT')
    # Use the one stdlib-only policy; optional NonZero models stay unloaded.
    from runtime.secret_redaction import (
        REDACTION_MARKER,
        contains_sensitive_material,
    )
    redacted = REDACTION_MARKER if contains_sensitive_material(value) else value
    return redacted.encode()[:maximum].decode('utf-8', errors='ignore')


def _rich_text_projection(value, maximum, *, nullable=False):
    """Hash original API text before the existing full-mask/UTF-8 byte bound."""
    from runtime.secret_redaction import contains_sensitive_material
    projected = _rich_text(value, maximum, nullable=nullable)
    raw = b'' if value is None else value.encode('utf-8')
    masked = value is not None and contains_sensitive_material(value)
    return projected, {'source_bytes': len(raw), 'source_sha256': hashlib.sha256(raw).hexdigest(),
                       'redacted': masked, 'truncated': not masked and len(raw) > maximum,
                       'null': value is None}


def _validate_text_projection(value, maximum, meta, *, nullable=False):
    """Metadata is signed, untrusted READ data, never an execution authority."""
    from runtime.secret_redaction import REDACTION_MARKER
    code = 'CHAT_READ_DATA_MISMATCH'
    _require(type(meta) is dict and set(meta) == {
        'source_bytes', 'source_sha256', 'redacted', 'truncated', 'null'}, code)
    _require(type(meta['source_bytes']) is int and 0 <= meta['source_bytes'] <= 32768
             and type(meta['source_sha256']) is str
             and re.fullmatch('[a-f0-9]{64}', meta['source_sha256'])
             and all(type(meta[key]) is bool for key in ('redacted', 'truncated', 'null')), code)
    _require(type(value) is str or nullable and value is None, code)
    raw = b'' if value is None else value.encode('utf-8')
    _require(len(raw) <= maximum, code)
    if meta['null']:
        _require(nullable and value in (None, '') and meta['source_bytes'] == 0
                 and meta['source_sha256'] == hashlib.sha256(b'').hexdigest()
                 and not meta['redacted'] and not meta['truncated'], code)
    elif meta['redacted']:
        _require(value == REDACTION_MARKER and meta['source_bytes'] > 0
                 and not meta['truncated'], code)
    else:
        _require(value is not None and meta['truncated'] == (meta['source_bytes'] > maximum), code)
        if meta['truncated']:
            _require(maximum - 3 <= len(raw) <= maximum, code)
        else:
            _require(len(raw) == meta['source_bytes']
                     and hashlib.sha256(raw).hexdigest() == meta['source_sha256'], code)


def _validate_text_provenance(operation, item):
    code = 'CHAT_READ_DATA_MISMATCH'
    meta = item['text_provenance']
    fields = ({'title', 'body', 'labels', 'author'} if operation == 'github.issue_contexts'
              else {'title', 'body'} if operation == 'github.pull_requests' else {'name'})
    _require(type(meta) is dict and set(meta) == fields, code)
    for field, maximum, nullable in (('title', 256, False), ('body', 768, True),
                                     ('author', 64, True), ('name', 256, False)):
        if field in fields:
            _validate_text_projection(item[field], maximum, meta[field], nullable=nullable)
    if 'labels' in fields:
        _require(type(meta['labels']) is list and len(meta['labels']) == len(item['labels']), code)
        for value, provenance in zip(item['labels'], meta['labels'], strict=True):
            _validate_text_projection(value, 64, provenance)


def _rich_repo(value):
    _require(type(value) is dict and type(value.get('id')) is int
             and value['id'] == REPOSITORY_ID and value.get('full_name') == REPOSITORY,
             'GITHUB_REPOSITORY_MISMATCH')


def _rich_sha(value):
    _require(type(value) is str and re.fullmatch('[a-f0-9]{40}', value), 'GITHUB_CONTEXT_SHA')
    return value


def _rich_ref(value, *, nullable=False):
    from runtime.secret_redaction import contains_sensitive_material
    if value is None and nullable:
        return None
    _require(type(value) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9._/-]{0,255}', value)
             and '..' not in value and not value.endswith('/')
             and not contains_sensitive_material(value), 'GITHUB_CONTEXT_REF')
    return value


def _rich_url(value, kind, number):
    expected = 'https://github.com/' + REPOSITORY + '/' + kind + '/' + str(number)
    _require(value == expected, 'GITHUB_CONTEXT_URL')
    return expected


def _rich_issue(row):
    _require(type(row) is dict, 'GITHUB_CONTEXT_ITEM')
    number = _rich_integer(row.get('number'), maximum=2**31-1)
    _require(row.get('state') in ('open', 'closed'), 'GITHUB_CONTEXT_STATE')
    labels = row.get('labels')
    _require(type(labels) is list and len(labels) <= 100, 'GITHUB_CONTEXT_LABELS')
    _require(all(type(label) is dict and type(label.get('name')) is str for label in labels),
             'GITHUB_CONTEXT_LABELS')
    user = row.get('user')
    _require(user is None or type(user) is dict and type(user.get('login')) is str,
             'GITHUB_CONTEXT_AUTHOR')
    title, title_meta = _rich_text_projection(row.get('title'), 256)
    body, body_meta = _rich_text_projection(row.get('body'), 768, nullable=True)
    label_values = [_rich_text_projection(label['name'], 64) for label in labels[:8]]
    author, author_meta = _rich_text_projection(None if user is None else user['login'], 64, nullable=True)
    return {'number': number, 'title': title, 'body': body,
            'state': row['state'].upper(),
            'labels': [value for value, _ in label_values],
            'labels_truncated': len(labels) > 8,
            'author': None if user is None else author,
            'url': _rich_url(row.get('html_url'), 'issues', number),
            'taint': 'REMOTE_UNTRUSTED_DATA',
            'text_provenance': {'title': title_meta, 'body': body_meta,
                                'labels': [meta for _, meta in label_values], 'author': author_meta}}


def _rich_optional_count(value):
    return None if value is None else _rich_integer(value, minimum=0, maximum=10**7)


def _rich_pull(row):
    _require(type(row) is dict and row.get('state') in ('open', 'closed'), 'GITHUB_CONTEXT_STATE')
    number = _rich_integer(row.get('number'), maximum=2**31-1)
    base, head = row.get('base'), row.get('head')
    _require(type(base) is dict and type(head) is dict, 'GITHUB_CONTEXT_ITEM')
    _rich_repo(base.get('repo'))
    merged = row.get('merged_at')
    _require(merged is None or type(merged) is str and row['state'] == 'closed',
             'GITHUB_CONTEXT_STATE')
    title, title_meta = _rich_text_projection(row.get('title'), 256)
    body, body_meta = _rich_text_projection(row.get('body'), 768, nullable=True)
    return {'number': number, 'title': title, 'body': body,
            'state': 'MERGED' if merged is not None else row['state'].upper(),
            'base_ref': _rich_ref(base.get('ref')), 'base_sha': _rich_sha(base.get('sha')),
            'head_ref': _rich_ref(head.get('ref')), 'head_sha': _rich_sha(head.get('sha')),
            'changed_files': _rich_optional_count(row.get('changed_files')),
            'commits': _rich_optional_count(row.get('commits')),
            'checks_summary': '', 'checks_verified': False,
            'url': _rich_url(row.get('html_url'), 'pull', number),
            'taint': 'REMOTE_UNTRUSTED_DATA',
            'text_provenance': {'title': title_meta, 'body': body_meta}}


def _rich_action(row):
    _require(type(row) is dict, 'GITHUB_CONTEXT_ITEM')
    _rich_repo(row.get('repository'))
    number = _rich_integer(row.get('id'))
    workflow = _rich_integer(row.get('workflow_id'))
    _require(row.get('status') in ('queued', 'in_progress', 'completed', 'waiting', 'pending', 'requested'),
             'GITHUB_CONTEXT_STATE')
    _require(row.get('conclusion') in (None, 'success', 'failure', 'neutral', 'cancelled',
                                     'skipped', 'timed_out', 'action_required', 'startup_failure', 'stale'),
             'GITHUB_CONTEXT_STATE')
    name, name_meta = _rich_text_projection(row.get('name'), 256)
    return {'run_id': number, 'workflow_id': str(workflow),
            'name': name, 'status': row['status'],
            'conclusion': row.get('conclusion'), 'head_sha': _rich_sha(row.get('head_sha')),
            'head_branch': _rich_ref(row.get('head_branch'), nullable=True),
            'job_id': None, 'log_context': '', 'logs_fetched': False,
            'core_completion_verified': False,
            'url': _rich_url(row.get('html_url'), 'actions/runs', number),
            'taint': 'REMOTE_UNTRUSTED_DATA', 'text_provenance': {'name': name_meta}}


def _rich_repository_context(operation, check, deadline):
    prefix = 'repos/' + REPOSITORY
    check()
    metadata = _github_json(prefix, check=check, deadline=deadline)
    check()
    _rich_repo(metadata)
    _require(metadata.get('visibility') == 'public', 'GITHUB_CONTEXT_VISIBILITY')
    # Reuse the existing complete-tree/blob verifier. Its bounded file bytes
    # stay private here; rich summaries project only the verified ref/tree.
    base = _repository_context('github.code_context', check, deadline)['data']
    items, seen, pages, truncated = [], set(), 0, False
    kinds = {'github.issue_contexts': ('issues', _rich_issue),
             'github.pull_requests': ('pulls', _rich_pull),
             'github.actions': ('actions/runs', _rich_action)}
    if operation in kinds:
        kind, project = kinds[operation]
        for page in (1, 2):
            query = '' if kind == 'actions/runs' else 'state=all&'
            endpoint = prefix + '/' + kind + '?' + query + 'per_page=10&page=' + str(page)
            check()
            rows = _github_json(endpoint, check=check, deadline=deadline)
            check()
            if kind == 'actions/runs':
                _require(type(rows) is dict, 'GITHUB_CONTEXT_PAGE')
                _rich_integer(rows.get('total_count'), minimum=0)
                rows = rows.get('workflow_runs')
            _require(type(rows) is list and len(rows) <= 10, 'GITHUB_CONTEXT_PAGE')
            pages += 1
            for row in rows:
                _require(type(row) is dict, 'GITHUB_CONTEXT_ITEM')
                number = _rich_integer(row.get('id' if kind == 'actions/runs' else 'number'))
                _require(number not in seen, 'GITHUB_CONTEXT_DUPLICATE')
                seen.add(number)
                if kind == 'issues' and 'pull_request' in row:
                    continue
                items.append(project(row))
            if len(rows) < 10:
                break
            truncated = page == 2
    check()
    final = _github_json(prefix + '/git/ref/heads/main', check=check, deadline=deadline)
    check()
    _require(type(final) is dict and final.get('ref') == 'refs/heads/main'
             and type(final.get('object')) is dict and final['object'].get('type') == 'commit'
             and final['object'].get('sha') == base['commit_sha'], 'GITHUB_CONTEXT_BASE_CHANGED')
    data = {'schema': 'aioa.github-read-context.v2',
            'repository': {'owner': 'luciferprosun', 'name': 'AIOA-spArkHAT',
                           'canonical_url': 'https://github.com/' + REPOSITORY,
                           'repository_id': REPOSITORY_ID},
            'default_branch': 'main', 'requested_ref': 'main',
            'observed_sha': base['commit_sha'], 'tree_sha': base['tree_sha'],
            'visibility': 'public', 'taint': 'REMOTE_UNTRUSTED_DATA', 'authority': 'NONE',
            'items': items, 'pagination': {'per_page': 10, 'page_limit': 2,
                                         'pages_read': pages, 'truncated': truncated}}
    _require(len(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()) <= 32768,
             'GITHUB_CONTEXT_OUTPUT_LIMIT')
    _validate_rich_context_data(operation, data)
    return {'operation': operation, 'data': data, 'transport': 'LIVE_GITHUB_GET'}


OPERATIONS = OPERATIONS | RICH_CONTEXT_OPERATIONS
VERIFIED_CONTEXT_OPERATIONS = frozenset((*CONTEXT_REPOSITORIES, *RICH_CONTEXT_OPERATIONS))


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
    if operation in RICH_CONTEXT_OPERATIONS:
        return _rich_repository_context(operation, check, deadline)
    if operation in CONTEXT_REPOSITORIES:
        return _repository_context(operation, check, deadline)
    if operation.startswith('github.'):
        _repo, branch = _repository(check, deadline)
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
                    issues.append({'number': row['number'], 'title': _rich_text(row['title'], 4096), 'state': row['state'], 'url': url})
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
    return {'operation': operation, 'data': {'text': _rich_text(output.decode('utf-8', 'replace'), 32768)}, 'transport': 'LOCAL_GIT_READ'}
