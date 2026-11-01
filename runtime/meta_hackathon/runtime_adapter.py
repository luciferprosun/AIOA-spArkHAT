"""Explicit OFFLINE profile of the existing AgentRuntime and WebRuntimeService.

Uses one Core and the existing durable demo transaction adapter, never a new
authority backend. Synthetic admission is confined to this labelled profile.
LIVE bindings must be provided independently by a trusted native host.
"""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

from runtime.browser_agent.chrome_read_adapter import ChromeReadAdapter, FixtureReadDriver
from runtime.core_admission import Capability, CoreAdmission, LocalOwnerAssignment, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.warrant import CoreWarrantLedger
from runtime.providers.config import ProviderManager
from runtime.providers.meta_model_api import MetaModelProvider, MODEL
from .mission_service import MissionService

ROOT = Path(__file__).resolve().parents[2]


SOURCE_FILES = ('runtime/meta_hackathon/runtime_adapter.py', 'runtime/meta_hackathon/mission_service.py',
        'runtime/meta_hackathon/mission_read_offline.py', 'runtime/providers/meta_model_api.py',
        'runtime/browser_agent/chrome_read_adapter.py', 'runtime/core_admission.py',
        'runtime/providers/config.py', 'runtime/mission/warrant.py', 'runtime/webapp.py',
        'web/app.js', 'web/meta_mission.js', 'web/index.html', 'web/styles.css',
        'runtime/providers/meta_receipts.py', 'runtime/browser_agent/chrome_process_read.py',
        'runtime/mission/governor.py', 'runtime/providers/exact.py',
        'runtime/providers/tool_calling.py', 'runtime/memory_patch/persistence/ports.py',
        'runtime/memory_patch/contracts/serialization.py', 'runtime/meta_hackathon/contracts.py',
        'runtime/meta_hackathon/muse_plan.py', 'runtime/meta_hackathon/network_admission.py',
        'runtime/browser_agent/offline_adapter.py', 'lab/archaioa/warrant.py',
        'lab/archaioa/authority.py', 'lab/archaioa/decision_root.py',
        'runtime/mobile_gateway/__init__.py', 'runtime/mobile_gateway/wire.py',
        'runtime/mobile_gateway/service.py', 'protocol/mobile_mission_v1.json',
        'runtime/memory_patch/audit.py', 'runtime/memory_patch/persistence/idempotency.py',
        'runtime/memory_patch/contracts/records.py', 'runtime/memory_patch/contracts/enums.py',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/Wire.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/TransportIdentity.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MobileClient.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MissionViewModel.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/Freshness.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MainActivity.kt',
        'clients/android/app/src/main/AndroidManifest.xml',
        'clients/android/app/src/main/res/xml/network_security_config.xml',
        'clients/android/app/src/main/res/xml/data_extraction_rules.xml')

SOURCE_FILES += ('LICENSE', 'runtime/meta_hackathon/agent_operations.py',
        'runtime/mission/intent.py', 'runtime/mission/tools.py', 'runtime/mission/liability.py',
        'runtime/service_guard/service.py', 'runtime/mission/project_recipe.py',
        'runtime/mission/project_worker.py', 'runtime/mission/workspace_worker.py',
        'runtime/mission/sensorbridge_template.py', 'runtime/mission/sensorbridge_checks.py',
        'runtime/mission/sandbox_linux.py', 'runtime/mission/sandbox_worker.py',
        'runtime/mission/sandbox_contracts.py', 'runtime/mission/native/worker_gate.c',
        'runtime/mission/native/bootstrap.c', 'runtime/mission/git_publish.py',
        'runtime/mission/git_publish_worker.py', 'runtime/mission/git_recipe.py',
        'runtime/mission/git_worker.py', 'runtime/mission/install_plan.py')
SOURCE_FILES += ('runtime/mcp_bridge/adapter.py','runtime/mcp_bridge/policy.py',
        'runtime/mcp_bridge/read_ops.py','runtime/mcp_bridge/contracts.py','runtime/mcp_bridge/task_bus.py',
        'runtime/mobile_gateway/views_v2.py','protocol/mobile_mission_v2.json',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/AgentMissionView.kt')
SOURCE_FILES += ('runtime/meta_hackathon/web_agent.py','web/agent_mission.js',
        'clients/android/ANDROID_BUILD_INPUT_MANIFEST.json')


def sealed_source_path(relative, *, root=None):
    """Fixed source list only; reject links before any source content read."""
    base = Path(root or ROOT).absolute()
    parts = Path(relative).parts
    if base.is_symlink() or Path(relative).is_absolute() or any(p in ('.','..') for p in parts):
        raise ValueError('META_SOURCE_PATH_DENIED')
    path = base
    for piece in parts:
        path = path/piece
        if path.is_symlink():raise ValueError('META_SOURCE_SYMLINK_DENIED')
    if not stat.S_ISREG(path.lstat().st_mode):raise ValueError('META_SOURCE_TYPE_DENIED')
    return path


def current_source():
    sha = subprocess.run(['git', '--no-optional-locks', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                         capture_output=True, text=True, timeout=3).stdout.strip()
    capsule = canonical_sha256({p: hashlib.sha256(sealed_source_path(p).read_bytes()).hexdigest() for p in SOURCE_FILES})
    return sha if len(sha) == 40 else capsule[:40], capsule


class OfflineMetaComposition:
    def __init__(self, root, *, delay_seconds=.6, source_probe=current_source):
        from main import create_runtime
        from runtime.personal_ai_fixture import DurableFactory
        self.root = Path(root).absolute()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or self.root.is_symlink() or info.st_uid != os.getuid()
                or info.st_mode & 0o077): raise ValueError('META_PRIVATE_STATE_DENIED')
        self._lease = os.open(self.root/'runtime.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try: fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._lease); raise ValueError('META_RUNTIME_ALREADY_ACTIVE') from None
        self._closed = False
        clock = lambda: datetime.now(timezone.utc)
        scope = OwnerScope('offline-fixture', 'offline-operator', 'offline-meta', 'single-runtime')
        self.core = CoreAdmission(LocalOwnerAssignment(scope,
            frozenset({Capability.READ, Capability.COMMIT, Capability.OWNER_APPROVAL, Capability.MANAGE}),
            frozenset({'offline-fixture'}), frozenset({MODEL}), operator_approved=True), clock=clock)
        self.runtime = create_runtime(inspection_only=True)
        self.runtime._memory_patch_admission = self.core
        self.manager = ProviderManager(ROOT, meta_only=True)
        def fixture(payload, cancel, timeout):
            value = json.loads(payload['messages'][-1]['content']); value.pop('instruction')
            body = {'id': 'chatcmpl-offline-fixture', 'model': MODEL, 'choices': [{'index': 0,
                'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'call_'+value['task_id'], 'type': 'function', 'function': {
                    'name': 'navigate_read', 'arguments': json.dumps(value, sort_keys=True)}}]}}],
                'usage': {'prompt_tokens': 50, 'completion_tokens': 30, 'total_tokens': 80}}
            return 200, json.dumps(body).encode()
        self.manager.configure_meta(MetaModelProvider(mode='MOCK', transport=fixture))
        self.runtime.provider_manager = self.manager
        state = self.root/'core-records.json'
        if state.exists() and (state.is_symlink() or not stat.S_ISREG(state.stat().st_mode)
                               or state.stat().st_mode & 0o077): raise ValueError('META_PRIVATE_STATE_DENIED')
        self.runner = TransactionRunner(self.core, DurableFactory(state))
        self.ledger = CoreWarrantLedger(self.core, self.runner, scope, clock=clock)
        self.driver = FixtureReadDriver(delay_seconds=delay_seconds)
        self.browser = ChromeReadAdapter(self.driver)
        self.missions = MissionService(self.ledger, self.manager, self.browser, source_probe)

    def enable_unified(self, *, config=None):
        """Explicit labelled fixture composition of the existing app, not LIVE GO."""
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        from runtime.mobile_gateway.wire import Identity
        from runtime.mobile_gateway.service import MobileGateway
        from runtime.mission.project_recipe import prepare_sensorbridge_sandbox
        from runtime.mission.sandbox_linux import save_host_config,load_host_config
        if hasattr(self,'mobile'):raise ValueError('UNIFIED_ALREADY_CONFIGURED')
        if config is None:
            cache=self.root/('sandbox-'+self.missions.source_probe()[1][:16])
            if (cache/'host-config.json').exists():config=load_host_config(cache,trusted_root=self.root)
            else:
                config=prepare_sensorbridge_sandbox(cache,workspace='workspace-sensorbridge')
                save_host_config(config)
        self.missions.bind_agent_tools(config,self.core.local_operator(Capability.OWNER_APPROVAL))
        # Only this profile's freshly generated fixture key, never user/API keys.
        key_path=self.root/'fixture-transport-key.pem'
        if key_path.exists():
            info=key_path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>1024:
                raise ValueError('UNIFIED_FIXTURE_KEY_DENIED')
            fd=os.open(key_path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            try:key=serialization.load_pem_private_key(os.read(fd,1025),password=None)
            finally:os.close(fd)
        else:
            key=ec.generate_private_key(ec.SECP256R1())
            raw=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
            fd=os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                with os.fdopen(fd,'wb',closefd=False) as stream:stream.write(raw);stream.flush();os.fsync(fd)
            finally:os.close(fd)
        self.mobile=MobileGateway(self.missions,identity=Identity(key),fixture=True)
        return self

    def close(self):
        if self._closed: return
        self._closed = True
        try:
            self.missions.close(); self.runner.close(); self.runtime.close()
        finally:
            os.close(self._lease)
