"""Offline official READ contracts. All Core keys and the stdio peer are synthetic."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import test_mobile_pairing as pairing
from runtime.mcp_bridge import official_read as mcp
from runtime.mobile_gateway import wire

SAMPLE_TOOLS = [{'name': name} for name in mcp.TOOLS]
LICENSE = Path(__file__).resolve().parents[1].joinpath('LICENSE').read_text()


def reply(method, params):
    if method == 'initialize':
        return {'serverInfo': {'name':'github-mcp-server','version':'1.0.5'},
                'protocolVersion':mcp.PROTOCOL,'capabilities':{'tools':{}}}
    if method == 'tools/list':
        return {'tools':SAMPLE_TOOLS}
    if params['name'] == 'search_repositories':
        repository = {'id':mcp.REPOSITORY_ID,'full_name':mcp.REPOSITORY,'private':False,
                      'html_url':'https://github.com/'+mcp.REPOSITORY}
        return {'content':[{'type':'text','text':json.dumps({
            'total_count':1,'incomplete_results':False,'items':[repository]})}]}
    return {'content':[{'type':'text','text':f'successfully downloaded text file (SHA: {mcp.BLOB})'},
                       {'type':'resource','resource':{'uri':mcp.URI,'mimeType':'text/plain; charset=utf-8',
                                                      'text':LICENSE}}]}


class ScriptedChannel:
    def __init__(self, change=lambda method,result:result):
        self.calls=[]
        self.reads=0
        self.change=change

    def send(self, value):
        self.calls.append(value)

    def rpc(self, method, params):
        self.calls.append({'method':method,'params':params})
        return self.change(method,reply(method,params))


class OfficialMcpWireTests(unittest.TestCase):
    def test_exact_small_recipe_and_local_write_refusal(self):
        channel=ScriptedChannel()
        with patch.object(mcp,'INVENTORY',wire.digest(wire.canonical(SAMPLE_TOOLS))):
            result=mcp.observe(channel)
        self.assertTrue(result['local_write_denial'])
        self.assertEqual(2,channel.reads)
        self.assertEqual(['initialize','notifications/initialized','tools/list','tools/call','tools/call'],
                         [c['method'] for c in channel.calls])
        self.assertEqual({'owner':'luciferprosun','repo':'AIOA-spArkHAT','path':'LICENSE','sha':mcp.TARGET},
                         channel.calls[-1]['params']['arguments'])
        self.assertEqual(mcp.CONTENT,result['content_sha256'])

    def test_unreviewed_descriptor_even_with_readonly_hint_denied_before_calls(self):
        def mutate(method, result):
            if method == 'tools/list':
                return {'tools': [{'name':name, 'annotations':{'readOnlyHint':True}} for name in mcp.TOOLS]}
            return result
        channel=ScriptedChannel(mutate)
        with self.assertRaisesRegex(ValueError,'OFFICIAL_MCP_INVENTORY'):
            mcp.observe(channel)
        self.assertEqual(0,channel.reads)

    def test_extra_inventory_page_and_changed_file_fail(self):
        def extra(method,result):
            return {**result,'nextCursor':'next'} if method=='tools/list' else result
        channel=ScriptedChannel(extra)
        with self.assertRaisesRegex(ValueError,'OFFICIAL_MCP_INVENTORY'):
            mcp.observe(channel)
        self.assertEqual(2,sum(c['method']=='tools/list' for c in channel.calls))
        def bad_file(method,result):
            if method=='tools/call' and len(result['content'])==2:
                result['content'][1]['resource']['text']+='\n'
            return result
        with patch.object(mcp,'INVENTORY',wire.digest(wire.canonical(SAMPLE_TOOLS))):
            with self.assertRaisesRegex(ValueError,'OFFICIAL_MCP_FILE'):
                mcp.observe(ScriptedChannel(bad_file))

    def test_real_fragmented_stdio_and_wrong_id_or_oversize_or_eof(self):
        for mode in ('valid','id','large','eof'):
            with self.subTest(mode=mode):
                script = """
import json, os, sys
v=json.loads(sys.stdin.buffer.readline())
mode=sys.argv[1]
if mode!='eof':
    raw=json.dumps({'jsonrpc':'2.0','id':False if mode=='id' else v['id'],'result':{'v':'x'*66000 if mode=='large' else 'ok'}}).encode()+b'\\n'
    for start in range(0,len(raw),731):os.write(1,raw[start:start+731])
"""
                with subprocess.Popen([sys.executable,'-I','-B','-c',script,mode],
                       stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL) as child:
                    channel=mcp.Channel(child,time.monotonic()+5,lambda:None)
                    if mode=='valid':
                        self.assertEqual({'v':'ok'},channel.rpc('initialize',{}))
                    else:
                        with self.assertRaises(ValueError):
                            channel.rpc('initialize',{})
                    child.stdin.close()

    def test_drifted_binary_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'github-mcp-server'
            path.write_bytes(b'not executable')
            path.chmod(0o400)
            with self.assertRaisesRegex(ValueError,'OFFICIAL_MCP_BINARY_CHANGED'),mcp.sealed_server(Path(d)):
                self.fail('drifted binary sealed')


class OfficialMcpCoreTests(unittest.TestCase):
    setUp=pairing.PairingTests.setUp
    start=pairing.PairingTests.start
    tearDown=pairing.PairingTests.tearDown

    def invoke(self, op, **args):
        return self.app.operator_request(os.getuid(),{'op':op, **args})

    def permit(self):
        permit={'request_id':mcp.REQUEST_ID,'source_sha':self.source[0],'starts_at':int(time.time())-1,
                'expires_at':int(time.time())+300, 'repo':mcp.REPOSITORY}
        patcher=patch.object(mcp,'manifest',return_value=permit)
        patcher.start()
        self.addCleanup(patcher.stop)
        with patch.object(mcp,'preflight'):
            review=self.invoke('tool_read_prepare',operation=mcp.OPERATION)
            return self.invoke('tool_read_approve',operation=mcp.OPERATION,permit_digest=review['permit_digest'])

    def execute(self,approval,request_id=mcp.REQUEST_ID):
        return self.invoke('tool_read',operation=mcp.OPERATION,request_id=request_id,approval=approval)

    def test_restart_returns_original_signed_result_and_does_not_launch_again(self):
        approval=self.permit()
        wire.verify(self.app.identity.spki,approval['signature'],approval['permit'])
        with patch.object(mcp,'run',return_value={'transport':mcp.TRANSPORT,'data':{
                    'permit':approval['permit'],'content_sha256':mcp.CONTENT}}) as transport:
            signed=self.execute(approval)
            wire.verify(self.app.identity.spki,signed['signature'],signed['receipt'])
            self.app.close()
            self.start()
            self.assertEqual(signed,self.invoke('tool_readback',request_id=mcp.REQUEST_ID))
            self.assertEqual(signed,self.execute(approval))
            self.assertEqual(1,transport.call_count)

    def test_complete_manifest_is_signed_persisted_and_recovered(self):
        directory = self.root / 'official-mcp-read'
        directory.mkdir(mode=0o700)
        window = directory / 'window.json'
        window.write_bytes(wire.canonical({
            'credential_id': '123', 'credential_sha256': 'e'*64, 'credential_scope': mcp.SCOPE,
            'starts_at': int(time.time())-1, 'expires_at': int(time.time())+300}))
        window.chmod(0o600)
        # Pairing fixture supplies the existing Core interfaces and a disposable key.
        with patch.object(self.app, '_existing_profile', object()), patch.object(
                mcp, '_source_tree', return_value='d'*40), patch.object(mcp, 'preflight'):
            review = self.invoke('tool_read_prepare', operation=mcp.OPERATION)
            permit = review['permit']
            self.assertEqual(self.app.instance_id, permit['grant_core_instance_id'])
            self.assertEqual(self.app.operator_principal().assignment_revision, permit['admission_revision'])
            with self.assertRaises(wire.MobileError):
                self.invoke('tool_read_approve', operation=mcp.OPERATION, permit_digest='1'*64)
            approval = self.invoke('tool_read_approve', operation=mcp.OPERATION,
                                   permit_digest=review['permit_digest'])
            data = {'permit': permit, 'permit_signature': approval['signature'], 'writes': 0,
                    'blob': mcp.BLOB, 'transcript_sha256': 'f'*64}
            with patch.object(mcp, 'run', return_value={'transport': mcp.TRANSPORT, 'data': data}):
                signed = self.execute(approval)
        self.app.close()
        self.start()
        self.assertEqual(signed, self.invoke('tool_readback', request_id=mcp.REQUEST_ID))
        self.assertNotEqual(permit['grant_core_instance_id'], self.app.instance_id)
        wire.verify(self.app.identity.spki, signed['signature'], signed['receipt'])
        wire.verify(self.app.identity.spki, signed['data']['permit_signature'], permit)

    def test_uncertain_after_reservation_cannot_start_another_session(self):
        approval=self.permit()
        with patch.object(mcp,'run',side_effect=ValueError('OFFICIAL_MCP_EOF')) as transport:
            with self.assertRaisesRegex(ValueError,'OFFICIAL_MCP_EOF'):
                self.execute(approval)
            self.app.close()
            self.start()
            self.assertEqual('UNKNOWN',self.invoke('tool_readback',request_id=mcp.REQUEST_ID)['state'])
            with self.assertRaises(wire.MobileError):
                self.execute(approval)
            self.assertEqual(1,transport.call_count)

    def test_invalid_signature_request_and_approval_expiry_never_reserve(self):
        approval=self.permit()
        with patch.object(mcp,'run') as transport:
            with self.assertRaises(wire.MobileError):
                self.execute({**approval,'signature':self.device.sign(approval['permit'])})
            with self.assertRaises(wire.MobileError):
                self.execute(approval,'f'*32)
            with patch.object(mcp,'check_window',side_effect=ValueError('OFFICIAL_MCP_WINDOW')):
                with self.assertRaisesRegex(ValueError,'OFFICIAL_MCP_WINDOW'):
                    self.execute(approval)
            self.assertEqual('NOT_FOUND',self.invoke('tool_readback',request_id=mcp.REQUEST_ID)['state'])
            transport.assert_not_called()
