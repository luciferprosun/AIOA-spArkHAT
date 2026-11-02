#!/usr/bin/env python3
"""Local AOIA-Core web interface and JSON API."""

from __future__ import annotations

import argparse
import json
import os
import traceback
import hmac
import secrets
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from evidence_review import ReviewInputError, bundled_scenario, review_candidate
from main import (
    DEBUG_RAW_RESPONSE,
    PROMPT_FILE,
    AgentRuntime,
    ProviderManager,
    load_prompt_template,
    create_runtime,
)
from providers.exact import ExactCallError, _unique_object


RUNTIME_DIR = Path(__file__).resolve().parent
REPOSITORY_DIR = RUNTIME_DIR.parent
WEB_DIR = REPOSITORY_DIR / "web"
if not (WEB_DIR / 'index.html').is_file():
    WEB_DIR = Path(sys.prefix) / 'share/aioa-sparkhat/web'
HOST = os.getenv("AOIA_WEB_HOST", "127.0.0.1")
PORT = int(os.getenv("AOIA_WEB_PORT", "4311"))
MAX_REQUEST_BYTES = 24_000
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
PERSONAL_AI_OPERATOR_INTENT = "personal-ai-prepare-v1"
PERSONAL_AI_APPROVAL_INTENT = "personal-ai-approve-exact-v1"
PERSONAL_AI_RESUME_INTENT = "personal-ai-resume-v1"


class WebRuntimeService:
    """Shared runtime adapter used by the local AOIA-Core UI."""

    def __init__(self, *, cpl_fixture=False, cpl_cost_policy=None, runtime=None,
                 personal_ai=None, personal_ai_catalog=None,
                 personal_ai_cost_quote=None, native_console=None,
                 meta_missions=None, meta_owner=None, mobile_gateway=None) -> None:
        self.runtime = runtime or create_runtime(cpl_fixture=cpl_fixture, cpl_cost_policy=cpl_cost_policy)
        self.personal_ai = personal_ai
        self.personal_ai_catalog = personal_ai_catalog
        self.personal_ai_cost_quote = personal_ai_cost_quote
        self.meta_missions, self.meta_owner = meta_missions, meta_owner
        if meta_missions is not None:
            from runtime.meta_hackathon.mission_service import MissionService
            if (type(meta_missions) is not MissionService or meta_owner is None
                    or getattr(self.runtime, '_memory_patch_admission', None) is not meta_missions.core
                    or getattr(meta_owner, 'runtime', None) is not self.runtime):
                raise ValueError('META_RUNTIME_CORE_BINDING_REQUIRED')
        if mobile_gateway is not None:
            from runtime.mobile_gateway.service import MobileGateway
            if type(mobile_gateway) is not MobileGateway or mobile_gateway.missions is not meta_missions:
                raise ValueError('MOBILE_SAME_MISSION_CORE_REQUIRED')
        self.mobile_gateway = mobile_gateway
        self.mobile_only=mobile_gateway is not None and mobile_gateway.native_host is not None
        self.unified_profile = meta_missions is not None and hasattr(meta_missions, 'agent_route')
        self.core_mcp = None
        if self.unified_profile:
            from runtime.core_admission import Capability
            from runtime.mcp_bridge.adapter import CoreMissionMCPAdapter
            self.core_mcp = CoreMissionMCPAdapter(meta_missions,
                meta_missions.core.local_operator(Capability.READ), project_root=REPOSITORY_DIR)
        if native_console is not None:
            from runtime.native_console import NativeConsoleBinding
            if type(native_console) is not NativeConsoleBinding:raise ValueError("NATIVE_CONSOLE_BINDING")
            if type(self.runtime) is not AgentRuntime:raise ValueError("NATIVE_CONSOLE_RUNTIME_CORE")
            from runtime.mission.lite_runtime import LiteScheduler
            from runtime.service_guard.service import GuardLoopBinding
            scheduler=getattr(self.runtime,'_lite_scheduler',None)
            if type(scheduler) is not LiteScheduler or type(scheduler.bindings.service_guard) is not GuardLoopBinding:
                raise ValueError("NATIVE_CONSOLE_RUNTIME_CORE")
            guard=getattr(getattr(getattr(scheduler,'bindings',None),'service_guard',None),'guard',None)
            if native_console.guard is None or guard is not native_console.guard:
                raise ValueError("NATIVE_CONSOLE_RUNTIME_CORE")
        self.native_console = native_console
        self.lock = Lock()
        self.csrf_token = secrets.token_urlsafe(32)

    def authority_payload(self):
        from authority_timeline import build_authority_timeline
        value=build_authority_timeline(self.runtime)
        if self.native_console is not None:
            from runtime.core_admission import Capability
            value['native_console']=self.native_console.read(self.native_console.governor.core.local_operator(Capability.READ))
        return value

    def close(self):
        if self.meta_owner is not None:
            self.meta_owner.close()
        else:
            self.runtime.close()

    def meta_request(self, action, payload=None, *, intent=None):
        from runtime.core_admission import Capability
        from runtime.meta_hackathon.mission_service import MissionError
        if self.meta_missions is None:
            raise MissionError('META_RUNTIME_NOT_BOUND')
        service = self.meta_missions
        reader = service.core.local_operator(Capability.READ)
        if action == 'status': return service.status(reader)
        if action == 'preview': return service.preview(payload, reader)
        if action == 'evidence': return service.evidence(payload['task_id'], reader)
        if action == 'stop' and type(payload) is dict and set(payload) == {'task_id'}:
            return service.stop(payload['task_id'], reader)
        if action == 'run' and type(payload) is dict and set(payload) == {'task_id', 'preview_digest'}:
            record = service.evidence(payload['task_id'], reader)
            if record.get('native_spend_binding') == 'BOUND' and intent != 'meta-run-approved-v1':
                raise MissionError('META_NATIVE_OPERATOR_INTENT_REQUIRED')
            return service.run(payload['task_id'], payload['preview_digest'],
                               service.core.local_operator(Capability.OWNER_APPROVAL))
        raise MissionError('META_REQUEST_DENIED')

    def status_payload(self) -> dict:
        if self.meta_missions is not None:
            fixture = self.meta_missions.manager._meta_provider.mode == 'MOCK'
            payload = {'product_name': 'AIOA spArkHAT', 'subtitle': 'METAGuardiansSPARK',
                'meta_profile': True, 'demo': fixture, 'session_id': 'offline-meta-fixture' if fixture else 'native-meta-core',
                'cwd': 'Isolated local fixture' if fixture else 'Native Core host binding', 'model': 'meta_model_api/muse-spark-1.3',
                'available_models': ['meta_model_api/muse-spark-1.3'], 'browser_active': False,
                'current_url': None, 'vault_dir': 'No personal data loaded',
                'tools': ['bounded offline document read'] if fixture else ['Core-approved advisory model request; browser blocked'], 'previous_commands': [], 'recent_outputs': [],
                'open_tabs': [], 'critical_loop': {'enabled': False, 'mode': 'OFFLINE_FIXTURE' if fixture else 'LIVE_PENDING_AUTHORIZATION',
                    'authority': 'ADVISORY_ONLY', 'live_enabled': False, 'run_ids': [], 'session_budget_usd': '0'},
                'assistant': {'default_mode': 'meta', 'plain_chat': 'DISABLED'}}
            if self.unified_profile:
                from runtime.meta_hackathon.web_agent import status
                payload.update(status(self))
            return payload
        owner = getattr(self, 'personal_ai_demo_owner', None)
        if owner is not None:
            return {'product_name': 'AIOA spArkHAT', 'demo': True, 'session_id': 'isolated-personal-ai-demo',
                'cwd': str(owner.root), 'model': 'nebius/' + owner.runtime._lite_scheduler.profile.model_id,
                'available_models': [], 'browser_active': False, 'current_url': None,
                'vault_dir': 'Private native HAT backend; content hidden', 'tools': [],
                'previous_commands': [], 'recent_outputs': [], 'open_tabs': [],
                'critical_loop': {'enabled': False, 'mode': 'TEST' if owner.mode == 'FIXTURE' else 'LIVE_PENDING_AUTHORIZATION',
                    'authority': 'ADVISORY_ONLY', 'live_enabled': False, 'session_budget_usd': '0', 'run_ids': [],
                    'status': 'USE_PERSONAL_AI_PREPARE'},
                'evidence_review': {'enabled': True, 'provider_call': False, 'authority': 'METADATA_ONLY_NO_AUTHORITY'},
                'assistant': {'default_mode': 'personal-ai-demo', 'plain_chat': 'DISABLED'}}
        payload = self.runtime.snapshot_status()
        payload["available_models"] = self.runtime.provider_manager.available_models()
        payload["evidence_review"] = {
            "enabled": True,
            "provider_call": False,
            "authority": "METADATA_ONLY_NO_AUTHORITY",
        }
        payload['critical_loop'] = self.runtime.critical_loop.status()
        payload['assistant'] = {'default_mode': 'cpl', 'plain_chat': 'EXPLICIT_BYPASS_ONLY'}
        return payload

    def agent_request(self, action, payload=None, *, intent=None):
        from runtime.meta_hackathon.web_agent import request
        return request(self, action, payload, intent=intent)

    def switch_model(self, model_name: str) -> dict:
        with self.lock:
            selected = self.runtime.provider_manager.switch_model(model_name)
            return {
                "ok": True,
                "model": selected,
                "notice": self.runtime.provider_manager.model_notice(selected),
                "status": self.status_payload(),
            }

    def run_prompt(self, prompt: str, *, mode='cpl', plan_options=None) -> dict:
        with self.lock:
            result = self.runtime.assistant_request(prompt, mode=mode, plan_options=plan_options)
            result['status'] = self.status_payload()
            return result

    def _personal_ai_projection(self, status):
        from competition_view import project_nebius_personal_ai
        from runtime.personal_ai_demo import PersonalAIDemoService

        if (
            type(self.personal_ai) is not PersonalAIDemoService
            or type(self.personal_ai_catalog) is not dict
            or type(self.personal_ai_cost_quote) is not dict
        ):
            raise RuntimeError("PERSONAL_AI_NOT_CONFIGURED")
        scheduler = self.personal_ai.bindings.scheduler
        value = project_nebius_personal_ai(
            status,
            scheduler.journal.reservations(),
            catalog=self.personal_ai_catalog,
            cost_quote=self.personal_ai_cost_quote,
            expected_execution_mode=self.personal_ai.bindings.execution_mode,
        )
        owner = getattr(self, "personal_ai_demo_owner", None)
        if owner is not None:
            value["judge"] = owner.readiness()
        return value

    def personal_ai_status(self):
        if self.personal_ai is None:
            raise RuntimeError("PERSONAL_AI_NOT_CONFIGURED")
        operation_id = self.personal_ai.bindings.scheduler.bindings.service_guard.operation_id
        from runtime.personal_ai_demo import PersonalAIDemoError
        try:
            return self._personal_ai_projection(self.personal_ai.status(operation_id))
        except PersonalAIDemoError as error:
            owner = getattr(self, 'personal_ai_demo_owner', None)
            if error.code != 'OPERATION_BINDING_MISMATCH' or owner is None:
                raise
            return {'status': 'READY', 'state': 'NOT_PREPARED', 'configured': True,
                'provider': {'provider_id': 'nebius', 'model_id': owner.runtime._lite_scheduler.profile.model_id,
                    'mode': owner.mode, 'execution_mode': owner.mode, 'authority': 'ADVISORY_ONLY', 'fallback': False},
                'target': {'mode': 'FIXTURE'}, 'judge': owner.readiness(), 'service_guard': {'state': 'NOT_PREPARED'},
                'blocked_reason': 'BLOCKED_BY_ADDITIONAL_COST_AUTHORIZATION' if owner.mode == 'LIVE' else None}

    def personal_ai_prepare(self, payload):
        if self.personal_ai is None:
            raise RuntimeError("PERSONAL_AI_NOT_CONFIGURED")
        with self.lock:
            owner = getattr(self, "personal_ai_demo_owner", None)
            if owner is not None:
                owner.validate_judge_request(payload)
            return self._personal_ai_projection(self.personal_ai.prepare(payload))

    def personal_ai_approve(self, proposal_id):
        if self.personal_ai is None:
            raise RuntimeError("PERSONAL_AI_NOT_CONFIGURED")
        with self.lock:
            return self._personal_ai_projection(self.personal_ai.approve(proposal_id))

    def personal_ai_resume(self, operation_id):
        if self.personal_ai is None:
            raise RuntimeError("PERSONAL_AI_NOT_CONFIGURED")
        with self.lock:
            return self._personal_ai_projection(self.personal_ai.resume(operation_id))

    def personal_ai_restart(self, operation_id):
        from runtime.personal_ai_demo import PersonalAIDemoError
        with self.lock:
            owner = getattr(self, 'personal_ai_demo_owner', None)
            if owner is None:
                raise PersonalAIDemoError('DEMO_RESTART_NOT_CONFIGURED')
            # Validate before closing; a restart cannot execute an unconsumed approval.
            current = self.personal_ai.status(operation_id)
            if current['state'] not in {'EXECUTED', 'RECONCILED'}:
                raise PersonalAIDemoError('RECONCILE_STATE_DENIED')
            from runtime.personal_ai_demo_launcher import DemoComposition
            root, mode = owner.root, owner.mode
            owner.close()
            restarted = DemoComposition(root, mode=mode)
            self.runtime, self.personal_ai = restarted.runtime, restarted.personal_ai
            self.personal_ai_catalog, self.personal_ai_cost_quote = restarted.catalog, restarted.quote
            self.personal_ai_demo_owner = restarted
            return self._personal_ai_projection(self.personal_ai.reconcile_restart(operation_id))

    def personal_ai_replay(self, operation_id):
        from runtime.personal_ai_demo import PersonalAIDemoError
        with self.lock:
            current = self.personal_ai.status(operation_id)
            if current['state'] not in {'RECONCILED', 'REPLAY_BLOCKED'}:
                raise PersonalAIDemoError('REPLAY_STATE_DENIED')
            return self._personal_ai_projection(self.personal_ai.resume(operation_id))


_SERVICE: WebRuntimeService | None = None
_SERVICE_LOCK = Lock()


def get_service() -> WebRuntimeService:
    """Initialize the model runtime only when an endpoint needs it."""

    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = WebRuntimeService()
    return _SERVICE


class AOIAWebHandler(SimpleHTTPRequestHandler):
    """Serve one static AOIA-Core UI and its bounded local APIs."""

    server_version = "AOIA-Core/1.0"

    def __init__(self, *args, service: WebRuntimeService | None = None, **kwargs):
        self.runtime_service = service
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _service(self) -> WebRuntimeService:
        return self.runtime_service or get_service()

    def parse_request(self):
        if not super().parse_request():return False
        if getattr(self.runtime_service,'mobile_only',False):
            if (self.command not in {'GET','POST'} or len(self.path)>2048 or
                    not self.path.startswith('/api/mobile/v1/') or any(c in self.path for c in ('?','#','%','\\'))):
                self.send_error(404);return False
        return True

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if not self._check_local_request():
            return
        if parsed.path.startswith('/api/mobile/'):
            self._handle_mobile('GET')
            return
        if parsed.path.startswith('/api/agent/'):
            if self._check_token(): self._handle_agent('GET', parsed, None)
            return
        if parsed.path.startswith('/api/meta/'):
            if self._check_token(): self._handle_meta('GET', parsed, None)
            return
        if getattr(self.runtime_service, 'meta_missions', None) is not None and parsed.path.startswith('/api/') and parsed.path not in {
                '/api/session', '/api/status', '/api/models', '/api/health', '/api/review/scenario'}:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {'ok': False, 'error': 'META_PROFILE_ONLY'})
            return
        if parsed.path.startswith("/api/memory-patch"):
            if self._check_memory_patch_operator():
                self._handle_memory_patch("GET", parsed, {})
            return
        if parsed.path == '/api/session':
            self._write_json(HTTPStatus.OK, {'token': self._service().csrf_token,
                                           'product_name': 'AIOA spArkHAT'})
            return
        if parsed.path == '/api/authority-timeline':
            if not self._check_token():
                return
            from authority_timeline import build_authority_timeline
            self._write_json(
                HTTPStatus.OK, self._service().authority_payload()
            )
            return
        if parsed.path == '/api/competition-demo':
            if not self._check_token():
                return
            from competition_view import load_competition_demo
            self._write_json(HTTPStatus.OK, load_competition_demo())
            return
        if parsed.path == '/api/competition-evaluation':
            if not self._check_token():
                return
            from competition_evaluation import competition_evaluation
            self._write_json(HTTPStatus.OK, competition_evaluation())
            return
        if parsed.path == '/api/provider-availability':
            if not self._check_token():
                return
            from provider_availability import provider_availability
            self._write_json(HTTPStatus.OK, provider_availability())
            return
        if parsed.path == '/api/personal-ai/status':
            if not self._check_token():
                return
            if parsed.query or parsed.fragment or parsed.params:
                self._write_json(HTTPStatus.BAD_REQUEST,
                                 {'ok': False, 'error': 'INVALID_PERSONAL_AI_REQUEST'})
                return
            self._handle_personal_ai('status', None)
            return
        if parsed.path.startswith('/api/nonzero/'):
            if not self._check_token():
                return
            self._handle_nonzero('GET', parsed, None)
            return
        if parsed.path.startswith('/api/cpl/'):
            if not self._check_token():
                return
            owner = getattr(self._service(), 'personal_ai_demo_owner', None)
            if owner is not None:
                if parsed.path == '/api/cpl/status':
                    self._write_json(HTTPStatus.OK, self._service().status_payload()['critical_loop'])
                elif parsed.path == '/api/cpl/preset':
                    self._write_json(HTTPStatus.OK, {'schema': 'aioa.cpl-preset.v1', 'enabled': False,
                        'preset_id': 'personal-ai-demo-only', 'scope': 'TEST' if owner.mode == 'FIXTURE' else 'LIVE_PENDING_AUTHORIZATION',
                        'primary_model': 'fixture/synthetic', 'observer_models': [], 'roles': [],
                        'live_preconditions_ready': False, 'blocking_reasons': ['USE_PERSONAL_AI_PREPARE'],
                        'authority': 'ADVISORY_ONLY', 'read_only': True})
                else:
                    self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {'ok': False, 'error': 'USE_PERSONAL_AI_PREPARE'})
                return
            try:
                service = self._service().runtime.critical_loop
                if parsed.path == '/api/cpl/status':
                    payload = service.status()
                elif parsed.path == '/api/cpl/preset':
                    from critical_loop.preset import build_openrouter_cpl_preset
                    payload = build_openrouter_cpl_preset(service)
                elif parsed.path == '/api/cpl/fixture':
                    from critical_loop.fixture import FIXTURE_PROMPT, FIXTURE_EVIDENCE
                    payload = {'prompt': FIXTURE_PROMPT, 'evidence': FIXTURE_EVIDENCE,
                               'scope': 'SYNTHETIC_TEST_DATA', 'model': 'fixture/synthetic'}
                elif parsed.path.startswith('/api/cpl/runs/'):
                    tail = parsed.path.removeprefix('/api/cpl/runs/')
                    payload = service.verify(tail[:-6]) if tail.endswith('/trace') else service.get(tail)
                else:
                    self._write_json(HTTPStatus.NOT_FOUND, {'ok': False, 'error': 'not_found'})
                    return
                self._write_json(HTTPStatus.OK, payload)
            except ExactCallError as error:
                self._write_cpl_error(error)
            return
        if parsed.path == "/api/health":
            owner = getattr(self._service(), "personal_ai_demo_owner", None)
            if owner is not None:
                self._write_json(HTTPStatus.OK, owner.readiness())
                return
            self._write_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "system": "AOIA-Core",
                    "product_name": "AIOA spArkHAT",
                    "network": "local-only",
                    "evidence_review": "enabled",
                },
            )
            return
        if parsed.path == "/api/status":
            if self._service().unified_profile and not self._check_token(): return
            self._write_json(HTTPStatus.OK, self._service().status_payload())
            return
        if parsed.path == "/api/models":
            service = self._service()
            if service.unified_profile and not self._check_token(): return
            self._write_json(
                HTTPStatus.OK,
                {
                    "current_model": service.runtime.provider_manager.describe(),
                    "available_models": service.runtime.provider_manager.available_models(),
                },
            )
            return
        if parsed.path == "/api/review/scenario":
            self._write_json(HTTPStatus.OK, bundled_scenario())
            return
        if parsed.path in {"/", "/index.html"}:
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if not self._check_local_request():
            return
        if parsed.path.startswith('/api/mobile/'):
            self._handle_mobile('POST')
            return
        if parsed.path.startswith('/api/agent/'):
            if not self._check_token(): return
            intents={'/api/agent/propose':'agent-propose-v2','/api/agent/git-preview':'agent-propose-v2',
                '/api/agent/install-preview':'agent-propose-v2','/api/agent/run':'agent-approve-offline-exact-v2',
                '/api/agent/stop':'agent-stop-v2','/api/agent/mcp/submit':'agent-mcp-propose-v2',
                '/api/agent/reconcile':'agent-readback-v2'}
            expected=intents.get(parsed.path)
            if expected is None or self.headers.get_all('X-AIOA-Intent',[]) != [expected]:
                self._write_json(HTTPStatus.FORBIDDEN,{'ok':False,'error':'AGENT_EXACT_INTENT_REQUIRED','automatic_retry':False})
                return
            payload=self._read_json_body()
            if payload is not None:self._handle_agent('POST',parsed,payload)
            return
        if parsed.path.startswith('/api/meta/'):
            if not self._check_token(): return
            intents = {'/api/meta/preview': 'meta-preview-v1', '/api/meta/run': 'meta-run-fixture-v1',
                       '/api/meta/stop': 'meta-stop-v1'}
            accepted = [intents.get(parsed.path)]
            if parsed.path == '/api/meta/run': accepted.append('meta-run-approved-v1')
            if self.headers.get_all('X-AIOA-Intent', []) not in [[value] for value in accepted]:
                self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'META_OPERATOR_INTENT_REQUIRED'})
                return
            payload = self._read_json_body()
            if payload is not None: self._handle_meta('POST', parsed, payload)
            return
        if getattr(self.runtime_service, 'meta_missions', None) is not None:
            self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'META_PROFILE_ONLY'})
            return
        if parsed.path.startswith("/api/memory-patch"):
            if not self._check_memory_patch_operator():
                return
            payload = self._read_json_body()
            if payload is not None:
                self._handle_memory_patch("POST", parsed, payload)
            return
        if parsed.path.startswith('/api/personal-ai/'):
            if not self._check_token():
                return
            actions = {
                '/api/personal-ai/prepare': ('prepare', PERSONAL_AI_OPERATOR_INTENT),
                '/api/personal-ai/approve': ('approve', PERSONAL_AI_APPROVAL_INTENT),
                '/api/personal-ai/resume': ('resume', PERSONAL_AI_RESUME_INTENT),
                '/api/personal-ai/restart': ('restart', 'personal-ai-restart-v1'),
                '/api/personal-ai/replay': ('replay', 'personal-ai-replay-v1'),
            }
            selected = actions.get(parsed.path)
            if selected is None or parsed.query or parsed.fragment or parsed.params:
                self._write_json(HTTPStatus.NOT_FOUND,
                                 {'ok': False, 'error': 'not_found'})
                return
            action, expected_intent = selected
            if self.headers.get_all('X-AIOA-Intent', []) != [expected_intent]:
                intent_name = {
                    'prepare': 'OPERATOR', 'approve': 'APPROVAL', 'resume': 'RESUME', 'restart': 'RESTART', 'replay': 'REPLAY'
                }[action]
                self._write_json(
                    HTTPStatus.FORBIDDEN,
                    {'ok': False, 'error': f'PERSONAL_AI_{intent_name}_INTENT_REQUIRED'},
                )
                return
            payload = self._read_json_body()
            if payload is not None:
                self._handle_personal_ai(action, payload)
            return
        if (parsed.path.startswith(('/api/cpl/', '/api/nonzero/')) or parsed.path in {'/api/chat', '/api/model'}) and not self._check_token():
            return
        if parsed.path.startswith('/api/nonzero/') and self.headers.get('X-AIOA-Intent') != 'nonzero-operator-v1':
            self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'NONZERO_OPERATOR_INTENT_REQUIRED'})
            return
        payload = self._read_json_body()
        if payload is None:
            return
        if getattr(self._service(), 'personal_ai_demo_owner', None) is not None and (
                parsed.path.startswith('/api/cpl/') or parsed.path in {'/api/chat', '/api/model'}):
            self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'DEMO_PERSONAL_AI_ONLY'})
            return
        if parsed.path.startswith('/api/nonzero/'):
            self._handle_nonzero('POST', parsed, payload)
            return

        try:
            if parsed.path == '/api/cpl/plan':
                self._write_json(HTTPStatus.CREATED, self._service().runtime.plan_critical_loop(payload))
                return
            if parsed.path == '/api/cpl/start':
                if set(payload) != {'run_id', 'plan_hash', 'nonce'}:
                    raise ExactCallError('INVALID_START_FIELDS')
                result = self._service().runtime.critical_loop.start(
                    payload['run_id'], payload['plan_hash'], payload['nonce'], approval_source='LOCAL_HTTP_NONCE')
                self._write_json(HTTPStatus.ACCEPTED, result)
                return
            if parsed.path == '/api/cpl/cancel':
                if set(payload) != {'run_id'}:
                    raise ExactCallError('INVALID_CANCEL_FIELDS')
                self._write_json(HTTPStatus.OK, self._service().runtime.critical_loop.cancel(payload['run_id']))
                return
            if parsed.path == '/api/cpl/verify':
                if set(payload) != {'run_id', 'manifest'}:
                    raise ExactCallError('INVALID_VERIFY_FIELDS')
                self._write_json(HTTPStatus.OK, self._service().runtime.critical_loop.verify(payload['run_id'], payload['manifest']))
                return
            if parsed.path == "/api/chat":
                options = {key: value for key, value in payload.items() if key not in {'prompt', 'mode'}}
                result = self._service().run_prompt(payload.get('prompt'),
                    mode=payload.get('mode', 'cpl'), plan_options=options)
                status = HTTPStatus.FORBIDDEN if result.get('ok') is False else (
                    HTTPStatus.CREATED if result['mode'] == 'cpl' else HTTPStatus.OK)
                self._write_json(status, result)
                return

            if parsed.path == "/api/model":
                model_name = str(payload.get("model", "")).strip()
                if not model_name:
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {"ok": False, "error": "model is required"},
                    )
                    return
                self._write_json(HTTPStatus.OK, self._service().switch_model(model_name))
                return

            if parsed.path == "/api/review":
                try:
                    result = review_candidate(payload.get("candidate_answer"))
                except ReviewInputError as error:
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {"ok": False, "error": "invalid_request", "detail": str(error)},
                    )
                    return
                self._write_json(HTTPStatus.OK, result)
                return

            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        except ExactCallError as error:
            self._write_cpl_error(error)
        except Exception as error:  # pragma: no cover - local debugging path
            if DEBUG_RAW_RESPONSE:
                traceback.print_exc()
            self._write_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "internal_error"},
            )

    def _handle_nonzero(self, method, parsed, payload):
        from nonzero_cloudops import NonZeroError
        try:
            if parsed.query or parsed.fragment:
                raise NonZeroError('NONZERO_QUERY_NOT_ALLOWED', 400)
            if method == 'GET' and parsed.path == '/api/nonzero/status':
                self._write_json(HTTPStatus.OK, self._service().runtime.nonzero_status())
                return
            self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'UNSUPPORTED_EFFECT_ROUTE',
                                                       'effect_status': 'UNSUPPORTED'})
        except NonZeroError as error:
            self._write_json(error.status, {'ok': False, 'error': error.code})
        except Exception:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {'ok': False, 'error': 'NONZERO_STATE_OR_DEPENDENCY_UNAVAILABLE'})

    def _handle_personal_ai(self, action, payload):
        from runtime.personal_ai_demo import PersonalAIDemoError

        if action != 'status':
            self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'UNSUPPORTED_EFFECT_ROUTE',
                                                   'effect_status': 'UNSUPPORTED'})
            return

        try:
            result = self._service().personal_ai_status()
            if result.get('status') != 'READY':
                self._write_json(HTTPStatus.SERVICE_UNAVAILABLE,
                                 {'ok': False, 'error': 'PERSONAL_AI_PROJECTION_INVALID'})
                return
            self._write_json(HTTPStatus.OK, result)
        except PersonalAIDemoError as error:
            conflicts = {
                'PROPOSAL_BINDING_MISMATCH', 'PERSONAL_AI_OPERATION_CONFLICT',
                'APPROVAL_STATE_DENIED', 'RESUME_STATE_DENIED',
                'OPERATION_BINDING_MISMATCH',
            }
            status = HTTPStatus.CONFLICT if error.code in conflicts else HTTPStatus.BAD_REQUEST
            self._write_json(status, {'ok': False, 'error': error.code})
        except (KeyError, RuntimeError):
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE,
                             {'ok': False, 'error': 'PERSONAL_AI_NOT_CONFIGURED'})

    def _check_memory_patch_operator(self):
        from runtime.memory_patch.contract import OPERATOR_INTENT

        if not self._check_token():
            return False
        if self.headers.get_all("X-AIOA-Intent", []) != [OPERATOR_INTENT]:
            self._write_json(
                HTTPStatus.FORBIDDEN, {"ok": False, "error": "operator_intent_required"}
            )
            return False
        return True

    def _handle_memory_patch(self, method, parsed, payload):
        from runtime.memory_patch.contract import OPERATION_CAPABILITIES
        from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
        from runtime.memory_patch.views import error_response

        operation = "invalid"
        try:
            if (
                parsed.query
                or parsed.fragment
                or parsed.params
                or not parsed.path.startswith("/api/memory-patch/")
            ):
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
            operation = parsed.path.removeprefix("/api/memory-patch/")
            if operation != "status" and operation not in OPERATION_CAPABILITIES:
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
            if method == "GET" and operation not in {"status", "list", "review-queue"}:
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
            if operation != 'status':
                status, result = error_response(operation, MemoryPatchError(ErrorCode.ADMISSION_DENIED))
                result['error']['safe_message'] = 'UNSUPPORTED_EFFECT_ROUTE: native authority and containment required.'
                self._write_json(status, result)
                return
            status, result = self._service().runtime.memory_patch_operator_request(
                operation, payload
            )
        except Exception as error:
            status, result = error_response(operation, error)
        self._write_json(status, result)

    def _handle_agent(self, method, parsed, payload):
        import re
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        try:
            if parsed.query or parsed.params or parsed.fragment:raise ValueError('AGENT_QUERY_DENIED')
            fixed={('GET','/api/agent/status'):'status',('GET','/api/agent/providers'):'providers',
                ('POST','/api/agent/propose'):'propose',('POST','/api/agent/run'):'run',
                ('POST','/api/agent/stop'):'stop',('POST','/api/agent/git-preview'):'git-preview',
                ('POST','/api/agent/install-preview'):'install-preview',('POST','/api/agent/mcp/submit'):'mcp-submit',
                ('POST','/api/agent/reconcile'):'reconcile'}
            action=fixed.get((method,parsed.path))
            if method=='GET' and parsed.path.startswith('/api/agent/tasks/'):
                action,payload='view',{'task_id':parsed.path.removeprefix('/api/agent/tasks/')}
            if method=='GET' and parsed.path.startswith('/api/agent/mcp/results/'):
                action,payload='mcp-result',{'task_id':parsed.path.removeprefix('/api/agent/mcp/results/')}
            if method=='GET' and parsed.path.startswith('/api/agent/proposals/'):
                action,payload='proposal-readback',{'request_id':parsed.path.removeprefix('/api/agent/proposals/')}
            if action is None:raise ValueError('AGENT_ROUTE_DENIED')
            result=self._service().agent_request(action,payload,intent=self.headers.get('X-AIOA-Intent'))
            self._write_json(HTTPStatus.ACCEPTED if action=='run' else HTTPStatus.OK,result)
        except CommitOutcomeUnknown:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE,{'ok':False,'error':'AGENT_ACK_UNKNOWN_READBACK_REQUIRED','automatic_retry':False})
        except Exception as error:
            code=str(error)
            if not re.fullmatch(r'(?:AGENT|MCP|LOCAL|CORE)_[A-Z0-9_]{1,72}',code):code='AGENT_REQUEST_DENIED'
            self._write_json(HTTPStatus.BAD_REQUEST,{'ok':False,'error':code,'automatic_retry':False})

    def _handle_meta(self, method, parsed, payload):
        from runtime.meta_hackathon.mission_service import MissionError
        try:
            if parsed.query or parsed.fragment or parsed.params:
                raise MissionError('META_REQUEST_DENIED')
            if method == 'GET' and parsed.path == '/api/meta/status': action = 'status'
            elif method == 'GET' and parsed.path.startswith('/api/meta/evidence/'):
                action, payload = 'evidence', {'task_id': parsed.path.removeprefix('/api/meta/evidence/')}
            elif method == 'POST' and parsed.path in ('/api/meta/preview', '/api/meta/run', '/api/meta/stop'):
                action = parsed.path.rsplit('/', 1)[-1]
            else: raise MissionError('META_REQUEST_DENIED')
            result = self._service().meta_request(action, payload, intent=self.headers.get('X-AIOA-Intent'))
            self._write_json(HTTPStatus.ACCEPTED if action == 'run' else HTTPStatus.OK, result)
        except Exception as error:
            code = getattr(error, 'code', 'META_REQUEST_DENIED')
            if not isinstance(code, str) or not code.startswith(('META_', 'CORE_')): code = 'META_REQUEST_DENIED'
            status = HTTPStatus.FORBIDDEN if 'OWNER_GO' in code or 'ADMISSION' in code else (
                HTTPStatus.CONFLICT if code in ('META_MISSION_ACTIVE', 'META_MISSION_NOT_PREVIEWED') else
                HTTPStatus.SERVICE_UNAVAILABLE if code == 'META_RUNTIME_NOT_BOUND' else HTTPStatus.BAD_REQUEST)
            self._write_json(status, {'ok': False, 'error': code})

    def _handle_mobile(self, method):
        """Exact raw-body signature, independent of the loopback UI credential."""
        from runtime.mobile_gateway import wire
        self.close_connection = True
        gateway = getattr(self._service(), 'mobile_gateway', None)
        try:
            if gateway is None:
                raise wire.MobileError(503)
            critical = ('Authorization', 'X-AIOA-Nonce', 'X-AIOA-Issued-At', 'X-AIOA-Audience',
                'X-AIOA-Source-SHA', 'X-AIOA-Capsule', 'X-AIOA-Signature', 'X-AIOA-Challenge',
                'Content-Length', 'Content-Type')
            if any(len(self.headers.get_all(h, [])) > 1 for h in critical):
                raise wire.MobileError()
            if self.headers.get('Transfer-Encoding') or any(self.headers.get(h) for h in
                    ('Forwarded', 'X-Forwarded-Host', 'X-Forwarded-Proto')):
                raise wire.MobileError()
            value = self.headers.get('Content-Length', '0')
            if not value.isascii() or not value.isdecimal() or len(value) > 6:
                raise wire.MobileError()
            length = int(value)
            if length > wire.BODY_LIMIT:
                raise wire.MobileError(413)
            if method == 'GET' and length:
                raise wire.MobileError()
            if method == 'POST' and (length == 0 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'):
                raise wire.MobileError()
            self.connection.settimeout(8)
            raw = self.rfile.read(length) if length else b''
            if len(raw) != length:
                raise wire.MobileError()
            status, payload = gateway.handle(method, self.path,
                {h:self.headers.get(h, '') for h in critical}, raw)
        except wire.MobileError as exc:
            status, payload = exc.status, {'ok':False,'error':exc.code,'automatic_retry':False}
        except (OSError, TimeoutError):
            status, payload = 503, {'ok':False,'error':wire.ERRORS[503],'automatic_retry':False}
        body = wire.canonical(payload)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_local_request(self):
        port = self.server.server_address[1]
        allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        mobile_only=getattr(self.runtime_service,'mobile_only',False)
        if mobile_only:
            import ssl
            owner=self.runtime_service.mobile_gateway.native_host
            allowed_hosts={urlparse(owner.origin).netloc}
            if not isinstance(self.connection,ssl.SSLSocket) or self.connection.version()!='TLSv1.3':
                self._write_json(403,{'ok':False,'error':'TLS_REQUIRED'});return False
        hosts = self.headers.get_all('Host', [])
        origins = self.headers.get_all('Origin', [])
        valid_origin = not origins or (len(origins) == 1 and origins[0] in {('https://' if mobile_only else 'http://') + host for host in allowed_hosts})
        if (len(hosts) != 1 or hosts[0].lower() not in allowed_hosts or not valid_origin
                or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
            self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'local_origin_required'})
            return False
        return True

    def _check_token(self):
        values = self.headers.get_all('X-AIOA-Session-Token', [])
        if len(values) != 1 or not hmac.compare_digest(values[0].encode('utf-8'), self._service().csrf_token.encode('ascii')):
            self._write_json(HTTPStatus.FORBIDDEN, {'ok': False, 'error': 'session_token_required'})
            return False
        return True

    def _write_cpl_error(self, error):
        conflicts = {'AUTHORIZATION_ALREADY_CONSUMED', 'CPL_WORKER_BUSY', 'PLAN_EXPIRED', 'RUN_TERMINAL'}
        status = HTTPStatus.CONFLICT if error.code in conflicts else HTTPStatus.BAD_REQUEST
        if error.code in {'RUN_NOT_FOUND', 'PLAN_NOT_AVAILABLE'}:
            status = HTTPStatus.NOT_FOUND
        self._write_json(status, {'ok': False, 'error': error.code})

    def log_message(self, format: str, *args: object) -> None:
        # Request bodies and candidate answers are never logged.
        return

    def _read_json_body(self) -> dict | None:
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            self._write_json(HTTPStatus.BAD_REQUEST, {'ok': False, 'error': 'invalid_body_framing'})
            return None
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_content_length"},
            )
            return None
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._write_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"ok": False, "error": "request_size_out_of_bounds"},
            )
            return None
        self.connection.settimeout(5)
        try:
            raw_body = self.rfile.read(length)
        except (TimeoutError, OSError):
            self._write_json(HTTPStatus.REQUEST_TIMEOUT, {'ok': False, 'error': 'request_body_timeout'})
            return None
        if len(raw_body) != length:
            self._write_json(HTTPStatus.BAD_REQUEST, {'ok': False, 'error': 'incomplete_request_body'})
            return None
        try:
            payload = json.loads(raw_body.decode("utf-8"), object_pairs_hook=_unique_object,
                                 parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
        except (UnicodeDecodeError, ValueError, RecursionError):
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_json_body"},
            )
            return None
        if not isinstance(payload, dict):
            self._write_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "request_body_must_be_an_object"},
            )
            return None
        return payload

    def _write_json(self, status: HTTPStatus, payload: object) -> None:
        if urlparse(self.path).path.startswith("/api/memory-patch") and (
            not isinstance(payload, dict)
            or set(payload) != {"ok", "module", "operation", "result", "error"}
        ):
            # Shared Core admission/framing failures also use the closed native
            # envelope. No raw Core exception or request echo crosses this route.
            from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
            from runtime.memory_patch.views import error_response

            code = (
                ErrorCode.ADMISSION_DENIED
                if status == HTTPStatus.FORBIDDEN
                else ErrorCode.INVALID_REQUEST
            )
            _, payload = error_response("invalid", MemoryPatchError(code))
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_mobile_operator_server(owner):
    """Private OS-peer authenticated transport of this same Core instance."""
    import socket,socketserver,stat,struct
    from runtime.core_admission import AdmissionError
    from runtime.mobile_gateway import wire
    owner.operator_principal()
    path=owner.root/'operator.sock'
    if path.exists() or path.is_symlink():
        info=path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=owner.uid:raise AdmissionError()
        path.unlink()  # Only our stale socket, after the exclusive runtime lease.
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(10)
            try:
                _,uid,_=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if uid!=owner.uid:raise AdmissionError()
                raw=self.rfile.readline(wire.BODY_LIMIT+1)
                if not raw.endswith(b'\n'):raise wire.MobileError(400)
                data=owner.operator_request(uid,wire.strict_json(raw))
                result={'ok':True,'data':data}
                if len(wire.canonical(result))>wire.BODY_LIMIT:raise wire.MobileError(413)
            except wire.MobileError as error:result={'ok':False,'error':error.code,'automatic_retry':False}
            except Exception:result={'ok':False,'error':'NATIVE_OPERATOR_DENIED_OR_UNKNOWN','automatic_retry':False}
            self.wfile.write(wire.canonical(result)+b'\n')
    class Server(socketserver.ThreadingUnixStreamServer):daemon_threads=True
    server=Server(str(path),Handler);os.chmod(path,0o600)
    return server


def mobile_operator_client(root,value):
    import socket,stat,struct
    from runtime.mobile_gateway import wire
    root=Path(root).absolute();path=root/'operator.sock';info=path.lstat()
    if (root.resolve()!=root or root.stat().st_uid!=os.getuid() or root.stat().st_mode&0o077
            or not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077):
        raise ValueError('NATIVE_OPERATOR_SOCKET_DENIED')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as peer:
        peer.settimeout(10);peer.connect(str(path))
        _,uid,_=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid!=os.getuid():raise ValueError('NATIVE_OPERATOR_PEER_DENIED')
        peer.sendall(wire.canonical(value)+b'\n')
        with peer.makefile('rb') as stream:raw=stream.readline(wire.BODY_LIMIT+1)
        if not raw.endswith(b'\n'):raise ValueError('UNKNOWN_NO_AUTOMATIC_RETRY')
        return wire.strict_json(raw)


def make_server(
    host: str = HOST,
    port: int = PORT,
    service: WebRuntimeService | None = None,
    *,tls_certificate=None,tls_key=None,
) -> ThreadingHTTPServer:
    """Create the single local AOIA-Core server."""

    if host not in LOOPBACK_HOSTS:
        raise ValueError("AOIA-Core web UI may bind only to a loopback interface")
    handler = partial(AOIAWebHandler, service=service)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    if getattr(service,'mobile_only',False):
        import ssl,stat
        try:
            for path,private in ((tls_certificate,False),(tls_key,True)):
                path=Path(path);info=path.lstat()
                if (not stat.S_ISREG(info.st_mode) or path.resolve()!=path.absolute() or info.st_uid!=os.getuid()
                        or info.st_nlink!=1 or info.st_size>65536 or info.st_mode&(0o077 if private else 0o022)):
                    raise ValueError('MOBILE_PRIVATE_TLS_FILES_REQUIRED')
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_3
            context.load_cert_chain(tls_certificate,tls_key)
            server.socket=context.wrap_socket(server.socket,server_side=True)
        except BaseException:server.server_close();raise
    elif tls_certificate is not None or tls_key is not None:
        server.server_close();raise ValueError('MOBILE_NATIVE_TLS_BINDING_REQUIRED')
    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local AIOA spArkHAT web interface (formerly AOIA-Core).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--cpl-fixture', action='store_true', help='Explicit local synthetic HTTP transport; no model API')
    mode.add_argument('--cpl-live-policy', help='Operator-authored price/budget policy JSON; still requires per-plan approval')
    mode.add_argument('--meta-offline', action='store_true', help='One existing UI, isolated Meta fixture, zero spend')
    mode.add_argument('--unified-offline', action='store_true', help='One app: Core-gated local recipes, MCP and signed mobile fixture; no paid calls')
    mode.add_argument('--mobile-native',action='store_true',help='System-authenticated private mobile status only; no model, task execution or fixture')
    mode.add_argument('--mobile-operator',choices=('settings','enroll','status','revoke'),help='Private native operator socket; code stays local')
    mode.add_argument('--meta-live-one-shot', action='store_true', help='Inspect the explicit one-shot LIVE gate; never implies owner GO')
    parser.add_argument('--state-dir', help='Private state directory for the explicit Meta offline profile')
    parser.add_argument('--mobile-origin')
    parser.add_argument('--mobile-tls-certificate')
    parser.add_argument('--mobile-tls-key')
    parser.add_argument('--device-spki',help='Exact public phone SPKI for native enrollment/revocation')
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", default=PORT, type=int)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.mobile_operator:
        if not args.state_dir:raise SystemExit('NATIVE_STATE_REQUIRED')
        value={'op':args.mobile_operator}
        if args.mobile_operator in ('enroll','revoke'):value['device_spki']=args.device_spki
        if args.mobile_operator=='enroll':value['request_id']=secrets.token_hex(16)
        try:result=mobile_operator_client(args.state_dir,value)
        except Exception:result={'ok':False,'error':'UNKNOWN_NO_AUTOMATIC_RETRY','automatic_retry':False}
        print(json.dumps(result,ensure_ascii=False),flush=True)
        return
    if args.mobile_native:
        import threading
        from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
        if not all((args.state_dir,args.mobile_origin,args.mobile_tls_certificate,args.mobile_tls_key)):
            raise SystemExit('NATIVE_STATE_OR_TLS_CONFIG_REQUIRED')
        owner=NativeMobileComposition(args.state_dir,origin=args.mobile_origin)
        server=control=None
        try:
            service=WebRuntimeService(runtime=owner.runtime,meta_missions=owner.missions,meta_owner=owner,mobile_gateway=owner.mobile)
            server=make_server(args.host,args.port,service,tls_certificate=Path(args.mobile_tls_certificate),tls_key=Path(args.mobile_tls_key))
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            owner.qualify_tls(server.server_address[1])
            control=make_mobile_operator_server(owner)
            threading.Thread(target=control.serve_forever,daemon=True).start()
            print(json.dumps({'status':'NATIVE_MOBILE_HOST_READY',**owner.public_settings()}),flush=True)
            threading.Event().wait()
        except KeyboardInterrupt:pass
        finally:
            if control is not None:control.shutdown();control.server_close()
            if server is not None:server.shutdown();server.server_close()
            owner.close()
        return
    if args.meta_live_one_shot:
        from runtime.providers.meta_model_api import MetaModelProvider
        print(json.dumps({'mode': 'META_LIVE_ONE_SHOT', **MetaModelProvider().diagnostics(),
            'required': ['trusted Core spend binding', 'exact model/cost/count owner GO',
                         'key type and billing confirmation'], 'api_calls': 0}))
        return
    from critical_loop.policy import load_cost_policy
    policy = load_cost_policy(args.cpl_live_policy) if args.cpl_live_policy else None
    if args.meta_offline or args.unified_offline:
        if args.unified_offline and args.host not in LOOPBACK_HOSTS:
            raise ValueError('UNIFIED_LOOPBACK_ONLY')
        from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
        root = Path(args.state_dir) if args.state_dir else Path.home()/('.local/state/aioa-unified-offline-v2' if args.unified_offline else '.local/state/aioa-meta-offline-v1')
        owner = OfflineMetaComposition(root)
        if args.unified_offline:owner.enable_unified()
        service = WebRuntimeService(runtime=owner.runtime, meta_missions=owner.missions, meta_owner=owner,
                                    mobile_gateway=owner.mobile if args.unified_offline else None)
    else:
        service = WebRuntimeService(cpl_fixture=args.cpl_fixture, cpl_cost_policy=policy)
    server = make_server(args.host, args.port, service)
    address, bound_port = server.server_address[:2]
    print(f"AIOA spArkHAT web UI running on http://{address}:{bound_port}",flush=True)
    print("One local runtime | dated evidence review | human authority retained")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__":
    main()
