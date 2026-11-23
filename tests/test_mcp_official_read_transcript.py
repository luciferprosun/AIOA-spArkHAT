"""Offline JSON-RPC envelope for the W7A synthetic MCP READ contract.

Fixture shapes adapted from the MIT-licensed W7A test
392487849eddc7444f5159994b66b72e73f15934:tests/unit/test_github_mcp_read_plane.py
(Git blob c893fe5bc63fbf6c635583803fc0836896a4ffc8). Repo ID, modern HEAD,
JSON-RPC envelopes and repeat-ref check are additions in this synthetic fixture.
"""

import unittest

from runtime.mcp_bridge.native_read import (
    REPOSITORY,
    REPOSITORY_ID,
    validate_context_data,
)
from runtime.mobile_gateway.wire import RESPONSE_LIMIT, canonical, digest, strict_json

PROTOCOL = '2025-06-18'
PINNED_HEAD = '914c9b1bf4dc7bf6ff14687d91560d9bcef1a5f6'
TOOLS = frozenset(('actions_list', 'list_branches', 'list_issues', 'list_pull_requests', 'search_repositories'))
OWNER, NAME = REPOSITORY.split('/')
SEARCH = {'query': f'repo:{REPOSITORY}', 'minimal_output': False, 'perPage': 5}
BRANCHES = {'owner': OWNER, 'repo': NAME, 'perPage': 100}
IDENTITY = {'name': 'github-mcp-server', 'version': '1.0.5'}


def request(identity, method, params):
    return {'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params}


def response(identity, result):
    return {'jsonrpc': '2.0', 'id': identity, 'result': result}


def result(payload):
    return {'structuredContent': {'result': payload}}


def fixture_frames():
    tools = [{'name': name, 'inputSchema': {'type': 'object', 'additionalProperties': False},
              'annotations': {'readOnlyHint': True}} for name in sorted(TOOLS)]
    repo = {'items': [{'id': REPOSITORY_ID, 'full_name': REPOSITORY, 'default_branch': 'main',
                       'private': False, 'html_url': f'https://github.com/{REPOSITORY}'}]}
    return [
        request(1, 'initialize', {'protocolVersion': PROTOCOL}),
        response(1, {'protocolVersion': PROTOCOL, 'serverInfo': dict(IDENTITY)}),
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        request(2, 'tools/list', {}), response(2, {'tools': tools}),
        request(3, 'tools/call', {'name': 'search_repositories', 'arguments': dict(SEARCH)}),
        response(3, result(repo)),
        request(4, 'tools/call', {'name': 'list_branches', 'arguments': dict(BRANCHES)}),
        response(4, result([{'name': 'main', 'sha': PINNED_HEAD}])),
        request(5, 'tools/call', {'name': 'list_branches', 'arguments': dict(BRANCHES)}),
        response(5, result([{'name': 'main', 'sha': PINNED_HEAD}])),
    ]


class OfficialMcpReadTranscriptTests(unittest.TestCase):
    def verify_fixture(self, raw):
        self.assertTrue(raw.endswith(b'\n'))
        self.assertLessEqual(len(raw), 262144)
        frames = [strict_json(line, limit=RESPONSE_LIMIT) for line in raw.splitlines()]
        self.assertEqual(11, len(frames))
        self.assertEqual(request(1, 'initialize', {'protocolVersion': PROTOCOL}), frames[0])
        self.assertEqual({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, frames[2])
        self.assertEqual(request(2, 'tools/list', {}), frames[3])
        self.assertEqual(request(3, 'tools/call', {'name': 'search_repositories', 'arguments': SEARCH}), frames[5])
        for identity, offset in ((4, 7), (5, 9)):
            self.assertEqual(request(identity, 'tools/call', {'name': 'list_branches', 'arguments': BRANCHES}), frames[offset])
        for identity, offset in enumerate((1, 4, 6, 8, 10), 1):
            for message in (frames[offset], frames[offset - 1]):
                self.assertIs(type(message['id']), int)
            self.assertEqual(response(identity, frames[offset]['result']), frames[offset])
        self.assertEqual({'protocolVersion': PROTOCOL, 'serverInfo': IDENTITY}, frames[1]['result'])
        inventory = frames[4]['result']
        self.assertEqual({'tools'}, set(inventory))
        self.assertEqual(sorted(TOOLS), sorted(tool['name'] for tool in inventory['tools']))
        for tool in inventory['tools']:
            self.assertIs(tool['annotations']['readOnlyHint'], True)
        first = frames[8]['result']
        self.assertEqual(first, frames[10]['result'])
        self.assertEqual(result([{'name': 'main', 'sha': PINNED_HEAD}]), first)
        repo, = frames[6]['result']['structuredContent']['result']['items']
        self.assertIs(repo['private'], False)
        projection = {'repository': repo['full_name'], 'repository_id': repo['id'],
                      'url': repo['html_url'], 'branch': repo['default_branch'], 'commit_sha': PINNED_HEAD}
        validate_context_data('github.repository', projection)
        return {'transport': 'OFFICIAL_MCP_READ_FIXTURE', 'authority': 'NONE', 'live_verified': False,
                'transcript_sha256': digest(raw), 'projection_sha256': digest(canonical(projection))}

    def encode(self, frames):
        return b''.join(canonical(frame) + b'\n' for frame in frames)

    def test_archived_fixture_shape_reaches_current_inert_core_projection(self):
        raw = self.encode(fixture_frames())
        observation = self.verify_fixture(raw)
        self.assertEqual(('OFFICIAL_MCP_READ_FIXTURE', 'NONE', False), (
            observation['transport'], observation['authority'], observation['live_verified']))
        self.assertEqual(digest(raw), observation['transcript_sha256'])

    def test_refuses_mismatched_peer_inventory_scope_and_ref(self):
        for offset, change in (
            (1, lambda frame: frame['result']['serverInfo'].update(name='untrusted')),
            (4, lambda frame: frame['result']['tools'][0]['annotations'].update(readOnlyHint=False)),
            (4, lambda frame: frame['result']['tools'].append(frame['result']['tools'][0])),
            (5, lambda frame: frame['params'].update(name='write_tool')),
            (6, lambda frame: frame.update(id=True)),
            (6, lambda frame: frame.update(id=2)),
            (6, lambda frame: frame['result']['structuredContent']['result']['items'][0].update(id=1)),
            (10, lambda frame: frame['result']['structuredContent']['result'][0].update(sha='f' * 40)),
        ):
            with self.subTest(offset=offset), self.assertRaises((AssertionError, ValueError)):
                frames = fixture_frames()
                change(frames[offset])
                self.verify_fixture(self.encode(frames))

    def test_current_wire_decoder_denies_noncanonical_response_frames(self):
        for first in (b'{"jsonrpc":"2.0","jsonrpc":"1.0"}', b'{"id":1.0}', b'{"text":"\xff"}'):
            with self.subTest(frame=first), self.assertRaises(ValueError):
                self.verify_fixture(first + b'\n' + self.encode(fixture_frames()[1:]))
