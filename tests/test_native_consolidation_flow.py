"""One offline Native/Core flow; only provider and external READ ports are fixtures."""
import json
import unittest
from unittest.mock import patch

import test_native_chat_session as chat
from runtime.mission.git_publish import DEMO_REPOSITORY, GitTreeSnapshot, git_object
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
        read_value = {'operation': 'github.repository', 'transport': 'FIXTURE_NOT_LIVE',
                      'data': {'commit_sha': 'c' * 40}}
        base = GitTreeSnapshot(git_object('tree', b''), {})
        with patch('runtime.providers.meta_model_api._https_once', return_value=response) as model, \
                patch('runtime.mcp_bridge.native_read.read', return_value=read_value) as read, \
                patch('runtime.mcp_bridge.github_remote.read_demo_base', return_value=('c' * 40, base)) as preflight, \
                patch('runtime.mcp_bridge.github_remote.GitHubAppCredentialSource.mint') as mint, \
                patch('runtime.mcp_bridge.github_remote.GitHubCreateOnly.execute') as execute, \
                patch('socket.create_connection', side_effect=AssertionError('external network forbidden')) as network, \
                patch('subprocess.Popen', side_effect=AssertionError('external process forbidden')) as child:
            self.begin()
            self.send()
            reply = self.wait()
            self.assertEqual('SUCCEEDED', reply['state'])
            self.assertEqual(proposal, reply['reply'])
            self.assertEqual(reply['request_digest'], self.send()['request_digest'])
            observation = self.owner('tool_read', request_id='c' * 32, operation='github.repository')
            wire.verify(self.app.identity.spki, observation['signature'], observation['receipt'])
            self.assertEqual('FIXTURE_NOT_LIVE', observation['receipt']['transport'])
            review = self.owner('tool_proposal', request_id='d' * 32, chat_request_id='2' * 32)
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
            self.assertEqual(1, read.call_count)
            self.assertEqual(1, preflight.call_count)
            mint.assert_not_called()
            execute.assert_not_called()
            network.assert_not_called()
            child.assert_not_called()


if __name__ == '__main__':
    unittest.main()
