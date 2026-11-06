"""One offline Native/Core flow; only provider and external READ ports are fixtures."""
import json
import unittest
from unittest.mock import patch

import test_native_chat_session as chat
from test_native_repository_context import PublicRepositoryFixture
from runtime.mission.git_publish import DEMO_REPOSITORY, GitTreeSnapshot
from runtime.mobile_gateway import wire


class NativeConsolidationFlowTests(unittest.TestCase):
    setUp = chat.NativeChatSessionTests.setUp
    start = chat.NativeChatSessionTests.start
    tearDown = chat.NativeChatSessionTests.tearDown
    owner = chat.NativeChatSessionTests.owner
    begin = chat.NativeChatSessionTests.begin
    payload = chat.NativeChatSessionTests.payload
    send = chat.NativeChatSessionTests.send
    wait = chat.NativeChatSessionTests.wait

    def test_muse_read_proposal_denial_stop_and_signed_readback_share_one_core(self):
        content = '# Reviewed offline proposal\nNo external write was performed.\n'
        proposal = json.dumps({
            'schema': 'aioa.muse.github-change.v1', 'operation': 'code.commit_draft_pr',
            'target_repo': DEMO_REPOSITORY, 'title': 'Review offline proposal',
            'body': 'Fixture acceptance only; requires a separate owner warrant.',
            'files': {'agent-demo/review.md': content},
        })
        response = (200, json.dumps({
            'id': 'synthetic-consolidation-flow', 'model': 'muse-spark-1.3',
            'choices': [{'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': proposal}}],
            'usage': {'prompt_tokens': 8, 'completion_tokens': 120, 'total_tokens': 128},
        }).encode())
        public = PublicRepositoryFixture(True, b'# Demo repository\nOffline fixture context only.\n')
        base = GitTreeSnapshot(public.tree, {'README.md': ('100644', 'blob', public.blob)})
        with patch('runtime.providers.meta_model_api._https_once', return_value=response) as model, \
                patch('runtime.mcp_bridge.native_read._github_json', side_effect=public.get) as read, \
                patch('runtime.mcp_bridge.github_remote.read_demo_base', return_value=('c' * 40, base)) as preflight, \
                patch('runtime.mcp_bridge.github_remote.GitHubAppCredentialSource.mint') as mint, \
                patch('runtime.mcp_bridge.github_remote.GitHubCreateOnly.execute') as execute, \
                patch('socket.create_connection', side_effect=AssertionError('external network forbidden')) as network, \
                patch('subprocess.Popen', side_effect=AssertionError('external process forbidden')) as child:
            self.begin()
            observation = self.owner('tool_read', request_id='c' * 32, operation='github.demo_context')
            wire.verify(self.app.identity.spki, observation['signature'], observation['receipt'])
            # Real recipe/signing code over an explicit fake GET port; no LIVE
            # acceptance is inferred from this isolated fixture receipt.
            self.assertEqual('LIVE_GITHUB_GET', observation['receipt']['transport'])
            def send_with_context():
                return self.owner('chat_send', payload=self.payload(), read_request_id='c' * 32)
            send_with_context()
            reply = self.wait()
            self.assertEqual('SUCCEEDED', reply['state'])
            self.assertEqual(proposal, reply['reply'])
            self.assertEqual(reply['request_digest'], send_with_context()['request_digest'])
            review = self.owner('tool_proposal', request_id='d' * 32, chat_request_id='2' * 32)
            self.assertEqual('GITHUB_PROPOSED', review['status'], review.get('error'))
            self.assertEqual('c' * 32, review['review']['source_read']['request_id'])
            self.assertEqual(content, review['review']['files']['agent-demo/review.md'])
            self.assertFalse(review['execution_authorized'])
            self.assertIn('GITHUB_APP_NOT_CONFIGURED', review['blockers'])
            repeated = self.owner('tool_proposal', request_id='e' * 32, chat_request_id='2' * 32)
            self.assertEqual(review['operation_id'], repeated['operation_id'])
            self.assertEqual(review['review_digest'], repeated['review_digest'])
            with self.assertRaises(wire.MobileError):
                self.owner('github_write_approve', operation_id='d' * 32, review_digest='0' * 64)
            refused = self.owner('github_write_approve', operation_id='d' * 32,
                                 review_digest=review['review_digest'])
            self.assertEqual('BLOCKED_EXTERNAL', refused['status'])
            self.assertFalse(refused['execution_authorized'])
            self.owner('github_write_stop', operation_id='d' * 32)
            stopped = self.owner('github_write_status', operation_id='d' * 32)
            self.assertIn('GITHUB_STOPPED', stopped['blockers'])
            self.assertFalse(stopped['approval_available'])
            self.assertFalse(stopped['execution_authorized'])
            wire.verify(self.app.identity.spki, stopped['signature'],
                        {k: v for k, v in stopped.items() if k != 'signature'})
            self.assertTrue(self.app.mobile._get('native-github-' + 'd' * 32).payload['stop_requested'])
            with self.assertRaisesRegex(ValueError, 'GITHUB_STOPPED'):
                self.owner('github_write_approve', operation_id='d' * 32,
                           review_digest=review['review_digest'])
            self.owner('chat_session_stop')
            with self.assertRaises(ValueError):
                self.send('f' * 32)
            self.assertEqual(reply['receipt'], self.owner('chat_request', request_id='2' * 32)['receipt'])
            self.assertEqual(observation, self.owner('tool_readback', request_id='c' * 32))
            self.assertEqual(1, model.call_count)
            self.assertEqual(6, read.call_count)
            self.assertEqual(1, preflight.call_count)
            mint.assert_not_called()
            execute.assert_not_called()
            network.assert_not_called()
            child.assert_not_called()


if __name__ == '__main__':
    unittest.main()
