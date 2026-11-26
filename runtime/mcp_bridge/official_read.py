"""One fixed official GitHub MCP observation for the Native owner qualification.

The client speaks line-delimited MCP over stdio. Operator admission, pending
reservation, signing and idempotent readback belong to the existing Native Core.
"""
import fcntl
import hashlib
import os
import re
import select
import stat
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from runtime.mcp_bridge.native_read import REPOSITORY, REPOSITORY_ID, _remaining, _require
from runtime.mobile_gateway import wire
from runtime.secret_redaction import contains_sensitive_material

OPERATION = 'github.official_mcp_license'
TARGET = 'd2870f33bb740184f7c2a18a7ea8f90b070fbd64'
TREE = '569f5591b2be0ae34c81701a3a54ea46e018c411'
BLOB = '00eb8a94bdcf22d647d94e23c9c6938ef93d5802'
CONTENT = 'a039f83d1d59d97624c355653e0eab74a45b867a091d3d10d12ac1183535e14c'
BINARY = 'e38247271e98ea3e0771db747523914b35e37787fa2c120ab6864ee6b4a2c87c'
BUILD = 'c471ae94bb04059dc26e12c305e219c8fd4299e4'
INVENTORY = '243b05c2f6ed9a7c600e503c827bfeb12b2c59f700443acbe8cb405b08dfbccc'
PROTOCOL = '2025-06-18'
REQUEST_ID = wire.digest((OPERATION + ':' + TARGET).encode())[:32]
TRANSPORT = 'OFFICIAL_GITHUB_MCP_STDIO'
TOOLS = ('get_file_contents', 'search_repositories')
URI = f'repo://{REPOSITORY}/sha/{TARGET}/contents/LICENSE'
SCOPE = 'one-repository/contents:read,metadata:read'
BUDGET = {'seconds': 20, 'sessions': 1, 'transport_bytes': 262144, 'frame_bytes': 65536,
          'receipt_bytes': 32768, 'inventory_pages': 2, 'max_reads': 5, 'writes': 0,
          'retries': 0, 'fallbacks': 0}


def _git(root, *args):
    # Both source identity and the target tree are local immutable Git proofs.
    return subprocess.check_output(
        ['/usr/bin/git', '--no-replace-objects', '-C', str(root), *args], timeout=3,
        env={'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'GIT_CONFIG_NOSYSTEM': '1',
             'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_NO_LAZY_FETCH': '1', 'GIT_ALLOW_PROTOCOL': ''},
        stderr=subprocess.DEVNULL)


def _source_tree(root, source):
    from runtime.meta_hackathon.runtime_adapter import SOURCE_FILES, sealed_source_path

    _require(wire.SHA40.fullmatch(source) and _git(root, 'rev-parse', 'HEAD').decode().strip() == source,
             'OFFICIAL_MCP_SOURCE')
    records = _git(root, 'ls-tree', '-rz', source, '--', *SOURCE_FILES).split(b'\0')
    remaining = set(SOURCE_FILES)
    for record in records[:-1]:
        header, name = record.split(b'\t', 1)
        mode, kind, oid = header.split()
        relative = name.decode()
        raw = sealed_source_path(relative, root=root).read_bytes()
        _require(relative in remaining and kind == b'blob' and mode in (b'100644', b'100755')
                 and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == oid.decode(),
                 'OFFICIAL_MCP_SOURCE')
        remaining.remove(relative)
    _require(not remaining, 'OFFICIAL_MCP_SOURCE')
    tree, target_tree, blob = _git(root, 'rev-parse', source+'^{tree}', TARGET+'^{tree}',
                                   TARGET+':LICENSE').decode().splitlines()
    _require(target_tree == TREE and blob == BLOB, 'OFFICIAL_MCP_TARGET')
    return tree


def private_dir(host):
    directory = host.root / 'official-mcp-read'
    info = directory.lstat()
    _require(directory.resolve() == directory and stat.S_ISDIR(info.st_mode)
             and info.st_uid == host.uid and stat.S_IMODE(info.st_mode) == 0o700,
             'OFFICIAL_MCP_PRIVATE_DIRECTORY')
    return directory


def manifest(host):
    from runtime.meta_hackathon.native_authority import _private_bytes
    from runtime.meta_hackathon.runtime_adapter import ROOT

    _require(host._existing_profile is not None, 'OFFICIAL_MCP_EXISTING_CORE_REQUIRED')
    directory = private_dir(host)
    settings = wire.strict_json(_private_bytes(str(directory/'window.json'), 4096))
    _require(set(settings) == {'credential_id', 'credential_sha256', 'credential_scope',
                              'starts_at', 'expires_at'} and settings['credential_scope'] == SCOPE
             and isinstance(settings['credential_id'], str)
             and re.fullmatch('[0-9]{1,24}', settings['credential_id'])
             and isinstance(settings['credential_sha256'], str)
             and wire.HEX64.fullmatch(settings['credential_sha256']), 'OFFICIAL_MCP_CREDENTIAL_BINDING')
    start, end = settings['starts_at'], settings['expires_at']
    _require(type(start) is int and type(end) is int and 0 < end-start <= 1800,
             'OFFICIAL_MCP_WINDOW')
    return {'schema': 'aioa.official-mcp-read-permit.v1', 'command': 'GO_OFFICIAL_MCP_READ',
            'request_id': REQUEST_ID, 'owner_scope': host.mobile.owner_scope_digest,
            'operator_uid': host.uid, 'hostname_sha256': wire.digest(os.uname().nodename.encode()),
            'source_sha': host.source[0], 'source_tree': _source_tree(ROOT, host.source[0]),
            'capsule_digest': host.source[1], 'host_key_id': host.identity.audience,
            'grant_core_instance_id': host.instance_id,
            'admission_revision': host.operator_principal().assignment_revision,
            'client_sha256': wire.digest(Path(__file__).read_bytes()),
            'repo': REPOSITORY, 'repository_id': REPOSITORY_ID, 'target_commit': TARGET,
            'target_tree_local_git': TREE, 'file': 'LICENSE', 'blob': BLOB, 'bytes': 1074,
            'content_sha256': CONTENT, 'server': 'github/github-mcp-server@1.0.5',
            'server_commit': BUILD, 'server_binary_sha256': BINARY, 'protocol': PROTOCOL,
            'tools': list(TOOLS), 'inventory_sha256': INVENTORY, 'budget': dict(BUDGET),
            'private_proof': 'official-mcp-read/'+REQUEST_ID+'.stdio', **settings}


def check_window(value):
    _require(value['starts_at'] <= int(time.time()) < value['expires_at'], 'OFFICIAL_MCP_WINDOW')


def validate_authorization(host, approval):
    _require(type(approval) is dict and set(approval) == {'permit', 'signature'},
             'OFFICIAL_MCP_SIGNED_AUTHORIZATION_REQUIRED')
    wire.verify(host.identity.spki, approval['signature'], approval['permit'])
    current = manifest(host)
    _require(wire.canonical(approval['permit']) == wire.canonical(current),
             'OFFICIAL_MCP_PERMIT_CHANGED')
    check_window(current)
    return current


class Channel:
    def __init__(self, child, deadline, check):
        self.child, self.deadline, self.check = child, deadline, check
        self.pending = b''
        self.transcript = bytearray()
        self.sequence = 0
        self.reads = 0
        os.set_blocking(child.stdin.fileno(), False)
        os.set_blocking(child.stdout.fileno(), False)

    def record(self, raw):
        _require(len(self.transcript)+len(raw) <= BUDGET['transport_bytes'], 'OFFICIAL_MCP_BYTE_LIMIT')
        self.transcript.extend(raw)

    def send(self, obj):
        self.check()
        raw = wire.canonical({'jsonrpc': '2.0', **obj}) + b'\n'
        _require(len(raw) <= BUDGET['frame_bytes'], 'OFFICIAL_MCP_FRAME_LIMIT')
        self.record(raw)
        fd = self.child.stdin.fileno()
        while raw:
            _require(select.select([], [fd], [], _remaining(self.deadline))[1], 'TOOL_READ_TIMEOUT')
            size = os.write(fd, raw)
            _require(size > 0, 'OFFICIAL_MCP_PIPE')
            raw = raw[size:]

    def rpc(self, method, params):
        self.sequence += 1
        self.send({'id': self.sequence, 'method': method, 'params': params})
        fd = self.child.stdout.fileno()
        while b'\n' not in self.pending:
            _require(select.select([fd], [], [], _remaining(self.deadline))[0], 'TOOL_READ_TIMEOUT')
            room = BUDGET['frame_bytes'] - len(self.pending)
            _require(room > 0, 'OFFICIAL_MCP_FRAME_LIMIT')
            available = BUDGET['transport_bytes'] - len(self.transcript)
            _require(available > 0, 'OFFICIAL_MCP_BYTE_LIMIT')
            data = os.read(fd, min(room, available, 16384))
            _require(data, 'OFFICIAL_MCP_EOF')
            self.record(data)
            self.pending += data
        line, self.pending = self.pending.split(b'\n', 1)
        result = wire.strict_json(line, limit=wire.RESPONSE_LIMIT)
        _require(set(result) == {'jsonrpc', 'id', 'result'} and result['jsonrpc'] == '2.0'
                 and type(result['id']) is int and result['id'] == self.sequence
                 and type(result['result']) is dict and not self.pending, 'OFFICIAL_MCP_REPLY')
        _remaining(self.deadline)
        return result['result']


def arguments(tool):
    if tool == 'search_repositories':
        return {'query': 'repo:'+REPOSITORY, 'minimal_output': True, 'perPage': 1}
    if tool == 'get_file_contents':
        owner, repo = REPOSITORY.split('/')
        return {'owner': owner, 'repo': repo, 'path': 'LICENSE', 'sha': TARGET}
    raise ValueError('OFFICIAL_MCP_TOOL_DENIED')


def _blocks(channel, name):
    args = arguments(name)
    _require(channel.reads < BUDGET['max_reads'], 'OFFICIAL_MCP_READ_LIMIT')
    channel.reads += 1
    result = channel.rpc('tools/call', {'name': name, 'arguments': args})
    _require(set(result) <= {'content', 'isError'} and result.get('isError', False) is False
             and type(result.get('content')) is list, 'OFFICIAL_MCP_TOOL_ERROR')
    return result['content']


def observe(channel):
    handshake = channel.rpc('initialize', {'protocolVersion': PROTOCOL, 'capabilities': {},
                            'clientInfo': {'name': 'aioa-native', 'version': '1'}})
    peer = handshake.get('serverInfo', {})
    _require(handshake.get('protocolVersion') == PROTOCOL and peer.get('name') == 'github-mcp-server'
             and peer.get('version') == '1.0.5' and type(handshake.get('capabilities', {}).get('tools')) is dict,
             'OFFICIAL_MCP_HANDSHAKE')
    channel.send({'method': 'notifications/initialized'})
    cursor = None
    tools = []
    for _ in range(BUDGET['inventory_pages']):
        page = channel.rpc('tools/list', {} if cursor is None else {'cursor': cursor})
        _require(set(page) <= {'tools', 'nextCursor'} and type(page.get('tools')) is list,
                 'OFFICIAL_MCP_INVENTORY')
        tools.extend(page['tools'])
        cursor = page.get('nextCursor')
        if cursor is None:
            break
        _require(type(cursor) is str and 0 < len(cursor) <= 512, 'OFFICIAL_MCP_INVENTORY')
    ordered = sorted(tools, key=lambda t: t['name'])
    _require(cursor is None and [t['name'] for t in ordered] == list(TOOLS)
             and wire.digest(wire.canonical(ordered)) == INVENTORY, 'OFFICIAL_MCP_INVENTORY')
    # Exercise the same local dispatch deny path before transmitting any tool call.
    try:
        _blocks(channel, 'create_pull_request')
    except ValueError as error:
        if error.args != ('OFFICIAL_MCP_TOOL_DENIED',):
            raise
    else:
        raise ValueError('OFFICIAL_MCP_WRITE_GATE')
    found, = _blocks(channel, 'search_repositories')
    _require(found['type'] == 'text', 'OFFICIAL_MCP_REPOSITORY')
    result = wire.strict_json(found['text'].encode(), limit=wire.RESPONSE_LIMIT)
    _require(type(result.get('total_count')) is int and result['total_count'] == 1
             and result.get('incomplete_results') is False and len(result['items']) == 1,
             'OFFICIAL_MCP_REPOSITORY')
    repo = result['items'][0]
    _require(type(repo.get('id')) is int and repo['id'] == REPOSITORY_ID
             and repo.get('full_name') == REPOSITORY and repo.get('private') is False
             and repo.get('html_url') == 'https://github.com/'+REPOSITORY, 'OFFICIAL_MCP_REPOSITORY')
    status, item = _blocks(channel, 'get_file_contents')
    _require(status == {'type': 'text', 'text': f'successfully downloaded text file (SHA: {BLOB})'}
             and item['type'] == 'resource', 'OFFICIAL_MCP_FILE')
    resource = item['resource']
    _require(resource['uri'] == URI and resource['mimeType'] == 'text/plain; charset=utf-8',
             'OFFICIAL_MCP_FILE')
    content = resource['text'].encode()
    _require(len(content) == 1074 and wire.digest(content) == CONTENT
             and hashlib.sha1(b'blob 1074\0'+content).hexdigest() == BLOB, 'OFFICIAL_MCP_FILE')
    return {'repository_id': REPOSITORY_ID, 'uri': URI, 'blob': BLOB, 'bytes': len(content),
            'content_sha256': CONTENT, 'reads': channel.reads, 'writes': 0, 'local_write_denial': True,
            'inventory_sha256': INVENTORY, 'taint': 'REMOTE_UNTRUSTED_DATA', 'authority': 'NONE'}


@contextmanager
def sealed_server(directory):
    # Pin exactly the bytes that will execute, including across a later rename.
    source = os.open(directory/'github-mcp-server', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    fd = None
    try:
        info = os.fstat(source)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                 and not info.st_mode & 0o7077 and 0 < info.st_size <= 32 * 1024 * 1024,
                 'OFFICIAL_MCP_BINARY_TYPE')
        fd = os.memfd_create('aioa-official-mcp', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        digest = hashlib.sha256()
        remain = info.st_size
        with os.fdopen(os.dup(fd), 'wb') as stream:
            while remain:
                raw = os.read(source, min(remain, 131072))
                _require(raw, 'OFFICIAL_MCP_BINARY_CHANGED')
                remain -= len(raw)
                digest.update(raw)
                stream.write(raw)
        _require(not os.read(source, 1) and digest.hexdigest() == BINARY,
                 'OFFICIAL_MCP_BINARY_CHANGED')
        os.fchmod(fd, 0o500)
        fcntl.fcntl(fd, 1033, 15)
        _require(fcntl.fcntl(fd, 1034) & 15 == 15, 'OFFICIAL_MCP_BINARY_UNSEALED')
        yield fd
    finally:
        os.close(source)
        if fd is not None:
            os.close(fd)


def _read_token(directory, permit):
    from runtime.meta_hackathon.native_authority import _private_bytes

    token = _private_bytes(str(directory/'read-token'), 512).rstrip(b'\n')
    _require(re.fullmatch(rb'github_pat_[A-Za-z0-9_]{25,255}', token)
             and wire.digest(token) == permit['credential_sha256'], 'OFFICIAL_MCP_CREDENTIAL_CHANGED')
    return token


def preflight(host, permit):
    directory = private_dir(host)
    _read_token(directory, permit)
    with sealed_server(directory):
        _require(not os.path.lexists(directory / (REQUEST_ID+'.stdio')),
                 'OFFICIAL_MCP_READBACK_REQUIRED')


def run(host, approval, deadline):
    directory = private_dir(host)
    permit = approval['permit']

    def check():
        host._require_qualified_operator()
        check_window(permit)

    token = _read_token(directory, permit)
    with sealed_server(directory) as fd:
        check()
        _remaining(deadline)
        evidence = directory / (REQUEST_ID+'.stdio')
        # Exclusive capture also prevents a second session with this same evidence destination.
        trace_fd = os.open(evidence, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(trace_fd, 'wb') as trace:
            child = subprocess.Popen(
                [f'/proc/self/fd/{fd}', 'stdio', '--read-only', '--tools', ','.join(TOOLS)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=directory, env={'HOME': '/nonexistent', 'LANG': 'C.UTF-8',
                                      'GITHUB_PERSONAL_ACCESS_TOKEN': token.decode('ascii')},
                pass_fds=(fd,), start_new_session=True)
            channel = Channel(child, deadline, check)
            complete = False
            try:
                try:
                    data = observe(channel)
                except (KeyError, TypeError, IndexError, AttributeError):
                    raise ValueError('OFFICIAL_MCP_REPLY_SHAPE') from None
                child.stdin.close()
                _require(child.wait(timeout=_remaining(deadline)) == 0, 'OFFICIAL_MCP_EXIT')
                _require(not os.read(child.stdout.fileno(), 1), 'OFFICIAL_MCP_EXTRA_OUTPUT')
                complete = True
            except subprocess.TimeoutExpired:
                raise ValueError('TOOL_READ_TIMEOUT') from None
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait()
                child.stdin.close()
                child.stdout.close()
                # Only validated public responses can be retained raw. On a protocol
                # failure keep a bounded byte count and hash without untrusted text.
                raw = bytes(channel.transcript)
                safe = (complete and token not in raw
                        and not contains_sensitive_material(raw.decode('utf-8', 'replace')))
                trace.write(raw if safe else wire.canonical({'bytes':len(raw),'sha256':wire.digest(raw)}))
                trace.flush()
                os.fsync(trace.fileno())
    dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    _require(safe, 'OFFICIAL_MCP_TRANSCRIPT_DENIED')
    return {'transport': TRANSPORT, 'data': {**data, 'permit': permit,
            'permit_signature': approval['signature'], 'transcript_bytes': len(raw),
            'transcript_sha256': wire.digest(raw)}}
