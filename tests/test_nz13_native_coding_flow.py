"""Causal gaps in the original Native graph and per-stage execution seam."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import nz13_native_foundation_support as fx
from nz13_native_coding_support import (
    NativeCompletionCase,
    require_method,
    require_parameter,
)
from runtime.core_admission import AdmissionError, Capability
from runtime.meta_hackathon import runtime_adapter
from runtime.meta_hackathon.native_authority import NativeAccessUse
from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
from runtime.mission.coding_tasks import CoreCodingTasks
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.repair_validation import CoreSandboxValidation
from runtime.mission.worker import CandidateFile, CandidatePatch
from runtime.mobile_gateway.wire import verify
from runtime.webapp import WebRuntimeService


class NativeCodingFlowTests(NativeCompletionCase):
    def test_owned_offline_candidates_are_explicit_host_data(self):
        require_parameter(self, NativeMobileComposition, "offline_candidates",
                          "NATIVE_OFFLINE_HOST_CANDIDATES_INPUT_MISSING")

    def test_controller_binds_original_fresh_native_access(self):
        require_parameter(self, CoreCodingTasks, "native_access",
                          "NATIVE_CODING_FRESH_PURPOSE_BINDING_MISSING")

    def test_validation_has_requested_stage_only_preparation(self):
        require_parameter(self, CoreSandboxValidation, "stage_preparer",
                          "NATIVE_JIT_VALIDATION_PREPARER_MISSING")

    def test_startup_readiness_uses_canonical_signed_read_projection(self):
        require_method(self, NativeMobileComposition, "readiness",
                       "NATIVE_CANONICAL_STARTUP_OBSERVATION_MISSING")

    def test_same_listener_borrows_original_native_access(self):
        require_parameter(self, WebRuntimeService, "native_access",
                          "NATIVE_WEB_ORIGINAL_PURPOSE_BINDING_MISSING")

    def test_default_off_constructs_one_original_runtime_without_activation(self):
        root = Path(tempfile.mkdtemp(prefix="native-coding-off-"))
        forbidden = AssertionError("DEFAULT_OFF_EXTRA_ACTIVATION")
        with patch.object(runtime_adapter, "_desktop_operator_uid", return_value=(
                os.getuid(), {"uid": os.getuid(), "method": "FIXTURE_OS_ADMISSION"})), \
             patch("runtime.meta_hackathon.native_authority.NativeAuthorityFoundation.bind_owner", side_effect=forbidden), \
             patch("runtime.mission.sandbox_linux.LinuxSandboxBroker.__init__", side_effect=forbidden), \
             patch("nonzero_cloudops.adapters.portable.PortableExecutor.__init__", side_effect=forbidden), \
             patch.object(CoreCodingTasks, "__init__", side_effect=forbidden):
            owner = NativeMobileComposition(root / "native", origin="https://fixture.example.org",
                                            source_probe=lambda: ("a" * 40, "b" * 64))
        self.addCleanup(owner.close)
        self.assertIsNone(owner.foundation)
        self.assertIsNone(owner.runtime._coding_tasks)
        self.assertIs(owner.runtime._memory_patch_admission, owner.core)
        self.assertEqual(0, owner.model_calls())
        self.assertIsNone(owner.runtime.provider_manager)
        self.assertIsNone(owner.runtime.executor)

    def test_offline_input_rejects_missing_host_and_mutable_proposals_before_admission(self):
        require_parameter(self, NativeMobileComposition, "offline_candidates",
                          "NATIVE_OFFLINE_HOST_CANDIDATES_INPUT_MISSING")
        root = Path(tempfile.mkdtemp(prefix="native-coding-input-"))
        proposal = CandidatePatch((CandidateFile("src/app.py", "def value():\n    return 2\n"),))
        with patch.object(runtime_adapter, "_desktop_operator_uid", side_effect=AssertionError("ADMISSION_BEFORE_CLOSED_INPUT")):
            for candidates in ((proposal,), [proposal], (), (object(),)):
                with self.subTest(type=type(candidates).__name__), self.assertRaises(AdmissionError):
                    NativeMobileComposition(root / "native", origin="https://fixture.example.org",
                                            offline_candidates=candidates)

    def test_unbound_host_readiness_is_signed_and_never_initializes_capacity(self):
        require_method(self, NativeMobileComposition, "readiness",
                       "NATIVE_CANONICAL_STARTUP_OBSERVATION_MISSING")
        owner, _ = fx.new_host(self)
        fx.fixture_tls(owner)
        capture = owner.foundation.access.capture(Capability.READ, use=NativeAccessUse.READ)
        self.addCleanup(capture.close)
        result = owner.readiness(capture)
        observation = result["observation"]
        verify(owner.identity.spki, result["signature"], observation)
        self.assertEqual("aioa.native-startup-observation.v1", observation["schema"])
        self.assertEqual("NONE", observation["authority"])
        self.assertEqual("NOT_CERTIFIED", observation["model_certification"])
        self.assertEqual("UNBOUND", observation["coding_state"])
        self.assertEqual(0, observation["governor"]["epoch"])
        self.assertEqual(0, owner.model_calls())
        self.assertIsNone(owner.runtime._coding_tasks)

    def test_same_core_controller_uses_original_capture_outside_sql(self):
        require_parameter(self, CoreCodingTasks, "native_access",
                          "NATIVE_CODING_FRESH_PURPOSE_BINDING_MISSING")
        owner, _ = fx.new_host(self)
        fx.fixture_tls(owner)
        foundation = owner.foundation
        capsules = CorePatchCapsules(foundation.intent_journal, owner.identity,
                                    source_probe=lambda: foundation.spec.project_source)
        tasks = CoreCodingTasks(foundation.intent_journal, capsules, native_access=foundation.access)
        self.addCleanup(tasks.close)
        principal = owner.core.local_operator(Capability.READ)
        actual_run = owner.runner.run
        probes = []
        actual_probe = owner.source_probe
        owner.source_probe = lambda: (probes.append("outside"), actual_probe())[1]
        def run(context, callback):
            def pure(tx):
                with patch.object(owner, "source_probe", side_effect=AssertionError("SOURCE_INSIDE_SQL")):
                    return callback(tx)
            return actual_run(context, pure)
        with patch.object(owner.runner, "run", side_effect=run):
            view = tasks.runtime_view(principal)
        self.assertEqual("UNBOUND", view["controller_state"])
        self.assertTrue(probes)
        self.assertIs(tasks.journal, foundation.intent_journal)
        self.assertIs(tasks.capsules.identity, owner.identity)

    def test_managed_route_capture_is_original_and_callback_is_pure(self):
        from contextlib import nullcontext

        from runtime.mission.tools import CoreToolRoute
        require_parameter(self, CoreToolRoute, "native_access", "NATIVE_TOOL_ROUTE_PURE_CAPTURE_JOIN_MISSING")
        owner, _ = fx.new_host(self)
        fx.fixture_tls(owner)
        f = owner.foundation
        route = CoreToolRoute(f.intent_journal, f.liability, workspace="fixture-workspace", policy_revision=1,
                              probe=lambda: None, executor=lambda *args: None, target_guard=nullcontext,
                              native_access=f.access)
        def pure(_tx):
            with patch.object(owner, "source_probe", side_effect=AssertionError("SOURCE_INSIDE_SQL")):
                return 42
        self.assertEqual(42, route._run(owner.core.local_operator(Capability.READ), Capability.READ, pure))
        self.assertEqual({}, f.access._originals)
        with self.assertRaises(ValueError):
            CoreToolRoute(f.intent_journal, f.liability, workspace="fixture-workspace", policy_revision=1,
                          probe=lambda: None, executor=lambda *args: None, target_guard=nullcontext,
                          native_access=object())


class NativeTransactionHistoryTests(NativeCompletionCase):
    """Real immutable histories are reused only in their original SQL snapshot."""

    def fixture(self, *, bind=True):
        from nz13_native_coding_support import NativeHistoryFixture
        return NativeHistoryFixture(self, bind=bind)

    def test_same_transaction_reuses_complete_governor_and_audit_histories(self):
        from runtime.memory_patch.audit import domain_chain
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.governor import KIND
        fixture = self.fixture()
        with fixture.scans() as scans:
            def read(tx):
                states = [fixture.governor._load(tx) for _ in range(3)]
                chains = [domain_chain(tx) for _ in range(3)]
                self.assertEqual(states[0], states[-1])
                self.assertEqual(chains[0], chains[-1])
                self.assertTrue(chains[0])
            fixture.run(Capability.READ, read)
        self.assertEqual(1, scans.count((RecordKind.OPERATION, KIND)), 'REPEATED_COMPLETE_GOVERNOR_REPLAY')
        self.assertEqual(1, scans.count((RecordKind.AUDIT, None)), 'REPEATED_COMPLETE_AUDIT_REPLAY')

    def test_two_distinct_jobs_reuse_global_rows_but_select_versions_independently(self):
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.governor import GovernorError
        from runtime.mission.jobs import load_job
        fixture = self.fixture()
        claims = fixture.seed_jobs()
        with fixture.scans() as scans:
            def read(tx):
                for claim in claims:
                    latest = load_job(fixture.governor, tx, claim.task_id)
                    historical = load_job(fixture.governor, tx, claim.task_id, version=1)
                    self.assertEqual(('CLAIMED', 2, claim.task_id),
                                     (latest['state'], latest['version'], latest['envelope']['task_id']))
                    self.assertEqual(('QUEUED', 1, None),
                                     (historical['state'], historical['version'], historical['claim']))
                with self.assertRaisesRegex(GovernorError, 'GOVERNOR_INTEGRITY'):
                    load_job(fixture.governor, tx, claims[1].task_id, version=99)
            fixture.run(Capability.READ, read)
        # One complete global scan, plus the four original selected-binding
        # scans. Invalid version 99 must still fail before a binding lookup.
        self.assertEqual(5, scans.count((RecordKind.OPERATION, None)), 'GLOBAL_JOB_ROWS_REPLAYED_PER_SELECTED_TASK')
        self.assertEqual(1, scans.count((RecordKind.AUDIT, None)))

    def test_selected_binding_is_checked_after_global_history_reuse_and_mutation(self):
        from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
        from runtime.mission.jobs import load_job
        from runtime.mission.sandbox_bindings import BINDING_SCHEMA
        from runtime.mission.warrant import WarrantError
        fixture = self.fixture()
        first, second = fixture.seed_jobs()
        def change(tx):
            load_job(fixture.governor, tx, first.task_id)
            tx.insert(StoredRecord(RecordKind.OPERATION, 'unusable-selected-binding', tx.context.scope, 1,
                                   {'schema': BINDING_SCHEMA, 'task_id': second.task_id}))
            self.assertEqual(first.task_id, load_job(fixture.governor, tx, first.task_id)['envelope']['task_id'])
            with self.assertRaisesRegex(WarrantError, 'SANDBOX_JOB_BINDING_REQUIRED'):
                load_job(fixture.governor, tx, second.task_id)
        fixture.run(Capability.MANAGE, change)

    def test_mutable_governor_results_and_deeply_frozen_audit_do_not_poison_reads(self):
        from dataclasses import FrozenInstanceError

        from runtime.memory_patch.audit import domain_chain
        fixture = self.fixture()
        def read(tx):
            state = fixture.governor._load(tx)
            state['kill'] = True
            state['reservations']['injected'] = {'state': 'COMMITTED'}
            fresh = fixture.governor._load(tx)
            self.assertFalse(fresh['kill'])
            self.assertEqual({}, fresh['reservations'])
            event = domain_chain(tx)[0]
            with self.assertRaises(TypeError):
                event.content_hashes['content'] = '0' * 64
            with self.assertRaises(FrozenInstanceError):
                event.sequence_number = 99
            self.assertEqual(event.event_hash, domain_chain(tx)[0].event_hash)
        fixture.run(Capability.READ, read)

    def test_normal_append_and_replace_invalidate_all_history_products(self):
        import json

        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
        from runtime.mission.governor import KIND
        fixture = self.fixture()
        with fixture.scans() as scans:
            def change(tx):
                before = fixture.governor._load(tx)
                fixture.governor._load(tx)
                state = json.loads(canonical_json_bytes(before))
                state['kill'] = True
                fixture.governor._write(tx, before, state, fixture.governor._now())
                self.assertTrue(fixture.governor._load(tx)['kill'])
                self.assertTrue(fixture.governor._load(tx)['kill'])
                row = StoredRecord(RecordKind.OPERATION, 'ordinary-mutation', tx.context.scope, 1, {'value': 1})
                tx.insert(row)
                fixture.governor._load(tx)
                tx.replace(StoredRecord(row.kind, row.record_id, row.scope, 2, {'value': 2}), expected_revision=1)
                self.assertEqual(2, tx.get(row.kind, row.record_id).payload['value'])
                fixture.governor._load(tx)
            fixture.run(Capability.MANAGE, change)
        self.assertEqual(4, scans.count((RecordKind.OPERATION, KIND)), 'HISTORY_REUSE_MUST_TRACK_ACTUAL_MUTATION')

    def test_direct_same_connection_corruption_forces_original_integrity_denial_and_rollback(self):
        from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
        from runtime.memory_patch.persistence.ports import RecordKind
        fixture = self.fixture()
        def corrupt(tx):
            fixture.governor._load(tx)
            fixture.factory.db.execute('UPDATE core_records_v1 SET record_digest=? WHERE scope_key=? AND kind=? AND record_id=?',
                ('0' * 64, tx._adapter.scope_key, RecordKind.OPERATION.value, fixture.governor._key(1)))
            with self.assertRaises(MemoryPatchError) as denied:
                fixture.governor._load(tx)
            self.assertIs(denied.exception.code, ErrorCode.INTEGRITY_FAILED)
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        with self.assertRaises(MemoryPatchError) as rolled_back:
            fixture.run(Capability.MANAGE, corrupt)
        self.assertIs(rolled_back.exception.code, ErrorCode.STATE_CONFLICT)
        self.assertEqual(1, fixture.run(Capability.READ, fixture.governor._load)['epoch'])

    def test_direct_audit_delete_is_detected_in_same_transaction(self):
        from runtime.memory_patch.audit import domain_chain
        from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
        from runtime.memory_patch.persistence.ports import RecordKind
        fixture = self.fixture()
        fixture.seed_jobs()
        def corrupt(tx):
            events = domain_chain(tx)
            self.assertGreater(len(events), 1)
            fixture.factory.db.execute('DELETE FROM core_records_v1 WHERE scope_key=? AND kind=? AND record_id=?',
                (tx._adapter.scope_key, RecordKind.AUDIT.value, events[0].audit_event_id))
            with self.assertRaises(MemoryPatchError) as denied:
                domain_chain(tx)
            self.assertIs(denied.exception.code, ErrorCode.PROVENANCE_CORRUPT)
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        with self.assertRaises(MemoryPatchError) as rolled_back:
            fixture.run(Capability.MANAGE, corrupt)
        self.assertIs(rolled_back.exception.code, ErrorCode.STATE_CONFLICT)
        self.assertGreater(len(fixture.run(Capability.READ, domain_chain)), 1)

    def test_copied_forged_alias_and_rewrapped_views_cannot_borrow_trusted_history(self):
        import copy

        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.memory_patch.persistence.ports import (
            TransactionContext,
            TransactionView,
        )
        fixture = self.fixture()
        class AliasView(TransactionView):
            pass
        def read(tx):
            fixture.governor._load(tx)
            forged = object.__new__(TransactionView)
            forged.__dict__.update(tx.__dict__)
            alternatives = (lambda: copy.copy(tx), lambda: forged, lambda: TransactionView(tx._adapter, tx.context),
                            lambda: AliasView(tx._adapter, tx.context),
                            lambda: TransactionView(tx._adapter, TransactionContext(tx.context.principal, tx.context.purpose)))
            denied = []
            for alternate in alternatives:
                try:
                    fixture.governor._load(alternate())
                except MemoryPatchError:
                    denied.append(True)
                else:
                    denied.append(False)
            self.assertEqual(1, fixture.governor._load(tx)['epoch'])
            return denied
        self.assertEqual([True] * 5, fixture.run(Capability.READ, read),
                         'COPIED_FORGED_REWRAPPED_ALIAS_AND_FOREIGN_CONTEXT_VIEWS_ACCEPTED')

    def test_foreign_governor_cannot_alias_original_native_history_reader(self):
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.mission.governor import CoreDualGovernor
        fixture = self.fixture()
        foreign = CoreDualGovernor(fixture.owner.core, fixture.owner.runner, fixture.governor.policy)
        def read(tx):
            fixture.governor._load(tx)
            try:
                foreign._load(tx)
            except MemoryPatchError:
                return True
            return False
        self.assertTrue(fixture.run(Capability.READ, read), 'FOREIGN_GOVERNOR_ACCEPTED')

    def test_serialization_retry_discards_history_and_uncommitted_writes(self):
        from runtime.memory_patch.errors import (
            MemoryPatchError,
            RetryableSerializationError,
        )
        from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
        from runtime.mission.governor import KIND
        fixture = self.fixture()
        attempts = []
        with fixture.scans() as scans:
            def retry(tx):
                attempts.append(tx)
                fixture.governor._load(tx)
                fixture.governor._load(tx)
                self.assertIsNone(tx.get(RecordKind.OPERATION, 'rolled-back-attempt'))
                if len(attempts) == 1:
                    tx.insert(StoredRecord(RecordKind.OPERATION, 'rolled-back-attempt', tx.context.scope, 1, {'value': 1}))
                    raise RetryableSerializationError()
                self.assertIsNot(attempts[0], tx)
                with self.assertRaises(MemoryPatchError):
                    fixture.governor._load(attempts[0])
                return 'second-attempt'
            self.assertEqual('second-attempt', fixture.run(Capability.MANAGE, retry))
        self.assertEqual(2, len(attempts))
        self.assertEqual(2, scans.count((RecordKind.OPERATION, KIND)), 'HISTORY_REUSED_ACROSS_RETRY_OR_NOT_REUSED_WITHIN_ATTEMPT')

    def test_new_transaction_and_escaped_view_never_reuse_previous_snapshot(self):
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.governor import KIND
        fixture = self.fixture()
        escaped = []
        with fixture.scans() as scans:
            def read(tx):
                escaped.append(tx)
                fixture.governor._load(tx)
                return fixture.governor._load(tx)
            self.assertEqual(fixture.run(Capability.READ, read), fixture.run(Capability.READ, read))
        self.assertIsNot(escaped[0], escaped[1])
        with self.assertRaises(MemoryPatchError):
            fixture.governor._load(escaped[0])
        self.assertEqual(2, scans.count((RecordKind.OPERATION, KIND)))

    def test_foundation_only_default_keeps_original_uncached_behavior(self):
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.governor import KIND
        fixture = self.fixture(bind=False)
        with fixture.scans() as scans:
            fixture.run(Capability.READ, lambda tx: (fixture.governor._load(tx), fixture.governor._load(tx)))
        self.assertEqual(2, scans.count((RecordKind.OPERATION, KIND)))
        self.assertIsNone(fixture.owner.runtime._coding_tasks)
        self.assertIsNone(getattr(fixture.owner, 'broker', None))
        self.assertEqual(0, fixture.owner.model_calls())

    def test_history_hit_still_checks_current_core_file_identity_and_native_phase(self):
        from datetime import timedelta

        from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
        from runtime.meta_hackathon.native_authority import NativePhase
        fixture = self.fixture()
        def read(tx):
            fixture.governor._load(tx)
            with (patch.object(fixture.owner.core, '_clock', return_value=tx.context.principal.expires_at + timedelta(seconds=1)),
                  self.assertRaises(AdmissionError)):
                fixture.governor._load(tx)
            with patch.object(fixture.factory, '_file_check', side_effect=MemoryPatchError(ErrorCode.INTEGRITY_FAILED)):
                with self.assertRaises(MemoryPatchError) as denied:
                    fixture.governor._load(tx)
                self.assertIs(denied.exception.code, ErrorCode.INTEGRITY_FAILED)
            capture = next(entry[0] for entry in fixture.foundation.access._originals.values()
                           if entry[0].principal is tx.context.principal)
            with (patch.object(fixture.foundation.lifecycle, '_phase', NativePhase.FENCED),
                  self.assertRaises(AdmissionError)):
                fixture.foundation.access.require_capture(capture, Capability.READ, tx=tx)
            self.assertEqual(1, fixture.governor._load(tx)['epoch'])
        fixture.run(Capability.READ, read)

    def test_expired_actual_claim_is_denied_after_warming_immutable_histories(self):
        from runtime.mission.governor import GovernorError
        from runtime.mission.jobs import load_job
        fixture = self.fixture()
        claim = fixture.seed_jobs()[0]
        def warm(tx):
            fixture.governor._load(tx)
            load_job(fixture.governor, tx, claim.task_id)
        with (patch.object(fixture.governor, 'clock', return_value=claim.lease_until),
              self.assertRaisesRegex(GovernorError, 'STALE_RESERVATION_EPOCH')):
            fixture.invoke(Capability.COMMIT, lambda principal: fixture.governor.begin_job(principal, claim), warm=warm)

    def test_changed_kill_and_epoch_are_not_immutable_history_authority(self):
        import json

        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.mission.governor import GovernorError
        fixture = self.fixture()
        claim = fixture.seed_jobs()[0]
        for field, expected in (('kill', 'KILL_SWITCH'), ('epoch', 'STALE_EPOCH')):
            def warm(tx, field=field):
                before = fixture.governor._load(tx)
                state = json.loads(canonical_json_bytes(before))
                state[field] = True if field == 'kill' else state[field] + 1
                fixture.governor._write(tx, before, state, fixture.governor._now())
            with self.subTest(field=field), self.assertRaisesRegex(GovernorError, expected):
                fixture.invoke(Capability.COMMIT, lambda principal: fixture.governor.claim_job(
                    principal, claim.task_id, claim.worker_id, claim.governor_epoch, lease_seconds=60), warm=warm)
        self.assertEqual(1, fixture.run(Capability.READ, fixture.governor._load)['epoch'])


    def test_original_readers_cannot_be_registered_again_or_replaced_by_aliases(self):
        from runtime.memory_patch import audit
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.memory_patch.persistence.ports import _register_history_reader
        fixture = self.fixture()
        original = audit._read_domain_chain
        with self.assertRaises(MemoryPatchError):
            _register_history_reader('AUDIT_CHAIN', original)
        def alias(tx):
            return original(tx)
        with self.assertRaises(MemoryPatchError):
            _register_history_reader('AUDIT_CHAIN', alias)
        def read(tx):
            audit.domain_chain(tx)
            with patch.object(audit, '_read_domain_chain', new=alias), self.assertRaises(MemoryPatchError):
                audit.domain_chain(tx)
            return audit.domain_chain(tx)
        self.assertTrue(fixture.run(Capability.READ, read))

    def test_binding_rejects_foreign_access_without_enabling_or_rebinding(self):
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.meta_hackathon.native_authority import NativeCoreAccess
        from runtime.mission.governor import KIND
        fixture = self.fixture(bind=False)
        with self.assertRaises(MemoryPatchError):
            fixture.factory.bind_native_history(NativeCoreAccess(fixture.foundation))
        with fixture.scans() as scans:
            fixture.run(Capability.READ, lambda tx: (fixture.governor._load(tx), fixture.governor._load(tx)))
        self.assertEqual(2, scans.count((RecordKind.OPERATION, KIND)))
        fixture.factory.bind_native_history(fixture.foundation.access)
        with self.assertRaises(MemoryPatchError):
            fixture.factory.bind_native_history(fixture.foundation.access)
        with fixture.scans() as scans:
            fixture.run(Capability.READ, lambda tx: (fixture.governor._load(tx), fixture.governor._load(tx)))
        self.assertEqual(1, scans.count((RecordKind.OPERATION, KIND)))

    def test_sql_snapshot_end_cannot_reuse_history_even_before_view_return(self):
        from runtime.memory_patch.errors import MemoryPatchError
        fixture = self.fixture()
        def read(tx):
            fixture.governor._load(tx)
            fixture.factory.db.commit()
            try:
                fixture.governor._load(tx)
            except MemoryPatchError:
                return True
            return False
        self.assertTrue(fixture.run(Capability.READ, read), 'SQL_SNAPSHOT_ALREADY_ENDED')

    def test_reconstructed_registry_tuple_cannot_replace_actual_begin_origin(self):
        from runtime.memory_patch.errors import MemoryPatchError
        fixture = self.fixture()
        def read(tx):
            fixture.governor._load(tx)
            original = fixture.factory._native_history_transaction
            try:
                fixture.factory._native_history_transaction = tuple(iter(original))
                try:
                    fixture.governor._load(tx)
                except MemoryPatchError:
                    return True
                return False
            finally:
                fixture.factory._native_history_transaction = original
        self.assertTrue(fixture.run(Capability.READ, read), 'RECONSTRUCTED_BEGIN_ORIGIN_ACCEPTED')
