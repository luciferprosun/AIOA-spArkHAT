"""Rich GitHub observations must reach advisory chat as inert user data.

All HTTP traffic is intercepted; this is not model inference certification.
"""
import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_meta_chat_provider as provider_fixture
import test_native_chat_session as session_fixture
from test_nz13_github_contexts import OPERATIONS, RichContextFixture

from runtime.mcp_bridge import native_read
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)


class RichProviderContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = provider_fixture.MetaChatProviderTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def request(self, operation, fixture=None):
        self.assertIn(operation, native_read.OPERATIONS, 'Rich READ is not integrated')
        fixture = fixture or RichContextFixture()
        with patch.object(native_read, '_github_json', side_effect=fixture.get):
            data = native_read.read(operation, '.')['data']
        original = self.fixture.request
        observation = {'schema': 'aioa.chat.read-context.v1', 'trust': 'UNTRUSTED_READ_DATA',
                       'request_id': 'a' * 32, 'operation': operation, 'observed_at': 100, 'expires_at': 400,
                       'source_sha': original.task.source_sha, 'capsule_digest': original.capsule_digest,
                       'data_sha256': canonical_sha256(data), 'receipt_sha256': 'e' * 64, 'data': data}
        context = {**self.fixture.context, 'schema': 'aioa.chat.core-context.v2', 'read_context': observation}
        return replace(original, context_json=canonical_json_bytes(context).decode()), context

    def test_each_new_recipe_is_validated_digest_bound_user_data_without_tools(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                request, context = self.request(operation)
                try:
                    payload = request.payload()
                except ValueError:
                    self.fail('Provider rejected the new signed observation recipe')
                self.assertNotIn('tools', payload)
                self.assertNotIn('tool_choice', payload)
                self.assertNotIn(operation, payload['messages'][0]['content'])
                projected = [m['content'] for m in payload['messages'] if m['role'] == 'user'
                             and m['content'].startswith('UNTRUSTED_READ_DATA\n')]
                self.assertEqual(1, len(projected))
                self.assertEqual(context['read_context'], json.loads(projected[0].split('\n', 1)[1]))
                self.assertLessEqual(len(canonical_json_bytes(payload)), 16384)

    def test_changed_digest_is_refused_before_a_transport_can_receive_it(self):
        request, context = self.request(OPERATIONS[1])
        context['read_context']['data_sha256'] = '0' * 64
        with patch('runtime.providers.meta_model_api._https_once') as transport, self.assertRaises(ValueError):
            replace(request, context_json=canonical_json_bytes(context).decode()).payload()
        transport.assert_not_called()

    def test_normalized_authority_cannot_be_replaced_even_with_a_fresh_data_digest(self):
        request, context = self.request(OPERATIONS[2])
        for change in ('authority', 'taint', 'unexpected_field'):
            with self.subTest(change=change):
                changed = copy.deepcopy(context)
                data = changed['read_context']['data']
                data[change] = 'OWNER'
                changed['read_context']['data_sha256'] = canonical_sha256(data)
                with self.assertRaises(ValueError):
                    replace(request, context_json=canonical_json_bytes(changed).decode()).payload()

    def test_large_read_result_is_not_silently_truncated_or_sent_over_chat_bound(self):
        fixture = RichContextFixture()
        fixture.add_pages('issues', [fixture.issue(n) for n in range(1, 11)],
                          [fixture.issue(n) for n in range(11, 21)])
        for endpoint, rows in fixture.responses.items():
            if '/issues?' in endpoint:
                for row in rows:
                    row['body'] = 'Neutral explanatory text. ' * 25
        request, _ = self.request(OPERATIONS[1], fixture)
        self.assertGreater(len(request.context_json.encode()), 4096)
        with patch('runtime.providers.meta_model_api._https_once') as transport, self.assertRaises(ValueError):
            request.payload()
        transport.assert_not_called()


class RichNativeChatFlowTests(unittest.TestCase):
    setUp = session_fixture.NativeChatSessionTests.setUp
    start = session_fixture.NativeChatSessionTests.start
    tearDown = session_fixture.NativeChatSessionTests.tearDown
    owner = session_fixture.NativeChatSessionTests.owner
    begin = session_fixture.NativeChatSessionTests.begin
    payload = session_fixture.NativeChatSessionTests.payload
    wait = session_fixture.NativeChatSessionTests.wait
    response = session_fixture.NativeChatSessionTests.response

    def test_same_native_core_read_receipt_is_bound_into_one_mock_chat_request(self):
        operation = OPERATIONS[1]
        self.assertIn(operation, native_read.OPERATIONS, 'Rich READ is not integrated')
        self.begin()
        fixture = RichContextFixture()
        with patch.object(native_read, '_github_json', side_effect=fixture.get):
            observed = self.owner('tool_read', operation=operation, request_id='9' * 32)
        with patch('runtime.providers.meta_model_api._https_once', return_value=self.response()) as transport:
            try:
                self.owner('chat_send', payload=self.payload(), read_request_id='9' * 32)
                result = self.wait()
            except ValueError:
                self.fail('Native read-to-chat request binding is missing')
        self.assertEqual('SUCCEEDED', result['state'], result.get('error'))
        self.assertEqual(1, transport.call_count)
        request = self.app.missions._chat_payloads['2' * 32][1]
        context = json.loads(request.context_json)['read_context']
        self.assertEqual(operation, context['operation'])
        self.assertEqual(observed['receipt']['data_sha256'], context['data_sha256'])
        self.assertEqual('UNTRUSTED_READ_DATA', context['trust'])
        self.assertNotIn('tools', request.payload())
