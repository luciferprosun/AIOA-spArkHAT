#!/usr/bin/env python3
"""
Autonomous local runtime for shell, filesystem, and browser actions.

Architecture:
USER -> LLM -> structured JSON action -> executor -> result -> LLM -> final response
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import time
import traceback
import threading
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from commands import build_command_registry
from adaptive_routing.epistemic_kernel import AOIAEpistemicKernel
from memory.rhcsa_context import inject_linux_context
from orchestrator import GeminiGemmaOrchestrator
from orchestrator.knowledge_router import KnowledgeRouter
from providers import ProviderManager
from router import LocalRouter
from tools.executor import ExecutionEngine
from memory.gemma_worker_memory import GemmaWorkerMemory
from tools.memory_hats import MemoryHatStore
from tools.memory import MemoryStore
from tools.system_info import detect_desktop_dir
from tools.validator import extract_json_object, validate_action


PROJECT_DIR = Path(__file__).resolve().parent
PROMPT_FILE = PROJECT_DIR / "prompts" / "system_prompt.txt"
MAX_AGENT_STEPS = 8
DEBUG_RAW_RESPONSE = os.getenv("AGENT_DEBUG", "0") == "1"
MODEL_RETRY_DELAYS = (1.0, 2.0, 4.0)
EXTERNAL_URL_RE = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
REPOSITORY_HOST_RE = re.compile(r"\b(?:github\.com|gitlab\.com)(?:/|\b)", re.IGNORECASE)
REPOSITORY_INTENT_RE = re.compile(
    r"\b(?:check|analy[sz]e|describe|review|inspect|sprawdz|sprawdź|przeanalizuj|opisz)\b"
    r".*\b(?:github|gitlab|repo|repository|repozytorium|projekt)\b"
    r"|\b(?:github|gitlab|repo|repository|repozytorium|projekt)\b"
    r".*\b(?:check|analy[sz]e|describe|review|inspect|sprawdz|sprawdź|przeanalizuj|opisz)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EpistemicSafeguards:
    kill_switch: bool
    disable_model: bool
    disable_knowledge: bool
    disable_memory_hats: bool
    reasoning_trace_enabled: bool
    prefer_unknown: bool


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_epistemic_safeguards() -> EpistemicSafeguards:
    return EpistemicSafeguards(
        kill_switch=_env_flag("EPISTEMIC_KILL_SWITCH", False),
        disable_model=_env_flag("EPISTEMIC_DISABLE_MODEL", False),
        disable_knowledge=_env_flag("EPISTEMIC_DISABLE_KNOWLEDGE_ROUTE", False),
        disable_memory_hats=_env_flag("EPISTEMIC_DISABLE_MEMORY_HATS", False),
        reasoning_trace_enabled=not _env_flag("EPISTEMIC_DISABLE_REASONING_TRACE", False),
        prefer_unknown=not _env_flag("EPISTEMIC_DISABLE_UNKNOWN_FALLBACK", False),
    )


def load_prompt_template(prompt_path: Path) -> str:
    """Read the editable runtime system prompt from disk."""
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def summarize_text(text: str, limit: int = 4000) -> str:
    """Trim long results before sending them back to the model."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]..."


def extract_first_url(text: str) -> str | None:
    """Extract the first HTTP(S) URL from free-form user text."""
    match = re.search(r"(?:https?|file)://\S+", text)
    if not match:
        return None
    return match.group(0).rstrip(").,!?\"'")


def normalize_external_url(raw_url: str) -> str:
    """Unwrap common redirect wrappers so the browser opens the real target."""
    parsed = urlparse(raw_url)
    host = parsed.netloc.lower()

    if host in {"l.facebook.com", "lm.facebook.com", "www.facebook.com", "facebook.com"}:
        query = parse_qs(parsed.query)
        target = query.get("u", [])
        if target:
            return unquote(target[0])

    return raw_url


def classify_external_review_request(user_input: str) -> str | None:
    """Deterministically keep external links out of local RHCSA retrieval."""
    if REPOSITORY_HOST_RE.search(user_input) or REPOSITORY_INTENT_RE.search(user_input):
        return "external_repository_review"
    if EXTERNAL_URL_RE.search(user_input):
        return "external_link_review"
    return None


def is_quota_exhausted_error(error: Exception) -> bool:
    """Detect provider quota exhaustion to avoid useless retries."""
    text = str(error)
    return "RESOURCE_EXHAUSTED" in text or "quota exceeded" in text.lower()


def is_daily_quota_error(error: Exception) -> bool:
    """Detect daily free-tier exhaustion where short retries will not help."""
    text = str(error)
    return "PerDay" in text or "free_tier_requests" in text


class AgentRuntime:
    """Main runtime loop coordinating model planning and local execution."""

    def __init__(
        self,
        provider_manager: Any,
        prompt_template: str,
        project_dir: Path,
        debug_raw: bool = False,
        max_steps: int = MAX_AGENT_STEPS,
        nonzero_config=None,
        memory_patch_config=None,
        memory_patch_dependencies=None,
        inspection_only: bool = False,
        mission_context=None,
        mission_bindings=None,
    ) -> None:
        if type(inspection_only) is not bool:
            raise ValueError('INVALID_INSPECTION_MODE')
        self._inspection_only = inspection_only
        self._mission_context = mission_context
        self._mission_bindings = mission_bindings
        self._lite_profile = None
        self._lite_scheduler = None
        self._lite_memory = None
        self._lite_cpl = None
        self.provider_manager = provider_manager
        self.prompt_template = prompt_template
        self.project_dir = project_dir
        self.debug_raw = debug_raw
        self.max_steps = max_steps
        self.safeguards = load_epistemic_safeguards()
        if inspection_only:
            # Same composition root, but no mutable legacy state or executor.
            self.provider_manager = None
            self.memory_store = self.hat_store = self.worker_memory = None
            self.executor = self.desktop_dir = self.local_router = None
            self.knowledge_router = self.aoia_kernel = self.command_registry = None
        else:
            self.memory_store = MemoryStore(project_dir, project_dir)
            self.hat_store = MemoryHatStore(project_dir)
            self.worker_memory = GemmaWorkerMemory(project_dir)
            self.executor = ExecutionEngine(project_dir, self.memory_store)
            self.desktop_dir = detect_desktop_dir(Path.home())
            self.local_router = LocalRouter(self.desktop_dir)
            self.knowledge_router = KnowledgeRouter(project_dir)
            self.aoia_kernel = AOIAEpistemicKernel(project_dir)
            self.command_registry = build_command_registry()
        self.use_orchestrator = False
        self.orchestrator: GeminiGemmaOrchestrator | None = None
        self._cpl_service = None
        self._cpl_init_lock = threading.Lock()
        self._nonzero_service = None
        from nonzero_cloudops.contract import snapshot_config
        self._nonzero_config = snapshot_config(nonzero_config)
        self._nonzero_closed = False
        self._nonzero_init_lock = threading.Lock()
        from runtime.memory_patch.contract import (
            snapshot_config as memory_patch_snapshot,
        )

        self._memory_patch_config = memory_patch_snapshot(memory_patch_config)
        self._memory_patch_dependencies = memory_patch_dependencies
        self._memory_patch_service = None
        self._memory_patch_admission = None
        self._memory_patch_closed = False
        self._memory_patch_init_lock = threading.RLock()
        self.cpl_cost_policy = None
        self._owned_cpl_fixture = None
        self.session_log = None if inspection_only else (
            self.memory_store.paths.session_logs_dir
            / f"session_{self.memory_store.memory.session_id}.jsonl"
        )

    def _require_operational_runtime(self):
        if self._inspection_only:
            from runtime.mission.contracts import MissionError
            raise MissionError('INSPECTION_ONLY', status='POLICY_BLOCKED', exit_code=4)

    def mission_doctor(self, *, manifest=None, trace=None):
        """Read-only NV-01 profile discovery through this existing runtime."""
        from runtime.mission.diagnostics import inspect_runtime
        return inspect_runtime(self, manifest=manifest, trace=trace)

    def render_system_prompt(self) -> str:
        prompt = self.prompt_template
        replacements = {
            "__HOME_DIR__": str(Path.home()),
            "__DESKTOP_DIR__": str(self.desktop_dir),
            "__CURRENT_PROJECT__": str(self.project_dir),
            "__CURRENT_CWD__": self.memory_store.memory.cwd,
        }
        for key, value in replacements.items():
            prompt = prompt.replace(key, value)
        return prompt

    @property
    def critical_loop(self):
        """One lazy advisory service, shared by CLI and WebRuntimeService."""
        self._require_operational_runtime()
        with self._cpl_init_lock:
            if self._cpl_service is None:
                from critical_loop.service import CriticalPromptLoopService
                from runtime_paths import runtime_state_dir

                self._cpl_service = CriticalPromptLoopService(
                    self.provider_manager, runtime_state_dir(self.project_dir) / 'critical_loop',
                    cost_policy=self.cpl_cost_policy, execution_guard=self._check_cpl_safeguards)
        return self._cpl_service

    def _check_cpl_safeguards(self):
        from providers.exact import ExactCallError

        if self.safeguards.kill_switch:
            raise ExactCallError('EPISTEMIC_KILL_SWITCH')
        if self.safeguards.disable_model and getattr(self.provider_manager, 'fixture_base_url', None) is None:
            raise ExactCallError('EPISTEMIC_DISABLE_MODEL')

    def plan_critical_loop(self, payload):
        return self.critical_loop.plan(payload)

    def assistant_request(self, prompt, *, mode='cpl', plan_options=None):
        """Default Assistant admission, not generation: one shared CPL service.

        The old action/chat engine remains available only through an explicit
        Plain Chat bypass. Registered slash commands retain their old surface.
        Nothing here auto-authorizes a plan or catches failures into chat.
        """
        from providers.exact import ExactCallError

        self._require_operational_runtime()
        if not isinstance(mode, str) or mode not in {'cpl', 'plain'}:
            raise ExactCallError('INVALID_ASSISTANT_MODE')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 12000:
            raise ExactCallError('INVALID_PROMPT')
        options = {} if plan_options is None else plan_options
        if not isinstance(options, dict) or set(options) - {'evidence', 'models', 'roles', 'limits', 'run_budget_usd'}:
            raise ExactCallError('INVALID_PLAN_FIELDS')
        command = prompt.lstrip().startswith('/')
        if command and prompt.strip().split(None, 1)[0].lower() == '/memory-patch':
            raise ExactCallError('MEMORY_PATCH_REQUIRES_OPERATOR_ENDPOINTS')
        if command and prompt.strip().split(' ', 1)[0].lower() == '/nonzero':
            raise ExactCallError('NONZERO_REQUIRES_OPERATOR_ENDPOINTS')
        if command and prompt.strip().split(' ', 1)[0].lower() == '/cpl':
            raise ExactCallError('CPL_REQUIRES_PLAN_START_ENDPOINTS')
        if mode == 'cpl' and not command:
            planned = self.plan_critical_loop({'prompt': prompt, **options})
            return {'ok': True, 'mode': 'cpl', 'cpl': planned,
                    'transcript': None, 'review_status': 'AWAITING_ONE_USE_APPROVAL',
                    'status': self.snapshot_status()}
        if options:
            raise ExactCallError('CPL_OPTIONS_REQUIRE_CPL_PROMPT')
        result = self.run_text_request(prompt)
        return {'ok': True, 'mode': 'command' if command else 'plain',
                'review_status': 'NOT_CPL_REVIEWED', **result}

    def run_cpl_fixture(self):
        from critical_loop.fixture import FIXTURE_PROMPT, FIXTURE_EVIDENCE
        from providers.exact import ExactCallError

        if getattr(self.provider_manager, 'fixture_base_url', None) is None:
            raise ExactCallError('EXPLICIT_CPL_FIXTURE_MODE_REQUIRED')
        plan = self.plan_critical_loop({'prompt': FIXTURE_PROMPT, 'evidence': FIXTURE_EVIDENCE})
        self.critical_loop.start(plan['run_id'], plan['plan_hash'], plan['nonce'])
        return self.critical_loop.wait(plan['run_id'])

    def close(self):
        if self._lite_scheduler is not None:
            self._lite_scheduler.close()
        if self._lite_memory is not None:
            self._lite_memory.close()
        if self._lite_cpl is not None:
            self._lite_cpl.close()
        with self._memory_patch_init_lock:
            self._memory_patch_closed = True
            if self._memory_patch_service is not None:
                self._memory_patch_service.close()
            if self._memory_patch_admission is not None:
                self._memory_patch_admission.close()
        with self._nonzero_init_lock:
            self._nonzero_closed = True
            if self._nonzero_service is not None:
                self._nonzero_service.close()
        if self._cpl_service is not None:
            self._cpl_service.close()
        if self._owned_cpl_fixture is not None:
            self._owned_cpl_fixture.close()
            self._owned_cpl_fixture = None

    def lite_status(self):
        from dataclasses import asdict
        from runtime.mission.contracts import MissionError
        if self._lite_profile is None:
            raise MissionError('LITE_PROFILE_NOT_CONFIGURED')
        if self._lite_scheduler is not None:
            return self._lite_scheduler.describe()
        profile = self._lite_profile
        value = asdict(profile)
        value.update(state='DISABLED' if not profile.enabled else 'INSPECTION_ONLY',
                     reason='LITE_DISABLED' if not profile.enabled else 'NO_SCHEDULER_STARTED',
                     scheduler_owner='AgentRuntime', queue_depth=0, model_calls=0,
                     domain_mutations=0)
        return value

    def lite_tick(self, *, execute=True):
        from runtime.mission.contracts import MissionError
        if self._lite_scheduler is None:
            raise MissionError('LITE_NOT_RUNNING')
        return self._lite_scheduler.tick(execute=execute)

    def lite_run(self):
        from runtime.mission.contracts import MissionError
        if self._lite_scheduler is None:
            raise MissionError('LITE_NOT_RUNNING')
        return self._lite_scheduler.run()

    def lite_request_stop(self):
        if self._lite_scheduler is not None:
            self._lite_scheduler.request_stop()

    def lite_chat(self, principal, question, *, operation_id, mode):
        """Private bounded chat; principal comes from this runtime's Core admission.

        This API neither authenticates an arbitrary owner string nor grants
        consent. Its operator must use the existing admitted identity boundary.
        """
        from runtime.mission.contracts import MissionError
        if self._lite_scheduler is None:
            raise MissionError('LITE_NOT_RUNNING')
        return self._lite_scheduler.chat(principal, question,
                                         operation_id=operation_id, mode=mode)

    def lite_nachwg_chat(self, principal, *, operation_id):
        """Explicit one-case Core entry; shares the existing scheduler mutex."""
        from runtime.memory_patch.learning.nachwg_contract import HISTORICAL_QUESTION, NACHWG_CASE_ID
        from runtime.mission.contracts import MissionError
        if self._lite_scheduler is None:
            raise MissionError('LITE_NOT_RUNNING')
        return self._lite_scheduler.chat(principal, HISTORICAL_QUESTION,
                                         operation_id=operation_id, mode=None,
                                         case_id=NACHWG_CASE_ID)

    def lite_memory_status(self):
        return ({'memory_mode': 'OFF', 'readiness': 'DISABLED'} if self._lite_memory is None
                else self._lite_memory.describe())

    def lite_cpl_status(self):
        return ({'mode': 'OFF', 'readiness': 'DISABLED'} if self._lite_cpl is None
                else self._lite_cpl.describe())

    def lite_dynamics_status(self):
        dynamics = None if self._lite_cpl is None else self._lite_cpl.learning.dynamics
        return {'mode': 'OFF', 'readiness': 'DISABLED'} if dynamics is None else dynamics.describe()

    def lite_memory_retrieve(self, query):
        from runtime.mission.contracts import MissionError
        if self._lite_memory is None:
            raise MissionError('MEMORY_NOT_COMPOSED')
        return self._lite_memory.retrieve(query)

    def lite_memory_operator_request(self, operation, payload):
        from runtime.mission.contracts import MissionError
        if self._lite_memory is None:
            raise MissionError('MEMORY_NOT_COMPOSED')
        return self._lite_memory.operator_request(operation, payload)

    @property
    def nonzero_config(self):
        """Read-only startup snapshot. Reconfiguration requires a new runtime."""
        return self._nonzero_config

    def nonzero_status(self):
        """Describe the effective lifecycle without initializing optional state."""
        from nonzero_cloudops import module_descriptor
        with self._nonzero_init_lock:
            if self._nonzero_service is not None:
                return self._nonzero_service.status()
            result = {**module_descriptor(self.nonzero_config),
                      'initialized': False, 'closed': self._nonzero_closed}
            if self._nonzero_closed:
                result.update(available=False, availability_code='NONZERO_SERVICE_CLOSED')
            return result

    @property
    def nonzero_cloudops(self):
        """Own one optional portable module through the existing runtime."""
        self._require_operational_runtime()
        with self._nonzero_init_lock:
            if self._nonzero_closed:
                from nonzero_cloudops import NonZeroError
                raise NonZeroError('NONZERO_SERVICE_CLOSED')
            if self._nonzero_service is None:
                from nonzero_cloudops import NonZeroCloudOpsService
                from runtime_paths import runtime_state_dir
                self._nonzero_service = NonZeroCloudOpsService(
                    runtime_state_dir(self.project_dir) / 'nonzero_cloudops' / 'native-v1',
                    guard=lambda: self.safeguards.kill_switch, config=self.nonzero_config)
        return self._nonzero_service

    @property
    def memory_patch_config(self):
        return self._memory_patch_config

    def memory_patch_status(self):
        """Discovery does not resolve a port, provider, HAT, credential or database."""
        from runtime.memory_patch.contract import module_descriptor

        with self._memory_patch_init_lock:
            if self._memory_patch_service is not None:
                return self._memory_patch_service.status()
            return module_descriptor(
                self.memory_patch_config, closed=self._memory_patch_closed
            )

    def memory_patch_operator_request(self, operation, payload):
        """Called only by existing local CLI or admitted operator HTTP endpoints.

        Body identifiers never create a principal. Core's immutable approved
        assignment and the explicit operation select its narrow capability.
        """
        from runtime.core_admission import CoreAdmission
        from runtime.memory_patch.contract import operation_capability
        from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
        from runtime.memory_patch.views import envelope, error_response

        try:
            with self._memory_patch_init_lock:
                if operation == "status" and type(payload) is dict and not payload:
                    return 200, envelope(operation, result=self.memory_patch_status())
                if self._inspection_only:
                    raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
                if self._memory_patch_closed:
                    raise MemoryPatchError(ErrorCode.MODULE_CLOSED)
                if self.safeguards.kill_switch or not self.memory_patch_config.enabled:
                    raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
                capability = operation_capability(operation)
                if self._memory_patch_admission is None:
                    self._memory_patch_admission = CoreAdmission(
                        self.memory_patch_config.assignment
                    )
                principal = self._memory_patch_admission.local_operator(capability)
                from runtime.memory_patch.service import (
                    MemoryPatchService,
                    validate_request,
                )

                validate_request(operation, payload)
                if self._memory_patch_service is None:
                    self._memory_patch_service = MemoryPatchService(
                        self._memory_patch_admission,
                        config=self.memory_patch_config,
                        dependencies=self._memory_patch_dependencies,
                        existing_provider_manager=self.provider_manager,
                        existing_hat_selection=self.hat_store,
                        existing_critic=self._cpl_service,
                    )
                return self._memory_patch_service.request(principal, operation, payload)
        except Exception as error:
            return error_response(operation, error)

    def build_model_request(
        self,
        user_input: str,
        request_trace: list[dict[str, Any]],
    ) -> str:
        memory = self.memory_store.memory
        state_payload = {
            "session_id": memory.session_id,
            "cwd": memory.cwd,
            "current_task": memory.current_task,
            "previous_commands": memory.previous_commands[-10:],
            "recent_outputs": memory.recent_outputs[-6:],
            "browser_active": memory.browser_active,
            "current_browser_page": memory.current_browser_page,
            "open_tabs": memory.open_tabs[-10:],
            "screenshots": memory.screenshots[-10:],
            "desktop_dir": str(self.desktop_dir),
            "active_model": self.provider_manager.describe(),
            "fallback_chain": self._provider_fallback_chain(),
            "active_memory_hat": {} if self.safeguards.disable_memory_hats else self.hat_store.prompt_block(),
            "rhcsa_context": inject_linux_context(user_input),
            "obsidian_vault": str(self.memory_store.vault_dir),
            "tools": self.executor.tool_names(),
            "epistemic_safeguards": {
                "kill_switch": self.safeguards.kill_switch,
                "disable_model": self.safeguards.disable_model,
                "disable_knowledge": self.safeguards.disable_knowledge,
                "disable_memory_hats": self.safeguards.disable_memory_hats,
                "prefer_unknown": self.safeguards.prefer_unknown,
            },
            "local_fast_routes": [
                "slash commands",
                "date/status",
                "pwd/ls/curl version",
                "simple desktop folder creation",
                "URL browser bootstrap",
            ],
        }
        request_payload = {
            "user_request": user_input,
            "request_trace": request_trace,
            "instruction": (
                "Return exactly one JSON object and no markdown. "
                "Choose the next proposed action. The runtime will ask the human "
                "for ENTER approval before executing any non-respond action. "
                "Include confidence as high, medium, low, or unknown. "
                'If you do not have enough evidence, respond with "I DO NOT KNOW".'
            ),
        }

        return "\n".join(
            [
                "SYSTEM PROMPT:",
                self.render_system_prompt(),
                "",
                "RUNTIME STATE JSON:",
                json.dumps(state_payload, indent=2, ensure_ascii=False),
                "",
                "REQUEST JSON:",
                json.dumps(request_payload, indent=2, ensure_ascii=False),
            ]
        )

    def snapshot_status(self) -> dict[str, Any]:
        """Return the current runtime status for CLI and web callers."""
        memory = self.memory_store.memory
        return {
            "session_id": memory.session_id,
            "cwd": memory.cwd,
            "current_task": memory.current_task,
            "desktop_dir": str(self.desktop_dir),
            "model": self.provider_manager.describe(),
            "product_name": "AIOA spArkHAT",
            "nonzero_cloudops": self.nonzero_status(),
            "critical_loop": {"enabled": True, "authority": "ADVISORY_ONLY",
                              "mode": "TEST" if getattr(self.provider_manager, 'fixture_base_url', None) is not None else "LIVE_PENDING_AUTHORIZATION",
                              "knowledge_promotion": "DISABLED"},
            "browser_active": memory.browser_active,
            "current_url": memory.current_browser_page,
            "open_tabs": memory.open_tabs[-10:],
            "recent_outputs": memory.recent_outputs[-10:],
            "previous_commands": memory.previous_commands[-10:],
            "session_log": str(self.session_log),
            "vault_dir": str(self.memory_store.vault_dir),
            "tools": self.executor.tool_names(),
            "active_memory_hat": self.hat_store.prompt_block(),
            "fallback_chain": self._provider_fallback_chain(),
            "provider_status": self._provider_status(),
            "orchestrator_enabled": self.use_orchestrator,
            "worker_memory": self.worker_memory.summarize_worker_state(),
            "knowledge_routing": {
                "enabled": not self.safeguards.disable_knowledge,
                "token_savings_report": str(self.knowledge_router.report_path),
                "aoia_kernel": "deterministic_local_epistemic_kernel_v0_1",
            },
            "epistemic_safeguards": {
                "kill_switch": self.safeguards.kill_switch,
                "disable_model": self.safeguards.disable_model,
                "disable_knowledge": self.safeguards.disable_knowledge,
                "disable_memory_hats": self.safeguards.disable_memory_hats,
                "reasoning_trace_enabled": self.safeguards.reasoning_trace_enabled,
                "prefer_unknown": self.safeguards.prefer_unknown,
            },
        }

    def _provider_fallback_chain(self) -> list[str]:
        method = getattr(self.provider_manager, "active_fallback_chain", None)
        if callable(method):
            return method()
        return []

    def _provider_status(self) -> list[dict[str, Any]]:
        method = getattr(self.provider_manager, "provider_status", None)
        if callable(method):
            return method()
        return []

    def ask_model(self, prompt: str) -> str:
        """Request one structured action from the active model provider."""
        self._require_operational_runtime()
        if self.safeguards.disable_model:
            raise RuntimeError("Model planning is disabled by EPISTEMIC_DISABLE_MODEL.")
        last_error: Exception | None = None
        for attempt, delay_seconds in enumerate(MODEL_RETRY_DELAYS, start=1):
            try:
                raw_text = self.provider_manager.generate(prompt)
                if self.debug_raw:
                    print("\n[DEBUG] RAW MODEL OUTPUT:")
                    print(raw_text)
                return raw_text
            except Exception as error:
                last_error = error
                if is_daily_quota_error(error):
                    break
                if attempt == len(MODEL_RETRY_DELAYS):
                    break
                print(
                    f"\n[WARN] Model request failed (attempt {attempt}/{len(MODEL_RETRY_DELAYS)}): {error}"
                )
                print(f"[WARN] Retrying in {delay_seconds:.0f}s...")
                time.sleep(delay_seconds)

        assert last_error is not None
        raise RuntimeError(f"Model request failed after retries: {last_error}")

    def handle_user_request(self, user_input: str) -> None:
        """Run the bounded action loop for one user request."""
        self._require_operational_runtime()
        self.memory_store.set_current_task(user_input)
        if user_input.strip().lower() in {"help", "?"}:
            result = self.command_registry.execute("/help", self)
            if result.handled and result.message:
                print(f"\nAgent> {result.message}")
            return
        if self.safeguards.kill_switch:
            self.emit_epistemic_unknown("Epistemic kill switch is enabled.")
            return

        if self.handle_external_review_route(user_input):
            return

        if self.handle_local_route(user_input):
            return

        if self.handle_knowledge_route(user_input):
            return

        if self.use_orchestrator:
            self.handle_orchestrated_request(user_input)
            return

        request_trace = self.bootstrap_local_context(user_input)

        planned_actions = self.create_plan(user_input, request_trace)
        if planned_actions:
            self.execute_planned_actions(planned_actions, request_trace)
            return

        for step in range(1, self.max_steps + 1):
            prompt = self.build_model_request(user_input, request_trace)
            self.log_reasoning_trace(
                "model_request",
                {
                    "step": step,
                    "user_request": user_input,
                    "prompt_preview": summarize_text(prompt, 1200),
                },
            )
            try:
                raw_output = self.ask_model(prompt)
            except Exception as error:
                self.log_error(
                    {
                        "step": step,
                        "error": str(error),
                        "traceback": traceback.format_exc(),
                        "prompt_preview": summarize_text(prompt, 1200),
                    }
                )
                self.handle_model_unavailable(request_trace, error)
                return

            self.log_session_event(
                "model_output",
                {
                    "step": step,
                    "prompt_preview": summarize_text(prompt, 1200),
                    "raw_output": raw_output,
                },
            )

            try:
                action = validate_action(extract_json_object(raw_output))
            except Exception as error:
                self.log_error(
                    {
                        "step": step,
                        "raw_output": raw_output,
                        "error": str(error),
                        "traceback": traceback.format_exc(),
                    }
                )
                print("\n[ERROR] Invalid action JSON from model.")
                print(str(error))
                if self.safeguards.prefer_unknown:
                    self.emit_epistemic_unknown("The model returned invalid structured output.")
                return

            self.print_action(action, step)

            try:
                result = self.executor.execute(action)
            except Exception as error:
                self.log_error(
                    {
                        "step": step,
                        "action": action,
                        "error": str(error),
                        "traceback": traceback.format_exc(),
                    }
                )
                print("\n[ERROR] Action execution failed.")
                print(str(error))
                return

            self.print_result(result)
            self.log_session_event(
                "step_result",
                {
                    "step": step,
                    "action": action,
                    "result": self.result_for_model(result),
                },
            )

            if action["action"] == "respond" or result.get("stop_loop"):
                return
            if result.get("cancelled"):
                return

            request_trace.append(
                {
                    "step": step,
                    "action": action,
                    "result": self.result_for_model(result),
                }
            )

        print("\nAgent> Agent stopped after reaching the maximum step limit.")

    def handle_external_review_route(self, user_input: str) -> bool:
        """Keep external URLs and repository requests out of RHCSA retrieval."""
        self._require_operational_runtime()
        route = classify_external_review_request(user_input)
        if route is None:
            return False

        raw_url = extract_first_url(user_input)
        if raw_url:
            normalized_url = normalize_external_url(raw_url)
            try:
                open_result = self.executor.execute(
                    {"action": "browser_open", "url": normalized_url},
                    require_approval=False,
                )
                self.print_result(open_result)
                if open_result.get("success"):
                    visible_text = self.executor.execute(
                        {"action": "browser_get_visible_text"},
                        require_approval=False,
                    )
                    self.print_result(visible_text)
                self.log_session_event(
                    route,
                    {
                        "user_request": user_input,
                        "routing_boundary": "no_rhcsa_local_knowledge",
                        "browser_handled": True,
                        "opened_url": normalized_url,
                    },
                )
                return True
            except Exception as error:
                self.log_error(
                    {
                        "user_request": user_input,
                        "route": route,
                        "error": str(error),
                        "traceback": traceback.format_exc(),
                    }
                )
                self.log_session_event(
                    route,
                    {
                        "user_request": user_input,
                        "routing_boundary": "no_rhcsa_local_knowledge",
                        "browser_handled": False,
                        "opened_url": normalized_url,
                        "error": str(error),
                    },
                )
                print("\nAgent> External URL detected. Browser inspection path available but browser handoff failed.")
                return True

        message = (
            "External repository inspection path detected. Browser inspection path available."
            if route == "external_repository_review"
            else "External URL detected. Browser inspection path available."
        )
        self.log_session_event(
            route,
            {
                "user_request": user_input,
                "routing_boundary": "no_rhcsa_local_knowledge",
                "browser_handled": False,
            },
        )
        print(f"\nAgent> {message}")
        return True

    def enable_orchestrator(self, enabled: bool = True) -> None:
        self._require_operational_runtime()
        self.use_orchestrator = enabled
        if enabled and self.orchestrator is None:
            self.orchestrator = GeminiGemmaOrchestrator(
                provider_manager=self.provider_manager,
                worker_memory=self.worker_memory,
                hat_store=self.hat_store,
                project_dir=self.project_dir,
                desktop_dir=self.desktop_dir,
                max_steps=self.max_steps,
            )

    def handle_orchestrated_request(self, user_input: str) -> None:
        """Run Gemini brain -> Gemma worker -> approval -> executor flow."""
        self._require_operational_runtime()
        self.enable_orchestrator(True)
        assert self.orchestrator is not None

        try:
            plan = self.orchestrator.create_plan(user_input, self.snapshot_status())
        except Exception as error:
            self.log_error(
                {
                    "kind": "orchestrator_planner_error",
                    **self.orchestrator.error_payload(error),
                }
            )
            print("\n[ERROR] Gemini planner failed.")
            print(str(error))
            return

        strategy = plan.get("strategy", "")
        steps = plan.get("steps", [])
        print("\n[GEMINI PLAN]")
        if strategy:
            print(strategy)
        for index, step in enumerate(steps, start=1):
            print(f"{index}. {step}")

        previous_results: list[dict[str, Any]] = []
        for index, step in enumerate(steps[: self.max_steps], start=1):
            try:
                action = self.orchestrator.action_for_step(
                    user_request=user_input,
                    step=step,
                    runtime_status=self.snapshot_status(),
                    previous_results=previous_results,
                )
            except Exception as error:
                self.log_error(
                    {
                        "kind": "gemma_worker_error",
                        "step": step,
                        **self.orchestrator.error_payload(error),
                    }
                )
                print("\n[ERROR] Gemma worker failed to produce a valid action.")
                print(str(error))
                print("Agent> Worker model is not available or did not return valid JSON. Use /worker status and /setup.")
                return

            self.print_action(action, index)
            try:
                result = self.executor.execute(action)
            except Exception as error:
                self.log_error(
                    {
                        "kind": "orchestrated_execution_error",
                        "step": step,
                        "action": action,
                        "error": str(error),
                        "traceback": traceback.format_exc(),
                    }
                )
                print("\n[ERROR] Orchestrated action execution failed.")
                print(str(error))
                return

            self.print_result(result)
            self.orchestrator.record_result(step, action, result)
            previous_results.append(
                {
                    "step": step,
                    "action": action,
                    "result": self.result_for_model(result),
                }
            )
            self.log_session_event(
                "orchestrated_step_result",
                previous_results[-1],
            )
            if action["action"] == "respond" or result.get("stop_loop") or result.get("cancelled"):
                return

    def create_plan(
        self,
        user_input: str,
        request_trace: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Ask the model for a short action plan before the reactive loop."""
        prompt = self.build_plan_request(user_input, request_trace)
        self.log_reasoning_trace(
            "planner_request",
            {
                "user_request": user_input,
                "prompt_preview": summarize_text(prompt, 1200),
            },
        )
        try:
            raw_output = self.ask_model(prompt)
            payload = extract_json_object(raw_output)
        except Exception as error:
            self.log_error(
                {
                    "kind": "planner_error",
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                    "prompt_preview": summarize_text(prompt, 1200),
                }
            )
            return []

        raw_plan = payload.get("plan", [])
        if "plan" not in payload and "action" in payload:
            try:
                return [validate_action(payload)]
            except Exception:
                return []
        if not isinstance(raw_plan, list):
            return []

        planned_actions: list[dict[str, Any]] = []
        for raw_action in raw_plan[: self.max_steps]:
            try:
                planned_actions.append(validate_action(raw_action))
            except Exception as error:
                self.log_error(
                    {
                        "kind": "planner_action_error",
                        "raw_action": raw_action,
                        "error": str(error),
                    }
                )
                return []

        if planned_actions:
            self.log_reasoning_trace(
                "planner_actions",
                {
                    "user_request": user_input,
                    "planned_actions": planned_actions,
                },
            )
            self.log_session_event(
                "planner_output",
                {
                    "raw_output": raw_output,
                    "planned_actions": planned_actions,
                },
            )
        return planned_actions

    def build_plan_request(
        self,
        user_input: str,
        request_trace: list[dict[str, Any]],
    ) -> str:
        payload = {
            "user_request": user_input,
            "request_trace": request_trace[-4:],
            "runtime": self.snapshot_status(),
            "rhcsa_context": inject_linux_context(user_input, max_chars=3000),
            "instruction": (
                "Return exactly one JSON object with a plan array. "
                "Each plan item must be one allowed action JSON object. "
                "Keep the plan minimal and include a final respond action when the task can be completed. "
                "Do not execute anything. The runtime will require human ENTER approval before tools run."
            ),
        }
        return "\n".join(
            [
                "SYSTEM PROMPT:",
                self.render_system_prompt(),
                "",
                "PLANNER REQUEST JSON:",
                json.dumps(payload, indent=2, ensure_ascii=False),
                "",
                'EXPECTED FORMAT: {"plan":[{"action":"respond","message":"...","reason":"..."}]}',
            ]
        )

    def execute_planned_actions(
        self,
        planned_actions: list[dict[str, Any]],
        request_trace: list[dict[str, Any]],
    ) -> None:
        self._require_operational_runtime()
        print(f"\n[PLAN] {len(planned_actions)} proposed step(s).")
        last_result: dict[str, Any] | None = None
        for step, action in enumerate(planned_actions, start=1):
            self.print_action(action, step)
            try:
                result = self.executor.execute(action)
            except Exception as error:
                self.log_error(
                    {
                        "step": step,
                        "action": action,
                        "error": str(error),
                        "traceback": traceback.format_exc(),
                    }
                )
                print("\n[ERROR] Planned action execution failed.")
                print(str(error))
                return

            self.print_result(result)
            last_result = result
            self.log_session_event(
                "planned_step_result",
                {
                    "step": step,
                    "action": action,
                    "result": self.result_for_model(result),
                },
            )
            request_trace.append(
                {
                    "step": step,
                    "action": action,
                    "result": self.result_for_model(result),
                }
            )
            if action["action"] == "respond" or result.get("stop_loop") or result.get("cancelled"):
                return
        if last_result and last_result.get("success"):
            print("Agent> Część operacji została już wykonana poprawnie.")

    def run_text_request(self, user_input: str) -> dict[str, Any]:
        """Execute one text request and capture the textual transcript."""
        self._require_operational_runtime()
        transcript_buffer = io.StringIO()
        with redirect_stdout(transcript_buffer):
            command_result = self.command_registry.execute(user_input, self)
            if command_result.handled:
                if command_result.message:
                    print(f"\nAgent> {command_result.message}")
            else:
                self.handle_user_request(user_input)
        transcript = transcript_buffer.getvalue().strip()
        return {
            "transcript": transcript,
            "status": self.snapshot_status(),
        }

    def handle_local_route(self, user_input: str) -> bool:
        """Execute obvious local tasks before calling the model."""
        self._require_operational_runtime()
        route = self.local_router.route(user_input)
        if route is None:
            return False

        if not route.actions:
            if route.final_message:
                print(f"\nAgent> {route.final_message}")
            return True

        last_result: dict[str, Any] | None = None
        for index, raw_action in enumerate(route.actions, start=1):
            action = validate_action(raw_action)
            self.print_action(action, index)
            result = self.executor.execute(action)
            last_result = result
            self.print_result(result)
            self.log_session_event(
                "local_route_result",
                {
                    "step": index,
                    "action": action,
                    "result": self.result_for_model(result),
                },
            )

        if route.final_message:
            print(f"\nAgent> {route.final_message}")
        elif last_result and last_result.get("message"):
            print(f"\nAgent> {last_result['message']}")
        return True

    def handle_knowledge_route(self, user_input: str) -> bool:
        """Answer Linux/RHCSA operational requests from local memory first."""
        self._require_operational_runtime()
        if self.safeguards.disable_knowledge:
            self.log_reasoning_trace(
                "knowledge_route_disabled",
                {"user_request": user_input},
            )
            return False
        kernel_decision = self.aoia_kernel.evaluate(user_input)
        self.log_reasoning_trace("aoia_kernel_decision", kernel_decision.reasoning)
        if kernel_decision.evidence:
            self.memory_store.append_reasoning(
                "aoia_kernel_evidence_reference",
                {
                    "query": user_input,
                    "route": kernel_decision.route,
                    "confidence": kernel_decision.confidence,
                    "manual_review_required": kernel_decision.manual_review_required,
                    "artifacts": [item.get("file_location") for item in kernel_decision.evidence],
                },
            )
        if kernel_decision.should_respond_locally:
            result = {
                "success": True,
                "message": kernel_decision.response,
                "confidence_label": kernel_decision.confidence,
                "manual_review_required": kernel_decision.manual_review_required,
                "manual_review_reasons": list(kernel_decision.manual_review_reasons),
                "stop_loop": True,
            }
            self.print_result(result)
            self.log_session_event(
                "aoia_kernel_hit",
                {
                    "confidence": kernel_decision.confidence,
                    "depth": kernel_decision.depth,
                    "pressure": kernel_decision.pressure,
                    "manual_review_required": kernel_decision.manual_review_required,
                    "evidence_count": len(kernel_decision.evidence),
                },
            )
            return True
        decision = self.knowledge_router.route(user_input, self.hat_store.prompt_block())
        if not decision.should_handle_locally:
            self.log_session_event(
                "knowledge_route_miss",
                {
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                },
            )
            return False

        print(f"\nAgent> [CONFIDENCE: {decision.confidence.upper()}] {decision.response}")
        self.log_session_event(
            "knowledge_route_hit",
            {
                "confidence": decision.confidence,
                "reason": decision.reason,
                "score": getattr(decision.hit, "confidence_score", getattr(decision.hit, "score", 0)) if decision.hit else 0,
            },
        )
        return True

    def emit_epistemic_unknown(self, reason: str) -> None:
        result = {
            "success": True,
            "message": "I DO NOT KNOW",
            "confidence_label": "UNKNOWN",
            "epistemic_note": reason,
            "stop_loop": True,
        }
        self.log_reasoning_trace(
            "unknown_response",
            {
                "reason": reason,
                "message": result["message"],
            },
        )
        self.memory_store.append_reasoning(
            "unknown_response",
            {"reason": reason, "message": result["message"]},
        )
        self.print_result(result)

    def handle_model_unavailable(
        self,
        request_trace: list[dict[str, Any]],
        error: Exception,
    ) -> None:
        """Avoid hard-crashing after partial success."""
        if is_quota_exhausted_error(error):
            print("\n[WARN] Provider quota is exhausted for the current key.")
        if request_trace:
            last_result = request_trace[-1]["result"]
            print("\n[WARN] Model became unavailable before the next planning step.")
            print(f"[WARN] {error}")
            if last_result.get("success"):
                print("Agent> Część operacji została już wykonana poprawnie.")
                if last_result.get("message"):
                    print(f"Agent> Ostatni zakończony krok: {last_result['message']}")
                if last_result.get("current_url"):
                    print(f"Agent> Aktywny URL: {last_result['current_url']}")
                print("Agent> Uruchom polecenie jeszcze raz, aby dokończyć kolejne kroki.")
                return

        print("\n[ERROR] Model is unavailable right now.")
        print(str(error))
        print("Agent> Configure a working free cloud API with /setup, or switch provider with /model.")

    def bootstrap_local_context(self, user_input: str) -> list[dict[str, Any]]:
        """Perform obvious local setup without spending model quota.

        This is intentionally narrow:
        - unwrap Facebook redirect links
        - start the browser if the request contains a URL
        - open the URL directly
        - optionally capture visible text for later analysis

        The goal is to save model requests for interpretation rather than for
        trivial browser setup.
        """
        self._require_operational_runtime()
        request_trace: list[dict[str, Any]] = []
        raw_url = extract_first_url(user_input)
        if not raw_url:
            return request_trace

        normalized_url = normalize_external_url(raw_url)
        if normalized_url != raw_url:
            print(f"\n[INFO] Redirect URL unwrapped to: {normalized_url}")

        start_action = {"action": "browser_start", "reason": "Local URL bootstrap."}
        start_result = self.executor.execute(start_action, require_approval=False)
        self.print_result(start_result)
        request_trace.append(
            {
                "step": 0,
                "action": start_action,
                "result": self.result_for_model(start_result),
            }
        )

        open_action = {
            "action": "browser_open",
            "url": normalized_url,
            "reason": "Local URL bootstrap.",
        }
        open_result = self.executor.execute(open_action, require_approval=False)
        self.print_result(open_result)
        request_trace.append(
            {
                "step": 0,
                "action": open_action,
                "result": self.result_for_model(open_result),
            }
        )

        lowered = user_input.lower()
        if any(token in lowered for token in ("analiz", "analy", "paper", "praca", "read", "przeczy")):
            text_action = {
                "action": "browser_get_visible_text",
                "reason": "Capture visible page text before analysis.",
            }
            text_result = self.executor.execute(text_action, require_approval=False)
            self.print_result(text_result)
            snapshot_path = self.save_page_text_snapshot(normalized_url, text_result)
            if snapshot_path is not None:
                text_result["snapshot_path"] = str(snapshot_path)
                print(f"Result: Saved text snapshot to {snapshot_path}")
            request_trace.append(
                {
                    "step": 0,
                    "action": text_action,
                    "result": self.result_for_model(text_result),
                }
            )

        return request_trace

    def save_page_text_snapshot(self, url: str, result: dict[str, Any]) -> Path | None:
        """Persist locally captured page text so quota failures do not lose context."""
        self._require_operational_runtime()
        text = result.get("text", "").strip()
        if not text:
            return None

        parsed = urlparse(url)
        slug = parsed.netloc.replace(".", "_") or "page"
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_path = self.memory_store.paths.memory_dir / f"{slug}_{timestamp}.txt"
        snapshot_path.write_text(text, encoding="utf-8")
        return snapshot_path

    def result_for_model(self, result: dict[str, Any]) -> dict[str, Any]:
        payload = dict(result)
        if "stdout" in payload:
            payload["stdout"] = summarize_text(str(payload["stdout"]), 2500)
        if "stderr" in payload:
            payload["stderr"] = summarize_text(str(payload["stderr"]), 2500)
        if "content" in payload:
            payload["content"] = summarize_text(str(payload["content"]), 2500)
        if "text" in payload:
            payload["text"] = summarize_text(str(payload["text"]), 2500)
        if "html" in payload:
            payload["html"] = summarize_text(str(payload["html"]), 2500)
        if "matches" in payload:
            payload["matches"] = payload["matches"][:20]
        return payload

    def log_session_event(self, kind: str, payload: dict[str, Any]) -> None:
        self._require_operational_runtime()
        record = {
            "timestamp": dt.datetime.now().isoformat(),
            "kind": kind,
            "payload": payload,
        }
        with self.session_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_reasoning_trace(self, kind: str, payload: dict[str, Any]) -> None:
        if not self.safeguards.reasoning_trace_enabled:
            return
        self.memory_store.append_reasoning(kind, payload)

    def log_error(self, payload: dict[str, Any]) -> None:
        self._require_operational_runtime()
        error_file = (
            self.memory_store.paths.error_logs_dir
            / f"error_{dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        )
        error_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def print_action(self, action: dict[str, Any], step: int) -> None:
        print(f"\n[STEP {step}] action={action['action']}")
        if action.get("reason"):
            print(f"Reason: {action['reason']}")
        for field in ("command", "path", "url", "selector", "key"):
            if field in action and action[field]:
                print(f"{field}: {action[field]}")

    def print_result(self, result: dict[str, Any]) -> None:
        if result.get("confidence_label"):
            print(f"[CONFIDENCE: {str(result['confidence_label']).upper()}]")
        if result.get("manual_review_required"):
            print("[MANUAL REVIEW: REQUIRED]")
            reasons = result.get("manual_review_reasons") or []
            if reasons:
                print(f"Review reasons: {', '.join(str(reason) for reason in reasons)}")
        if result.get("message"):
            prefix = "Agent>" if result.get("stop_loop") else "Result:"
            print(f"{prefix} {result['message']}")
        if result.get("epistemic_note"):
            print(f"Epistemic note: {result['epistemic_note']}")

        if "stdout" in result:
            print("\n--- STDOUT ---")
            print(result["stdout"] if result["stdout"].strip() else "(empty)")

        if "stderr" in result:
            print("\n--- STDERR ---")
            print(result["stderr"] if result["stderr"].strip() else "(empty)")

        if "content" in result:
            print("\n--- FILE CONTENT ---")
            print(result["content"])

        if "text" in result:
            print("\n--- PAGE TEXT ---")
            print(result["text"])

        if "current_url" in result and result["current_url"]:
            print(f"\nCurrent URL: {result['current_url']}")

        if "screenshot_path" in result:
            print(f"Screenshot: {result['screenshot_path']}")

        if "exit_code" in result:
            print(f"\nExit code: {result['exit_code']}")


def print_banner(runtime: AgentRuntime) -> None:
    print("########################################################")
    print("###  AIOA spArkHAT (formerly AOIA-Core)              ###")
    print("###  ONE RUNTIME | ASSISTANT | REVIEW | CPL         ###")
    print("########################################################")
    print(f"[INFO] Desktop directory detected: {runtime.desktop_dir}")
    print(f"[INFO] Current working directory: {runtime.memory_store.memory.cwd}")
    print(f"[INFO] Active model: {runtime.provider_manager.describe()}")
    print(f"[INFO] Session log: {runtime.session_log}")
    print(f"[INFO] Obsidian vault: {runtime.memory_store.vault_dir}")


def create_runtime(*, cpl_fixture=False, cpl_cost_policy=None, nonzero_config=None,
                   memory_patch_config=None, memory_patch_dependencies=None,
                   inspection_only=False, mission_context=None, mission_bindings=None,
                   lite_profile=None, lite_bindings=None):
    if type(inspection_only) is not bool:
        raise ValueError('INVALID_INSPECTION_MODE')
    if lite_profile is not None or lite_bindings is not None:
        from runtime.mission.contracts import MissionError
        from runtime.mission.lite_contracts import LiteProfile
        from runtime.mission.lite_runtime import LiteScheduler
        if type(lite_profile) is not LiteProfile:
            raise MissionError('INVALID_LITE_MANIFEST')
        lite_profile.require_context(mission_context)
        if (cpl_fixture or cpl_cost_policy is not None or nonzero_config is not None
                or memory_patch_config is not None or memory_patch_dependencies is not None
                or mission_bindings is not None):
            raise MissionError('LITE_READONLY_REQUIRED')
        # Same AgentRuntime, with the existing inspection guard on every legacy
        # operational/approval endpoint. Only the typed read-only loop is added.
        runtime = AgentRuntime(None, '', PROJECT_DIR, inspection_only=True,
                               mission_context=mission_context)
        runtime._lite_profile = lite_profile
        try:
            if lite_profile.enabled and not inspection_only:
                from runtime.mission.lite_runtime import LiteBindings
                if type(lite_bindings) is not LiteBindings:
                    raise MissionError('INVALID_LITE_BINDINGS')
                if lite_profile.memory_mode != 'OFF' and lite_bindings.memory is not None:
                    from runtime.memory_patch.lite import LiteMemoryService
                    runtime._lite_memory = LiteMemoryService(lite_profile, mission_context, lite_bindings.memory)
                    runtime._memory_patch_service = runtime._lite_memory.service
                elif lite_profile.memory_mode == 'ACTIVE' or lite_profile.memory_profile_digest is not None:
                    raise MissionError('MEMORY_BINDINGS_REQUIRED')
                if lite_profile.cpl_mode != 'OFF' and lite_bindings.cpl is not None:
                    from runtime.mission.lite_cpl import LiteCPL
                    runtime._lite_cpl = LiteCPL(lite_profile, mission_context, runtime._lite_memory, lite_bindings.cpl)
                elif lite_profile.cpl_mode == 'ACTIVE':
                    raise MissionError('CPL_BINDINGS_REQUIRED')
                if lite_bindings.dynamics is not None and lite_profile.dynamics_profile_digest is not None:
                    from runtime.memory_patch.learning.dynamics import CoreDynamicsBindings, MemoryDynamics
                    if type(lite_bindings.dynamics) is not CoreDynamicsBindings or runtime._lite_cpl is None:
                        raise MissionError('DYNAMICS_BINDINGS_REQUIRED')
                    runtime._lite_cpl.learning.dynamics = MemoryDynamics(runtime._lite_cpl.learning,
                        lite_bindings.dynamics.policy, mission_context, lite_profile)
                elif 'ACTIVE' in {lite_profile.dvm_mode, lite_profile.pheromone_mode}:
                    raise MissionError('DYNAMICS_BINDINGS_REQUIRED')
                runtime._lite_scheduler = LiteScheduler(lite_profile, mission_context, lite_bindings,
                                                        memory=runtime._lite_memory, cpl=runtime._lite_cpl)
            return runtime
        except Exception:
            runtime.close()
            raise
    if inspection_only:
        if cpl_fixture or cpl_cost_policy is not None:
            from runtime.mission.contracts import MissionError
            raise MissionError('INSPECTION_ONLY', status='POLICY_BLOCKED', exit_code=4)
        return AgentRuntime(
            None, '', PROJECT_DIR, inspection_only=True,
            nonzero_config=nonzero_config, memory_patch_config=memory_patch_config,
            memory_patch_dependencies=memory_patch_dependencies,
            mission_context=mission_context, mission_bindings=mission_bindings)
    fixture = None
    if cpl_fixture:
        from critical_loop.fixture import LocalCPLFixture
        fixture = LocalCPLFixture()
    provider_manager = ProviderManager(PROJECT_DIR, fixture_base_url=fixture.base_url if fixture else None)
    prompt_template = load_prompt_template(PROMPT_FILE)
    runtime = AgentRuntime(
        provider_manager=provider_manager,
        prompt_template=prompt_template,
        project_dir=PROJECT_DIR,
        debug_raw=DEBUG_RAW_RESPONSE,
        nonzero_config=nonzero_config,
        memory_patch_config=memory_patch_config,
        memory_patch_dependencies=memory_patch_dependencies,
        mission_context=mission_context,
        mission_bindings=mission_bindings,
    )
    runtime.cpl_cost_policy = cpl_cost_policy
    runtime._owned_cpl_fixture = fixture
    return runtime


def main() -> None:
    import argparse
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'lite':
        from runtime.mission.lite_cli import run_lite_cli
        raise SystemExit(run_lite_cli(sys.argv[2:], runtime_factory=create_runtime))

    if len(sys.argv) > 1 and sys.argv[1] in {'doctor', 'mission'}:
        from runtime.mission.cli import run_diagnostic_cli
        raise SystemExit(run_diagnostic_cli(sys.argv[1:], runtime_factory=create_runtime))

    parser = argparse.ArgumentParser(description='AIOA spArkHAT — one local runtime, formerly AOIA-Core')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--cpl-fixture', action='store_true', help='Explicit synthetic local HTTP transport; no model API')
    mode.add_argument('--cpl-live-policy', help='Operator-authored price/budget policy JSON; still requires per-plan approval')
    parser.add_argument('--command', help='Execute one registered slash command and exit')
    parser.add_argument('--plain-chat', action='store_true', help='Explicit bypass of CPL for interactive questions; retains the legacy Core action/approval path')
    parser.add_argument('--cpl-run-budget', default='0', help='Per-question LIVE admission cap in USD; never substitutes for plan-hash/nonce approval')
    args = parser.parse_args()
    from critical_loop.policy import load_cost_policy
    policy = load_cost_policy(args.cpl_live_policy) if args.cpl_live_policy else None
    runtime = create_runtime(cpl_fixture=args.cpl_fixture, cpl_cost_policy=policy)
    if args.command is not None:
        try:
            result = runtime.command_registry.execute(args.command, runtime)
            if not result.handled:
                parser.error('--command requires a registered slash command')
            print(result.message)
            if result.exit_code:
                raise SystemExit(result.exit_code)
        finally:
            runtime.close()
        return

    print_banner(runtime)
    print('Assistant mode: Plain Chat — CPL BYPASS (not reviewed)' if args.plain_chat else
          'Assistant mode: Critical Prompt Loop — DEFAULT; questions create plans, never auto-approve.')

    while True:
        try:
            user_input = input("\nYou> ")

            if not user_input.strip():
                continue

            if user_input.strip().lower() in {"exit", "quit", "q"}:
                print("Exiting agent...")
                break

            command_result = runtime.command_registry.execute(user_input, runtime)
            if command_result.handled:
                if command_result.message:
                    print(f"\nAgent> {command_result.message}")
                continue

            result = runtime.assistant_request(user_input, mode='plain' if args.plain_chat else 'cpl',
                plan_options=None if args.plain_chat else {'run_budget_usd':args.cpl_run_budget})
            if result['mode'] == 'cpl':
                print(json.dumps(result['cpl'], ensure_ascii=False, indent=2))
                print('Inspect the immutable plan. To approve in this process: /cpl start RUN_ID PLAN_HASH NONCE')
            else:
                print(result['transcript'])
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
            break
        except Exception as error:
            runtime.log_error(
                {
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                }
            )
            print(f"\n[FATAL ERROR] {error}")
            break
    runtime.close()


if __name__ == "__main__":
    main()
