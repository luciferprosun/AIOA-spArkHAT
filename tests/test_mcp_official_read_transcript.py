"""Synthetic offline transcript for the official GitHub MCP v1.0.5 READ subset.

The handshake and inventory fixture adapt the MIT-licensed W7A test
392487849eddc7444f5159994b66b72e73f15934:tests/unit/test_github_mcp_read_plane.py
(Git blob c893fe5bc63fbf6c635583803fc0836896a4ffc8). Tool response shapes follow
github/github-mcp-server commit c471ae94bb04059dc26e12c305e219c8fd4299e4,
pkg/github/{search,repositories,minimal_types,repository_resource}.go and
pkg/utils/result.go. The fixture uses no server, credentials or network.
"""

from pathlib import Path
import unittest

from runtime.mcp_bridge.native_read import (
    REPOSITORY,
    REPOSITORY_ID,
    validate_context_data,
)
from runtime.mobile_gateway.wire import RESPONSE_LIMIT, canonical, digest, strict_json
from runtime.mission.git_recipe import git_object

PROTOCOL = '2025-06-18'
PINNED_HEAD = '8bd2fe14033f1b49609092a353cd7e6fd6b8d3ef'
LICENSE_BLOB = '00eb8a94bdcf22d647d94e23c9c6938ef93d5802'
LICENSE_DIGEST = 'a039f83d1d59d97624c355653e0eab74a45b867a091d3d10d12ac1183535e14c'
LICENSE_BYTES = 1074
LICENSE_URI = f'repo://{REPOSITORY}/sha/{PINNED_HEAD}/contents/LICENSE'
# The W7A inventory sample plus the file tool used in this fixture.
TOOLS = frozenset(('actions_list', 'get_file_contents', 'list_branches', 'list_issues',
                   'list_pull_requests', 'search_repositories'))
OWNER, NAME = REPOSITORY.split('/')
SEARCH = {'query': f'repo:{REPOSITORY}', 'minimal_output': True, 'perPage': 5}
BRANCHES = {'owner': OWNER, 'repo': NAME, 'perPage': 100}
LICENSE_READ = {'owner': OWNER, 'repo': NAME, 'path': 'LICENSE', 'sha': PINNED_HEAD}
IDENTITY = {'name': 'github-mcp-server', 'version': '1.0.5'}
INITIALIZE = {'protocolVersion': PROTOCOL, 'capabilities': {},
              'clientInfo': {'name': 'aioa-offline-fixture', 'version': '1'}}


def request(identity, method, params):
    return {'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params}


def response(identity, result):
    return {'jsonrpc': '2.0', 'id': identity, 'result': result}


def text_result(payload):
    return {'content': [{'type': 'text', 'text': canonical(payload).decode('utf-8')}]}


def tool_descriptor(name):
    return {'name': name, 'inputSchema': {'type': 'object', 'additionalProperties': False},
            'annotations': {'readOnlyHint': True}}


def fixture_frames():
    tools = [tool_descriptor(name) for name in sorted(TOOLS)]
    repository = {
        'id': REPOSITORY_ID, 'name': NAME, 'full_name': REPOSITORY,
        'default_branch': 'main', 'html_url': f'https://github.com/{REPOSITORY}',
        'stargazers_count': 0, 'forks_count': 0, 'open_issues_count': 0,
        'private': False, 'archived': False, 'fork': False,
    }
    branches = [{'name': 'main', 'sha': PINNED_HEAD, 'protected': True}]
    license_text = Path(__file__).resolve().parents[1].joinpath('LICENSE').read_bytes().decode('utf-8')
    license_result = {'content': [
        {'type': 'text', 'text': f'successfully downloaded text file (SHA: {LICENSE_BLOB})'},
        {'type': 'resource', 'resource': {
            'uri': LICENSE_URI, 'mimeType': 'text/plain; charset=utf-8', 'text': license_text,
        }},
    ]}
    return [
        request(1, 'initialize', INITIALIZE),
        # Minimal synthetic server capabilities for the selected tool session.
        response(1, {'protocolVersion': PROTOCOL, 'serverInfo': dict(IDENTITY),
                     'capabilities': {'tools': {}}}),
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        request(2, 'tools/list', {}), response(2, {'tools': tools}),
        request(3, 'tools/call', {'name': 'search_repositories', 'arguments': dict(SEARCH)}),
        response(3, text_result({'total_count': 1, 'incomplete_results': False, 'items': [repository]})),
        request(4, 'tools/call', {'name': 'list_branches', 'arguments': dict(BRANCHES)}),
        response(4, text_result(branches)),
        request(5, 'tools/call', {'name': 'get_file_contents', 'arguments': dict(LICENSE_READ)}),
        response(5, license_result),
        request(6, 'tools/call', {'name': 'list_branches', 'arguments': dict(BRANCHES)}),
        response(6, text_result(branches)),
    ]


class OfficialMcpReadTranscriptTests(unittest.TestCase):
    def result_blocks(self, result, count):
        self.assertIs(type(result), dict)
        self.assertIn(set(result), ({'content'}, {'content', 'isError'}))
        self.assertIs(result.get('isError', False), False)
        self.assertIs(type(result['content']), list)
        self.assertEqual(count, len(result['content']))
        return result['content']

    def text_block(self, block):
        self.assertIs(type(block), dict)
        self.assertEqual({'type', 'text'}, set(block))
        self.assertEqual('text', block['type'])
        self.assertIs(type(block['text']), str)
        return block['text']

    def text_payload(self, result):
        block, = self.result_blocks(result, 1)
        raw = self.text_block(block).encode('utf-8')
        # The Core decoder expects an object, even for an embedded branch array.
        decoded = strict_json(b'{"payload":' + raw + b'}', limit=RESPONSE_LIMIT)
        self.assertEqual({'payload'}, set(decoded))
        return decoded['payload']

    def verify_license(self, result):
        status, block = self.result_blocks(result, 2)
        self.assertEqual(f'successfully downloaded text file (SHA: {LICENSE_BLOB})', self.text_block(status))
        self.assertIs(type(block), dict)
        self.assertEqual({'type', 'resource'}, set(block))
        self.assertEqual('resource', block['type'])
        resource = block['resource']
        self.assertIs(type(resource), dict)
        self.assertEqual({'uri', 'mimeType', 'text'}, set(resource))
        self.assertEqual(LICENSE_URI, resource['uri'])
        self.assertEqual('text/plain; charset=utf-8', resource['mimeType'])
        self.assertIs(type(resource['text']), str)
        raw = resource['text'].encode('utf-8')
        proof = {'uri': resource['uri'], 'bytes': len(raw), 'git_blob': git_object('blob', raw),
                 'sha256': digest(raw)}
        self.assertEqual((LICENSE_BYTES, LICENSE_BLOB, LICENSE_DIGEST),
                         (proof['bytes'], proof['git_blob'], proof['sha256']))
        return proof

    def verify_fixture(self, raw):
        self.assertTrue(raw.endswith(b'\n'))
        self.assertLessEqual(len(raw), 262144)
        frames = [strict_json(line, limit=RESPONSE_LIMIT) for line in raw.splitlines()]
        self.assertEqual(13, len(frames))
        self.assertEqual(request(1, 'initialize', INITIALIZE), frames[0])
        self.assertEqual({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, frames[2])
        self.assertEqual(request(2, 'tools/list', {}), frames[3])
        calls = (('search_repositories', SEARCH), ('list_branches', BRANCHES),
                 ('get_file_contents', LICENSE_READ), ('list_branches', BRANCHES))
        for identity, (name, arguments) in enumerate(calls, 3):
            self.assertEqual(request(identity, 'tools/call', {'name': name, 'arguments': arguments}),
                             frames[2 * identity - 1])
        for identity, offset in enumerate((1, 4, 6, 8, 10, 12), 1):
            for message in (frames[offset], frames[offset - 1]):
                self.assertIs(type(message['id']), int)
            self.assertEqual(response(identity, frames[offset]['result']), frames[offset])
        self.assertEqual({'protocolVersion': PROTOCOL, 'serverInfo': IDENTITY,
                          'capabilities': {'tools': {}}}, frames[1]['result'])
        inventory = frames[4]['result']
        self.assertEqual({'tools'}, set(inventory))
        self.assertEqual(sorted(TOOLS), sorted(tool['name'] for tool in inventory['tools']))
        for tool in inventory['tools']:
            self.assertIs(tool['annotations']['readOnlyHint'], True)
            self.assertEqual(tool_descriptor(tool['name']), tool)
        first = self.text_payload(frames[8]['result'])
        last = self.text_payload(frames[12]['result'])
        self.assertEqual([{'name': 'main', 'sha': PINNED_HEAD, 'protected': True}], first)
        self.assertEqual(first, last)
        self.assertIs(first[0]['protected'], True)
        self.assertIs(last[0]['protected'], True)
        payload = self.text_payload(frames[6]['result'])
        self.assertIs(type(payload), dict)
        self.assertEqual({'total_count', 'incomplete_results', 'items'}, set(payload))
        self.assertIs(type(payload['total_count']), int)
        self.assertEqual(1, payload['total_count'])
        self.assertIs(payload['incomplete_results'], False)
        self.assertIs(type(payload['items']), list)
        self.assertEqual(1, len(payload['items']))
        repo = payload['items'][0]
        self.assertIs(type(repo), dict)
        self.assertEqual({'id', 'name', 'full_name', 'default_branch', 'html_url', 'stargazers_count',
                          'forks_count', 'open_issues_count', 'private', 'archived', 'fork'}, set(repo))
        self.assertEqual(NAME, repo['name'])
        self.assertIs(repo['private'], False)
        self.assertIs(repo['archived'], False)
        self.assertIs(repo['fork'], False)
        projection = {'repository': repo['full_name'], 'repository_id': repo['id'],
                      'url': repo['html_url'], 'branch': repo['default_branch'], 'commit_sha': first[0]['sha']}
        validate_context_data('github.repository', projection)
        return {'transport': 'OFFICIAL_MCP_READ_FIXTURE', 'authority': 'NONE', 'live_verified': False,
                'live_status': 'NOT_RUN',
                'transcript_sha256': digest(raw), 'projection_sha256': digest(canonical(projection)),
                'license': self.verify_license(frames[10]['result'])}

    def encode(self, frames):
        return b''.join(canonical(frame) + b'\n' for frame in frames)

    def test_upstream_text_results_reach_current_inert_core_projection(self):
        raw = self.encode(fixture_frames())
        observation = self.verify_fixture(raw)
        self.assertEqual(('OFFICIAL_MCP_READ_FIXTURE', 'NONE', False, 'NOT_RUN'), (
            observation['transport'], observation['authority'], observation['live_verified'],
            observation['live_status']))
        self.assertEqual(digest(raw), observation['transcript_sha256'])

    def test_v105_embedded_license_is_bound_to_the_pinned_public_file(self):
        frames = fixture_frames()
        calls = [frame['params']['name'] for frame in frames if frame.get('method') == 'tools/call']
        self.assertIn('get_file_contents', calls)
        observation = self.verify_fixture(self.encode(frames))
        self.assertEqual({
            'uri': 'repo://luciferprosun/AIOA-spArkHAT/sha/8bd2fe14033f1b49609092a353cd7e6fd6b8d3ef/contents/LICENSE',
            'bytes': 1074,
            'git_blob': '00eb8a94bdcf22d647d94e23c9c6938ef93d5802',
            'sha256': 'a039f83d1d59d97624c355653e0eab74a45b867a091d3d10d12ac1183535e14c',
        }, observation['license'])

    def test_fixture_advertises_tools_before_inventory(self):
        frames = fixture_frames()
        self.assertEqual({'tools': {}}, frames[1]['result'].get('capabilities'))
        for capabilities in (None, {}, {'tools': None}, {'tools': []}):
            with self.subTest(capabilities=capabilities), self.assertRaises(AssertionError):
                invalid = fixture_frames()
                if capabilities is None:
                    invalid[1]['result'].pop('capabilities')
                else:
                    invalid[1]['result']['capabilities'] = capabilities
                self.verify_fixture(self.encode(invalid))

    def test_refuses_mismatched_peer_inventory_scope_and_ref(self):
        for offset, change in (
            (1, lambda frame: frame['result']['serverInfo'].update(name='untrusted')),
            (4, lambda frame: frame['result']['tools'][0]['annotations'].update(readOnlyHint=False)),
            (4, lambda frame: frame['result']['tools'].append(frame['result']['tools'][0])),
            (4, lambda frame: frame['result']['tools'][0]['inputSchema'].update(type='array')),
            (5, lambda frame: frame['params'].update(name='write_tool')),
            (6, lambda frame: frame.update(id=True)),
            (6, lambda frame: frame.update(id=2)),
            (6, lambda frame: frame.update(error={'code': -32603, 'message': 'failed'})),
            (6, lambda frame: frame['result'].update(isError=True)),
            (6, lambda frame: frame['result'].update(authority='WRITE')),
            (9, lambda frame: frame['params']['arguments'].update(path='README.md')),
            (12, lambda frame: frame.update(result=text_result([{'name': 'main', 'sha': 'f' * 40,
                                                                 'protected': True}]))),
        ):
            with self.subTest(offset=offset), self.assertRaises((AssertionError, ValueError)):
                frames = fixture_frames()
                change(frames[offset])
                self.verify_fixture(self.encode(frames))

    def test_refuses_legacy_or_malformed_text_results(self):
        search = self.text_payload(fixture_frames()[6]['result'])
        repo, = search['items']
        for offset, result in (
            (6, {'structuredContent': {'result': {'items': []}}}),
            (6, {'content': [{'type': 'text', 'text': '{"total_count":0,"total_count":1}'}]}),
            (6, {'content': [{'type': 'text', 'text': canonical(search).decode() + ',"extra":false'}]}),
            (6, text_result({**search, 'items': []})),
            (6, text_result({**search, 'authority': 'WRITE'})),
            (6, text_result({**search, 'items': [{**repo, 'id': 1}]})),
            (8, text_result([{'name': 'main', 'commit': {'sha': PINNED_HEAD}, 'protected': True}])),
            (12, text_result([{'name': 'main', 'sha': PINNED_HEAD, 'protected': 1}])),
        ):
            with self.subTest(offset=offset, result=result), self.assertRaises((AssertionError, ValueError)):
                frames = fixture_frames()
                frames[offset]['result'] = result
                self.verify_fixture(self.encode(frames))

    def test_refuses_invalid_embedded_license_even_with_valid_repository_projection(self):
        for change in (
            lambda result: result.update(isError=True),
            lambda result: result['content'][1].update(type='resource_link'),
            lambda result: result['content'][1]['resource'].update(uri=LICENSE_URI.replace('/sha/', '/ref/')),
            lambda result: result['content'][1]['resource'].update(mimeType='application/octet-stream'),
            lambda result: result['content'][1]['resource'].update(text='x' * LICENSE_BYTES),
            lambda result: result['content'][1]['resource'].update(blob='fixture'),
        ):
            with self.assertRaises((AssertionError, ValueError)):
                frames = fixture_frames()
                change(frames[10]['result'])
                self.verify_fixture(self.encode(frames))

    def test_current_wire_decoder_denies_noncanonical_response_frames(self):
        for first in (b'{"jsonrpc":"2.0","jsonrpc":"1.0"}', b'{"id":1.0}', b'{"text":"\xff"}'):
            with self.subTest(frame=first), self.assertRaises(ValueError):
                self.verify_fixture(first + b'\n' + self.encode(fixture_frames()[1:]))
