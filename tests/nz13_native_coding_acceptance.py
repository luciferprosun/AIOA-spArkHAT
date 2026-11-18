"""Explicit owned Native/Linux acceptance; never ordinary test discovery.

The operator supplies only a private fixture/runtime manifest. All positive OS
admission in this driver is labelled FIXTURE_OS_ADMISSION, model NOT_CERTIFIED.
"""
import time
import unittest
from dataclasses import asdict
from unittest.mock import patch

from runtime.core_admission import Capability
from runtime.meta_hackathon import native_coding
from runtime.mission.repair import TEST_STAGES
from runtime.mobile_gateway.wire import verify

FIXTURE_FACTORY = None


class NativeOwnedAcceptance(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(native_coding, "NativeStagePreparer", None)),
                        "NATIVE_CLOSED_JIT_STAGE_PREPARER_MISSING")
        self.assertTrue(callable(FIXTURE_FACTORY), "EXPLICIT_OWNED_NATIVE_FIXTURE_REQUIRED")
        self.fx = FIXTURE_FACTORY(self)
        self.host = self.fx.host
        self.tasks = self.host.coding_tasks

    def test_single_original_graph_jit_real_repair_and_signed_review(self):
        h, f, tasks = self.host, self.host.foundation, self.tasks
        self.assertIs(h.runtime._memory_patch_admission, h.core)
        self.assertIs(h.runtime._coding_tasks, tasks)
        self.assertIs(h.missions.core, h.core)
        self.assertIs(tasks.journal, f.intent_journal)
        self.assertIs(tasks.capsules.identity, h.identity)
        self.assertIs(h.sandbox_route.journal, tasks.journal)
        self.assertIs(h.sandbox_route.executor, h.broker)
        self.assertIs(h.portable_target.projection, f.target_projection)
        self.assertIs(h.portable_target.executor, h.portable_executor)
        self.assertIs(h.portable_target.store, h.portable_store)
        self.assertFalse(h.runtime._owns_memory_patch_admission)
        import socket
        import tempfile
        from pathlib import Path
        control = Path(tempfile.mkdtemp(prefix='aioa-handoff-')) / 'control'
        self.fx.retained['handoff_probe'] = str(control)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            try:
                peer.bind(str(control))
            except OSError as exc:
                self.fail(f'FIXTURE_HANDOFF_BIND_FAILED:{type(exc).__name__}:{exc}:length={len(str(control))}')
        from dataclasses import replace
        from runtime.mission.warrant import WarrantError
        managed = h._native_coding
        original_probe = h.sandbox_route.probe
        try:
            h.sandbox_route.probe = managed.project_probe
            with self.assertRaisesRegex(WarrantError, "^NATIVE_RETAINED_FACTORY_BINDING$"):
                f.require_bindings()
        finally:
            h.sandbox_route.probe = original_probe
        original_policy = h.broker.binding_policy
        with self.assertRaises(AttributeError):
            h.broker.binding_policy = replace(original_policy)
        self.assertIs(original_policy, h.broker.binding_policy)
        try:
            managed.sandbox_policy = replace(original_policy)
            with self.assertRaisesRegex(WarrantError, "^NATIVE_SANDBOX_POLICY_BINDING$"):
                f.require_bindings()
        finally:
            managed.sandbox_policy = original_policy
        original_profile = managed.profile
        try:
            managed.profile = replace(original_profile)
            with self.assertRaisesRegex(WarrantError, "^NATIVE_RETAINED_HOST_DATA$"):
                f.require_bindings()
        finally:
            managed.profile = original_profile
        f.require_bindings()
        self.assertEqual([], managed.job_observation())
        entries, producer_errors, settlement_errors, session_results = [], [], [], []
        def public_exception(exc):
            import re
            frames, tb = [], exc.__traceback__
            while tb is not None and len(frames) < 24:
                module = tb.tb_frame.f_globals.get('__name__', '')
                name = tb.tb_frame.f_code.co_name
                frames.append({'module': module if re.fullmatch(r'[A-Za-z0-9_.]{1,128}', module) else 'boundary',
                               'function': name if re.fullmatch(r'[A-Za-z0-9_<>]{1,96}', name) else 'boundary',
                               'line': tb.tb_lineno})
                tb = tb.tb_next
            return {'type': type(exc).__name__,
                    'code': str(exc) if re.fullmatch(r'[A-Z][A-Z0-9_]{1,95}', str(exc)) else 'BOUNDARY_ERROR',
                    'frames': frames}
        from runtime.mission.repair_validation import CoreRepositoryMaterializer
        materialize = CoreRepositoryMaterializer.materialize
        def observed_materialize(materializer, *args, **kwargs):
            try:
                return materialize(materializer, *args, **kwargs)
            except BaseException as exc:
                producer_errors.append(public_exception(exc))
                raise
        original = native_coding.NativeStagePreparer.prepare_stage
        def stage(preparer, plan, name, cancel):
            current = h._native_coding.job_observation()
            self.assertFalse(any(row['state'] in ('CLAIMED', 'STARTED') for row in current), current)
            entries.append((plan.patchset.patchset_sha256, name, len(current), int(time.time())))
            return original(preparer, plan, name, cancel)
        task = self.fx.task
        from contextlib import ExitStack
        from runtime.mission import repair_validation
        settle = repair_validation._settle_sandbox_receipt
        session_run = repair_validation._CoreValidationSession.run
        def observed_settle(*args, **kwargs):
            try:
                return settle(*args, **kwargs)
            except BaseException as exc:
                settlement_errors.append(public_exception(exc))
                raise
        def observed_run(session, *args, **kwargs):
            result = session_run(session, *args, **kwargs)
            session_results.append({'stage': result.stage, 'status': result.status,
                                    'failure_code': session.failure_code})
            return result
        with ExitStack() as stack:
            stack.enter_context(self.fx.profile_timings())
            stack.enter_context(patch.object(native_coding.NativeStagePreparer, "prepare_stage", stage))
            stack.enter_context(patch.object(CoreRepositoryMaterializer, "materialize", observed_materialize))
            if 'SETTLE_DIAG' in self.fx.context['fixture_root'].name:
                stack.enter_context(patch.object(repair_validation, '_settle_sandbox_receipt', observed_settle))
                stack.enter_context(patch.object(repair_validation._CoreValidationSession, 'run', observed_run))
            self.fx.request("create_task", {"task": task.to_dict()})
            self.fx.request("start", {"task_id": task.task_id})
            for _ in range(20):
                if tasks.wait(task.task_id, 30):
                    break
            else:
                self.fail("OWNED_NATIVE_REPAIR_DID_NOT_DRAIN")
        if 'SETTLE_DIAG' in self.fx.context['fixture_root'].name:
            import hashlib
            import json
            data = {'schema': 'nz13.native-settlement-layer-diagnostic.v1', 'diagnostic': True,
                    'exceptions': settlement_errors, 'session_results': session_results}
            diagnostic_raw = json.dumps(data, sort_keys=True).encode()
            diagnostic_path = self.fx.root / 'settlement-diagnostic.json'
            self.fx.context['safe'].write_new(diagnostic_path, diagnostic_raw)
            self.fx.retained['settlement_diagnostic'] = {'path': str(diagnostic_path),
                'sha256': hashlib.sha256(diagnostic_raw).hexdigest()}
        view = self.fx.request("get_receipts", {"task_id": task.task_id})
        self.assertEqual("REVIEW_REQUIRED", view["state"],
                         {"view": view, "producer_errors": producer_errors,
                          "jobs": h._native_coding.job_observation(),
                          "timing_diagnostic": self.fx.retained.get("layer_timings"),
                          "settlement_diagnostic": self.fx.retained.get("settlement_diagnostic"),
                          "settlement_errors": settlement_errors, "session_results": session_results})
        loop = view["run_result"]
        self.assertEqual(["FAIL", "PASS"], [row["status"] for row in loop["attempts"]])
        self.assertEqual([1, 3], [len(row["steps"]) for row in loop["attempts"]])
        self.assertEqual(["FAST_TESTS", *TEST_STAGES], [row[1] for row in entries])
        jobs = h._native_coding.job_observation()
        self.assertEqual(6, len(jobs))
        for row in jobs:
            owned = h._native_coding.jobs[row['envelope']['task_id']]
            self.assertEqual(task.deadline_at, row['envelope']['deadline_at'])
            self.assertLessEqual(row['claim']['lease_until'], owned['claim_returned_at'] + 60)
            self.assertGreaterEqual(row['claim']['lease_until'], owned['claim_requested_at'] + 59)
            self.assertLess(row['claim']['lease_until'], row['envelope']['deadline_at'])
            self.assertLessEqual(int(owned['warrant'].expires_at.timestamp()), row['claim']['lease_until'])
        self.assertTrue(all(row['state'] == 'DONE' and row['task_completion'] == 'COMPLETED'
                            and row['completion_proof'] for row in jobs), jobs)
        for signed in view['receipts']:
            verify(h.identity.spki, signed['signature'], signed['receipt'])
        self.assertEqual(0, h.model_calls())
        self.assertEqual((), tasks.lifecycle_snapshot().work)
        self.fx.retained['review'] = view
        self.fx.retained['jit_entries'] = entries

    def test_inert_open_single_use_stage_and_stop_create_no_future_claim(self):
        plan = self.fx.inert_validation()
        session = plan['validator'].open(plan['root'], plan['patchset'])
        self.assertEqual([], self.host._native_coding.job_observation())
        plan['cancel'].cancel()
        result = session.run('FAST_TESTS')
        self.assertEqual('CANCELLED', result.status)
        self.assertEqual([], self.host._native_coding.job_observation())
        with self.assertRaises(ValueError):
            session.run('FAST_TESTS')
        session.close()

    def test_produce_capacity_history_for_newer_limits_restart(self):
        self.fx.produce_capacity_history_for_newer_limits_restart(self)

    def test_old_capacity_receipt_after_newer_limits_config(self):
        self.fx.old_capacity_receipt_after_newer_limits_observation(self)

    def test_produce_legacy_v1_governor_history_before_capacity(self):
        self.fx.produce_legacy_v1_capacity_history(self)

    def test_populated_v1_governor_capacity_migration_and_old_reader(self):
        self.fx.legacy_v1_capacity_restart_observation(self)

    def test_produce_orphan_running_ack_history_for_new_process(self):
        self.fx.produce_orphan_running_ack_history(self)

    def test_produce_terminal_child_acquisition_history_for_new_process(self):
        self.fx.produce_terminal_acquisition_history(self)

    def test_populated_restart_reads_history_without_replay_or_new_epoch(self):
        self.fx.restart_history_assertions(self, recover_interrupted=True)

    def test_populated_restart_reads_declared_linux_and_git_history(self):
        self.assertEqual('TERMINAL_CHILD_ACQUISITION', self.fx.handoff['scenario'])
        self.fx.restart_history_assertions(self)

    def test_git_stop_before_applying_has_no_start_or_release(self):
        self.fx.complete_single_candidate(self)
        self.fx.git_assertions(self, admission_boundary='BEFORE_APPLYING')

    def test_git_stop_before_core_start_has_no_physical_release(self):
        self.fx.complete_single_candidate(self)
        self.fx.git_assertions(self, admission_boundary='BEFORE_START')

    def test_git_lost_applying_ack_retains_unknown_and_fences_new_work(self):
        self.fx.complete_single_candidate(self)
        self.fx.git_assertions(self, admission_boundary='LOST_APPLYING_ACK')

    def test_git_lost_physical_ack_reconciles_exact_owned_history_without_resend(self):
        self.fx.complete_single_candidate(self)
        self.fx.git_assertions(self, lost_physical_ack=True)
        self.assertEqual({'status': 'CLOSED', 'closed': True}, self.fx.close())

    def test_historical_git_warrant_settles_at_canonical_current_epoch(self):
        self.fx.complete_single_candidate(self)
        self.fx.git_assertions(self, historical_epoch=True)
        self.assertEqual({'status': 'CLOSED', 'closed': True}, self.fx.close())

    def test_git_reconciliation_scope_ownership_denials_and_lost_verified_ack(self):
        self.fx.complete_single_candidate(self)
        self.fx.git_assertions(self, reconciliation_safety=True)
        self.assertEqual({'status': 'CLOSED', 'closed': True}, self.fx.close())

    def test_git_ordinary_mutation_callbacks_do_not_read_source_in_sql(self):
        self.fx.complete_single_candidate(self)
        self.fx.observe_git_mutation_source_io(self, reconciliation_safety=False)
        self.assertEqual({'status': 'CLOSED', 'closed': True}, self.fx.close())

    def test_git_historical_mutation_callbacks_do_not_read_source_in_sql(self):
        self.fx.complete_single_candidate(self)
        self.fx.observe_git_mutation_source_io(self, reconciliation_safety=True)
        self.assertEqual({'status': 'CLOSED', 'closed': True}, self.fx.close())

    def test_git_owned_handle_survives_stop_after_physical_release_until_settlement(self):
        self.test_single_original_graph_jit_real_repair_and_signed_review()
        self.fx.git_assertions(self, stop_after_release=True)

    def test_exact_local_git_add_modify_and_independent_readback(self):
        self.test_single_original_graph_jit_real_repair_and_signed_review()
        self.fx.git_assertions(self)

    def test_portable_stop_after_seal_blocks_actual_store_write(self):
        self.fx.portable_boundary_assertions(self, 'STOP')

    def test_portable_rearm_lost_executor_ack_keeps_unknown_without_resend(self):
        self.fx.portable_boundary_assertions(self, 'EXEC_ACK')

    def test_portable_rearm_lost_committed_ack_reconciles_without_resend(self):
        self.fx.portable_boundary_assertions(self, 'COMMIT_ACK')

    def test_portable_lost_start_ack_settles_fresh_fenced_no_release_without_resend(self):
        self.fx.portable_no_release_assertions(self, 'START_ACK')

    def test_portable_revoked_session_at_write_denies_and_reconciles_no_release(self):
        self.fx.portable_no_release_assertions(self, 'SESSION_REVOKE')

    def test_physical_portable_release_rearm_separate_approvals_and_full_roots(self):
        self.fx.portable_assertions(self)

    def test_stop_release_and_ack_uncertainty_hold_ownership_until_reconciled(self):
        self.fx.stop_assertions(self)

    def test_actual_same_tls_cookie_origin_csrf_intent_and_conditional_entry(self):
        self.fx.tls_assertions(self)


    def test_native_git_constructor_uses_original_capture_outside_sql_on_denial(self):
        import inspect
        from unittest.mock import patch
        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
        from runtime.mission.git_publish import CoreRemoteGitRoute
        from runtime.mission.warrant import WarrantError
        fx = self.fx
        h, f = fx.host._native_coding, fx.host.foundation
        inert = fx.inert_validation()
        preparation = CoreRemoteGitRoute.prepare_patchset(h.base_root, inert['root'],
            source=h.spec.project_source, task=fx.task, worker_session_id='native-git-access-probe',
            capsule_digest='c' * 64)
        kwargs = {'capsules': fx.host.coding_tasks.capsules, 'preparation': preparation,
            'profile': h.profile, 'source_snapshot': h.source_snapshot,
            'source_repository': h.source_repository, 'target_repository': h.git_target_repository,
            'check': f.require_bindings, 'target_guard': lambda: h.lock}
        # The old path is still exercised before the new keyword exists. The
        # assertion below then identifies its actual unguarded initial SQL.
        if 'native_access' in inspect.signature(CoreRemoteGitRoute.for_local_patch).parameters:
            kwargs['native_access'] = f.access
        actual_capture, actual_run = f.access.capture, fx.host.runner.run
        captures = []
        def capture(purpose, *, use):
            self.assertFalse(_IN_TRANSACTION.get(), 'NATIVE_GIT_CAPTURE_INSIDE_SQL')
            captures.append(purpose)
            return actual_capture(purpose, use=use)
        def run(context, callback):
            def pure(tx):
                with patch.object(fx.host, 'source_probe', side_effect=AssertionError('NATIVE_GIT_SOURCE_INSIDE_SQL')):
                    return callback(tx)
            return actual_run(context, pure)
        with h.authority(Capability.COMMIT) as principal:
            with (patch.object(f.access, 'capture', new=capture), patch.object(fx.host.runner, 'run', new=run),
                  patch.object(f.intent_journal, '_run', side_effect=AssertionError('NATIVE_GIT_RAW_INITIAL_SQL_BYPASS')),
                  self.assertRaisesRegex(WarrantError, 'CAPSULE_REQUIRED')):
                CoreRemoteGitRoute.for_local_patch(principal, f.intent_journal, **kwargs)
        self.assertEqual([Capability.COMMIT], captures)
        self.assertEqual({}, f.access._originals)
        self.assertEqual({}, h.jobs)
        self.assertTrue(fx.host.close()['closed'])

    def test_produce_profile_generation_restore_history(self):
        self.fx.produce_profile_generation_restore_history(self)

    def test_cold_restore_refuses_newer_owned_profile(self):
        self.fx.profile_cold_restore_observation(self)


    def test_restart_changed_owned_source_export_denies_cold_restore(self):
        self.fx.source_generation_restore_observation(self)




    def test_portable_current_epoch_change_before_authorize_blocks_store_write(self):
        self.fx.portable_post_r103_boundary_assertions(self, scenario='EPOCH_BEFORE_AUTHORIZE')

    def test_portable_current_epoch_change_after_authorize_retains_unknown_until_readback(self):
        self.fx.portable_post_r103_boundary_assertions(self, scenario='EPOCH_AFTER_AUTHORIZE')

    def test_portable_session_revoked_after_authorize_blocks_store_write(self):
        self.fx.portable_post_r103_boundary_assertions(self, scenario='SESSION_AFTER_AUTHORIZE')

    def test_portable_expired_claim_after_authorize_blocks_store_write(self):
        self.fx.portable_expired_claim_after_authorize_assertions(self)

    def test_portable_native_tls_invalid_before_authorize_blocks_store_write(self):
        self.fx.portable_native_tls_at_write_assertions(self, after_authorize=False)

    def test_portable_native_tls_invalid_after_authorize_blocks_store_write(self):
        self.fx.portable_native_tls_at_write_assertions(self, after_authorize=True)

    def test_portable_native_sql_retry_reuses_authorize_and_consume_captures_without_domain_io(self):
        self.fx.portable_native_sql_retry_assertions(self)

    def test_portable_source_export_changed_after_capture_blocks_store_write(self):
        self.fx.portable_source_after_capture_assertions(self, mutate_export=True)

    def test_portable_unchanged_source_after_capture_allows_one_store_write(self):
        self.fx.portable_source_after_capture_assertions(self, mutate_export=False)

    def test_portable_claim_expiry_in_final_store_guard_blocks_physical_write(self):
        self.fx.portable_claim_expiry_in_final_store_guard_assertions(self)


    def test_portable_claim_expiry_during_ack_observation_blocks_store_write(self):
        self.fx.portable_expired_claim_after_authorize_assertions(self, observer_delay=True)




def suite():
    return unittest.defaultTestLoader.loadTestsFromTestCase(NativeOwnedAcceptance)
