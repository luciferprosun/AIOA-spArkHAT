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
from runtime.core_admission import AdmissionError
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
        'runtime/mobile_gateway/pairing.py', 'protocol/mobile_pairing_v1.json',
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
SOURCE_FILES += ('web/mobile_devices.js','web/mobile_devices_dom.js','web/qr.js')
SOURCE_FILES += tuple('clients/android/app/src/main/java/eu/sparkhat/aioa/companion/'+name
        for name in ('PairingProtocol.kt','TrustedHostStore.kt','CosmicScreen.kt',
                     'PairingProblem.kt','SessionRecovery.kt','RecoveryNetworkMonitor.kt'))
SOURCE_FILES += tuple('clients/android/app/src/main/res/'+name+'/strings.xml'
        for name in ('values','values-pl'))
SOURCE_FILES += ('web/cosmic_tokens.css',
        'web/cosmic_space_grotesk.ttf','web/cosmic_manrope.ttf','web/cosmic_ibm_plex_mono.ttf',
        'web/cosmic_fonts_ofl.txt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/CosmicTheme.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/PairingDelivery.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/CosmicMissionPages.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/CosmicComponents.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/CosmicPresentation.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MissionUi.kt',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/TaskReadback.kt',
        'clients/android/app/src/main/res/values/cosmic_colors.xml',
        'clients/android/app/src/main/res/font/cosmic_space_grotesk.ttf',
        'clients/android/app/src/main/res/font/cosmic_manrope.ttf',
        'clients/android/app/src/main/res/font/cosmic_ibm_plex_mono.ttf',
        'clients/android/app/src/main/assets/licenses/cosmic_fonts_ofl.txt')
SOURCE_FILES += ('runtime/meta_hackathon/chat.py','runtime/mobile_gateway/chat_views.py',
        'runtime/mobile_gateway/operator_chat.py','runtime/mobile_gateway/chrome_console.py',
        'protocol/mobile_chat_v1.json','web/mobile_chat.js',
        'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/ChatView.kt')
SOURCE_FILES += ('runtime/mcp_bridge/native_read.py','runtime/meta_hackathon/native_tools.py')


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


def _desktop_operator_uid():
    """Authenticate the actual OS subject through the existing system polkit.

    No flag, model text, environment identity or persisted JSON grants admission.
    PID/start-time/UID are bound together to prevent PID-reuse substitution.
    """
    try:
        uid,pid=os.getuid(),os.getpid()
        if uid==0:raise AdmissionError()
        for name in ('/usr/bin/pkcheck','/usr/bin/loginctl'):
            info=Path(name).lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:raise AdmissionError()
        environment={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}
        for name in ('DISPLAY','XAUTHORITY'):
            if name in os.environ:environment[name]=os.environ[name]
        session=subprocess.run(['/usr/bin/loginctl','show-session','self','-p','User','-p','Active','-p','Remote'],
            env=environment,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=10)
        fields=dict(line.split('=',1) for line in session.stdout.splitlines() if '=' in line)
        if session.returncode or fields!={'User':str(uid),'Remote':'no','Active':'yes'}:raise AdmissionError()
        raw=Path('/proc/self/stat').read_text();started=raw[raw.rfind(')')+2:].split()[19]
        result=subprocess.run(['/usr/bin/pkcheck','--action-id','org.freedesktop.policykit.exec',
            '--process',f'{pid},{started},{uid}','--allow-user-interaction'],env=environment,
            stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=120)
        if result.returncode!=0:raise AdmissionError()
        return uid,{'method':'SYSTEM_POLKIT_ACTIVE_LOCAL_SESSION','action':'org.freedesktop.policykit.exec',
            'uid':uid,'pid':pid,'process_start':started}
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        raise AdmissionError() from error


class NativeMobileComposition:
    """Read-only phone transport in the existing app, without a model/worker.

    One admitted Core, MissionService and native TransactionRunner. The local
    persistent record adapter carries all mobile records and native audit/outbox.
    This is neither OfflineMetaComposition nor a promotion of its fixture data.
    """
    def __init__(self,root,*,origin,source_probe=current_source,chat=False,key_path=None):
        import time
        from runtime.mobile_gateway import wire
        self.origin=wire.origin(origin)
        if self.origin=='https://fixture.invalid':raise AdmissionError()
        self.uid,self.operator_authentication=_desktop_operator_uid()
        if type(chat) is not bool:raise AdmissionError()
        from runtime.providers.meta_model_api import KEY_FILE,key_metadata
        self.chat_enabled=chat
        self._meta_key_path=Path(key_path) if key_path is not None else KEY_FILE
        if chat and not key_metadata(self._meta_key_path)['configured']:raise ValueError('META_KEY_NOT_CONFIGURED')
        self.profile='NATIVE_ADVISORY_CHAT_V1' if chat else 'NATIVE_STATUS_READ_ONLY_V1'
        self.source_probe,self.source=source_probe,tuple(source_probe())
        self._auth_deadline=time.monotonic()+3600
        self.root=Path(root).absolute()
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        info=self.root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or self.root.resolve()!=self.root or info.st_uid!=self.uid
                or info.st_mode&0o077):raise AdmissionError()
        self._lease=os.open(self.root/'runtime.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        info=os.fstat(self._lease)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=self.uid or info.st_nlink!=1 or info.st_mode&0o077:
            os.close(self._lease);raise AdmissionError()
        try:fcntl.flock(self._lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:os.close(self._lease);raise AdmissionError() from None
        self._closed=False
        try:self._initialize()
        except BaseException:self.close();raise

    def _initialize(self):
        from main import create_runtime
        from runtime.memory_patch.persistence.ports import LocalCoreRecordFactory
        from runtime.mobile_gateway import wire
        from runtime.mobile_gateway.service import MobileGateway
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        scope=OwnerScope('local-linux',f'uid-{self.uid}','aioa-main','mobile-status')
        # True is derived from successful system authentication above, never a
        # caller-supplied approval flag or a synthetic fixture assignment.
        admitted=self.operator_authentication['uid']==os.getuid()
        capabilities={Capability.READ,Capability.COMMIT,Capability.OWNER_APPROVAL}
        if self.chat_enabled:capabilities.add(Capability.MANAGE)
        self.core=CoreAdmission(LocalOwnerAssignment(scope,frozenset(capabilities),
            frozenset({'mobile-status'}),frozenset({MODEL if self.chat_enabled else 'NO_MODEL_PAIRING'}),operator_approved=admitted))
        self.instance_id=self.core.local_operator(Capability.READ).actor_session_id
        self.runtime=create_runtime(inspection_only=True)
        self.runtime._memory_patch_admission=self.core
        self.runner=TransactionRunner(self.core,LocalCoreRecordFactory(self.root/'core-records.sqlite3',self.core))
        self.ledger=CoreWarrantLedger(self.core,self.runner,scope)
        self.manager=None
        if self.chat_enabled:
            self.manager=ProviderManager(ROOT,meta_only=True)
            self.manager.configure_meta(MetaModelProvider(mode='LIVE',key_path=self._meta_key_path))
        self.missions=MissionService(self.ledger,self.manager,None,self.source_probe)
        path=self.root/'host-signing-key.pem'
        if path.exists() or path.is_symlink():
            info=path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=self.uid or info.st_nlink!=1
                    or info.st_mode&0o077 or info.st_size>1024):raise AdmissionError()
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            try:key=serialization.load_pem_private_key(os.read(fd,1025),password=None)
            finally:os.close(fd)
        else:
            key=ec.generate_private_key(ec.SECP256R1())
            data=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        self.identity=wire.Identity(key)
        self.tls_verified=False
        self.mobile=MobileGateway(self.missions,identity=self.identity,native_host=self)
        if self.chat_enabled:
            from runtime.mission.governor import CoreDualGovernor,GovernorPolicy,Limits
            limits=Limits(50000000,20)
            self.chat_governor=CoreDualGovernor(self.core,self.runner,GovernorPolicy(scope,'native-mobile-chat-v1',limits,limits,limits,max_clock_step_seconds=3600))
            self.chat_governor.start_epoch(self.core.local_operator(Capability.MANAGE))
            self.missions.bind_chat(self.chat_governor,self._chat_authority)
        now=int(datetime.now(timezone.utc).timestamp())
        self.mobile._run(Capability.COMMIT,lambda tx:self.mobile._record(tx,
            'mobile-operator-'+self.instance_id,{'state':'MOBILE_OPERATOR_ADMISSION',
                'authentication':self.operator_authentication,'source_sha':self.source[0],
                'capsule_digest':self.source[1],'core_instance_id':self.instance_id},at=now))

    def operator_principal(self):
        import time
        if (self._closed or os.getuid()!=self.uid or time.monotonic()>=self._auth_deadline
                or tuple(self.source_probe())!=self.source):raise AdmissionError()
        return self.core.local_operator(Capability.OWNER_APPROVAL)

    def _chat_authority(self,task):
        """Recheck the admitted OS owner and actual registered device/session."""
        from runtime.memory_patch.persistence.ports import RecordKind
        import time
        try:
            self.operator_principal()
            if task.source_sha!=self.source[0]:return False
            if task.actor=='LINUX_OWNER':
                return task.session_id==canonical_sha256(self.instance_id)[:32]
            device=self.mobile._get('mobile-device-'+task.device_id)
            if device is None or device.payload.get('revoked') is not False:return False
            rows=self.mobile._run(Capability.READ,lambda tx:tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_SESSION',)))
            return any(r.payload.get('session_id')==task.session_id and r.payload.get('device_id')==task.device_id
                and r.payload.get('core_instance_id')==self.instance_id and r.payload.get('revoked') is False
                and r.payload['expires_at']>time.time() and r.payload.get('source_sha')==self.source[0]
                and r.payload.get('capsule_digest')==self.source[1] for r in rows)
        except Exception:return False

    def qualify_tls(self,port):
        """System-CA/hostname/TLS1.3 plus a signed challenge of this same app."""
        import base64,http.client,secrets,socket,ssl,time
        from urllib.parse import urlsplit
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from runtime.mobile_gateway import wire
        self.operator_principal()
        context=ssl.create_default_context()
        context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_3
        peer=context.wrap_socket(socket.create_connection(('127.0.0.1',port),timeout=8),
            server_hostname=urlsplit(self.origin).hostname)
        try:
            if peer.version()!='TLSv1.3':raise AdmissionError()
            certificate=x509.load_der_x509_certificate(peer.getpeercert(binary_form=True))
            challenge=secrets.token_hex(32)
            client=http.client.HTTPConnection('127.0.0.1',port,timeout=8);client.sock=peer
            client.request('GET',wire.BASE+'/capabilities',headers={'Host':urlsplit(self.origin).hostname,'X-AIOA-Challenge':challenge})
            response=client.getresponse();raw=response.read(65537)
            if response.status!=200 or len(raw)>65536:raise AdmissionError()
            value=wire.strict_json(raw);proof=value['proof']
            wire.verify(self.identity.spki,value['signature'],proof)
            caps=value['capabilities'];now=int(time.time())
            if (proof['challenge']!=challenge or proof['origin']!=self.origin or proof['host_spki']!=self.identity.spki
                    or proof['schema']!='aioa.mobile.host-proof.v1' or proof['audience']!=self.identity.audience
                    or proof['owner_scope_digest']!=self.mobile.owner_scope_digest
                    or (proof['source_sha'],proof['capsule_digest'])!=self.source
                    or not proof['issued_at']<=now<proof['expires_at']<=proof['issued_at']+30
                    or proof['capabilities_sha256']!=wire.digest(wire.canonical(caps))
                    or caps['profile']!=self.profile or caps['chat'] is not self.chat_enabled
                    or any(caps[k] is not False for k in ('run','approve','meta_spend','native_execute','github_write','install'))):
                raise AdmissionError()
            public=certificate.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
            self.tls_pin='sha256/'+base64.b64encode(hashlib.sha256(public).digest()).decode()
            self.tls_certificate_sha256=hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
            self._tls_expires=certificate.not_valid_after.replace(tzinfo=timezone.utc).timestamp()
            if self._tls_expires<=time.time()+300:raise AdmissionError()
            self.tls_verified=True
        finally:peer.close()

    def _require_qualified_operator(self):
        """No transaction or model ledger reads: safe inside a Core callback."""
        import time
        self.operator_principal()
        if not self.tls_verified or time.time()>=self._tls_expires:raise AdmissionError()

    def public_settings(self):
        self._require_qualified_operator()
        return {'profile':self.profile,'origin':self.origin,'tls_spki_pin':self.tls_pin,
            'host_spki':self.identity.spki,'source_sha':self.source[0],'capsule_digest':self.source[1],
            'operator_authentication':self.operator_authentication,'model_calls':self.model_calls()}

    def model_calls(self):
        if not self.chat_enabled:return 0
        from runtime.providers.meta_receipts import FILTER
        from runtime.memory_patch.persistence.ports import RecordKind
        return self.mobile._run(Capability.READ,lambda tx:len(tx.scan(RecordKind.OPERATION,limit=128,states=FILTER)))

    def operator_request(self,peer_uid,value):
        """Called only by the private socket after kernel SO_PEERCRED lookup."""
        from runtime.mobile_gateway import wire
        from runtime.mobile_gateway.service import plain
        from runtime.memory_patch.persistence.ports import RecordKind
        if peer_uid!=self.uid:raise AdmissionError()
        owner=self.operator_principal()
        if type(value) is not dict or type(value.get('op')) is not str:raise wire.MobileError(400)
        op=value['op']
        if op in ('tool_read','tool_readback','tool_proposal'):
            from .native_tools import dispatch
            return dispatch(self,owner,value)
        if op.startswith('chat_'):
            from runtime.mobile_gateway.operator_chat import dispatch
            return dispatch(self,owner,value)
        from runtime.mobile_gateway.pairing import Pairing, OWNER_FIELDS
        if op in OWNER_FIELDS:return Pairing(self.mobile).owner(owner,value)
        fields={'settings':{'op'},'status':{'op'},'enroll':{'op','request_id','device_spki'},'revoke':{'op','device_spki'}}
        if op not in fields or set(value)!=fields[op]:raise wire.MobileError(400)
        if op=='settings':return self.public_settings()
        if op=='enroll':
            key=value['device_spki'];wire.public_key(key)
            code=self.mobile.issue_enrollment(owner,key,ttl=300,native_request_id=value['request_id'])
            return {'enrollment_code':code,'expires_in_seconds':300,'device_id':wire.digest(wire.unbase64(key)),
                'request_id':value['request_id'],'source_sha':self.source[0]}
        if op=='revoke':
            wire.public_key(value['device_spki']);device=wire.digest(wire.unbase64(value['device_spki']))
            if self.mobile._get('mobile-device-'+device) is not None:
                return Pairing(self.mobile).owner(owner,{'op':'pairing_revoke','device_id':device})
            now=int(self.mobile.clock())
            def revoke(tx):
                count=0
                for row in tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_SESSION',)):
                    if row.payload['device_id']==device and not row.payload['revoked']:
                        data=plain(row.payload);data.pop('schema');data['revoked']=True
                        self.mobile._record(tx,row.record_id,data,row,at=now);count+=1
                return count
            return {'revoked_sessions':self.mobile._run(Capability.COMMIT,revoke),'device_id':device}
        def inspect(tx):
            sessions=tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_SESSION',))
            observations=tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_OBSERVATION',))
            sessions=[r for r in sessions if r.payload.get('core_instance_id')==self.instance_id]
            observations=sorted((r for r in observations if r.payload.get('core_instance_id')==self.instance_id),
                key=lambda r:r.payload['proof']['issued_at'],reverse=True)
            return {'sessions':[{k:r.payload[k] for k in ('device_id','session_id','expires_at','revoked','nonce_count')}
                for r in sessions[:8]],'history_truncated':len(sessions)>8 or len(observations)>8,
                'observations':[{'proof':plain(r.payload['proof']),'signature':r.payload['signature']}
                    for r in observations[:8]]}
        from .native_tools import registry
        return {**self.public_settings(),**self.mobile._run(Capability.READ,inspect), 'components':registry(self)}

    def close(self):
        if self._closed:return
        self._closed=True
        try:
            if hasattr(self,'missions'):self.missions.close()
        finally:
            try:
                if hasattr(self,'runner'):self.runner.close()
            finally:
                try:
                    if hasattr(self,'runtime'):self.runtime.close()
                    if hasattr(self,'core'):self.core.close()
                finally:os.close(self._lease)
