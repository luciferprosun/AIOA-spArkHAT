"""Synthetic READ transport with real Core records; no network or model call."""
import os
import time
import unittest
from unittest.mock import patch
import test_mobile_pairing as fixture
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mobile_gateway import wire


class NativeChatContextTests(unittest.TestCase):
    setUp=fixture.PairingTests.setUp
    start=fixture.PairingTests.start
    tearDown=fixture.PairingTests.tearDown

    def read(self):
        data={'repository':'luciferprosun/AIOA-spArkHAT','repository_id':1247349659,
            'branch':'main','url':'https://github.com/luciferprosun/AIOA-spArkHAT','commit_sha':'c'*40}
        with patch('runtime.mcp_bridge.native_read.read',return_value={'operation':'github.repository',
                'data':data,'transport':'LIVE_GITHUB_GET'}):
            return self.app.operator_request(os.getuid(),{'op':'tool_read','operation':'github.repository','request_id':'1'*32})

    def resolve(self):
        from runtime.meta_hackathon.native_tools import chat_read_context
        return chat_read_context(self.app,'1'*32)

    def test_current_signed_read_is_bounded_untrusted_context_without_new_get(self):
        original=self.read()
        with patch('runtime.mcp_bridge.native_read.read') as transport:
            context=self.resolve();transport.assert_not_called()
        self.assertEqual(original['data'],context['data'])
        self.assertEqual(original['receipt']['data_sha256'],context['data_sha256'])
        self.assertEqual('UNTRUSTED_READ_DATA',context['trust'])
        self.assertEqual(context['observed_at']+300,context['expires_at'])
        self.assertNotIn('signature',context);self.assertNotIn('owner_scope_digest',context)

    def test_stale_source_instance_scope_signature_hash_and_fixture_origin_are_denied(self):
        original=self.read();identity='native-tool-read-'+'1'*32
        row=self.app.mobile._get(identity)
        for field,value in (('source_sha','f'*40),('capsule_digest','f'*64),('core_instance_id','other'),
                ('owner_scope_digest','e'*64),('data_sha256','d'*64),('transport','FIXTURE_NOT_LIVE'),
                ('operation','github.issues'),('observed_at',int(time.time())-301)):
            with self.subTest(field=field):
                result=wire.strict_json(wire.canonical(original));result['receipt'][field]=value
                result['signature']=self.app.identity.sign(result['receipt'])
                altered=dict(row.payload);altered['result']=result
                # A synthetic changed record is returned by the existing port;
                # it cannot pass host/current-source/signature/data validation.
                from dataclasses import replace
                with patch.object(self.app.mobile,'_get',return_value=replace(row,payload=altered)):
                    with self.assertRaises((ValueError,wire.MobileError)):self.resolve()
        invalid=wire.strict_json(wire.canonical(original));invalid['signature']='forged'
        with patch.object(self.app.mobile,'_get',return_value=replace(row,payload={**dict(row.payload),'result':invalid})):
            with self.assertRaises((ValueError,wire.MobileError)):self.resolve()


if __name__=='__main__':unittest.main()
