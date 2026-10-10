"""CLI and real loopback HTTP denial, not a demo or LIVE provider run."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import test_cpl_web as existing_web


class ToolHTTPBoundaryTests(unittest.TestCase):
    setUp=existing_web.CPLWebTests.setUp
    tearDown=existing_web.CPLWebTests.tearDown
    request=existing_web.CPLWebTests.request

    def test_actual_web_slash_denial_has_false_ok_and_forbidden_status(self):
        status,view,_=self.request('POST','/api/chat',{'prompt':'/worker clear','mode':'plain'})
        self.assertEqual(403,status,view);self.assertFalse(view['ok'])
        self.assertEqual('UNSUPPORTED_EFFECT_ROUTE',view['error'])
        self.assertEqual([],self.fixture.requests)

    def test_plain_chat_local_route_denial_cannot_print_success(self):
        runtime=self.service.runtime
        with tempfile.TemporaryDirectory() as temporary:
            runtime.local_router.desktop_dir=Path(temporary)
            # Deterministic local route, not a provider-generated response.
            view=runtime.run_text_request('utworz folder AI_TEST na pulpicie')
            self.assertFalse(view.get('ok',True),view)
            self.assertNotIn('Folder ready',view['transcript'])
            self.assertFalse((Path(temporary)/'AI_TEST').exists())
            self.assertEqual([],self.fixture.requests)

    def test_external_review_does_not_claim_a_blocked_browser_was_opened(self):
        events=[]
        runtime=self.service.runtime
        with patch.object(runtime,'log_session_event',side_effect=lambda kind,data:events.append((kind,data))):
            view=runtime.run_text_request('read https://example.com/paper')
        self.assertFalse(view['ok']);self.assertEqual([],self.fixture.requests)
        review=[data for kind,data in events if kind in ('external_link_review','external_repository_review')]
        self.assertTrue(review,events)
        self.assertFalse(review[-1]['browser_handled']);self.assertNotIn('opened_url',review[-1])

    def test_no_url_repository_denial_is_structured_in_plain_and_actual_web(self):
        runtime=self.service.runtime
        for prompt in ('review repository','inspect github.com/example/repo'):
            view=runtime.run_text_request(prompt)
            self.assertFalse(view['ok'],view)
            self.assertEqual('UNSUPPORTED_EFFECT_ROUTE',view['error'])
            status,view,_=self.request('POST','/api/chat',{'prompt':prompt,'mode':'plain'})
            self.assertEqual(403,status,view);self.assertFalse(view['ok'])
        self.assertEqual([],self.fixture.requests)

    def test_browser_adapter_exception_has_closed_denial_without_private_error(self):
        runtime=self.service.runtime
        with patch.object(runtime.executor,'execute',side_effect=RuntimeError('PRIVATE_ERROR_SENTINEL')):
            status,view,_=self.request('POST','/api/chat',{'prompt':'read https://example.com/paper','mode':'plain'})
        self.assertEqual(403,status,view);self.assertFalse(view['ok'])
        self.assertEqual('UNSUPPORTED_EFFECT_ROUTE',view['error'])
        self.assertNotIn('PRIVATE_ERROR_SENTINEL',json.dumps(view))
        self.assertEqual([],self.fixture.requests)

    def test_actual_dependency_free_tui_denies_before_private_extraction_or_store_clear(self):
        from tui.assistant import operator_request
        runtime=self.service.runtime;calls=[]
        with patch('commands.local_commands.ensure_scemda_addon',side_effect=lambda *_:calls.append('extract')),patch.object(
                runtime.worker_memory,'clear_worker_memory',side_effect=lambda:calls.append('clear'),create=True):
            for prompt in ('/scemda','/worker clear'):
                result=operator_request(runtime,prompt)
                self.assertIn('UNSUPPORTED_EFFECT_ROUTE',result)
        self.assertEqual([],calls);self.assertEqual([],self.fixture.requests)

    def test_url_bootstrap_stops_at_first_denial_before_model_turn(self):
        runtime=self.service.runtime
        calls=[];execute=runtime.executor.execute
        with patch.object(runtime.executor,'execute',side_effect=lambda *a,**kw:calls.append(a[0]['action']) or execute(*a,**kw)):
            trace=runtime.bootstrap_local_context('read https://example.com/paper')
        self.assertEqual(['browser_start'],calls);self.assertFalse(trace[-1]['result']['success'])


class ToolCLIBoundaryTests(unittest.TestCase):
    def test_real_cli_slash_returns_failure_without_scemda_or_provider_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            env={**os.environ,'AOIA_HOME':temporary,'PYTHONDONTWRITEBYTECODE':'1'}
            result=subprocess.run([sys.executable,'-B','-m','runtime','--cpl-fixture','--command','/scemda'],
                cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(1,result.returncode,result.stderr)
            self.assertIn('UNSUPPORTED_EFFECT_ROUTE',result.stdout)
            self.assertFalse((Path(temporary)/'addons').exists())

class DomainHTTPBoundaryTests(unittest.TestCase):
    setUp=existing_web.CPLWebTests.setUp
    tearDown=existing_web.CPLWebTests.tearDown
    request=existing_web.CPLWebTests.request

    def test_noncomposed_nonzero_mutation_denied_before_lazy_init(self):
        calls=[]
        with patch('nonzero_cloudops.NonZeroCloudOpsService',side_effect=lambda *_args,**_kw:calls.append(1)):
            status,view,_=self.request('POST','/api/nonzero/runs',{'prompt':'synthetic'},
                headers={'X-AIOA-Intent':'nonzero-operator-v1'})
        self.assertEqual(403,status,view);self.assertEqual('UNSUPPORTED_EFFECT_ROUTE',view['error'])
        self.assertEqual([],calls);self.assertIsNone(self.service.runtime._nonzero_service)
        self.assertEqual(200,self.request('GET','/api/nonzero/status')[0])

    def test_memory_patch_mutation_denied_before_operator_adapter(self):
        calls=[]
        with patch.object(self.service.runtime,'memory_patch_operator_request',
                side_effect=lambda *_:calls.append(1) or (200,{'ok':True})):
            status,view,_=self.request('POST','/api/memory-patch/commit',{},
                headers={'X-AIOA-Intent':'memory-patch-operator-v1'})
        self.assertEqual(403,status,view);self.assertEqual([],calls)
        self.assertIn('UNSUPPORTED_EFFECT_ROUTE',view['error']['safe_message'])

    def test_personal_ai_effect_denied_before_service_dispatch(self):
        calls=[]
        with patch.object(self.service,'personal_ai_resume',side_effect=lambda *_:calls.append(1) or {'status':'READY'}):
            status,view,_=self.request('POST','/api/personal-ai/resume',{'operation_id':'synthetic'},
                headers={'X-AIOA-Intent':'personal-ai-resume-v1'})
        self.assertEqual(403,status,view);self.assertEqual('UNSUPPORTED_EFFECT_ROUTE',view['error'])
        self.assertEqual([],calls)
