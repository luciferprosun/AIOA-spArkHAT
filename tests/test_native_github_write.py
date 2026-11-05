"""Native binding tests with real temporary Core/SQLite and offline ports."""
import json
import os
import unittest
import time
from unittest.mock import patch

import test_mobile_pairing as pairing
import test_mobile_chat as chat_fixture
import test_github_remote_execution as protocol_fixture
from runtime.mcp_bridge.github_remote import InstallationCredential
from runtime.mobile_gateway import wire
from runtime.mission.git_publish import GitTreeSnapshot,git_object,DEMO_REPOSITORY


class NativeGitHubWriteTests(unittest.TestCase):
    setUp=pairing.PairingTests.setUp
    tearDown=pairing.PairingTests.tearDown
    start=chat_fixture.NativeChatTests.start

    def proposal(self):
        raw=json.dumps({'schema':'aioa.muse.github-change.v1','operation':'code.commit_draft_pr',
            'target_repo':DEMO_REPOSITORY,'title':'Add reviewed contract','body':'Proposed code; tests not run.',
            'files':{'agent-demo/contracts.py':'VALUE = 1\n'}})
        message={'state':'SUCCEEDED','live_verified':True,'current_source':True,'reply':raw,
            'source_sha':self.source[0],'capsule_digest':self.source[1],'request_id':'a'*32,'thread_id':'b'*32,
            'receipt':{'response_sha256':wire.digest(raw.encode())}}
        self.message=message
        base=GitTreeSnapshot(git_object('tree',b''),{})
        with patch.object(self.app.missions,'chat_request',return_value=message),\
                patch('runtime.mcp_bridge.github_remote.read_demo_base',return_value=('c'*40,base)):
            return self.app.operator_request(os.getuid(),{'op':'tool_proposal','request_id':'d'*32,'chat_request_id':'a'*32})

    def test_model_file_proposal_is_signed_exact_and_grants_no_authority(self):
        result=self.proposal()
        self.assertFalse(result['execution_authorized'])
        self.assertEqual('code.commit_draft_pr',result['proposal']['operation'])
        self.assertEqual('VALUE = 1\n',result['review']['files']['agent-demo/contracts.py'])
        self.assertEqual('aioa/muse-'+'d'*32,result['review']['branch'])
        wire.verify(self.app.identity.spki,result['signature'],{k:v for k,v in result.items() if k!='signature'})
        self.assertIn('GITHUB_APP_NOT_CONFIGURED',result['blockers'])

    def test_bad_review_and_missing_credentials_never_mint_or_dispatch(self):
        result=self.proposal()
        with patch('runtime.mcp_bridge.github_remote.GitHubAppCredentialSource.mint') as mint,\
                patch('runtime.mcp_bridge.github_remote.GitHubCreateOnly.execute') as execute:
            with self.assertRaises(wire.MobileError):
                self.app.operator_request(os.getuid(),{'op':'github_write_approve','operation_id':'d'*32,'review_digest':'0'*64})
            blocked=self.app.operator_request(os.getuid(),{'op':'github_write_approve','operation_id':'d'*32,
                'review_digest':result['review_digest']})
            self.assertEqual('BLOCKED_EXTERNAL',blocked['status'])
            self.assertFalse(blocked['execution_authorized'])
            mint.assert_not_called();execute.assert_not_called()

    def test_status_readback_is_local_only_and_unknown_id_does_not_grant_execution(self):
        with patch('runtime.mcp_bridge.github_remote._https_once') as network:
            value=self.app.operator_request(os.getuid(),{'op':'github_write_status','operation_id':'e'*32})
            self.assertEqual('NOT_FOUND',value['status']);network.assert_not_called()

    def test_native_owner_to_core_to_git_protocol_receipt_is_offline_test_only(self):
        from runtime.meta_hackathon import github_write
        from runtime.mobile_gateway.service import plain
        self.app.operator_request(os.getuid(),{'op':'chat_session_start','request_id':'f'*32,'local_money_limit_usd':None})
        review=self.proposal();data=plain(self.app.mobile._get('native-github-'+'d'*32).payload)
        port=protocol_fixture.RemoteExecutionTests();port.setUp()
        port.plan,port.base=github_write._decode(data)
        port.tree=port.base.add_files(port.plan.files);port.commit=port.plan.commit_sha_for_tree(port.tree.sha)
        port.credential=InstallationCredential('ghs_NATIVE_TEST_FIXTURE_ONLY',73,int(time.time())+3600,'a'*64,'LIVE')
        port.marker_assertion=lambda:self.assertIsNotNone(self.app.mobile._get('github-step-'+'d'*32+'-tree'))
        errors=[]
        def transport(*args):
            try:return port.transport(*args)
            except Exception as error:
                errors.append(type(error).__name__+': '+str(error));raise
        with patch('runtime.mcp_bridge.github_remote.GitHubAppCredentialSource.configuration',return_value=({'installation_id':73},None)),\
                patch('runtime.mcp_bridge.github_remote.GitHubAppCredentialSource.mint',return_value=port.credential),\
                patch('runtime.mcp_bridge.github_remote._https_once',side_effect=transport):
            self.app.operator_request(os.getuid(),{'op':'github_write_approve','operation_id':'d'*32,
                'review_digest':review['review_digest']})
            self.app.missions._workers['github-'+'d'*32].join(timeout=20)
            state=self.app.operator_request(os.getuid(),{'op':'github_write_status','operation_id':'d'*32})
        self.assertEqual('GITHUB_VERIFIED',state['status'],str((state.get('error'),errors)))
        self.assertEqual(port.commit,state['result']['receipt']['commit_sha'])
        wire.verify(self.app.identity.spki,state['result']['signature'],state['result']['receipt'])
        self.assertEqual(4,sum(m=='POST' for m,_,_ in port.calls))
        with self.assertRaises(wire.MobileError):self.app.operator_request(os.getuid(),{
            'op':'github_write_approve','operation_id':'d'*32,'review_digest':review['review_digest']})

    def test_approval_ack_loss_keeps_candidate_and_stop_revokes_without_dispatch(self):
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        from lab.archaioa.warrant import EffectWarrant
        from runtime.core_admission import Capability
        self.app.operator_request(os.getuid(),{'op':'chat_session_start','request_id':'f'*32,'local_money_limit_usd':None})
        review=self.proposal();approve=self.app.ledger.approve
        def lost(*args):approve(*args);raise CommitOutcomeUnknown()
        with patch('runtime.mcp_bridge.github_remote.GitHubAppCredentialSource.configuration',return_value=({'installation_id':73},None)),\
                patch('runtime.mcp_bridge.github_remote.GitHubAppCredentialSource.mint') as mint,\
                patch.object(self.app.ledger,'approve',side_effect=lost):
            with self.assertRaises(CommitOutcomeUnknown):self.app.operator_request(os.getuid(),{
                'op':'github_write_approve','operation_id':'d'*32,'review_digest':review['review_digest']})
            mint.assert_not_called()
        row=self.app.mobile._get('native-github-'+'d'*32)
        self.assertEqual('GITHUB_APPROVAL_PENDING',row.payload['state'])
        self.app.operator_request(os.getuid(),{'op':'github_write_stop','operation_id':'d'*32})
        row=self.app.mobile._get('native-github-'+'d'*32);self.assertTrue(row.payload['stop_requested'])
        from runtime.mobile_gateway.service import plain
        warrant=EffectWarrant.from_dict(plain(row.payload['candidate_warrant']))
        with self.assertRaisesRegex(ValueError,'WARRANT_REVOKED'):
            self.app.ledger.consume(self.app.core.local_operator(Capability.COMMIT),warrant)

    def test_same_verified_muse_turn_cannot_create_a_second_operation(self):
        first=self.proposal()
        with patch.object(self.app.missions,'chat_request',return_value=self.message),\
                patch('runtime.mcp_bridge.github_remote.read_demo_base') as read:
            repeated=self.app.operator_request(os.getuid(),{'op':'tool_proposal','request_id':'e'*32,'chat_request_id':'a'*32})
        self.assertEqual(first['operation_id'],repeated['operation_id'])
        self.assertEqual(first['review_digest'],repeated['review_digest']);read.assert_not_called()

    def test_local_history_recovers_operation_ids_without_network_or_write(self):
        first=self.proposal()
        with patch('runtime.mcp_bridge.github_remote._https_once') as network:
            history=self.app.operator_request(os.getuid(),{'op':'github_write_list'})
        network.assert_not_called()
        self.assertEqual([first['operation_id']],[x['operation_id'] for x in history['operations']])
        self.assertEqual('PROPOSE',history['operations'][0]['mode'])
        self.assertFalse(history['authorization']['configured'])

    def test_incomplete_or_foreign_source_muse_reply_never_reaches_remote_port(self):
        self.proposal()
        for fields in ({'state':'CHAT_TRUNCATED'},{'current_source':False},{'live_verified':False},
                {'source_sha':'0'*40},{'receipt':{'response_sha256':'0'*64}}):
            with self.subTest(fields=fields),patch.object(self.app.missions,'chat_request',return_value={**self.message,**fields}),\
                    patch('runtime.mcp_bridge.github_remote.read_demo_base') as read,\
                    patch('runtime.mcp_bridge.github_remote.GitHubAppCredentialSource.mint') as mint:
                with self.assertRaises(wire.MobileError):self.app.operator_request(os.getuid(),{
                    'op':'tool_proposal','request_id':'e'*32,'chat_request_id':'a'*32})
                read.assert_not_called();mint.assert_not_called()

    def test_stop_is_durable_and_expired_review_cannot_authorize_write(self):
        from runtime.meta_hackathon import github_write
        from runtime.mobile_gateway.service import plain
        review=self.proposal();data=plain(self.app.mobile._get('native-github-'+'d'*32).payload)
        data.pop('schema',None)
        github_write._save(self.app,'d'*32,{**data,'expires_at':int(time.time())-1})
        with patch('runtime.mcp_bridge.github_remote.GitHubAppCredentialSource.mint') as mint:
            with self.assertRaisesRegex(ValueError,'GITHUB_REVIEW_EXPIRED'):
                self.app.operator_request(os.getuid(),{'op':'github_write_approve','operation_id':'d'*32,
                    'review_digest':review['review_digest']})
            self.app.operator_request(os.getuid(),{'op':'github_write_stop','operation_id':'d'*32})
            github_write._save(self.app,'d'*32,data)
            status=self.app.operator_request(os.getuid(),{'op':'github_write_status','operation_id':'d'*32})
            self.assertIn('GITHUB_STOPPED',status['blockers']);self.assertFalse(status['approval_available'])
            mint.assert_not_called()


if __name__=='__main__':unittest.main()
