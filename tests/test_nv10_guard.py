"""NV10 effects against an actual local HTTP target; database is a labelled FIXTURE."""

from dataclasses import replace
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from nv09_support import GuardFixture, LocalTarget, SCOPE, proposal, response
from nv10_support import POISON, child, evidence
from runtime.core_admission import Capability
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.mission.contracts import MissionError
from runtime.mission.lite_journal import LiteJournal
from runtime.service_guard.contracts import GuardError, parse_proposal
from runtime.service_guard.target import LoopbackTargetClient, TargetUnknown


class NV10GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = LocalTarget(self.root / "target", target_id="nv10-target")
        self.addCleanup(self.target.close)
        self.fx = GuardFixture(self.root / "runtime", self.target.client)
        self.addCleanup(self.fx.close)

    def probe(self, fx=None, target=None, **changes):
        fx, target = fx or self.fx, target or self.target
        return child({"mode": "guard-probe", "root": str(fx.root),
                      "port": target.port, "target_id": target.target_id,
                      "scope": list(target.scope.binding()), "key": target.key.hex(),
                      "operation_id": fx.operation_id, **changes})

    def no_effect(self):
        self.assertEqual(0, self.target.client.read()["effect_count"])
        self.assertIsNone(self.fx.inspect()["receipt"])

    def test_expiry_before_intent_stays_blocked_after_rollback_and_fresh_process(self):
        approval = self.fx.approve(validity_seconds=2)
        initial = self.fx.clock_value
        self.fx.clock_value = approval["expires_at"] + 1
        result = self.fx.guard.cycle(self.fx.runtime._lite_scheduler, self.fx.operation_id)
        self.assertEqual("CONSENT_EXPIRED_OR_POLICY_CHANGED", result["reason"])
        self.assertIsNone(self.fx.inspect()["intent"])
        self.assertIsNotNone(self.fx.inspect()["blocked"])
        self.fx.clock_value = initial
        rollback = self.fx.guard.cycle(self.fx.runtime._lite_scheduler, self.fx.operation_id)
        self.assertEqual("BLOCKED", rollback["status"])
        self.no_effect()
        self.fx.close()
        fresh = self.probe(clock=initial)
        self.assertNotEqual(os.getpid(), fresh["pid"])
        self.assertEqual("BLOCKED", fresh["result"]["status"])
        self.assertEqual("CONSENT_EXPIRED_OR_POLICY_CHANGED", fresh["result"]["reason"])
        self.assertEqual([], fresh["requests"])
        self.assertEqual(0, fresh["actor_calls"])
        self.assertEqual(0, self.target.client.read()["effect_count"])
        evidence("guard-expiry-clock", label="REAL_LOCAL_TARGET", revivals=0,
                 t1=initial, t2=approval["expires_at"] + 1, fresh_pid=fresh["pid"])

    def test_staged_effect_token_expires_at_boundary_and_never_revives(self):
        approval = self.fx.approve(validity_seconds=5)
        initial = self.fx.clock_value
        captured = []

        def hold(client, command, authorization=None):
            captured.append((command, authorization))
            raise TargetUnknown()

        with patch.object(LoopbackTargetClient, "dispatch", hold):
            self.assertEqual("UNKNOWN", self.fx.tick()["status"])
        command, authorization = captured[0]
        self.fx.clock_value = approval["expires_at"] + 1
        calls = []
        original = http.client.HTTPConnection.request

        def count(connection, method, url, *args, **kwargs):
            calls.append(method)
            return original(connection, method, url, *args, **kwargs)

        with patch.object(http.client.HTTPConnection, "request", count):
            with self.assertRaisesRegex(GuardError, "CONSENT_EXPIRED_OR_POLICY_CHANGED"):
                self.target.client.dispatch(command, authorization)
            self.fx.clock_value = initial
            with self.assertRaisesRegex(GuardError, "EFFECT_AUTHORIZATION_DENIED"):
                self.target.client.dispatch(command, authorization)
        self.assertNotIn("POST", calls)
        self.assertEqual("BLOCKED", self.fx.guard.cycle(
            self.fx.runtime._lite_scheduler, self.fx.operation_id)["status"])
        self.no_effect()

    def test_target_a_b_a2_keeps_monotonic_revision_and_denies_original_approval(self):
        approval = self.fx.approve()
        self.target.state.operator_advance(mode="MAINTENANCE")
        middle = self.target.client.read()
        self.target.state.operator_advance(mode="NORMAL")
        final = self.target.client.read()
        self.assertEqual([1, 2, 3], [approval["approved_revision"], middle["revision"], final["revision"]])
        result = self.fx.tick()
        self.assertEqual("STALE_TARGET", result["reason"])
        self.assertIsNone(self.fx.inspect()["intent"])
        self.no_effect()
        evidence("target-ABA2", label="REAL_LOCAL_TARGET", revisions=[1, 2, 3], stale_effects=0)

    def test_owner_approval_cannot_transfer_to_different_target(self):
        self.fx.approve()
        self.fx.close()
        other = LocalTarget(self.root / "different-target", target_id="nv10-other")
        self.addCleanup(other.close)
        fresh = GuardFixture(self.root / "runtime", other.client)
        self.addCleanup(fresh.close)
        result = fresh.tick()
        self.assertEqual("CONSENT_EXPIRED_OR_POLICY_CHANGED", result["reason"])
        self.assertIsNone(fresh.inspect()["intent"])
        self.assertEqual(0, self.target.client.read()["effect_count"])
        self.assertEqual(0, other.client.read()["effect_count"])

    def test_poisoned_observation_and_summary_cannot_grant_authority(self):
        actual = self.target.client.read()
        with patch.object(LoopbackTargetClient, "read", return_value={**actual, "instructions": POISON}):
            result = self.fx.tick()
        self.assertEqual("TARGET_IDENTITY_OR_STATE_MISMATCH", result["reason"])
        self.assertEqual([], self.fx.transport.calls)
        self.fx.transport.replies = [response(proposal(actual, reason_summary=POISON))]
        self.assertEqual("CONSENT_REQUIRED", self.fx.tick()["reason"])
        self.no_effect()

    def test_receipt_metadata_cannot_override_invalid_facts_or_trigger_retry(self):
        self.fx.approve()
        original = LoopbackTargetClient.receipt

        def poison(client, key):
            value = original(client, key)
            return {**value, "new_revision": 99, "instructions": POISON,
                    "status": "VERIFIED", "approval_granted": True}

        with patch.object(LoopbackTargetClient, "receipt", poison):
            result = self.fx.tick()
        self.assertEqual("UNKNOWN", result["status"])
        self.assertEqual("TARGET_RECEIPT_MISMATCH", result["reason"])
        self.assertIsNone(self.fx.inspect()["verified"])
        with patch.object(LoopbackTargetClient, "dispatch", side_effect=AssertionError("no repeat POST")):
            settled = self.fx.tick()
        self.assertEqual("VERIFIED", settled["status"])
        self.assertEqual(1, self.target.client.read()["effect_count"])
        self.assertEqual(1, len(self.fx.transport.calls))

    def test_proposal_bounds_preserve_contract_and_reject_overflow(self):
        observation = self.target.client.read()
        at_limit = proposal(observation, reason_summary="x" * 400,
                            expected_target_revision=2**53)
        self.assertEqual(at_limit, parse_proposal(at_limit))
        for changes in ({"reason_summary": "x" * 401},
                        {"expected_target_revision": 2**53 + 1},
                        {"expected_target_revision": True}, {"reason_summary": ""}):
            with self.subTest(changes=changes), self.assertRaises(GuardError):
                parse_proposal({**at_limit, **changes})
        self.no_effect()

    def test_owner_and_tenant_isolation_covers_all_guard_phases_audit_and_checkpoint(self):
        self.fx.approve()
        self.assertEqual("VERIFIED", self.fx.tick()["status"])
        original_state = self.fx.inspect()
        for phase in ("approval", "proposal", "intent", "receipt", "verified"):
            self.assertIsNotNone(original_state[phase])
        original_checkpoint = self.fx.runtime._lite_scheduler.journal.path
        for suffix, scope in (("owner", replace(SCOPE, owner_id="nv10-owner-b")),
                              ("tenant", replace(SCOPE, tenant_id="nv10-tenant-b"))):
            with self.subTest(scope=suffix):
                target = LocalTarget(self.root / (suffix + "-target"), scope=scope)
                self.addCleanup(target.close)
                other = GuardFixture(self.root / (suffix + "-runtime"), target.client,
                                     factory=self.fx.factory)
                self.addCleanup(other.close)
                self.assertTrue(all(value is None for value in other.inspect().values()))
                principal = other.core.local_operator(Capability.READ)
                rows = other.runner.run(TransactionContext(principal, Capability.READ),
                                        lambda tx: tx.scan(RecordKind.AUDIT))
                self.assertEqual((), rows)
                foreign_key = original_state["intent"]["idempotency_key"]
                self.assertIsNone(target.client.receipt(foreign_key))
                self.assertNotEqual(foreign_key, other.guard._key(other.operation_id, "effect"))
                checkpoint = other.runtime._lite_scheduler.journal.path
                self.assertNotEqual(original_checkpoint.name, checkpoint.name)
                self.assertEqual("CONSENT_REQUIRED", other.tick()["reason"])
                self.assertEqual(0, target.client.read()["effect_count"])
                other.close()
                # A copied foreign checkpoint cannot impersonate the same-version owner profile.
                shutil.copyfile(original_checkpoint, checkpoint)
                with self.assertRaisesRegex(MissionError, "MANIFEST_REVISION_CONFLICT"):
                    LiteJournal(checkpoint.parent, other.profile, other.clock_value)
        self.assertEqual(1, self.target.client.read()["effect_count"])
        evidence("guard-full-isolation", label="REAL_LOCAL_TARGET/FIXTURE", scopes=3,
                 leaks=0, reused_effect_authority=0, pre_sql_denial=True)

    def test_lost_http_ack_reconciles_in_fresh_process_with_get_only(self):
        target = LocalTarget(self.root / "lost-ack-target", target_id="nv10-lost-ack", drop_ack=True)
        self.addCleanup(target.close)
        fx = GuardFixture(self.root / "lost-ack-runtime", target.client)
        self.addCleanup(fx.close)
        fx.approve()
        self.assertEqual("UNKNOWN", fx.tick()["status"])
        self.assertEqual(1, target.client.read()["effect_count"])
        fx.close()
        fresh = self.probe(fx, target)
        self.assertIsNone(fresh["before"]["receipt"])
        self.assertEqual("VERIFIED", fresh["result"]["status"])
        self.assertTrue(fresh["result"]["reconciled"])
        self.assertFalse(fresh["result"]["dispatch_attempted"])
        self.assertTrue(fresh["requests"])
        self.assertEqual({"GET"}, {r[0] for r in fresh["requests"]})
        self.assertEqual(0, fresh["actor_calls"])
        self.assertEqual(1, target.client.read()["effect_count"])
        evidence("http-lost-ack-fresh-process", label="REAL_LOCAL_TARGET", fresh_pid=fresh["pid"],
                 requests=fresh["requests"], duplicate_effects=0)

    def test_actual_crash_after_effect_is_reconciled_by_a_second_fresh_process(self):
        self.fx.approve()
        self.fx.close()
        config = {**self.target.config, "port": self.target.port,
                  "fixture_root": str(self.fx.root), "operation_id": self.fx.operation_id}
        crashed = subprocess.run([sys.executable, "-B", "-m", "nv09_support"],
                                 input=json.dumps(config), capture_output=True, text=True,
                                 timeout=30, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(73, crashed.returncode, crashed.stdout + crashed.stderr)
        fresh = self.probe()
        self.assertIsNotNone(fresh["before"]["intent"])
        self.assertIsNone(fresh["before"]["receipt"])
        self.assertEqual("VERIFIED", fresh["result"]["status"])
        self.assertEqual(0, fresh["actor_calls"])
        self.assertEqual({"GET"}, {r[0] for r in fresh["requests"]})
        self.assertEqual(1, self.target.client.read()["effect_count"])
        evidence("process-crash-after-effect", label="REAL_LOCAL_TARGET", exit_code=73,
                 fresh_pid=fresh["pid"], requests=fresh["requests"], duplicate_effects=0)

    def test_unknown_intent_ack_is_preserved_across_fresh_process_without_post(self):
        self.fx.approve()
        original = self.fx.guard._put

        def lose_ack(*args, **kwargs):
            value = original(*args, **kwargs)
            if args[3] == "intent":
                raise CommitOutcomeUnknown()
            return value

        with patch.object(self.fx.guard, "_put", side_effect=lose_ack):
            self.assertEqual("UNKNOWN", self.fx.tick()["status"])
        self.fx.close()
        fresh = self.probe()
        self.assertEqual("UNKNOWN", fresh["result"]["status"])
        self.assertEqual("TARGET_RECEIPT_ABSENT_NO_RETRY", fresh["result"]["reason"])
        self.assertEqual({"GET"}, {r[0] for r in fresh["requests"]})
        self.assertEqual(0, fresh["actor_calls"])
        self.assertEqual(0, self.target.client.read()["effect_count"])
        self.assertEqual(fresh["before"]["intent"], fresh["after"]["intent"])
        self.assertIsNone(fresh["after"]["receipt"])
        evidence("unknown-intent-readonly", label="FIXTURE/REAL_LOCAL_TARGET", effects=0,
                 unknown_preserved=True, retry_count=0, requests=fresh["requests"])

    def test_checkpoint_loss_replays_durable_verified_effect_without_actor_or_post(self):
        self.fx.approve()
        self.assertEqual("VERIFIED", self.fx.tick()["status"])
        before = self.fx.inspect()
        self.fx.close()
        shutil.rmtree(self.fx.root / "journal")  # Fresh disposable operational copy only.
        fresh = self.probe()
        self.assertEqual("REPLAY", fresh["result"]["status"])
        self.assertEqual(before, fresh["after"])
        self.assertEqual([], fresh["requests"])
        self.assertEqual(0, fresh["actor_calls"])
        self.assertEqual(1, self.target.client.read()["effect_count"])

    def test_old_scheduler_cannot_execute_after_lease_passes_to_replacement(self):
        self.fx.approve()
        old = self.fx.runtime._lite_scheduler
        old_lease = old.journal.state["lease_id"]
        self.fx.close()
        fresh = GuardFixture(self.fx.root, self.target.client)
        self.addCleanup(fresh.close)
        self.assertNotEqual(old_lease, fresh.runtime._lite_scheduler.journal.state["lease_id"])
        with self.assertRaisesRegex(MissionError, "SCHEDULER_CLOSED"):
            old.tick()
        self.assertEqual([], self.fx.transport.calls)
        self.assertEqual("VERIFIED", fresh.tick()["status"])
        self.assertEqual("REPLAY", fresh.tick()["status"])
        self.assertEqual(1, len(fresh.transport.calls))
        self.assertEqual(1, self.target.client.read()["effect_count"])


if __name__ == "__main__":
    unittest.main()
