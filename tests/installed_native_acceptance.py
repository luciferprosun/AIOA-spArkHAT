"""Executed as an isolated -c fixture from the packaging harness, never imported.

The real installed Native/Core/SQLite is exercised. OS identity, TLS and the
source probe are explicitly synthetic; this is not production admission.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

venv=Path(sys.argv[1]).resolve()
expected=json.loads(sys.argv[2])
import runtime
from runtime.core_admission import AdmissionError,Capability
from runtime.memory_patch.persistence.ports import LocalCoreRecordFactory,RecordKind
from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
from runtime.mobile_gateway import wire
from runtime.mobile_gateway.service import plain
from runtime.webapp import WebRuntimeService,WEB_DIR

assert 'PYTHONPATH' not in os.environ
assert all(not name.startswith('test_') and name!='tests' for name in sys.modules)
assert Path(runtime.__file__).resolve().is_relative_to(venv)
site=Path(runtime.__file__).resolve().parent.parent
for relative,digest in expected.items():
    path=(venv/'share/aioa-sparkhat'/relative) if relative.startswith('web/') else site/relative
    assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==digest, relative
assert WEB_DIR.resolve()==venv/'share/aioa-sparkhat/web'

fixture_source=['f'*40,hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()]
proof=(os.getuid(),{'uid':os.getuid(),'test_only':True})
def open_fixture(root,*,existing=False):
    with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',return_value=proof):
        host=NativeMobileComposition(root,origin='https://installed.example.org',chat=False,
            source_probe=lambda:tuple(fixture_source),existing_profile=existing)
    host.tls_verified=True
    host.tls_pin='sha256/'+'A'*43+'='
    host._tls_expires=time.time()+3600
    return host

def counts(host):
    return host.mobile._run(Capability.READ,lambda tx:tuple(
        len(tx.scan(kind,limit=128)) for kind in (RecordKind.OPERATION,RecordKind.AUDIT,RecordKind.OUTBOX)))

with tempfile.TemporaryDirectory(prefix='aioa-installed-native-') as temporary,\
        patch('subprocess.Popen',side_effect=AssertionError('UNEXPECTED_CHILD')) as child,\
        patch('socket.create_connection',side_effect=AssertionError('UNEXPECTED_NETWORK')) as network,\
        patch('runtime.providers.meta_model_api._https_once',side_effect=AssertionError('UNEXPECTED_PROVIDER')) as provider:
    root=Path(temporary)/'state'
    host=open_fixture(root)
    try:
        assert host.core is host.ledger.core is host.missions.core is host.mobile.core
        assert host.runner is host.ledger.runner is host.missions.runner is host.mobile.runner
        assert host.runtime._memory_patch_admission is host.core
        assert type(host.runner._factory) is LocalCoreRecordFactory
        assert host.runner._factory.path==root/'core-records.sqlite3'
        assert host.manager is None and not host.chat_enabled
        service=WebRuntimeService(runtime=host.runtime,meta_missions=host.missions,
            meta_owner=host,mobile_gateway=host.mobile)
        assert service.runtime is host.runtime and service.meta_missions is host.missions
        assert service.mobile_only and not service.unified_profile and service.core_mcp is None
        try:open_fixture(root)
        except AdmissionError:pass
        else:raise AssertionError('SECOND_NATIVE_ACCEPTED')
        initial=counts(host)
        request={'op':'command_advice','request_id':'1'*32,'payload':{'command':'ls "$TARGET"'}}
        first=host.operator_request(os.getuid(),request)
        assert first['data']['classification']['danger']=='unknown'
        wire.verify(host.identity.spki,first['signature'],first['receipt'])
        assert wire.digest(wire.canonical(first['data']))==first['receipt']['data_sha256']
        assert not first['receipt']['execution_authorized']
        assert counts(host)==tuple(n+1 for n in initial)
        after_first=counts(host)
        assert host.operator_request(os.getuid(),request)==first
        assert counts(host)==after_first
        try:host.operator_request(os.getuid(),{**request,'payload':{'command':'ls changed'}})
        except wire.MobileError as error:assert error.status==409
        else:raise AssertionError('REUSED_ID_ACCEPTED')
        mail=host.operator_request(os.getuid(),{'op':'mail_preview','request_id':'2'*32,
            'payload':{'sender':'author@example.org','to':['reviewer@example.org'],
                'subject':'Installed Native fixture','body_text':'No delivery or provider call.'}})
        wire.verify(host.identity.spki,mail['signature'],mail['receipt'])
        assert mail['data']['status']=='DRAFT_PREVIEW_ONLY' and mail['receipt']['external_calls']==0
        assert counts(host)==tuple(n+2 for n in initial)
        cpt_request={'op':'critic_transform_preview','request_id':'3'*32,
            'payload':{'prompt':'An installed private synthetic CPT proposal.'}}
        cpt=host.operator_request(os.getuid(),cpt_request)
        wire.verify(host.identity.spki,cpt['signature'],cpt['receipt'])
        assert cpt['data']['status']=='CPT_DRAFT_PREVIEW_ONLY'
        assert wire.digest(cpt['preview']['transformed_prompt'].encode())==cpt['data']['transformed_prompt_sha256']
        assert 'preview' not in host.mobile._get('native-advisory-'+'3'*32).payload['result']
        assert counts(host)==tuple(n+3 for n in initial)
        assert host.operator_request(os.getuid(),cpt_request)==cpt
        assert counts(host)==tuple(n+3 for n in initial)
        assert cpt_request['payload']['prompt'].encode() not in (root/'core-records.sqlite3').read_bytes()
        before_status=counts(host)
        components=host.operator_request(os.getuid(),{'op':'status'})['components']
        assert not components['github_write']['enabled'] and not components['worker']['enabled']
        assert components['worker']['status']=='BLOCKED_NATIVE_WORKER_NOT_CERTIFIED'
        assert components['memory']['blocking_reason']=='MEMORY_CONSENT_REQUIRED'
        assert components['cpl']['preview']['provider_calls']==0 and not components['cpl']['enabled']
        assert counts(host)==before_status
        try:host.operator_request(os.getuid()+1,request)
        except AdmissionError:pass
        else:raise AssertionError('FOREIGN_UID_ACCEPTED')
        original_source=fixture_source[1];fixture_source[1]='0'*64
        try:host.operator_request(os.getuid(),request)
        except AdmissionError:pass
        else:raise AssertionError('SOURCE_DRIFT_ACCEPTED')
        fixture_source[1]=original_source
        spki=host.identity.spki;instance=host.instance_id
    finally:host.close()
    host=open_fixture(root,existing=True)
    try:
        assert host.identity.spki==spki and host.instance_id!=instance
        saved=plain(host.mobile._get('native-advisory-'+'1'*32).payload['result'])
        assert saved==first
        wire.verify(host.identity.spki,saved['signature'],saved['receipt'])
        try:host.operator_request(os.getuid(),request)
        except wire.MobileError as error:assert error.status==409
        else:raise AssertionError('OLD_INSTANCE_REBOUND')
    finally:host.close()
    child.assert_not_called();network.assert_not_called();provider.assert_not_called()

origins={}
for name in ('runtime.meta_hackathon.runtime_adapter','runtime.core_admission',
        'runtime.memory_patch.persistence.ports','runtime.meta_hackathon.mission_service',
        'runtime.mobile_gateway.service','runtime.webapp'):
    path=Path(importlib.import_module(name).__file__).resolve()
    assert path.is_relative_to(venv)
    origins[name]=str(path)
print(json.dumps({'status':'PASS','scope':'INSTALLED_NATIVE_FIXTURE',
    'one_core_and_transaction_factory':True,'second_native_same_state_denied':True,
    'real_sqlite_audit_outbox':True,'signed_preview_receipts':3,'cpt_prompt_text_persisted':False,
    'restart_preserves_identity_and_receipt':True,
    'source_drift_and_foreign_uid_denied':True,'provider_calls':0,'external_calls':0,
    'os_tls_source_qualification':'SYNTHETIC_FIXTURE_ONLY','production_deployment_qualified':False,
    'installed_source_files_verified':len(expected),'installed_source_manifest_sha256':original_source,
    'origins':origins}))
