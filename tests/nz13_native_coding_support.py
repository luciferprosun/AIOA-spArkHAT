"""Causal Native completion checks; synthetic owned data never grants OS admission."""
import inspect
import unittest


def require_parameter(case, target, name, reason):
    case.assertIn(name, inspect.signature(target).parameters, reason)


def require_method(case, target, name, reason):
    case.assertTrue(callable(getattr(target, name, None)), reason)


class NativeCompletionCase(unittest.TestCase):
    """Missing product seams fail explicitly before any new fixture is constructed."""


ACTUAL_CONTEXT = None
OWNED_ROOTS = []


class NativeOwnedFixture:
    """Explicit disposable administration, then one Native graph on retained DB."""
    def __init__(self, case, *, prepare_execution_capacity=True):
        import base64
        import hashlib
        import json
        import os
        import tempfile
        import time
        from dataclasses import asdict, replace
        from pathlib import Path

        import nz13_native_foundation_support as foundation_fixture
        from nonzero_cloudops.adapters.portable import PortableStateStore
        from nonzero_cloudops.adapters.resources import default_mock_resources
        from nz11_support import BareRepository
        from runtime.core_admission import Capability, OwnerScope
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.ports import (
            RecordKind,
            TransactionContext,
        )
        from runtime.meta_hackathon import runtime_adapter
        from runtime.mission.git_publish import GitSourceSnapshot
        from runtime.mission.governor import GovernorPolicy, Limits
        from runtime.mission.project_recipe import (
            PythonFunctionCase,
            PythonRepositoryRecipe,
        )
        from runtime.mission.sandbox_contracts import PYTHON_ARGV
        from runtime.mission.sandbox_linux import (
            prepare_linux_sandbox,
            save_host_config,
        )
        from runtime.mission.target_projection import CoreTargetProjection
        from runtime.mission.worker import CandidateFile, CandidatePatch, Task
        case.assertIsNotNone(ACTUAL_CONTEXT, 'EXPLICIT_ACTUAL_CONTEXT_REQUIRED')
        self.case, self.context = case, ACTUAL_CONTEXT
        self.root = Path(tempfile.mkdtemp(prefix='owned-native-completion-', dir=self.context['fixture_root']))
        self.retained = {}
        self.native_root = Path(tempfile.mkdtemp(prefix='nc-', dir=self.context['fixture_root'].parent))
        self.context.setdefault('owned_roots', set()).add(self.native_root)
        self.runtime_tmp = Path(tempfile.mkdtemp(prefix='nt-', dir=self.native_root.parent))
        self.context['owned_roots'].add(self.runtime_tmp)
        OWNED_ROOTS.extend((str(self.root), str(self.native_root), str(self.runtime_tmp)))
        old_tmp = tempfile.tempdir
        tempfile.tempdir = str(self.runtime_tmp)
        case.addCleanup(setattr, tempfile, 'tempdir', old_tmp)
        from runtime.webapp import make_server
        self.reserved_server = make_server('127.0.0.1', 0)
        self.origin = 'https://fixture.example.org:' + str(self.reserved_server.server_address[1])
        case.addCleanup(self.reserved_server.server_close)
        raw_files = {'README.md': b'# Owned local text fixture\n',
                     'src/textutil.py': b'def slug(text):\n    return text.strip()\n'}
        self.source_repo = BareRepository(self.root / 'source.git', raw_files)
        self.target_repo = BareRepository(self.root / 'target.git', raw_files)
        self.target_repo.mark_disposable()
        case.assertEqual(self.source_repo.base, self.target_repo.base)
        snapshot = GitSourceSnapshot.capture(self.source_repo.path, expected_sha=self.source_repo.base,
                                            repository_id='text-repository', workspace_id='workspace-1')
        source = snapshot.export(self.root / 'base')
        for name in ('candidates', 'cache', 'managed'):
            (self.root / name).mkdir(mode=0o700)
        oracle = PythonFunctionCase('normalized', 'textutil', 'slug', b'[" Hello World "]', b'"hello-world"')
        profile = PythonRepositoryRecipe(source.repository_id, source.source_base_sha,
            ('src/extra.py', 'src/textutil.py'), ('src',),
            tuple((stage, (oracle,)) for stage in ('FAST_TESTS', 'TARGETED_TESTS', 'FINAL_TESTS')), PYTHON_ARGV)
        runtime_dir = self.root / 'cache/runtime'
        runtime_dir.mkdir(mode=0o700)
        manifest = {}
        for index, (target, entry) in enumerate(self.context['runtime_manifest']['manifest'].items()):
            raw = self.context['safe'].read(Path(entry['snapshot']), maximum=entry['bytes'])
            case.assertEqual((entry['bytes'], entry['sha256']), (len(raw), hashlib.sha256(raw).hexdigest()))
            path = runtime_dir / str(index)
            path.write_bytes(raw)
            mode = self.context['safe'].info(Path(entry['snapshot'])).st_mode & 0o700
            path.chmod(mode)
            manifest[target] = {**entry, 'snapshot': str(path)}
        from runtime.mission.sandbox_bindings import MaterializationBindingInput
        from runtime.mission.worker import WorkerSession
        task = Task('native-repair', 'native-run', source.workspace_id, source.repository_id,
                    source.source_base_sha, 'Normalize whitespace and casing; include a finite helper.', int(time.time()) + 3600)
        candidates = (CandidatePatch((CandidateFile('src/textutil.py', 'def slug(text):\n    return text.strip()\n'),)),
                      CandidatePatch((CandidateFile('src/extra.py', 'def title(text):\n    return text.lower()\n'),
                                      CandidateFile('src/textutil.py', 'def slug(text):\n    return "-".join(text.lower().split())\n'))))
        # A changes source bytes while still failing the independent oracle.
        candidates = (CandidatePatch((CandidateFile('src/textutil.py', 'def slug(text):\n    return text.strip() + ""\n'),)), candidates[1])
        ownership_negatives = {
            'test_git_stop_before_applying_has_no_start_or_release',
            'test_git_stop_before_core_start_has_no_physical_release',
            'test_git_lost_applying_ack_retains_unknown_and_fences_new_work',
            'test_git_lost_physical_ack_reconciles_exact_owned_history_without_resend',
            'test_historical_git_warrant_settles_at_canonical_current_epoch',
            'test_git_reconciliation_scope_ownership_denials_and_lost_verified_ack',
            'test_git_ordinary_mutation_callbacks_do_not_read_source_in_sql',
            'test_git_historical_mutation_callbacks_do_not_read_source_in_sql',
        }
        self.single_good_candidate = (case._testMethodName in ownership_negatives
            or self.context.get('restart_phase') in ('ORPHAN_RUNNING_ACK_PRODUCE',
                                                    'TERMINAL_CHILD_ACQUISITION_PRODUCE'))
        if self.single_good_candidate:
            # These lifecycle negatives need one genuine signed review, not a
            # second proof of A/B repair. All four physical stages stay real.
            candidates = (candidates[1],)
        session = WorkerSession('seed-session', task.task_id, task.run_id, task.digest, 'offline-seed')
        binding = MaterializationBindingInput(task, session, candidates[0])
        seed_spec = profile.materialization_spec(self.root / 'base', source=source, task=task,
                                                worker_session_id=session.session_id, candidate=candidates[0])[2]
        seed = prepare_linux_sandbox(self.root / 'cache/seed', manifest, workspace=source.workspace_id,
                                     recipes={'0': seed_spec})
        retained_runtime = seed.root / 'runtime'
        retained_runtime.mkdir(mode=0o700)
        inside = {}
        for index, (target, entry) in enumerate(seed.runtime().items()):
            path = retained_runtime / str(index)
            path.write_bytes(self.context['safe'].read(Path(entry['snapshot']), maximum=entry['bytes']))
            path.chmod(entry['mode'])
            inside[target] = {**entry, 'snapshot': str(path)}
        seed = replace(seed, runtime_bytes=json.dumps(inside, sort_keys=True, separators=(',', ':')).encode())
        seed = replace(seed, registry=replace(seed.registry,
            recipes=tuple(replace(recipe, timeout_ms=20000) for recipe in seed.registry.recipes)))
        save_host_config(seed)
        scope = OwnerScope('local-linux', f'uid-{os.getuid()}', 'aioa-main', 'mobile-status')
        limits = Limits(50000000, 20)
        policy = GovernorPolicy(scope, 'native-mobile-chat-v1', limits, limits, limits, max_clock_step_seconds=3600)
        target_id = 'native-portable'
        head_key = canonical_sha256(('aioa-core-target-head.v1', scope, source.workspace_id, target_id))
        registration_key = canonical_sha256(('aioa-core-target-registration.v1', head_key))
        inventory = self.root / 'managed/.aioa-core-managed-v1' / canonical_sha256(scope) / registration_key / 'inventory.json'
        inventory.parent.mkdir(mode=0o700, parents=True)
        for directory in inventory.parents:
            if directory == self.root: break
            directory.chmod(0o700)
        administration = PortableStateStore(self.root / 'administration/inventory.json')
        with administration._lock(exclusive=True):
            resources, receipts = administration._initial_snapshot()
            administration._write(resources, receipts)
        inventory.write_bytes(self.context['safe'].read(administration.path))
        inventory.chmod(0o600)
        inventory.with_name('inventory.json.lock').write_bytes(b'')
        inventory.with_name('inventory.json.lock').chmod(0o600)
        query = next(resource for resource in default_mock_resources() if resource.resource_type.value == 'AWS::EC2::EIP')
        self.body = {'schema': 'aioa.native-host-composition.v1', 'profile': 'OWNED_OFFLINE_PROOF_V1',
            'host_source': dict(zip(('source_sha', 'capsule_digest'), runtime_adapter.current_source(), strict=True)),
            'bootstrap_policy_digest': policy.digest, 'base_root': str(self.root / 'base'),
            'candidate_root': str(self.root / 'candidates'), 'source_repository': str(self.source_repo.path),
            'git_target_repository': str(self.target_repo.path), 'sandbox_cache_root': str(seed.root),
            'project_source': asdict(source),
            'source_snapshot': {'repository_id': snapshot.repository_id, 'workspace_id': snapshot.workspace_id,
                'source_base_sha': snapshot.source_base_sha, 'git_tree_sha': snapshot.git_tree_sha, 'ref': snapshot.ref,
                'files': [[name, base64.b64encode(raw).decode()] for name, raw in snapshot.files]},
            'recipe': json.loads(profile.manifest_bytes()),
            'sandbox_seed': {'descriptor_path': str(seed.root / 'host-config.json'),
                             'descriptor_sha256': hashlib.sha256(self.context['safe'].read(seed.root / 'host-config.json')).hexdigest()},
            'retained_sandbox_task_ids': [],
            'accounting': {'job_model_id': 'aioa/offline-host-worker-v1', 'job_provider_id': 'offline-host',
                           'effect_model_binding_id': 'aioa/offline-host-worker-v1'},
            'operations': ['GIT_COMMIT', 'PORTABLE_REARM_DEMO_V1', 'PORTABLE_RELEASE_ELASTIC_IP', 'SANDBOX_EXEC'],
            'portable': {'binding': {'scope': list(scope.binding()), 'workspace': source.workspace_id,
                         'target_id': target_id, 'incarnation': 'pre-administration', 'guard_fingerprint': 'f' * 64},
                         'inventory_path': str(inventory), 'registration_digest': '1' * 64, 'adoption_digest': '2' * 64,
                         'expected_head_revision': 1, 'generation': 0, 'history_digest': '3' * 64,
                         'resource_query': {'resource_type': query.resource_type.value, 'resource_id': query.resource_id,
                                            'region': query.region}},
            'limits_plan': {'sandbox_effects': 8, 'local_git_effects': 2, 'portable_effects': 2,
                            'max_duration_seconds': 3600, 'proposed_capacity': foundation_fixture.proposal()}}
        self.candidates, self.task, self.binding = candidates, task, binding
        admin = self.construct(None)
        foundation_fixture.fixture_tls(admin)
        foundation_fixture.initialize(admin)
        f = admin.foundation
        store = PortableStateStore(inventory)
        with store.target_guard():
            observed = store.observe_guarded_inventory()
            projection, request = CoreTargetProjection.prepare_existing_adoption(f.intent_journal, f.liability,
                admin.core.local_operator(Capability.COMMIT), workspace=source.workspace_id, target_id=target_id,
                state_root=observed.state_root, resources_root=observed.resources_root,
                receipts_root=observed.receipts_root, guard_fingerprint=observed.guard_fingerprint)
            warrant = self.adoption_warrant(admin, request)
            f.ledger.approve(admin.core.local_operator(Capability.OWNER_APPROVAL), warrant)
            receipt = admin.runner.run(TransactionContext(admin.core.local_operator(Capability.COMMIT), Capability.COMMIT),
                lambda tx: projection.adopt_existing_in_transaction(tx, warrant, request))
            def read(tx):
                row, state = projection.load(tx)
                return row, state, tx.get(RecordKind.OPERATION, projection.registration_key)
            row, state, registration = admin.runner.run(TransactionContext(
                admin.core.local_operator(Capability.READ), Capability.READ), read)
        self.body['portable'].update(binding={**asdict(request.binding), 'scope': list(scope.binding())},
            registration_digest=registration.payload_digest, adoption_digest=receipt['adoption_digest'],
            expected_head_revision=row.revision, generation=state['generation'], history_digest=state['history_digest'])
        case.assertTrue(admin.close()['closed'])
        self.host = self.construct(candidates)
        case.addCleanup(self.close)
        foundation_fixture.fixture_tls(self.host)
        if self.body['retained_sandbox_task_ids']:
            self.host._native_coding.restore_history()
        if prepare_execution_capacity:
            reviewed = foundation_fixture.review(self.host)
            foundation_fixture.approve(self.host, reviewed)
            foundation_fixture.apply(self.host, reviewed)
            case.assertEqual('ACTIVE', self.host.foundation.lifecycle.phase.value)
        else:
            case.assertEqual('CAPACITY_ADMIN', self.host.foundation.lifecycle.phase.value)

    def construct(self, candidates):
        import os
        from unittest.mock import patch

        from runtime.meta_hackathon import runtime_adapter
        from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
        with patch.object(runtime_adapter, '_desktop_operator_uid', return_value=(os.getuid(),
                {'uid': os.getuid(), 'method': 'FIXTURE_OS_ADMISSION'})):
            return runtime_adapter.NativeMobileComposition(self.native_root, origin=self.origin,
                host_composition=NativeHostCompositionConfig.from_dict(self.body), offline_candidates=candidates)

    @__import__('contextlib').contextmanager
    def profile_timings(self):
        if 'TIMING_DIAG' not in self.context['fixture_root'].name:
            yield
            return
        import hashlib
        import json
        import sys
        import threading
        import time

        from runtime.meta_hackathon import (
            native_authority,
            native_coding,
            runtime_adapter,
        )
        from runtime.mission.git_publish import GitSourceSnapshot
        from runtime.mission.intent import CoreIntentJournal
        from runtime.mission.sandbox_linux import LinuxSandboxBroker
        from runtime.mission.tools import CoreToolRoute
        functions = (native_authority.NativeCoreAccess.capture,
            native_authority.NativeCoreAccess.require_capture,
            native_authority.NativeHostCompositionConfig.observe,
            native_authority._directory_identity, runtime_adapter.current_source,
            runtime_adapter.NativeMobileComposition.operator_principal,
            CoreToolRoute._run, CoreToolRoute._probe_target, CoreToolRoute._reconcile,
            native_coding.NativeCodingHost.project_probe,
            native_coding.NativeCodingHost.sandbox_probe,
            native_coding.NativeCodingHost.prepare_job,
            native_coding.NativeCodingHost.finish_step,
            LinuxSandboxBroker.revalidate_capture, LinuxSandboxBroker.dispatch,
            LinuxSandboxBroker.verify, CoreIntentJournal._run,
            GitSourceSnapshot.capture.__func__, GitSourceSnapshot.verify,
            GitSourceSnapshot.verify_export)
        allowed = {id(fn.__code__): (fn.__code__, fn.__qualname__) for fn in functions}
        samples = {name: [] for _code, name in allowed.values()}
        stacks, bound = {}, [0]
        def observe(frame, event, _result):
            code = frame.f_code
            entry = allowed.get(id(code))
            if entry is None or entry[0] is not code or event not in ('call', 'return') or bound[0] >= 10000:
                return
            bound[0] += 1
            key = (threading.get_ident(), code)
            if event == 'call':
                stacks.setdefault(key, []).append(time.perf_counter_ns())
            elif stacks.get(key):
                elapsed = time.perf_counter_ns() - stacks[key].pop()
                samples[entry[1]].append(elapsed)
        old_current, old_threads = sys.getprofile(), threading.getprofile()
        sys.setprofile(observe)
        threading.setprofile(observe)
        try:
            yield
        finally:
            sys.setprofile(old_current)
            threading.setprofile(old_threads)
            value = {'schema': 'nz13.native-layer-timing-diagnostic.v1', 'diagnostic': True,
                'arguments_or_locals_recorded': False, 'event_limit': 10000,
                'event_limit_reached': bound[0] >= 10000,
                'layers': {name: {'count': len(values), 'total_ns': sum(values),
                    'max_ns': max(values, default=0), 'samples_ns': values}
                    for name, values in samples.items()}}
            raw = json.dumps(value, sort_keys=True).encode()
            path = self.root / 'layer-timings.json'
            self.context['safe'].write_new(path, raw)
            self.retained['layer_timings'] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}

    def close(self):
        result = self.host.close()
        self.retained['close'] = result
        return result

    def request(self, action, payload):
        from runtime.core_admission import Capability
        purpose = {'runtime_status': Capability.READ, 'read_status': Capability.READ, 'get_receipts': Capability.READ,
            'review_effect': Capability.READ, 'create_task': Capability.MANAGE, 'start': Capability.MANAGE,
            'stop': Capability.MANAGE, 'cancel': Capability.MANAGE, 'recover': Capability.MANAGE,
            'approve': Capability.OWNER_APPROVAL, 'deny': Capability.OWNER_APPROVAL,
            'apply': Capability.COMMIT, 'reconcile': Capability.COMMIT}[action]
        with self.host._native_coding.authority(purpose) as principal:
            return self.host.coding_tasks.request(principal, action, payload)

    def stop_assertions(self, case):
        import json
        import threading
        from dataclasses import replace
        from unittest.mock import patch

        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.persistence.ports import (
            _IN_TRANSACTION,
            TransactionContext,
        )
        from runtime.meta_hackathon.native_authority import (
            NativeAccessUse,
            NativeOwnedWorkHandle,
        )
        from runtime.mission.repair_validation import CoreRepositoryMaterializer

        tasks, owner = self.host.coding_tasks, self.host
        foundation = owner.foundation
        identities = ('owned-stop-a', 'owned-stop-b')
        entered = {name: threading.Event() for name in identities}
        release = {name: threading.Event() for name in identities}
        published, tokens = [], {}
        materialize = CoreRepositoryMaterializer.materialize
        transition = tasks._transition

        def observe_transition(*args, **kwargs):
            if len(args) > 3 and args[3] == 'RUNNING' and kwargs.get('admission') is True:
                task_id = args[1]
                case.assertFalse(_IN_TRANSACTION.get())
                active = tasks._active[task_id]
                handle = active['native_handle']
                case.assertIs(type(handle), NativeOwnedWorkHandle)
                case.assertIs(foundation.lifecycle._handles[task_id], handle)
                case.assertIs(handle.producer, tasks)
                case.assertEqual('CODING_WORKER', handle.role)
                case.assertIs(handle.cancel, active['cancel'])
                case.assertIs(handle.thread, active['thread'])
                case.assertIs(handle.done, active['done'])
                case.assertFalse(handle.thread.is_alive())
                published.append(task_id)
            return transition(*args, **kwargs)

        def gate(materializer, task, session, candidate):
            case.assertFalse(_IN_TRANSACTION.get(), 'WORKER_WAIT_INSIDE_SQL')
            tokens[task.task_id] = materializer.cancel
            entered[task.task_id].set()
            if not release[task.task_id].wait(30):
                raise ValueError('OWNED_STOP_FIXTURE_GATE_TIMEOUT')
            return materialize(materializer, task, session, candidate)

        try:
            with (patch.object(tasks, '_transition', new=observe_transition),
                  patch.object(CoreRepositoryMaterializer, 'materialize', new=gate)):
                for name in identities:
                    task = replace(self.task, task_id=name, run_id='run-' + name)
                    self.request('create_task', {'task': task.to_dict()})
                    self.request('start', {'task_id': name})
                    case.assertTrue(entered[name].wait(5), 'OWNED_WORKER_GATE_NOT_ENTERED')
                case.assertEqual(list(identities), published)
                snapshot = tasks.lifecycle_snapshot()
                case.assertEqual(identities, tuple(work.task_id for work in snapshot.work))
                case.assertIsNot(tokens[identities[0]], tokens[identities[1]])
                self.request('stop', {'task_id': identities[0]})
                case.assertTrue(tokens[identities[0]].cancelled)
                case.assertFalse(tokens[identities[1]].cancelled)
                release[identities[0]].set()
                case.assertTrue(tasks.wait(identities[0], 10))
                first = self.request('get_receipts', {'task_id': identities[0]})
                case.assertEqual('CANCELLED', first['state'], first)
                case.assertEqual((identities[1],), tuple(work.task_id for work in tasks.lifecycle_snapshot().work))
                case.assertEqual({}, owner._native_coding.jobs)
                closing = owner.close()
                case.assertFalse(closing['closed'])
                case.assertEqual('QUARANTINED', closing['status'])
                case.assertTrue(owner.core.configured)
                principal = owner.core.local_operator(Capability.READ)
                case.assertEqual(42, owner.runner.run(TransactionContext(principal, Capability.READ), lambda _tx: 42))
                case.assertTrue(tokens[identities[1]].cancelled)
                before_work = tasks.lifecycle_snapshot()
                before_handles = tuple(foundation.lifecycle._handles)
                before_jobs = dict(owner._native_coding.jobs)
                negative_captures = [
                    (purpose, use) for purpose in (Capability.COMMIT, Capability.MANAGE, Capability.OWNER_APPROVAL)
                    for use in (NativeAccessUse.READ, NativeAccessUse.CONTROL, NativeAccessUse.EXECUTION)]
                negative_captures.extend((Capability.READ, use) for use in (NativeAccessUse.CONTROL,
                                                                          NativeAccessUse.CAPACITY, NativeAccessUse.EXECUTION))
                negative_captures.extend((purpose, NativeAccessUse.SETTLEMENT)
                                         for purpose in (Capability.READ, Capability.COMMIT))
                for purpose, use in negative_captures:
                    returned = None
                    try:
                        with case.subTest(purpose=purpose.value, use=use.value), case.assertRaises(AdmissionError):
                            returned = foundation.access.capture(purpose, use=use)
                    finally:
                        if returned is not None:
                            returned.close()
                for action, payload in (
                        ('start', {'task_id': identities[0]}),
                        ('create_task', {'task': replace(self.task, task_id='quarantine-new',
                                                        run_id='quarantine-new-run').to_dict()})):
                    with case.subTest(action=action), case.assertRaises(AdmissionError):
                        self.request(action, payload)
                case.assertEqual(before_work, tasks.lifecycle_snapshot())
                case.assertEqual(before_handles, tuple(foundation.lifecycle._handles))
                case.assertEqual(before_jobs, owner._native_coding.jobs)
                case.assertEqual({}, foundation.access._originals)
                try:
                    retained = self.request('get_receipts', {'task_id': identities[1]})
                except AdmissionError:
                    case.fail('NATIVE_QUARANTINE_RECEIPTS_READ_UNAVAILABLE')
                case.assertIn(retained['state'], ('RUNNING', 'VALIDATING', 'REPAIRING', 'CANCELLED'))
        finally:
            for event in release.values():
                event.set()
            for name in identities:
                tasks.wait(name, 10)
        case.assertEqual((), tasks.lifecycle_snapshot().work)
        case.assertEqual({}, owner._native_coding.jobs)
        case.assertTrue(owner.close()['closed'])
        self.retained['stop'] = {'published_before_running': published, 'independent_tokens': True,
            'quarantined_while_producer_blocked': True, 'core_runner_retained_until_actual_return': True,
            'new_job_claims': 0, 'model_certification': 'NOT_CERTIFIED'}
        path = self.root / 'native-worker-stop-proof.json'
        raw = json.dumps(self.retained['stop'], sort_keys=True).encode()
        self.context['safe'].write_new(path, raw)

    def start_tls(self):
        if getattr(self, 'server', None) is not None:
            return
        import hashlib
        import json
        import ssl
        import threading
        from datetime import UTC, datetime, timedelta
        from unittest.mock import patch

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        from runtime.core_admission import AdmissionError
        from runtime.webapp import (
            WebRuntimeService,
            make_mobile_operator_server,
            make_server,
        )
        now = datetime.now(UTC)
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'fixture.example.org')])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=3))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('fixture.example.org')]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
        self.certificate = self.native_root / 'owned-certificate.pem'
        self.certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        self.certificate.chmod(0o600)
        private_key = self.native_root / 'owned-tls-key.pem'
        private_key.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        private_key.chmod(0o600)
        self.service = WebRuntimeService(runtime=self.host.runtime, meta_missions=self.host.missions,
            meta_owner=self.host, mobile_gateway=self.host.mobile, native_access=self.host.foundation.access)
        self.server = make_server('127.0.0.1', self.reserved_server.server_port, self.service,
            tls_certificate=self.certificate, tls_key=private_key, reserved_server=self.reserved_server)
        self.case.addCleanup(self.stop_listeners)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.host.tls_verified = False
        original_context = ssl.create_default_context
        self.client_context = original_context(cafile=str(self.certificate))
        self.client_context.minimum_version = self.client_context.maximum_version = ssl.TLSVersion.TLSv1_3
        # A private CA trust root is supplied only to this owned test call.
        # Hostname verification, TLS1.3 and original signed challenge stay active.
        with patch.object(ssl, 'create_default_context',
                          side_effect=lambda: original_context(cafile=str(self.certificate))):
            try:
                self.host.qualify_tls(self.server.server_port)
            except AdmissionError:
                self.case.fail('NATIVE_OWNED_TLS_ORIGIN_NETLOC_QUALIFICATION_FAILED')
        self.case.assertTrue(self.host.tls_verified)
        self.control = make_mobile_operator_server(self.host, service=self.service)
        self.control_thread = threading.Thread(target=self.control.serve_forever, daemon=True)
        self.control_thread.start()
        grant = self.operator({'op': 'console'})
        raw = ('delivery=' + grant['delivery']).encode('ascii')
        status, headers, _ = self.http('POST', '/devices', raw,
            headers=[('Host', self.origin.removeprefix('https://')),
                     ('Content-Type', 'application/x-www-form-urlencoded'), ('Content-Length', str(len(raw))),
                     ('Origin', self.origin), ('Sec-Fetch-Site', 'same-origin'),
                     ('Sec-Fetch-Mode', 'cors'), ('Sec-Fetch-Dest', 'empty')])
        self.case.assertEqual(200, status)
        cookie = next(value for name, value in headers if name.lower() == 'set-cookie')
        self.case.assertTrue(all(flag in cookie for flag in ('Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/')))
        self.cookie = cookie.split(';', 1)[0]
        status, _, body = self.http('GET', '/api/native-operator/session')
        self.case.assertEqual(200, status)
        session = json.loads(body)
        self.case.assertIs(True, session['coding_profile'])
        self.csrf = session['csrf_token']
        # The consumed SO_PEERCRED-derived launch grant cannot be redeemed again.
        duplicate, _, _ = self.http('POST', '/devices', raw,
            headers=[('Host', self.origin.removeprefix('https://')),
                     ('Content-Type', 'application/x-www-form-urlencoded'), ('Content-Length', str(len(raw))),
                     ('Origin', self.origin), ('Sec-Fetch-Site', 'same-origin'),
                     ('Sec-Fetch-Mode', 'cors'), ('Sec-Fetch-Dest', 'empty')])
        self.case.assertEqual(403, duplicate)
        self.retained['tls'] = {'scope': 'OWNED_CA_FIXTURE_NOT_SYSTEM_CA_CERTIFICATION',
            'certificate_sha256': hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest(),
            'version': 'TLSv1.3', 'origin': self.origin, 'port': self.server.server_port,
            'actual_signed_challenge': True, 'actual_unix_peer_uid': self.host.uid,
            'one_time_delivery_replay_denied': True}
        self.http_events = []

    def stop_listeners(self):
        for name in ('control', 'server'):
            server = getattr(self, name, None)
            if server is not None:
                server.shutdown()
                server.server_close()
                getattr(self, name + '_thread').join(3)
                setattr(self, name, None)

    def operator(self, value):
        from runtime.webapp import mobile_operator_client
        result = mobile_operator_client(self.native_root, value)
        if result.get('ok') is not True:
            raise ValueError(result.get('error', 'NATIVE_OPERATOR_DENIED'))
        return result['data']

    def http_headers(self, method, raw=b'', intent=None):
        values = [('Host', self.origin.removeprefix('https://'))]
        if getattr(self, 'cookie', None):
            values.append(('Cookie', self.cookie))
        if getattr(self, 'csrf', None):
            values.append(('X-AIOA-Session-Token', self.csrf))
        if method == 'POST':
            values.extend((('Origin', self.origin), ('Content-Type', 'application/json'),
                           ('Content-Length', str(len(raw)))))
        if intent is not None:
            values.append(('X-AIOA-Intent', intent))
        return values

    def http(self, method, path, raw=b'', *, headers=None, context=None):
        import http.client
        import socket
        from urllib.parse import urlsplit
        context = context or self.client_context
        peer = context.wrap_socket(socket.create_connection(('127.0.0.1', self.server.server_port), timeout=60),
                                   server_hostname=urlsplit(self.origin).hostname)
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=60)
        client.sock = peer
        try:
            client.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for name, value in headers if headers is not None else self.http_headers(method, raw):
                client.putheader(name, value)
            client.endheaders(raw if raw else None)
            response = client.getresponse()
            body = response.read(1048577)
            self.case.assertLessEqual(len(body), 1048576)
            if hasattr(self, 'http_events'):
                self.http_events.append((method, path, response.status))
            return response.status, response.getheaders(), body
        finally:
            client.close()
            peer.close()

    def tls_assertions(self, case):
        import json
        import socket
        import ssl
        from unittest.mock import patch

        from runtime.mobile_gateway import wire
        self.start_tls()
        status, _, raw = self.http('GET', '/coding')
        case.assertEqual(200, status)
        case.assertIn(b'coding-panel', raw)
        status, _, raw = self.http('GET', '/api/native-operator/readiness')
        case.assertEqual(200, status)
        signed = json.loads(raw)
        wire.verify(self.host.identity.spki, signed['signature'], signed['observation'])
        case.assertEqual('NOT_CERTIFIED', signed['observation']['model_certification'])
        body = b'{}'
        positive = self.http_headers('POST', body, 'coding-create_task-v1')
        def changed(name, value):
            return [(key, value if key.lower() == name.lower() else current) for key, current in positive]
        bad = [
            ('wrong-host', changed('Host', 'foreign.example.org')),
            ('duplicate-host', positive + [('Host', self.origin.removeprefix('https://'))]),
            ('wrong-origin', changed('Origin', 'https://foreign.example.org')),
            ('duplicate-origin', positive + [('Origin', self.origin)]),
            ('cross-site', positive + [('Sec-Fetch-Site', 'cross-site')]),
            ('missing-cookie', [(key, value) for key, value in positive if key != 'Cookie']),
            ('wrong-cookie', changed('Cookie', '__Host-aioa-console=foreign')),
            ('duplicate-cookie', positive + [('Cookie', self.cookie)]),
            ('missing-csrf', [(key, value) for key, value in positive if key != 'X-AIOA-Session-Token']),
            ('duplicate-csrf', positive + [('X-AIOA-Session-Token', self.csrf)]),
            ('wrong-intent', changed('X-AIOA-Intent', 'coding-start-v1')),
            ('duplicate-intent', positive + [('X-AIOA-Intent', 'coding-create_task-v1')]),
            ('duplicate-content-type', positive + [('Content-Type', 'application/json')]),
            ('duplicate-content-length', positive + [('Content-Length', '2')]),
            ('forwarded', positive + [('Forwarded', 'host=foreign.example.org')]),
            ('transfer-encoding', positive + [('Transfer-Encoding', 'chunked')]),
            ('expect', positive + [('Expect', '100-continue')]),
        ]
        with patch.object(self.host.coding_tasks, 'request', side_effect=AssertionError('TRANSPORT_REACHED_ACTION')):
            for name, headers in bad:
                with case.subTest(vector=name):
                    status, _, _ = self.http('POST', '/api/agent/coding/create_task', body, headers=headers)
                    case.assertEqual(403, status)
            for path in ('/api/session', '/api/agent/coding/runtime?extra=1',
                         '/api/agent/coding/tasks/../foreign', '/api/agent/coding/start/extra'):
                with case.subTest(path=path):
                    status, _, _ = self.http('GET', path)
                    case.assertEqual(403, status)
            for malformed in (b'{"task":{},"task":{}}', b'{"task":NaN}', b'not-json'):
                status, _, _ = self.http('POST', '/api/agent/coding/create_task', malformed,
                    headers=self.http_headers('POST', malformed, 'coding-create_task-v1'))
                case.assertEqual(403, status)
        old_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        old_context.load_verify_locations(cafile=str(self.certificate))
        old_context.minimum_version = old_context.maximum_version = ssl.TLSVersion.TLSv1_2
        with case.assertRaises((ssl.SSLError, OSError)):
            self.http('GET', '/api/native-operator/session', context=old_context)
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=5) as plain:
            plain.sendall(b'GET /api/session HTTP/1.1\r\nHost: fixture.example.org\r\n\r\n')
            try:
                value = plain.recv(4096)
            except OSError:
                value = b''
            case.assertNotIn(b'200 OK', value)
        case.assertEqual(0, self.host.model_calls())
        self.retained['tls_negative_vectors'] = [name for name, _headers in bad]

    def complete_single_candidate(self, case):
        from runtime.mobile_gateway.wire import verify

        case.assertTrue(self.single_good_candidate)
        case.assertEqual(1, len(self.host._offline_candidates))
        tasks, task = self.host.coding_tasks, self.task
        self.request('create_task', {'task': task.to_dict()})
        self.request('start', {'task_id': task.task_id})
        for _ in range(20):
            if tasks.wait(task.task_id, 30):
                break
        else:
            case.fail('OWNED_NATIVE_SINGLE_CANDIDATE_DID_NOT_DRAIN')
        view = self.request('get_receipts', {'task_id': task.task_id})
        case.assertEqual('REVIEW_REQUIRED', view['state'],
                         {'view': view, 'jobs': self.host._native_coding.job_observation()})
        case.assertEqual(['PASS'], [attempt['status'] for attempt in view['run_result']['attempts']])
        case.assertEqual(3, len(view['run_result']['attempts'][0]['steps']))
        jobs = self.host._native_coding.job_observation()
        case.assertEqual(4, len(jobs))
        case.assertTrue(all(row['state'] == 'DONE' and row['task_completion'] == 'COMPLETED'
                            and row['completion_proof'] for row in jobs), jobs)
        for signed in view['receipts']:
            verify(self.host.identity.spki, signed['signature'], signed['receipt'])
        case.assertEqual((), tasks.lifecycle_snapshot().work)
        case.assertEqual(0, self.host.model_calls())
        self.retained['review'] = view

    def _interrupt_git_admission(self, case, route, exact, boundary):
        import hashlib
        import json
        import re
        import threading
        from dataclasses import replace
        from unittest.mock import patch

        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION, RecordKind
        from runtime.meta_hackathon.native_authority import NativeOwnedWorkHandle
        from runtime.mission.coding_tasks import CoreCodingTasks
        from runtime.mission.git_publish import CoreRemoteGitRoute
        from runtime.mission.warrant import WarrantError
        from runtime.service_guard.service import CoreServiceGuard

        case.assertIn(boundary, ('BEFORE_APPLYING', 'BEFORE_START', 'LOST_APPLYING_ACK'))
        tasks, foundation, task = self.host.coding_tasks, self.host.foundation, self.task
        lifecycle = foundation.lifecycle
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        observed, physical, response = [], [], {}
        original_transition = CoreCodingTasks._transition
        original_start = CoreServiceGuard.dispatch_registered_remote_git
        original_physical = CoreRemoteGitRoute._dispatch_local_patch
        before_refs = self.target_repo.git('for-each-ref', '--format=%(refname):%(objectname)')

        def observe():
            case.assertFalse(_IN_TRANSACTION.get(), 'GIT_ADMISSION_FIXTURE_BOUNDARY_INSIDE_SQL')
            item = tasks._effect_ownership.get(task.task_id)
            handle = item.get('native_handle') if type(item) is dict else None
            owned = (type(handle) is NativeOwnedWorkHandle
                and lifecycle._handles.get(handle.task_id) is handle and handle.foundation is foundation
                and handle.producer is tasks and handle.role == 'CODING_HTTP_EFFECT'
                and handle.thread is threading.current_thread() and item['thread'] is handle.thread
                and item['done'] is handle.done and item['cancel'] is handle.cancel
                and tasks._effects.get(task.task_id) is handle.cancel and item['route'] is route)
            observed.append({'boundary': boundary, 'owned': owned, 'inside_sql': False})
            entered.set()
            if boundary != 'LOST_APPLYING_ACK':
                case.assertTrue(release.wait(60), 'GIT_ADMISSION_FIXTURE_GATE_TIMED_OUT')

        def transition(current, *args, **kwargs):
            selected = current is tasks and len(args) >= 4 and args[1] == task.task_id and args[3] == 'APPLYING'
            if selected and boundary == 'BEFORE_APPLYING':
                observe()
            value = original_transition(current, *args, **kwargs)
            if selected and boundary == 'LOST_APPLYING_ACK':
                # The original canonical commit happened. Only delivery of its
                # ACK is lost; there is no retry, rollback or clock replacement.
                observe()
                raise CommitOutcomeUnknown()
            return value

        def start(current, *args, **kwargs):
            if current is route and boundary == 'BEFORE_START':
                observe()
            return original_start(current, *args, **kwargs)

        def dispatch(current, *args, **kwargs):
            if current is route:
                physical.append('ORIGINAL_PHYSICAL_GIT_DISPATCH')
            return original_physical(current, *args, **kwargs)

        def apply():
            try:
                response['value'] = self.request('apply', exact)
            except (AdmissionError, WarrantError, CommitOutcomeUnknown) as exc:
                response['error'] = exc
            finally:
                returned.set()

        thread = threading.Thread(target=apply, name='owned-native-git-admission-negative')
        with (patch.object(CoreCodingTasks, '_transition', new=transition),
              patch.object(CoreServiceGuard, 'dispatch_registered_remote_git', new=staticmethod(start)),
              patch.object(CoreRemoteGitRoute, '_dispatch_local_patch', new=dispatch)):
            thread.start()
            try:
                case.assertTrue(entered.wait(30), 'GIT_ADMISSION_FIXTURE_NOT_ENTERED')
                stopped = None
                if boundary != 'LOST_APPLYING_ACK':
                    stopped = self.request('stop', {'task_id': task.task_id})
                    case.assertEqual('APPROVED' if boundary == 'BEFORE_APPLYING' else 'APPLYING', stopped['state'])
            finally:
                release.set()
                thread.join(60)
        case.assertFalse(thread.is_alive(), 'GIT_ADMISSION_OWNED_THREAD_NOT_RETURNED')
        case.assertTrue(returned.is_set())
        item = tasks._effect_ownership.get(task.task_id)
        case.assertIsNotNone(item)
        handle = item['native_handle']
        case.assertIs(lifecycle._handles.get(handle.task_id), handle)
        case.assertTrue(item['quarantined'] and handle.quarantined)
        case.assertTrue(item['returned'] and item['done'].is_set())
        phase_before_close = lifecycle.phase.value
        after = self.request('get_receipts', {'task_id': task.task_id})
        with route.target_guard():
            after_refs = self.target_repo.git('for-each-ref', '--format=%(refname):%(objectname)')
        def canonical(tx):
            with patch.object(self.host, 'source_probe', side_effect=AssertionError('SOURCE_INSIDE_SQL')):
                _, intent = route.journal._load(tx, item['warrant'])
                governor = foundation.governor._load(tx)
                witness = tx.get(RecordKind.APPROVAL,
                                 foundation.ledger._key(item['warrant']))
                return json.loads(canonical_json_bytes((intent, governor, witness.payload)))
        with self.host._native_coding.authority(Capability.READ) as principal:
            intent, governor, witness = tasks._run(principal, Capability.READ, canonical)
        # Actual mutation attempt, with a valid independent task, tests the
        # lifecycle fence before close rather than relying on a phase mock.
        later = replace(task, task_id=task.task_id + '-after-unknown', run_id=task.run_id + '-after-unknown')
        try:
            new_work = self.request('create_task', {'task': later.to_dict()})
        except (AdmissionError, WarrantError):
            new_work = None
        with case.assertRaises((AdmissionError, WarrantError)):
            self.request('apply', exact)
        close_report = self.host.close()
        error = response.get('error')
        public_code = str(error) if error is not None and re.fullmatch('[A-Z][A-Z0-9_]{1,95}', str(error)) else None
        proof = {'schema': 'nz13.native-git-admission-uncertainty.v1', 'boundary': boundary,
            'fixture_os_admission': 'FIXTURE_OS_ADMISSION', 'model_certification': 'NOT_CERTIFIED',
            'candidate_mode': 'ONE_GOOD_ADVISORY_FOUR_REAL_SANDBOX_EFFECTS',
            'observed': observed, 'stop': stopped, 'canonical': after, 'intent': intent,
            'physical_dispatches': physical, 'target_refs_unchanged': before_refs == after_refs,
            'caller_ack': {'returned': 'value' in response, 'error_type': type(error).__name__ if error else None,
                           'public_code': public_code},
            'retained': {'native_handle_same': lifecycle._handles.get(handle.task_id) is handle,
                'entry_same': tasks._effect_ownership.get(task.task_id) is item,
                'quarantined': item['quarantined'] and handle.quarantined,
                'thread_alive': thread.is_alive(), 'done': item['done'].is_set(), 'returned': item['returned']},
            'phase_before_close': phase_before_close, 'new_work_admitted': new_work is not None,
            'new_work_state': new_work['state'] if new_work else None, 'close': close_report,
            'core_still_owned': not self.host._closed, 'governor_epoch': governor['epoch'],
            'risk_reservation_present': item['warrant'].risk_reservation_id in governor['reservations'],
            'witness_session': witness['session_id']}
        path = self.root / 'native-git-admission-uncertainty-proof.json'
        raw = json.dumps(proof, sort_keys=True).encode()
        self.context['safe'].write_new(path, raw)
        self.retained['git_admission'] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
        case.assertTrue(observed and all(row['owned'] for row in observed))
        case.assertEqual([], physical)
        case.assertIsNone(intent)
        case.assertEqual(before_refs, after_refs)
        case.assertEqual('APPROVED' if boundary == 'BEFORE_APPLYING' else 'APPLYING', after['state'])
        case.assertIsInstance(error, CommitOutcomeUnknown if boundary == 'LOST_APPLYING_ACK' else WarrantError)
        case.assertNotIn('value', response)
        case.assertEqual({'status': 'QUARANTINED', 'closed': False}, close_report)
        case.assertFalse(self.host._closed)
        case.assertEqual('QUARANTINED', phase_before_close, 'NATIVE_QUARANTINED_EFFECT_DID_NOT_FENCE_ADMISSION')
        case.assertIsNone(new_work, 'NATIVE_QUARANTINED_GIT_EFFECT_ADMITTED_NEW_WORK')
        case.assertEqual(0, self.host.model_calls())

    def _apply_git_with_owned_stop(self, case, route, exact):
        import hashlib
        import json
        import threading
        from unittest.mock import patch

        from runtime.core_admission import AdmissionError
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
        from runtime.meta_hackathon.native_authority import (
            NativeOwnedWorkHandle,
            NativePhase,
        )
        from runtime.mission.coding_tasks import CoreCodingTasks
        from runtime.mission.git_publish import CoreRemoteGitRoute

        tasks, foundation = self.host.coding_tasks, self.host.foundation
        lifecycle = foundation.lifecycle
        task_id = self.task.task_id
        released, complete, returned = threading.Event(), threading.Event(), threading.Event()
        observations, handles, dispatches, failures = [], [], [], []
        response = {}
        original_transition = CoreCodingTasks._transition
        original_dispatch = CoreRemoteGitRoute._dispatch_local_patch
        original_complete = CoreRemoteGitRoute._complete_local_patch

        def lock_is_free():
            acquired = []
            def probe():
                held = tasks._active_lock.acquire(blocking=False)
                acquired.append(held)
                if held:
                    tasks._active_lock.release()
            thread = threading.Thread(target=probe, name='owned-git-lock-observer')
            thread.start()
            thread.join(1)
            case.assertFalse(thread.is_alive(), 'GIT_FIXTURE_LOCK_OBSERVER_NOT_RETURNED')
            return acquired == [True]

        def observe(label):
            case.assertFalse(_IN_TRANSACTION.get(), 'GIT_OWNERSHIP_OBSERVER_INSIDE_SQL')
            with tasks._active_lock:
                item = tasks._effect_ownership.get(task_id)
                token = tasks._effects.get(task_id)
            handle = item.get('native_handle') if type(item) is dict else None
            with lifecycle.lock:
                owned = (type(handle) is NativeOwnedWorkHandle
                    and lifecycle._handles.get(handle.task_id) is handle
                    and handle.foundation is foundation and handle.producer is tasks
                    and handle.role == 'CODING_HTTP_EFFECT' and handle.synchronous and handle.started
                    and handle.thread is threading.current_thread() and handle.cancel is token
                    and item['thread'] is handle.thread and item['cancel'] is handle.cancel
                    and item['done'] is handle.done and not handle.done.is_set()
                    and item.get('route') is route and not item.get('quarantined')
                    and not handle.quarantined)
            if type(handle) is NativeOwnedWorkHandle:
                handles.append(handle)
            observations.append({'boundary': label, 'owned': owned,
                'same_handle': not handles or all(value is handles[0] for value in handles),
                'controller_lock_free': lock_is_free(), 'phase': lifecycle.phase.value})

        def transition(controller, *args, **kwargs):
            if controller is tasks and len(args) >= 4 and args[1] == task_id:
                if args[3] == 'APPLYING':
                    observe('BEFORE_APPLYING')
                elif args[3] == 'VERIFIED':
                    observe('BEFORE_VERIFIED')
            return original_transition(controller, *args, **kwargs)

        def dispatch(current, *args, **kwargs):
            if current is route:
                dispatches.append('ORIGINAL_LOCAL_GIT_DISPATCH')
                observe('BEFORE_PHYSICAL_DISPATCH')
            return original_dispatch(current, *args, **kwargs)

        def settle(current, *args, **kwargs):
            if current is not route:
                return original_complete(current, *args, **kwargs)
            observe('AFTER_REF_RELEASE_BEFORE_READBACK')
            released.set()
            case.assertTrue(complete.wait(90), 'GIT_FIXTURE_SETTLEMENT_GATE_TIMED_OUT')
            observe('AFTER_STOP_BEFORE_SETTLEMENT')
            try:
                value = original_complete(current, *args, **kwargs)
            except BaseException as exc:
                failures.append({'layer': 'original_complete_local_patch', 'type': type(exc).__name__})
                raise
            observe('AFTER_CANONICAL_SETTLEMENT')
            return value

        def apply():
            try:
                response['value'] = self.request('apply', exact)
            except (AdmissionError, ValueError) as exc:
                response['error'] = exc
            finally:
                returned.set()

        thread = threading.Thread(target=apply, name='owned-native-git-effect')
        with (patch.object(CoreCodingTasks, '_transition', new=transition),
              patch.object(CoreRemoteGitRoute, '_dispatch_local_patch', new=dispatch),
              patch.object(CoreRemoteGitRoute, '_complete_local_patch', new=settle)):
            thread.start()
            try:
                case.assertTrue(released.wait(120), 'GIT_FIXTURE_NO_PHYSICAL_REF_RELEASE')
                physical_commit = self.target_repo.git('rev-parse', route.plan.ref).decode().strip()
                case.assertEqual(route.plan.commit_sha, physical_commit)
                stopped = self.request('stop', {'task_id': task_id})
                case.assertEqual('APPLYING', stopped['state'])
                close_report = self.host.close()
                case.assertEqual({'status': 'QUARANTINED', 'closed': False}, close_report)
                case.assertIs(lifecycle.phase, NativePhase.QUARANTINED)
                case.assertFalse(self.host._closed)
                before = self.request('get_receipts', {'task_id': task_id})
                case.assertEqual('APPLYING', before['state'])
                with case.assertRaises(AdmissionError):
                    self.request('apply', exact)
                case.assertEqual(['ORIGINAL_LOCAL_GIT_DISPATCH'], dispatches)
            finally:
                complete.set()
                thread.join(120)
        case.assertFalse(thread.is_alive(), 'GIT_OWNED_EFFECT_NOT_RETURNED')
        case.assertTrue(returned.is_set())
        after = self.request('get_receipts', {'task_id': task_id})
        error = response.get('error')
        proof = {'schema': 'nz13.native-git-owned-stop-boundaries.v1',
            'fixture_os_admission': 'FIXTURE_OS_ADMISSION', 'model_certification': 'NOT_CERTIFIED',
            'observations': observations, 'dispatches': dispatches, 'stop': stopped,
            'close': close_report, 'before_settlement': before, 'after_settlement': after,
            'original_settlement_failures': failures,
            'caller_ack': {'returned': 'value' in response, 'error_type': type(error).__name__ if error else None},
            'physical_commit': physical_commit, 'intended_commit': route.plan.commit_sha,
            'core_still_owned': not self.host._closed,
            'remaining_effects': len(tasks._effect_ownership), 'remaining_native_handles': len(lifecycle._handles)}
        path = self.root / 'native-git-ownership-stop-proof.json'
        raw = json.dumps(proof, sort_keys=True).encode()
        self.context['safe'].write_new(path, raw)
        self.retained['git_owned_stop'] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
        case.assertTrue(observations and all(item['owned'] for item in observations),
                        'NATIVE_GIT_OWNED_HANDLE_MISSING_BEFORE_APPLYING_OR_SETTLEMENT')
        case.assertTrue(all(item['same_handle'] for item in observations), 'NATIVE_GIT_OWNED_HANDLE_REPLACED')
        case.assertTrue(all(item['controller_lock_free'] for item in observations), 'NATIVE_GIT_GLOBAL_LOCK_OVER_IO')
        case.assertEqual(['BEFORE_APPLYING', 'BEFORE_PHYSICAL_DISPATCH', 'AFTER_REF_RELEASE_BEFORE_READBACK',
                          'AFTER_STOP_BEFORE_SETTLEMENT', 'AFTER_CANONICAL_SETTLEMENT', 'BEFORE_VERIFIED'],
                         [item['boundary'] for item in observations])
        case.assertEqual([], failures)
        case.assertEqual('VERIFIED', after['state'], 'NATIVE_GIT_RELEASED_EFFECT_NOT_CANONICALLY_SETTLED')
        # Closing Native invalidates the outer caller capture. Canonical readback,
        # rather than a successful client ACK, is the proof of this exact effect.
        case.assertIsInstance(error, AdmissionError)
        case.assertNotIn('value', response)
        case.assertEqual({}, tasks._effects)
        case.assertEqual({}, tasks._effect_ownership)
        case.assertEqual({}, lifecycle._handles)
        with case.assertRaises(AdmissionError):
            self.request('apply', exact)
        case.assertEqual(['ORIGINAL_LOCAL_GIT_DISPATCH'], dispatches)
        return after

    def _reconcile_lost_git_ack(self, case, route, exact, *, historical_epoch=False):
        import hashlib
        import json
        import threading
        from unittest.mock import patch

        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import (
            _IN_TRANSACTION,
            CommitOutcomeUnknown,
            RecordKind,
        )
        from runtime.meta_hackathon.native_authority import (
            NativeOwnedWorkHandle,
            NativePhase,
        )
        from runtime.mission import git_publish
        from runtime.mission.coding_tasks import CoreCodingTasks
        from runtime.mission.git_publish import CoreRemoteGitRoute

        tasks, foundation = self.host.coding_tasks, self.host.foundation
        lifecycle, task_id = foundation.lifecycle, self.task.task_id
        original_dispatch = CoreRemoteGitRoute._dispatch_local_patch
        original_complete = CoreRemoteGitRoute._complete_local_patch
        original_start_ack = CoreCodingTasks._native_git_start_ack
        original_git = git_publish._bounded_git
        binding = tasks._effect(task_id, exact['capsule_digest'])
        case.assertIs(binding[0], route)
        warrant = binding[1]
        counts = {'dispatch': 0, 'start_ack': 0, 'ref_write': 0, 'readback': 0, 'fault': 0}
        response, observations = {}, []
        returned = threading.Event()

        if historical_epoch:
            from runtime.meta_hackathon.native_authority import NativeAccessUse
            from runtime.mission.governor import GovernorError

            epoch_data, epoch_errors, epoch_git = {'snapshots': {}}, [], []
            old_warrant_bytes = canonical_json_bytes(warrant.to_dict())
            ledger_key = foundation.ledger._key(warrant)
            warrant_row_keys = (RecordKind.OPERATION.value + ':' + ledger_key,
                                RecordKind.APPROVAL.value + ':' + ledger_key)

            def epoch_work():
                managed = self.host._native_coding
                return {'model_calls': self.host.model_calls(), 'materializations': len(managed.materializations),
                        'jobs': len(managed.jobs), 'runs': len(managed.runs), 'effects': len(managed.effects)}

            def advance_existing_epoch():
                try:
                    case.assertFalse(_IN_TRANSACTION.get())
                    case.assertIs(lifecycle.phase, NativePhase.ACTIVE)
                    case.assertEqual((1, 1, 1), (counts['dispatch'], counts['start_ack'], counts['ref_write']))
                    epoch_data['before_work'] = epoch_work()
                    before_epoch = self.legacy_capacity_snapshot()
                    epoch_data['snapshots']['before'] = self.legacy_capacity_save(
                        'native-historical-epoch-before.json', before_epoch)
                    epoch_data['old_warrant'] = json.loads(old_warrant_bytes)
                    epoch_data['old_warrant_digest'] = warrant.digest()
                    epoch_data['old_lease_epoch'] = warrant.lease_epoch
                    case.assertEqual(warrant.lease_epoch, before_epoch['state']['epoch'])
                    case.assertNotIn('HALF_OPEN', [value['state'] for value in before_epoch['state']['circuits'].values()])
                    control = foundation.access.capture(Capability.MANAGE, use=NativeAccessUse.CONTROL)
                    try:
                        foundation.access.require_capture(control, Capability.MANAGE)
                        case.assertIs(control.core, self.host.core)
                        case.assertIs(control.runner, self.host.runner)
                        epoch_data['new_epoch'] = foundation.governor.start_epoch(control.principal)
                        foundation.access.require_capture(control, Capability.MANAGE)
                    finally:
                        control.close()
                    epoch_data['transition_completed'] = True
                    after_epoch = self.legacy_capacity_snapshot()
                    epoch_data['snapshots']['after'] = self.legacy_capacity_save(
                        'native-historical-epoch-after.json', after_epoch)
                    epoch_data['after_work'] = epoch_work()
                except BaseException as error:
                    code = str(error)
                    epoch_data['transition_error'] = {'type': type(error).__module__ + '.' + type(error).__qualname__,
                        'public_code': code if len(code) <= 96 and code.replace('_', '').isalnum() and code.upper() == code else None}
                    epoch_errors.append(error)
                    raise
                finally:
                    self.retained['git_historical_epoch_transition'] = self.legacy_capacity_save(
                        'native-historical-epoch-transition.json', epoch_data)

        def dispatch(current, *args, **kwargs):
            if current is route:
                case.assertFalse(_IN_TRANSACTION.get())
                counts['dispatch'] += 1
            return original_dispatch(current, *args, **kwargs)

        def start_ack(current, *args, **kwargs):
            value = original_start_ack(current, *args, **kwargs)
            if current is tasks and args[0] is route:
                case.assertFalse(_IN_TRANSACTION.get())
                counts['start_ack'] += 1
            return value

        def bounded_git(repository, arguments, **kwargs):
            if historical_epoch and epoch_data.get('transition_completed'):
                epoch_git.append({'repository': str(repository), 'arguments': list(arguments),
                                  'input_data': kwargs.get('data') is not None})
            value = original_git(repository, arguments, **kwargs)
            if repository == route.target_repository and arguments[0] == 'update-ref':
                case.assertFalse(_IN_TRANSACTION.get())
                case.assertEqual(('update-ref', route.plan.ref, route.plan.commit_sha, '0' * 40), arguments)
                counts['ref_write'] += 1
            return value

        def complete(current, *args, **kwargs):
            if current is route:
                case.assertFalse(_IN_TRANSACTION.get())
                if not kwargs['historical'] and counts['fault'] == 0:
                    case.assertEqual((1, 1, 1), (counts['dispatch'], counts['start_ack'], counts['ref_write']))
                    if historical_epoch:
                        advance_existing_epoch()
                    counts['fault'] += 1
                    observations.append('POSTWRITE_ACK_LOSS_BEFORE_ORIGINAL_READBACK')
                    raise CommitOutcomeUnknown()
                counts['readback'] += 1
            return original_complete(current, *args, **kwargs)

        def apply():
            try:
                response['value'] = self.request('apply', exact)
            except (AdmissionError, ValueError) as error:
                response['error_type'] = type(error).__name__
            finally:
                returned.set()

        def canonical(tx):
            _, intent = route.journal._load(tx, warrant)
            step = tx.get(RecordKind.OPERATION, 'github-step-' + route.plan.operation_id + '-local_patch')
            result = tx.get(RecordKind.OPERATION, 'github-result-' + route.plan.operation_id)
            return json.loads(canonical_json_bytes((intent, None if step is None else step.payload,
                                                   None if result is None else result.payload)))

        thread = threading.Thread(target=apply, name='owned-native-git-lost-postwrite-ack')
        with (patch.object(CoreRemoteGitRoute, '_dispatch_local_patch', new=dispatch),
              patch.object(CoreRemoteGitRoute, '_complete_local_patch', new=complete),
              patch.object(CoreCodingTasks, '_native_git_start_ack', new=start_ack),
              patch.object(git_publish, '_bounded_git', new=bounded_git)):
            thread.start()
            thread.join(120)
            case.assertFalse(thread.is_alive(), 'GIT_LOST_ACK_EFFECT_NOT_RETURNED')
            case.assertTrue(returned.is_set())
            if historical_epoch and epoch_errors:
                raise epoch_errors[0]
            before = self.request('get_receipts', {'task_id': task_id})
            case.assertEqual('UNKNOWN', before['state'])
            case.assertEqual(route.plan.commit_sha,
                             self.target_repo.git('rev-parse', route.plan.ref).decode().strip())
            with tasks._active_lock:
                retained = tasks._effect_ownership.get(task_id)
                handle = retained['native_handle'] if type(retained) is dict else None
            case.assertIs(type(handle), NativeOwnedWorkHandle)
            case.assertIs(lifecycle._handles.get(handle.task_id), handle)
            case.assertTrue(retained['quarantined'] and handle.quarantined)
            case.assertTrue(retained['returned'] and handle.done.is_set())
            case.assertIs(handle.thread, thread)
            case.assertIs(lifecycle.phase, NativePhase.QUARANTINED)
            with self.host._native_coding.authority(Capability.READ) as principal:
                initial_intent, step, initial_result = route._run(principal, Capability.READ, canonical)
            case.assertIsNotNone(initial_intent)
            case.assertIsNone(initial_intent['resolution'])
            case.assertIsNotNone(step)
            case.assertIsNone(initial_result)
            close_report = self.host.close()
            case.assertEqual({'status': 'QUARANTINED', 'closed': False}, close_report)
            case.assertFalse(self.host._closed)
            if historical_epoch:
                denied_before = self.legacy_capacity_snapshot()
                epoch_data['snapshots']['denied_before'] = self.legacy_capacity_save(
                    'native-historical-epoch-denied-before.json', denied_before)
            with case.assertRaises(AdmissionError):
                self.host.runtime.coding_request('apply', exact, principal=None)
            if historical_epoch:
                denied_after = self.legacy_capacity_snapshot()
                epoch_data['snapshots']['denied_after'] = self.legacy_capacity_save(
                    'native-historical-epoch-denied-after.json', denied_after)
            error_type, reconciled = None, None
            try:
                reconciled = self.host.runtime.coding_request('reconcile', {'task_id': task_id}, principal=None)
            except (AdmissionError, ValueError) as error:
                error_type = type(error).__name__
                if historical_epoch:
                    epoch_errors.append(error)
                    epoch_data['reconcile_error'] = {'type': type(error).__module__ + '.' + type(error).__qualname__,
                                                     'public_code': str(error)}
            after = self.request('get_receipts', {'task_id': task_id})
            with self.host._native_coding.authority(Capability.READ) as principal:
                final_intent, _, final_result = route._run(principal, Capability.READ, canonical)
            proof = {'schema': 'nz13.native-git-owned-lost-postwrite-ack.v1',
                'fixture_os_admission': 'FIXTURE_OS_ADMISSION', 'model_certification': 'NOT_CERTIFIED',
                'fault_boundary': observations, 'counts': dict(counts), 'caller_ack': response,
                'before': before, 'after': after, 'close_before_reconcile': close_report,
                'reconcile_error_type': error_type, 'reconcile_response': reconciled,
                'initial_intent': initial_intent, 'final_intent': final_intent,
                'initial_result': initial_result, 'final_result': final_result,
                'step': step, 'warrant_digest': retained['warrant'].digest(),
                'physical_commit': route.plan.commit_sha,
                'retained_original_handle': lifecycle._handles.get(handle.task_id) is handle,
                'remaining_effects': len(tasks._effect_ownership), 'remaining_handles': len(lifecycle._handles),
                'core_still_owned': not self.host._closed}
            if historical_epoch:
                final_epoch = self.legacy_capacity_snapshot()
                epoch_data['snapshots']['final'] = self.legacy_capacity_save(
                    'native-historical-epoch-final.json', final_epoch)
                epoch_data['final_work'] = epoch_work()
                epoch_data['after_epoch_git'] = epoch_git
                epoch_data['same_warrant_object'] = retained['warrant'] is warrant is binding[1]
                epoch_data['final_warrant'] = warrant.to_dict()
                epoch_data['final_warrant_digest'] = warrant.digest()
                epoch_data['phase_after'] = lifecycle.phase.value
                epoch_data['canonical_intent'] = final_intent
                epoch_data['counts'] = dict(counts)
                epoch_data['qualification'] = False
                self.retained['git_historical_epoch'] = self.legacy_capacity_save(
                    'native-historical-epoch-proof.json', epoch_data)
                proof['historical_epoch'] = self.retained['git_historical_epoch']
            path = self.root / 'native-git-lost-postwrite-ack-proof.json'
            raw = json.dumps(proof, sort_keys=True).encode()
            self.context['safe'].write_new(path, raw)
            self.retained['git_lost_postwrite_ack'] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
            if historical_epoch:
                if epoch_errors:
                    error = epoch_errors[0]
                    if type(error) is GovernorError and str(error) == 'STALE_EPOCH':
                        case.fail('NATIVE_HISTORICAL_WARRANT_CURRENT_EPOCH_SETTLEMENT_DENIED')
                    raise error
                before_raw = self.context['safe'].read(self.root / 'native-historical-epoch-before.json', maximum=4 * 1024 * 1024)
                after_raw = self.context['safe'].read(self.root / 'native-historical-epoch-after.json', maximum=4 * 1024 * 1024)
                case.assertEqual(epoch_data['snapshots']['before']['sha256'], hashlib.sha256(before_raw).hexdigest())
                case.assertEqual(epoch_data['snapshots']['after']['sha256'], hashlib.sha256(after_raw).hexdigest())
                before_epoch, after_epoch = json.loads(before_raw), json.loads(after_raw)
                expected_state = json.loads(canonical_json_bytes(before_epoch['state']))
                expected_state.update(epoch=before_epoch['state']['epoch'] + 1,
                                      version=before_epoch['state']['version'] + 1,
                                      last_now=after_epoch['state']['last_now'])
                case.assertEqual(expected_state, after_epoch['state'])
                case.assertEqual(epoch_data['new_epoch'], after_epoch['state']['epoch'])
                case.assertLess(warrant.lease_epoch, after_epoch['state']['epoch'])
                case.assertEqual(after_epoch['state']['epoch'], final_epoch['state']['epoch'])
                case.assertEqual(before_epoch['exposure'], after_epoch['exposure'])
                case.assertEqual(before_epoch['exposure'], final_epoch['exposure'])
                case.assertEqual(epoch_data['before_work'], epoch_data['after_work'])
                case.assertEqual(epoch_data['after_work'], epoch_data['final_work'])
                case.assertEqual(0, epoch_data['final_work']['model_calls'])
                for key, value in before_epoch['rows'].items():
                    case.assertEqual(value, after_epoch['rows'][key])
                key = foundation.governor._key(after_epoch['state']['version'])
                case.assertEqual({RecordKind.OPERATION.value + ':' + key,
                                  RecordKind.AUDIT.value + ':governor-' + key,
                                  RecordKind.OUTBOX.value + ':governor-outbox-' + key},
                                 set(after_epoch['rows']) - set(before_epoch['rows']))
                for key in warrant_row_keys:
                    case.assertEqual(before_epoch['rows'][key], after_epoch['rows'][key])
                    case.assertEqual(before_epoch['rows'][key], final_epoch['rows'][key])
                case.assertTrue(epoch_data['same_warrant_object'])
                case.assertEqual(old_warrant_bytes, canonical_json_bytes(warrant.to_dict()))
                case.assertEqual(epoch_data['old_warrant_digest'], warrant.digest())
                for key, value in before_epoch['state']['reservations'].items():
                    if key != binding[2].request_id:
                        case.assertEqual(value, final_epoch['state']['reservations'][key])
                for key in ('state', 'rows', 'exposure', 'policy_digest', 'identity_spki_sha256', 'phase'):
                    case.assertEqual(denied_before[key], denied_after[key])
                case.assertIs(lifecycle.phase, NativePhase.QUARANTINED)
                case.assertTrue(epoch_git)
                case.assertFalse(any(value['input_data'] or value['arguments'][0] in ('update-ref', 'hash-object')
                                     for value in epoch_git))
            case.assertIsNone(error_type, 'NATIVE_OWNED_UNKNOWN_CANNOT_RECONCILE_WITHOUT_RESEND')
            case.assertEqual('VERIFIED', reconciled['state'])
            case.assertEqual('VERIFIED', after['state'])
            case.assertEqual({'dispatch': 1, 'start_ack': 1, 'ref_write': 1, 'readback': 1, 'fault': 1}, counts)
            case.assertEqual('Applied', final_intent['outcome']['contract_type'])
            case.assertIsNotNone(final_intent['resolution'])
            case.assertIsNotNone(final_result)
            case.assertEqual({}, tasks._effect_ownership)
            case.assertEqual({}, tasks._effects)
            case.assertEqual({}, lifecycle._handles)
            return reconciled

    def _git_reconciliation_safety(self, case, route, exact):
        import hashlib
        import json
        import re
        import threading
        from copy import copy
        from dataclasses import asdict, replace
        from unittest.mock import patch

        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import (
            _IN_TRANSACTION,
            CommitOutcomeUnknown,
            RecordKind,
        )
        from runtime.meta_hackathon.native_authority import NativePhase
        from runtime.mission import coding_tasks, git_publish
        from runtime.mission.coding_tasks import CoreCodingTasks
        from runtime.mission.git_publish import CoreRemoteGitRoute
        from runtime.mission.warrant import WarrantError
        from runtime.providers.exact import CancellationToken

        tasks, foundation = self.host.coding_tasks, self.host.foundation
        lifecycle, task_id = foundation.lifecycle, self.task.task_id
        managed, original_core, original_runner = self.host._native_coding, self.host.core, self.host.runner
        binding = tasks._effect(task_id, exact['capsule_digest'])
        case.assertIs(binding[0], route)
        warrant, reservation = binding[1:]
        originals = (CoreRemoteGitRoute._dispatch_local_patch, CoreRemoteGitRoute._complete_local_patch,
                     CoreCodingTasks._native_git_start_ack, git_publish._bounded_git, CoreCodingTasks._transition)
        counts = {'dispatch': 0, 'start_ack': 0, 'ref_write': 0, 'postwrite_fault': 0,
                  'publication_fault': 0, 'verified_ack_fault': 0, 'readback': 0}
        observations, proofs = [], []
        baseline, child_response = {}, {}
        main_thread = threading.current_thread()
        gate_entered, release_readback = threading.Event(), threading.Event()
        child_thread = None
        gate_enabled, lose_verified_ack = False, False
        state = {'scope': 'REAL_LINUX_GIT_FIXTURE_TLS_FLAG_ONLY',
                 'phase': 'BEFORE_START', 'counts': counts, 'observations': observations}

        def code(error):
            value = str(error)
            return value if re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}', value) else 'BOUNDED_PUBLIC_ERROR'

        def invoke(label):
            try:
                value = self.host.runtime.coding_request('reconcile', {'task_id': task_id}, principal=None)
                outcome = {'returned': value['state'], 'error_type': None, 'code': None}
            except (AdmissionError, WarrantError, CommitOutcomeUnknown) as error:
                value = None
                outcome = {'returned': None, 'error_type': type(error).__name__, 'code': code(error)}
            observations.append({'boundary': label, **outcome})
            return value, outcome

        def save_proof(stage):
            snapshot = tasks.lifecycle_snapshot()
            payload = {'schema': 'nz13.native-git-reconciliation-safety.v1',
                       'fixture_os_admission': 'FIXTURE_OS_ADMISSION', 'model_certification': 'NOT_CERTIFIED',
                       'stage': stage, 'task_id': task_id, 'operation_digest': exact['operation_digest'],
                       'state': state, 'work': asdict(snapshot),
                       'remaining_handles': len(lifecycle._handles),
                       'remaining_effects': len(tasks._effect_ownership),
                       'same_core': self.host.core is original_core, 'same_runner': self.host.runner is original_runner,
                       'native_closed': self.host._closed}
            raw = json.dumps(payload, sort_keys=True).encode()
            path = self.root / ('native-git-reconciliation-safety-' + stage + '.json')
            self.context['safe'].write_new(path, raw)
            proofs.append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()})
            self.retained['git_reconciliation_safety'] = list(proofs)

        def canonical(tx):
            _, intent = route.journal._load(tx, warrant)
            step = tx.get(RecordKind.OPERATION, 'github-step-' + route.plan.operation_id + '-local_patch')
            result = tx.get(RecordKind.OPERATION, 'github-result-' + route.plan.operation_id)
            return json.loads(canonical_json_bytes((intent, None if step is None else step.payload,
                                                   None if result is None else result.payload)))

        def canonical_read():
            with managed.authority(Capability.READ) as principal:
                return route._run(principal, Capability.READ, canonical)

        def unchanged():
            case.assertEqual(baseline['counts'], counts)
            case.assertIs(tasks._effect_ownership[task_id], baseline['item'])
            case.assertIs(tasks._effects[task_id], baseline['cancel'])
            case.assertEqual(set(baseline['handles']), set(lifecycle._handles))
            for name, handle in baseline['handles'].items():
                case.assertIs(lifecycle._handles[name], handle)

        def deny_parent(label, target, field, replacement):
            value = target[field] if type(target) is dict else getattr(target, field)
            try:
                if type(target) is dict:
                    target[field] = replacement
                else:
                    setattr(target, field, replacement)
                _, outcome = invoke(label)
                case.assertEqual('WarrantError', outcome['error_type'], outcome)
                case.assertEqual('CODING_NATIVE_RECONCILIATION_PARENT', outcome['code'], outcome)
            finally:
                if type(target) is dict:
                    target[field] = value
                else:
                    setattr(target, field, value)
            unchanged()

        def dispatch(current, *args, **kwargs):
            if current is route:
                case.assertFalse(_IN_TRANSACTION.get())
                counts['dispatch'] += 1
            return originals[0](current, *args, **kwargs)

        def start_ack(current, *args, **kwargs):
            value = originals[2](current, *args, **kwargs)
            if current is tasks and args[0] is route:
                case.assertFalse(_IN_TRANSACTION.get())
                counts['start_ack'] += 1
            return value

        def bounded_git(repository, arguments, **kwargs):
            value = originals[3](repository, arguments, **kwargs)
            if repository == route.target_repository and arguments[0] == 'update-ref':
                case.assertEqual(('update-ref', route.plan.ref, route.plan.commit_sha, '0' * 40), arguments)
                counts['ref_write'] += 1
            return value

        def transition(controller, *args, **kwargs):
            value = originals[4](controller, *args, **kwargs)
            if controller is tasks and len(args) >= 4 and args[1] == task_id and args[3] == 'VERIFIED' and lose_verified_ack:
                case.assertFalse(_IN_TRANSACTION.get())
                case.assertEqual('VERIFIED', value['state'])
                counts['verified_ack_fault'] += 1
                observations.append({'boundary': 'ORIGINAL_VERIFIED_COMMITTED_ACK_LOST', 'state': value['state']})
                raise CommitOutcomeUnknown()
            return value

        def complete(current, *args, **kwargs):
            if current is not route:
                return originals[1](current, *args, **kwargs)
            case.assertFalse(_IN_TRANSACTION.get())
            if not kwargs['historical']:
                case.assertEqual((1, 1, 1), (counts['dispatch'], counts['start_ack'], counts['ref_write']))
                parent_item = tasks._effect_ownership[task_id]
                parent = parent_item['native_handle']
                case.assertIs(parent.thread, main_thread)
                case.assertFalse(parent_item['returned'])
                case.assertFalse(parent.done.is_set())
                with case.assertRaisesRegex(WarrantError, '^CODING_NATIVE_RECONCILIATION_PARENT$'):
                    tasks._native_git_reconciliation_parent(parent)
                observations.append({'boundary': 'ACTUAL_UNRETURNED_PARENT_DENIED',
                                     'thread_alive': parent.thread.is_alive(), 'done': parent.done.is_set()})
                counts['postwrite_fault'] += 1
                observations.append({'boundary': 'POSTWRITE_ACK_LOSS_BEFORE_ORIGINAL_READBACK'})
                raise CommitOutcomeUnknown()
            if gate_enabled:
                item = lifecycle._boundary.coding_effect
                case.assertIs(item['parent_item'], baseline['item'])
                case.assertIs(item['native_handle'].thread, threading.current_thread())
                case.assertFalse(item['returned'])
                for action, payload in (('apply', exact), ('approve', exact), ('start', {'task_id': task_id})):
                    with case.assertRaises(AdmissionError):
                        self.host.runtime.coding_request(action, payload, principal=None)
                    observations.append({'boundary': 'CHILD_' + action.upper() + '_DENIED'})
                with case.assertRaisesRegex(WarrantError, '^CODING_NATIVE_START_ACK_BINDING$'):
                    tasks._native_git_start_ack(route, warrant)
                with case.assertRaisesRegex(WarrantError, '^CODING_NATIVE_START_ACK_BINDING$'):
                    route.dispatch(args[0], warrant, item['operation'], reservation, cancel=item['cancel'])
                observations.append({'boundary': 'CHILD_START_AND_DISPATCH_DENIED'})
                gate_entered.set()
                case.assertTrue(release_readback.wait(60), 'GIT_CHILD_READBACK_GATE_TIMED_OUT')
            value = originals[1](current, *args, **kwargs)
            counts['readback'] += 1
            return value

        try:
            before = canonical_read()
            case.assertEqual([None, None, None], before)
            with (managed.authority(Capability.READ) as principal,
                  case.assertRaisesRegex(WarrantError, '^GIT_DISPATCH_PROVENANCE_REQUIRED$')):
                route._run(principal, Capability.READ, route._local_history)
            with case.assertRaisesRegex(WarrantError, '^CODING_NATIVE_RECONCILIATION_BINDING$'):
                self.host.runtime.coding_request('reconcile', {'task_id': task_id}, principal=None)
            case.assertEqual({}, tasks._effect_ownership)
            case.assertEqual({}, lifecycle._handles)
            observations.append({'boundary': 'REAL_HISTORY_WITHOUT_CANONICAL_START_DENIED'})
            with (patch.object(CoreRemoteGitRoute, '_dispatch_local_patch', new=dispatch),
                  patch.object(CoreRemoteGitRoute, '_complete_local_patch', new=complete),
                  patch.object(CoreCodingTasks, '_native_git_start_ack', new=start_ack),
                  patch.object(CoreCodingTasks, '_transition', new=transition),
                  patch.object(git_publish, '_bounded_git', new=bounded_git)):
                state['phase'] = 'SYNCHRONOUS_APPLY'
                with case.assertRaisesRegex(AdmissionError, '^CORE_ADMISSION_DENIED$') as caller_ack:
                    self.request('apply', exact)
                state['apply_caller_ack'] = {'error_type': type(caller_ack.exception).__name__,
                                             'code': str(caller_ack.exception)}
                applied = self.request('get_receipts', {'task_id': task_id})
                state['phase'] = 'RETURNED_SCOPE_HISTORY_READ'
                case.assertEqual('UNKNOWN', applied['state'])
                case.assertEqual((1, 1, 1, 1), (counts['dispatch'], counts['start_ack'],
                                               counts['ref_write'], counts['postwrite_fault']))
                item = tasks._effect_ownership[task_id]
                parent = item['native_handle']
                baseline.update(item=item, cancel=item['cancel'], handles=dict(lifecycle._handles), counts=dict(counts))
                old_binding, old_returned = parent.context, parent.returned
                case.assertIs(parent.thread, main_thread)
                case.assertTrue(parent.thread.is_alive() and parent.done.is_set() and item['returned'])
                case.assertIs(parent.returned[0], tasks)
                case.assertIs(parent.returned[1], item)
                case.assertIs(parent.returned[2], main_thread)
                case.assertIs(parent.returned[3], parent.done)
                state['initial_coding'] = applied['state']
                state['initial_intent'], _, result = canonical_read()
                case.assertIsNone(result)
                case.assertIsNone(state['initial_intent']['resolution'])
                case.assertIs(lifecycle.phase, NativePhase.QUARANTINED)
                case.assertEqual({'status': 'QUARANTINED', 'closed': False}, self.host.close())
                case.assertTrue(parent.cancel.cancelled)
                for label, target, field, replacement in (
                    ('FOREIGN_CONTEXT', parent, 'context', tuple(iter(parent.context))),
                    ('FOREIGN_RETURNED', parent, 'returned', None),
                    ('FOREIGN_THREAD', parent, 'thread', threading.Thread()),
                    ('FOREIGN_TOKEN', parent, 'cancel', CancellationToken()),
                    ('FOREIGN_DONE', parent, 'done', threading.Event()),
                    ('FOREIGN_ROUTE', item, 'route', copy(route)),
                    ('FOREIGN_WARRANT', item, 'warrant', replace(warrant)),
                    ('UNRETURNED_SCOPE', item, 'returned', False),
                    ('FOREIGN_OWNERSHIP_MAP', tasks._effect_ownership, task_id, dict(item)),
                ):
                    deny_parent(label, target, field, replacement)
                case.assertIs(parent.context, old_binding)
                case.assertIs(parent.returned, old_returned)
                baseline['counts'] = dict(counts)
                original_require = coding_tasks.require
                def publication_require(condition, message):
                    value = original_require(condition, message)
                    if (message == 'CODING_NATIVE_RECONCILIATION_PARENT' and not _IN_TRANSACTION.get()
                            and counts['publication_fault'] == 0):
                        identity = 'coding-readback-' + task_id + '-1'
                        child = lifecycle._handles.get(identity)
                        if child is not None and type(child.context) is tuple and len(child.context) == 11:
                            child_item = child.context[0]
                            if child_item['binding'] is child.context and not item.get('readbacks', ()):
                                case.assertIs(child.parent, parent)
                                case.assertIs(child.thread, main_thread)
                                counts['publication_fault'] += 1
                                observations.append({'boundary': 'REGISTERED_FULL_BINDING_BEFORE_PUBLICATION_ACK_LOSS'})
                                raise CommitOutcomeUnknown()
                    return value
                with patch.object(coding_tasks, 'require', new=publication_require):
                    _, first = invoke('RETURNED_MAIN_THREAD_PARENT_READBACK')
                state['first_readback'] = first
                state['parent_returned_thread_alive'] = (parent.context is old_binding and parent.returned is old_returned
                    and parent.thread is main_thread and parent.thread.is_alive() and parent.done.is_set())
                save_proof('returned-scope')
                case.assertEqual('RECOVERY_REQUIRED', first['code'],
                                 'NATIVE_RETURNED_MAIN_THREAD_SCOPE_WRONGLY_REJECTED')
                case.assertEqual('CommitOutcomeUnknown', first['error_type'])
                case.assertEqual(1, counts['publication_fault'])
                prior = item['readbacks'][0]
                prior_handle = prior['native_handle']
                case.assertTrue(prior['returned'] and prior['quarantined'] and prior_handle.quarantined)
                case.assertTrue(prior_handle.done.is_set() and prior_handle.thread is main_thread and main_thread.is_alive())
                case.assertIs(prior_handle.context, prior['binding'])
                case.assertIs(lifecycle._handles[prior_handle.task_id], prior_handle)
                observations.append({'boundary': 'REGISTERED_FULL_BINDING_PUBLICATION_FAULT_RETAINED'})
                gate_enabled, lose_verified_ack = True, True
                def gated_readback():
                    child_response['value'], child_response['outcome'] = invoke('GATED_CHILD_VERIFIED_ACK_LOSS')
                child_thread = threading.Thread(target=gated_readback, name='owned-native-git-reconciliation-child')
                child_thread.start()
                case.assertTrue(gate_entered.wait(60), {'child': child_response, 'counts': counts})
                child_item = item['readbacks'][-1]
                child = child_item['native_handle']
                case.assertIs(child.thread, child_thread)
                case.assertIsNot(child.cancel, parent.cancel)
                case.assertIsNot(child.done, parent.done)
                case.assertIsNot(child_item['admission_guard'], item['admission_guard'])
                snapshot = tasks.lifecycle_snapshot()
                case.assertEqual(1, len(snapshot.work))
                case.assertTrue(snapshot.work[0].thread_alive)
                case.assertFalse(snapshot.work[0].done)
                handles_before = dict(lifecycle._handles)
                _, concurrent = invoke('CONCURRENT_CHILD_DENIED')
                case.assertEqual('CODING_NATIVE_RECONCILIATION_CHILD', concurrent['code'], concurrent)
                case.assertEqual(set(handles_before), set(lifecycle._handles))
                for identity, handle in handles_before.items():
                    case.assertIs(lifecycle._handles[identity], handle)
                state['close_while_child_live'] = self.host.close()
                case.assertEqual({'status': 'QUARANTINED', 'closed': False}, state['close_while_child_live'])
                case.assertTrue(child.cancel.cancelled and child_thread.is_alive())
                case.assertFalse(child.done.is_set() or child_item['returned'])
                case.assertIs(self.host.core, original_core)
                case.assertIs(self.host.runner, original_runner)
                foundation.require_bindings()
                case.assertEqual('UNKNOWN', self.request('get_receipts', {'task_id': task_id})['state'])
                observations.append({'boundary': 'STOP_DRAIN_REAL_CHILD_CORE_RUNNER_BINDING_LIVE',
                                     'child_cancelled': child.cancel.cancelled, 'same_parent_binding': parent.context is old_binding})
                release_readback.set()
                child_thread.join(60)
                case.assertFalse(child_thread.is_alive(), 'GIT_READBACK_SCOPE_DID_NOT_RETURN')
                gate_enabled, lose_verified_ack = False, False
                case.assertEqual('CommitOutcomeUnknown', child_response['outcome']['error_type'], child_response)
                case.assertEqual('RECOVERY_REQUIRED', child_response['outcome']['code'], child_response)
                verified = self.request('get_receipts', {'task_id': task_id})
                intent, _, result = canonical_read()
                case.assertEqual('VERIFIED', verified['state'])
                case.assertEqual('Applied', intent['outcome']['contract_type'])
                case.assertIsNotNone(intent['resolution'])
                case.assertIsNotNone(result)
                case.assertEqual(1, counts['verified_ack_fault'])
                case.assertIs(tasks._effect_ownership[task_id], item)
                case.assertTrue(child_item['quarantined'] and child.quarantined and child_item['returned'] and child.done.is_set())
                state['canonical_after_lost_verified_ack'] = {'coding': verified['state'], 'intent': intent}
                save_proof('verified-ack-lost')
                reconciled, final = invoke('EXPLICIT_READBACK_AFTER_COMMITTED_VERIFIED_ACK_LOSS')
                state['last_readback'] = final
                case.assertIsNone(final['error_type'], final)
                case.assertEqual('VERIFIED', reconciled['state'])
                case.assertEqual({'dispatch': 1, 'start_ack': 1, 'ref_write': 1, 'postwrite_fault': 1,
                                  'publication_fault': 1, 'verified_ack_fault': 1, 'readback': 2}, counts)
                case.assertEqual({}, tasks._effects)
                case.assertEqual({}, tasks._effect_ownership)
                case.assertEqual({}, lifecycle._handles)
                case.assertIs(parent.context, old_binding)
                case.assertIs(parent.returned, old_returned)
                case.assertIs(parent.thread, main_thread)
                case.assertTrue(main_thread.is_alive())
                state['phase'] = 'CANONICAL_VERIFIED_ACK_FAMILY_RETIRED_WITHOUT_RESEND'
                return reconciled
        finally:
            release_readback.set()
            if child_thread is not None and child_thread.ident is not None:
                child_thread.join(60)
            save_proof('final')

    def git_assertions(self, case, *, stop_after_release=False, admission_boundary=None,
                       lost_physical_ack=False, reconciliation_safety=False, terminal_acquisition=False,
                       historical_epoch=False):
        import hashlib
        import json

        from runtime.mission.git_publish import GitSourceSnapshot
        from runtime.mission.warrant import WarrantError
        from runtime.mobile_gateway.wire import verify

        task_id = self.task.task_id
        before_main = self.target_repo.git('rev-parse', 'refs/heads/main').decode().strip()
        before_refs = self.target_repo.git('for-each-ref', '--format=%(refname):%(objectname)')
        try:
            reviewed = self.request('review_effect', {'task_id': task_id})
        except AttributeError as exc:
            if str(exc) != "'NativeCodingHost' object has no attribute 'local_git_binding'":
                raise
            case.fail('NATIVE_SIGNED_REPAIR_HAS_NO_LOCAL_GIT_EFFECT_REVIEW')
        case.assertEqual('REVIEW_REQUIRED', reviewed['state'])
        from dataclasses import replace

        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import RecordKind
        managed, foundation = self.host._native_coding, self.host.foundation
        binding = self.host.coding_tasks._effect(task_id, reviewed['capsule_digest'])
        route, warrant, reservation = binding
        case.assertIs(binding, managed.local_git_binding(task_id, reviewed['capsule_digest']))
        case.assertIs(route.native_access, foundation.access)
        case.assertIs(route.journal, foundation.intent_journal)
        case.assertIs(route.core, self.host.core)
        case.assertIs(route.runner, self.host.runner)
        case.assertIs(route.capsules, self.host.coding_tasks.capsules)
        case.assertIs(route.identity, self.host.identity)
        case.assertIs(route.test_profile, managed.profile)
        case.assertIs(route.plan.source, managed.source_snapshot)
        for field, changed in (('plan', replace(route.plan)), ('target_guard', lambda: managed.lock)):
            original = getattr(route, field)
            try:
                setattr(route, field, changed)
                with case.assertRaisesRegex(WarrantError, '^NATIVE_GIT_RETAINED_BINDING$'):
                    foundation.require_bindings()
            finally:
                setattr(route, field, original)
        foundation.require_bindings()
        preview = reviewed['effect_preview']
        case.assertEqual('NONE', preview['authority'])
        operation = preview['operation']
        case.assertEqual('GIT_COMMIT', operation['operation_class'])
        case.assertEqual('DISPOSABLE_BARE_PATCH_V1', operation['payload']['profile'])
        case.assertEqual(reviewed['capsule_digest'], preview['capsule_digest'])
        case.assertEqual(before_refs, self.target_repo.git('for-each-ref', '--format=%(refname):%(objectname)'))
        exact = {'task_id': task_id, 'capsule_digest': preview['capsule_digest'],
                 'operation_digest': preview['operation_digest']}
        for field in ('capsule_digest', 'operation_digest'):
            with case.assertRaisesRegex(WarrantError, '^CODING_EXACT_APPROVAL_REQUIRED$'):
                self.request('approve', {**exact, field: '0' * 64})
        case.assertEqual('REVIEW_REQUIRED', self.request('read_status', {'task_id': task_id})['state'])
        case.assertEqual(before_refs, self.target_repo.git('for-each-ref', '--format=%(refname):%(objectname)'))
        approved = self.request('approve', exact)
        case.assertEqual('APPROVED', approved['state'])
        case.assertEqual(before_refs, self.target_repo.git('for-each-ref', '--format=%(refname):%(objectname)'))
        if admission_boundary is not None:
            self._interrupt_git_admission(case, route, exact, admission_boundary)
            return
        if terminal_acquisition:
            return self._terminal_child_acquisition(case, route, exact)
        if reconciliation_safety:
            applied = self._git_reconciliation_safety(case, route, exact)
        elif historical_epoch:
            applied = self._reconcile_lost_git_ack(case, route, exact, historical_epoch=True)
        elif lost_physical_ack:
            applied = self._reconcile_lost_git_ack(case, route, exact)
        else:
            applied = (self._apply_git_with_owned_stop(case, route, exact) if stop_after_release
                       else self.request('apply', exact))
        case.assertEqual('VERIFIED', applied['state'], applied)
        payload = operation['payload']
        observed = GitSourceSnapshot.capture(self.target_repo.path, expected_sha=payload['commit_sha'],
            repository_id=self.body['project_source']['repository_id'],
            workspace_id=self.body['project_source']['workspace_id'], ref=payload['ref'])
        expected = dict(self.host._native_coding.source_snapshot.files)
        expected.update((file.path, file.text.encode()) for file in self.candidates[-1].files)
        case.assertEqual(expected, dict(observed.files))
        case.assertEqual(payload['tree_sha'], observed.git_tree_sha)
        case.assertEqual(before_main, self.target_repo.git('rev-parse', 'refs/heads/main').decode().strip())
        changes = self.target_repo.git('diff-tree', '--no-commit-id', '--name-status', '-r', payload['commit_sha']).decode().splitlines()
        case.assertEqual(['A\tsrc/extra.py', 'M\tsrc/textutil.py'], changes)
        case.assertEqual(payload['commit_sha'], self.target_repo.git('rev-parse', payload['ref']).decode().strip())
        receipts = self.request('get_receipts', {'task_id': task_id})
        for signed in receipts['receipts']:
            verify(self.host.identity.spki, signed['signature'], signed['receipt'])
        def canonical_read(tx):
            result = tx.get(RecordKind.OPERATION, 'github-result-' + route.plan.operation_id)
            case.assertIsNotNone(result)
            _, intent = route.journal._load(tx, warrant)
            witness = tx.get(RecordKind.APPROVAL, foundation.ledger._key(warrant))
            risk = foundation.governor._load(tx)['reservations'][reservation.request_id]
            return json.loads(canonical_json_bytes((result.payload, intent, witness.payload, risk)))
        with managed.authority(Capability.READ) as principal:
            result, intent, witness, risk = route._run(principal, Capability.READ, canonical_read)
        signed_git = result['result']
        verify(self.host.identity.spki, signed_git['signature'], signed_git['receipt'])
        case.assertEqual('LOCAL_GIT_VERIFIED', signed_git['receipt']['state'])
        case.assertEqual(payload['commit_sha'], signed_git['receipt']['commit_sha'])
        case.assertEqual(observed.digest, signed_git['receipt']['readback_digest'])
        case.assertIs(False, signed_git['receipt']['remote_write_performed'])
        case.assertIs(False, signed_git['receipt']['automatic_retry'])
        case.assertEqual('Applied', intent['outcome']['contract_type'])
        case.assertIsNotNone(intent['resolution'])
        case.assertEqual('COMMITTED', risk['state'])
        case.assertEqual((0, 1), (risk['money_nano'], risk['risk_units']))
        case.assertEqual(self.host.instance_id, witness['session_id'])
        case.assertEqual(warrant.digest(), witness['warrant_digest'])
        case.assertEqual({}, self.host.coding_tasks._effects)
        case.assertEqual((), self.host.coding_tasks.lifecycle_snapshot().work)
        case.assertEqual(0, self.host.model_calls())
        proof = {'schema': 'nz13.native-owned-git-flow.v1', 'fixture_os_admission': 'FIXTURE_OS_ADMISSION',
            'model_certification': 'NOT_CERTIFIED', 'review': reviewed, 'approval': approved,
            'final': receipts, 'operation': operation, 'signed_git': signed_git,
            'intent': intent, 'risk': risk, 'owner_witness': witness, 'readback_digest': observed.digest,
            'main_before': before_main, 'main_after': before_main,
            'changes': changes, 'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in observed.files}}
        raw = json.dumps(proof, sort_keys=True).encode()
        path = self.root / 'native-git-flow-proof.json'
        self.context['safe'].write_new(path, raw)
        self.retained['git'] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}

    def observe_git_mutation_source_io(self, case, *, reconciliation_safety):
        import hashlib
        import json
        import sys
        from pathlib import Path
        from unittest.mock import patch

        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
        from runtime.mission import sandbox_linux

        original_read = Path.read_bytes
        broker_source = Path(sandbox_linux.__file__)
        git_source = str(self.context['source_root'] / 'runtime/mission/git_publish.py')
        events, completed = [], False
        def read(path):
            if path == broker_source:
                self.context['strict_path_guard'](path)
                case.assertEqual(self.context['source_root'] / 'runtime/mission/sandbox_linux.py', path)
                callers, frame = [], sys._getframe(1)
                for _ in range(48):
                    if frame is None:
                        break
                    if frame.f_code.co_filename == git_source and len(callers) < 12:
                        callers.append({'module': 'runtime.mission.git_publish',
                                        'function': frame.f_code.co_name, 'line': frame.f_lineno})
                    frame = frame.f_back
                events.append({'path': 'runtime/mission/sandbox_linux.py',
                               'inside_sql': bool(_IN_TRANSACTION.get()), 'callers': callers})
            return original_read(path)
        try:
            with patch.object(Path, 'read_bytes', new=read):
                self.git_assertions(case, reconciliation_safety=reconciliation_safety)
            completed = True
        finally:
            # Preserve actual original workflow/readback/settlement outcome even
            # when an earlier integrity exception prevents qualification.
            data = {'schema': 'nz13.native-git-mutation-source-io-observation.v1',
                'qualification': False, 'workflow': 'TYPED_SHARED_SAFETY' if reconciliation_safety else 'ORDINARY',
                'scope': 'REAL_LINUX_GIT_FIXTURE_TLS_FLAG_ONLY',
                'original_git_workflow_completed': completed, 'original_git_flow_proof': self.retained.get('git'),
                'events': events, 'inside_sql_count': sum(row['inside_sql'] for row in events),
                'observer': 'DELEGATE_ORIGINAL_READ_ONCE_RAM_CONTEXTVAR_AND_CODE_CALLERS_ONLY'}
            raw = json.dumps(data, sort_keys=True).encode()
            path = self.root / 'native-git-mutation-source-io-observation.json'
            self.context['safe'].write_new(path, raw)
            self.retained['mutation_source_io'] = {'path': str(path), 'bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest()}
        case.assertTrue(completed)
        case.assertIsNotNone(self.retained.get('git'))
        case.assertEqual(0, data['inside_sql_count'], 'NATIVE_GIT_MUTATION_SQL_SOURCE_IO')

    def produce_terminal_acquisition_history(self, case):
        self.complete_single_candidate(case)
        return self.git_assertions(case, terminal_acquisition=True)

    def _terminal_child_acquisition(self, case, route, exact):
        import threading
        from unittest.mock import patch

        from runtime.core_admission import AdmissionError
        from runtime.memory_patch.persistence.ports import (
            _IN_TRANSACTION,
            CommitOutcomeUnknown,
        )
        from runtime.meta_hackathon.native_authority import (
            NativeLifecycle,
            NativeOwnedWorkHandle,
        )
        from runtime.mission import git_publish
        from runtime.mission.git_publish import CoreRemoteGitRoute
        from runtime.mission.warrant import WarrantError

        h, tasks, lifecycle = self.host, self.host.coding_tasks, self.host.foundation.lifecycle
        task_id = self.task.task_id
        original_dispatch, original_complete = CoreRemoteGitRoute._dispatch_local_patch, CoreRemoteGitRoute._complete_local_patch
        original_git, original_begin = git_publish._bounded_git, NativeLifecycle.begin_synchronous
        counts = {'dispatch': 0, 'ref_write': 0, 'postwrite_fault': 0, 'acquisition_fault': 0, 'readback': 0}
        observations = []
        def dispatch(current, *args, **kwargs):
            if current is route:
                counts['dispatch'] += 1
            return original_dispatch(current, *args, **kwargs)
        def bounded_git(repository, arguments, **kwargs):
            result = original_git(repository, arguments, **kwargs)
            if repository == route.target_repository and arguments[0] == 'update-ref':
                case.assertEqual(('update-ref', route.plan.ref, route.plan.commit_sha, '0' * 40), arguments)
                counts['ref_write'] += 1
            return result
        def complete(current, *args, **kwargs):
            if current is route:
                case.assertFalse(_IN_TRANSACTION.get())
                if not kwargs['historical']:
                    counts['postwrite_fault'] += 1
                    observations.append('POSTWRITE_TYPED_ACK_LOSS_BEFORE_ORIGINAL_READBACK')
                    raise CommitOutcomeUnknown()
                counts['readback'] += 1
            return original_complete(current, *args, **kwargs)
        with (patch.object(CoreRemoteGitRoute, '_dispatch_local_patch', new=dispatch),
              patch.object(CoreRemoteGitRoute, '_complete_local_patch', new=complete),
              patch.object(git_publish, '_bounded_git', new=bounded_git)):
            with case.assertRaisesRegex(AdmissionError, '^CORE_ADMISSION_DENIED$'):
                self.request('apply', exact)
            before = self.request('get_receipts', {'task_id': task_id})
            case.assertEqual('UNKNOWN', before['state'])
            item = tasks._effect_ownership[task_id]
            parent = item['native_handle']
            old_context, old_thread, old_token, old_guard = parent.context, parent.thread, parent.cancel, item['admission_guard']
            case.assertTrue(item['returned'] and parent.done.is_set() and parent.quarantined)
            case.assertEqual({'status': 'QUARANTINED', 'closed': False}, self.close())
            registered = []
            def begin(current, producer, role, identity, cancel, *, parent=None):
                value = original_begin(current, producer, role, identity, cancel, parent=parent)
                if current is lifecycle and producer is tasks and parent is item['native_handle']:
                    case.assertFalse(_IN_TRANSACTION.get())
                    case.assertIs(type(value), NativeOwnedWorkHandle)
                    case.assertIs(lifecycle._handles[identity], value)
                    case.assertIs(value.thread, threading.current_thread())
                    registered.append(value)
                    counts['acquisition_fault'] += 1
                    observations.append('ORIGINAL_CHILD_REGISTERED_RETURN_LOST_BEFORE_CALLER_BINDING')
                    raise CommitOutcomeUnknown()
                return value
            with (patch.object(NativeLifecycle, 'begin_synchronous', new=begin),
                  case.assertRaisesRegex(CommitOutcomeUnknown, '^RECOVERY_REQUIRED$')):
                h.runtime.coding_request('reconcile', {'task_id': task_id}, principal=None)
            case.assertEqual(1, len(registered))
            child = registered[0]
            child_item = item['readbacks'][0]
            case.assertIs(child_item['native_handle'], child)
            case.assertIs(child.parent, parent)
            case.assertIs(child.thread, threading.current_thread())
            case.assertIsNone(child_item['binding'])
            case.assertEqual((), child.context)
            case.assertTrue(child_item['returned'] and child.done.is_set() and child.quarantined)
            case.assertIs(lifecycle._handles[child.task_id], child)
            with case.assertRaisesRegex(WarrantError, '^CODING_NATIVE_RECONCILIATION_CHILD$'):
                h.runtime.coding_request('reconcile', {'task_id': task_id}, principal=None)
            with case.assertRaisesRegex(AdmissionError, '^CORE_ADMISSION_DENIED$'):
                h.runtime.coding_request('apply', exact, principal=None)
            case.assertIs(parent.context, old_context)
            case.assertIs(parent.thread, old_thread)
            case.assertIs(parent.cancel, old_token)
            case.assertIs(item['admission_guard'], old_guard)
            case.assertEqual({'dispatch': 1, 'ref_write': 1, 'postwrite_fault': 1,
                              'acquisition_fault': 1, 'readback': 0}, counts)
            after = self.request('get_receipts', {'task_id': task_id})
            case.assertEqual('UNKNOWN', after['state'])
            close = self.close()
            case.assertEqual({'status': 'QUARANTINED', 'closed': False}, close)
            case.assertFalse(h._closed)
            history_locator = {'ref': route.plan.ref, 'tree_sha': route.plan.tree_sha,
                'commit_sha': route.plan.commit_sha, 'operation_id': route.plan.operation_id,
                'target_repository': str(route.target_repository),
                'objects': [[kind, identity] for kind, _, identity in route.plan.objects]}
            proof = {'counts': counts, 'boundaries': observations, 'before': before, 'after': after,
                'local_git_read_locator': history_locator,
                'close': close, 'phase': lifecycle.phase.value, 'retained_handles': len(lifecycle._handles),
                'retained_effects': len(tasks._effect_ownership), 'incomplete_binding_retained': True,
                'old_parent_bindings_unchanged': True, 'actual_returned_done_child': True,
                'core_retained_before_process_exit': True, 'model_calls': h.model_calls()}
            return self.write_restart_handoff('TERMINAL_CHILD_ACQUISITION', proof)

    def restart_business_read(self):
        import json

        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.audit import domain_chain
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.meta_hackathon.native_authority import NativeCapacityCoreView
        from runtime.mission.coding_tasks import KIND as CODING_KIND
        from runtime.mission.coding_tasks import decode_coding_task_row
        from runtime.mission.jobs import KIND as JOB_KIND
        from runtime.mission.jobs import load_job
        from runtime.mobile_gateway import wire

        h, f = self.host, self.host.foundation
        def read(tx):
            coding, kept, job_ids, actual = {}, {}, set(), {}
            for kind in RecordKind:
                rows = tx.scan(kind, limit=1024)
                self.case.assertLess(len(rows), 1024)
                for row in rows:
                    row.verify()
                    identity = kind.value + ':' + row.record_id
                    kept[identity] = {'revision': row.revision, 'payload_digest': row.payload_digest}
                    actual[identity] = row
                    if kind is not RecordKind.OPERATION:
                        continue
                    if row.payload.get('schema') == CODING_KIND:
                        _, value, task = decode_coding_task_row(row, row.payload['task']['task_id'], h.identity.spki)
                        coding[task.task_id] = h.coding_tasks._view(value)
                    if row.payload.get('operation_kind') == JOB_KIND:
                        job_ids.add(row.payload['outcome']['job']['envelope']['task_id'])
            # The constructor's one fresh mobile admission is the ONLY allowed
            # business delta. Its original audit/outbox append is retained too.
            key = 'mobile-operator-' + h.instance_id
            identity = wire.digest(wire.canonical([key, 1]))
            admission_keys = ('operation:' + key, 'audit:mobile-audit-' + identity,
                              'outbox:mobile-outbox-' + identity)
            admission = actual[admission_keys[0]]
            self.case.assertEqual(1, admission.revision)
            self.case.assertEqual(json.loads(canonical_json_bytes(admission.payload)), {
                'schema': 'aioa.mobile.transport.v1', 'state': 'MOBILE_OPERATOR_ADMISSION',
                'authentication': h.operator_authentication, 'source_sha': h.source[0],
                'capsule_digest': h.source[1], 'core_instance_id': h.instance_id})
            events = domain_chain(tx)  # Original complete-chain decoder/validator.
            event = next(event for event in events if event.audit_event_id == 'mobile-audit-' + identity)
            self.case.assertEqual(key, event.resource_id)
            self.case.assertEqual('MOBILE_TRANSPORT_RECORD', event.event_type)
            outbox = actual[admission_keys[2]]
            self.case.assertEqual('mobile-audit-' + identity, outbox.payload['event_id'])
            self.case.assertEqual(event.event_hash, outbox.payload['event_digest'])
            governor = f.governor._load(tx)
            view = NativeCapacityCoreView.read_in_transaction(tx, f)
            try:
                view.require_idle()
                idle = True
            except AdmissionError as error:
                self.case.assertEqual('CORE_ADMISSION_DENIED', str(error))
                idle = False
            _, target = f.target_projection.load(tx)
            return json.loads(canonical_json_bytes({'coding': coding, 'business_rows': kept,
                'fresh_admission_rows': {key: kept[key] for key in admission_keys},
                'audit_events': [event.audit_event_id for event in events],
                'governor': governor, 'capacity': view.to_dict(), 'capacity_idle': idle, 'target': target,
                'jobs': {identity: load_job(f.governor, tx, identity) for identity in sorted(job_ids)}}))
        with h._native_coding.authority(Capability.READ) as principal:
            return h.coding_tasks._run(principal, Capability.READ, read)

    def write_restart_handoff(self, scenario, observations):
        import hashlib
        import json

        from runtime.memory_patch.contracts.serialization import canonical_sha256

        self.case.assertIn(scenario, ('ORPHAN_RUNNING_ACK', 'TERMINAL_CHILD_ACQUISITION', 'LEGACY_V1_CAPACITY', 'NEWER_LIMITS_RECEIPT'))
        h = self.host
        business = self.restart_business_read()
        produced = sorted(h._native_coding.jobs)
        if scenario == 'TERMINAL_CHILD_ACQUISITION':
            self.case.assertEqual(4, len(produced))
            self.case.assertEqual(produced, sorted(business['jobs']))
            self.case.assertTrue(all(business['jobs'][identity]['state'] == 'DONE' for identity in produced))
            self.case.assertEqual([], self.body['retained_sandbox_task_ids'])
        business_raw = json.dumps(business, sort_keys=True).encode()
        self.case.assertLessEqual(len(business_raw), 4 * 1024 * 1024)
        business_path = self.root / 'native-restart-business-before.json'
        self.context['safe'].write_new(business_path, business_raw)
        business_ref = {'path': str(business_path), 'bytes': len(business_raw),
                        'sha256': hashlib.sha256(business_raw).hexdigest()}
        self.retained['restart_business_before'] = business_ref
        body = json.loads(json.dumps(self.body))
        body_sha = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        handoff = {'schema': 'nz13.native-owned-restart-handoff.v1', 'scenario': scenario,
            'fixture_root': str(self.root), 'native_root': str(self.native_root),
            'runtime_tmp': str(self.runtime_tmp), 'origin': self.origin, 'host_config': body,
            'host_config_json_sha256': body_sha,
            'produced_sandbox_task_ids': produced,
            'offline_candidates': [[{'path': file.path, 'text': file.text} for file in candidate.files]
                                   for candidate in self.candidates],
            'task': self.task.to_dict(), 'old_source': list(h.source), 'old_instance_id': h.instance_id,
            'identity_spki_sha256': canonical_sha256(h.identity.spki), 'old_business': business_ref,
            'observations': observations, 'producer_pid': __import__('os').getpid(),
            'qualification': False, 'completion_status': 'HISTORY_PRODUCED_UNQUALIFIED'}
        raw = json.dumps(handoff, sort_keys=True).encode()
        self.case.assertLessEqual(len(raw), 65536)
        path = self.root / 'native-restart-handoff.json'
        self.context['safe'].write_new(path, raw)
        self.retained['restart_handoff'] = {'path': str(path), 'bytes': len(raw),
                                           'sha256': hashlib.sha256(raw).hexdigest()}
        return self.retained['restart_handoff']

    def legacy_reader_load(self):
        import base64
        import hashlib
        import importlib.machinery
        import importlib.util
        import json
        import sys
        from pathlib import Path

        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION

        case = self.case
        case.assertFalse(_IN_TRANSACTION.get())
        path = Path(__file__).parent / 'fixtures' / 'nz13_f13_governor_599195.json'
        raw = self.context['safe'].read(path, maximum=131072)
        case.assertEqual('f93c45884dee87b53b7bebf5aea6e2c33af89aedcaefaba9518d9f38d25a1b59',
                         hashlib.sha256(raw).hexdigest())
        data = json.loads(raw)
        case.assertEqual({'schema', 'license', 'license_notice', 'provenance', 'source_base64'}, set(data))
        case.assertEqual('aioa.test-authentic-f13-governor.v1', data['schema'])
        case.assertEqual('MIT', data['license'])
        case.assertEqual('a039f83d1d59d97624c355653e0eab74a45b867a091d3d10d12ac1183535e14c',
                         hashlib.sha256(data['license_notice'].encode()).hexdigest())
        original = base64.b64decode(data['source_base64'], validate=True)
        case.assertEqual(28911, len(original))
        case.assertEqual('599195e37a64acefb66ae373dd4e273078c5c60242d424048772b484c9553767',
                         hashlib.sha256(original).hexdigest())
        case.assertEqual('76c45fc828adcbafa055a984b8bdc62a825de12c', data['provenance']['git_blob'])
        case.assertEqual('76c45fc828adcbafa055a984b8bdc62a825de12c', hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\x00' + original).hexdigest())
        name = 'nz13_f13_governor_fixture_599195'
        case.assertNotIn(name, sys.modules)
        code_filename = str(path) + '::decoded-F13-runtime-mission-governor.py'
        class _F13FixtureLoader(importlib.machinery.SourceFileLoader):
            def get_code(self, fullname):
                case.assertEqual(name, fullname)
                case.assertEqual(name, self.name)
                case.assertEqual(str(path), self.path)
                case.assertFalse(_IN_TRANSACTION.get())
                return compile(original, code_filename, 'exec', dont_inherit=True)
        loader = _F13FixtureLoader(name, str(path))
        spec = importlib.util.spec_from_loader(name, loader)
        module = importlib.util.module_from_spec(spec)
        module.__file__ = str(path)  # Actual source container, not current governor.py.
        module.__package__ = ''
        sys.modules[name] = module
        try:
            loader.exec_module(module)
        except BaseException:
            if sys.modules.get(name) is module:
                del sys.modules[name]
            raise
        def release_module():
            if sys.modules.get(name) is module:
                del sys.modules[name]
        case.addCleanup(release_module)
        f = self.host.foundation
        policy_owner = f.governor
        policy = f.governor.policy
        legacy_policy = module.GovernorPolicy(policy.scope, policy.deployment_id,
            module.Limits(policy.task_limit.money_nano, policy.task_limit.risk_units),
            module.Limits(policy.owner_provider_limit.money_nano, policy.owner_provider_limit.risk_units),
            module.Limits(policy.global_limit.money_nano, policy.global_limit.risk_units),
            failure_threshold=policy.failure_threshold, cooldown_seconds=policy.cooldown_seconds,
            recovery_successes=policy.recovery_successes,
            max_clock_step_seconds=policy.max_clock_step_seconds)
        case.assertEqual(policy.digest, legacy_policy.digest)
        legacy = module.CoreDualGovernor(f.core, f.runner, legacy_policy)
        origin = {'module': name, 'container': str(path), 'container_sha256': hashlib.sha256(raw).hexdigest(),
            'decoded_code_sha256': hashlib.sha256(original).hexdigest(), 'decoded_code_bytes': len(original),
            'code_filename': code_filename, 'origin_scope': 'AUTHENTIC_HISTORICAL_TEST_DATA_NOT_CURRENT_AUTHORITY',
            'policy_digest': legacy_policy.digest, 'same_core': legacy.core is f.core,
            'same_runner': legacy.runner is f.runner, 'current_governor_unchanged': f.governor is policy_owner}
        return module, legacy, origin

    def legacy_reader_observe(self, module, legacy, *, expect_capacity=False):
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import (
            _IN_TRANSACTION,
            TransactionContext,
        )
        from runtime.meta_hackathon.native_authority import NativeAccessUse

        case, f = self.case, self.host.foundation
        case.assertFalse(_IN_TRANSACTION.get())
        current_governor, current_policy = f.governor, f.governor.policy
        capture = f.access.capture(Capability.READ, use=NativeAccessUse.READ)
        returned, error_type, error_code, reason = None, None, None, None
        try:
            legacy._require(capture.principal, Capability.READ)
            def read(tx):
                f.access.require_capture(capture, Capability.READ, tx=tx)
                try:
                    return legacy._load(tx)
                finally:
                    f.access.require_capture(capture, Capability.READ, tx=tx)
            try:
                returned = f.runner.run(TransactionContext(capture.principal, Capability.READ), read)
            except module.GovernorError as error:
                if not expect_capacity or error.reason is not module.GovernorReason.INTEGRITY:
                    raise
                error_type, error_code, reason = type(error).__name__, str(error), error.reason.value
            f.access.require_capture(capture, Capability.READ)
            case.assertIs(current_governor, f.governor)
            case.assertIs(current_policy, f.governor.policy)
        finally:
            capture.close()
        return {'value': None if returned is None else __import__('json').loads(canonical_json_bytes(returned)),
            'error_type': error_type, 'code': error_code, 'reason': reason,
            'same_core': legacy.core is f.core, 'same_runner': legacy.runner is f.runner,
            'capture_closed_after_finally': capture._closed, 'read_path': 'ORIGINAL_OLD_REQUIRE_AND_LOAD_ON_ACTUAL_CURRENT_PORT'}

    def legacy_capacity_snapshot(self):
        import json

        from runtime.core_admission import Capability
        from runtime.memory_patch.adapters.cockroach.repositories import (
            canonical_record,
        )
        from runtime.memory_patch.contracts.serialization import (
            canonical_json_bytes,
            canonical_sha256,
        )
        from runtime.memory_patch.persistence.ports import (
            RecordKind,
            TransactionContext,
        )
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        from runtime.mission.governor import _exposure

        case, h = self.case, self.host
        f = h.foundation
        capture = f.access.capture(Capability.READ, use=NativeAccessUse.READ)
        try:
            def read(tx):
                f.access.require_capture(capture, Capability.READ, tx=tx)
                try:
                    state = f.governor._load(tx)
                    rows = {}
                    for kind in RecordKind:
                        records = tx.scan(kind, limit=1024)
                        case.assertLess(len(records), 1024)
                        for row in records:
                            row.verify()
                            rows[kind.value + ':' + row.record_id] = {
                                'canonical_record': canonical_record(row),
                                'payload_digest': row.payload_digest, 'revision': row.revision}
                    return json.loads(canonical_json_bytes({
                        'state': state, 'exposure': _exposure(state['reservations']), 'rows': rows}))
                finally:
                    f.access.require_capture(capture, Capability.READ, tx=tx)
            value = f.runner.run(TransactionContext(capture.principal, Capability.READ), read)
        finally:
            capture.close()
        return {**value, 'business': self.restart_business_read(),
            'phase': f.lifecycle.phase.value, 'policy_digest': f.governor.policy.digest,
            'identity_spki_sha256': canonical_sha256(h.identity.spki)}

    def legacy_capacity_save(self, name, value):
        import hashlib
        import json

        raw = json.dumps(value, sort_keys=True).encode()
        self.case.assertLessEqual(len(raw), 4 * 1024 * 1024)
        path = self.root / name
        self.context['safe'].write_new(path, raw)
        return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

    def populate_newer_limits_accounting_history(self):
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.mission.governor import ReservationRequest

        h, f = self.host, self.host.foundation
        review = f.governor.money_policy_review(h.core.local_operator(Capability.READ),
            {'task_limit': 100000000, 'owner_provider_limit': 100000000, 'global_limit': 100000000},
            request_id='newer-limits-money')
        f.governor.apply_money_policy(h.core.local_operator(Capability.MANAGE), review)
        state = self.legacy_capacity_snapshot()['state']
        epoch = state['epoch']
        failure_threshold = state['execution_capacity']['capacity']['sandbox_exec_failure_threshold']
        for index in range(failure_threshold):
            request = ReservationRequest('newer-limits-prior-' + str(index), 'newer-limits-task-' + str(index),
                'sandbox-exec', 'aioa/offline-host-worker-v1',
                canonical_sha256(['newer-limits-bookkeeping-only', index]), 1, 1)
            f.governor.reserve(h.core.local_operator(Capability.COMMIT), request, epoch)
            f.governor.dispatch_commit(h.core.local_operator(Capability.COMMIT), request.request_id, epoch)
            f.governor.mark_unknown(h.core.local_operator(Capability.COMMIT), request.request_id, epoch,
                canonical_sha256(['newer-limits-bookkeeping-only', index, 'unknown']))
            f.governor.settle(h.core.local_operator(Capability.COMMIT), request.request_id, epoch,
                canonical_sha256(['newer-limits-bookkeeping-only', index, 'pessimistic-commit']))

    def produce_capacity_history_for_newer_limits_restart(self, case):
        import os

        h, f = self.host, self.host.foundation
        case.assertEqual('ACTIVE', f.lifecycle.phase.value)
        self.populate_newer_limits_accounting_history()
        before = self.legacy_capacity_snapshot()
        case.assertEqual('OPEN', before['state']['circuits']['sandbox-exec']['state'],
                         'NATIVE_NEWER_LIMITS_OPEN_BASELINE_REQUIRED')
        request_id = before['state']['execution_capacity']['request_id']
        # Actual original trusted readback, not a manufactured receipt. The
        # public capacity dispatcher is deliberately CAPACITY_ADMIN only.
        receipt = f.controller._readback(request_id)
        actual_receipt = None if receipt is None else receipt.to_dict()
        after = self.legacy_capacity_snapshot()
        before_ref = self.legacy_capacity_save('native-newer-limits-os1-before.json', before)
        after_ref = self.legacy_capacity_save('native-newer-limits-os1-after-read.json', after)
        observed = {'schema': 'aioa.native-newer-limits-producer.v1', 'qualification': False,
            'fixture_scope': 'FIXTURE_OS_ADMISSION_TLS_FLAG_ONLY_PESSIMISTIC_LOCAL_ACCOUNTING',
            'capacity_request_id': request_id, 'baseline_receipt': actual_receipt,
            'baseline_return_type': type(receipt).__module__ + '.' + type(receipt).__name__,
            'snapshot': before_ref, 'after_read_snapshot': after_ref,
            'actual_spec_config': f.spec.to_dict(), 'actual_spec_digest': f.spec.digest,
            'phase': f.lifecycle.phase.value, 'source': list(h.source),
            'job_observation': h._native_coding.job_observation(), 'model_calls': h.model_calls(),
            'host_preparations': {name: len(getattr(h._native_coding, name))
                                  for name in ('materializations', 'jobs', 'runs', 'effects')},
            'active_tasks': sorted(h.coding_tasks._active), 'owned_effect_tasks': sorted(h.coding_tasks._effect_ownership)}
        handoff = self.write_restart_handoff('NEWER_LIMITS_RECEIPT', observed)
        closed = self.close()
        close_ref = self.legacy_capacity_save('native-newer-limits-os1-close.json', {
            'schema': 'aioa.native-newer-limits-actual-close.v1', 'actual_close_report': closed,
            'handoff': handoff, 'pid': os.getpid(), 'qualification': False})
        self.retained['newer_limits_close'] = close_ref
        case.assertTrue(closed['closed'])
        return handoff

    def produce_legacy_v1_capacity_history(self, case):
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.mission.governor import ReservationRequest

        h, f = self.host, self.host.foundation
        case.assertEqual('CAPACITY_ADMIN', f.lifecycle.phase.value)
        initial = self.legacy_capacity_snapshot()
        case.assertNotIn('execution_capacity', initial['state'])
        # Existing trusted foundation bookkeeping API, as in the original
        # populate fixture. Fresh original Core purposes only; no effect grant,
        # model/provider/tool call or alternative issuer is introduced.
        review = f.governor.money_policy_review(h.core.local_operator(Capability.READ),
            {'task_limit': 100000000, 'owner_provider_limit': 100000000, 'global_limit': 100000000},
            request_id='legacy-v1-money')
        f.governor.apply_money_policy(h.core.local_operator(Capability.MANAGE), review)
        epoch = self.legacy_capacity_snapshot()['state']['epoch']
        for index in range(3):
            request = ReservationRequest('legacy-v1-prior-' + str(index), 'legacy-v1-task-' + str(index),
                'sandbox-exec', 'aioa/offline-host-worker-v1',
                canonical_sha256(['legacy-bookkeeping-only', index]), 1, 1)
            f.governor.reserve(h.core.local_operator(Capability.COMMIT), request, epoch)
            f.governor.dispatch_commit(h.core.local_operator(Capability.COMMIT), request.request_id, epoch)
            f.governor.mark_unknown(h.core.local_operator(Capability.COMMIT), request.request_id, epoch,
                canonical_sha256(['legacy-bookkeeping-only', index, 'unknown']))
            f.governor.settle(h.core.local_operator(Capability.COMMIT), request.request_id, epoch,
                canonical_sha256(['legacy-bookkeeping-only', index, 'pessimistic-commit']))
        module, legacy, origin = self.legacy_reader_load()
        old_read = self.legacy_reader_observe(module, legacy)
        current = self.legacy_capacity_snapshot()
        snapshot = self.legacy_capacity_save('native-legacy-capacity-os1-before.json', current)
        observed = {'schema': 'aioa.native-legacy-capacity-producer.v1',
            'fixture_scope': 'FIXTURE_OS_ADMISSION_TLS_FLAG_ONLY_PESSIMISTIC_LOCAL_ACCOUNTING',
            'initial_state': initial['state'], 'snapshot': snapshot, 'legacy_reader_before': old_read,
            'legacy_origin': origin, 'governor_state': current['state'], 'exposure': current['exposure'],
            'phase_before_close': f.lifecycle.phase.value,
            'no_execution_capacity_before': 'execution_capacity' not in current['state'],
            'legacy_reader_agrees': old_read['value'] == current['state'],
            'job_observation': h._native_coding.job_observation(), 'model_calls': h.model_calls(),
            'host_preparations': {name: len(getattr(h._native_coding, name))
                                  for name in ('materializations', 'jobs', 'runs', 'effects')}}
        # Handoff's original reader must run while the real Core is still
        # open. Actual closure is then retained in a separate pinned sidecar.
        handoff = self.write_restart_handoff('LEGACY_V1_CAPACITY', observed)
        closed = self.close()
        close_ref = self.legacy_capacity_save('native-legacy-capacity-os1-close.json', {
            'schema': 'aioa.native-legacy-capacity-actual-close.v1',
            'actual_close_report': closed, 'handoff': handoff,
            'pid': __import__('os').getpid(), 'qualification': False})
        self.retained['legacy_capacity_close'] = close_ref
        # Closure is an integrity prerequisite to reopening, not invented data.
        case.assertTrue(closed['closed'])
        return handoff

    def produce_orphan_running_ack_history(self, case):
        from dataclasses import asdict, replace
        from unittest.mock import patch

        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.persistence.ports import (
            _IN_TRANSACTION,
            CommitOutcomeUnknown,
        )
        from runtime.mission.coding_tasks import CoreCodingTasks
        from runtime.mission.warrant import WarrantError

        h, tasks = self.host, self.host.coding_tasks
        task_id = self.task.task_id
        original = CoreCodingTasks._transition
        observed = {'faults': 0, 'worker_thread_started': False, 'sandbox_jobs': [],
                    'fixture_os_admission': 'FIXTURE_OS_ADMISSION', 'tls': 'FIXTURE_TLS_FLAG_ONLY'}
        self.request('create_task', {'task': self.task.to_dict()})
        def transition(current, *args, **kwargs):
            value = original(current, *args, **kwargs)
            if (current is tasks and len(args) >= 4 and args[1] == task_id
                    and args[3] == 'RUNNING' and kwargs.get('admission') is True):
                case.assertFalse(_IN_TRANSACTION.get())
                case.assertEqual('RUNNING', value['state'])
                observed['faults'] += 1
                raise CommitOutcomeUnknown()
            return value
        with (patch.object(CoreCodingTasks, '_transition', new=transition),
              case.assertRaisesRegex(CommitOutcomeUnknown, '^RECOVERY_REQUIRED$') as failure):
            self.request('start', {'task_id': task_id})
        observed['caller_error'] = {'type': type(failure.exception).__name__, 'code': str(failure.exception)}
        case.assertEqual(1, observed['faults'])
        active = tasks._active[task_id]
        handle = active['native_handle']
        observed['worker_thread_started'] = active['thread'].ident is not None
        case.assertFalse(observed['worker_thread_started'])
        case.assertFalse(handle.started)
        case.assertTrue(active['quarantined'] and active['done'].is_set())
        observed['old_phase'] = h.foundation.lifecycle.phase.value
        observed['old_native_handle_quarantined'] = handle.quarantined
        observed['old_snapshot'] = asdict(tasks.lifecycle_snapshot())
        observed['old_receipts'] = self.request('get_receipts', {'task_id': task_id})
        case.assertEqual('RUNNING', observed['old_receipts']['state'])
        observed['sandbox_jobs'] = h._native_coding.job_observation()
        case.assertEqual([], observed['sandbox_jobs'])
        probe = replace(self.task, task_id=task_id + '-probe', run_id=self.task.run_id + '-probe')
        try:
            value = self.request('create_task', {'task': probe.to_dict()})
            observed['new_work_probe'] = {'accepted': True, 'state': value['state'], 'error_type': None, 'code': None}
        except AdmissionError as error:
            case.assertEqual('CORE_ADMISSION_DENIED', str(error))
            observed['new_work_probe'] = {'accepted': False, 'state': None,
                                          'error_type': type(error).__name__, 'code': str(error)}
        case.assertEqual([], h._native_coding.job_observation())
        case.assertEqual(0, h.model_calls())
        # The old scope is genuinely retained and quarantined. Calling the
        # original public recover must not gain CONTROL from that ownership.
        runtime = h.runtime
        case.assertIs(runtime._memory_patch_admission, h.foundation.core)
        case.assertIs(runtime._coding_tasks, tasks)
        before_recover = self.restart_business_read()
        returned, error_type, error_code = None, None, None
        phase_before = h.foundation.lifecycle.phase.value
        try:
            returned = runtime.coding_request('recover', {'task_id': task_id}, principal=None)
        except WarrantError as error:
            if str(error) != 'CODING_RUN_ACTIVE':
                raise
            error_type, error_code = type(error).__name__, str(error)
        after_recover = self.restart_business_read()
        observed['quarantine_public_recover'] = {
            'public_api': "AgentRuntime.coding_request('recover', {'task_id': task_id}, principal=None)",
            'phase_before': phase_before, 'phase_after': h.foundation.lifecycle.phase.value,
            'returned_state': None if returned is None else returned['state'],
            'error_type': error_type, 'code': error_code,
            'before_business': before_recover, 'after_business': after_recover,
            'business_unchanged': all(before_recover[key] == after_recover[key] for key in
                ('business_rows', 'audit_events', 'fresh_admission_rows', 'coding', 'governor', 'jobs', 'target')),
            'same_registered_parent': tasks._active.get(task_id) is active
                and active['native_handle'] is handle,
            'actual_parent_quarantined': handle.quarantined,
            'actual_parent_done': active['done'].is_set(),
            'read_purpose': Capability.READ.value,
            'current_work_handle_present': getattr(h.foundation.lifecycle._boundary, 'work_handle', None) is not None,
            'current_settlement_handle_present': getattr(h.foundation.lifecycle._boundary, 'settlement_handle', None) is not None,
            'job_observation': h._native_coding.job_observation(), 'model_calls': h.model_calls()}
        # A different, absent task ID passes the original active-task guard.
        # No ownership/context is installed; the original CONTROL capture must
        # deny this public request in the actual QUARANTINED phase.
        before_control = self.restart_business_read()
        control_returned, control_error_type, control_error_code = None, None, None
        control_phase_before = h.foundation.lifecycle.phase.value
        try:
            control_returned = runtime.coding_request('recover', {'task_id': task_id + '-absent'}, principal=None)
        except AdmissionError as error:
            if str(error) != 'CORE_ADMISSION_DENIED':
                raise
            control_error_type, control_error_code = type(error).__name__, str(error)
        after_control = self.restart_business_read()
        observed['quarantine_control_recover'] = {
            'public_api': "AgentRuntime.coding_request('recover', {'task_id': task_id + '-absent'}, principal=None)",
            'phase_before': control_phase_before, 'phase_after': h.foundation.lifecycle.phase.value,
            'returned_state': None if control_returned is None else control_returned['state'],
            'error_type': control_error_type, 'code': control_error_code,
            'before_business': before_control, 'after_business': after_control,
            'business_unchanged': all(before_control[key] == after_control[key] for key in
                ('business_rows', 'audit_events', 'fresh_admission_rows', 'coding', 'governor', 'jobs', 'target')),
            'same_registered_parent': tasks._active.get(task_id) is active
                and active['native_handle'] is handle,
            'actual_parent_quarantined': handle.quarantined,
            'actual_parent_done': active['done'].is_set(),
            'current_work_handle_present': getattr(h.foundation.lifecycle._boundary, 'work_handle', None) is not None,
            'current_settlement_handle_present': getattr(h.foundation.lifecycle._boundary, 'settlement_handle', None) is not None,
            'job_observation': h._native_coding.job_observation(), 'model_calls': h.model_calls()}
        observed['close'] = self.close()
        case.assertEqual({'status': 'QUARANTINED', 'closed': False}, observed['close'])
        case.assertFalse(h._closed)
        observed['core_retained_before_process_exit'] = True
        # Wrong source-derived phase/new-work observations are DATA here. The
        # supervisor's actual qualification assertions run only after OS2 exits.
        return self.write_restart_handoff('ORPHAN_RUNNING_ACK', observed)

    def _portable_snapshot(self, tasks):
        import json

        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.jobs import load_job

        h, f = self.host, self.host.foundation
        with h.portable_store.target_guard():
            observed = h.portable_store.observe_guarded_inventory()
            def read(tx):
                row, head, histories = f.target_projection._details(tx)
                records = {}
                for kind in RecordKind:
                    values = tx.scan(kind, limit=1024)
                    self.case.assertLess(len(values), 1024)
                    for value in values:
                        value.verify()
                        records[kind.value + ':' + value.record_id] = {
                            'revision': value.revision, 'payload_digest': value.payload_digest}
                joined = {}
                for task in tasks:
                    warrant = task['warrant']
                    context = task['route']._context(tx, warrant)[0]
                    _, intent = f.intent_journal._load(tx, warrant)
                    _, liability = f.liability._load(tx, warrant.task_id)
                    key = f.ledger._key(warrant)
                    joined[warrant.task_id] = {
                        'job': load_job(f.governor, tx, warrant.task_id),
                        'session': tx.get(RecordKind.OPERATION,
                            task['route'].session_key(task['session_id'])).payload,
                        'context': context, 'intent': intent, 'liability': liability,
                        'ledger': tx.get(RecordKind.OPERATION, key).payload,
                        'owner_witness': tx.get(RecordKind.APPROVAL, key).payload}
                return json.loads(canonical_json_bytes({'head': head,
                    'head_record': {'revision': row.revision, 'payload_digest': row.payload_digest},
                    'histories': histories, 'governor': f.governor._load(tx),
                    'canonical_rows': records, 'tasks': joined}))
            with h._native_coding.authority(Capability.READ) as principal:
                snapshot = h.portable_release_route._run(principal, Capability.READ, read)
            snapshot['physical'] = {'inventory': json.loads(observed.canonical_state),
                'state_root': observed.state_root, 'resources_root': observed.resources_root,
                'receipts_root': observed.receipts_root, 'guard_fingerprint': observed.guard_fingerprint,
                'guard_identity': list(observed.guard_identity), 'authority': observed.authority}
        snapshot['executor_counters'] = list(h.portable_executor.counters())
        snapshot['model_calls'] = h.model_calls()
        return snapshot

    def _portable_task(self, policy, domain, *, claim_lease_seconds=60, session_lease_seconds=None):
        import time
        from dataclasses import asdict
        from datetime import UTC, datetime, timedelta

        from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
        from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
        from nonzero_cloudops.models import generate_run_id
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.mission.completion import TaskCompletionBinding
        from runtime.mission.governor import ReservationRequest
        from runtime.mission.job_contracts import JobEnvelope
        from runtime.mission.portable_target import (
            PortableOperation,
            PortableRearmOperation,
            PortableRearmRequest,
        )
        from runtime.mission.tools import LocalSessionGrant

        h, f, case = self.host, self.host.foundation, self.case
        managed = h._native_coding
        label = 'native-portable-' + ('release' if policy == 4 else 'rearm')
        task_id, session_id, nonce = label + '-task', label + '-session', label + '-decision'
        route = h.portable_release_route if policy == 4 else h.portable_rearm_route
        with managed.authority(Capability.READ) as principal:
            epoch = f.governor.inspect(principal)['epoch']
            actor, assignment = principal.actor_session_id, principal.assignment_revision
        now = datetime.now(UTC)
        with h.portable_target.target_guard():
            snapshot = h.portable_target.probe()
        arguments = {'workspace': f.spec.project_source.workspace_id, 'task_id': task_id,
            'session_id': session_id, 'principal_session_id': actor, 'policy_epoch': epoch,
            'target_binding_digest': f.target_projection.binding.digest(),
            'target_revision': snapshot.revision, 'domain_input': domain}
        if policy == 4:
            operation = PortableOperation.create(**arguments).to_dict()
        else:
            request = PortableRearmRequest.create(domain_input=domain, request_id=label + '-request',
                run_id=generate_run_id(), actor_session_id=actor, assignment_revision=assignment,
                decision_nonce_hash=canonical_sha256(nonce), requested_at=now,
                expires_at=now + timedelta(seconds=120))
            operation = PortableRearmOperation.create(**arguments, request=request).to_dict()
        trace = FaultTrace(FaultKind.LOST_ACK, task_id, label + '-request',
                           'sha256:' + canonical_sha256(operation))
        graph = DependencyGraph(task_id, (
            DependencyNode('effect', NodeKind.OPERATION, liability_ids=(classify_fault(trace).liability_id,)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('effect',))))
        completion = TaskCompletionBinding.for_graph(f.ledger.scope, graph, 'completion')
        envelope = JobEnvelope.for_offline_host(f.ledger.scope, task_id, request_id=label + '-job',
            request_digest=canonical_sha256(operation), deadline_at=self.task.deadline_at)
        with managed.authority(Capability.COMMIT) as principal:
            f.liability.initialize(principal, graph)
        with managed.authority(Capability.MANAGE) as principal:
            submitted = f.governor.submit_job(principal, envelope, completion=completion)
        with managed.authority(Capability.COMMIT) as principal:
            claim = f.governor.claim_job(principal, task_id, 'native-offline-host', epoch, lease_seconds=claim_lease_seconds)
            started = f.governor.begin_job(principal, claim)
        case.assertIs(True, started['local_step_now'])
        case.assertEqual('STARTED', started['state'])
        now_seconds = int(time.time())
        grant = LocalSessionGrant(session_id, f.ledger.scope, arguments['workspace'], policy,
            (operation['operation_class'],), completion.digest, now_seconds - 1,
            claim.lease_until if session_lease_seconds is None else
                claim.lease_until + session_lease_seconds - claim_lease_seconds,
            epoch, 0, 5, 20, 16384)
        with managed.authority(Capability.OWNER_APPROVAL) as principal:
            route.create_session(principal, grant)
            warrant = route.authorize_exact(principal, session_id, operation, completion, graph, trace,
                nonce=nonce, model_id=envelope.model_id, money_nano=0, risk_units=5)
        reservation = ReservationRequest(warrant.risk_reservation_id, task_id, 'portable-local',
            envelope.model_id, canonical_sha256(operation), 0, 5)
        return {'route': route, 'operation': operation, 'epoch': epoch, 'task_id': task_id,
            'session_id': session_id, 'nonce': nonce, 'warrant': warrant, 'claim': claim,
            'reservation': reservation, 'completion': completion, 'graph': graph, 'trace': trace,
            'facts': {'envelope': envelope.as_dict(), 'submitted': submitted, 'started': started,
                'claim': asdict(claim), 'grant': grant.to_dict(), 'operation': operation,
                'warrant': warrant.to_dict(), 'completion': completion.to_dict()}}

    def portable_assertions(self, case):
        import json
        import traceback
        from datetime import UTC, datetime, timedelta

        from nonzero_cloudops.adapters.portable import PortableResourceReader
        from nonzero_cloudops.investigation import QueryResource
        from nonzero_cloudops.models import (
            BudgetCounters,
            LocalApprovalRequestRecord,
            ProposalState,
            RemediationOperation,
            RemediationProposal,
            ResourceQuery,
            Run,
            generate_proposal_id,
            generate_run_id,
            generate_trace_id,
        )
        from nonzero_cloudops.models.public_enums import AuthorityGate
        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.contracts.serialization import (
            canonical_json_bytes,
            canonical_sha256,
        )
        from runtime.mission.portable_target import PortableDomainInput
        from runtime.mission.warrant import WarrantError

        h, f, managed = self.host, self.host.foundation, self.host._native_coding
        release_route, rearm_route = h.portable_release_route, h.portable_rearm_route
        target, store, executor = h.portable_target, h.portable_store, h.portable_executor
        for route in (release_route, rearm_route):
            case.assertIs(route.executor, target)
            case.assertIs(route.journal, f.intent_journal)
            case.assertIs(route.liability, f.liability)
            case.assertIs(route.target_settlement, f.target_projection)
            case.assertIs(route.native_access, f.access)
            case.assertIs(route.core, h.core)
            case.assertIs(route.runner, h.runner)
        case.assertIs(target.executor, executor)
        case.assertIs(target.store, store)
        case.assertIs(target.projection, f.target_projection)
        case.assertIs(executor._state, store)
        f.require_bindings()
        tasks = []
        proof = {'schema': 'nz13.native-physical-portable-flow.v1', 'phase': 'BEFORE_RELEASE',
            'model_certification': 'NOT_CERTIFIED', 'snapshots': {}, 'operations': {}, 'denials': []}
        def capture(name):
            value = self._portable_snapshot(tasks)
            proof['snapshots'][name] = self.legacy_capacity_save('portable-' + name + '.json', value)
            return value
        def dispatch(route, task):
            with managed.authority(Capability.COMMIT) as principal:
                return route.dispatch(principal, session_id=task['session_id'], warrant=task['warrant'],
                    operation=task['operation'], reservation=task['reservation'], completion=task['completion'])
        def authorize(route, task, purpose, nonce):
            with managed.authority(purpose) as principal:
                return route.authorize_exact(principal, task['session_id'], task['operation'],
                    task['completion'], task['graph'], task['trace'], nonce=nonce,
                    model_id=task['reservation'].model_id, money_nano=0, risk_units=5)
        def negatives(label, attempts):
            before = capture(label + '-before')
            for name, callback, error_type, code in attempts:
                observed = {'name': name, 'accepted': False}
                try:
                    callback()
                    observed['accepted'] = True
                except error_type as error:
                    observed.update(type=type(error).__name__, code=str(error),
                        traceback=[{'file': frame.filename, 'function': frame.name, 'line': frame.lineno}
                            for frame in traceback.extract_tb(error.__traceback__, limit=32)])
                proof['denials'].append(observed)
            after = capture(label + '-after')
            case.assertEqual(before, after, label)
            for observation, attempt in zip(proof['denials'][-len(attempts):], attempts, strict=True):
                case.assertIs(False, observation['accepted'], observation)
                case.assertEqual(attempt[3], observation['code'], observation)
        def settle(task, label):
            with target.target_guard():
                independent = target.verify(task['operation'], task['warrant'])
            proof['operations'][label]['independent_readback'] = json.loads(canonical_json_bytes(independent))
            with managed.authority(Capability.COMMIT) as principal:
                applied = task['route'].reconcile(principal, task['warrant'], task['epoch'])
            proof['operations'][label]['applied'] = applied
            with managed.authority(Capability.COMMIT) as principal:
                finished = f.governor.finish_offline_host_job(principal, task['claim'])
            proof['operations'][label]['finished'] = finished
            observed = capture(label + '-settled')
            case.assertEqual('Applied', applied['outcome']['contract_type'])
            case.assertEqual('DONE', finished['state'])
            case.assertEqual('NOT_CERTIFIED', finished['envelope']['worker_certification'])
            case.assertIsNotNone(finished['completion_proof'])
            case.assertIsNone(observed['head']['in_flight'])
            for field in ('state_root', 'resources_root', 'receipts_root'):
                case.assertEqual(observed['physical'][field], observed['head'][field])
            joined = observed['tasks'][task['task_id']]
            case.assertEqual('Applied', joined['intent']['outcome']['contract_type'])
            case.assertIsNotNone(joined['intent']['resolution'])
            case.assertEqual(task['warrant'].digest(), joined['owner_witness']['warrant_digest'])
            case.assertEqual(h.instance_id, joined['owner_witness']['session_id'])
            case.assertEqual('DONE', joined['job']['state'])
            entry = observed['governor']['reservations'][task['reservation'].request_id]
            case.assertEqual(('COMMITTED', 0, 5), (entry['state'], entry['money_nano'], entry['risk_units']))
            job_entry = observed['governor']['reservations'][joined['job']['reservation_id']]
            case.assertEqual(('COMMITTED', 0, 0),
                (job_entry['state'], job_entry['money_nano'], job_entry['risk_units']))
            return observed
        try:
            baseline = capture('baseline')
            query = ResourceQuery(**self.body['portable']['resource_query'])
            with managed.authority(Capability.READ) as principal:
                actor = principal.actor_session_id
            now = datetime.now(UTC)
            run = Run.new(run_id=generate_run_id(), trace_id=generate_trace_id(),
                correlation_id=generate_run_id(), idempotency_key='native-portable-release-once',
                created_at=now, budget=BudgetCounters(max_turns=1, max_tokens=1))
            with store.target_guard():
                evidence = QueryResource(PortableResourceReader(store)).execute(query, run=run, observed_at=now).value
                case.assertIsNotNone(evidence)
                proposal = RemediationProposal.create(proposal_id=generate_proposal_id(), evidence=evidence,
                    operation_type=RemediationOperation.RELEASE_ELASTIC_IP,
                    normalized_parameters={'allocation_id': query.resource_id},
                    authority_class=AuthorityGate.PLAN_AND_CONFIRM, risk_summary='One owned Native local address',
                    created_at=now, expires_at=now + timedelta(seconds=180))
                proposal = proposal.model_copy(update={'status': ProposalState.AWAITING_APPROVAL})
                request = LocalApprovalRequestRecord.create(request_id=generate_proposal_id(), proposal=proposal,
                    actor_session_id=actor, decision_nonce_hash=canonical_sha256('native-portable-release-decision'),
                    requested_at=now, expires_at=now + timedelta(seconds=120))
                inventory = store.observe_guarded_inventory()
                domain = PortableDomainInput(canonical_json_bytes({'schema': 'aioa.portable-domain-input.v1',
                    'proposal': proposal.model_dump(mode='json'), 'evidence': evidence.model_dump(mode='json'),
                    'request': request.model_dump(mode='json'), 'inventory': json.loads(inventory.canonical_state)}))
            release = self._portable_task(4, domain)
            tasks.append(release)
            proof['operations']['release'] = release['facts']
            negatives('release-denials', [
                ('READ_CANNOT_APPROVE', lambda: authorize(release_route, release, Capability.READ, release['nonce']),
                    AdmissionError, 'CORE_ADMISSION_DENIED'),
                ('POLICY5_CANNOT_DISPATCH_POLICY4', lambda: dispatch(rearm_route, release),
                    WarrantError, 'SESSION_INACTIVE'),
                ('SANDBOX_CANNOT_USE_PORTABLE_APPROVAL', lambda: dispatch(h.sandbox_route, release),
                    WarrantError, 'TARGET_PORT_REQUIRED_FOR_DURABLE_CONTEXT')])
            before_release = capture('release-before')
            unknown = dispatch(release_route, release)
            proof['operations']['release']['unknown'] = unknown
            released = capture('release-unknown')
            case.assertEqual('Unknown', unknown['outcome']['contract_type'])
            case.assertEqual([1, 1, 0], [a - b for a, b in zip(
                released['executor_counters'], before_release['executor_counters'], strict=True)])
            case.assertNotEqual(before_release['physical']['state_root'], released['physical']['state_root'])
            case.assertEqual('RELEASED', released['head']['in_flight']['phase'])
            case.assertIsNone(released['tasks'][release['task_id']]['intent']['resolution'])
            after_release = settle(release, 'release')
            case.assertEqual(released['executor_counters'], after_release['executor_counters'])
            case.assertEqual(baseline['head']['generation'] + 1, after_release['head']['generation'])
            case.assertEqual(1, len(after_release['physical']['inventory']['receipts']))
            def unrelated(value):
                return [resource for resource in value['physical']['inventory']['resources']
                    if (resource['resource_type'], resource['resource_id'], resource['region'])
                    != (str(query.resource_type), query.resource_id, query.region)]
            case.assertEqual(unrelated(baseline), unrelated(after_release))
            proof['phase'] = 'BEFORE_EXPLICIT_REARM'
            with target.target_guard():
                rearm_domain = target.prepare_rearm(query)
            proof['rearm_domain'] = rearm_domain.to_dict()
            case.assertEqual(after_release['physical']['inventory'], rearm_domain.to_dict()['inventory'])
            case.assertEqual(sorted(receipt['receipt_hash'] for receipt in after_release['physical']['inventory']['receipts']),
                rearm_domain.to_dict()['release_receipt_hashes'])
            rearm = self._portable_task(5, rearm_domain)
            tasks.append(rearm)
            proof['operations']['rearm'] = rearm['facts']
            negatives('rearm-denials', [
                ('POLICY4_CANNOT_APPROVE_POLICY5', lambda: authorize(release_route, rearm,
                    Capability.OWNER_APPROVAL, rearm['nonce']), WarrantError, 'INVALID_TOOL_OPERATION'),
                ('POLICY4_CANNOT_DISPATCH_POLICY5', lambda: dispatch(release_route, rearm),
                    WarrantError, 'SESSION_INACTIVE'),
                ('POLICY4_NONCE_CANNOT_APPROVE_POLICY5', lambda: authorize(rearm_route, rearm,
                    Capability.OWNER_APPROVAL, release['nonce']), WarrantError, 'PORTABLE_REARM_NONCE_BINDING')])
            case.assertNotEqual(release['session_id'], rearm['session_id'])
            case.assertNotEqual(release['nonce'], rearm['nonce'])
            case.assertNotEqual(release['warrant'].digest(), rearm['warrant'].digest())
            before_rearm = capture('rearm-before')
            unknown = dispatch(rearm_route, rearm)
            proof['operations']['rearm']['unknown'] = unknown
            rearmed = capture('rearm-unknown')
            case.assertEqual('Unknown', unknown['outcome']['contract_type'])
            case.assertEqual([1, 1, 0], [a - b for a, b in zip(
                rearmed['executor_counters'], before_rearm['executor_counters'], strict=True)])
            case.assertEqual('RELEASED', rearmed['head']['in_flight']['phase'])
            case.assertIsNotNone(rearmed['head']['in_flight']['ack'])
            case.assertIsNone(rearmed['tasks'][rearm['task_id']]['intent']['resolution'])
            final = settle(rearm, 'rearm')
            case.assertEqual(rearmed['executor_counters'], final['executor_counters'])
            case.assertEqual(baseline['head']['generation'] + 2, final['head']['generation'])
            case.assertEqual(baseline['physical']['inventory']['resources'], final['physical']['inventory']['resources'])
            case.assertEqual(after_release['physical']['inventory']['receipts'], final['physical']['inventory']['receipts'])
            case.assertEqual(after_release['histories'][release['warrant'].digest()],
                final['histories'][release['warrant'].digest()])
            case.assertEqual(2, len(final['histories']))
            case.assertEqual(baseline['physical']['guard_identity'], final['physical']['guard_identity'])
            case.assertEqual(baseline['governor']['epoch'], final['governor']['epoch'])
            case.assertEqual(baseline['governor']['execution_capacity'], final['governor']['execution_capacity'])
            for key, value in baseline['governor']['reservations'].items():
                case.assertEqual(value, final['governor']['reservations'][key])
            new_entries = [entry for key, entry in final['governor']['reservations'].items()
                if key not in baseline['governor']['reservations']]
            case.assertEqual(4, len(new_entries))
            case.assertEqual((0, 10), (sum(entry['money_nano'] for entry in new_entries),
                sum(entry['risk_units'] for entry in new_entries)))
            case.assertEqual({'COMMITTED'}, {entry['state'] for entry in new_entries})
            case.assertEqual([2, 2, 0], final['executor_counters'])
            case.assertEqual(0, h.model_calls())
            case.assertEqual([], managed.job_observation())
            case.assertEqual((), h.coding_tasks.lifecycle_snapshot().work)
            case.assertEqual('ACTIVE', f.lifecycle.phase.value)
            f.require_bindings()
            proof['phase'] = 'COMPLETE'
        finally:
            self.retained['portable'] = self.legacy_capacity_save('native-portable-flow-proof.json', proof)

    def _portable_a6_release_domain(self):
        import json
        from datetime import UTC, datetime, timedelta

        from nonzero_cloudops.adapters.portable import PortableResourceReader
        from nonzero_cloudops.investigation import QueryResource
        from nonzero_cloudops.models import (
            BudgetCounters,
            LocalApprovalRequestRecord,
            ProposalState,
            RemediationOperation,
            RemediationProposal,
            ResourceQuery,
            Run,
            generate_proposal_id,
            generate_run_id,
            generate_trace_id,
        )
        from nonzero_cloudops.models.public_enums import AuthorityGate
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import (
            canonical_json_bytes,
            canonical_sha256,
        )
        from runtime.mission.portable_target import PortableDomainInput

        h = self.host
        with h._native_coding.authority(Capability.READ) as principal:
            actor = principal.actor_session_id
        now = datetime.now(UTC)
        query = ResourceQuery(**self.body['portable']['resource_query'])
        run = Run.new(run_id=generate_run_id(), trace_id=generate_trace_id(),
            correlation_id=generate_run_id(), idempotency_key='native-portable-a6-release-once',
            created_at=now, budget=BudgetCounters(max_turns=1, max_tokens=1))
        with h.portable_store.target_guard():
            evidence = QueryResource(PortableResourceReader(h.portable_store)).execute(
                query, run=run, observed_at=now).value
            self.case.assertIsNotNone(evidence)
            proposal = RemediationProposal.create(proposal_id=generate_proposal_id(), evidence=evidence,
                operation_type=RemediationOperation.RELEASE_ELASTIC_IP,
                normalized_parameters={'allocation_id': query.resource_id},
                authority_class=AuthorityGate.PLAN_AND_CONFIRM, risk_summary='One owned Native A6 boundary',
                created_at=now, expires_at=now + timedelta(seconds=180))
            proposal = proposal.model_copy(update={'status': ProposalState.AWAITING_APPROVAL})
            request = LocalApprovalRequestRecord.create(request_id=generate_proposal_id(), proposal=proposal,
                actor_session_id=actor, decision_nonce_hash=canonical_sha256('native-portable-release-decision'),
                requested_at=now, expires_at=now + timedelta(seconds=120))
            inventory = h.portable_store.observe_guarded_inventory()
            return query, PortableDomainInput(canonical_json_bytes({'schema': 'aioa.portable-domain-input.v1',
                'proposal': proposal.model_dump(mode='json'), 'evidence': evidence.model_dump(mode='json'),
                'request': request.model_dump(mode='json'), 'inventory': json.loads(inventory.canonical_state)}))

    def _portable_a6_snapshot(self, tasks):
        import base64
        import hashlib
        import json
        import stat

        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION

        snapshot = self._portable_snapshot(tasks)
        store = self.host.portable_store
        with store.target_guard():
            raw = self.context['safe'].read(store.path)
            info = self.context['safe'].info(store.path)
        envelope = json.loads(raw)
        material = {name: envelope[name] for name in ('integrity_version', 'payload_type', 'payload')}
        snapshot['raw_inventory'] = {'path': str(store.path), 'bytes': len(raw),
            'raw_b64': base64.b64encode(raw).decode(), 'sha256': hashlib.sha256(raw).hexdigest(),
            'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'nlink': info.st_nlink,
            'envelope': envelope, 'material_sha256': hashlib.sha256(canonical_json_bytes(material)).hexdigest(),
            'payload_equals_held_guard_observation': envelope['payload'] == snapshot['physical']['inventory']}
        snapshot['snapshot_outside_SQL'] = not bool(_IN_TRANSACTION.get())
        return snapshot

    def portable_boundary_assertions(self, case, scenario):
        import json
        import traceback
        from unittest.mock import patch

        from nonzero_cloudops.adapters import portable
        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        from runtime.memory_patch.persistence.ports import (
            _IN_TRANSACTION,
            LocalCoreTransaction,
            RecordKind,
        )
        from runtime.mission.portable_target import CorePortableTarget
        from runtime.mission.warrant import WarrantError

        case.assertIn(scenario, ('STOP', 'EXEC_ACK', 'COMMIT_ACK'))
        h, f, managed = self.host, self.host.foundation, self.host._native_coding
        target = h.portable_target
        tasks, cuts = [], []
        proof = {'schema': 'nz13.native-portable-A6-boundary.v1', 'scenario': scenario,
            'phase': 'INITIAL', 'model_certification': 'NOT_CERTIFIED', 'snapshots': {},
            'operations': {}, 'calls': {}, 'cuts': cuts, 'qualification': False}
        def capture(name):
            observed = self._portable_a6_snapshot(tasks)
            proof['snapshots'][name] = self.legacy_capacity_save('portable-a6-' + name + '.json', observed)
            return observed
        def error_facts(error):
            result, seen = [], set()
            while error is not None and id(error) not in seen and len(result) < 8:
                seen.add(id(error))
                result.append({'type': type(error).__name__, 'module': type(error).__module__, 'code': str(error),
                    'frames': [{'file': frame.filename, 'function': frame.name, 'line': frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__, limit=32)]})
                error = error.__cause__ if error.__cause__ is not None else error.__context__
            return result
        def invoke(name, callback):
            try:
                observed = {'returned': True, 'value': callback()}
            except (AdmissionError, WarrantError, CommitOutcomeUnknown) as error:
                observed = {'returned': False, 'errors': error_facts(error)}
            proof['calls'][name] = observed
            return observed
        def dispatch(task):
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].dispatch(principal, session_id=task['session_id'],
                    warrant=task['warrant'], operation=task['operation'], reservation=task['reservation'],
                    completion=task['completion'])
        def reconcile(task):
            with managed.authority(Capability.READ) as principal:
                epoch = f.governor.inspect(principal)['epoch']
            proof['current_reconcile_epoch'] = epoch
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].reconcile(principal, task['warrant'], epoch)
        def finish(task):
            with managed.authority(Capability.COMMIT) as principal:
                return f.governor.finish_offline_host_job(principal, task['claim'])
        def check_raw(value):
            raw = value['raw_inventory']
            case.assertIs(True, value['snapshot_outside_SQL'])
            case.assertIs(True, raw['payload_equals_held_guard_observation'])
            case.assertEqual(raw['envelope']['payload_sha256'], raw['material_sha256'])
            case.assertEqual((0o600, 1), (raw['mode'], raw['nlink']))
        try:
            baseline = capture('baseline')
            query, domain = self._portable_a6_release_domain()
            release = self._portable_task(4, domain)
            tasks.append(release)
            proof['operations']['release'] = release['facts']
            seed = None
            if scenario != 'STOP':
                invoke('release_dispatch', lambda: dispatch(release))
                capture('release-unknown')
                applied = invoke('release_reconcile', lambda: reconcile(release))
                finished = invoke('release_finish', lambda: finish(release))
                seed = capture('release-settled')
                case.assertIs(True, applied['returned'])
                case.assertEqual('Applied', applied['value']['outcome']['contract_type'])
                case.assertIs(True, finished['returned'])
                case.assertEqual('DONE', finished['value']['state'])
                with target.target_guard():
                    rearm_domain = target.prepare_rearm(query)
                proof['rearm_domain'] = rearm_domain.to_dict()
                task = self._portable_task(5, rearm_domain)
                tasks.append(task)
                proof['operations']['rearm'] = task['facts']
            else:
                task = release
            before = capture('before-cut')
            proof['phase'] = 'DISPATCH_BOUNDARY'
            if scenario == 'STOP':
                original_seal = portable.seal_local_payload
                def stop_after_original_seal(*args, **kwargs):
                    result = original_seal(*args, **kwargs)
                    if not cuts:
                        cuts.append({'boundary': 'ORIGINAL_SEAL_RETURNED_BEFORE_AUTHORIZE_WRITE',
                            'inside_SQL': bool(_IN_TRANSACTION.get()), 'original_called_once': True})
                        with managed.authority(Capability.MANAGE) as principal:
                            cuts[-1]['kill_result'] = f.governor.set_kill(principal, True)
                    return result
                with patch.object(portable, 'seal_local_payload', new=stop_after_original_seal):
                    dispatched = invoke('cut_dispatch', lambda: dispatch(task))
            elif scenario == 'EXEC_ACK':
                original_dispatch = CorePortableTarget.dispatch
                def lose_executor_ack(adapter, operation, warrant, limits, release_port):
                    acknowledgment = original_dispatch(adapter, operation, warrant, limits, release_port)
                    if adapter is target and warrant == task['warrant'] and not cuts:
                        cuts.append({'boundary': 'ORIGINAL_PHYSICAL_DISPATCH_RETURNED_BEFORE_RECORD_ACK',
                            'inside_SQL': bool(_IN_TRANSACTION.get()), 'original_called_once': True,
                            'warrant_digest': warrant.digest(),
                            'original_ack': json.loads(canonical_json_bytes(acknowledgment))})
                        raise CommitOutcomeUnknown()
                    return acknowledgment
                with patch.object(CorePortableTarget, 'dispatch', new=lose_executor_ack):
                    dispatched = invoke('cut_dispatch', lambda: dispatch(task))
            else:
                original_commit = LocalCoreTransaction.commit
                def lose_committed_ack(tx):
                    row = tx.get(RecordKind.OPERATION, f.target_projection.head_key)
                    flight = None if row is None else row.payload['in_flight']
                    selected = (flight is not None and flight['warrant_digest'] == task['warrant'].digest()
                        and flight['phase'] == 'RELEASED' and flight['ack'] is not None
                        and tx.context.purpose is Capability.COMMIT)
                    result = original_commit(tx)
                    if selected and not cuts:
                        cuts.append({'boundary': 'ORIGINAL_COMMIT_RETURNED_WITH_DURABLE_EXECUTION_ACK',
                            'inside_SQL_context_after_commit': bool(_IN_TRANSACTION.get()),
                            'original_called_once': True, 'warrant_digest': task['warrant'].digest(),
                            'original_ack': json.loads(canonical_json_bytes(flight['ack']))})
                        raise CommitOutcomeUnknown()
                    return result
                with patch.object(LocalCoreTransaction, 'commit', new=lose_committed_ack):
                    dispatched = invoke('cut_dispatch', lambda: dispatch(task))
            after = capture('after-cut')
            with managed.authority(Capability.READ) as principal:
                proof['calls']['inspect_after_cut'] = task['route'].inspect(principal, task['warrant'])
            if scenario == 'EXEC_ACK':
                readback = invoke('reconcile_missing_ack', lambda: reconcile(task))
                after_readback = capture('after-reconcile-refusal')
            elif scenario == 'COMMIT_ACK':
                readback = invoke('reconcile_durable_ack', lambda: reconcile(task))
                finished = invoke('finish_durable_ack', lambda: finish(task))
                after_readback = capture('after-reconcile-finish')
            else:
                after_readback = after
                proof['no_release_witness_not_requested'] = True
            replay = invoke('retained_dispatch', lambda: dispatch(task))
            final = capture('after-retained-dispatch')
            proof['phase'] = 'ALL_ACTUAL_FACTS_SAVED_BEFORE_QUALIFICATION'
            case.assertEqual(1, len(cuts))
            for observed in (baseline, before, after, after_readback, final):
                check_raw(observed)
            joined = after['tasks'][task['task_id']]
            case.assertEqual('Unknown', joined['intent']['outcome']['contract_type'])
            case.assertIsNone(joined['intent']['resolution'])
            case.assertEqual('STARTED', joined['job']['state'])
            case.assertIsNone(joined['job']['completion_proof'])
            case.assertEqual('Unknown', proof['calls']['inspect_after_cut']['outcome']['contract_type'])
            case.assertEqual(before['head']['generation'], after['head']['generation'])
            case.assertEqual(before['physical']['guard_identity'], final['physical']['guard_identity'])
            case.assertEqual(after_readback['canonical_rows'], final['canonical_rows'])
            case.assertEqual(after_readback['raw_inventory'], final['raw_inventory'])
            case.assertEqual(after['executor_counters'], final['executor_counters'])
            case.assertIs(True, replay['returned'])
            if scenario == 'STOP':
                case.assertIs(False, cuts[0]['inside_SQL'])
                case.assertIs(True, after['governor']['kill'])
                case.assertIs(True, final['governor']['kill'])
                case.assertEqual(before['raw_inventory'], after['raw_inventory'])
                case.assertEqual([1, 0, 0], [a - b for a, b in zip(
                    after['executor_counters'], before['executor_counters'], strict=True)])
                case.assertEqual('STARTED', after['head']['in_flight']['phase'])
                case.assertIsNone(after['head']['in_flight']['write_observation'])
                case.assertEqual('Unknown', replay['value']['outcome']['contract_type'])
                if dispatched['returned']:
                    case.assertEqual('Unknown', dispatched['value']['outcome']['contract_type'])
                else:
                    case.assertIn((dispatched['errors'][0]['type'], dispatched['errors'][0]['code']),
                        (('AdmissionError', 'CORE_ADMISSION_DENIED'), ('WarrantError', 'KILL_SWITCH')))
            else:
                case.assertIs(False, dispatched['returned'])
                case.assertEqual(('CommitOutcomeUnknown', 'RECOVERY_REQUIRED'),
                    (dispatched['errors'][0]['type'], dispatched['errors'][0]['code']))
                case.assertEqual([1, 1, 0], [a - b for a, b in zip(
                    after['executor_counters'], before['executor_counters'], strict=True)])
                case.assertNotEqual(before['physical']['state_root'], after['physical']['state_root'])
                case.assertEqual('RELEASED', after['head']['in_flight']['phase'])
                case.assertEqual(seed['tasks'][release['task_id']], final['tasks'][release['task_id']])
                case.assertEqual(seed['histories'][release['warrant'].digest()],
                    final['histories'][release['warrant'].digest()])
                case.assertEqual(seed['physical']['inventory']['receipts'], final['physical']['inventory']['receipts'])
                if scenario == 'EXEC_ACK':
                    case.assertIs(False, cuts[0]['inside_SQL'])
                    case.assertIsNone(after['head']['in_flight']['ack'])
                    case.assertIs(False, readback['returned'])
                    case.assertEqual(('WarrantError', 'INDEPENDENT_READBACK_UNAVAILABLE'),
                        (readback['errors'][0]['type'], readback['errors'][0]['code']))
                    case.assertIn('PORTABLE_REARM_DURABLE_EXECUTION_ACK_REQUIRED',
                        [value['code'] for value in readback['errors']])
                    case.assertEqual(after['canonical_rows'], after_readback['canonical_rows'])
                    case.assertEqual('Unknown', replay['value']['outcome']['contract_type'])
                    case.assertEqual('STARTED', final['tasks'][task['task_id']]['job']['state'])
                    case.assertIsNone(final['tasks'][task['task_id']]['intent']['resolution'])
                else:
                    case.assertIsNotNone(after['head']['in_flight']['ack'])
                    case.assertIs(True, readback['returned'])
                    case.assertEqual('Applied', readback['value']['outcome']['contract_type'])
                    case.assertIs(True, finished['returned'])
                    case.assertEqual('DONE', finished['value']['state'])
                    case.assertEqual('NOT_CERTIFIED', finished['value']['worker_certification'])
                    case.assertIsNotNone(finished['value']['completion_proof'])
                    case.assertEqual('Applied', replay['value']['outcome']['contract_type'])
                    case.assertIsNone(final['head']['in_flight'])
                    case.assertEqual(before['head']['generation'] + 1, final['head']['generation'])
                    for name in ('state_root', 'resources_root', 'receipts_root'):
                        case.assertEqual(final['physical'][name], final['head'][name])
            case.assertEqual(0, h.model_calls())
            proof['phase'] = 'COMPLETE'
        finally:
            self.retained['portable_a6'] = self.legacy_capacity_save('native-portable-a6-proof.json', proof)

    def _portable_no_release_snapshot(self, tasks):
        import json

        from runtime.core_admission import Capability
        from runtime.memory_patch.adapters.cockroach.repositories import (
            canonical_record,
        )
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import RecordKind

        value = self._portable_a6_snapshot(tasks)
        def read(tx):
            records = {}
            for kind in RecordKind:
                rows = tx.scan(kind, limit=1024)
                self.case.assertLess(len(rows), 1024)
                for row in rows:
                    row.verify()
                    records[kind.value + ':' + row.record_id] = {
                        'revision': row.revision, 'payload_digest': row.payload_digest,
                        'payload': row.payload, 'canonical_record': canonical_record(row)}
            return json.loads(canonical_json_bytes(records))
        with self.host._native_coding.authority(Capability.READ) as principal:
            value['full_canonical_rows'] = self.host.portable_release_route._run(
                principal, Capability.READ, read)
        value['full_rows_match_summary'] = value['canonical_rows'] == {
            key: {'revision': row['revision'], 'payload_digest': row['payload_digest']}
            for key, row in value['full_canonical_rows'].items()}
        return value

    def portable_no_release_assertions(self, case, scenario):
        import hashlib
        import json
        import traceback
        from unittest.mock import patch

        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import (
            canonical_json_bytes,
            canonical_sha256,
        )
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        from runtime.memory_patch.persistence.ports import (
            _IN_TRANSACTION,
            LocalCoreTransaction,
            RecordKind,
        )
        from runtime.mission.liability import Reconciliation
        from runtime.mission.portable_target import (
            CorePortableTarget,
            CorePortableWriteRelease,
        )
        from runtime.mission.warrant import WarrantError

        case.assertIn(scenario, ('START_ACK', 'SESSION_REVOKE'))
        h, f, managed = self.host, self.host.foundation, self.host._native_coding
        target = h.portable_target
        tasks, cuts, witnesses = [], [], []
        proof = {'schema': 'nz13.native-portable-fresh-no-release.v1', 'scenario': scenario,
            'phase': 'INITIAL', 'snapshots': {}, 'calls': {}, 'cuts': cuts,
            'live_original_witnesses': witnesses, 'model_certification': 'NOT_CERTIFIED',
            'qualification': False, 'finish_not_called_because_required_goal_NotApplied': True}
        def capture(name):
            value = self._portable_no_release_snapshot(tasks)
            proof['snapshots'][name] = self.legacy_capacity_save(
                'portable-no-release-' + name + '.json', value)
            return value
        def errors(error):
            chain, seen = [], set()
            while error is not None and id(error) not in seen and len(chain) < 8:
                seen.add(id(error))
                chain.append({'type': type(error).__name__, 'module': type(error).__module__,
                    'code': str(error), 'frames': [{'file': item.filename, 'function': item.name,
                        'line': item.lineno} for item in traceback.extract_tb(error.__traceback__, limit=32)]})
                error = error.__cause__ if error.__cause__ is not None else error.__context__
            return chain
        def invoke(name, callback, *, lost_start=False, independent_readback=False):
            try:
                value = {'returned': True, 'value': callback()}
            except CommitOutcomeUnknown as error:
                proof['calls'][name] = {'returned': False, 'errors': errors(error)}
                if not lost_start:
                    raise
                return proof['calls'][name]
            except WarrantError as error:
                proof['calls'][name] = {'returned': False, 'errors': errors(error)}
                if not independent_readback or str(error) != 'INDEPENDENT_READBACK_UNAVAILABLE':
                    raise
                return proof['calls'][name]
            proof['calls'][name] = value
            return value
        def dispatch(task):
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].dispatch(principal, session_id=task['session_id'],
                    warrant=task['warrant'], operation=task['operation'],
                    reservation=task['reservation'], completion=task['completion'])
        def reconcile(task):
            with managed.authority(Capability.READ) as principal:
                epoch = f.governor.inspect(principal)['epoch']
            proof.setdefault('actual_reconcile_epochs', []).append(epoch)
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].reconcile(principal, task['warrant'], epoch)
        try:
            baseline = capture('baseline')
            _, domain = self._portable_a6_release_domain()
            task = self._portable_task(4, domain)
            tasks.append(task)
            proof['operation'] = task['facts']
            before = capture('before-cut')
            proof['phase'] = 'ORIGINAL_DISPATCH_CUT'
            if scenario == 'START_ACK':
                original_commit = LocalCoreTransaction.commit
                def lose_original_started_ack(tx):
                    row = tx.get(RecordKind.OPERATION, f.target_projection.head_key)
                    flight = None if row is None else row.payload['in_flight']
                    selected = (tx.context.purpose is Capability.COMMIT and flight is not None
                        and flight['warrant_digest'] == task['warrant'].digest()
                        and flight['phase'] == 'STARTED' and flight['write_observation'] is None
                        and flight['ack'] is None)
                    result = original_commit(tx)
                    if selected and not cuts:
                        cuts.append({'boundary': 'ORIGINAL_START_COMMIT_RETURNED_BEFORE_START_ACK_RETURN',
                            'original_commit_called_once': True,
                            'inside_SQL_context_after_original_commit': bool(_IN_TRANSACTION.get()),
                            'original_flight': json.loads(canonical_json_bytes(flight))})
                        raise CommitOutcomeUnknown()
                    return result
                with patch.object(LocalCoreTransaction, 'commit', new=lose_original_started_ack):
                    dispatched = invoke('cut_dispatch', lambda: dispatch(task), lost_start=True)
            else:
                original_authorize = CorePortableWriteRelease.authorize_write
                def revoke_before_original_authorize(release, store, observed, candidate):
                    selected = (release.adapter is target and store is h.portable_store
                        and release.warrant == task['warrant'] and not cuts)
                    if not selected:
                        return original_authorize(release, store, observed, candidate)
                    cut = {'boundary': 'ORIGINAL_SEAL_RETURNED_AT_AUTHORIZE_WRITE_ENTRY',
                        'inside_SQL': bool(_IN_TRANSACTION.get()), 'original_authorize_calls': 0,
                        'warrant_digest': release.warrant.digest(),
                        'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
                        'before_state_root': observed.state_root,
                        'caller_frames': [{'file': item.filename, 'function': item.name,
                            'line': item.lineno} for item in traceback.extract_stack(limit=24)]}
                    cuts.append(cut)
                    with managed.authority(Capability.MANAGE) as principal:
                        cut['original_revoke_result'] = task['route'].revoke_session(
                            principal, task['session_id'])
                    cut['original_authorize_calls'] += 1
                    try:
                        return original_authorize(release, store, observed, candidate)
                    except WarrantError as error:
                        cut['original_authorize_errors'] = errors(error)
                        raise
                with patch.object(CorePortableWriteRelease, 'authorize_write',
                        new=revoke_before_original_authorize):
                    dispatched = invoke('cut_dispatch', lambda: dispatch(task))
            after = capture('after-cut')
            proof['prior_write_lifetime_exited'] = {
                'no_active_write_port': getattr(h.portable_store._held_lock, 'write_release', None) is None,
                'no_old_Core_guard_capture': getattr(
                    h.portable_store._held_lock, 'core_no_release_capture', None) is None}
            original_verify = CorePortableTarget._verify_no_release
            def observe_original_live_no_release(adapter, operation, warrant):
                verified = original_verify(adapter, operation, warrant)
                if adapter is target and warrant == task['warrant']:
                    witness, certificate = verified._witness, verified.certificate
                    captured = witness.capture
                    witnesses.append({'outside_SQL': not bool(_IN_TRANSACTION.get()),
                        'result_type': type(verified).__name__, 'witness_type': type(witness).__name__,
                        'original_called_once': True, 'same_certificate_object': witness.certificate is certificate,
                        'same_adapter': captured.adapter is target,
                        'same_projection': adapter.projection is f.target_projection,
                        'current_guard_capture': getattr(adapter.store._held_lock,
                            'core_no_release_capture', None) is captured,
                        'owns_outer_guard': captured.entry.owns_outer_lock,
                        'no_active_write_port': getattr(adapter.store._held_lock, 'write_release', None) is None,
                        'head_revision': captured.head_revision, 'intent_revision': captured.intent_revision,
                        'captured_head': json.loads(captured.head_bytes),
                        'captured_intent': json.loads(captured.intent_bytes),
                        'consumption_digest': captured.consumption_digest,
                        'liability_id': captured.liability_id, 'certificate': certificate.to_dict()})
                return verified
            proof['phase'] = 'FRESH_PUBLIC_RECONCILIATION'
            with patch.object(CorePortableTarget, '_verify_no_release', new=observe_original_live_no_release):
                settled = invoke('fresh_no_release', lambda: reconcile(task), independent_readback=True)
            after_settle = capture('after-fresh-reconcile')
            if settled['returned']:
                invoke('retained_reconcile', lambda: reconcile(task))
                invoke('retained_dispatch', lambda: dispatch(task))
            else:
                proof['retained_controls_not_run'] = 'FIRST_FRESH_NO_RELEASE_DID_NOT_RETURN_NO_RETRY'
            final = capture('after-retained-controls')
            proof['phase'] = 'ALL_ACTUAL_FACTS_SAVED_BEFORE_QUALIFICATION'
            case.assertEqual(1, len(cuts))
            for value in (baseline, before, after, after_settle, final):
                case.assertIs(True, value['full_rows_match_summary'])
                case.assertIs(True, value['snapshot_outside_SQL'])
                case.assertEqual(value['raw_inventory']['envelope']['payload_sha256'],
                    value['raw_inventory']['material_sha256'])
            joined = after['tasks'][task['task_id']]
            case.assertEqual('Unknown', joined['intent']['outcome']['contract_type'])
            case.assertIsNone(joined['intent']['resolution'])
            case.assertEqual('STARTED', after['head']['in_flight']['phase'])
            case.assertIsNone(after['head']['in_flight']['write_observation'])
            case.assertIsNone(after['head']['in_flight']['ack'])
            case.assertEqual(before['raw_inventory'], after['raw_inventory'])
            case.assertTrue(all(proof['prior_write_lifetime_exited'].values()))
            if scenario == 'START_ACK':
                case.assertIs(False, dispatched['returned'])
                case.assertEqual(('CommitOutcomeUnknown', 'RECOVERY_REQUIRED'),
                    (dispatched['errors'][0]['type'], dispatched['errors'][0]['code']))
                expected_delta = [0, 0, 0]
            else:
                case.assertIs(True, dispatched['returned'])
                case.assertEqual('Unknown', dispatched['value']['outcome']['contract_type'])
                case.assertIs(False, cuts[0]['inside_SQL'])
                case.assertEqual(1, cuts[0]['original_authorize_calls'])
                case.assertEqual(('WarrantError', 'SESSION_INACTIVE'),
                    (cuts[0]['original_authorize_errors'][0]['type'],
                     cuts[0]['original_authorize_errors'][0]['code']))
                case.assertIs(True, joined['session']['revoked'])
                expected_delta = [1, 0, 0]
            case.assertEqual(expected_delta, [a - b for a, b in zip(
                after['executor_counters'], before['executor_counters'], strict=True)])
            case.assertTrue(settled['returned'], 'NATIVE_PORTABLE_FRESH_FENCED_NO_RELEASE_REQUIRED')
            case.assertEqual('NotApplied', settled['value']['outcome']['contract_type'])
            case.assertIs(False, settled['value']['grants_replay'])
            case.assertEqual('NONE', settled['value']['authority'])
            case.assertEqual(1, len(witnesses))
            witness = witnesses[0]
            for name in ('outside_SQL', 'original_called_once', 'same_certificate_object', 'same_adapter',
                    'same_projection', 'current_guard_capture', 'owns_outer_guard', 'no_active_write_port'):
                case.assertIs(True, witness[name])
            case.assertEqual('VerifiedNoReleaseSettlement', witness['result_type'])
            case.assertEqual('_PortableNoReleaseWitness', witness['witness_type'])
            case.assertEqual(after['head_record']['revision'], witness['head_revision'])
            case.assertEqual(after['head'], witness['captured_head'])
            case.assertEqual(joined['intent'], witness['captured_intent'])
            certificate = witness['certificate']
            history = after_settle['histories'][task['warrant'].digest()]
            case.assertEqual('aioa-core-target-history-portable-no-release.v1', history['schema'])
            case.assertEqual(certificate, history['no_release_certificate'])
            case.assertNotIn('write_observation', history)
            case.assertEqual('no-effect-certificate', history['resolution']['receipt']['kind'])
            case.assertEqual(task['warrant'].digest(), certificate['warrant_digest'])
            case.assertEqual(canonical_sha256(after['head']), certificate['head_digest'])
            case.assertEqual(canonical_sha256(joined['intent']), certificate['intent_digest'])
            case.assertEqual(canonical_sha256(f.ledger._receipt(task['warrant'])), certificate['consumption_digest'])
            case.assertEqual(after['head']['generation'] + 1, after_settle['head']['generation'])
            case.assertEqual(after['head_record']['revision'] + 1, after_settle['head_record']['revision'])
            case.assertIsNone(after_settle['head']['in_flight'])
            for name in ('state_root', 'resources_root', 'receipts_root', 'guard_fingerprint'):
                case.assertEqual(after['physical'][name], certificate[name])
                case.assertEqual(after['physical'][name], after_settle['physical'][name])
            case.assertEqual(after['raw_inventory'], after_settle['raw_inventory'])
            settled_task = after_settle['tasks'][task['task_id']]
            for name in ('job', 'session', 'context', 'ledger', 'owner_witness'):
                case.assertEqual(joined[name], settled_task[name])
            case.assertEqual('STARTED', settled_task['job']['state'])
            case.assertIsNone(settled_task['job']['completion_proof'])
            entry = settled_task['liability']['entries'][witness['liability_id']]
            case.assertEqual('CLOSED', entry['record']['status'])
            case.assertEqual('NotApplied', entry['resolution']['outcome']['contract_type'])
            expected_governor = json.loads(canonical_json_bytes(after['governor']))
            expected_governor['version'] += 1
            case.assertGreaterEqual(after_settle['governor']['last_now'], expected_governor['last_now'])
            expected_governor['last_now'] = after_settle['governor']['last_now']
            risk_id = task['warrant'].risk_reservation_id
            case.assertEqual('UNKNOWN', expected_governor['reservations'][risk_id]['state'])
            expected_governor['reservations'][risk_id].update(state='COMMITTED',
                evidence_digest=canonical_sha256(
                    Reconciliation.from_dict(settled_task['intent']['resolution'])))
            case.assertEqual(expected_governor, after_settle['governor'])
            old_rows, new_rows = after['full_canonical_rows'], after_settle['full_canonical_rows']
            changed = {key for key in old_rows.keys() & new_rows.keys() if old_rows[key] != new_rows[key]}
            inserted = new_rows.keys() - old_rows.keys()
            case.assertFalse(old_rows.keys() - new_rows.keys())
            intent_key = f.intent_journal._key(task['warrant'])
            case.assertEqual({RecordKind.OPERATION.value + ':' + f.target_projection.head_key,
                RecordKind.OPERATION.value + ':' + f.liability._key(task['task_id']),
                RecordKind.OPERATION.value + ':' + intent_key,
                RecordKind.OUTBOX.value + ':' + intent_key}, changed)
            case.assertEqual(4, len(inserted))
            case.assertEqual(sorted([RecordKind.OPERATION.value, RecordKind.OPERATION.value,
                RecordKind.AUDIT.value, RecordKind.OUTBOX.value]), sorted(key.split(':', 1)[0] for key in inserted))
            case.assertIn(RecordKind.OPERATION.value + ':' + f.target_projection.history_key(task['warrant']), inserted)
            case.assertIn(RecordKind.OPERATION.value + ':' + f.governor._key(after_settle['governor']['version']), inserted)
            case.assertEqual(after_settle['full_canonical_rows'], final['full_canonical_rows'])
            case.assertEqual(after_settle['raw_inventory'], final['raw_inventory'])
            case.assertEqual(after['executor_counters'], final['executor_counters'])
            for name in ('retained_reconcile', 'retained_dispatch'):
                case.assertIs(True, proof['calls'][name]['returned'])
                case.assertEqual('NotApplied', proof['calls'][name]['value']['outcome']['contract_type'])
                case.assertIs(False, proof['calls'][name]['value']['grants_replay'])
            case.assertEqual(0, h.model_calls())
            proof['phase'] = 'COMPLETE'
        finally:
            self.retained['portable_no_release'] = self.legacy_capacity_save(
                'native-portable-no-release-proof.json', proof)

    def adoption_warrant(self, owner, request):
        from dataclasses import replace
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal

        from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
        from lab.archaioa.decision_root import DecisionDependencyRoot
        from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.mission.warrant import approval_digest
        now = datetime.now(UTC)
        operation = request.operation()
        owner_digest = canonical_sha256(owner.ledger.scope)
        scope = AuthorityScope(operation_classes=('TARGET_ADOPT_EXISTING',), target_scope=operation['target_fingerprint'],
            risk_ceiling=RiskLevel.LOW, monetary_ceiling=Money(Decimal(0), 'USD'), not_before=now,
            expires_at=now + timedelta(minutes=1), owner_scope=owner_digest, task_scope='owned-adoption')
        warrant = EffectWarrant(warrant_id='owned-adoption', task_id='owned-adoption', owner_scope=owner_digest,
            operation_class=operation['operation_class'], operation_hash='sha256:' + canonical_sha256(operation),
            target_fingerprint=operation['target_fingerprint'], expected_target_revision=operation['expected_target_revision'],
            revision_policy=RevisionPolicy.REQUIRE,
            decision_dependency_root=DecisionDependencyRoot((request.binding.evidence(), request.evidence())),
            lease_epoch=request.epoch, authority_scope=scope, approval_digest='sha256:' + '0' * 64,
            money_reservation_id='NONE', risk_reservation_id='NONE', nonce='owned-adoption',
            issued_at=now, expires_at=now + timedelta(minutes=1))
        return replace(warrant, approval_digest=approval_digest(warrant))

    def inert_validation(self):
        import time
        from dataclasses import replace

        from runtime.meta_hackathon.native_coding import NativeStagePreparer
        from runtime.mission.repair_validation import CoreSandboxValidation
        from runtime.mission.sandbox_bindings import MaterializationBindingInput
        from runtime.mission.worker import WorkerSession
        from runtime.providers.exact import CancellationToken
        h = self.host._native_coding
        task = replace(self.task, task_id='inert-task', run_id='inert-run', deadline_at=int(time.time()) + 120)
        session = WorkerSession('inert-session', task.task_id, task.run_id, task.digest, 'offline-inert')
        candidate = self.candidates[-1]
        patch = h.profile.materialization_spec(h.base_root, source=h.spec.project_source,
            task=task, worker_session_id=session.session_id, candidate=candidate)[0]
        root = h.candidate_root / 'inert-advisory-data'
        root.mkdir(mode=0o700)
        files = dict(h.source_snapshot.files)
        files.update((file.path, file.text.encode()) for file in candidate.files)
        for name, raw in files.items():
            path = root / name
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o644)
        h.materializations[session.session_id] = MaterializationBindingInput(task, session, candidate)
        cancel = CancellationToken()
        preparer = NativeStagePreparer(h, task, cancel)
        validator = CoreSandboxValidation(self.host.intent_journal, stage_preparer=preparer,
                                         profile=h.profile, cancel=cancel, sandbox_jobs=True)
        return {'validator': validator, 'patchset': patch, 'root': root, 'cancel': cancel}

    def _stage_profile_restore_template(self, case):
        import hashlib
        import json
        from dataclasses import replace

        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.mission.sandbox_contracts import sandbox_input_limits
        from runtime.mission.sandbox_linux import (
            TrustedSandboxConfig,
            load_host_config,
            prepare_linux_sandbox,
            save_host_config,
        )

        h = self.host
        original = h.broker.config
        case.assertIs(type(original), TrustedSandboxConfig)
        profile_a = original.profile()
        case.assertIsNone(profile_a.get('input_profile'))
        case.assertEqual('ACTIVE', h.foundation.lifecycle.phase.value)
        seed_spec = h._native_coding.profile.materialization_spec(
            self.root / 'base', source=h.foundation.spec.project_source,
            task=self.task, worker_session_id=self.binding.session.session_id,
            candidate=self.candidates[0])[2]
        staged = prepare_linux_sandbox(self.root / 'cache/profile-restore-template',
            original.runtime(), workspace=original.registry.workspace,
            recipes={'0': seed_spec}, input_profile='PYTEST_WHEELS_V1')
        staged = replace(staged, registry=replace(staged.registry,
            recipes=tuple(replace(recipe, timeout_ms=original.registry.recipes[0].timeout_ms)
                          for recipe in staged.registry.recipes)))
        save_host_config(staged)
        loaded = load_host_config(staged.root, trusted_root=h.broker.binding_policy.trusted_root)
        case.assertIs(type(loaded), TrustedSandboxConfig)
        case.assertEqual(staged, loaded)
        expected_profile = dict(profile_a)
        expected_profile.update(input_profile='PYTEST_WHEELS_V1',
                                input_limits=dict(sandbox_input_limits('PYTEST_WHEELS_V1')))
        case.assertEqual(expected_profile, loaded.profile())
        case.assertEqual(canonical_sha256(loaded.profile()), loaded.profile_digest)
        case.assertNotEqual(original.profile_digest, loaded.profile_digest)
        raw_descriptor = self.context['safe'].read(loaded.root / 'host-config.json',
                                                    maximum=4 * 1024 * 1024)
        observation = {'schema': 'nz13.native-owned-profile-restore-template.v1',
            'qualification': False, 'scope': 'PHYSICAL_HOST_CONFIG_DRIFT_UNDER_UNCHANGED_ADMITTED_POLICY_A',
            'actual_prepare': 'runtime.mission.sandbox_linux.prepare_linux_sandbox',
            'actual_loaded_type': type(loaded).__module__ + '.' + type(loaded).__name__,
            'seed_root': str(original.root), 'template_root': str(loaded.root),
            'profile_a': profile_a, 'profile_b': loaded.profile(),
            'profile_a_digest': original.profile_digest, 'profile_b_digest': loaded.profile_digest,
            'changed_profile_fields': ['input_limits', 'input_profile'],
            'new_descriptor': {'path': str(loaded.root / 'host-config.json'),
                               'bytes': len(raw_descriptor),
                               'sha256': hashlib.sha256(raw_descriptor).hexdigest()},
            'source_and_recipe_unchanged': self.body['project_source'],
            'current_native_config': self.body,
            'current_native_config_digest': h.foundation.spec.digest,
            'template_registry': {'workspace': loaded.registry.workspace,
                                 'recipes': [recipe.payload(loaded.registry.workspace,
                                     self.task.task_id, 'profile-template')
                                             for recipe in loaded.registry.recipes]}}
        raw = json.dumps(observation, sort_keys=True).encode()
        case.assertLessEqual(len(raw), 4 * 1024 * 1024)
        output = self.root / 'native-profile-restore-template.json'
        self.context['safe'].write_new(output, raw)
        self.retained['profile_restore_template'] = {'path': str(output), 'bytes': len(raw),
                                                     'sha256': hashlib.sha256(raw).hexdigest()}
        return self.retained['profile_restore_template']

    def produce_profile_generation_restore_history(self, case):
        self._stage_profile_restore_template(case)
        return self.produce_terminal_acquisition_history(case)

    def stage_owned_startup_inputs(self):
        """Owned TLS/config data only, before the original producer uncertainty."""
        import hashlib
        import json
        from datetime import UTC, datetime, timedelta

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        self.case.assertEqual('aioa.native-host-composition.v1', self.body['schema'])
        now = datetime.now(UTC)
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'fixture.example.org')])
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=3))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('fixture.example.org')]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
        values = {
            'certificate': ('startup-owned-certificate.pem', certificate.public_bytes(serialization.Encoding.PEM)),
            'key': ('startup-owned-key.pem', key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption())),
            'host_spec': ('startup-host-composition.json', json.dumps(self.body, sort_keys=True).encode()),
        }
        refs = {}
        for kind, (name, raw) in values.items():
            path = self.root / name
            self.context['safe'].write_new(path, raw)
            self.case.assertEqual(raw, self.context['safe'].read(path))
            refs[kind] = {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        value = {'schema': 'nz13.native-owned-startup-bundle.v1', 'files': refs,
            'origin': self.origin, 'native_root': str(self.native_root),
            'host_config': self.body, 'host_source': list(self.host.source),
            'scope': 'FIXTURE_OS_ADMISSION_OWNED_CA_MODEL_NOT_CERTIFIED'}
        self.retained['startup_bundle'] = _native_startup_save(self.context, self.root / 'native-startup-bundle.json', value)
        return self.retained['startup_bundle']




    def portable_claim_expiry_in_final_store_guard_assertions(self, case):
        import hashlib
        import sys
        import time
        import traceback
        from unittest.mock import patch

        from nonzero_cloudops.adapters.portable import PortableStateStore

        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
        from runtime.mission.portable_target import CorePortableWriteRelease
        from runtime.mission.warrant import WarrantError

        h, f, managed = self.host, self.host.foundation, self.host._native_coding
        tasks, cuts, selected = [], [], {}
        proof = {'schema': 'nz13.native-portable-final-store-guard-claim-expiry.v1',
            'phase': 'INITIAL', 'snapshots': {}, 'cuts': cuts, 'calls': {},
            'dispatch_calls': 0, 'original_consume_calls': 0,
            'fixture_scope': 'FIXTURE_OS_ADMISSION_SYNTHETIC_TEST_ONLY',
            'claim_lease_seconds': 12, 'session_lease_seconds': 60,
            'real_wait_bound_seconds': 14, 'clock_monkeypatch': False,
            'policy_max_clock_step_seconds': f.governor.policy.max_clock_step_seconds,
            'model_certification': 'NOT_CERTIFIED', 'qualification': False,
            'no_new_warrant_after_cut': True, 'finish_offline_job_not_called': True}
        saved = False

        def diagnostic_time():
            return {'wall': time.time(), 'monotonic': time.monotonic()}

        def errors(error):
            values, seen = [], set()
            while error is not None and id(error) not in seen and len(values) < 8:
                seen.add(id(error))
                values.append({'type': type(error).__name__, 'module': type(error).__module__,
                    'code': str(error), 'frames': [{'file': item.filename, 'function': item.name,
                        'line': item.lineno} for item in traceback.extract_tb(error.__traceback__, limit=32)]})
                error = error.__cause__ if error.__cause__ is not None else error.__context__
            return values

        def capture(name):
            timing = {'name': name, 'snapshot_start': diagnostic_time()}
            proof.setdefault('diagnostic_timings', []).append(timing)
            value = self._portable_no_release_snapshot(tasks)
            timing['snapshot_end'] = diagnostic_time()
            proof['snapshots'][name] = self.legacy_capacity_save(
                'portable-final-store-guard-' + name + '.json', value)
            timing['save_end'] = diagnostic_time()
            return value

        def times(release):
            return {'wall': time.time(), 'monotonic': time.monotonic(),
                'governor_now': f.governor._now(), 'claim_until': task['claim'].lease_until,
                'session_until': task['facts']['grant']['expires_at'],
                'warrant_until': task['warrant'].expires_at.timestamp(),
                'envelope_until': task['facts']['envelope']['deadline_at'],
                'dispatch_principal_until': release.principal.expires_at.timestamp(),
                'host_auth_monotonic_until': h._auth_deadline,
                'TLS_until': h._tls_expires, 'TLS_verified': h.tls_verified}

        def other_deadlines_valid(value):
            return (all(value['wall'] < value[name] for name in (
                'session_until', 'warrant_until', 'envelope_until',
                'dispatch_principal_until', 'TLS_until'))
                and value['monotonic'] < value['host_auth_monotonic_until']
                and value['TLS_verified'] is True)

        def isolation_error(cut, reason):
            cut['isolation_error'] = reason
            proof['isolation_error'] = reason
            raise RuntimeError('NATIVE_FINAL_STORE_GUARD_FIXTURE_NOT_ISOLATED: ' + reason)

        def invoke(name, callback, *, independent=False):
            try:
                value = {'returned': True, 'value': callback()}
            except BaseException as error:
                value = {'returned': False, 'errors': errors(error)}
                proof['calls'][name] = value
                if not (independent and type(error) is WarrantError
                        and str(error) == 'INDEPENDENT_READBACK_UNAVAILABLE'):
                    raise
                return value
            proof['calls'][name] = value
            return value

        try:
            baseline = capture('baseline')
            _, domain = self._portable_a6_release_domain()
            task = self._portable_task(4, domain, claim_lease_seconds=12, session_lease_seconds=60)
            tasks.append(task)
            proof['operation'] = task['facts']
            before = capture('before-dispatch')
            original_consume = CorePortableWriteRelease.consume_write_ack
            original_guard = PortableStateStore._check_target_guard
            write_code = PortableStateStore._write.__code__

            def observe_consume(release, acknowledgment, store, observed, candidate):
                if not (release.adapter is h.portable_target and store is h.portable_store
                        and release.warrant is task['warrant']):
                    return original_consume(release, acknowledgment, store, observed, candidate)
                proof['original_consume_calls'] += 1
                selected.update(release=release, acknowledgment=acknowledgment,
                    store=store, observed=observed, candidate=candidate)
                proof['consume_entry'] = times(release)
                try:
                    value = original_consume(release, acknowledgment, store, observed, candidate)
                    selected['consume_returned'] = True
                    proof['original_consume_returned'] = True
                    return value
                except BaseException as error:
                    proof['original_consume_returned'] = False
                    proof['original_consume_errors'] = errors(error)
                    raise
                finally:
                    proof['consume_exit'] = times(release)
                    proof['ACK_after_original_consume'] = {
                        'same_release': acknowledgment.release is release,
                        'consumed': acknowledgment.consumed, 'release_consumed': release._consumed,
                        'write_observation': None if release._write_observation is None
                            else release._write_observation.to_dict()}

            def hold_final_guard(store):
                caller_is_write = sys._getframe(1).f_code is write_code
                if store is not h.portable_store or not caller_is_write:
                    return original_guard(store)
                cut = {'boundary': 'STORE_WRITE_FINAL_DIRECT_GUARD_AFTER_ORIGINAL_CONSUME',
                    'outside_SQL': not bool(_IN_TRANSACTION.get()), 'same_store': True,
                    'caller_exact_original_write_code': caller_is_write,
                    'original_guard_calls': 0, 'original_guard_returned': False}
                cuts.append(cut)
                if not selected or selected.get('consume_returned') is not True:
                    isolation_error(cut, 'original consume did not return before final Store guard')
                release, acknowledgment = selected['release'], selected['acknowledgment']
                entry = times(release)
                cut.update(entry=entry, candidate_sha256=hashlib.sha256(selected['candidate']).hexdigest(),
                    warrant_digest=release.warrant.digest(),
                    executor_counters_entry=list(h.portable_executor.counters()),
                    ACK_entry={'same_release': acknowledgment.release is release,
                        'consumed': acknowledgment.consumed, 'release_consumed': release._consumed,
                        'write_observation': None if release._write_observation is None
                            else release._write_observation.to_dict()})
                if (len(cuts) != 1 or proof['original_consume_calls'] != 1
                        or not cut['outside_SQL'] or not other_deadlines_valid(entry)
                        or not acknowledgment.consumed or not release._consumed
                        or acknowledgment.release is not release
                        or selected['store'] is not store
                        or release._write_observation is None
                        or not entry['wall'] < entry['claim_until']
                        or not entry['claim_until'] < min(entry[name] for name in (
                            'session_until', 'warrant_until', 'envelope_until',
                            'dispatch_principal_until'))):
                    isolation_error(cut, 'final guard entry not isolated with live consumed ACK')
                hold = {'reason': 'REAL_DELAY_INSIDE_FINAL_STORE_GUARD_UNTIL_ORIGINAL_CLAIM_EXPIRY',
                    'original_claim_until': task['claim'].lease_until, 'bound_seconds': 14,
                    'start': diagnostic_time()}
                cut['hold'] = hold
                try:
                    while time.time() < task['claim'].lease_until:
                        if time.monotonic() - hold['start']['monotonic'] >= 14:
                            isolation_error(cut, 'bounded final guard hold exceeded')
                        time.sleep(min(0.05, max(0.0, task['claim'].lease_until - time.time())))
                finally:
                    hold['end'] = diagnostic_time()
                    hold['actual_seconds'] = hold['end']['monotonic'] - hold['start']['monotonic']
                cut['after_hold'] = times(release)
                cut['executor_counters_after_hold'] = list(h.portable_executor.counters())
                cut['clock_guard'] = {'canonical_last_now_before_dispatch': before['governor']['last_now'],
                    'max_clock_step_seconds': f.governor.policy.max_clock_step_seconds,
                    'after_hold_governor_now': cut['after_hold']['governor_now']}
                cut['clock_guard']['actual_step_seconds'] = (
                    cut['clock_guard']['after_hold_governor_now']
                    - cut['clock_guard']['canonical_last_now_before_dispatch'])
                if (hold['actual_seconds'] > 14 or cut['after_hold']['governor_now'] < task['claim'].lease_until
                        or not other_deadlines_valid(cut['after_hold'])
                        or not 0 <= cut['clock_guard']['actual_step_seconds']
                            <= cut['clock_guard']['max_clock_step_seconds']):
                    isolation_error(cut, 'final guard hold did not isolate original claim expiry')
                cut['original_guard_calls'] += 1
                try:
                    value = original_guard(store)
                    cut['original_guard_returned'] = True
                    return value
                except BaseException as error:
                    cut['original_guard_errors'] = errors(error)
                    raise
                finally:
                    cut['guard_exit'] = times(release)
                    cut['executor_counters_guard_exit'] = list(h.portable_executor.counters())
                    cut['ACK_guard_exit'] = {'consumed': acknowledgment.consumed,
                        'release_consumed': release._consumed,
                        'write_observation': None if release._write_observation is None
                            else release._write_observation.to_dict()}
                    if not other_deadlines_valid(cut['guard_exit']):
                        cut['isolation_error'] = 'other authority expired during original final Store guard'
                        proof['isolation_error'] = cut['isolation_error']

            proof['phase'] = 'ORIGINAL_DISPATCH'
            with (patch.object(CorePortableWriteRelease, 'consume_write_ack', new=observe_consume),
                    patch.object(PortableStateStore, '_check_target_guard', new=hold_final_guard)):
                def dispatch():
                    proof['dispatch_calls'] += 1
                    with managed.authority(Capability.COMMIT) as principal:
                        return task['route'].dispatch(principal, session_id=task['session_id'],
                            warrant=task['warrant'], operation=task['operation'],
                            reservation=task['reservation'], completion=task['completion'])
                dispatched = invoke('dispatch', dispatch)
            after = capture('after-dispatch')
            if (proof.get('isolation_error') or len(cuts) != 1
                    or cuts[0]['original_guard_calls'] != 1 or not cuts[0]['original_guard_returned']):
                proof['phase'] = 'FIXTURE_ISOLATION_FAILED_NO_CAUSAL_RED_QUALIFICATION'
                raise RuntimeError('NATIVE_FINAL_STORE_GUARD_FIXTURE_NOT_ISOLATED')

            def reconcile():
                with managed.authority(Capability.READ) as principal:
                    epoch = f.governor.inspect(principal)['epoch']
                proof['actual_reconcile_epoch'] = epoch
                with managed.authority(Capability.COMMIT) as principal:
                    return task['route'].reconcile(principal, task['warrant'], epoch)
            settled = invoke('fresh_reconcile', reconcile, independent=True)
            final = capture('after-fresh-reconcile')
            proof['physical_delta'] = [a - b for a, b in zip(
                after['executor_counters'], before['executor_counters'], strict=True)]
            proof['phase'] = 'ALL_ACTUAL_FACTS_SAVED_BEFORE_QUALIFICATION'
            self.retained['portable_final_store_guard_claim_expiry'] = self.legacy_capacity_save(
                'native-portable-final-store-guard-claim-expiry-proof.json', proof)
            saved = True
            case.assertEqual([1, 0, 0], proof['physical_delta'],
                'NATIVE_PORTABLE_CLAIM_EXPIRED_IN_FINAL_STORE_GUARD_MUST_BLOCK_PHYSICAL_WRITE')
            cut = cuts[0]
            case.assertEqual(1, proof['dispatch_calls'])
            case.assertEqual(1, proof['original_consume_calls'])
            case.assertIs(True, proof['original_consume_returned'])
            case.assertIs(True, cut['ACK_entry']['consumed'])
            case.assertIs(True, cut['ACK_entry']['release_consumed'])
            case.assertIs(True, cut['ACK_guard_exit']['consumed'])
            case.assertIs(True, cut['ACK_guard_exit']['release_consumed'])
            case.assertEqual(cut['ACK_entry']['write_observation'], cut['ACK_guard_exit']['write_observation'])
            case.assertEqual(cut['executor_counters_entry'], cut['executor_counters_after_hold'])
            case.assertEqual(cut['executor_counters_entry'], cut['executor_counters_guard_exit'])
            case.assertEqual(before['raw_inventory'], after['raw_inventory'])
            for value in (baseline, before, after, final):
                case.assertIs(True, value['full_rows_match_summary'])
                case.assertIs(True, value['snapshot_outside_SQL'])
                case.assertEqual(value['raw_inventory']['envelope']['payload_sha256'],
                                 value['raw_inventory']['material_sha256'])
            case.assertEqual('RELEASED', after['head']['in_flight']['phase'])
            case.assertIsNotNone(after['head']['in_flight']['write_observation'])
            case.assertIsNone(after['head']['in_flight']['ack'])
            case.assertIs(True, dispatched['returned'])
            case.assertEqual('Unknown', dispatched['value']['outcome']['contract_type'])
            case.assertIs(False, settled['returned'])
            case.assertEqual('INDEPENDENT_READBACK_UNAVAILABLE', settled['errors'][0]['code'])
            case.assertEqual(after['full_canonical_rows'], final['full_canonical_rows'])
            case.assertEqual(after['raw_inventory'], final['raw_inventory'])
            case.assertEqual(after['executor_counters'], final['executor_counters'])
            joined = final['tasks'][task['task_id']]
            case.assertEqual('STARTED', joined['job']['state'])
            case.assertIsNone(joined['job']['completion_proof'])
            case.assertIsNone(joined['intent']['resolution'])
            case.assertEqual('UNKNOWN', final['governor']['reservations'][task['warrant'].risk_reservation_id]['state'])
            case.assertEqual(0, h.model_calls())
        finally:
            if not saved:
                self.retained['portable_final_store_guard_claim_expiry'] = self.legacy_capacity_save(
                    'native-portable-final-store-guard-claim-expiry-proof.json', proof)


    def portable_expired_claim_after_authorize_assertions(self, case, *, observer_delay=False):
        import hashlib
        import time
        import traceback
        from unittest.mock import patch

        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        from runtime.mission.portable_target import CorePortableWriteRelease
        from runtime.mission.warrant import WarrantError

        h, f, managed = self.host, self.host.foundation, self.host._native_coding
        tasks, cuts = [], []
        proof = {'schema': 'nz13.native-portable-claim-expiry.v1', 'phase': 'INITIAL',
            'snapshots': {}, 'cuts': cuts, 'calls': {}, 'dispatch_calls': 0,
            'fixture_scope': 'FIXTURE_OS_ADMISSION_SYNTHETIC_TEST_ONLY',
            'claim_lease_seconds': 12, 'session_lease_seconds': 60,
            'real_wait_bound_seconds': 14, 'clock_monkeypatch': False,
            'observer_delay_requested': observer_delay,
            'policy_max_clock_step_seconds': f.governor.policy.max_clock_step_seconds,
            'model_certification': 'NOT_CERTIFIED', 'qualification': False,
            'finish_offline_job_not_called': True, 'no_new_warrant_after_cut': True}
        def diagnostic_time():
            return {'wall': time.time(), 'monotonic': time.monotonic()}

        def capture(name):
            timing = {'name': name, 'snapshot_start': diagnostic_time()}
            proof.setdefault('diagnostic_timings', []).append(timing)
            value = self._portable_no_release_snapshot(tasks)
            timing['snapshot_end'] = diagnostic_time()
            timing['save_start'] = diagnostic_time()
            proof['snapshots'][name] = self.legacy_capacity_save(
                'portable-claim-expiry-' + name + '.json', value)
            timing['save_end'] = diagnostic_time()
            return value
        def errors(error):
            values, seen = [], set()
            while error is not None and id(error) not in seen and len(values) < 8:
                seen.add(id(error))
                values.append({'type': type(error).__name__, 'module': type(error).__module__,
                    'code': str(error), 'frames': [{'file': item.filename, 'function': item.name,
                        'line': item.lineno} for item in traceback.extract_tb(error.__traceback__, limit=32)]})
                error = error.__cause__ if error.__cause__ is not None else error.__context__
            return values
        def invoke(name, callback, *, independent=False):
            try:
                value = {'returned': True, 'value': callback()}
            except BaseException as error:
                value = {'returned': False, 'errors': errors(error)}
                proof['calls'][name] = value
                if not (independent and type(error) is WarrantError
                        and str(error) == 'INDEPENDENT_READBACK_UNAVAILABLE'):
                    raise
                return value
            proof['calls'][name] = value
            return value
        def times(release):
            return {'wall': time.time(), 'monotonic': time.monotonic(),
                'governor_now': f.governor._now(), 'claim_until': task['claim'].lease_until,
                'session_until': task['facts']['grant']['expires_at'],
                'warrant_until': task['warrant'].expires_at.timestamp(),
                'envelope_until': task['facts']['envelope']['deadline_at'],
                'dispatch_principal_until': release.principal.expires_at.timestamp(),
                'host_auth_monotonic_until': h._auth_deadline,
                'TLS_until': h._tls_expires, 'TLS_verified': h.tls_verified}
        def other_deadlines_valid(value):
            return (all(value['wall'] < value[name] for name in (
                'session_until', 'warrant_until', 'envelope_until',
                'dispatch_principal_until', 'TLS_until'))
                and value['monotonic'] < value['host_auth_monotonic_until']
                and value['TLS_verified'] is True)
        def isolated_error(cut, reason):
            cut['isolation_error'] = reason
            proof['isolation_error'] = reason
            raise RuntimeError('NATIVE_CLAIM_EXPIRY_FIXTURE_NOT_ISOLATED: ' + reason)
        try:
            baseline = capture('baseline')
            _, domain = self._portable_a6_release_domain()
            task = self._portable_task(4, domain, claim_lease_seconds=12, session_lease_seconds=60)
            tasks.append(task)
            proof['operation'] = task['facts']
            before = capture('before-dispatch')
            original_consume = CorePortableWriteRelease.consume_write_ack
            def expire_before_consume(release, acknowledgment, store, observed, candidate):
                hook_entry = diagnostic_time()
                selected = (release.adapter is h.portable_target and store is h.portable_store
                    and release.warrant is task['warrant'])
                if not selected:
                    return original_consume(release, acknowledgment, store, observed, candidate)
                ack_entry = times(release)
                ack_entry['ACK_consumed'] = acknowledgment.consumed
                ack_entry['ACK_same_release'] = acknowledgment.release is release
                cut = {'hook_entry': hook_entry, 'ACK_entry_before_observer': ack_entry,
                    'outside_SQL': not bool(_IN_TRANSACTION.get()),
                    'boundary': 'ORIGINAL_AUTHORIZE_ACK_RETURNED_BEFORE_ORIGINAL_CONSUME',
                    'same_store': store is h.portable_store, 'same_target': release.adapter is h.portable_target,
                    'warrant_digest': release.warrant.digest(),
                    'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
                    'ACK_before': {'type': type(acknowledgment).__name__,
                        'same_release': acknowledgment.release is release,
                        'consumed': acknowledgment.consumed,
                        'observation': acknowledgment.observation.to_dict()},
                    'original_consume_calls': 0,
                    'frames': [{'file': item.filename, 'function': item.name,
                        'line': item.lineno} for item in traceback.extract_stack(limit=24)]}
                cuts.append(cut)
                if observer_delay:
                    if (ack_entry['ACK_consumed'] or not ack_entry['ACK_same_release']
                            or not cut['outside_SQL'] or not other_deadlines_valid(ack_entry)
                            or not ack_entry['wall'] < ack_entry['claim_until']
                            or not ack_entry['claim_until'] < min(ack_entry[name] for name in (
                                'session_until', 'warrant_until', 'envelope_until',
                                'dispatch_principal_until'))):
                        isolated_error(cut, 'ACK not live on adversarial observer entry')
                    hold = {'reason': 'ADVERSARIAL_OBSERVER_DELAY_UNTIL_ORIGINAL_CLAIM_EXPIRY',
                        'original_claim_until': task['claim'].lease_until, 'bound_seconds': 14,
                        'start': diagnostic_time()}
                    cut['observer_hold'] = hold
                    if not hold['start']['wall'] < task['claim'].lease_until:
                        isolated_error(cut, 'claim expired before requested observer hold')
                    try:
                        while time.time() < task['claim'].lease_until:
                            if time.monotonic() - hold['start']['monotonic'] >= 14:
                                isolated_error(cut, 'bounded adversarial observer hold exceeded')
                            time.sleep(min(0.05, max(0.0, task['claim'].lease_until - time.time())))
                    finally:
                        hold['end'] = diagnostic_time()
                        hold['actual_seconds'] = (
                            hold['end']['monotonic'] - hold['start']['monotonic'])
                    hold['after_hold'] = times(release)
                    if (hold['actual_seconds'] > 14
                            or hold['after_hold']['wall'] < task['claim'].lease_until
                            or not other_deadlines_valid(hold['after_hold'])):
                        isolated_error(cut, 'adversarial observer hold not isolated')
                cut['before_wait_snapshot'] = capture('at-ACK-before-real-wait')
                cut['before_wait'] = times(release)
                value = cut['ACK_entry_before_observer']
                if (len(cuts) != 1 or not cut['outside_SQL'] or acknowledgment.consumed
                        or acknowledgment.release is not release or not other_deadlines_valid(value)
                        or not value['wall'] < value['claim_until']
                        or not value['claim_until'] < min(value[name] for name in (
                            'session_until', 'warrant_until', 'envelope_until', 'dispatch_principal_until'))):
                    isolated_error(cut, 'ACK not live before isolated claim expiry')
                wait_started = time.monotonic()
                while time.time() < task['claim'].lease_until:
                    if time.monotonic() - wait_started >= 14:
                        isolated_error(cut, 'bounded real wait exceeded')
                    time.sleep(min(0.05, max(0.0, task['claim'].lease_until - time.time())))
                cut['actual_wait_seconds'] = time.monotonic() - wait_started
                cut['after_wait'] = times(release)
                cut['clock_guard'] = {
                    'canonical_last_now': cut['before_wait_snapshot']['governor']['last_now'],
                    'max_clock_step_seconds': f.governor.policy.max_clock_step_seconds,
                    'after_wait_governor_now': cut['after_wait']['governor_now']}
                cut['clock_guard']['actual_step_seconds'] = (cut['clock_guard']['after_wait_governor_now']
                    - cut['clock_guard']['canonical_last_now'])
                if not 0 <= cut['clock_guard']['actual_step_seconds'] <= cut['clock_guard']['max_clock_step_seconds']:
                    isolated_error(cut, 'real wait exceeds original governor clock policy')
                if (cut['after_wait']['governor_now'] < task['claim'].lease_until
                        or not other_deadlines_valid(cut['after_wait'])):
                    isolated_error(cut, 'claim not expired or other authority expired')
                cut['after_wait_snapshot'] = capture('after-real-claim-expiry-before-consume')
                authority = None
                try:
                    authority = f.access.capture(Capability.COMMIT, use=NativeAccessUse.EXECUTION)
                    f.access.require_capture(authority, Capability.COMMIT)
                    cut['fresh_original_Native_control'] = {'same_Core': authority.core is f.core,
                        'same_runner': authority.runner is f.runner, 'purpose': authority.purpose.value,
                        'use': authority.use.value, 'issued_at': authority.principal.issued_at.isoformat(),
                        'expires_at': authority.principal.expires_at.isoformat(),
                        'actor_session_id': authority.principal.actor_session_id}
                except BaseException as error:
                    cut['native_control_error'] = errors(error)
                    cut['isolation_error'] = 'fresh original Native control refused'
                    proof['isolation_error'] = 'fresh original Native control refused'
                    raise RuntimeError('NATIVE_CLAIM_EXPIRY_FIXTURE_NOT_ISOLATED: fresh original Native control refused') from error
                finally:
                    if authority is not None:
                        authority.close()
                        cut['native_control_closed'] = authority._closed
                cut['before_original_consume'] = times(release)
                if not other_deadlines_valid(cut['before_original_consume']):
                    isolated_error(cut, 'other deadline expired before original consume')
                cut['isolated_claim_expiry'] = True
                cut['original_consume_calls'] += 1
                try:
                    value = original_consume(release, acknowledgment, store, observed, candidate)
                    cut['original_consume_returned'] = True
                    return value
                except BaseException as error:
                    cut['original_consume_returned'] = False
                    cut['original_consume_errors'] = errors(error)
                    raise
                finally:
                    cut['after_original_consume'] = times(release)
                    if not other_deadlines_valid(cut['after_original_consume']):
                        cut['isolation_error'] = 'other authority deadline crossed original consume'
                        proof['isolation_error'] = cut['isolation_error']
                    cut['ACK_after'] = {'consumed': acknowledgment.consumed,
                        'release_consumed': release._consumed,
                        'write_observation': None if release._write_observation is None
                            else release._write_observation.to_dict()}
            proof['phase'] = 'ORIGINAL_DISPATCH'
            with patch.object(CorePortableWriteRelease, 'consume_write_ack', new=expire_before_consume):
                def dispatch():
                    proof['dispatch_calls'] += 1
                    with managed.authority(Capability.COMMIT) as principal:
                        return task['route'].dispatch(principal, session_id=task['session_id'],
                            warrant=task['warrant'], operation=task['operation'],
                            reservation=task['reservation'], completion=task['completion'])
                dispatched = invoke('dispatch', dispatch)
            after = capture('after-dispatch')
            if proof.get('isolation_error') or len(cuts) != 1 or not cuts[0].get('isolated_claim_expiry'):
                proof['phase'] = 'FIXTURE_ISOLATION_FAILED_NO_CAUSAL_RED_QUALIFICATION'
                raise RuntimeError('NATIVE_CLAIM_EXPIRY_FIXTURE_NOT_ISOLATED')
            def reconcile():
                with managed.authority(Capability.READ) as principal:
                    epoch = f.governor.inspect(principal)['epoch']
                proof['actual_reconcile_epoch'] = epoch
                with managed.authority(Capability.COMMIT) as principal:
                    return task['route'].reconcile(principal, task['warrant'], epoch)
            settled = invoke('fresh_reconcile', reconcile, independent=True)
            final = capture('after-fresh-reconcile')
            proof['phase'] = 'ALL_ACTUAL_FACTS_SAVED_BEFORE_QUALIFICATION'
            cut = cuts[0]
            case.assertTrue(cut['isolated_claim_expiry'])
            case.assertTrue(other_deadlines_valid(cut['after_original_consume']))
            case.assertLessEqual(cut['clock_guard']['actual_step_seconds'],
                                 cut['clock_guard']['max_clock_step_seconds'])
            case.assertEqual(1, proof['dispatch_calls'])
            case.assertEqual(1, cut['original_consume_calls'])
            case.assertTrue(all(cut[key] for key in ('outside_SQL', 'same_store', 'same_target')))
            case.assertIs(False, cut['ACK_before']['consumed'])
            case.assertIs(True, cut['ACK_before']['same_release'])
            case.assertEqual(cut['before_wait_snapshot']['full_canonical_rows'],
                             cut['after_wait_snapshot']['full_canonical_rows'])
            case.assertEqual(cut['before_wait_snapshot']['governor'], cut['after_wait_snapshot']['governor'])
            case.assertEqual(cut['before_wait_snapshot']['raw_inventory'], cut['after_wait_snapshot']['raw_inventory'])
            for value in (baseline, before, cut['before_wait_snapshot'], cut['after_wait_snapshot'], after, final):
                case.assertIs(True, value['full_rows_match_summary'])
                case.assertIs(True, value['snapshot_outside_SQL'])
                case.assertEqual(value['raw_inventory']['envelope']['payload_sha256'],
                                 value['raw_inventory']['material_sha256'])
            case.assertEqual([1, 0, 0], [a - b for a, b in zip(
                after['executor_counters'], before['executor_counters'], strict=True)],
                'NATIVE_PORTABLE_EXPIRED_CLAIM_MUST_BLOCK_PHYSICAL_WRITE')
            case.assertEqual(before['raw_inventory'], after['raw_inventory'])
            case.assertIs(False, cut['ACK_after']['consumed'])
            case.assertIs(False, cut['ACK_after']['release_consumed'])
            case.assertIsNone(cut['ACK_after']['write_observation'])
            case.assertIs(False, cut['original_consume_returned'])
            case.assertEqual('REQUIRED_TASK_INACTIVE', cut['original_consume_errors'][0]['code'])
            case.assertEqual('RELEASED', after['head']['in_flight']['phase'])
            case.assertIsNotNone(after['head']['in_flight']['write_observation'])
            case.assertIsNone(after['head']['in_flight']['ack'])
            case.assertIs(True, dispatched['returned'])
            case.assertEqual('Unknown', dispatched['value']['outcome']['contract_type'])
            case.assertIs(False, settled['returned'])
            case.assertEqual('INDEPENDENT_READBACK_UNAVAILABLE', settled['errors'][0]['code'])
            case.assertEqual(after['full_canonical_rows'], final['full_canonical_rows'])
            case.assertEqual(after['raw_inventory'], final['raw_inventory'])
            case.assertEqual(after['executor_counters'], final['executor_counters'])
            joined = final['tasks'][task['task_id']]
            case.assertEqual('STARTED', joined['job']['state'])
            case.assertIsNone(joined['job']['completion_proof'])
            case.assertEqual('Unknown', joined['intent']['outcome']['contract_type'])
            case.assertIsNone(joined['intent']['resolution'])
            case.assertEqual('UNKNOWN', final['governor']['reservations'][task['warrant'].risk_reservation_id]['state'])
            case.assertEqual(0, h.model_calls())
            proof['phase'] = 'COMPLETE'
        finally:
            self.retained['portable_claim_expiry'] = self.legacy_capacity_save(
                'native-portable-claim-expiry-proof.json', proof)

    def portable_native_tls_at_write_assertions(self, case, *, after_authorize):
        import hashlib
        import json
        import traceback
        from unittest.mock import patch

        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.contracts.serialization import (
            canonical_json_bytes,
            canonical_sha256,
        )
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION, RecordKind
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        from runtime.mission.liability import Reconciliation
        from runtime.mission.portable_target import (
            CorePortableTarget,
            CorePortableWriteRelease,
        )
        from runtime.mission.warrant import WarrantError

        h, f, managed = self.host, self.host.foundation, self.host._native_coding
        target, tasks, cuts, witnesses = h.portable_target, [], [], []
        proof = {'schema': 'nz13.native-portable-tls-at-write.v1',
            'scenario': 'AFTER_AUTHORIZE' if after_authorize else 'BEFORE_AUTHORIZE',
            'phase': 'INITIAL', 'snapshots': {}, 'calls': {}, 'cuts': cuts,
            'boundary_calls': {'authorize': 0, 'consume': 0},
            'live_original_witnesses': witnesses,
            'fixture_scope': 'FIXTURE_OS_ADMISSION_SYNTHETIC_TEST_ONLY',
            'TLS_scope': 'Only the existing synthetic fixture tls_verified flag is transiently false. '
                'Restoring its previous value is not certificate renewal or TLS/CA/PolicyKit certification.',
            'model_certification': 'NOT_CERTIFIED', 'qualification': False,
            'finish_offline_job_not_called': True}
        def plain(value):
            return json.loads(canonical_json_bytes(value))
        def tls_state():
            return {'verified': h.tls_verified, 'pin': h.tls_pin, 'expires': h._tls_expires,
                'auth_deadline': h._auth_deadline, 'source': list(h.source),
                'composition_digest': f.spec.digest, 'instance_id': h.instance_id,
                'phase': f.lifecycle.phase.value,
                'admission_generation': f.lifecycle.admission_generation,
                'composition_generation': f.lifecycle.composition_generation,
                'fence_sequence': f.lifecycle.fence_sequence}
        def capture(name):
            value = self._portable_no_release_snapshot(tasks)
            proof['snapshots'][name] = self.legacy_capacity_save(
                'portable-native-tls-' + name + '.json', value)
            return value
        def errors(error):
            chain, seen = [], set()
            while error is not None and id(error) not in seen and len(chain) < 8:
                seen.add(id(error))
                chain.append({'type': type(error).__name__, 'module': type(error).__module__,
                    'code': str(error), 'frames': [{'file': item.filename, 'function': item.name,
                        'line': item.lineno} for item in traceback.extract_tb(error.__traceback__, limit=32)]})
                error = error.__cause__ if error.__cause__ is not None else error.__context__
            return chain
        def invoke(name, callback, *, independent_readback=False):
            try:
                value = {'returned': True, 'value': callback()}
            except BaseException as error:
                value = {'returned': False, 'errors': errors(error)}
                proof['calls'][name] = value
                if not (independent_readback and type(error) is WarrantError
                        and str(error) == 'INDEPENDENT_READBACK_UNAVAILABLE'):
                    raise
                return value
            proof['calls'][name] = value
            return value
        def dispatch(task):
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].dispatch(principal, session_id=task['session_id'],
                    warrant=task['warrant'], operation=task['operation'],
                    reservation=task['reservation'], completion=task['completion'])
        def reconcile(task):
            with managed.authority(Capability.READ) as principal:
                epoch = f.governor.inspect(principal)['epoch']
            proof.setdefault('actual_reconcile_epochs', []).append(epoch)
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].reconcile(principal, task['warrant'], epoch)
        def deny_fresh_read(cut):
            authority = None
            read = {'capture_created': False, 'returned': False,
                'purpose': Capability.READ.value, 'use': NativeAccessUse.READ.value,
                'outside_SQL': not bool(_IN_TRANSACTION.get())}
            cut['fresh_READ_while_invalid'] = read
            try:
                authority = f.access.capture(Capability.READ, use=NativeAccessUse.READ)
                read['capture_created'] = True
                f.access.require_capture(authority, Capability.READ)
                read['returned'] = True
            except BaseException as error:
                read['errors'] = errors(error)
                read['original_AdmissionError'] = type(error) is AdmissionError
                if type(error) is not AdmissionError:
                    raise
            finally:
                if authority is not None:
                    authority.close()
                    read['capture_closed'] = authority._closed
        def at_invalid_tls(release, store, observed, candidate, delegate, acknowledgment=None):
            cut = {'boundary': 'ORIGINAL_AUTHORIZE_ACK_RETURNED_BEFORE_ORIGINAL_CONSUME'
                    if after_authorize else 'ORIGINAL_SEAL_RETURNED_AT_AUTHORIZE_ENTRY',
                'outside_SQL': not bool(_IN_TRANSACTION.get()),
                'same_store': store is h.portable_store, 'same_target': release.adapter is target,
                'same_original_warrant': release.warrant is task['warrant'],
                'warrant_digest': release.warrant.digest(), 'before_state_root': observed.state_root,
                'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
                'original_delegate_calls': 0,
                'caller_frames': [{'file': item.filename, 'function': item.name,
                    'line': item.lineno} for item in traceback.extract_stack(limit=24)]}
            cuts.append(cut)
            cut['before_snapshot'] = capture('at-boundary-before-TLS-invalidation')
            cut['TLS_before'] = tls_state()
            previous = h.tls_verified
            if acknowledgment is not None:
                cut['original_ACK_before_consume'] = {'type': type(acknowledgment).__name__,
                    'same_release': acknowledgment.release is release,
                    'consumed': acknowledgment.consumed,
                    'observation': acknowledgment.observation.to_dict()}
            try:
                h.tls_verified = False
                cut['TLS_invalid'] = tls_state()
                deny_fresh_read(cut)
                cut['original_delegate_calls'] += 1
                try:
                    result = delegate()
                    cut['original_delegate_returned'] = True
                    cut['original_result_type'] = type(result).__name__
                    return result
                except BaseException as error:
                    cut['original_delegate_returned'] = False
                    cut['original_delegate_errors'] = errors(error)
                    cut['original_AdmissionError'] = type(error) is AdmissionError
                    raise
            finally:
                h.tls_verified = previous
                cut['TLS_restored_previous_fixture_value'] = tls_state()
                cut['release_after_original_call'] = {'attempted': release._attempted,
                    'consumed': release._consumed,
                    'write_observation': None if release._write_observation is None
                        else release._write_observation.to_dict()}
                if acknowledgment is not None:
                    cut['original_ACK_after_consume'] = {'consumed': acknowledgment.consumed,
                        'same_release': acknowledgment.release is release}
        try:
            baseline = capture('baseline')
            _, domain = self._portable_a6_release_domain()
            task = self._portable_task(4, domain)
            tasks.append(task)
            proof['operation'] = task['facts']
            before = capture('before-cut')
            original_authorize = CorePortableWriteRelease.authorize_write
            original_consume = CorePortableWriteRelease.consume_write_ack
            def selected(release, store):
                return (release.adapter is target and store is h.portable_store
                    and release.warrant == task['warrant'])
            def at_authorize(release, store, observed, candidate):
                if not selected(release, store):
                    return original_authorize(release, store, observed, candidate)
                proof['boundary_calls']['authorize'] += 1
                if not after_authorize and not cuts:
                    return at_invalid_tls(release, store, observed, candidate,
                        lambda: original_authorize(release, store, observed, candidate))
                return original_authorize(release, store, observed, candidate)
            def at_consume(release, acknowledgment, store, observed, candidate):
                if not selected(release, store):
                    return original_consume(release, acknowledgment, store, observed, candidate)
                proof['boundary_calls']['consume'] += 1
                if after_authorize and not cuts:
                    return at_invalid_tls(release, store, observed, candidate,
                        lambda: original_consume(release, acknowledgment, store, observed, candidate),
                        acknowledgment)
                return original_consume(release, acknowledgment, store, observed, candidate)
            proof['phase'] = 'ORIGINAL_TLS_BOUNDARY'
            with patch.object(CorePortableWriteRelease, 'authorize_write', new=at_authorize), \
                    patch.object(CorePortableWriteRelease, 'consume_write_ack', new=at_consume):
                dispatched = invoke('cut_dispatch', lambda: dispatch(task))
            after = capture('after-TLS-restored-cut')
            proof['prior_write_lifetime_exited'] = {
                'no_active_write_port': getattr(h.portable_store._held_lock, 'write_release', None) is None,
                'no_old_Core_guard_capture': getattr(h.portable_store._held_lock,
                    'core_no_release_capture', None) is None}
            original_verify = CorePortableTarget._verify_no_release
            def observe_no_release(adapter, operation, warrant):
                verified = original_verify(adapter, operation, warrant)
                if adapter is target and warrant == task['warrant']:
                    witness, certificate = verified._witness, verified.certificate
                    captured = witness.capture
                    witnesses.append({'same_certificate': witness.certificate is certificate,
                        'owns_outer_guard': captured.entry.owns_outer_lock,
                        'current_guard_capture': getattr(adapter.store._held_lock,
                            'core_no_release_capture', None) is captured,
                        'outside_SQL': not bool(_IN_TRANSACTION.get()),
                        'head_revision': captured.head_revision, 'intent_revision': captured.intent_revision,
                        'captured_head': json.loads(captured.head_bytes),
                        'captured_intent': json.loads(captured.intent_bytes),
                        'certificate': certificate.to_dict()})
                return verified
            proof['phase'] = 'FRESH_ORIGINAL_READBACK_AFTER_EXPLICIT_FIXTURE_RESTORATION'
            with patch.object(CorePortableTarget, '_verify_no_release', new=observe_no_release):
                settled = invoke('fresh_reconcile', lambda: reconcile(task), independent_readback=True)
            after_settle = capture('after-fresh-reconcile')
            if settled['returned']:
                invoke('retained_reconcile', lambda: reconcile(task))
            else:
                proof['retained_reconcile_not_attempted'] = 'FIRST_READBACK_REFUSED_NO_RETRY'
            invoke('retained_dispatch', lambda: dispatch(task))
            final = capture('after-retained-controls')
            proof['phase'] = 'ALL_ACTUAL_FACTS_SAVED_BEFORE_QUALIFICATION'
            case.assertEqual(1, len(cuts))
            cut = cuts[0]
            case.assertTrue(all(cut[key] for key in (
                'outside_SQL', 'same_store', 'same_target', 'same_original_warrant')))
            case.assertEqual({'authorize': 1, 'consume': 1 if after_authorize else 0},
                             proof['boundary_calls'])
            case.assertEqual('SYNTHETIC_TEST_ONLY', cut['TLS_before']['pin'])
            case.assertIs(True, cut['TLS_before']['verified'])
            case.assertEqual({**cut['TLS_before'], 'verified': False}, cut['TLS_invalid'])
            case.assertEqual(cut['TLS_before'], cut['TLS_restored_previous_fixture_value'])
            case.assertEqual(1, cut['original_delegate_calls'])
            case.assertIs(False, cut['original_delegate_returned'])
            case.assertIs(True, cut['original_AdmissionError'])
            read = cut['fresh_READ_while_invalid']
            case.assertIs(True, read['outside_SQL'])
            case.assertIs(False, read['capture_created'])
            case.assertIs(False, read['returned'])
            case.assertIs(True, read['original_AdmissionError'])
            for chain in (read['errors'], cut['original_delegate_errors']):
                case.assertEqual('CORE_ADMISSION_DENIED', chain[0]['code'])
                case.assertIn('_require_qualified_operator',
                              [frame['function'] for frame in chain[0]['frames']])
            for value in (baseline, before, cut['before_snapshot'], after, after_settle, final):
                case.assertIs(True, value['full_rows_match_summary'])
                case.assertIs(True, value['snapshot_outside_SQL'])
                case.assertEqual(value['raw_inventory']['envelope']['payload_sha256'],
                                 value['raw_inventory']['material_sha256'])
            case.assertEqual(cut['before_snapshot']['full_canonical_rows'], after['full_canonical_rows'])
            case.assertEqual(cut['before_snapshot']['governor'], after['governor'])
            case.assertEqual(cut['before_snapshot']['raw_inventory'], after['raw_inventory'])
            case.assertIs(True, dispatched['returned'])
            case.assertEqual('Unknown', dispatched['value']['outcome']['contract_type'])
            case.assertTrue(all(proof['prior_write_lifetime_exited'].values()))
            case.assertEqual([1, 0, 0], [a - b for a, b in zip(
                after['executor_counters'], before['executor_counters'], strict=True)],
                'NATIVE_PORTABLE_INVALID_TLS_MUST_BLOCK_PHYSICAL_WRITE')
            case.assertEqual(before['raw_inventory'], after['raw_inventory'])
            joined = after['tasks'][task['task_id']]
            case.assertEqual('Unknown', joined['intent']['outcome']['contract_type'])
            case.assertIsNone(joined['intent']['resolution'])
            case.assertEqual('STARTED', joined['job']['state'])
            case.assertIsNone(joined['job']['completion_proof'])
            case.assertEqual(task['facts']['warrant'], after['head']['in_flight']['warrant'])
            case.assertEqual(task['warrant'].digest(), after['head']['in_flight']['warrant_digest'])
            case.assertIsNone(after['head']['in_flight']['ack'])
            if after_authorize:
                case.assertEqual('RELEASED', after['head']['in_flight']['phase'])
                case.assertIsNotNone(after['head']['in_flight']['write_observation'])
                case.assertIs(False, cut['original_ACK_before_consume']['consumed'])
                case.assertIs(True, cut['original_ACK_before_consume']['same_release'])
                case.assertIs(False, cut['original_ACK_after_consume']['consumed'])
                case.assertIs(False, cut['release_after_original_call']['consumed'])
                case.assertIsNone(cut['release_after_original_call']['write_observation'])
                case.assertIs(False, settled['returned'])
                case.assertEqual('INDEPENDENT_READBACK_UNAVAILABLE', settled['errors'][0]['code'])
                case.assertEqual([], witnesses)
                case.assertEqual(after['full_canonical_rows'], after_settle['full_canonical_rows'])
                case.assertEqual('UNKNOWN', after_settle['governor']['reservations'][task['warrant'].risk_reservation_id]['state'])
            else:
                case.assertEqual('STARTED', after['head']['in_flight']['phase'])
                case.assertIsNone(after['head']['in_flight']['write_observation'])
                case.assertIs(True, settled['returned'], 'NATIVE_TLS_DENIAL_REQUIRES_FRESH_NO_RELEASE')
                case.assertEqual('NotApplied', settled['value']['outcome']['contract_type'])
                case.assertEqual(1, len(witnesses))
                case.assertTrue(all(witnesses[0][key] for key in (
                    'same_certificate', 'owns_outer_guard', 'current_guard_capture', 'outside_SQL')))
                case.assertEqual(after['head'], witnesses[0]['captured_head'])
                case.assertEqual(joined['intent'], witnesses[0]['captured_intent'])
                case.assertEqual(witnesses[0]['certificate'],
                    after_settle['histories'][task['warrant'].digest()]['no_release_certificate'])
                case.assertIs(False, settled['value']['grants_replay'])
                case.assertEqual('NONE', settled['value']['authority'])
                case.assertIsNone(after_settle['head']['in_flight'])
                expected_governor = plain(after['governor'])
                expected_governor['version'] += 1
                case.assertGreaterEqual(after_settle['governor']['last_now'], expected_governor['last_now'])
                expected_governor['last_now'] = after_settle['governor']['last_now']
                expected_governor['reservations'][task['warrant'].risk_reservation_id].update(
                    state='COMMITTED', evidence_digest=canonical_sha256(
                        Reconciliation.from_dict(after_settle['tasks'][task['task_id']]['intent']['resolution'])))
                case.assertEqual(expected_governor, after_settle['governor'])
                settlement_before, settlement_after = after['full_canonical_rows'], after_settle['full_canonical_rows']
                changed = {key for key in settlement_before.keys() & settlement_after.keys()
                           if settlement_before[key] != settlement_after[key]}
                intent_key = f.intent_journal._key(task['warrant'])
                case.assertEqual({RecordKind.OPERATION.value + ':' + f.target_projection.head_key,
                    RecordKind.OPERATION.value + ':' + f.liability._key(task['task_id']),
                    RecordKind.OPERATION.value + ':' + intent_key, RecordKind.OUTBOX.value + ':' + intent_key}, changed)
                case.assertFalse(settlement_before.keys() - settlement_after.keys())
                case.assertEqual(4, len(settlement_after.keys() - settlement_before.keys()))
                for name in ('job', 'session', 'context', 'ledger', 'owner_witness'):
                    case.assertEqual(joined[name], after_settle['tasks'][task['task_id']][name])
            case.assertEqual('STARTED', final['tasks'][task['task_id']]['job']['state'])
            case.assertIsNone(final['tasks'][task['task_id']]['job']['completion_proof'])
            case.assertEqual(after_settle['full_canonical_rows'], final['full_canonical_rows'])
            case.assertEqual(after_settle['raw_inventory'], final['raw_inventory'])
            case.assertEqual(after['executor_counters'], final['executor_counters'])
            case.assertIs(True, proof['calls']['retained_dispatch']['returned'])
            case.assertIs(False, proof['calls']['retained_dispatch']['value']['grants_replay'])
            case.assertEqual(0, h.model_calls())
            proof['phase'] = 'COMPLETE'
        finally:
            self.retained['portable_tls_at_write'] = self.legacy_capacity_save(
                'native-portable-tls-at-write-proof.json', proof)

    def portable_native_sql_retry_assertions(self, case):
        import json
        import subprocess
        import sys
        import threading
        import time
        import traceback
        from contextlib import ExitStack
        from types import CodeType
        from unittest.mock import patch

        from runtime.core_admission import Capability
        from runtime.memory_patch.adapters.cockroach.repositories import (
            canonical_record,
        )
        from runtime.memory_patch.contracts.serialization import (
            canonical_json_bytes,
            canonical_sha256,
        )
        from runtime.memory_patch.errors import (
            MemoryPatchError,
            RetryableSerializationError,
        )
        from runtime.memory_patch.persistence.ports import (
            _IN_TRANSACTION,
            LocalCoreTransaction,
            RecordKind,
        )
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        from runtime.mission import sandbox_linux
        from runtime.mission.liability import Reconciliation
        from runtime.mission.portable_target import CorePortableWriteRelease

        h, f, managed = self.host, self.host.foundation, self.host._native_coding
        target, store, runner = h.portable_target, h.portable_store, h.runner
        factory = runner._factory
        tasks, views, capture_objects, candidate_objects, attempts = [], [], [], [], []
        proof = {'schema': 'nz13.native-portable-sql-retry.v1', 'phase': 'INITIAL',
            'snapshots': {}, 'attempts': attempts, 'captures': [], 'capture_checks': [],
            'faults': [], 'rollbacks': [], 'backoffs': [], 'domain_calls': [],
            'callback_audit': [], 'identity_guard_calls': [], 'release_observations': [],
            'candidate_observations': [], 'map_publications': [], 'calls': {},
            'boundary_calls': {'authorize': 0, 'consume': 0}, 'legacy_calls': [],
            'fixture_scope': 'FIXTURE_OS_ADMISSION_SYNTHETIC_TEST_ONLY',
            'model_certification': 'NOT_CERTIFIED', 'qualification': False,
            'retry_scope': 'Original SQLSTATE40001 replay, not SQLite lock contention.',
            'IO_scope': 'Domain callback I/O only; original Core/SQLite identity guards retained.',
            'finish_offline_job_not_called': True}
        state = {'enabled': False, 'boundary': None, 'legacy': None, 'callback_active': False,
            'current_view': None, 'current_attempt': None, 'faulted': set()}
        original_run, original_sleep = runner.run, runner._sleep
        original_legacy = h.portable_release_route._legacy_run
        original_commit, original_rollback = LocalCoreTransaction.commit, LocalCoreTransaction.rollback
        original_authorize = CorePortableWriteRelease.authorize_write
        original_consume = CorePortableWriteRelease.consume_write_ack
        original_inner_consume = CorePortableWriteRelease._consume_write_ack
        capture_code = f.access.capture.__func__.__code__
        diagnostic_now_code = f.governor._now.__func__.__code__
        check_code = f.access.require_capture.__func__.__code__
        identity_codes = {factory._file_check.__func__.__code__}
        authorize_code = next(value for value in h.portable_release_route._run.__func__.__code__.co_consts
                              if type(value) is CodeType and value.co_name == 'pure')
        consume_code = next(value for value in original_consume.__code__.co_consts
                            if type(value) is CodeType and value.co_name == 'unrevoked_session')
        release_code = h.portable_release_route.target_settlement.before_release_in_transaction.__func__.__code__
        candidate_code = target.candidate_observation.__func__.__code__
        domain_codes = {}
        for category, functions in (
                ('source', (h.source_probe, managed.project_probe, managed.sandbox_probe)),
                ('config', (sandbox_linux.load_host_config, h.broker.capture_config, h.broker.restore_capture)),
                ('Store', (store._load, store._write, store.observe_guarded_inventory,
                           store.execute, store.verify, store.get_receipt)),
                ('executor', (h.portable_executor.execute, h.portable_executor.rearm,
                              h.portable_executor.verify)),
                ('worker', (managed.prepare_job, managed.run_factory)),
                ('publication', (managed.effect_factory, managed.local_git_binding)),
                ('wait', (threading.Condition.wait, threading.Event.wait, threading.Thread.join,
                          subprocess.Popen.wait, subprocess.Popen.communicate))):
            for function in functions:
                code = getattr(function, '__code__', None)
                if code is None:
                    code = function.__func__.__code__
                domain_codes[code] = category
        maps = {name: getattr(managed, name) for name in ('jobs', 'runs', 'effects', 'materializations')}
        profile_domain_names = frozenset(code.co_name for code in domain_codes)
        profile_identity_names = frozenset(code.co_name for code in identity_codes)
        old_profile = sys.getprofile()

        def plain(value):
            return json.loads(canonical_json_bytes(value))

        def rows(tx):
            found = {}
            for kind in RecordKind:
                values = tx.scan(kind, limit=1024)
                if len(values) >= 1024:
                    raise AssertionError('NATIVE_SQL_RETRY_CANONICAL_ROW_BOUND')
                for row in values:
                    row.verify()
                    found[kind.value + ':' + row.record_id] = {
                        'revision': row.revision, 'payload_digest': row.payload_digest,
                        'payload': row.payload, 'canonical_record': canonical_record(row)}
            return plain(found)

        def observer_rows(tx):
            previous_profile = sys.getprofile()
            sys.setprofile(old_profile)
            try:
                return rows(tx)
            finally:
                sys.setprofile(previous_profile)

        def map_state():
            return {name: sorted((str(key), id(value)) for key, value in mapping.items())
                    for name, mapping in maps.items()}

        def capture(name):
            value = self._portable_no_release_snapshot(tasks)
            proof['snapshots'][name] = self.legacy_capacity_save('portable-sql-retry-' + name + '.json', value)
            return value

        def profile(frame, event, arg):
            if old_profile is not None:
                old_profile(frame, event, arg)
            if not state['enabled']:
                return
            code = frame.f_code
            if event in ('c_return', 'c_exception'):
                return
            if event == 'c_call' and (arg is not time.sleep or not state['callback_active']):
                return
            if (event == 'return' and code is not diagnostic_now_code
                    and code is not capture_code and code is not candidate_code):
                return
            if (event == 'return' and code is diagnostic_now_code and state['callback_active']
                    and frame.f_locals.get('self') is f.governor):
                state['current_attempt'].setdefault('original_governor_clock_samples', []).append({
                    'returned_now': arg, 'wall': time.time(), 'monotonic': time.monotonic()})
            if event == 'call' and code.co_name in profile_domain_names and code in domain_codes:
                proof['domain_calls'].append({'category': domain_codes[code],
                    'function': code.co_qualname, 'callback_active': state['callback_active'],
                    'in_transaction_flag': bool(_IN_TRANSACTION.get()),
                    'db_transaction_active': factory.db.in_transaction, 'boundary': state['boundary']})
            module = frame.f_globals.get('__name__', '')
            if (event == 'call' and module.startswith(('runtime.providers.', 'providers.'))
                    and not module.endswith('.coding_contracts')):
                proof['domain_calls'].append({'category': 'provider', 'function': code.co_qualname,
                    'callback_active': state['callback_active'],
                    'in_transaction_flag': bool(_IN_TRANSACTION.get()),
                    'db_transaction_active': factory.db.in_transaction, 'boundary': state['boundary']})
            if event == 'c_call' and arg is time.sleep and state['callback_active']:
                proof['domain_calls'].append({'category': 'wait', 'function': 'time.sleep',
                    'callback_active': True, 'in_transaction_flag': bool(_IN_TRANSACTION.get()),
                    'db_transaction_active': factory.db.in_transaction, 'boundary': state['boundary']})
            if event == 'call' and code.co_name in profile_identity_names and code in identity_codes and _IN_TRANSACTION.get():
                proof['identity_guard_calls'].append({'function': code.co_qualname,
                    'callback_active': state['callback_active'],
                    'db_transaction_active': factory.db.in_transaction})
            if event == 'return' and code is capture_code and state['boundary'] is not None and arg is not None:
                capture_objects.append(arg)
                proof['captures'].append({'boundary': state['boundary'], 'capture_id': id(arg),
                    'principal_id': id(arg.principal), 'purpose': arg.purpose.value, 'use': arg.use.value,
                    'outside_callback': not state['callback_active'],
                    'in_transaction_flag': bool(_IN_TRANSACTION.get()),
                    'same_Core': arg.core is f.core, 'same_runner': arg.runner is runner,
                    'native_record_id': arg.native_record_id, 'native_revision': arg.native_revision,
                    'native_digest': arg.native_digest})
            if event == 'call' and code is check_code and state['callback_active']:
                local = frame.f_locals
                authority, tx = local['capture'], local.get('tx')
                proof['capture_checks'].append({'boundary': state['legacy']['boundary'],
                    'attempt': state['current_attempt']['number'], 'capture_id': id(authority),
                    'principal_id': id(authority.principal), 'tx_id': None if tx is None else id(tx)})
            if event == 'call' and code is release_code and state['callback_active']:
                local = frame.f_locals
                observation = local['write_observation']
                proof['release_observations'].append({'view_id': id(local['tx']),
                    'observation_id': id(observation), 'observation': observation.to_dict()})
            if event == 'return' and code is candidate_code and state['boundary'] == 'authorize' and arg is not None:
                candidate_objects.append(arg)
                proof['candidate_observations'].append({'object_id': id(arg), 'value': arg.to_dict(),
                    'callback_active': state['callback_active']})
            if event == 'call' and code is original_inner_consume.__code__ and state['boundary'] == 'consume':
                proof['inner_consume_calls'] = proof.get('inner_consume_calls', 0) + 1

        def audit(event, _args):
            if not state['enabled'] or not state['callback_active']:
                return
            if event not in ('open', 'os.listdir', 'os.scandir', 'os.chdir', 'os.mkdir', 'os.remove',
                             'os.rename', 'os.rmdir', 'os.chmod', 'os.chown', 'os.link', 'os.symlink',
                             'os.truncate', 'subprocess.Popen', 'socket.connect', 'socket.bind', 'compile', 'exec'):
                return
            frame, identity_guard = sys._getframe(1), False
            while frame is not None:
                if frame.f_code in identity_codes:
                    identity_guard = True
                    break
                frame = frame.f_back
            proof['callback_audit'].append({'event': event, 'original_identity_guard': identity_guard,
                'in_transaction_flag': bool(_IN_TRANSACTION.get()),
                'db_transaction_active': factory.db.in_transaction,
                'boundary': state['legacy']['boundary']})

        def observed_legacy(principal, purpose, callback):
            boundary = state['boundary']
            expected = {'authorize': authorize_code, 'consume': consume_code}.get(boundary)
            if expected is None:
                return original_legacy(principal, purpose, callback)
            selected = {'boundary': boundary, 'callback_name': callback.__name__,
                'exact_original_code': callback.__code__ is expected, 'principal_id': id(principal),
                'purpose': purpose.value, 'outside_callback': not state['callback_active']}
            proof['legacy_calls'].append(selected)
            previous = state['legacy']
            state['legacy'] = selected
            try:
                return original_legacy(principal, purpose, callback)
            finally:
                state['legacy'] = previous

        def observed_run(context, callback):
            selected = state['legacy']
            if selected is None:
                return original_run(context, callback)
            boundary = selected['boundary']
            def observed_callback(tx):
                current = {'boundary': boundary,
                    'number': 1 + sum(item['boundary'] == boundary for item in attempts),
                    'view_id': id(tx), 'adapter_id': id(tx._adapter),
                    'principal_id': id(context.principal), 'same_context': tx.context is context,
                    'same_factory': tx._adapter.factory is factory,
                    'db_transaction_active': factory.db.in_transaction,
                    'in_transaction_flag': bool(_IN_TRANSACTION.get())}
                authority = next(item[0] for item in f.access._originals.values()
                                 if item[0].principal is context.principal)
                current['capture_id'] = id(authority)
                current['previous_views_invalid'] = all(not view._active for stage, view in views if stage == boundary)
                views.append((boundary, tx))
                attempts.append(current)
                state['current_view'], state['current_attempt'] = tx, current
                old_active = state['callback_active']
                state['callback_active'] = True
                before_maps = map_state()
                try:
                    current['entry_rows'] = observer_rows(tx)
                    current['before_original_callback'] = {'wall': time.time(), 'monotonic': time.monotonic()}
                    try:
                        result = callback(tx)
                    except BaseException as error:
                        current['original_callback_error_time'] = {'wall': time.time(), 'monotonic': time.monotonic()}
                        chain, seen = [], set()
                        actual_error = error
                        while actual_error is not None and id(actual_error) not in seen and len(chain) < 8:
                            seen.add(id(actual_error))
                            frames, tb = [], actual_error.__traceback__
                            while tb is not None and len(frames) < 32:
                                code = tb.tb_frame.f_code
                                frames.append({'file': code.co_filename, 'function': code.co_qualname,
                                    'line': tb.tb_lineno})
                                tb = tb.tb_next
                            chain.append({'type': type(actual_error).__name__,
                                'module': type(actual_error).__module__, 'code': str(actual_error),
                                'frames': frames})
                            actual_error = (actual_error.__cause__ if actual_error.__cause__ is not None
                                            else actual_error.__context__)
                        current['original_callback_errors'] = chain
                        raise
                    finally:
                        current['after_original_callback'] = {'wall': time.time(), 'monotonic': time.monotonic()}
                    current['returned_rows'] = observer_rows(tx)
                    current['returned'] = True
                    return result
                finally:
                    after_maps = map_state()
                    if before_maps != after_maps:
                        proof['map_publications'].append({'boundary': boundary, 'before': before_maps, 'after': after_maps})
                    state['callback_active'] = old_active
            try:
                return original_run(context, observed_callback)
            finally:
                for stage, view in views:
                    if stage == boundary:
                        next(item for item in attempts if item['view_id'] == id(view)).update(
                            view_invalid_after_run=not view._active, adapter_closed_after_run=not view._adapter.active,
                            history_products_cleared=not view._adapter._history_products)

        def conflict(adapter):
            selected = state['legacy']
            if selected is not None and adapter.factory is factory:
                current = state['current_attempt']
                row = adapter.get(RecordKind.OPERATION, f.target_projection.head_key)
                flight = None if row is None else row.payload['in_flight']
                matches = (selected['exact_original_code'] and adapter.context.purpose is Capability.COMMIT
                    and current['adapter_id'] == id(adapter) and flight is not None
                    and flight['warrant_digest'] == tasks[0]['warrant'].digest()
                    and flight['phase'] == 'RELEASED' and flight['ack'] is None)
                boundary = selected['boundary']
                if matches and boundary not in state['faulted']:
                    state['faulted'].add(boundary)
                    proof['faults'].append({'boundary': boundary, 'attempt': current['number'],
                        'sqlstate': '40001', 'before_original_commit': True,
                        'exact_original_callback_code': selected['exact_original_code'],
                        'callback_active': state['callback_active'],
                        'db_transaction_active': factory.db.in_transaction,
                        'uncommitted_head': plain(row.payload)})
                    current['faulted_before_commit'] = True
                    raise RetryableSerializationError()
                current['original_commit_called'] = True
            return original_commit(adapter)

        def rollback(adapter):
            selected = state['legacy']
            before = factory.db.in_transaction
            try:
                return original_rollback(adapter)
            finally:
                if selected is not None and adapter.factory is factory:
                    proof['rollbacks'].append({'boundary': selected['boundary'], 'adapter_id': id(adapter),
                        'before_db_transaction': before, 'after_db_transaction': factory.db.in_transaction,
                        'view_invalid': not state['current_view']._active,
                        'history_products_cleared': not adapter._history_products})

        def sleep(seconds):
            proof['backoffs'].append({'boundary': state['legacy']['boundary'], 'seconds': seconds,
                'callback_active': state['callback_active'], 'in_transaction_flag': bool(_IN_TRANSACTION.get()),
                'db_transaction_active': factory.db.in_transaction,
                'prior_view_invalid': not state['current_view']._active})
            return original_sleep(seconds)

        def selected(release, actual_store):
            return release.adapter is target and actual_store is store and release.warrant == tasks[0]['warrant']

        def authorize(release, actual_store, before, candidate):
            if not selected(release, actual_store):
                return original_authorize(release, actual_store, before, candidate)
            proof['boundary_calls']['authorize'] += 1
            state['boundary'] = 'authorize'
            previous_boundary_profile = sys.getprofile()
            sys.setprofile(profile)
            try:
                result = original_authorize(release, actual_store, before, candidate)
                proof['original_ACK'] = {'object_id': id(result), 'consumed_before_consume': result.consumed,
                    'same_release': result.release is release, 'observation': result.observation.to_dict()}
                return result
            finally:
                sys.setprofile(previous_boundary_profile)
                state['boundary'] = None

        def consume(release, acknowledgment, actual_store, before, candidate):
            if not selected(release, actual_store):
                return original_consume(release, acknowledgment, actual_store, before, candidate)
            proof['boundary_calls']['consume'] += 1
            state['boundary'] = 'consume'
            previous_boundary_profile = sys.getprofile()
            sys.setprofile(profile)
            try:
                return original_consume(release, acknowledgment, actual_store, before, candidate)
            finally:
                sys.setprofile(previous_boundary_profile)
                proof['ACK_after_consume'] = {'object_id': id(acknowledgment),
                    'ack_consumed': acknowledgment.consumed, 'release_consumed': release._consumed,
                    'write_observation': None if release._write_observation is None else release._write_observation.to_dict()}
                state['boundary'] = None

        def dispatch(task):
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].dispatch(principal, session_id=task['session_id'],
                    warrant=task['warrant'], operation=task['operation'],
                    reservation=task['reservation'], completion=task['completion'])

        try:
            sys.addaudithook(audit)
            state['enabled'] = True
            baseline = capture('baseline')
            _, domain = self._portable_a6_release_domain()
            task = self._portable_task(4, domain)
            tasks.append(task)
            proof['operation'] = task['facts']
            before = capture('before-dispatch')
            proof['phase'] = 'ORIGINAL_DISPATCH_WITH_TWO_PRECOMMIT_40001_CUTS'
            with ExitStack() as patches:
                patches.enter_context(patch.object(runner, 'run', new=observed_run))
                patches.enter_context(patch.object(runner, '_sleep', new=sleep))
                patches.enter_context(patch.object(task['route'], '_legacy_run', new=observed_legacy))
                patches.enter_context(patch.object(LocalCoreTransaction, 'commit', new=conflict))
                patches.enter_context(patch.object(LocalCoreTransaction, 'rollback', new=rollback))
                patches.enter_context(patch.object(CorePortableWriteRelease, 'authorize_write', new=authorize))
                patches.enter_context(patch.object(CorePortableWriteRelease, 'consume_write_ack', new=consume))
                proof['calls']['dispatch'] = dispatch(task)
            calibration = {'phase': 'AFTER_DISPATCH_BEFORE_GENUINE_READONLY_CONTROLS',
                'outside_SQL_before': not bool(_IN_TRANSACTION.get()) and not factory.db.in_transaction,
                'admitted_source': plain(h.source), 'authority': 'NONE'}
            proof['observer_calibration'] = calibration
            source_code = getattr(h.source_probe, '__code__', None)
            if source_code is None:
                source_code = h.source_probe.__func__.__code__
            store_code = store.observe_guarded_inventory.__func__.__code__
            calibration['original_code_provenance'] = {
                'source': {'function': source_code.co_qualname, 'file': source_code.co_filename,
                    'line': source_code.co_firstlineno, 'registered_category': domain_codes[source_code]},
                'Store': {'function': store_code.co_qualname, 'file': store_code.co_filename,
                    'line': store_code.co_firstlineno, 'registered_category': domain_codes[store_code]}}
            def control_material(observation):
                return {'inventory': json.loads(observation.canonical_state),
                    'state_root': observation.state_root, 'resources_root': observation.resources_root,
                    'receipts_root': observation.receipts_root,
                    'guard_fingerprint': observation.guard_fingerprint,
                    'guard_identity': list(observation.guard_identity), 'authority': observation.authority}
            with store.target_guard():
                calibration['before'] = control_material(store.observe_guarded_inventory())
                event_start = len(proof['domain_calls'])
                previous_control_profile = sys.getprofile()
                sys.setprofile(profile)
                try:
                    observed_control = store.observe_guarded_inventory()
                    source_control = h.source_probe()
                finally:
                    sys.setprofile(previous_control_profile)
                calibration['observed'] = control_material(observed_control)
                calibration['source_result'] = plain(source_control)
                calibration['after'] = control_material(store.observe_guarded_inventory())
                calibration['domain_events'] = plain(proof['domain_calls'][event_start:])
            calibration['outside_SQL_after'] = not bool(_IN_TRANSACTION.get()) and not factory.db.in_transaction
            calibration['phase'] = 'ORIGINAL_READONLY_CONTROLS_OBSERVED'
            proof['captures_closed_after_boundaries'] = [value._closed for value in capture_objects]
            proof['native_registry_after_dispatch'] = len(f.access._originals)
            after = capture('after-dispatch')
            proof['escaped_views'] = []
            for boundary, view in views:
                try:
                    f.governor._load(view)
                except MemoryPatchError as error:
                    proof['escaped_views'].append({'boundary': boundary, 'view_id': id(view),
                        'denied': True, 'type': type(error).__name__, 'code': error.code.value})
                else:
                    proof['escaped_views'].append({'boundary': boundary, 'view_id': id(view), 'denied': False})
            with managed.authority(Capability.READ) as principal:
                epoch = f.governor.inspect(principal)['epoch']
            proof['actual_reconcile_epoch'] = epoch
            with managed.authority(Capability.COMMIT) as principal:
                proof['calls']['reconcile'] = task['route'].reconcile(principal, task['warrant'], epoch)
            settled = capture('after-independent-reconcile')
            proof['calls']['retained_dispatch'] = dispatch(task)
            with managed.authority(Capability.COMMIT) as principal:
                proof['calls']['retained_reconcile'] = task['route'].reconcile(principal, task['warrant'], epoch)
            final = capture('after-retained-controls')
            proof['phase'] = 'ALL_ACTUAL_FACTS_SAVED_BEFORE_QUALIFICATION'
            proof['callback_domain_IO'] = [item for item in proof['domain_calls'] if item['callback_active']]
            proof['callback_nonidentity_audit'] = [item for item in proof['callback_audit']
                                                   if not item['original_identity_guard']]
            proof['positive_outside_SQL_controls'] = {category: sum(
                item['category'] == category and not item['callback_active'] and not item['in_transaction_flag']
                for item in proof['domain_calls']) for category in ('source', 'Store')}
            calibration = proof['observer_calibration']
            case.assertTrue(calibration['outside_SQL_before'] and calibration['outside_SQL_after'])
            case.assertEqual(calibration['before'], calibration['observed'])
            case.assertEqual(calibration['before'], calibration['after'])
            case.assertEqual(calibration['admitted_source'], calibration['source_result'])
            case.assertEqual('NONE', calibration['observed']['authority'])
            case.assertTrue(all(not item['callback_active'] and not item['in_transaction_flag']
                and not item['db_transaction_active'] for item in calibration['domain_events']))
            for category in ('source', 'Store'):
                original = calibration['original_code_provenance'][category]
                case.assertEqual(category, original['registered_category'])
                case.assertTrue(any(item['category'] == category and item['function'] == original['function']
                                    for item in calibration['domain_events']))
            case.assertEqual({'authorize': 1, 'consume': 1}, proof['boundary_calls'])
            case.assertEqual(['authorize', 'consume'], [item['boundary'] for item in proof['faults']])
            case.assertTrue(all(item['before_original_commit'] and item['exact_original_callback_code']
                and item['db_transaction_active'] and not item['callback_active'] for item in proof['faults']))
            case.assertEqual(2, len(proof['legacy_calls']))
            case.assertTrue(all(item['exact_original_code'] for item in proof['legacy_calls']))
            case.assertEqual(2, len(proof['captures']))
            case.assertNotEqual(proof['captures'][0]['capture_id'], proof['captures'][1]['capture_id'])
            case.assertEqual([True, True], proof['captures_closed_after_boundaries'])
            case.assertEqual(0, proof['native_registry_after_dispatch'])
            for boundary in ('authorize', 'consume'):
                stages = [item for item in attempts if item['boundary'] == boundary]
                case.assertEqual([1, 2], [item['number'] for item in stages])
                authority = next(item for item in proof['captures'] if item['boundary'] == boundary)
                case.assertTrue(authority['outside_callback'] and not authority['in_transaction_flag']
                                and authority['same_Core'] and authority['same_runner'])
                case.assertEqual(Capability.COMMIT.value, authority['purpose'])
                case.assertEqual(NativeAccessUse.EXECUTION.value, authority['use'])
                case.assertNotEqual(stages[0]['view_id'], stages[1]['view_id'])
                case.assertNotEqual(stages[0]['adapter_id'], stages[1]['adapter_id'])
                case.assertEqual(stages[0]['entry_rows'], stages[1]['entry_rows'])
                for stage in stages:
                    case.assertEqual(authority['capture_id'], stage['capture_id'])
                    case.assertEqual(authority['principal_id'], stage['principal_id'])
                    case.assertTrue(all(stage[key] for key in ('same_context', 'same_factory',
                        'db_transaction_active', 'in_transaction_flag', 'previous_views_invalid',
                        'view_invalid_after_run', 'adapter_closed_after_run', 'history_products_cleared')))
                checks = [item for item in proof['capture_checks'] if item['boundary'] == boundary]
                case.assertTrue(checks)
                case.assertEqual({authority['capture_id']}, {item['capture_id'] for item in checks})
                case.assertEqual({authority['principal_id']}, {item['principal_id'] for item in checks})
                case.assertTrue(any(item['boundary'] == boundary and item['before_db_transaction']
                    and not item['after_db_transaction'] and item['view_invalid']
                    and item['history_products_cleared'] for item in proof['rollbacks']))
            case.assertEqual(2, len(proof['backoffs']))
            case.assertTrue(all(item['seconds'] == 0.01 and not item['callback_active']
                and item['in_transaction_flag'] and not item['db_transaction_active']
                and item['prior_view_invalid'] for item in proof['backoffs']))
            case.assertTrue(all(item['denied'] for item in proof['escaped_views']))
            case.assertEqual([], proof['callback_domain_IO'])
            case.assertEqual([], proof['callback_nonidentity_audit'])
            case.assertEqual([], proof['map_publications'])
            case.assertTrue(proof['identity_guard_calls'])
            case.assertTrue(all(count > 0 for count in proof['positive_outside_SQL_controls'].values()))
            case.assertEqual(1, len(candidate_objects))
            case.assertEqual(2, len(proof['release_observations']))
            case.assertEqual({id(candidate_objects[0])},
                             {item['observation_id'] for item in proof['release_observations']})
            case.assertEqual(1, proof['inner_consume_calls'])
            case.assertEqual(proof['original_ACK']['object_id'], proof['ACK_after_consume']['object_id'])
            case.assertIs(False, proof['original_ACK']['consumed_before_consume'])
            case.assertTrue(proof['ACK_after_consume']['ack_consumed'] and proof['ACK_after_consume']['release_consumed'])
            case.assertEqual([1, 1, 0], [a - b for a, b in zip(
                after['executor_counters'], before['executor_counters'], strict=True)])
            case.assertEqual('Unknown', proof['calls']['dispatch']['outcome']['contract_type'])
            joined = after['tasks'][task['task_id']]
            case.assertEqual('Unknown', joined['intent']['outcome']['contract_type'])
            case.assertIsNone(joined['intent']['resolution'])
            case.assertEqual('RELEASED', after['head']['in_flight']['phase'])
            case.assertIsNotNone(after['head']['in_flight']['ack'])
            case.assertEqual(task['facts']['warrant'], after['head']['in_flight']['warrant'])
            case.assertEqual('Applied', proof['calls']['reconcile']['outcome']['contract_type'])
            case.assertIs(False, proof['calls']['reconcile']['grants_replay'])
            case.assertEqual('NONE', proof['calls']['reconcile']['authority'])
            case.assertIsNone(settled['head']['in_flight'])
            case.assertEqual(before['head']['generation'] + 1, settled['head']['generation'])
            history = settled['histories'][task['warrant'].digest()]
            case.assertEqual(after['head']['in_flight']['write_observation'], history['write_observation'])
            case.assertNotIn('no_release_certificate', history)
            expected_governor = plain(after['governor'])
            expected_governor['version'] += 1
            case.assertGreaterEqual(settled['governor']['last_now'], expected_governor['last_now'])
            expected_governor['last_now'] = settled['governor']['last_now']
            expected_governor['reservations'][task['warrant'].risk_reservation_id].update(
                state='COMMITTED', evidence_digest=canonical_sha256(
                    Reconciliation.from_dict(settled['tasks'][task['task_id']]['intent']['resolution'])))
            case.assertEqual(expected_governor, settled['governor'])
            for name in ('job', 'session', 'context', 'ledger', 'owner_witness'):
                case.assertEqual(joined[name], settled['tasks'][task['task_id']][name])
            for value in (baseline, before, after, settled, final):
                case.assertIs(True, value['full_rows_match_summary'])
                case.assertIs(True, value['snapshot_outside_SQL'])
                case.assertEqual(value['raw_inventory']['envelope']['payload_sha256'], value['raw_inventory']['material_sha256'])
            case.assertEqual('STARTED', final['tasks'][task['task_id']]['job']['state'])
            case.assertIsNone(final['tasks'][task['task_id']]['job']['completion_proof'])
            case.assertEqual(settled['full_canonical_rows'], final['full_canonical_rows'])
            case.assertEqual(settled['raw_inventory'], final['raw_inventory'])
            case.assertEqual(after['executor_counters'], final['executor_counters'])
            case.assertIs(False, proof['calls']['retained_dispatch']['grants_replay'])
            case.assertEqual('Applied', proof['calls']['retained_dispatch']['outcome']['contract_type'])
            case.assertEqual('Applied', proof['calls']['retained_reconcile']['outcome']['contract_type'])
            case.assertEqual(0, h.model_calls())
            proof['phase'] = 'COMPLETE'
        except BaseException as error:
            proof['original_error'] = {'type': type(error).__name__, 'module': type(error).__module__,
                'code': str(error), 'traceback': [{'file': frame.filename, 'function': frame.name,
                    'line': frame.lineno} for frame in traceback.extract_tb(error.__traceback__, limit=32)]}
            raise
        finally:
            state['enabled'] = False
            sys.setprofile(old_profile)
            for attempt in attempts:
                for field in ('entry_rows', 'returned_rows'):
                    if field in attempt:
                        name = 'portable-sql-retry-' + attempt['boundary'] + '-' + str(attempt['number']) + '-' + field + '.json'
                        attempt[field] = self.legacy_capacity_save(name, attempt[field])
            self.retained['portable_sql_retry'] = self.legacy_capacity_save('native-portable-sql-retry-proof.json', proof)

    def portable_post_r103_boundary_assertions(self, case, *, scenario):
        import hashlib
        import json
        import traceback
        from pathlib import Path
        from unittest.mock import patch

        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import (
            canonical_json_bytes,
            canonical_sha256,
        )
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION, RecordKind
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        from runtime.mission.liability import Reconciliation
        from runtime.mission.portable_target import (
            CorePortableTarget,
            CorePortableWriteRelease,
        )
        from runtime.mission.warrant import WarrantError

        case.assertIn(scenario, ('EPOCH_BEFORE_AUTHORIZE', 'EPOCH_AFTER_AUTHORIZE',
                                'SESSION_AFTER_AUTHORIZE'))
        h, f, managed = self.host, self.host.foundation, self.host._native_coding
        target, tasks, cuts, witnesses = h.portable_target, [], [], []
        proof = {'schema': 'nz13.native-portable-post-r103-boundary.v1', 'scenario': scenario,
            'phase': 'INITIAL', 'snapshots': {}, 'calls': {}, 'cuts': cuts,
            'boundary_calls': {'authorize': 0, 'consume': 0}, 'live_original_witnesses': witnesses,
            'fixture_scope': 'FIXTURE_OS_ADMISSION_SYNTHETIC_TEST_ONLY',
            'model_certification': 'NOT_CERTIFIED', 'qualification': False,
            'finish_offline_job_not_called': True,
            'post_authorize_rule': 'Durable RELEASED is retained; equal inventory cannot issue NoRelease.',
            'epoch_post_scope': 'One already-admitted attempt remains UNKNOWN until independent original readback; '
                'this does not prove another route._check inside consume.'}
        def plain(value):
            return json.loads(canonical_json_bytes(value))
        def capture(name):
            value = self._portable_no_release_snapshot(tasks)
            proof['snapshots'][name] = self.legacy_capacity_save(
                'portable-post-r103-' + name + '.json', value)
            return value
        def errors(error):
            chain, seen = [], set()
            while error is not None and id(error) not in seen and len(chain) < 8:
                seen.add(id(error))
                chain.append({'type': type(error).__name__, 'module': type(error).__module__,
                    'code': str(error), 'frames': [{'file': item.filename, 'function': item.name,
                        'line': item.lineno} for item in traceback.extract_tb(error.__traceback__, limit=32)]})
                error = error.__cause__ if error.__cause__ is not None else error.__context__
            return chain
        def invoke(name, callback, *, independent_readback=False):
            try:
                value = {'returned': True, 'value': callback()}
            except WarrantError as error:
                proof['calls'][name] = {'returned': False, 'errors': errors(error)}
                if not independent_readback or str(error) != 'INDEPENDENT_READBACK_UNAVAILABLE':
                    raise
                return proof['calls'][name]
            proof['calls'][name] = value
            return value
        def dispatch(task):
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].dispatch(principal, session_id=task['session_id'],
                    warrant=task['warrant'], operation=task['operation'],
                    reservation=task['reservation'], completion=task['completion'])
        def reconcile(task):
            with managed.authority(Capability.READ) as principal:
                epoch = f.governor.inspect(principal)['epoch']
            proof.setdefault('actual_reconcile_epochs', []).append(epoch)
            with managed.authority(Capability.COMMIT) as principal:
                return task['route'].reconcile(principal, task['warrant'], epoch)
        def invalidate(task, cut):
            if scenario == 'SESSION_AFTER_AUTHORIZE':
                with managed.authority(Capability.MANAGE) as principal:
                    cut['original_revoke_result'] = task['route'].revoke_session(
                        principal, task['session_id'])
                return
            authority = f.access.capture(Capability.MANAGE, use=NativeAccessUse.CONTROL)
            try:
                f.access.require_capture(authority, Capability.MANAGE)
                cut['epoch_control'] = {'use': authority.use.value,
                    'purpose': authority.purpose.value, 'same_Core': authority.core is f.core,
                    'same_runner': authority.runner is f.runner,
                    'actor_session_id': authority.principal.actor_session_id}
                cut['original_start_epoch_result'] = f.governor.start_epoch(authority.principal)
                f.access.require_capture(authority, Capability.MANAGE)
            finally:
                authority.close()
                cut['epoch_capture_closed'] = authority._closed
        def new_cut(task, release, store, observed, candidate, acknowledgment=None):
            cut = {'boundary': 'AUTHORIZE_ENTRY_AFTER_ORIGINAL_SEAL' if scenario == 'EPOCH_BEFORE_AUTHORIZE'
                else 'ORIGINAL_AUTHORIZE_ACK_RETURNED_BEFORE_ORIGINAL_CONSUME',
                'outside_SQL': not bool(_IN_TRANSACTION.get()),
                'same_store': store is h.portable_store, 'same_target': release.adapter is target,
                'same_original_warrant': release.warrant is task['warrant'],
                'warrant_digest': release.warrant.digest(), 'before_state_root': observed.state_root,
                'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
                'caller_frames': [{'file': item.filename, 'function': item.name,
                    'line': item.lineno} for item in traceback.extract_stack(limit=24)]}
            if acknowledgment is not None:
                cut['original_ACK_before_consume'] = {'type': type(acknowledgment).__name__,
                    'same_release': acknowledgment.release is release,
                    'consumed': acknowledgment.consumed,
                    'observation': acknowledgment.observation.to_dict()}
            cuts.append(cut)
            capture('at-boundary-before-invalidation')
            invalidate(task, cut)
            capture('at-boundary-after-invalidation')
            return cut
        try:
            baseline = capture('baseline')
            _, domain = self._portable_a6_release_domain()
            task = self._portable_task(4, domain)
            tasks.append(task)
            proof['operation'] = task['facts']
            before = capture('before-cut')
            original_authorize = CorePortableWriteRelease.authorize_write
            original_consume = CorePortableWriteRelease.consume_write_ack
            def selected(release, store):
                return (release.adapter is target and store is h.portable_store
                    and release.warrant == task['warrant'])
            def at_authorize(release, store, observed, candidate):
                if not selected(release, store):
                    return original_authorize(release, store, observed, candidate)
                proof['boundary_calls']['authorize'] += 1
                if scenario == 'EPOCH_BEFORE_AUTHORIZE' and not cuts:
                    new_cut(task, release, store, observed, candidate)
                try:
                    acknowledgment = original_authorize(release, store, observed, candidate)
                except BaseException as error:
                    proof['original_authorize_errors'] = errors(error)
                    raise
                proof['original_authorize_ACK'] = {'type': type(acknowledgment).__name__,
                    'same_release': acknowledgment.release is release,
                    'consumed': acknowledgment.consumed,
                    'observation': acknowledgment.observation.to_dict()}
                return acknowledgment
            def at_consume(release, acknowledgment, store, observed, candidate):
                if not selected(release, store):
                    return original_consume(release, acknowledgment, store, observed, candidate)
                proof['boundary_calls']['consume'] += 1
                cut = (new_cut(task, release, store, observed, candidate, acknowledgment)
                       if not cuts else cuts[0])
                try:
                    result = original_consume(release, acknowledgment, store, observed, candidate)
                    cut['original_consume_returned'] = True
                    return result
                except BaseException as error:
                    cut['original_consume_returned'] = False
                    cut['original_consume_errors'] = errors(error)
                    raise
                finally:
                    cut['original_ACK_after_consume'] = {'consumed': acknowledgment.consumed,
                        'release_consumed': release._consumed,
                        'write_observation': None if release._write_observation is None
                        else release._write_observation.to_dict()}
            proof['phase'] = 'ORIGINAL_PHYSICAL_BOUNDARY'
            with patch.object(CorePortableWriteRelease, 'authorize_write', new=at_authorize), \
                    patch.object(CorePortableWriteRelease, 'consume_write_ack', new=at_consume):
                dispatched = invoke('cut_dispatch', lambda: dispatch(task))
            after = capture('after-cut')
            proof['prior_write_lifetime_exited'] = {
                'no_active_write_port': getattr(h.portable_store._held_lock, 'write_release', None) is None,
                'no_old_Core_guard_capture': getattr(h.portable_store._held_lock,
                    'core_no_release_capture', None) is None}
            original_verify = CorePortableTarget._verify_no_release
            def observe_no_release(adapter, operation, warrant):
                verified = original_verify(adapter, operation, warrant)
                if adapter is target and warrant == task['warrant']:
                    witness, certificate = verified._witness, verified.certificate
                    captured = witness.capture
                    witnesses.append({'same_certificate': witness.certificate is certificate,
                        'owns_outer_guard': captured.entry.owns_outer_lock,
                        'current_guard_capture': getattr(adapter.store._held_lock,
                            'core_no_release_capture', None) is captured,
                        'outside_SQL': not bool(_IN_TRANSACTION.get()),
                        'head_revision': captured.head_revision, 'intent_revision': captured.intent_revision,
                        'captured_head': json.loads(captured.head_bytes),
                        'captured_intent': json.loads(captured.intent_bytes),
                        'certificate': certificate.to_dict()})
                return verified
            proof['phase'] = 'FRESH_ORIGINAL_INDEPENDENT_READBACK'
            with patch.object(CorePortableTarget, '_verify_no_release', new=observe_no_release):
                settled = invoke('fresh_reconcile', lambda: reconcile(task), independent_readback=True)
            after_settle = capture('after-fresh-reconcile')
            if settled['returned']:
                invoke('retained_reconcile', lambda: reconcile(task))
            else:
                proof['retained_reconcile_not_attempted'] = 'FIRST_READBACK_REFUSED_NO_RETRY'
            invoke('retained_dispatch', lambda: dispatch(task))
            final = capture('after-retained-controls')
            proof['phase'] = 'ALL_ACTUAL_FACTS_SAVED_BEFORE_QUALIFICATION'
            observed_before = json.loads(self.context['safe'].read(
                Path(proof['snapshots']['at-boundary-before-invalidation']['path'])))
            observed_invalidated = json.loads(self.context['safe'].read(
                Path(proof['snapshots']['at-boundary-after-invalidation']['path'])))
            case.assertEqual(1, len(cuts))
            case.assertTrue(all(cuts[0][key] for key in (
                'outside_SQL', 'same_store', 'same_target', 'same_original_warrant')))
            case.assertEqual({'authorize': 1, 'consume': 0 if scenario == 'EPOCH_BEFORE_AUTHORIZE' else 1},
                             proof['boundary_calls'])
            for value in (baseline, before, observed_before, observed_invalidated, after, after_settle, final):
                case.assertIs(True, value['full_rows_match_summary'])
                case.assertIs(True, value['snapshot_outside_SQL'])
                case.assertEqual(value['raw_inventory']['envelope']['payload_sha256'],
                                 value['raw_inventory']['material_sha256'])
            case.assertIs(True, dispatched['returned'])
            case.assertEqual('Unknown', dispatched['value']['outcome']['contract_type'])
            case.assertTrue(all(proof['prior_write_lifetime_exited'].values()))
            old_rows, invalidated_rows = (observed_before['full_canonical_rows'],
                                         observed_invalidated['full_canonical_rows'])
            changed = {key for key in old_rows.keys() & invalidated_rows.keys()
                       if old_rows[key] != invalidated_rows[key]}
            inserted = invalidated_rows.keys() - old_rows.keys()
            case.assertFalse(old_rows.keys() - invalidated_rows.keys())
            if scenario == 'SESSION_AFTER_AUTHORIZE':
                session_key = RecordKind.OPERATION.value + ':' + task['route'].session_key(task['session_id'])
                case.assertEqual({session_key}, changed)
                case.assertFalse(inserted)
                case.assertEqual(old_rows[session_key]['revision'] + 1, invalidated_rows[session_key]['revision'])
                expected_session = plain(old_rows[session_key]['payload'])
                expected_session['revoked'] = True
                case.assertEqual(expected_session, invalidated_rows[session_key]['payload'])
                case.assertEqual(observed_before['governor'], observed_invalidated['governor'])
            else:
                case.assertFalse(changed)
                case.assertEqual(3, len(inserted))
                case.assertEqual(sorted((RecordKind.OPERATION.value, RecordKind.AUDIT.value, RecordKind.OUTBOX.value)),
                                 sorted(key.split(':', 1)[0] for key in inserted))
                expected_governor = plain(observed_before['governor'])
                expected_governor['epoch'] += 1
                expected_governor['version'] += 1
                case.assertGreaterEqual(observed_invalidated['governor']['last_now'], expected_governor['last_now'])
                expected_governor['last_now'] = observed_invalidated['governor']['last_now']
                for circuit in expected_governor['circuits'].values():
                    if circuit['state'] == 'HALF_OPEN':
                        circuit.update(state='OPEN', opened_at=expected_governor['last_now'], probe=None, successes=0)
                case.assertEqual(expected_governor, observed_invalidated['governor'])
                case.assertEqual(expected_governor['epoch'], cuts[0]['original_start_epoch_result'])
                case.assertEqual([expected_governor['epoch']], proof['actual_reconcile_epochs'][:1])
                case.assertIs(True, cuts[0]['epoch_capture_closed'])
            joined = after['tasks'][task['task_id']]
            case.assertEqual('Unknown', joined['intent']['outcome']['contract_type'])
            case.assertIsNone(joined['intent']['resolution'])
            case.assertEqual('STARTED', joined['job']['state'])
            case.assertIsNone(joined['job']['completion_proof'])
            case.assertEqual(task['facts']['warrant'], after['head']['in_flight']['warrant'])
            case.assertEqual(task['warrant'].digest(), after['head']['in_flight']['warrant_digest'])
            if scenario == 'EPOCH_BEFORE_AUTHORIZE':
                case.assertTrue(any(value['code'] == 'STALE_EPOCH'
                                    for value in proof['original_authorize_errors']))
                case.assertEqual('STARTED', after['head']['in_flight']['phase'])
                case.assertIsNone(after['head']['in_flight']['write_observation'])
                case.assertIsNone(after['head']['in_flight']['ack'])
                case.assertEqual([1, 0, 0], [a - b for a, b in zip(
                    after['executor_counters'], before['executor_counters'], strict=True)])
                case.assertEqual(before['raw_inventory'], after['raw_inventory'])
                case.assertIs(True, settled['returned'], 'NATIVE_EPOCH_DENIAL_REQUIRES_FRESH_NO_RELEASE')
                case.assertEqual('NotApplied', settled['value']['outcome']['contract_type'])
                case.assertEqual(1, len(witnesses))
                case.assertTrue(all(witnesses[0][key] for key in (
                    'same_certificate', 'owns_outer_guard', 'current_guard_capture', 'outside_SQL')))
                case.assertEqual(after['head'], witnesses[0]['captured_head'])
                case.assertEqual(joined['intent'], witnesses[0]['captured_intent'])
                case.assertEqual(witnesses[0]['certificate'],
                    after_settle['histories'][task['warrant'].digest()]['no_release_certificate'])
            elif scenario == 'SESSION_AFTER_AUTHORIZE':
                case.assertEqual([1, 0, 0], [a - b for a, b in zip(
                    after['executor_counters'], before['executor_counters'], strict=True)],
                    'NATIVE_PORTABLE_REVOKED_SESSION_MUST_BLOCK_PHYSICAL_WRITE')
                case.assertEqual(before['raw_inventory'], after['raw_inventory'])
                case.assertEqual('RELEASED', after['head']['in_flight']['phase'])
                case.assertIsNotNone(after['head']['in_flight']['write_observation'])
                case.assertIsNone(after['head']['in_flight']['ack'])
                case.assertFalse(cuts[0]['original_ACK_after_consume']['consumed'])
                case.assertIs(False, settled['returned'])
                case.assertEqual('INDEPENDENT_READBACK_UNAVAILABLE', settled['errors'][0]['code'])
                case.assertEqual([], witnesses)
                case.assertEqual(after['full_canonical_rows'], after_settle['full_canonical_rows'])
                case.assertEqual('UNKNOWN', after_settle['governor']['reservations'][task['warrant'].risk_reservation_id]['state'])
            else:
                # A6 preserves actual UNKNOWN after durable RELEASED. The original ACK
                # grants one attempt; only independent verified readback may settle it.
                case.assertEqual([1, 1, 0], [a - b for a, b in zip(
                    after['executor_counters'], before['executor_counters'], strict=True)])
                case.assertEqual('RELEASED', after['head']['in_flight']['phase'])
                case.assertIsNotNone(after['head']['in_flight']['write_observation'])
                case.assertIsNotNone(after['head']['in_flight']['ack'])
                case.assertIs(True, cuts[0]['original_ACK_after_consume']['consumed'])
                case.assertNotEqual(before['raw_inventory']['sha256'], after['raw_inventory']['sha256'])
                case.assertIs(True, settled['returned'])
                case.assertEqual('Applied', settled['value']['outcome']['contract_type'])
                case.assertEqual([], witnesses)
                history = after_settle['histories'][task['warrant'].digest()]
                case.assertEqual(after['head']['in_flight']['write_observation'], history['write_observation'])
                case.assertNotIn('no_release_certificate', history)
            if settled['returned']:
                case.assertIs(False, settled['value']['grants_replay'])
                case.assertEqual('NONE', settled['value']['authority'])
                case.assertIsNone(after_settle['head']['in_flight'])
                expected_governor = plain(after['governor'])
                expected_governor['version'] += 1
                case.assertGreaterEqual(after_settle['governor']['last_now'], expected_governor['last_now'])
                expected_governor['last_now'] = after_settle['governor']['last_now']
                expected_governor['reservations'][task['warrant'].risk_reservation_id].update(
                    state='COMMITTED', evidence_digest=canonical_sha256(
                        Reconciliation.from_dict(after_settle['tasks'][task['task_id']]['intent']['resolution'])))
                case.assertEqual(expected_governor, after_settle['governor'])
                settlement_before, settlement_after = after['full_canonical_rows'], after_settle['full_canonical_rows']
                changed = {key for key in settlement_before.keys() & settlement_after.keys()
                           if settlement_before[key] != settlement_after[key]}
                intent_key = f.intent_journal._key(task['warrant'])
                case.assertEqual({RecordKind.OPERATION.value + ':' + f.target_projection.head_key,
                    RecordKind.OPERATION.value + ':' + f.liability._key(task['task_id']),
                    RecordKind.OPERATION.value + ':' + intent_key, RecordKind.OUTBOX.value + ':' + intent_key}, changed)
                case.assertFalse(settlement_before.keys() - settlement_after.keys())
                case.assertEqual(4, len(settlement_after.keys() - settlement_before.keys()))
                for name in ('job', 'session', 'context', 'ledger', 'owner_witness'):
                    case.assertEqual(joined[name], after_settle['tasks'][task['task_id']][name])
            case.assertEqual('STARTED', final['tasks'][task['task_id']]['job']['state'])
            case.assertIsNone(final['tasks'][task['task_id']]['job']['completion_proof'])
            case.assertEqual(after_settle['full_canonical_rows'], final['full_canonical_rows'])
            case.assertEqual(after_settle['raw_inventory'], final['raw_inventory'])
            case.assertEqual(after['executor_counters'], final['executor_counters'])
            case.assertIs(True, proof['calls']['retained_dispatch']['returned'])
            case.assertIs(False, proof['calls']['retained_dispatch']['value']['grants_replay'])
            case.assertEqual(0, h.model_calls())
            proof['phase'] = 'COMPLETE'
        finally:
            self.retained['portable_post_r103'] = self.legacy_capacity_save(
                'native-portable-post-r103-boundary-proof.json', proof)

    def portable_source_after_capture_assertions(self, case, *, mutate_export):
        import hashlib
        import os
        import stat
        import sys
        import time
        import traceback
        from dataclasses import asdict
        from pathlib import Path
        from unittest.mock import patch

        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
        from runtime.meta_hackathon.native_authority import (
            NativeAccessUse,
            NativeAuthorityCapture,
        )
        from runtime.mission.patchset import _snapshot
        from runtime.mission.portable_target import CorePortableWriteRelease
        from runtime.mission.warrant import WarrantError

        h, f, managed = self.host, self.host.foundation, self.host._native_coding
        target, store, tasks, cuts = h.portable_target, h.portable_store, [], []
        proof = {'schema': 'nz13.native-portable-source-after-capture.v1',
            'scenario': 'OWNED_EXPORT_A_TO_B' if mutate_export else 'UNCHANGED_EXPORT_A',
            'phase': 'INITIAL', 'snapshots': {}, 'calls': {}, 'cuts': cuts,
            'fixture_scope': 'FIXTURE_OS_ADMISSION_SYNTHETIC_TEST_ONLY',
            'model_certification': 'NOT_CERTIFIED', 'qualification': False,
            'finish_offline_job_not_called': True, 'effect_dispatch_calls': 0,
            'original_consume_calls': 0, 'selected_original_capture_calls': 0,
            'source_W_or_policy_clock_TTL_changes': False}
        base = Path(self.body['base_root'])
        path = base / 'src/textutil.py'
        original = self.context['safe'].read(path, maximum=1048576)
        info = self.context['safe'].info(path)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_uid, s.st_gid,
                              s.st_nlink, stat.S_IMODE(s.st_mode))
        expected_identity = identity(info)
        case.assertTrue(stat.S_ISREG(info.st_mode))
        case.assertEqual((os.getuid(), 1, 0o644), (info.st_uid, info.st_nlink, stat.S_IMODE(info.st_mode)))
        replacement = b'def slug(text):\n    return text.strip().upper()\n'
        case.assertNotEqual(original, replacement)
        compile(replacement, '<owned-source-at-write-B>', 'exec', dont_inherit=True)
        source_a = _snapshot(base)
        case.assertEqual(f.spec.source_snapshot.export_tree_sha256, source_a.digest)
        f.spec.source_snapshot.verify_export(base)
        composition_before = f.spec.to_dict()
        mutation_started = False
        selected_capture = []
        def errors(error):
            values, seen = [], set()
            while error is not None and id(error) not in seen and len(values) < 8:
                seen.add(id(error))
                values.append({'type': type(error).__name__, 'module': type(error).__module__,
                    'code': str(error), 'frames': [{'file': z.filename, 'function': z.name,
                        'line': z.lineno} for z in traceback.extract_tb(error.__traceback__, limit=32)]})
                error = error.__cause__ if error.__cause__ is not None else error.__context__
            return values
        def tree_value(tree):
            return {'digest': tree.digest, 'files': {name: asdict(file.identity)
                    for name, file in sorted(tree.files.items())}}
        def save(name, value):
            return self.legacy_capacity_save('portable-source-at-write-' + name + '.json', value)
        def capture(name):
            value = self._portable_no_release_snapshot(tasks)
            proof['snapshots'][name] = save(name, value)
            return value
        def write_export(raw):
            # Literal guarded writer seam already used by source_generation_restore_observation.
            case.assertFalse(_IN_TRANSACTION.get())
            self.context['strict_path_guard'](path)
            parent_fd, leaf = self.context['safe'].parent(path)
            descriptor = None
            try:
                descriptor = os.open(leaf, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent_fd)
                before = os.fstat(descriptor)
                named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                case.assertEqual(expected_identity, identity(before))
                case.assertEqual(identity(before), identity(named))
                case.assertTrue(stat.S_ISREG(before.st_mode) and stat.S_ISREG(named.st_mode))
                os.ftruncate(descriptor, 0)
                offset = 0
                while offset < len(raw):
                    count = os.write(descriptor, raw[offset:])
                    case.assertGreater(count, 0)
                    offset += count
                os.fsync(descriptor)
                after = os.fstat(descriptor)
                named_after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                case.assertEqual(expected_identity, identity(after))
                case.assertEqual(identity(after), identity(named_after))
                case.assertTrue(stat.S_ISREG(after.st_mode) and stat.S_ISREG(named_after.st_mode))
                case.assertEqual((len(raw), len(raw)), (after.st_size, named_after.st_size))
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                os.close(parent_fd)
            case.assertEqual(raw, self.context['safe'].read(path, maximum=1048576))
        def artifact(name, raw):
            out = self.root / name
            self.context['safe'].write_new(out, raw)
            return {'path': str(out), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        def isolation(captured):
            wall, mono = time.time(), time.monotonic()
            value = {'wall': wall, 'monotonic': mono,
                'claim_until': task['claim'].lease_until,
                'session_until': task['facts']['grant']['expires_at'],
                'warrant_until': task['warrant'].expires_at.timestamp(),
                'envelope_until': task['facts']['envelope']['deadline_at'],
                'principal_until': captured.principal.expires_at.timestamp(),
                'native_auth_monotonic_until': captured.auth_deadline,
                'TLS_until': h._tls_expires, 'TLS_verified': h.tls_verified,
                'source': list(h.source), 'composition_digest': f.spec.digest,
                'phase': f.lifecycle.phase.value,
                'admission_generation': f.lifecycle.admission_generation,
                'composition_generation': f.lifecycle.composition_generation,
                'fence_sequence': f.lifecycle.fence_sequence}
            value['all_other_deadlines_live'] = (wall < min(value[k] for k in
                ('claim_until', 'session_until', 'warrant_until', 'envelope_until', 'principal_until', 'TLS_until'))
                and mono < value['native_auth_monotonic_until'] and value['TLS_verified'] is True
                and not captured._closed and captured.source == h.source)
            return value
        def fresh_read(cut):
            observed, authority = {'purpose': 'READ', 'use': 'READ',
                'outside_SQL': not bool(_IN_TRANSACTION.get()), 'returned': False,
                'capture_created': False}, None
            cut['fresh_READ'] = observed
            try:
                authority = f.access.capture(Capability.READ, use=NativeAccessUse.READ)
                observed['capture_created'] = True
                f.access.require_capture(authority, Capability.READ)
                observed['returned'] = True
            except BaseException as error:
                observed['errors'] = errors(error)
                observed['original_source_drift'] = (type(error) is WarrantError
                    and str(error) == 'GIT_SOURCE_EXPORT_DRIFT')
                if not (mutate_export and observed['original_source_drift']):
                    raise
            finally:
                if authority is not None:
                    authority.close()
                    observed['capture_closed'] = authority._closed
            if mutate_export and observed['returned']:
                proof['isolation_error'] = 'NATIVE_SOURCE_AT_WRITE_EXPECTED_REAL_SOURCE_READ_DENIAL'
                raise RuntimeError(proof['isolation_error'])
        try:
            baseline = capture('baseline')
            _, domain = self._portable_a6_release_domain()
            task = self._portable_task(4, domain)
            tasks.append(task)
            proof['operation'] = task['facts']
            proof['source_A'] = tree_value(source_a)
            proof['A_data'] = artifact('portable-source-at-write-A.txt', original)
            proof['B_data'] = artifact('portable-source-at-write-B.txt', replacement)
            before = capture('before-dispatch')
            original_capture = type(f.access).capture
            original_consume = CorePortableWriteRelease.consume_write_ack
            selected_release = []
            def observe_capture(access, purpose, *, use):
                nonlocal mutation_started
                caller = sys._getframe(1)
                selected = (access is f.access and purpose is Capability.COMMIT
                    and use is NativeAccessUse.EXECUTION and caller.f_code is original_consume.__code__
                    and selected_release and caller.f_locals.get('self') is selected_release[0])
                captured = original_capture(access, purpose, use=use)
                if not selected:
                    return captured
                proof['selected_original_capture_calls'] += 1
                selected_capture.append(captured)
                release = selected_release[0]
                cut = {'outside_SQL': not bool(_IN_TRANSACTION.get()),
                    'boundary': 'ORIGINAL_EXECUTION_CAPTURE_RETURNED_BEFORE_REMAINING_ORIGINAL_CONSUME',
                    'same_store': store is h.portable_store, 'same_target': release.adapter is target,
                    'same_warrant_object': release.warrant is task['warrant'],
                    'original_capture_type': type(captured).__module__ + '.' + type(captured).__name__,
                    'registered_original_capture': type(captured) is NativeAuthorityCapture
                        and f.access._originals.get(id(captured), (None,))[0] is captured,
                    'capture_purpose': captured.purpose.value, 'capture_use': captured.use.value,
                    'captured_at': captured.captured_at.isoformat(), 'monotonic_at': captured.monotonic_at,
                    'native_revision': captured.native_revision, 'native_digest': captured.native_digest,
                    'capture_source': list(captured.source), 'capture_composition_digest': captured.composition_digest,
                    'original_capture_called_once_for_this_boundary': True,
                    'same_capture_returned_to_original_consume': True,
                    'caller_is_original_consume_CodeType': True,
                    'source_A_before_mutation': tree_value(_snapshot(base)),
                    'TLS_principal_before': isolation(captured)}
                cuts.append(cut)
                try:
                    # A is physically checked and the real original capture already exists before mutation.
                    f.spec.source_snapshot.verify_export(base)
                    cut['before_mutation_snapshot'] = capture('capture-returned-before-mutation')
                    if mutate_export:
                        mutation_started = True
                        write_export(replacement)
                    actual = _snapshot(base)
                    cut['actual_tree_during_original_consume'] = tree_value(actual)
                    cut['mutation_performed'] = mutate_export
                    cut['physical_B_preserved_before_original_consume'] = save('physical-source-at-cut', {
                        'path': str(path), 'A': proof['source_A'], 'current': tree_value(actual),
                        'A_data': proof['A_data'], 'B_data': proof['B_data'],
                        'composition_unchanged': f.spec.to_dict() == composition_before,
                        'unchanged_raw_file_identity': list(identity(self.context['safe'].info(path)))})
                    fresh_read(cut)
                    cut['TLS_principal_before_remaining_original_consume'] = isolation(captured)
                    if not (cut['TLS_principal_before']['all_other_deadlines_live']
                            and cut['TLS_principal_before_remaining_original_consume']['all_other_deadlines_live']):
                        proof['isolation_error'] = 'NATIVE_SOURCE_AT_WRITE_OTHER_AUTHORITY_EXPIRED'
                        raise RuntimeError(proof['isolation_error'])
                    proof['cut_before_original_consume_saved'] = save('cut-before-remaining-consume', cut)
                except BaseException as error:
                    proof.setdefault('isolation_error', 'NATIVE_SOURCE_AT_WRITE_OBSERVER_FAILED_BEFORE_CONSUME')
                    cut['observer_error'] = errors(error)
                    captured.close()
                    cut['observer_closed_unreturned_capture'] = captured._closed
                    raise
                return captured
            def observe_consume(release, acknowledgment, actual_store, observed, candidate):
                if not (release.adapter is target and actual_store is store and release.warrant is task['warrant']):
                    return original_consume(release, acknowledgment, actual_store, observed, candidate)
                proof['original_consume_calls'] += 1
                selected_release.append(release)
                proof['ACK_before'] = {'consumed': acknowledgment.consumed,
                    'same_release': acknowledgment.release is release,
                    'warrant_digest': release.warrant.digest()}
                try:
                    value = original_consume(release, acknowledgment, actual_store, observed, candidate)
                    proof['original_consume_returned'] = True
                    return value
                except BaseException as error:
                    proof['original_consume_returned'] = False
                    proof['original_consume_errors'] = errors(error)
                    raise
                finally:
                    proof['ACK_after'] = {'consumed': acknowledgment.consumed,
                        'release_consumed': release._consumed,
                        'write_observation': release._write_observation.to_dict()
                            if release._write_observation is not None else None}
            proof['phase'] = 'ORIGINAL_DISPATCH_CAPTURE_SOURCE_CUT'
            try:
                with patch.object(type(f.access), 'capture', new=observe_capture), \
                        patch.object(CorePortableWriteRelease, 'consume_write_ack', new=observe_consume):
                    proof['effect_dispatch_calls'] += 1
                    with managed.authority(Capability.COMMIT) as principal:
                        try:
                            dispatched = task['route'].dispatch(principal, session_id=task['session_id'],
                                warrant=task['warrant'], operation=task['operation'],
                                reservation=task['reservation'], completion=task['completion'])
                        except WarrantError as error:
                            proof['calls']['dispatch'] = {'returned': False, 'errors': errors(error)}
                            if not (mutate_export and type(error) is WarrantError
                                    and str(error) == 'GIT_SOURCE_EXPORT_DRIFT'):
                                raise
                            proof['late_original_source_drift_after_ACK_saved_not_early_denial'] = True
                        else:
                            proof['calls']['dispatch'] = {'returned': True, 'value': dispatched}
            finally:
                proof['capture_closed_after_original_dispatch'] = [value._closed for value in selected_capture]
                proof['actual_executor_counters_before_A_cleanup'] = list(h.portable_executor.counters())
                if mutation_started:
                    proof['B_tree_before_cleanup'] = tree_value(_snapshot(base))
                    self.retained['portable_source_before_cleanup'] = save('B-before-A-cleanup', proof)
                    write_export(original)
                    proof['explicit_A_cleanup'] = {'after': tree_value(_snapshot(base)),
                        'raw_mode': stat.S_IMODE(self.context['safe'].info(path).st_mode),
                        'no_phase_epoch_authority_or_cache_reset': True}
            f.spec.source_snapshot.verify_export(base)
            after = capture('after-explicit-A-cleanup-new-READ')
            delta = [a - b for a, b in zip(after['executor_counters'], before['executor_counters'], strict=True)]
            proof['physical_counter_delta'] = delta
            if not mutate_export or (delta == [1, 0, 0] and proof['ACK_after']['consumed'] is False):
                with managed.authority(Capability.READ) as principal:
                    epoch = f.governor.inspect(principal)['epoch']
                try:
                    with managed.authority(Capability.COMMIT) as principal:
                        value = task['route'].reconcile(principal, task['warrant'], epoch)
                    proof['calls']['fresh_readback'] = {'returned': True, 'value': value}
                except WarrantError as error:
                    proof['calls']['fresh_readback'] = {'returned': False, 'errors': errors(error)}
                    if not (mutate_export and str(error) == 'INDEPENDENT_READBACK_UNAVAILABLE'):
                        raise
            else:
                proof['fresh_reconcile_not_attempted'] = 'UNEXPECTED_ACK_OR_EFFECT_PRESERVE_UNKNOWN_NO_SETTLEMENT'
            final = capture('final-new-READ-no-resend')
            proof['phase'] = 'ALL_ACTUAL_FACTS_SAVED_BEFORE_LATE_ASSERTIONS'
            case.assertNotIn('isolation_error', proof, 'NATIVE_SOURCE_AT_WRITE_ISOLATION_FAILURE_NOT_PRODUCT_RED')
            case.assertEqual(1, proof['effect_dispatch_calls'])
            case.assertEqual(1, proof['original_consume_calls'])
            case.assertEqual(1, proof['selected_original_capture_calls'])
            case.assertEqual(1, len(cuts))
            cut = cuts[0]
            case.assertTrue(all(cut[k] for k in ('outside_SQL', 'same_store', 'same_target',
                'same_warrant_object', 'registered_original_capture', 'same_capture_returned_to_original_consume')))
            case.assertTrue(cut['TLS_principal_before']['all_other_deadlines_live'])
            case.assertTrue(cut['TLS_principal_before_remaining_original_consume']['all_other_deadlines_live'])
            case.assertTrue(all(proof['capture_closed_after_original_dispatch']))
            case.assertEqual(proof['source_A'], cut['source_A_before_mutation'])
            case.assertEqual(composition_before, f.spec.to_dict())
            case.assertEqual(task['facts']['claim'], after['tasks'][task['task_id']]['job']['claim'])
            case.assertEqual('STARTED', final['tasks'][task['task_id']]['job']['state'])
            case.assertIsNone(final['tasks'][task['task_id']]['job']['completion_proof'])
            case.assertEqual(0, h.model_calls())
            for value in (baseline, before, after, final):
                case.assertIs(True, value['full_rows_match_summary'])
                case.assertIs(True, value['snapshot_outside_SQL'])
            if mutate_export:
                case.assertEqual({'src/textutil.py'}, {name for name in proof['source_A']['files']
                    if proof['source_A']['files'][name] != cut['actual_tree_during_original_consume']['files'][name]})
                case.assertNotEqual(source_a.digest, cut['actual_tree_during_original_consume']['digest'])
                case.assertIs(True, cut['fresh_READ']['original_source_drift'])
                case.assertEqual([1, 0, 0], delta,
                    'NATIVE_PORTABLE_CHANGED_SOURCE_AFTER_CAPTURE_MUST_BLOCK_PHYSICAL_WRITE')
                case.assertIs(False, proof['ACK_after']['consumed'],
                    'NATIVE_SOURCE_DRIFT_MUST_DENY_BEFORE_ACK_CONSUMPTION_NOT_ONLY_LATE_MARKER')
                case.assertIs(False, proof['original_consume_returned'])
                case.assertTrue(any(value['code'] == 'GIT_SOURCE_EXPORT_DRIFT'
                    and any(frame['function'] == 'verify_export' for frame in value['frames'])
                    for value in proof.get('original_consume_errors', ())),
                    'ORIGINAL_CONSUME_MUST_DENY_SOURCE_DRIFT_NOT_EXPIRED_CLAIM_OR_ONLY_FRESH_READ')
                case.assertEqual(before['raw_inventory'], after['raw_inventory'])
                case.assertEqual(proof['source_A'], proof['explicit_A_cleanup']['after'])
                case.assertEqual('RELEASED', final['head']['in_flight']['phase'])
                case.assertIsNone(final['head']['in_flight']['ack'])
                case.assertEqual('Unknown', final['tasks'][task['task_id']]['intent']['outcome']['contract_type'])
                case.assertIsNone(final['tasks'][task['task_id']]['intent']['resolution'])
                case.assertIs(False, proof['calls']['fresh_readback']['returned'])
            else:
                case.assertIs(False, cut['mutation_performed'])
                case.assertEqual(proof['source_A'], cut['actual_tree_during_original_consume'])
                case.assertIs(True, cut['fresh_READ']['returned'])
                case.assertIs(True, cut['fresh_READ']['capture_closed'])
                case.assertEqual([1, 1, 0], delta, 'UNCHANGED_SOURCE_MUST_ALLOW_ONE_ORIGINAL_WRITE')
                case.assertIs(True, proof['ACK_after']['consumed'])
                case.assertIs(True, proof['original_consume_returned'])
                case.assertEqual('Applied', proof['calls']['fresh_readback']['value']['outcome']['contract_type'])
                case.assertIs(False, proof['calls']['fresh_readback']['value']['grants_replay'])
                case.assertEqual('NONE', proof['calls']['fresh_readback']['value']['authority'])
            case.assertEqual(after['executor_counters'], final['executor_counters'])
            proof['phase'] = 'COMPLETE'
        except BaseException as error:
            proof['primary_or_late_error'] = errors(error)
            raise
        finally:
            self.retained['portable_source_at_write'] = save('proof', proof)



def make_owned_fixture(case):
    return NativeOwnedFixture(case)


class NativeRestartFixture(NativeOwnedFixture):
    """Actual fresh Native over a closed retained namespace; no admin bootstrap."""

    def __init__(self, case):
        import json
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import nz13_native_foundation_support as foundation_fixture
        from runtime.meta_hackathon import runtime_adapter
        from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
        from runtime.mission.worker import CandidateFile, CandidatePatch, Task

        case.assertIsNotNone(ACTUAL_CONTEXT)
        context = ACTUAL_CONTEXT
        handoff = context['restart_handoff']
        case.assertEqual('nz13.native-owned-restart-handoff.v1', handoff['schema'])
        self.case, self.context, self.handoff = case, context, handoff
        self.root = Path(handoff['fixture_root'])
        self.native_root = Path(handoff['native_root'])
        self.runtime_tmp = Path(handoff['runtime_tmp'])
        self.origin = handoff['origin']
        self.body = json.loads(json.dumps(context['restart_reopen_body']))
        original_body = json.loads(json.dumps(handoff['host_config']))
        expected_body = json.loads(json.dumps(original_body))
        expected_body['retained_sandbox_task_ids'] = list(handoff['produced_sandbox_task_ids'])
        if handoff['scenario'] == 'NEWER_LIMITS_RECEIPT':
            case.assertEqual(3600, expected_body['limits_plan']['max_duration_seconds'])
            expected_body['limits_plan']['max_duration_seconds'] = 1800
        case.assertEqual(expected_body, self.body)
        self.retained = {}
        self.task = Task(**handoff['task'])
        self.candidates = tuple(CandidatePatch(tuple(CandidateFile(**file) for file in files))
                                for files in handoff['offline_candidates'])
        for path in (self.root, self.native_root, self.runtime_tmp):
            context['owned_roots'].add(path)
            OWNED_ROOTS.append(str(path))
        old_tmp = tempfile.tempdir
        tempfile.tempdir = str(self.runtime_tmp)
        case.addCleanup(setattr, tempfile, 'tempdir', old_tmp)
        with patch.object(runtime_adapter, '_desktop_operator_uid', return_value=(os.getuid(),
                {'uid': os.getuid(), 'method': 'FIXTURE_OS_ADMISSION'})):
            self.host = runtime_adapter.NativeMobileComposition(self.native_root, origin=self.origin,
                existing_profile=True, host_composition=NativeHostCompositionConfig.from_dict(self.body),
                offline_candidates=self.candidates)
        case.addCleanup(self.close)
        foundation_fixture.fixture_tls(self.host)

    def old_capacity_receipt_after_newer_limits_observation(self, case):
        import hashlib
        import json
        import os
        from pathlib import Path

        h, f = self.host, self.host.foundation
        prior_ref = self.handoff['observations']['snapshot']
        prior_path = Path(prior_ref['path'])
        case.assertEqual(self.root / 'native-newer-limits-os1-before.json', prior_path)
        raw = self.context['safe'].read(prior_path, maximum=4 * 1024 * 1024)
        case.assertEqual(prior_ref['bytes'], len(raw))
        case.assertEqual(prior_ref['sha256'], hashlib.sha256(raw).hexdigest())
        before = self.legacy_capacity_snapshot()
        actual_spec = f.spec.to_dict()
        actual_digest = f.spec.digest
        phase_before = f.lifecycle.phase.value
        public_request = {'op': 'execution_capacity_status',
                          'request_id': self.handoff['observations']['capacity_request_id']}
        receipt = h.operator_request(os.getuid(), public_request)
        after = self.legacy_capacity_snapshot()
        before_ref = self.legacy_capacity_save('native-newer-limits-os2-before.json', before)
        after_ref = self.legacy_capacity_save('native-newer-limits-os2-after-read.json', after)
        observed = {'schema': 'aioa.native-newer-limits-reopen.v1', 'qualification': False,
            'scenario': 'NEWER_LIMITS_RECEIPT', 'pid': os.getpid(),
            'old_pid': self.handoff['producer_pid'], 'old_instance_id': self.handoff['old_instance_id'],
            'new_instance_id': h.instance_id, 'old_source': self.handoff['old_source'],
            'fresh_source': list(h.source), 'prior_snapshot': prior_ref,
            'before_snapshot': before_ref, 'after_snapshot': after_ref,
            'actual_spec_config': actual_spec, 'actual_spec_digest': actual_digest,
            'phase_before_public_read': phase_before, 'phase_after_public_read': f.lifecycle.phase.value,
            'public_request': public_request, 'public_receipt': receipt,
            'job_observation': h._native_coding.job_observation(), 'model_calls': h.model_calls(),
            'host_preparations': {name: len(getattr(h._native_coding, name))
                                  for name in ('materializations', 'jobs', 'runs', 'effects')},
            'active_tasks': sorted(h.coding_tasks._active), 'owned_effect_tasks': sorted(h.coding_tasks._effect_ownership)}
        output = self.context['fixture_root'] / 'native-restart-reopen-observation.json'
        raw = json.dumps(observed, sort_keys=True).encode()
        self.context['safe'].write_new(output, raw)
        result = {'path': str(output), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        self.retained.update(restart_observation=result, newer_limits_os2_before=before_ref,
                             newer_limits_os2_after=after_ref)
        return result

    def legacy_v1_capacity_restart_observation(self, case):
        import hashlib
        import json
        from pathlib import Path

        import nz13_native_foundation_support as foundation_fixture

        h, f = self.host, self.host.foundation
        original_governor, original_policy = f.governor, f.governor.policy
        old_ref = self.handoff['observations']['snapshot']
        old_path = Path(old_ref['path'])
        case.assertEqual(self.root / 'native-legacy-capacity-os1-before.json', old_path)
        raw = self.context['safe'].read(old_path, maximum=4 * 1024 * 1024)
        case.assertEqual(old_ref['bytes'], len(raw))
        case.assertEqual(old_ref['sha256'], hashlib.sha256(raw).hexdigest())
        prior = json.loads(raw)
        before = self.legacy_capacity_snapshot()
        module, legacy, origin = self.legacy_reader_load()
        old_before = self.legacy_reader_observe(module, legacy)
        before_ref = self.legacy_capacity_save('native-legacy-capacity-os2-before.json', before)
        reviewed = foundation_fixture.review(h)
        foundation_fixture.approve(h, reviewed)
        applied = foundation_fixture.apply(h, reviewed)
        after = self.legacy_capacity_snapshot()
        after_ref = self.legacy_capacity_save('native-legacy-capacity-os2-after.json', after)
        old_after = self.legacy_reader_observe(module, legacy, expect_capacity=True)
        final = self.legacy_capacity_snapshot()
        final_ref = self.legacy_capacity_save('native-legacy-capacity-os2-after-old-read.json', final)
        old_rows = prior['rows']
        current_before = before['rows']
        new_admission = before['business']['fresh_admission_rows']
        observations = {'schema': 'aioa.native-legacy-capacity-reopen.v1',
            'qualification': False, 'scenario': 'LEGACY_V1_CAPACITY', 'pid': __import__('os').getpid(),
            'old_pid': self.handoff['producer_pid'], 'old_instance_id': self.handoff['old_instance_id'],
            'new_instance_id': h.instance_id, 'old_source': self.handoff['old_source'],
            'fresh_source': list(h.source), 'legacy_origin': origin,
            'prior_snapshot': old_ref, 'before_snapshot': before_ref, 'after_snapshot': after_ref,
            'final_snapshot': final_ref, 'old_reader_before': old_before, 'old_reader_after': old_after,
            'before_state': before['state'], 'after_state': after['state'],
            'before_exposure': before['exposure'], 'after_exposure': after['exposure'],
            'fresh_admission_records': sorted(new_admission),
            'reopen_old_rows_unchanged': all(current_before.get(key) == value for key, value in old_rows.items()),
            'reopen_only_fresh_admission': set(current_before) == set(old_rows) | set(new_admission),
            'reopen_state_unchanged': before['state'] == prior['state'],
            'old_reader_before_agrees': old_before['value'] == before['state'],
            'capacity_applied': applied, 'capacity_review_digest': reviewed['review']['review_digest'],
            'old_rows_preserved_after_capacity': all(after['rows'].get(key) == value
                                                      for key, value in current_before.items()),
            'old_failed_read_wrote_no_rows': final['rows'] == after['rows'] and final['state'] == after['state'],
            'same_governor_and_policy': f.governor is original_governor and f.governor.policy is original_policy,
            'job_observation': h._native_coding.job_observation(), 'model_calls': h.model_calls(),
            'host_preparations': {name: len(getattr(h._native_coding, name))
                                  for name in ('materializations', 'jobs', 'runs', 'effects')},
            'active_tasks': sorted(h.coding_tasks._active), 'owned_effect_tasks': sorted(h.coding_tasks._effect_ownership),
            'initialization_or_adoption_on_reopen': False}
        output = self.context['fixture_root'] / 'native-restart-reopen-observation.json'
        raw = json.dumps(observations, sort_keys=True).encode()
        self.context['safe'].write_new(output, raw)
        result = {'path': str(output), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        self.retained.update(restart_observation=result, legacy_capacity_os2_before=before_ref,
            legacy_capacity_os2_after=after_ref, legacy_capacity_os2_final=final_ref)
        return result

    def restart_public_recover_observation(self, case):
        from dataclasses import replace

        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.audit import domain_chain
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.warrant import WarrantError

        h, f, task_id = self.host, self.host.foundation, self.task.task_id
        runtime = h.runtime
        case.assertIs(runtime._memory_patch_admission, f.core)
        case.assertIs(runtime._coding_tasks, h.coding_tasks)
        case.assertFalse(runtime._owns_memory_patch_admission)
        business_keys = ('business_rows', 'audit_events', 'fresh_admission_rows', 'coding', 'governor', 'jobs', 'target')
        negative_before = self.restart_business_read()
        negative_phase_before = f.lifecycle.phase.value
        negative_results = []

        def observe_denial(name, action, payload, expected_type, expected_code, *, principal=None):
            value, error_type, error_code = None, None, None
            try:
                value = runtime.coding_request(action, payload, principal=principal)
            except expected_type as error:
                if str(error) != expected_code:
                    raise
                error_type, error_code = type(error).__name__, str(error)
            negative_results.append({'name': name, 'action': action,
                'returned_state': None if value is None else value['state'],
                'error_type': error_type, 'code': error_code})

        # This is a real current READ capture from the same Native graph, used
        # only as the rejected caller hint. It is never promoted to MANAGE.
        with h._native_coding.authority(Capability.READ) as current:
            h.coding_tasks._require_principal(current, Capability.READ)
            negative_identity = {'current_instance_id': h.instance_id,
                'actor_session_sha256': canonical_sha256(current.actor_session_id),
                'same_core': runtime._memory_patch_admission is h.coding_tasks.journal.ledger.core,
                'qualification_purpose': current.capability.value}
            observe_denial('READ_AS_MANAGE', 'recover', {'task_id': task_id},
                WarrantError, 'CODING_NATIVE_PRINCIPAL_BINDING', principal=current)
        observe_denial('EXTRA_FIELD', 'recover', {'task_id': task_id, 'unexpected': 'closed-negative-fixture'},
            WarrantError, 'CODING_REQUEST_SCHEMA')
        observe_denial('MISSING_TASK', 'recover', {'task_id': task_id + '-absent'},
            WarrantError, 'CODING_TASK_REQUIRED')
        observe_denial('START_IN_CAPACITY_ADMIN', 'start', {'task_id': task_id},
            AdmissionError, 'CORE_ADMISSION_DENIED')
        for action in ('approve', 'apply'):
            observe_denial(action.upper() + '_IN_CAPACITY_ADMIN', action,
                {'task_id': task_id, 'capsule_digest': '0' * 64, 'operation_digest': '0' * 64},
                AdmissionError, 'CORE_ADMISSION_DENIED')
        negative_after = self.restart_business_read()
        negative_boundaries = {'phase_before': negative_phase_before,
            'phase_after': f.lifecycle.phase.value, 'current_read_identity': negative_identity,
            'results': negative_results, 'before_business': negative_before, 'after_business': negative_after,
            'business_unchanged': all(negative_before[key] == negative_after[key] for key in business_keys)}
        before = self.restart_business_read()
        before_receipts = self.request('get_receipts', {'task_id': task_id})
        phase_before = f.lifecycle.phase.value
        # Current identity/source qualification only; close it BEFORE the public
        # call. No READ principal is passed as MANAGE or reused from OS1.
        with h._native_coding.authority(Capability.READ) as current:
            h.coding_tasks._require_principal(current, Capability.READ)
            identity = {'current_instance_id': h.instance_id,
                'actor_session_sha256': canonical_sha256(current.actor_session_id),
                'same_core': runtime._memory_patch_admission is h.coding_tasks.journal.ledger.core,
                'qualification_purpose': current.capability.value,
                'qualification_closed_before_public_call': True}
        returned, error_type, error_code = None, None, None
        try:
            returned = runtime.coding_request('recover', {'task_id': task_id}, principal=None)
        except AdmissionError as error:
            error_code = str(error)
            if error_code != 'CORE_ADMISSION_DENIED':
                raise
            error_type = type(error).__name__
        after_receipts = self.request('get_receipts', {'task_id': task_id})
        after = self.restart_business_read()
        coding_key = h.coding_tasks._key(task_id)
        coding_identity = 'operation:' + coding_key
        next_revision = before['business_rows'][coding_identity]['revision'] + 1
        event_hash = canonical_sha256([coding_key, next_revision])
        audit_id, proof_id = 'coding-audit-' + event_hash, 'coding-proof-' + event_hash
        expected_added = {'audit:' + audit_id, 'outbox:' + proof_id}
        old_rows, new_rows = before['business_rows'], after['business_rows']
        added, removed = set(new_rows) - set(old_rows), set(old_rows) - set(new_rows)
        changed = {key for key in set(old_rows) & set(new_rows) if old_rows[key] != new_rows[key]}

        def recovery_binding(tx):
            row, data, task = h.coding_tasks._load(tx, task_id)
            events = domain_chain(tx)  # Original full-chain and signed-row validators.
            event = next((entry for entry in events if entry.audit_event_id == audit_id), None)
            outbox = tx.get(RecordKind.OUTBOX, proof_id)
            return {'row_revision': row.revision, 'task_digest': task.digest,
                'audit_matches': event is not None and event.resource_id == coding_key
                    and event.event_type == 'CODING_INTAKE' and event.state_before == 'RUNNING'
                    and event.state_after == 'UNKNOWN' and event.content_hashes['content'] == row.payload_digest,
                'outbox_matches': outbox is not None and event is not None
                    and outbox.payload['event_id'] == audit_id and outbox.payload['event_digest'] == event.event_hash,
                'signed_receipts': data['receipts']}
        with h._native_coding.authority(Capability.READ) as current:
            binding = h.coding_tasks._run(current, Capability.READ, recovery_binding)
        receipts = binding['signed_receipts']
        receipt_append = (len(receipts) == len(before_receipts['receipts']) + 1
            and receipts[:-1] == before_receipts['receipts']
            and receipts[-1]['receipt']['state'] == 'UNKNOWN')
        untouched = all(old_rows[key] == new_rows.get(key) for key in old_rows if key != coding_identity)
        accounting = all(before[key] == after[key] for key in ('governor', 'jobs', 'target', 'fresh_admission_rows'))
        legal_delta = (changed == {coding_identity} and added == expected_added and not removed
            and binding['row_revision'] == next_revision and binding['task_digest'] == self.task.digest
            and untouched and accounting and receipt_append and binding['audit_matches'] and binding['outbox_matches']
            and after['audit_events'] == before['audit_events'] + [audit_id])
        probe = replace(self.task, task_id=task_id + '-recover-probe', run_id=self.task.run_id + '-recover-probe')
        probe_result = {'accepted': False, 'state': None, 'error_type': None, 'code': None}
        try:
            value = self.request('create_task', {'task': probe.to_dict()})
            probe_result.update(accepted=True, state=value['state'])
        except AdmissionError as error:
            code = str(error)
            if code != 'CORE_ADMISSION_DENIED':
                raise
            probe_result.update(error_type=type(error).__name__, code=code)
        after_probe = self.restart_business_read()
        # The original _append_transition returns the existing UNKNOWN view
        # before _save. Prove that behavior through the public API and rows.
        repeat_before = self.restart_business_read()
        repeat_receipts_before = self.request('get_receipts', {'task_id': task_id})
        repeat_value, repeat_error_type, repeat_code = None, None, None
        repeat_phase_before = f.lifecycle.phase.value
        try:
            repeat_value = runtime.coding_request('recover', {'task_id': task_id}, principal=None)
        except AdmissionError as error:
            if str(error) != 'CORE_ADMISSION_DENIED':
                raise
            repeat_error_type, repeat_code = type(error).__name__, str(error)
        repeat_receipts_after = self.request('get_receipts', {'task_id': task_id})
        repeat_after = self.restart_business_read()
        repeat_recover = {'returned_state': None if repeat_value is None else repeat_value['state'],
            'error_type': repeat_error_type, 'code': repeat_code,
            'phase_before': repeat_phase_before, 'phase_after': f.lifecycle.phase.value,
            'before_receipts': repeat_receipts_before, 'after_receipts': repeat_receipts_after,
            'before_business': repeat_before, 'after_business': repeat_after,
            'receipts_unchanged': repeat_receipts_before == repeat_receipts_after,
            'business_unchanged': all(repeat_before[key] == repeat_after[key] for key in business_keys)}
        return {'negative_boundaries': negative_boundaries, 'repeat_recover': repeat_recover,
            'public_api': "AgentRuntime.coding_request('recover', {'task_id': task_id}, principal=None)",
            'identity': identity, 'phase_before': phase_before, 'phase_after': f.lifecycle.phase.value,
            'returned_state': None if returned is None else returned['state'],
            'error_type': error_type, 'code': error_code, 'before_receipts': before_receipts,
            'after_receipts': after_receipts, 'before_business': before, 'after_business': after,
            'actual_added_rows': sorted(added), 'actual_removed_rows': sorted(removed),
            'actual_changed_rows': sorted(changed), 'expected_added_rows': sorted(expected_added),
            'expected_changed_row': coding_identity, 'legal_coding_audit_outbox_delta': legal_delta,
            'signed_receipt_append_only': receipt_append, 'audit_binding': binding['audit_matches'],
            'outbox_binding': binding['outbox_matches'], 'accounting_unchanged': accounting,
            'unrelated_old_rows_unchanged': untouched, 'new_work_probe': probe_result,
            'after_probe_business': after_probe, 'probe_wrote_no_rows': all(after_probe[key] == after[key] for key in
                ('business_rows', 'audit_events', 'fresh_admission_rows', 'coding', 'governor', 'jobs', 'target')),
            'job_observation': h._native_coding.job_observation(), 'model_calls': h.model_calls(),
            'host_preparations': {name: len(getattr(h._native_coding, name))
                                  for name in ('materializations', 'jobs', 'runs', 'effects')},
            'active_tasks': sorted(h.coding_tasks._active), 'owned_effect_tasks': sorted(h.coding_tasks._effect_ownership)}

    def restart_history_assertions(self, case, *, recover_interrupted=False):
        import hashlib
        import json
        import os

        from runtime.core_admission import AdmissionError, Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.mission.warrant import WarrantError

        h, f = self.host, self.host.foundation
        before_ref = self.handoff['old_business']
        before_raw = self.context['safe'].read(__import__('pathlib').Path(before_ref['path']), maximum=4 * 1024 * 1024)
        case.assertEqual(before_ref['bytes'], len(before_raw))
        case.assertEqual(before_ref['sha256'], hashlib.sha256(before_raw).hexdigest())
        before = json.loads(before_raw)
        current = self.restart_business_read()
        case.assertNotEqual(self.handoff['producer_pid'], os.getpid())
        case.assertNotEqual(self.handoff['old_instance_id'], h.instance_id)
        case.assertEqual(self.handoff['old_source'], list(h.source))
        case.assertEqual(self.handoff['identity_spki_sha256'], canonical_sha256(h.identity.spki))
        case.assertEqual(before['governor'], current['governor'])
        case.assertEqual(before['target'], current['target'])
        case.assertEqual(before['jobs'], current['jobs'])
        added = current['fresh_admission_rows']
        case.assertTrue(set(added).isdisjoint(before['business_rows']))
        case.assertEqual(before['business_rows'] | added, current['business_rows'])
        case.assertEqual(before['audit_events'] + [key.removeprefix('audit:') for key in added if key.startswith('audit:')],
                         current['audit_events'])
        case.assertEqual(before['coding'], current['coding'])
        idle = current['capacity_idle']
        result = {'schema': 'nz13.native-populated-restart-observation.v1',
            'qualification': False, 'scenario': self.handoff['scenario'], 'pid': os.getpid(),
            'old_pid': self.handoff['producer_pid'], 'old_instance_id': self.handoff['old_instance_id'],
            'new_instance_id': h.instance_id, 'fresh_source': list(h.source),
            'phase': f.lifecycle.phase.value, 'current': current, 'idle_observed': idle,
            'fresh_receipts': self.request('get_receipts', {'task_id': self.task.task_id}),
            'composition_configured_retained_ids': list(f.spec.to_dict()['retained_sandbox_task_ids']),
            'composition_job_ids_before_explicit_restore': sorted(h._native_coding.jobs),
            'model_calls': h.model_calls(), 'manual_init_adopt_reset': False,
            'old_handle_or_principal_recreated': False, 'recover_to_unknown': 'PENDING_SEPARATE_PUBLIC_RECOVER_GATE_PROOF'}
        ids = tuple(self.body['retained_sandbox_task_ids'])
        if ids:
            with h._native_coding.authority(Capability.READ) as principal:
                restored = h.sandbox_route.restore_sandbox_bindings(principal, task_ids=ids)
            result['explicit_restore'] = {'task_ids': list(ids), 'bindings': len(restored),
                'modes': [h.broker._bindings[identity][0].mode for identity in ids]}
            case.assertEqual(['HISTORY_ONLY'] * len(ids), result['explicit_restore']['modes'])
        else:
            result['explicit_restore'] = {'task_ids': [], 'bindings': 0, 'modes': []}
        if self.handoff['scenario'] == 'TERMINAL_CHILD_ACQUISITION':
            from pathlib import Path
            from unittest.mock import patch

            from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
            from runtime.mission import sandbox_linux

            # Observe/delegate the original source read exactly once. This is
            # an in-memory diagnostic, not a substituted digest/readback/proof.
            original_read = Path.read_bytes
            broker_source = Path(sandbox_linux.__file__)
            source_reads = []
            def source_read(path):
                if path == broker_source:
                    self.context['strict_path_guard'](path)
                    case.assertEqual(self.context['source_root'] / 'runtime/mission/sandbox_linux.py', path)
                    source_reads.append({'inside_sql': bool(_IN_TRANSACTION.get())})
                return original_read(path)
            with patch.object(Path, 'read_bytes', new=source_read):
                try:
                    value = self.request('review_effect', {'task_id': self.task.task_id})
                    result['inert_history_review'] = {'value': value, 'error_type': None, 'code': None}
                except (AdmissionError, WarrantError) as error:
                    result['inert_history_review'] = {'value': None, 'error_type': type(error).__name__, 'code': str(error)}
            result['inert_history_review']['source_io_observer'] = {
                'scope': 'DELEGATING_ORIGINAL_BROKER_SOURCE_READ_ONLY_NO_NEW_IO',
                'reads': source_reads, 'inside_sql_count': sum(row['inside_sql'] for row in source_reads)}
        case.assertEqual(0, h.model_calls())
        case.assertEqual({}, h.coding_tasks._active)
        case.assertEqual({}, h.coding_tasks._effect_ownership)
        result['after_read_business'] = self.restart_business_read()
        for key in ('business_rows', 'audit_events', 'fresh_admission_rows', 'coding', 'target', 'governor', 'jobs'):
            case.assertEqual(current[key], result['after_read_business'][key])
        result['business_preservation'] = {'all_record_kinds': True, 'old_rows_unchanged': True,
            'only_fresh_admission_added': sorted(added), 'read_review_wrote_no_business_records': True,
            'before_file': before_ref}
        # This explicit owned probe follows the no-write READ/review comparison;
        # its admitted/denied outcome is DATA for the supervisor after OS2 EXIT.
        from dataclasses import replace
        probe = replace(self.task, task_id=self.task.task_id + '-reopen-probe',
                        run_id=self.task.run_id + '-reopen-probe')
        try:
            value = self.request('create_task', {'task': probe.to_dict()})
            result['new_work_probe'] = {'accepted': True, 'state': value['state'], 'code': None}
        except AdmissionError as error:
            case.assertEqual('CORE_ADMISSION_DENIED', str(error))
            result['new_work_probe'] = {'accepted': False, 'state': None, 'code': str(error)}
        if self.handoff['scenario'] == 'ORPHAN_RUNNING_ACK':
            case.assertEqual([], h._native_coding.job_observation())
        case.assertEqual(0, h.model_calls())
        case.assertEqual({}, h.coding_tasks._active)
        result['after_explicit_new_work_probe'] = self.restart_business_read()
        if recover_interrupted:
            case.assertEqual('ORPHAN_RUNNING_ACK', self.handoff['scenario'])
            result['public_recover'] = self.restart_public_recover_observation(case)
            result['recover_to_unknown'] = 'ORIGINAL_PUBLIC_API_OBSERVATION_PRESENT_QUALIFICATION_PENDING'
        raw = json.dumps(result, sort_keys=True).encode()
        output = self.context['fixture_root'] / 'native-restart-reopen-observation.json'
        self.context['safe'].write_new(output, raw)
        self.retained['restart_observation'] = {'path': str(output), 'bytes': len(raw),
                                               'sha256': hashlib.sha256(raw).hexdigest()}
        return self.retained['restart_observation']

    def profile_cold_restore_observation(self, case):
        import hashlib
        import json
        import os
        from dataclasses import replace
        from pathlib import Path

        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
        from runtime.mission.jobs import load_job
        from runtime.mission.sandbox_bindings import read_binding
        from runtime.mission.sandbox_contracts import (
            SandboxRegistry,
            sandbox_input_limits,
        )
        from runtime.mission.sandbox_linux import (
            LinuxSandboxBroker,
            TrustedSandboxConfig,
            load_host_config,
            save_host_config,
        )
        from runtime.mission.warrant import WarrantError

        h, route, broker = self.host, self.host.sandbox_route, self.host.broker
        case.assertIs(route.executor, broker)
        case.assertEqual('CAPACITY_ADMIN', h.foundation.lifecycle.phase.value)
        case.assertEqual(self.handoff['identity_spki_sha256'], canonical_sha256(h.identity.spki))
        case.assertFalse(_IN_TRANSACTION.get())
        template_ref = self.context['profile_restore_template']
        template_path = Path(template_ref['path'])
        case.assertEqual(self.root / 'native-profile-restore-template.json', template_path)
        template_raw = self.context['safe'].read(template_path, maximum=4 * 1024 * 1024)
        case.assertEqual(template_ref['bytes'], len(template_raw))
        case.assertEqual(template_ref['sha256'], hashlib.sha256(template_raw).hexdigest())
        template = json.loads(template_raw)
        template_root = Path(template['template_root'])
        case.assertEqual(self.root / 'cache/profile-restore-template', template_root)
        template_b = load_host_config(template_root, trusted_root=broker.binding_policy.trusted_root)
        case.assertIs(type(template_b), TrustedSandboxConfig)
        case.assertEqual(template['profile_b'], template_b.profile())
        case.assertEqual(template['profile_b_digest'], template_b.profile_digest)
        case.assertEqual(template['profile_a_digest'], broker.binding_policy.profile_digest)
        case.assertEqual(template['current_native_config'], self.handoff['host_config'])
        seed_path = Path(self.body['sandbox_seed']['descriptor_path'])
        seed_before = self.context['safe'].read(seed_path, maximum=4 * 1024 * 1024)
        case.assertEqual(self.body['sandbox_seed']['descriptor_sha256'], hashlib.sha256(seed_before).hexdigest())
        ids = tuple(self.body['retained_sandbox_task_ids'])
        case.assertEqual(tuple(self.handoff['produced_sandbox_task_ids']), ids)
        case.assertEqual(4, len(ids))

        def signed_locators(tx):
            values = []
            for identity in ids:
                job = load_job(route.journal.governor, tx, identity)
                case.assertIsNotNone(job)
                values.append(read_binding(tx, route.scope, route.journal.governor.policy.deployment_id,
                                           route.workspace, identity,
                                           expected_digest=job['sandbox_binding_digest']))
            return values

        with h._native_coding.authority(Capability.READ) as principal:
            values = route._run(principal, Capability.READ, signed_locators)
        before = self.restart_business_read()
        snapshots = {'before': self.legacy_capacity_save('native-profile-restore-before.json', before)}
        self.retained['profile_restore_before'] = snapshots['before']
        cold_before = {'binding_ids': sorted(broker._bindings), 'capture_roots': sorted(broker._captures)}
        candidates = []
        used_roots = set()
        for value in values:
            identity, root_ref = value['task_id'], value['root_ref']
            if (identity not in broker._bindings and root_ref not in broker._captures
                    and root_ref not in used_roots and root_ref != broker.config.root.name
                    and root_ref != template_root.name):
                candidates.append(value)
                used_roots.add(root_ref)
        prerequisites = {'schema': 'nz13.native-profile-cold-prerequisites.v1',
            'qualification': False, 'declared_ids': list(ids), 'actual_signed_binding_values': values,
            'cold_before': cold_before, 'candidate_ids': [value['task_id'] for value in candidates],
            'candidate_roots': [value['root_ref'] for value in candidates],
            'seed_root': str(broker.config.root), 'template_root': str(template_root),
            'native_phase': h.foundation.lifecycle.phase.value}
        self.retained['profile_restore_prerequisites'] = self.legacy_capacity_save(
            'native-profile-restore-prerequisites.json', prerequisites)
        case.assertGreaterEqual(len(candidates), 2, 'NATIVE_PROFILE_RESTORE_NEEDS_TWO_DISTINCT_COLD_ROOTS')
        positive, negative = candidates[:2]
        negative_root = broker.binding_policy.trusted_root / negative['root_ref']
        case.assertNotEqual(positive['root_ref'], negative['root_ref'])
        with h._native_coding.authority(Capability.READ) as principal:
            restored = route.restore_sandbox_bindings(principal, task_ids=(positive['task_id'],))
        positive_result = {'id': positive['task_id'], 'root_ref': positive['root_ref'],
            'actual_modes': [value.mode for value in restored],
            'actual_return_types': [type(value).__module__ + '.' + type(value).__name__ for value in restored],
            'binding_ids_after': sorted(broker._bindings), 'capture_roots_after': sorted(broker._captures)}
        case.assertEqual(['HISTORY_ONLY'], positive_result['actual_modes'])
        case.assertNotIn(negative['task_id'], broker._bindings)
        case.assertNotIn(negative['root_ref'], broker._captures)
        after_positive = self.restart_business_read()
        snapshots['after_positive'] = self.legacy_capacity_save(
            'native-profile-restore-after-positive.json', after_positive)
        self.retained['profile_restore_after_positive'] = snapshots['after_positive']

        config_a = load_host_config(negative_root, trusted_root=broker.binding_policy.trusted_root,
                                    root_identity=negative['root_identity'])
        root_identity_before = broker._validate_config(config_a, root_identity=negative['root_identity'])
        case.assertEqual(template['profile_a'], config_a.profile())
        case.assertEqual(broker.binding_policy.profile_digest, config_a.profile_digest)
        descriptor_path = negative_root / 'host-config.json'
        descriptor_a = self.context['safe'].read(descriptor_path, maximum=4 * 1024 * 1024)
        case.assertEqual(negative['host_config_sha256'], hashlib.sha256(descriptor_a).hexdigest())
        old_descriptor_path = self.root / 'native-profile-restore-old-descriptor.json'
        self.context['safe'].write_new(old_descriptor_path, descriptor_a)
        self.retained['profile_restore_old_descriptor'] = {'path': str(old_descriptor_path),
            'bytes': len(descriptor_a), 'sha256': hashlib.sha256(descriptor_a).hexdigest()}
        changed_recipes = tuple(replace(recipe, sandbox_profile_digest=template_b.profile_digest,
                                        input_profile='PYTEST_WHEELS_V1')
                                for recipe in config_a.registry.recipes)
        changed = replace(config_a, profile_bytes=template_b.profile_bytes,
            profile_digest=template_b.profile_digest,
            registry=SandboxRegistry(config_a.registry.workspace, changed_recipes))
        case.assertIs(type(changed), TrustedSandboxConfig)
        limits = dict(sandbox_input_limits('PYTEST_WHEELS_V1'))
        actual_input_bounds = []
        for recipe_id, entry in config_a.inputs().items():
            sizes = []
            for name, filename in entry['files'].items():
                raw = self.context['safe'].read(Path(filename), maximum=limits['per_file_bytes'])
                case.assertEqual(entry['manifest'][name], hashlib.sha256(raw).hexdigest())
                sizes.append(len(raw))
            case.assertLessEqual(len(sizes), limits['files'])
            case.assertLessEqual(sum(sizes), limits['total_bytes'])
            actual_input_bounds.append({'recipe_id': recipe_id, 'file_bytes': sizes,
                                        'total_bytes': sum(sizes), 'limits': limits})
        staging_root = self.root / 'cache/profile-rebased-descriptor'
        self.context['strict_path_guard'](staging_root)
        staging_root.mkdir(mode=0o700)
        save_host_config(replace(changed, root=staging_root))
        descriptor_b = self.context['safe'].read(staging_root / 'host-config.json', maximum=4 * 1024 * 1024)
        old_document, new_document = json.loads(descriptor_a), json.loads(descriptor_b)
        expected_document = json.loads(descriptor_a)
        expected_document['profile'] = template_b.profile()
        expected_document['profile_digest'] = template_b.profile_digest
        for recipe in expected_document['recipes']:
            recipe['sandbox_profile_digest'] = template_b.profile_digest
            recipe['input_profile'] = 'PYTEST_WHEELS_V1'
        case.assertEqual(expected_document, new_document)
        case.assertEqual(descriptor_a, self.context['safe'].read(descriptor_path, maximum=4 * 1024 * 1024))
        self.context['safe'].replace_alias(descriptor_path, descriptor_b,
                                           'profile-restore-' + str(os.getpid()))
        loaded_b = load_host_config(negative_root, trusted_root=broker.binding_policy.trusted_root,
                                    root_identity=negative['root_identity'])
        case.assertIs(type(loaded_b), TrustedSandboxConfig)
        case.assertEqual(changed, loaded_b)
        case.assertEqual(template_b.profile_bytes, loaded_b.profile_bytes)
        case.assertEqual(template_b.profile_digest, loaded_b.profile_digest)
        case.assertNotEqual(config_a.profile_digest, loaded_b.profile_digest)
        case.assertEqual(descriptor_b, self.context['safe'].read(descriptor_path, maximum=4 * 1024 * 1024))
        # This is the unchanged actual A object loaded before mutation. It is
        # used only as a read-only validity control, never supplied to restore.
        root_identity_after = broker._validate_config(config_a, root_identity=negative['root_identity'])
        case.assertEqual(root_identity_before, root_identity_after)
        case.assertEqual(config_a.runtime(), loaded_b.runtime())
        case.assertEqual(config_a.inputs(), loaded_b.inputs())
        case.assertEqual(broker.binding_policy.profile_digest, config_a.profile_digest)
        case.assertEqual(seed_before, self.context['safe'].read(seed_path, maximum=4 * 1024 * 1024))
        changed_descriptor_path = self.root / 'native-profile-restore-new-descriptor.json'
        self.context['safe'].write_new(changed_descriptor_path, descriptor_b)
        self.retained['profile_restore_new_descriptor'] = {'path': str(changed_descriptor_path),
            'bytes': len(descriptor_b), 'sha256': hashlib.sha256(descriptor_b).hexdigest()}
        case.assertNotIn(negative['task_id'], broker._bindings)
        case.assertNotIn(negative['root_ref'], broker._captures)
        cold_before_negative = {'binding_ids': sorted(broker._bindings),
                                'capture_roots': sorted(broker._captures)}
        before_negative = self.restart_business_read()
        snapshots['before_negative'] = self.legacy_capacity_save(
            'native-profile-restore-before-negative.json', before_negative)
        self.retained['profile_restore_before_negative'] = snapshots['before_negative']
        process_events = self.context['profile_process_events']
        case.assertIs(type(process_events), list)

        def operation_counts():
            return {'popen_events': len(process_events), 'model_calls': h.model_calls(),
                'host_preparations': {name: len(getattr(h._native_coding, name))
                                      for name in ('materializations', 'jobs', 'runs', 'effects')},
                'active_tasks': sorted(h.coding_tasks._active),
                'owned_effect_tasks': sorted(h.coding_tasks._effect_ownership)}

        operation_before = operation_counts()
        event_offset = len(process_events)
        try:
            try:
                with h._native_coding.authority(Capability.READ) as principal:
                    result = route.restore_sandbox_bindings(principal, task_ids=(negative['task_id'],))
                negative_result = {'accepted': True, 'modes': [value.mode for value in result],
                                   'error_type': None, 'code': None, 'frames': []}
            except WarrantError as error:
                frames = []
                cursor = error.__traceback__
                while cursor is not None:
                    code = cursor.tb_frame.f_code
                    frames.append({'file': code.co_filename, 'function': code.co_name,
                        'line': cursor.tb_lineno, 'first_line': code.co_firstlineno,
                        'code_sha256': hashlib.sha256(code.co_code).hexdigest(),
                        'original_restore_capture': code is LinuxSandboxBroker.restore_capture.__code__,
                        'original_validate_config': code is LinuxSandboxBroker._validate_config.__code__})
                    cursor = cursor.tb_next
                negative_result = {'accepted': False, 'modes': [],
                    'error_type': type(error).__module__ + '.' + type(error).__name__,
                    'code': str(error), 'frames': frames}
                if str(error) != 'SANDBOX_BINDING_PROFILE':
                    self.retained['profile_restore_unexpected_error'] = self.legacy_capacity_save(
                        'native-profile-restore-unexpected-error.json', negative_result)
                    raise
        finally:
            operation_after = operation_counts()
            operation_audit = {'schema': 'nz13.native-profile-denied-operation-audit.v1',
                'qualification': False, 'scope': 'ONLY_ORIGINAL_RESTORE_AND_FRESH_READ_AUTHORITY_BOUNDARY',
                'before': operation_before, 'after': operation_after,
                'popen_events': list(process_events[event_offset:]),
                'event_count_delta': len(process_events) - event_offset,
                'all_events_including_allowed_and_denied': True,
                'sampling_finished_before_next_business_READ': True}
            self.retained['profile_restore_operation_audit'] = self.legacy_capacity_save(
                'native-profile-restore-operation-audit.json', operation_audit)
        after_negative = self.restart_business_read()
        snapshots['after_negative'] = self.legacy_capacity_save(
            'native-profile-restore-after-negative.json', after_negative)
        self.retained['profile_restore_after_negative'] = snapshots['after_negative']
        current_seed = self.context['safe'].read(seed_path, maximum=4 * 1024 * 1024)
        observation = {'schema': 'nz13.native-cold-physical-profile-restore-observation.v1',
            'qualification': False, 'scope': 'PHYSICAL_HOST_CONFIG_DRIFT_UNDER_UNCHANGED_ADMITTED_POLICY_A',
            'profile_template': template_ref, 'snapshots': snapshots, 'positive': positive_result,
            'negative_id': negative['task_id'], 'negative_root_ref': negative['root_ref'],
            'negative': negative_result,
            'denial_operation_audit': self.retained['profile_restore_operation_audit'],
            'cold_before': cold_before,
            'cold_before_negative': cold_before_negative,
            'after_negative_binding_ids': sorted(broker._bindings),
            'after_negative_capture_roots': sorted(broker._captures),
            'old_descriptor': self.retained['profile_restore_old_descriptor'],
            'new_descriptor': self.retained['profile_restore_new_descriptor'],
            'original_A_validation_root_before': json.loads(root_identity_before),
            'original_A_validation_root_after': json.loads(root_identity_after),
            'actual_B_loaded_type': type(loaded_b).__module__ + '.' + type(loaded_b).__name__,
            'actual_B_loaded_profile': loaded_b.profile(), 'actual_B_loaded_digest': loaded_b.profile_digest,
            'policy_A_digest': broker.binding_policy.profile_digest, 'actual_input_bounds': actual_input_bounds,
            'actual_document_A': old_document, 'actual_document_B': new_document,
            'native_body': self.body, 'native_body_digest': h.foundation.spec.digest,
            'old_seed_sha256': hashlib.sha256(seed_before).hexdigest(),
            'new_seed_sha256': hashlib.sha256(current_seed).hexdigest(),
            'phase_after': h.foundation.lifecycle.phase.value, 'host_closed': h._closed,
            'job_observation': h._native_coding.job_observation(), 'model_calls': h.model_calls(),
            'host_preparations': {name: len(getattr(h._native_coding, name))
                                  for name in ('materializations', 'jobs', 'runs', 'effects')},
            'active_tasks': sorted(h.coding_tasks._active),
            'owned_effect_tasks': sorted(h.coding_tasks._effect_ownership),
            'source_generation_vector': 'PENDING_SEPARATE_FRESH_NATIVE_SOURCE_PROTOCOL',
            'historical_warrant_current_epoch_vector': 'PENDING_SEPARATE_BEHAVIOR'}
        self.retained['profile_restore_observation'] = self.legacy_capacity_save(
            'native-profile-restore-observation.json', observation)
        return self.retained['profile_restore_observation']


    def source_generation_restore_observation(self, case):
        import hashlib
        import os
        import stat
        import sys
        from dataclasses import asdict
        from pathlib import Path

        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
        from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
        from runtime.mission.git_publish import GitSourceSnapshot
        from runtime.mission.jobs import load_job
        from runtime.mission.patchset import _snapshot, observe_source
        from runtime.mission.sandbox_bindings import read_binding
        from runtime.mission.sandbox_linux import LinuxSandboxBroker
        from runtime.mission.warrant import WarrantError

        h, route, broker = self.host, self.host.sandbox_route, self.host.broker
        case.assertIs(route.executor, broker)
        case.assertEqual('CAPACITY_ADMIN', h.foundation.lifecycle.phase.value)
        case.assertFalse(_IN_TRANSACTION.get())
        case.assertEqual(self.handoff['identity_spki_sha256'], canonical_sha256(h.identity.spki))
        ids = tuple(self.body['retained_sandbox_task_ids'])
        case.assertEqual(tuple(self.handoff['produced_sandbox_task_ids']), ids)
        case.assertEqual(4, len(ids))
        spec_before = h.foundation.spec.to_dict()
        spec_digest_before = h.foundation.spec.digest

        def signed_locators(tx):
            values = []
            for identity in ids:
                job = load_job(route.journal.governor, tx, identity)
                case.assertIsNotNone(job)
                values.append(read_binding(tx, route.scope, route.journal.governor.policy.deployment_id,
                    route.workspace, identity, expected_digest=job['sandbox_binding_digest']))
            return values

        with h._native_coding.authority(Capability.READ) as principal:
            values = route._run(principal, Capability.READ, signed_locators)
        before = self.legacy_capacity_snapshot()
        snapshots = {'before': self.legacy_capacity_save('native-source-generation-before.json', before)}
        cold_before = {'binding_ids': sorted(broker._bindings), 'capture_roots': sorted(broker._captures)}
        candidates, roots = [], set()
        for value in values:
            if (value['task_id'] not in broker._bindings and value['root_ref'] not in broker._captures
                    and value['root_ref'] not in roots and value['root_ref'] != broker.config.root.name):
                candidates.append(value)
                roots.add(value['root_ref'])
        prerequisites = {'schema': 'nz13.native-source-generation-cold-prerequisites.v1',
            'qualification': False, 'declared_ids': list(ids), 'actual_signed_binding_values': values,
            'cold_before': cold_before, 'candidate_ids': [value['task_id'] for value in candidates],
            'candidate_roots': [value['root_ref'] for value in candidates], 'native_body': spec_before,
            'native_body_digest': spec_digest_before, 'identity_spki_sha256': canonical_sha256(h.identity.spki)}
        self.retained['source_generation_prerequisites'] = self.legacy_capacity_save(
            'native-source-generation-prerequisites.json', prerequisites)
        case.assertGreaterEqual(len(candidates), 2, 'NATIVE_SOURCE_RESTORE_NEEDS_TWO_DISTINCT_COLD_ROOTS')
        positive, negative = candidates[:2]
        with h._native_coding.authority(Capability.READ) as principal:
            restored = route.restore_sandbox_bindings(principal, task_ids=(positive['task_id'],))
        positive_result = {'id': positive['task_id'], 'root_ref': positive['root_ref'],
            'actual_modes': [value.mode for value in restored],
            'actual_return_types': [type(value).__module__ + '.' + type(value).__name__ for value in restored],
            'binding_ids_after': sorted(broker._bindings), 'capture_roots_after': sorted(broker._captures)}
        self.retained['source_generation_positive'] = self.legacy_capacity_save(
            'native-source-generation-positive.json', positive_result)
        case.assertEqual(['HISTORY_ONLY'], positive_result['actual_modes'])
        case.assertNotIn(negative['task_id'], broker._bindings)
        case.assertNotIn(negative['root_ref'], broker._captures)
        after_positive = self.legacy_capacity_snapshot()
        snapshots['after_positive'] = self.legacy_capacity_save(
            'native-source-generation-after-positive.json', after_positive)
        base_root = Path(self.body['base_root'])
        path = base_root / 'src/textutil.py'
        self.context['strict_path_guard'](path)
        original = self.context['safe'].read(path, maximum=1048576)
        original_info = self.context['safe'].info(path)
        case.assertEqual(0o644, stat.S_IMODE(original_info.st_mode))
        case.assertTrue(stat.S_ISREG(original_info.st_mode))
        case.assertEqual((os.getuid(), 1), (original_info.st_uid, original_info.st_nlink))
        replacement = b'def slug(text):\n    return text.strip().upper()\n'
        case.assertNotEqual(original, replacement)
        compile(replacement, '<owned-source-generation-B>', 'exec', dont_inherit=True)
        source_a = _snapshot(base_root)
        case.assertEqual(h.foundation.spec.source_snapshot.export_tree_sha256, source_a.digest)

        def tree_value(tree):
            return {'digest': tree.digest, 'files': {name: asdict(file.identity)
                    for name, file in sorted(tree.files.items())}}

        def preserve_file(name, raw):
            target = self.root / name
            self.context['safe'].write_new(target, raw)
            return {'path': str(target), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

        data_a = preserve_file('native-source-generation-A.txt', original)
        data_b = preserve_file('native-source-generation-B.txt', replacement)
        expected_file_identity = (original_info.st_dev, original_info.st_ino, original_info.st_uid,
                                  original_info.st_gid, original_info.st_nlink, stat.S_IMODE(original_info.st_mode))

        def write_export(raw):
            case.assertFalse(_IN_TRANSACTION.get())
            self.context['strict_path_guard'](path)
            parent_fd, leaf = self.context['safe'].parent(path)
            descriptor = None
            try:
                descriptor = os.open(leaf, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent_fd)
                info = os.fstat(descriptor)
                named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                actual = (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_nlink, stat.S_IMODE(info.st_mode))
                named_identity = (named.st_dev, named.st_ino, named.st_uid, named.st_gid, named.st_nlink, stat.S_IMODE(named.st_mode))
                case.assertEqual(expected_file_identity, actual)
                case.assertEqual(actual, named_identity)
                case.assertTrue(stat.S_ISREG(info.st_mode) and stat.S_ISREG(named.st_mode))
                os.ftruncate(descriptor, 0)
                offset = 0
                while offset < len(raw):
                    written = os.write(descriptor, raw[offset:])
                    case.assertGreater(written, 0)
                    offset += written
                os.fsync(descriptor)
                after = os.fstat(descriptor)
                named_after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                after_identity = (after.st_dev, after.st_ino, after.st_uid, after.st_gid, after.st_nlink, stat.S_IMODE(after.st_mode))
                named_after_identity = (named_after.st_dev, named_after.st_ino, named_after.st_uid, named_after.st_gid, named_after.st_nlink, stat.S_IMODE(named_after.st_mode))
                case.assertEqual(expected_file_identity, after_identity)
                case.assertEqual(after_identity, named_after_identity)
                case.assertTrue(stat.S_ISREG(after.st_mode) and stat.S_ISREG(named_after.st_mode))
                case.assertEqual((len(raw), len(raw)), (after.st_size, named_after.st_size))
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                os.close(parent_fd)
            case.assertEqual(raw, self.context['safe'].read(path, maximum=1048576))

        events = self.context['source_process_events']
        case.assertIs(type(events), list)

        def operation_counts():
            return {'popen_events': len(events), 'model_calls': h.model_calls(),
                'host_preparations': {name: len(getattr(h._native_coding, name))
                                      for name in ('materializations', 'jobs', 'runs', 'effects')},
                'active_tasks': sorted(h.coding_tasks._active),
                'owned_effect_tasks': sorted(h.coding_tasks._effect_ownership),
                'native_handles': len(h.foundation.lifecycle._handles),
                'capture_slots': len(h.foundation.access._originals),
                'capturing': h.foundation.lifecycle._capturing}

        negative_result = None
        physical_b = None
        mutation_started = False
        try:
            mutation_started = True
            write_export(replacement)
            source_b = _snapshot(base_root)
            observed_b = observe_source(base_root, repository_id=broker.binding_policy.recipe.repository_id,
                workspace_id=broker.binding_policy.workspace, source_base_sha=broker.binding_policy.recipe.source_base_sha)
            physical_b = {'schema': 'nz13.native-owned-physical-source-B.v1', 'qualification': False,
                'path': str(path), 'data_A': data_a, 'data_B': data_b,
                'actual_tree_A': tree_value(source_a), 'actual_tree_B': tree_value(source_b),
                'actual_observed_source_B': asdict(observed_b), 'file_identity': list(expected_file_identity),
                'admitted_export_digest_A': h.foundation.spec.source_snapshot.export_tree_sha256,
                'native_body_unchanged': h.foundation.spec.to_dict() == spec_before,
                'native_body_digest': h.foundation.spec.digest}
            self.retained['source_generation_physical_B'] = self.legacy_capacity_save(
                'native-source-generation-physical-B.json', physical_b)
            cold_before_negative = {'binding_ids': sorted(broker._bindings), 'capture_roots': sorted(broker._captures)}
            operation_before, offset = operation_counts(), len(events)
            try:
                try:
                    with h._native_coding.authority(Capability.READ) as principal:
                        returned = route.restore_sandbox_bindings(principal, task_ids=(negative['task_id'],))
                    negative_result = {'accepted': True, 'modes': [value.mode for value in returned],
                        'error_type': None, 'code': None, 'frames': []}
                except WarrantError as error:
                    frames, cursor = [], error.__traceback__
                    while cursor is not None:
                        code = cursor.tb_frame.f_code
                        frames.append({'file': code.co_filename, 'function': code.co_name, 'line': cursor.tb_lineno,
                            'first_line': code.co_firstlineno, 'code_sha256': hashlib.sha256(code.co_code).hexdigest(),
                            'original_native_observe': code is NativeHostCompositionConfig.observe.__code__,
                            'original_verify_export': code is GitSourceSnapshot.verify_export.__code__,
                            'original_broker_restore': code is LinuxSandboxBroker.restore_capture.__code__})
                        cursor = cursor.tb_next
                    negative_result = {'accepted': False, 'modes': [],
                        'error_type': type(error).__module__ + '.' + type(error).__name__, 'code': str(error), 'frames': frames}
                    if str(error) != 'GIT_SOURCE_EXPORT_DRIFT':
                        raise
            finally:
                pending = sys.exc_info()[1]
                operation_audit = {'schema': 'nz13.native-source-generation-denial-operation-audit.v1',
                    'qualification': False, 'scope': 'WHOLE_NEW_ORIGINAL_READ_AUTHORITY_AND_UNUSED_ID_RESTORE_WHILE_B',
                    'before': operation_before, 'after': operation_counts(), 'popen_events': list(events[offset:]),
                    'event_count_delta': len(events) - offset, 'all_events_including_allowed_and_denied': True,
                    'negative_result': negative_result, 'unexpected_type': type(pending).__name__ if pending is not None else None,
                    'cold_before': cold_before_negative, 'binding_ids_after': sorted(broker._bindings),
                    'capture_roots_after': sorted(broker._captures), 'negative_id': negative['task_id'],
                    'negative_root_ref': negative['root_ref'], 'physical_B': self.retained['source_generation_physical_B'],
                    'persisted_before_any_qualification_assertion_and_A_cleanup': True}
                self.retained['source_generation_operation_audit'] = self.legacy_capacity_save(
                    'native-source-generation-operation-audit.json', operation_audit)
        finally:
            if mutation_started:
                write_export(original)
                restored_a = _snapshot(base_root)
                cleanup = {'schema': 'nz13.native-source-generation-explicit-A-cleanup.v1', 'qualification': False,
                    'actual_tree_A_restored': tree_value(restored_a), 'original_tree_A': tree_value(source_a),
                    'original_data_A': data_a, 'actual_restored_file_sha256': hashlib.sha256(
                        self.context['safe'].read(path, maximum=1048576)).hexdigest(),
                    'physical_B': self.retained.get('source_generation_physical_B'),
                    'operation_audit_before_cleanup': self.retained.get('source_generation_operation_audit'),
                    'cleanup_only_no_phase_epoch_policy_authority_or_cache_reset': True}
                self.retained['source_generation_A_cleanup'] = self.legacy_capacity_save(
                    'native-source-generation-A-cleanup.json', cleanup)
        after_cleanup = self.legacy_capacity_snapshot()
        snapshots['after_A_cleanup'] = self.legacy_capacity_save(
            'native-source-generation-after-A-cleanup.json', after_cleanup)
        observation = {'schema': 'nz13.native-owned-source-generation-restore-observation.v1', 'qualification': False,
            'scope': 'PHYSICALLY_CHANGED_OWNED_SOURCE_EXPORT_B_UNDER_UNCHANGED_ADMITTED_GIT_CONFIG_POLICY_A',
            'prerequisites': self.retained['source_generation_prerequisites'], 'positive': positive_result,
            'physical_B': self.retained['source_generation_physical_B'], 'negative': negative_result,
            'denial_operation_audit': self.retained['source_generation_operation_audit'],
            'A_cleanup': self.retained['source_generation_A_cleanup'], 'snapshots': snapshots,
            'negative_id': negative['task_id'], 'negative_root_ref': negative['root_ref'],
            'cold_before': cold_before, 'cold_before_negative': cold_before_negative,
            'binding_ids_after': sorted(broker._bindings), 'capture_roots_after': sorted(broker._captures),
            'native_body_before': spec_before, 'native_body_after': h.foundation.spec.to_dict(),
            'native_body_digest_before': spec_digest_before, 'native_body_digest_after': h.foundation.spec.digest,
            'phase_after': h.foundation.lifecycle.phase.value, 'job_observation': h._native_coding.job_observation(),
            'model_calls': h.model_calls()}
        self.retained['source_generation_observation'] = self.legacy_capacity_save(
            'native-source-generation-observation.json', observation)
        return self.retained['source_generation_observation']

    def http_recover_startup_observation(self, case):
        """The existing owned TLS/cookie path calls the original public HTTP route."""
        import json
        from urllib.parse import urlsplit

        from runtime.webapp import make_server

        port = urlsplit(self.origin).port
        case.assertIsNone(getattr(self, 'reserved_server', None))
        self.reserved_server = make_server('127.0.0.1', port)
        case.addCleanup(self.reserved_server.server_close)
        self.start_tls()
        h, f = self.host, self.host.foundation
        observed = {'schema': 'nz13.native-owned-http-recover-observation.v1',
            'scope': 'FIXTURE_OS_ADMISSION_OWNED_CA_MODEL_NOT_CERTIFIED',
            'phase_before': f.lifecycle.phase.value, 'task_id': self.task.task_id,
            'instance_id': h.instance_id, 'old_instance_id': self.handoff['old_instance_id'],
            'source': list(h.source), 'old_source': self.handoff['old_source'],
            'tls': self.retained['tls'], 'snapshots': {}, 'http': {},
            'same_core': h.runtime._memory_patch_admission is f.core,
            'same_coding_tasks': h.runtime._coding_tasks is h.coding_tasks,
            'coding_identity': 'operation:' + h.coding_tasks._key(self.task.task_id)}
        try:
            before = _native_startup_business_snapshot(case, h)
            observed['snapshots']['before'] = _native_startup_save(self.context,
                self.root / 'native-http-recover-before.json', before)
            for kind, path in (('status', '/api/agent/coding/tasks/'),
                               ('receipts', '/api/agent/coding/receipts/')):
                status, _, raw = self.http('GET', path + self.task.task_id)
                observed['http'][kind] = {'status': status, 'body': json.loads(raw)}
            raw = json.dumps({'task_id': self.task.task_id}).encode()
            status, _, response = self.http('POST', '/api/agent/coding/recover', raw,
                headers=self.http_headers('POST', raw, intent='coding-recover-v1'))
            observed['http']['recover'] = {'status': status, 'body': json.loads(response),
                'method': 'POST', 'path': '/api/agent/coding/recover', 'intent': 'coding-recover-v1'}
            after = _native_startup_business_snapshot(case, h)
            observed['snapshots']['after'] = _native_startup_save(self.context,
                self.root / 'native-http-recover-after.json', after)
            observed.update(phase_after=f.lifecycle.phase.value, model_calls=h.model_calls(),
                jobs=h._native_coding.job_observation(),
                active_count=len(h.coding_tasks._active), effects=len(h._native_coding.effects),
                owned_work=len(f.lifecycle._handles), source_after=list(h.source),
                http_events=self.http_events)
        finally:
            self.stop_listeners()
            observed['close'] = self.close()
            self.retained['startup_http_recover'] = _native_startup_save(self.context,
                self.root / 'native-http-recover-observation.json', observed)
        return observed, before, after





class NativeHistoryFixture:
    """One original owned foundation; DB-only history, no effect dispatcher."""

    def __init__(self, case, *, bind=True):
        import nz13_native_foundation_support as foundation_fixture
        self.case = case
        self.owner, _ = foundation_fixture.new_host(case)
        foundation_fixture.fixture_tls(self.owner)
        foundation_fixture.initialize(self.owner)
        self.foundation = self.owner.foundation
        self.governor = self.foundation.governor
        self.factory = self.owner.runner._factory
        # The pre-implementation run measures the original validators. A dummy
        # binding implementation cannot satisfy the scan or origin assertions.
        binder = getattr(self.factory, 'bind_native_history', None)
        if bind and binder is not None:
            binder(self.foundation.access)

    def invoke(self, purpose, operation, *, warm=None):
        from unittest.mock import patch

        from runtime.core_admission import Capability
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        use = NativeAccessUse.READ if purpose is Capability.READ else NativeAccessUse.CONTROL
        capture = self.foundation.access.capture(purpose, use=use)
        original_run = self.owner.runner.run

        def guarded(context, callback):
            self.case.assertIs(context.principal, capture.principal)
            self.case.assertIs(context.purpose, purpose)

            def pure(tx):
                self.foundation.access.require_capture(capture, purpose, tx=tx)
                with patch.object(self.owner, 'source_probe', side_effect=AssertionError('SOURCE_IO_INSIDE_SQL')):
                    if warm is not None:
                        warm(tx)
                    result = callback(tx)
                self.foundation.access.require_capture(capture, purpose, tx=tx)
                return result
            return original_run(context, pure)
        try:
            with patch.object(self.owner.runner, 'run', new=guarded):
                return operation(capture.principal)
        finally:
            capture.close()

    def run(self, purpose, callback):
        from runtime.memory_patch.persistence.ports import TransactionContext
        return self.invoke(purpose, lambda principal: self.owner.runner.run(
            TransactionContext(principal, purpose), callback))

    @__import__('contextlib').contextmanager
    def scans(self):
        from unittest.mock import patch

        from runtime.memory_patch.persistence.ports import LocalCoreTransaction
        original = LocalCoreTransaction.scan
        calls = []

        def observed(adapter, kind, *, limit=128, states=(), operation_kind=None):
            if adapter.factory is self.factory:
                calls.append((kind, operation_kind))
            return original(adapter, kind, limit=limit, states=states, operation_kind=operation_kind)
        with patch.object(LocalCoreTransaction, 'scan', new=observed):
            yield calls

    def seed_jobs(self):
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.mission.completion import TaskCompletionBinding
        from runtime.mission.job_contracts import JobEnvelope
        claims = []
        for task in ('history-task-a', 'history-task-b'):
            envelope = JobEnvelope.for_offline_host(self.governor.policy.scope, task,
                request_id=task + '-request', request_digest=canonical_sha256(task),
                deadline_at=self.governor._now() + 3600)
            binding = TaskCompletionBinding(self.governor.policy.scope, task, canonical_sha256((task, 'graph')),
                                            task + '-completion')
            self.invoke(Capability.MANAGE, lambda principal, envelope=envelope, binding=binding: self.governor.submit_job(
                principal, envelope, completion=binding))
            claims.append(self.invoke(Capability.COMMIT, lambda principal, task=task: self.governor.claim_job(
                principal, task, task + '-worker', 1, lease_seconds=60)))
        return tuple(claims)


def _native_startup_save(context, path, value):
    import hashlib
    import json

    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    context['safe'].write_new(path, raw)
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _native_startup_business_snapshot(case, owner):
    """Original fresh READ, including every signed row and complete governor load."""
    import json

    from runtime.core_admission import Capability
    from runtime.memory_patch.adapters.cockroach.repositories import canonical_record
    from runtime.memory_patch.audit import domain_chain
    from runtime.memory_patch.contracts.serialization import canonical_json_bytes
    from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
    from runtime.meta_hackathon.native_authority import NativeAccessUse
    from runtime.mission.coding_tasks import (
        KIND,
        CoreCodingTasks,
        decode_coding_task_row,
    )
    from runtime.mission.jobs import KIND as JOB_KIND
    from runtime.mission.jobs import load_job

    f = owner.foundation
    case.assertIs(owner.runtime._memory_patch_admission, f.core)
    case.assertIs(owner.runner, f.runner)
    capture = f.access.capture(Capability.READ, use=NativeAccessUse.READ)
    try:
        f.access.require_capture(capture, Capability.READ)
        def read(tx):
            f.access.require_capture(capture, Capability.READ, tx=tx)
            rows, coding, job_ids = {}, {}, set()
            for kind in RecordKind:
                kept = tx.scan(kind, limit=1024)
                case.assertLess(len(kept), 1024)
                for row in kept:
                    row.verify()
                    rows[kind.value + ':' + row.record_id] = {
                        'revision': row.revision, 'payload_digest': row.payload_digest,
                        'payload': row.payload, 'canonical_record': canonical_record(row)}
                    if kind is RecordKind.OPERATION and row.payload.get('schema') == KIND:
                        _, value, task = decode_coding_task_row(row, row.payload['task']['task_id'], owner.identity.spki)
                        coding[task.task_id] = CoreCodingTasks._view(value)
                    if kind is RecordKind.OPERATION and row.payload.get('operation_kind') == JOB_KIND:
                        job_ids.add(row.payload['outcome']['job']['envelope']['task_id'])
            _, target = f.target_projection.load(tx)
            value = {'rows': rows,
                'business_rows': {key: {'revision': row['revision'], 'payload_digest': row['payload_digest']}
                                  for key, row in rows.items()},
                'coding': coding, 'governor': f.governor._load(tx), 'target': target,
                'jobs': {key: load_job(f.governor, tx, key) for key in sorted(job_ids)},
                'audit_events': [event.audit_event_id for event in domain_chain(tx)],
                'audit_bindings': [{'id': event.audit_event_id, 'resource': event.resource_id,
                    'event_type': event.event_type, 'state_before': event.state_before,
                    'state_after': event.state_after, 'content_hashes': event.content_hashes,
                    'event_hash': event.event_hash} for event in domain_chain(tx)]}
            return json.loads(canonical_json_bytes(value))
        value = owner.runner.run(TransactionContext(capture.principal, Capability.READ), read)
        f.access.require_capture(capture, Capability.READ)
    finally:
        capture.close()
    case.assertTrue(capture._closed)
    return value


class NativeMainEntryFixture:
    """Data-only fixture; the original webapp.main constructs and owns its Core."""
    def __init__(self, case):
        import hashlib
        import json
        from pathlib import Path

        case.assertIsNotNone(ACTUAL_CONTEXT)
        self.case, self.context = case, ACTUAL_CONTEXT
        self.handoff = self.context['restart_handoff']
        self.root = Path(self.handoff['fixture_root'])
        self.native_root = Path(self.handoff['native_root'])
        self.origin = self.handoff['origin']
        self.retained = {}
        reference = self.context['startup_bundle']
        raw = self.context['safe'].read(Path(reference['path']))
        case.assertEqual((reference['bytes'], reference['sha256']), (len(raw), hashlib.sha256(raw).hexdigest()))
        self.bundle = json.loads(raw)
        case.assertEqual('nz13.native-owned-startup-bundle.v1', self.bundle['schema'])
        case.assertEqual(self.origin, self.bundle['origin'])
        case.assertEqual(str(self.native_root), self.bundle['native_root'])
        case.assertEqual(self.handoff['host_config'], self.bundle['host_config'])
        for reference in self.bundle['files'].values():
            raw = self.context['safe'].read(Path(reference['path']))
            case.assertEqual((reference['bytes'], reference['sha256']), (len(raw), hashlib.sha256(raw).hexdigest()))
        for name in ('fixture_root', 'native_root', 'runtime_tmp'):
            path = Path(self.handoff[name])
            self.context['owned_roots'].add(path)
            OWNED_ROOTS.append(str(path))

    def normal_main_startup_observation(self, case):
        import hashlib
        import io
        import json
        import os
        import signal
        import ssl
        import sys
        import threading
        import traceback
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import redirect_stdout
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from urllib.parse import urlsplit

        from runtime.meta_hackathon import runtime_adapter
        from runtime.mobile_gateway import wire
        from runtime.webapp import main, mobile_operator_client

        files, port = self.bundle['files'], urlsplit(self.origin).port
        self.server = SimpleNamespace(server_port=port)
        self.cookie = self.csrf = None
        self.http_events = []
        original_context = ssl.create_default_context
        self.client_context = original_context(cafile=files['certificate']['path'])
        self.client_context.minimum_version = self.client_context.maximum_version = ssl.TLSVersion.TLSv1_3
        ready, client_done, main_running = threading.Event(), threading.Event(), threading.Event()
        observed, owners = {'schema': 'nz13.native-owned-main-readiness-observation.v1',
            'scope': 'FIXTURE_OS_ADMISSION_OWNED_CA_MODEL_NOT_CERTIFIED', 'http': {}, 'snapshots': {},
            'main_entrypoint': {'file': main.__code__.co_filename, 'firstline': main.__code__.co_firstlineno},
            'actual_orig_argv': list(sys.orig_argv), 'actual_pid': os.getpid(),
            'actual_orig_argv_sha256': hashlib.sha256(json.dumps(sys.orig_argv).encode()).hexdigest()}, []
        original_qualify = runtime_adapter.NativeMobileComposition.qualify_tls
        def qualify(owner, actual_port):
            case.assertEqual(port, actual_port)
            with patch.object(ssl, 'create_default_context',
                    side_effect=lambda: original_context(cafile=files['certificate']['path'])):
                original_qualify(owner, actual_port)
            owners.append(owner)
            observed.update(instance_id=owner.instance_id, old_instance_id=self.handoff['old_instance_id'],
                source=list(owner.source), identity_spki_sha256=wire.digest(wire.canonical(owner.identity.spki)),
                actual_host_spec=owner.foundation.spec.to_dict(),
                actual_host_spec_digest=owner.foundation.spec.digest, tls_verified=owner.tls_verified,
                actual_offline_candidates_none=owner._offline_candidates is None,
                actual_coding_tasks_none=owner.runtime._coding_tasks is None,
                phase_before=owner.foundation.lifecycle.phase.value)
            before = _native_startup_business_snapshot(case, owner)
            observed['snapshots']['before_auth'] = _native_startup_save(self.context,
                self.root / 'native-normal-main-before-auth.json', before)
        output = io.StringIO()
        class ReadyOutput:
            def write(self, text):
                count = output.write(text)
                if 'NATIVE_MOBILE_HOST_READY' in output.getvalue():
                    ready.set()
                return count
            def flush(self):
                return None
        def client():
            try:
                if not ready.wait(90):
                    raise TimeoutError('NATIVE_ORIGINAL_MAIN_READY_TIMEOUT')
                owner = owners[0]
                grant = mobile_operator_client(self.native_root, {'op': 'console'})
                case.assertIs(True, grant['ok'])
                raw = ('delivery=' + grant['data']['delivery']).encode('ascii')
                headers = [('Host', self.origin.removeprefix('https://')),
                    ('Content-Type', 'application/x-www-form-urlencoded'), ('Content-Length', str(len(raw))),
                    ('Origin', self.origin), ('Sec-Fetch-Site', 'same-origin'),
                    ('Sec-Fetch-Mode', 'cors'), ('Sec-Fetch-Dest', 'empty')]
                status, response_headers, body = NativeOwnedFixture.http(self, 'POST', '/devices', raw, headers=headers)
                cookie = next(value for name, value in response_headers if name.lower() == 'set-cookie')
                self.cookie = cookie.split(';', 1)[0]
                observed['http']['devices'] = {'status': status, 'cookie_flags':
                    [flag for flag in ('Secure', 'HttpOnly', 'SameSite=Strict', 'Path=/') if flag in cookie],
                    'body': body.decode()}
                status, _, body = NativeOwnedFixture.http(self, 'GET', '/api/native-operator/session')
                session = json.loads(body)
                self.csrf = session['csrf_token']
                observed['http']['session'] = {'status': status, 'coding_profile': session['coding_profile'],
                    'csrf_present': bool(self.csrf)}
                duplicate, _, _ = NativeOwnedFixture.http(self, 'POST', '/devices', raw, headers=headers)
                observed['http']['delivery_replay_status'] = duplicate
                before_read = _native_startup_business_snapshot(case, owner)
                cold = json.loads(self.context['safe'].read(Path(observed['snapshots']['before_auth']['path']),
                    maximum=4 * 1024 * 1024))
                observed['auth_delta'] = {'scope': 'ORIGINAL_CONSOLE_DELIVERY_COOKIE_SESSION_CEREMONY',
                    'added': sorted(set(before_read['rows']) - set(cold['rows'])),
                    'removed': sorted(set(cold['rows']) - set(before_read['rows'])),
                    'changed': sorted(name for name in set(cold['rows']) & set(before_read['rows'])
                                      if cold['rows'][name] != before_read['rows'][name])}
                observed['snapshots']['before'] = _native_startup_save(self.context,
                    self.root / 'native-normal-main-before-readiness.json', before_read)
                status, _, raw = NativeOwnedFixture.http(self, 'GET', '/api/native-operator/readiness')
                value = json.loads(raw)
                observed['http']['readiness'] = {'status': status, 'body': value}
                if status == 200:
                    wire.verify(owner.identity.spki, value['signature'], value['observation'])
                    observed['readiness_signature_verified'] = True
                after = _native_startup_business_snapshot(case, owner)
                observed['snapshots']['after'] = _native_startup_save(self.context,
                    self.root / 'native-normal-main-after.json', after)
                observed.update(phase_after=owner.foundation.lifecycle.phase.value, model_calls=owner.model_calls(),
                    http_events=self.http_events, source_after=list(owner.source))
            finally:
                client_done.set()
                if main_running.is_set():
                    os.kill(os.getpid(), signal.SIGINT)
        argv = [str(Path(main.__code__.co_filename)), '--mobile-native', '--state-dir', str(self.native_root),
            '--mobile-existing-profile', '--native-host-composition', files['host_spec']['path'],
            '--mobile-origin', self.origin, '--mobile-tls-certificate', files['certificate']['path'],
            '--mobile-tls-key', files['key']['path'], '--host', '127.0.0.1', '--port', str(port)]
        case.assertEqual(argv[1:], self.context['main_cli_tail'])
        case.assertEqual(argv[1:], list(sys.orig_argv[-len(argv[1:]):]))
        observed['main_sys_argv'] = argv
        observed['native_cli_tail_present_in_actual_orig_argv'] = True
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='owned-normal-main-client')
        future = None
        old_argv = list(sys.argv)
        try:
            sys.argv = argv
            with (patch.object(runtime_adapter, '_desktop_operator_uid', return_value=(os.getuid(),
                      {'uid': os.getuid(), 'method': 'FIXTURE_OS_ADMISSION'})),
                  patch.object(runtime_adapter.NativeMobileComposition, 'qualify_tls', new=qualify),
                  redirect_stdout(ReadyOutput())):
                main_running.set()
                future = pool.submit(client)
                main()
        finally:
            main_running.clear()
            ready.set()
            sys.argv = old_argv
            client_done.wait(95)
            pool.shutdown(wait=True)
            error = future.exception() if future is not None else None
            if error is not None:
                observed['client_error'] = {'type': type(error).__name__, 'message': str(error),
                    'traceback': ''.join(traceback.format_exception(error))}
            observed.update(main_stdout=output.getvalue(), client_returned=bool(future and future.done()))
            if owners:
                owner = owners[0]
                observed['close'] = {'closed': owner._closed, 'phase': owner.foundation.lifecycle.phase.value,
                    'scope': 'OBSERVED_AFTER_ORIGINAL_MAIN_FINALLY_RETURN'}
            self.retained['startup_normal_main'] = _native_startup_save(self.context,
                self.root / 'native-normal-main-observation.json', observed)
        if future is not None:
            future.result()
        return observed

    http_headers = NativeOwnedFixture.http_headers
