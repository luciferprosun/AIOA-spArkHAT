"""Synthetic same-Core S2 publisher tests; no model or Native qualification."""
import copy
import json
import threading
import time
import unittest
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from nz13_native_foundation_support import fixture_tls, initialize, new_host
from test_nz13_coding_profiles import synthetic_profile

from runtime.core_admission import AdmissionError, Capability, CoreActor
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import (
    CommitOutcomeUnknown,
    ErrorCode,
    MemoryPatchError,
)
from runtime.memory_patch.persistence.ports import (
    LocalCoreTransaction,
    RecordKind,
    StoredRecord,
)
from runtime.meta_hackathon.native_authority import (
    NativeAccessUse,
    NativeAuthorityCapture,
    NativeCoreAccess,
    NativePhase,
)
from runtime.mission import coding_tasks
from runtime.mission.coding_tasks import CoreCodingTasks
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.warrant import WarrantError
from runtime.mission.worker import Task, WorkerError
from runtime.providers import coding_contracts, config, meta_model_api
from runtime.providers.exact import CancellationToken

Choice = getattr(coding_contracts, "CodingBackendChoiceV1", None)
Policy = getattr(coding_contracts, "CodingRunPolicyV1", None)
Binding = getattr(coding_contracts, "CodingBackendBindingV1", None)
Registry = getattr(coding_contracts, "CodingBackendRegistry", None)
decode_row = getattr(coding_tasks, "decode_coding_backend_binding_row", None)
ContractError = coding_contracts.CodingContractError


class Effects:
    def __init__(self):
        self.events = []

    def deny(self, *args, **kwargs):
        self.events.append("FORBIDDEN_EFFECT")
        raise AssertionError("S2_EXTERNAL_EFFECT_DENIED")

    def total(self):
        return len(self.events)


class FailingFactory:
    def __init__(self):
        self.calls = 0

    def __call__(self, task, cancel):
        self.calls += 1
        raise WorkerError("SYNTHETIC_TYPED_FACTORY_FAILURE")


class CodingBackendBindingTests(unittest.TestCase):
    def setUp(self):
        # Causal RED is an assertion before any fixture/new absent API is used.
        self.assertTrue(
            all(value is not None for value in (Choice, Policy, Binding, Registry, decode_row))
            and callable(getattr(CoreCodingTasks, "bind_coding_backend", None))
            and callable(getattr(CoreCodingTasks, "read_coding_backend", None)),
            "S2_CANONICAL_BACKEND_BINDING_INTERFACE_MISSING",
        )
        self.domain()
        self.effects = Effects()
        guards = self.enterContext(ExitStack())
        for module, names in (
            (meta_model_api, ("key_metadata", "load_private_key", "_https_once")),
            (config, ("load_api_environment",)),
            (config.ProviderManager, ("_load_env_key",)),
        ):
            for name in names:
                guards.enter_context(patch.object(module, name, self.effects.deny))

    def domain(self):
        self.owner, self.host_data = new_host(self)
        fixture_tls(self.owner)
        initialize(self.owner)
        self.journal = self.owner.intent_journal
        self.assertIs(self.journal, self.owner.foundation.intent_journal)
        self.owner_manage = self.owner.core.local_operator(Capability.MANAGE)
        self.owner_read = self.owner.core.local_operator(Capability.READ)
        self.owner_commit = self.owner.core.local_operator(Capability.COMMIT)
        self.capsules = CorePatchCapsules(
            self.journal, self.owner.identity,
            source_probe=lambda: self.owner.foundation.spec.project_source,
        )
        self.profiles = tuple(synthetic_profile(name) for name in ("CODEX", "META_MUSE", "OPENROUTER"))
        self.registry = Registry(self.profiles)
        self.factory = FailingFactory()
        self.tasks = self.controller()
        self.task = self.create_task("task-one")

    def controller(self, *, registry=True, journal=None, capsules=None, access=None):
        options = {}
        if registry:
            options = {"coding_backend_registry": self.registry,
                       "coding_access": access or self.owner.foundation.access}
        value = CoreCodingTasks(
            journal or self.journal, capsules or self.capsules,
            run_factory=self.factory, run_principal=self.owner_commit, **options,
        )
        self.addCleanup(value.close)
        return value

    def create_task(self, name):
        source = self.owner.foundation.spec.project_source
        task = Task(name, "run-" + name, source.workspace_id, source.repository_id,
                    source.source_base_sha, "Return one deterministic owned change.",
                    int(time.time()) + 240)
        self.tasks.request(self.owner_manage, "create_task", {"task": task.to_dict()})
        return task

    @staticmethod
    def choice(profile):
        body = profile.to_dict()
        return Choice({
            "schema": "aioa.coding-backend-choice.v1",
            "selection_id": body["selection_id"],
            "selection_revision": body["selection_revision"],
            "backend": body["backend"], "model_id": body["model_id"],
            "selection_digest": profile.selection_digest,
        })

    def policy(self, profile=None, task=None, **changes):
        profile, task = profile or self.profiles[0], task or self.task
        now = int(time.time())
        body = {
            "schema": "aioa.coding-run-policy.v1", "task_digest": task.digest,
            "selection_digest": profile.selection_digest, "max_model_calls": 1,
            "max_repairs": 0, "max_total_input_units": 4096,
            "max_total_output_tokens": 512, "max_total_cost_nano_usd": 100,
            "model_risk_units": 1, "issued_at": now - 1, "expires_at": now + 120,
        }
        body.update(changes)
        return Policy(body)

    def bind(self, profile=None, policy=None, task=None, principal=None):
        profile, task = profile or self.profiles[0], task or self.task
        return self.tasks.bind_coding_backend(
            principal or self.owner_manage, task.task_id, self.choice(profile),
            policy or self.policy(profile, task),
        )

    def row(self, task=None):
        task = task or self.task
        return self.journal._run(self.owner_read, Capability.READ, lambda tx: tx.get(
            RecordKind.OPERATION, "coding-backend-" + task.digest))

    def rows(self):
        return self.journal._run(self.owner_read, Capability.READ, lambda tx: tuple(
            row for row in tx.scan(RecordKind.OPERATION, limit=1024)
            if row.record_id.startswith("coding-backend-")))

    def task_state(self, task=None):
        return self.tasks.request(self.owner_read, "read_status",
                                  {"task_id": (task or self.task).task_id})["state"]

    def test_all_three_bind_actual_queued_task_and_preserve_full_snapshot(self):
        for number, profile in enumerate(self.profiles):
            task = self.task if number == 0 else self.create_task("task-" + str(number))
            bound = self.bind(profile, task=task)
            self.assertEqual(bound.to_dict()["selection"], profile.to_dict())
            self.assertEqual(bound.to_dict()["selection_digest"], canonical_sha256(profile.to_dict()))
            self.assertEqual(bound.to_dict()["selected_by_session_digest"],
                             canonical_sha256(self.owner_manage.actor_session_id))
            self.assertEqual(self.tasks.read_coding_backend(self.owner_read, task.task_id), bound)
            self.assertEqual(self.task_state(task), "QUEUED")
            self.assertEqual(self.effects.total(), 0)
        self.assertEqual(len(self.rows()), 3)
        self.assertEqual(self.owner.foundation.access._originals, {})

    def test_exact_idempotence_preserves_record_revision_time_and_digest(self):
        policy = self.policy()
        first = self.bind(policy=policy)
        before = self.row()
        second = self.bind(policy=policy)
        after = self.row()
        self.assertEqual(first, second)
        self.assertEqual(first.to_dict()["selected_at"], second.to_dict()["selected_at"])
        self.assertEqual(before.payload_digest, after.payload_digest)
        self.assertEqual(after.revision, 1)
        self.assertEqual(len(self.rows()), 1)

    def test_conflicting_choice_policy_and_session_cannot_overwrite(self):
        policy = self.policy()
        first = self.bind(policy=policy)
        for profile, supplied in ((self.profiles[1], self.policy(self.profiles[1])),
                                  (self.profiles[0], self.policy(max_total_cost_nano_usd=101))):
            with self.subTest(backend=profile.to_dict()["backend"]), self.assertRaises(WarrantError):
                self.bind(profile, supplied)
        altered = replace(self.owner_manage, actor_session_id="f" * 64)
        with self.assertRaises(AdmissionError):
            self.bind(policy=policy, principal=altered)
        self.assertEqual(self.tasks.read_coding_backend(self.owner_read, self.task.task_id), first)
        self.assertEqual(self.row().revision, 1)

    def test_registry_missing_duplicate_and_identity_mutations_deny(self):
        profile = self.profiles[0]
        for values in ((), (profile, profile), self.profiles * 6, list(self.profiles), ({},)):
            with self.subTest(entries=len(values)), self.assertRaises(ContractError):
                Registry(values)
        for name, value in (("selection_id", "f" * 32), ("selection_revision", 2),
                            ("selection_digest", "f" * 64), ("backend", "META_MUSE"),
                            ("model_id", "synthetic/other")):
            body = self.choice(profile).to_dict()
            body[name] = value
            with self.subTest(field=name), self.assertRaises(ContractError):
                self.registry.resolve(Choice(body))
        unique = []
        for number in range(17):
            body = profile.to_dict()
            body["selection_id"] = format(number, "032x")
            unique.append(coding_contracts.SelectedCodingProfileV2(body))
        with self.assertRaises(ContractError):
            Registry(tuple(unique))
        finite = Registry(tuple(unique[:16]))
        self.assertEqual(finite.resolve(self.choice(unique[15])), unique[15])
        resolved = self.registry.resolve(self.choice(profile))
        self.assertIsNot(resolved, profile)
        changed = resolved.to_dict()
        changed["protocol_options"]["binary_sha256"] = "f" * 64
        self.assertEqual(self.registry.resolve(self.choice(profile)).to_dict(), profile.to_dict())
        # Captured canonical bytes survive mutation even of an original DTO's internals.
        object.__setattr__(profile, "_wire", canonical_json_bytes(changed))
        self.assertNotEqual(profile.to_dict(), self.registry.resolve(self.choice(resolved)).to_dict())

    def test_binding_and_start_conflicts_cannot_reach_legacy_factory(self):
        with self.assertRaisesRegex(WarrantError, "^CODING_BACKEND_BINDING_REQUIRED$"):
            self.tasks.request(self.owner_manage, "start", {"task_id": self.task.task_id})
        self.bind()
        with self.assertRaisesRegex(WarrantError, "^CODING_MODEL_WORKER_NOT_READY$"):
            self.tasks.request(self.owner_manage, "start", {"task_id": self.task.task_id})
        self.assertEqual(self.task_state(), "QUEUED")
        self.assertEqual(self.factory.calls, 0)
        self.assertEqual(self.effects.total(), 0)

    def test_concurrent_conflicting_choices_have_one_record_and_no_execution(self):
        gate = threading.Barrier(2)
        successes, errors = [], []
        def choose(profile):
            try:
                gate.wait(10)
                successes.append(self.bind(profile))
            except (ValueError, RuntimeError, AssertionError, TypeError) as error:
                errors.append(error)
        workers = [threading.Thread(target=choose, args=(profile,)) for profile in self.profiles[:2]]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(15)
            self.assertFalse(worker.is_alive())
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], WarrantError)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.factory.calls, 0)
        self.assertEqual(self.task_state(), "QUEUED")

    def test_unknown_commit_is_not_replayed_or_treated_as_no_binding(self):
        original = LocalCoreTransaction.commit
        commits = []
        key = "coding-backend-" + self.task.digest
        def lose_ack(transaction):
            present = transaction.get(RecordKind.OPERATION, key)
            original(transaction)
            if present is not None:
                commits.append(present)
                raise CommitOutcomeUnknown()
        with patch.object(LocalCoreTransaction, "commit", lose_ack), self.assertRaises(CommitOutcomeUnknown):
            self.bind()
        self.assertEqual(len(commits), 1)
        retained = self.tasks.read_coding_backend(self.owner_read, self.task.task_id)
        self.assertEqual(retained.to_dict(), json.loads(canonical_json_bytes(commits[0].payload)))
        self.assertEqual(self.row().payload_digest, commits[0].payload_digest)
        self.assertEqual(self.row().record_id, key)
        self.assertEqual(self.row().revision, 1)
        self.assertEqual(self.factory.calls, 0)

    def test_choice_policy_binding_strict_types_hashes_and_detached_mutations(self):
        bound = self.bind()
        for codec, valid, integer, maximum in (
            (Choice, self.choice(self.profiles[0]).to_dict(), "selection_revision", 4096),
            (Policy, self.policy().to_dict(), "max_model_calls", 4096),
            (Binding, bound.to_dict(), "selected_at", 24576),
        ):
            instance = codec.from_dict(valid)
            digest = instance.digest
            exported = instance.to_dict()
            exported["schema"] = "changed"
            self.assertEqual(instance.digest, digest)
            self.assertEqual(instance.to_dict(), valid)
            self.assertEqual(digest, canonical_sha256(valid))
            self.assertEqual(codec.from_json(canonical_json_bytes(valid)), instance)
            for changed in ({**valid, "extra": None}, {**valid, integer: True},
                            {**valid, integer: 1.0}, {**valid, integer: None},
                            {**valid, integer: {"nested": {"too": {"deep": {"data": 1}}}}},
                            {**valid, "schema": "\ud800"}):
                with self.subTest(codec=codec.__name__, invalid=integer), self.assertRaises(ContractError):
                    codec(changed)
            wire = canonical_json_bytes(valid)
            for raw in (wire[:-1] + b',"schema":"duplicate"}', b"\xff", b" " * (maximum + 1),
                        wire.replace(b'"schema":', b'"unknown":', 1),
                        b'{"value":NaN}', b'{"value":Infinity}', b'{"value":1.5}',
                        b'[' * 1000 + b'0' + b']' * 1000, bytearray(wire)):
                with self.subTest(codec=codec.__name__), self.assertRaises(ContractError):
                    codec.from_json(raw)
        for field, value in (
            ("max_model_calls", 0), ("max_model_calls", 4), ("max_repairs", 1),
            ("max_total_input_units", 16897), ("max_total_output_tokens", 4097),
            ("max_total_cost_nano_usd", 0), ("model_risk_units", 2**63),
            ("expires_at", 2**53 + 1),
        ):
            with self.subTest(field=field), self.assertRaises(ContractError):
                self.policy(**{field: value})
        now = int(time.time())
        for changes in ({"issued_at": now, "expires_at": now},
                        {"issued_at": now, "expires_at": now + 301}):
            with self.assertRaises(ContractError):
                self.policy(**changes)
        for field in ("selection_digest", "run_policy_digest", "task_digest"):
            body = bound.to_dict()
            body[field] = "f" * 64
            with self.subTest(join=field), self.assertRaises(ContractError):
                Binding(body)
        body = bound.to_dict()
        body["selected_at"] = body["run_policy"]["expires_at"]
        with self.assertRaises(ContractError):
            Binding(body)

    def test_foreign_core_non_owner_wrong_purpose_and_copied_capture_denied_before_insert(self):
        foreign, _ = new_host(self)
        fixture_tls(foreign)
        for principal in (foreign.core.local_operator(Capability.MANAGE), self.owner_read,
                          self.owner.core._issue(Capability.MANAGE, CoreActor.HUMAN_REVIEWER)):
            with self.subTest(actor=principal.actor), self.assertRaises((AdmissionError, WarrantError)):
                self.bind(principal=principal)
        access = self.owner.foundation.access
        original = access.capture(Capability.MANAGE, use=NativeAccessUse.CONTROL)
        self.addCleanup(original.close)
        copied = object.__new__(NativeAuthorityCapture)
        for cls in (NativeAuthorityCapture, NativeAuthorityCapture.__base__):
            for name in cls.__slots__:
                object.__setattr__(copied, name, getattr(original, name))
        wrong = access.capture(Capability.READ, use=NativeAccessUse.READ)
        self.addCleanup(wrong.close)
        for captured in (copied, wrong):
            with patch.object(NativeCoreAccess, "capture", return_value=captured), self.assertRaises(AdmissionError):
                self.bind()
        self.assertEqual(len(self.rows()), 0)
        self.assertEqual(self.factory.calls, 0)
        self.assertEqual(self.effects.total(), 0)

    def test_source_auth_tls_generation_and_time_drift_denies_before_insert(self):
        original = NativeCoreAccess.capture
        drifts = (
            ("source", lambda owner: setattr(owner, "source", ("f" * 40, "e" * 64))),
            ("auth", lambda owner: setattr(owner, "_auth_deadline", time.monotonic() - 1)),
            ("tls", lambda owner: setattr(owner, "_tls_expires", time.time() - 1)),
            ("tls_flag", lambda owner: setattr(owner, "tls_verified", False)),
            ("generation", lambda owner: setattr(owner.foundation.lifecycle, "admission_generation", 999)),
            ("composition", lambda owner: setattr(owner.foundation.lifecycle, "composition_generation", 999)),
            ("phase", lambda owner: setattr(owner.foundation.lifecycle, "_phase", NativePhase.ACTIVE)),
        )
        for number, (label, drift) in enumerate(drifts):
            if number:
                self.domain()
            def capture_then_drift(access, purpose, *, use, _drift=drift):
                value = original(access, purpose, use=use)
                _drift(self.owner)
                return value
            with (self.subTest(drift=label),
                  patch.object(NativeCoreAccess, "capture", capture_then_drift),
                  self.assertRaises((AdmissionError, WarrantError))):
                self.bind()
            self.assertEqual(len(self.rows()), 0)
            self.assertEqual(self.task_state(), "QUEUED")
            self.assertEqual(self.owner.foundation.access._originals, {})
        self.assertEqual(self.effects.total(), 0)

    def test_project_commit_is_distinct_from_host_commit_and_binding_succeeds(self):
        self.assertNotEqual(self.task.source_base_sha, self.owner.source[0])
        bound = self.bind()
        self.assertEqual(bound.to_dict()["task_digest"], self.task.digest)
        self.assertEqual(bound.to_dict()["selection"]["host_source"]["source_sha"], self.owner.source[0])

    def test_reconstructed_controller_keeps_binding_and_denies_selected_legacy_start(self):
        first = self.bind()
        self.tasks.close()
        changed_registry = Registry((self.profiles[1],))
        for configured in (False, True):
            with patch.object(self, "registry", changed_registry):
                self.tasks = self.controller(registry=configured)
            with patch.object(NativeCoreAccess, "capture", self.effects.deny):
                self.assertEqual(self.tasks.read_coding_backend(self.owner_read, self.task.task_id), first)
            with self.assertRaisesRegex(WarrantError, "^CODING_MODEL_WORKER_NOT_READY$"):
                self.tasks.request(self.owner_manage, "start", {"task_id": self.task.task_id})
        self.assertEqual(self.factory.calls, 0)
        self.assertEqual(self.task_state(), "QUEUED")
        self.assertEqual(self.effects.total(), 0)

    def test_bound_execute_entry_cannot_bypass_start_refusal(self):
        self.bind()
        active = {"cancel": CancellationToken(), "producer": None, "thread": threading.current_thread()}
        self.tasks._execute(self.task.task_id, active)
        self.assertEqual(self.factory.calls, 0)
        self.assertEqual(self.task_state(), "QUEUED")
        self.assertEqual(self.effects.total(), 0)

    def test_mutated_missing_mixed_row_and_policy_joins_deny_pure_read(self):
        self.bind()
        row = self.row()
        payload = json.loads(canonical_json_bytes(row.payload))
        invalid = [None, replace(row, kind=RecordKind.RECEIPT), replace(row, record_id="wrong"),
                   replace(row, revision=2),
                   replace(row, scope=replace(self.owner_manage.scope, owner_id="another-owner"))]
        for name in ("selection", "run_policy", "selected_by_session_digest"):
            body = copy.deepcopy(payload)
            body.pop(name)
            invalid.append(StoredRecord(RecordKind.OPERATION, row.record_id, row.scope, 1, body))
        body = copy.deepcopy(payload)
        body["run_policy"]["task_digest"] = "f" * 64
        body["run_policy_digest"] = canonical_sha256(body["run_policy"])
        invalid.append(StoredRecord(RecordKind.OPERATION, row.record_id, row.scope, 1, body))
        corrupted = replace(row)
        object.__setattr__(corrupted, "payload_digest", "f" * 64)
        invalid.append(corrupted)
        with patch.object(self.owner.runner, "run", self.effects.deny), patch("builtins.open", self.effects.deny):
            for bad in invalid:
                with self.subTest(row_type=type(bad).__name__), self.assertRaises(WarrantError):
                    decode_row(bad, self.task, self.owner_manage.scope)
        self.assertEqual(self.effects.total(), 0)
        self.assertEqual(self.task_state(), "QUEUED")

    def test_legacy_none_unbound_still_uses_existing_controller_path(self):
        self.tasks.close()
        self.tasks = self.controller(registry=False)
        self.assertIsNone(self.tasks.read_coding_backend(self.owner_read, self.task.task_id))
        self.tasks.request(self.owner_manage, "start", {"task_id": self.task.task_id})
        self.assertTrue(self.tasks.wait(self.task.task_id, 5))
        self.assertEqual(self.factory.calls, 1)
        # Controller ruling: actual legacy typed factory failures are UNKNOWN.
        self.assertEqual(self.task_state(), "UNKNOWN")
        receipts = self.tasks.request(self.owner_read, "get_receipts", {"task_id": self.task.task_id})["receipts"]
        self.assertEqual([row["receipt"]["state"] for row in receipts], ["QUEUED", "RUNNING", "UNKNOWN"])
        retained = self.tasks.request(self.owner_manage, "start", {"task_id": self.task.task_id})
        self.assertEqual(retained["state"], "UNKNOWN")
        self.assertEqual(self.factory.calls, 1)
        self.assertEqual(self.effects.total(), 0)

    def test_legacy_task_fixed_vector_and_none_hash_unchanged(self):
        wire = (b'{"deadline_at":1700000300,"instruction":"Owned fixed task.","max_events":64,'
                b'"repository_id":"fixture-repo","run_id":"fixed-run","source_base_sha":'
                b'"cccccccccccccccccccccccccccccccccccccccc","task_id":"fixed-task",'
                b'"workspace_id":"fixture-workspace"}')
        task = Task(**json.loads(wire))
        self.assertEqual(canonical_json_bytes(task.to_dict()), wire)
        self.assertEqual(task.digest, "f2150da8e0978ef5f4ecdce9c2ee147589bf7a2e036e870606b68a579810de6b")
        self.assertEqual(canonical_sha256(None), "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b")
        self.assertNotIn("max_output_tokens", task.to_dict())

    def test_pairing_original_journal_signer_and_host_source_are_required(self):
        for options in ({"coding_backend_registry": self.registry},
                        {"coding_access": self.owner.foundation.access},
                        {"coding_backend_registry": (), "coding_access": self.owner.foundation.access}):
            with self.subTest(fields=tuple(options)), self.assertRaises(WarrantError):
                CoreCodingTasks(self.journal, self.capsules, **options)
        other = CoreIntentJournal(self.journal.ledger, self.journal.governor)
        other_capsules = CorePatchCapsules(other, self.owner.identity,
                                           source_probe=lambda: self.owner.foundation.spec.project_source)
        with self.assertRaises(WarrantError):
            self.controller(journal=other, capsules=other_capsules)
        body = self.profiles[0].to_dict()
        body["host_source"]["source_sha"] = "f" * 40
        with (patch.object(self, "registry", Registry((coding_contracts.SelectedCodingProfileV2(body),))),
              self.assertRaises(WarrantError)):
            self.controller()
        foreign, _ = new_host(self)
        with self.assertRaises(WarrantError):
            self.controller(access=foreign.foundation.access)
        wrong_signer = CorePatchCapsules(self.journal, foreign.identity,
                                         source_probe=lambda: self.owner.foundation.spec.project_source)
        with self.assertRaises(WarrantError):
            self.controller(capsules=wrong_signer)
        self.assertEqual(len(self.rows()), 0)

    def test_freshness_limits_and_quota_fail_without_binding_or_execution(self):
        now = int(time.time())
        for changes in (
            {"issued_at": now - 20, "expires_at": now - 1},
            {"issued_at": now + 20, "expires_at": now + 30},
            {"issued_at": now, "expires_at": self.task.deadline_at + 1},
        ):
            with self.subTest(changes=tuple(changes)), self.assertRaises(WarrantError):
                self.bind(policy=self.policy(**changes))
        for name, value in (("_auth_deadline", time.monotonic() + 30),
                            ("_tls_expires", time.time() + 30)):
            with patch.object(self.owner, name, value), self.assertRaises(WarrantError):
                self.bind()
        # The same existing issuer supplies a genuine, shorter-lived caller.
        with patch.object(self.owner.core, "_clock",
                          return_value=datetime.now(UTC) - timedelta(seconds=240)):
            short_caller = self.owner.core.local_operator(Capability.MANAGE)
        with self.assertRaises(WarrantError):
            self.bind(principal=short_caller)
        original = LocalCoreTransaction.insert
        def quota(transaction, record):
            if record.record_id.startswith("coding-backend-"):
                raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
            return original(transaction, record)
        with patch.object(LocalCoreTransaction, "insert", quota), self.assertRaises(MemoryPatchError):
            self.bind()
        self.assertEqual(len(self.rows()), 0)
        self.assertEqual(self.task_state(), "QUEUED")
        self.assertEqual(self.factory.calls, 0)

    def test_concurrent_bind_start_race_never_admits_configured_legacy_run(self):
        gate = threading.Barrier(2)
        outcomes, failures = [], []
        def bind():
            try:
                gate.wait(10)
                outcomes.append(self.bind())
            except (ValueError, RuntimeError, AssertionError, TypeError) as error:
                failures.append(error)
        def start():
            try:
                gate.wait(10)
                self.tasks.request(self.owner_manage, "start", {"task_id": self.task.task_id})
            except WarrantError:
                outcomes.append("START_DENIED")
            except (ValueError, RuntimeError, AssertionError, TypeError) as error:
                failures.append(error)
        workers = [threading.Thread(target=operation) for operation in (bind, start)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(15)
            self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(outcomes), 2)
        self.assertIn("START_DENIED", outcomes)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.task_state(), "QUEUED")
        self.assertEqual(self.factory.calls, 0)
