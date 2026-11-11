"""Owned Native model eligibility and real publisher; no model certification."""
import copy
import hashlib
import json
import os
import time
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch

from nz13_native_foundation_support import config_data, fixture_tls, initialize
from test_nz13_coding_profiles import synthetic_profile_wire

from runtime.core_admission import AdmissionError, Capability, CoreAdmission
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.meta_hackathon import runtime_adapter
from runtime.meta_hackathon.native_authority import (
    NativeAccessUse,
    NativeHostCompositionConfig,
)
from runtime.mission.coding_tasks import CoreCodingTasks
from runtime.mission.execution_capacity import CapacityError
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.worker import Task
from runtime.providers import config, meta_model_api
from runtime.providers.coding_contracts import (
    CodingBackendChoiceV1,
    CodingBackendRegistry,
    CodingRunPolicyV1,
    SelectedCodingProfileV2,
)

OWNED_ROOTS = []
OFFLINE = "aioa/offline-host-worker-v1"
CODING_IDS = frozenset(("gpt-6.1-sol", "muse-spark-1.3", "synthetic-owner/synthetic-model"))


def host_bytes(body):
    # Independent host-wire serializer: paths remain real parts of the digest.
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


class NativeCodingAdmissionTests(unittest.TestCase):
    def setUp(self):
        # Missing feature must fail causally before any new fixture/API is used.
        self.assertTrue(
            "coding_backend_registry" in NativeHostCompositionConfig.__dataclass_fields__
            and callable(getattr(NativeHostCompositionConfig, "coding_model_ids", None)),
            "NATIVE_CODING_ADMISSION_INTERFACE_MISSING",
        )
        self.effects = []
        self.metadata = []
        self.constructed = []
        self.provider_constructions = []
        self.roots = []
        real_metadata = meta_model_api.key_metadata
        real_provider_init = meta_model_api.MetaModelProvider.__init__
        real_manager_init = config.ProviderManager.__init__

        def denied(*args, **kwargs):
            self.effects.append("FORBIDDEN_EFFECT")
            raise AssertionError("NATIVE_CODING_EXTERNAL_EFFECT_DENIED")

        def owned_metadata(path):
            path = Path(path)
            self.assertTrue(any(path.is_relative_to(root) for root in self.roots),
                            "DEFAULT_OR_FOREIGN_KEY_METADATA_DENIED_BEFORE_OS")
            self.metadata.append(str(path))
            return real_metadata(path)

        def provider_init(value, *args, **kwargs):
            self.provider_constructions.append("META")
            if "key_path" in kwargs:
                path = Path(kwargs["key_path"])
                self.assertTrue(any(path.is_relative_to(root) for root in self.roots))
            else:
                # The existing manager creates an inert DISABLED provider first.
                # All default-path metadata/open stays denied before the OS.
                self.assertEqual(kwargs.get("mode", "DISABLED"), "DISABLED")
            return real_provider_init(value, *args, **kwargs)

        def manager_init(value, *args, **kwargs):
            self.provider_constructions.append("MANAGER")
            return real_manager_init(value, *args, **kwargs)

        def core_constructor(assignment, **kwargs):
            value = CoreAdmission(assignment, **kwargs)
            self.constructed.append((value, assignment))
            return value

        self.core_constructor = self.enterContext(
            patch.object(runtime_adapter, "CoreAdmission", side_effect=core_constructor))
        self.enterContext(patch.object(meta_model_api, "key_metadata", side_effect=owned_metadata))
        self.enterContext(patch.object(meta_model_api.MetaModelProvider, "__init__", provider_init))
        self.enterContext(patch.object(config.ProviderManager, "__init__", manager_init))
        for target, names in (
            (meta_model_api, ("load_private_key", "_https_once")),
            (config, ("load_api_environment",)),
            (config.ProviderManager, ("_load_env_key", "_build_provider", "_fallback_candidates")),
        ):
            for name in names:
                self.enterContext(patch.object(target, name, side_effect=denied))
        self.addCleanup(lambda: self.assertEqual(self.effects, []))

    def root(self):
        root = Path(mkdtemp(prefix="bes2n-owned-"))
        self.roots.append(root)
        OWNED_ROOTS.append(str(root))
        return root

    def data(self, *, v2=True):
        root = self.root()
        body = config_data(root)
        if v2:
            body["schema"] = "aioa.native-host-composition.v2"
            body["coding_profiles"] = [synthetic_profile_wire(name)
                                       for name in ("CODEX", "META_MUSE", "OPENROUTER")]
        return root, body

    def owner(self, root, spec=None, *, chat=False, source=None):
        source = source if source is not None else ["a" * 40, "b" * 64]
        key_path = root / "synthetic-owned-meta-key"
        if chat:
            key_path.write_bytes(b"SYNTHETIC_TEST_ONLY_NEVER_LOAD")
            key_path.chmod(0o600)
        authentication = {"uid": os.getuid(), "method": "SYNTHETIC_TEST_ONLY"}
        with patch.object(runtime_adapter, "_desktop_operator_uid",
                          return_value=(os.getuid(), authentication)):
            owner = runtime_adapter.NativeMobileComposition(
                root / "native", origin="https://fixture.example.org",
                source_probe=lambda: tuple(source), chat=chat, key_path=key_path,
                host_composition=spec)
        self.addCleanup(owner.close)
        return owner

    def host(self, *, v2=True, descriptor=False):
        root, body = self.data(v2=v2)
        if descriptor:
            path = root / "composition.json"
            path.write_bytes(host_bytes(body))
            path.chmod(0o600)
            spec = NativeHostCompositionConfig.load(path)
        else:
            spec = NativeHostCompositionConfig.from_dict(body)
        owner = self.owner(root, spec)
        fixture_tls(owner)
        initialize(owner)
        return owner, spec, body

    @staticmethod
    def choice(profile):
        body = profile.to_dict()
        return CodingBackendChoiceV1({
            "schema": "aioa.coding-backend-choice.v1", "selection_id": body["selection_id"],
            "selection_revision": body["selection_revision"], "backend": body["backend"],
            "model_id": body["model_id"], "selection_digest": profile.selection_digest,
        })

    def publisher(self, owner):
        capsules = CorePatchCapsules(owner.intent_journal, owner.identity,
                                    source_probe=lambda: owner.foundation.spec.project_source)
        tasks = CoreCodingTasks(owner.intent_journal, capsules,
                                coding_backend_registry=owner.foundation.coding_backend_registry,
                                coding_access=owner.foundation.access)
        self.addCleanup(tasks.close)
        return tasks

    def task(self, owner, tasks, name):
        source = owner.foundation.spec.project_source
        task = Task(name, "run-" + name, source.workspace_id, source.repository_id,
                    source.source_base_sha, "One synthetic owned task.", int(time.time()) + 240)
        tasks.request(owner.core.local_operator(Capability.MANAGE), "create_task",
                      {"task": task.to_dict()})
        return task

    @staticmethod
    def policy(profile, task):
        now = int(time.time())
        return CodingRunPolicyV1({
            "schema": "aioa.coding-run-policy.v1", "task_digest": task.digest,
            "selection_digest": profile.selection_digest, "max_model_calls": 1,
            "max_repairs": 0, "max_total_input_units": 4096, "max_total_output_tokens": 512,
            "max_total_cost_nano_usd": 100, "model_risk_units": 1,
            "issued_at": now - 1, "expires_at": now + 120,
        })

    @staticmethod
    def rows(owner):
        read = owner.core.local_operator(Capability.READ)
        return owner.intent_journal._run(
            read, Capability.READ, lambda tx: tuple(
                (kind.value, row.record_id, row.payload_digest)
                for kind in RecordKind for row in tx.scan(kind, limit=1024)))

    def test_v1_retains_fixed_body_digest_default_models_and_none_registry(self):
        root, body = self.data(v2=False)
        original = copy.deepcopy(body)
        expected_bytes = host_bytes(original)
        spec = NativeHostCompositionConfig.from_dict(body)
        owner = self.owner(root, spec)
        self.assertEqual(spec.to_dict(), original)
        self.assertEqual(spec._bytes, expected_bytes)
        self.assertEqual(spec.digest, hashlib.sha256(expected_bytes).hexdigest())
        self.assertIsNone(spec.coding_backend_registry)
        self.assertEqual(spec.coding_model_ids(), frozenset())
        self.assertIsNone(owner.foundation.coding_backend_registry)
        self.assertEqual(owner.core._assignment.model_binding_ids,
                         frozenset(("NO_MODEL_PAIRING", OFFLINE)))
        self.assertEqual(self.provider_constructions, [])
        self.assertEqual(self.metadata, [])

    def test_v2_all_three_models_admitted_at_the_single_original_core(self):
        owner, spec, _ = self.host()
        self.assertEqual(self.core_constructor.call_count, 1)
        self.assertIs(type(owner.core), CoreAdmission)
        self.assertIs(self.constructed[0][0], owner.core)
        self.assertIs(owner.core._assignment, self.constructed[0][1])
        self.assertEqual(owner.core._assignment.model_binding_ids, CODING_IDS | {OFFLINE})
        self.assertNotIn("NO_MODEL_PAIRING", owner.core._assignment.model_binding_ids)
        self.assertIs(owner.foundation.coding_backend_registry, spec.coding_backend_registry)
        self.assertIs(owner.foundation.intent_journal, owner.intent_journal)
        self.assertIs(owner.foundation.runner, owner.runner)
        self.assertIs(owner.foundation.core, owner.core)
        self.assertEqual(self.provider_constructions, [])
        self.assertEqual(self.metadata, [])

    def test_actual_publisher_binds_each_admitted_choice_without_execution_or_spend(self):
        owner, spec, body = self.host()
        tasks = self.publisher(owner)
        self.assertIs(tasks.journal, owner.intent_journal)
        self.assertIs(tasks.coding_backend_registry, spec.coding_backend_registry)
        self.assertIs(tasks.coding_access, owner.foundation.access)
        for number, wire in enumerate(body["coding_profiles"]):
            profile = SelectedCodingProfileV2.from_dict(wire)
            self.assertIn(wire["model_id"], owner.core._assignment.model_binding_ids)
            task = self.task(owner, tasks, "native-choice-" + str(number))
            manage = owner.core.local_operator(Capability.MANAGE)
            bound = tasks.bind_coding_backend(manage, task.task_id, self.choice(profile),
                                              self.policy(profile, task))
            self.assertEqual(bound.to_dict()["selection"], wire)
            read = owner.core.local_operator(Capability.READ)
            self.assertEqual(tasks.read_coding_backend(read, task.task_id), bound)
            self.assertEqual(tasks.request(read, "read_status", {"task_id": task.task_id})["state"],
                             "QUEUED")
        self.assertEqual(tasks._active, {})
        self.assertIsNone(tasks.run_factory)
        self.assertEqual(self.provider_constructions, [])
        self.assertEqual(self.metadata, [])

    def test_registry_unknown_duplicate_mixed_source_and_bounds_deny_before_core(self):
        _, body = self.data()
        invalid = []
        for value in ([], None, {}, True, body["coding_profiles"] * 6):
            changed = copy.deepcopy(body)
            changed["coding_profiles"] = value
            invalid.append(changed)
        for mutate in (
            lambda b: b["coding_profiles"].append(copy.deepcopy(b["coding_profiles"][0])),
            lambda b: b["coding_profiles"][0].update({"unknown": "denied"}),
            lambda b: b["coding_profiles"][0].update({"schema": "unknown"}),
            lambda b: b["coding_profiles"][1]["host_source"].update({"source_sha": "f" * 40}),
            lambda b: b["coding_profiles"][2].update({"model_id": "x" * 17000}),
        ):
            changed = copy.deepcopy(body)
            mutate(changed)
            invalid.append(changed)
        for changed in invalid:
            with self.subTest(profiles=type(changed["coding_profiles"]).__name__), self.assertRaises(AdmissionError):
                NativeHostCompositionConfig.from_dict(changed)
        self.assertEqual(self.core_constructor.call_count, 0)
        self.assertEqual(self.provider_constructions, [])
        self.assertEqual(self.metadata, [])

    def test_none_and_chat_legacy_model_sets_unchanged(self):
        plain = self.owner(self.root())
        self.assertEqual(plain.core._assignment.model_binding_ids, frozenset(("NO_MODEL_PAIRING",)))
        self.assertIsNone(plain.foundation)
        chat = self.owner(self.root(), chat=True)
        self.assertEqual(chat.core._assignment.model_binding_ids, frozenset(("muse-spark-1.3",)))
        self.assertIsNone(chat.foundation)
        self.assertEqual(chat.manager._meta_provider.key_path, Path(self.metadata[0]))
        self.assertEqual(self.provider_constructions, ["MANAGER", "META", "META"])
        self.assertEqual(len(self.metadata), 1)

    def test_v1_and_v2_chat_host_combinations_deny_before_core_provider_or_key(self):
        for v2 in (False, True):
            root, body = self.data(v2=v2)
            spec = NativeHostCompositionConfig.from_dict(body)
            with self.assertRaises(AdmissionError):
                self.owner(root, spec, chat=True)
        self.assertEqual(self.core_constructor.call_count, 0)
        self.assertEqual(self.provider_constructions, [])
        self.assertEqual(self.metadata, [])

    def test_full_v2_snapshot_and_canonical_digest_include_every_profile_option(self):
        _, body = self.data()
        original = copy.deepcopy(body)
        spec = NativeHostCompositionConfig.from_dict(body)
        expected = host_bytes(original)
        self.assertEqual(spec._bytes, expected)
        self.assertEqual(spec.digest, hashlib.sha256(expected).hexdigest())
        registry = spec.coding_backend_registry
        expected_profiles = [SelectedCodingProfileV2.from_dict(w) for w in original["coding_profiles"]]
        for wire in body["coding_profiles"]:
            wire["protocol_options"].clear()
            wire["host_source"]["source_sha"] = "f" * 40
        exported = spec.to_dict()
        exported["coding_profiles"][2]["protocol_options"]["reasoning_effort"] = "high"
        exported["coding_profiles"].reverse()
        self.assertEqual(spec.to_dict(), original)
        self.assertEqual(spec.coding_model_ids(), CODING_IDS)
        self.assertIs(spec.coding_backend_registry, registry)
        for profile, wire in zip(expected_profiles, original["coding_profiles"], strict=True):
            self.assertEqual(registry.resolve(self.choice(profile)).to_dict(), wire)
        changed = copy.deepcopy(original)
        changed["coding_profiles"][2]["protocol_options"]["reasoning_effort"] = "high"
        other = NativeHostCompositionConfig.from_dict(changed)
        self.assertNotEqual(other.digest, spec.digest)
        self.assertNotEqual(other.coding_backend_registry.resolve(
            self.choice(SelectedCodingProfileV2.from_dict(changed["coding_profiles"][2]))).selection_digest,
            expected_profiles[2].selection_digest)
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            spec.coding_backend_registry = None

    def test_same_model_distinct_selection_ids_remain_distinct_profiles(self):
        _, body = self.data()
        first = body["coding_profiles"][0]
        second = copy.deepcopy(first)
        second["selection_id"] = "9" * 32
        second["selection_revision"] = 2
        body["coding_profiles"] = [first, second]
        spec = NativeHostCompositionConfig.from_dict(body)
        self.assertEqual(spec.coding_model_ids(), frozenset(("gpt-6.1-sol",)))
        profiles = [SelectedCodingProfileV2.from_dict(w) for w in body["coding_profiles"]]
        self.assertNotEqual(profiles[0].selection_digest, profiles[1].selection_digest)
        for profile in profiles:
            self.assertEqual(spec.coding_backend_registry.resolve(self.choice(profile)), profile)

    def test_registry_one_and_sixteen_profile_boundaries(self):
        _, body = self.data()
        for count in (1, 16):
            wire = copy.deepcopy(body)
            wire["coding_profiles"] = []
            for number in range(count):
                profile = copy.deepcopy(body["coding_profiles"][2])
                profile["selection_id"] = f"{number + 1:032x}"
                wire["coding_profiles"].append(profile)
            spec = NativeHostCompositionConfig.from_dict(wire)
            self.assertEqual(spec.to_dict(), wire)
            self.assertEqual(spec.coding_model_ids(), frozenset(("synthetic-owner/synthetic-model",)))
            for profile in wire["coding_profiles"]:
                value = SelectedCodingProfileV2.from_dict(profile)
                self.assertEqual(spec.coding_backend_registry.resolve(self.choice(value)), value)

    def test_v1_extra_coding_field_and_v2_missing_or_null_list_denied(self):
        _, body = self.data()
        invalid = []
        for schema in ("aioa.native-host-composition.v1", "unknown", None):
            changed = copy.deepcopy(body)
            changed["schema"] = schema
            invalid.append(changed)
        changed = copy.deepcopy(body)
        del changed["coding_profiles"]
        invalid.append(changed)
        # Preserve non-dict root rejection as well as exact field-set rejection.
        for value in (None, True, [], "untrusted"):
            with self.subTest(root_type=type(value).__name__):
                try:
                    NativeHostCompositionConfig.from_dict(value)
                except (AdmissionError, CapacityError) as error:
                    self.assertIs(type(error), CapacityError, "LEGACY_ROOT_SHAPE_ERROR_CHANGED")
                else:
                    self.fail("NON_DICT_HOST_CONFIG_ACCEPTED")
        # Preserve the original top-level shape codec's exact exception.
        for changed in invalid:
            with self.assertRaises(CapacityError):
                NativeHostCompositionConfig.from_dict(changed)
        changed = copy.deepcopy(body)
        changed["coding_profiles"] = None
        with self.assertRaises(AdmissionError):
            NativeHostCompositionConfig.from_dict(changed)
        self.assertEqual(self.core_constructor.call_count, 0)

    def test_profile_source_and_config_descriptor_drift_denies_native_capture(self):
        owner, spec, body = self.host(descriptor=True)
        access = owner.foundation.access
        capture = access.capture(Capability.MANAGE, use=NativeAccessUse.CONTROL)
        access.require_capture(capture, Capability.MANAGE)
        capture.close()
        original = spec._descriptor_path.read_bytes()
        changed = copy.deepcopy(body)
        changed["coding_profiles"][0]["protocol_options"]["effort"] = "high"
        spec._descriptor_path.write_bytes(host_bytes(changed))
        try:
            with self.assertRaises(AdmissionError):
                access.capture(Capability.MANAGE, use=NativeAccessUse.CONTROL)
        finally:
            spec._descriptor_path.write_bytes(original)
        owner.source_probe = lambda: ("f" * 40, "b" * 64)
        with self.assertRaises(AdmissionError):
            access.capture(Capability.MANAGE, use=NativeAccessUse.CONTROL)

    def test_foundation_registry_foreign_or_replaced_identity_denies(self):
        owner, spec, body = self.host()
        foundation = owner.foundation
        retained = foundation.coding_backend_registry
        foreign = CodingBackendRegistry(tuple(SelectedCodingProfileV2.from_dict(w)
                                              for w in body["coding_profiles"]))
        self.assertIsNot(foreign, retained)
        for value in (None, foreign):
            foundation.coding_backend_registry = value
            try:
                with self.assertRaises(AdmissionError):
                    foundation.require_bindings()
                with self.assertRaises(AdmissionError):
                    foundation.access.capture(Capability.MANAGE, use=NativeAccessUse.CONTROL)
            finally:
                foundation.coding_backend_registry = retained
        replacement = replace(spec, coding_backend_registry=foreign)
        owner._host_composition = replacement
        try:
            with self.assertRaises(AdmissionError):
                foundation.require_bindings()
        finally:
            owner._host_composition = spec
        foreign_foundation = copy.copy(foundation)
        owner.foundation = foreign_foundation
        try:
            with self.assertRaises(AdmissionError):
                foundation.require_bindings()
            with self.assertRaises(AdmissionError):
                foreign_foundation.require_bindings()
        finally:
            owner.foundation = foundation
        foundation.require_bindings()

    def test_constructing_v2_does_not_reserve_approve_select_dispatch_or_modify_policy(self):
        owner, spec, body = self.host()
        before = self.rows(owner)
        policy = owner.foundation.governor.policy
        digest = policy.digest
        for wire in body["coding_profiles"]:
            profile = SelectedCodingProfileV2.from_dict(wire)
            spec.coding_backend_registry.resolve(self.choice(profile))
            self.assertEqual(spec.coding_model_ids(), CODING_IDS)
        self.assertEqual(self.rows(owner), before)
        self.assertIs(owner.foundation.governor.policy, policy)
        self.assertEqual(policy.digest, digest)
        self.assertFalse(any(record_id.startswith(("coding-backend-", "coding-task-", "intent-", "warrant-"))
                             for _, record_id, _ in before))
        self.assertEqual(self.provider_constructions, [])
        self.assertEqual(self.metadata, [])

    def test_no_late_assignment_mutation_after_first_principal(self):
        owner, _, body = self.host()
        core, assignment = self.constructed[0]
        principal = core.local_operator(Capability.MANAGE)
        self.assertEqual(principal.model_binding_ids, CODING_IDS | {OFFLINE})
        tasks = self.publisher(owner)
        task = self.task(owner, tasks, "original-assignment")
        profile = SelectedCodingProfileV2.from_dict(body["coding_profiles"][0])
        tasks.bind_coding_backend(principal, task.task_id, self.choice(profile), self.policy(profile, task))
        self.assertIs(owner.core, core)
        self.assertIs(core._assignment, assignment)
        self.assertIs(assignment.model_binding_ids, principal.model_binding_ids)
        core.require(principal, Capability.MANAGE, scope=owner.ledger.scope)
        self.assertEqual(self.core_constructor.call_count, 1)


if __name__ == "__main__":
    unittest.main()
