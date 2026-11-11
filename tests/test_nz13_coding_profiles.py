"""Synthetic S1 profile data: no model, entitlement, credentials or transport."""
import copy
import json
import logging
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from dataclasses import FrozenInstanceError
from functools import partial
from pathlib import Path
from unittest import mock

from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.providers import config as provider_config
from runtime.providers import meta_model_api

try:
    from runtime.providers.coding_contracts import (
        CodingContractError,
        SelectedCodingProfileV2,
    )
except ModuleNotFoundError as error:
    if error.name != "runtime.providers.coding_contracts":
        raise
    CodingContractError = SelectedCodingProfileV2 = None

# Independently serialized before the production codec existed. These literals
# are synthetic expired zero-price data and confer no production configuration.
_WIRES = {'CODEX': '{"adapter_contract_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","auth_ref":"CODEX_OWNER_APPROVED_ISOLATED_AUTH_REF","backend":"CODEX","capability_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","endpoint":"owned-stdio://codex-app-server-0.167.0","host_source":{"capsule_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","source_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"limits":{"max_events":16,"max_input_bytes":4096,"max_input_units":4608,"max_output_tokens":512,"max_response_bytes":8192,"timeout_seconds":10},"model_id":"gpt-6.1-sol","pricing_evidence":{"checked_at_utc":"2025-01-01T00:00:00Z","currency":"USD","endpoint_digest":"80f1aa1836e6091498bc2c28715f3c1371a414ce7bc09210a3cae8af14b5c8d1","evidence_digest":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","fixed_nano_usd":0,"input_nano_usd_per_million":0,"model_id":"gpt-6.1-sol","output_nano_usd_per_million":0,"provider_id":"codex_app_server","reasoning_accounting":"BOUNDED_IN_OUTPUT","schema":"aioa.coding-pricing-evidence.v1","valid_until_utc":"2025-01-02T00:00:00Z"},"protocol_options":{"binary_sha256":"1111111111111111111111111111111111111111111111111111111111111111","effort":"max","isolation_profile_digest":"3333333333333333333333333333333333333333333333333333333333333333","model_provider":"SYNTHETIC_TEST_ONLY","schema_manifest_sha256":"2222222222222222222222222222222222222222222222222222222222222222"},"provider_id":"codex_app_server","schema":"aioa.selected-coding-profile.v2","selection_id":"11111111111111111111111111111111","selection_revision":1}', 'META_MUSE': '{"adapter_contract_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","auth_ref":"MUSE_EXISTING_PRIVATE_KEY_REF","backend":"META_MUSE","capability_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","endpoint":"https://api.meta.ai/v1/chat/completions","host_source":{"capsule_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","source_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"limits":{"max_events":16,"max_input_bytes":4096,"max_input_units":4608,"max_output_tokens":512,"max_response_bytes":8192,"timeout_seconds":10},"model_id":"muse-spark-1.3","pricing_evidence":{"checked_at_utc":"2025-01-01T00:00:00Z","currency":"USD","endpoint_digest":"e7ae568e537ee07d2940750b6e97ed8531e7b35aef4eeb644d9ac60d4a52e86a","evidence_digest":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","fixed_nano_usd":0,"input_nano_usd_per_million":0,"model_id":"muse-spark-1.3","output_nano_usd_per_million":0,"provider_id":"meta_model_api","reasoning_accounting":"BOUNDED_IN_OUTPUT","schema":"aioa.coding-pricing-evidence.v1","valid_until_utc":"2025-01-02T00:00:00Z"},"protocol_options":{"api":"CHAT_COMPLETIONS_V1","output_token_parameter":"max_completion_tokens","reasoning_effort":"high"},"provider_id":"meta_model_api","schema":"aioa.selected-coding-profile.v2","selection_id":"22222222222222222222222222222222","selection_revision":1}', 'OPENROUTER': '{"adapter_contract_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","auth_ref":"OPENROUTER_SELECTED_ENV_REF","backend":"OPENROUTER","capability_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","endpoint":"https://openrouter.ai/api/v1/chat/completions","host_source":{"capsule_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","source_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"limits":{"max_events":16,"max_input_bytes":4096,"max_input_units":4608,"max_output_tokens":512,"max_response_bytes":8192,"timeout_seconds":10},"model_id":"synthetic-owner/synthetic-model","pricing_evidence":{"checked_at_utc":"2025-01-01T00:00:00Z","currency":"USD","endpoint_digest":"c82ae1d6c3df7074f75a0a54b6d823dc479180db13e5e7fc1e4345bd97c6f38f","evidence_digest":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","fixed_nano_usd":0,"input_nano_usd_per_million":0,"model_id":"synthetic-owner/synthetic-model","output_nano_usd_per_million":0,"provider_id":"openrouter","reasoning_accounting":"BOUNDED_IN_OUTPUT","schema":"aioa.coding-pricing-evidence.v1","valid_until_utc":"2025-01-02T00:00:00Z"},"protocol_options":{"allow_fallbacks":false,"api":"CHAT_COMPLETIONS_V1","output_token_parameter":"max_tokens","reasoning_effort":null,"require_parameters":true,"upstream_endpoint_slug":"synthetic-provider/synthetic-endpoint"},"provider_id":"openrouter","schema":"aioa.selected-coding-profile.v2","selection_id":"33333333333333333333333333333333","selection_revision":1}'}
_EXPECTED_HASHES = {'CODEX': 'c8a5310cea4f89c02a0a212c715db9da487541c8372d6f133de97226891bb94e', 'META_MUSE': 'a65e668d4adf70d065980294c9d50b1ae0fbf8868927ea3f821917a495f89f36', 'OPENROUTER': '4299cbff20948ea4f03f19140f1d05c7edc657056c8a0a35e8c87b8a0175fef9'}
OWNED_ROOTS = []


def synthetic_profile_wire(backend: str) -> dict:
    return json.loads(_WIRES[backend])


def synthetic_profile(backend: str):
    return SelectedCodingProfileV2.from_dict(synthetic_profile_wire(backend))


class Untouchable:
    def __getattribute__(self, name):
        raise AssertionError("ARGUMENT_MUST_NOT_BE_INSPECTED")

    def __fspath__(self):
        raise AssertionError("ARGUMENT_MUST_NOT_BE_INSPECTED")


class DeniedEnvironment:
    def __init__(self, blocked):
        self.blocked = blocked

    def __getitem__(self, key):
        self.blocked()

    def get(self, *args):
        self.blocked()

    def __iter__(self):
        self.blocked()

    def __contains__(self, key):
        self.blocked()


class CodingProfileTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(SelectedCodingProfileV2, "S1_SELECTED_CODING_PROFILE_INTERFACE_MISSING")
        self.temporary = tempfile.TemporaryDirectory(prefix="bes1-profile-", dir=os.environ["TMPDIR"])
        self.addCleanup(self.temporary.cleanup)
        self.owned_root = Path(self.temporary.name)
        self.owned_key_path = self.owned_root / "synthetic-owned-key-never-read"
        OWNED_ROOTS.append(str(self.owned_root))
        self.ambient_effects = []

    @contextmanager
    def ambient_guard(self):
        def deny(name):
            def blocked(*args, **kwargs):
                self.ambient_effects.append(name)
                raise AssertionError("AMBIENT_ACTIVITY_DENIED:" + name)
            return blocked

        with ExitStack() as stack:
            for name in ("load_api_environment", "runtime_state_dir", "AureonProvider", "GeminiProvider",
                         "NebiusProvider", "OpenAICompatibleProvider"):
                stack.enter_context(mock.patch.object(provider_config, name, deny(name)))
            for name in ("_load_provider_chain", "_load_model_name", "_provider_is_available",
                         "_load_env_key", "_load_xai_key", "_fallback_candidates", "_build_provider"):
                stack.enter_context(mock.patch.object(provider_config.ProviderManager, name, deny(name)))
            for name in ("key_metadata", "load_private_key", "_https_once"):
                stack.enter_context(mock.patch.object(meta_model_api, name, deny(name)))
            stack.enter_context(mock.patch.object(meta_model_api.MetaModelProvider, "__init__", deny("MetaModelProvider")))
            logger = getattr(provider_config, "logger", None)
            if logger is not None:
                stack.enter_context(mock.patch.object(logger, "exception", deny("logger.exception")))
            stack.enter_context(mock.patch("builtins.open", deny("open")))
            stack.enter_context(mock.patch.object(os, "getenv", deny("getenv")))
            stack.enter_context(mock.patch.object(os, "environ", DeniedEnvironment(deny("environ"))))
            for name in ("stat", "lstat", "access", "open", "mkdir", "makedirs", "listdir", "scandir"):
                stack.enter_context(mock.patch.object(os, name, deny("os." + name)))
            for name in ("exists", "is_file", "is_dir", "is_symlink", "stat", "lstat", "open", "mkdir",
                         "read_bytes", "read_text", "write_bytes", "write_text"):
                stack.enter_context(mock.patch.object(Path, name, deny("Path." + name)))
            yield
        self.assertEqual(self.ambient_effects, [])

    def test_all_three_coding_managers_construct_without_ambient_authority(self):
        with self.ambient_guard():
            for backend in ("CODEX", "META_MUSE", "OPENROUTER"):
                profile = synthetic_profile(backend)
                manager = provider_config.ProviderManager(self.owned_root, strict_coding=profile)
                status = manager.coding_status()
                self.assertEqual(status["backend"], backend)
                self.assertEqual(status["selection_digest"], profile.selection_digest)
                self.assertEqual(status["live_status"], "NOT_CERTIFIED")
                self.assertIsNone(manager.provider)
                self.assertIsNone(manager._meta_provider)
                self.assertFalse(hasattr(manager, "config_path"))
                self.assertFalse(hasattr(manager, "providers_path"))
        self.assertFalse(self.owned_key_path.exists())
        self.assertEqual(list(self.owned_root.iterdir()), [])

    def test_profile_snapshot_is_detached_and_full_hash_commits_options(self):
        wire = synthetic_profile_wire("OPENROUTER")
        with self.ambient_guard():
            profile = SelectedCodingProfileV2.from_dict(wire)
            before = profile.selection_digest
            self.assertEqual(before, _EXPECTED_HASHES["OPENROUTER"])
            manager = provider_config.ProviderManager(self.owned_root, strict_coding=profile)
            wire["limits"]["max_output_tokens"] = 4096
            wire["protocol_options"]["allow_fallbacks"] = True
            wire["host_source"]["source_sha"] = "f" * 40
            wire["pricing_evidence"]["fixed_nano_usd"] = 100
            exported = profile.to_dict()
            exported["protocol_options"]["allow_fallbacks"] = True
            exported["pricing_evidence"]["evidence_digest"] = "0" * 64
            self.assertEqual(profile.selection_digest, before)
            self.assertFalse(profile.to_dict()["protocol_options"]["allow_fallbacks"])
            self.assertEqual(manager.coding_status()["selection_digest"], before)
            with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
                profile.selection_digest = "0" * 64

    def test_strict_legacy_entries_cannot_read_keys_or_send(self):
        with self.ambient_guard():
            for backend in ("CODEX", "META_MUSE", "OPENROUTER"):
                manager = provider_config.ProviderManager(self.owned_root, strict_coding=synthetic_profile(backend))
                poison = Untouchable()
                operations = (
                    partial(manager.generate, poison),
                    partial(manager.generate_with_fallback, poison),
                    partial(manager.switch_model, poison),
                    partial(manager.generate_exact, poison, poison, poison),
                    partial(manager.configure_meta, poison),
                    partial(manager.generate_meta_plan, poison, poison, live_binding=poison),
                    partial(manager.generate_meta_chat, poison, poison, live_binding=poison),
                    manager.strict_known_secrets,
                    partial(manager.unified_catalog, receipt_view=poison, last_fixture_invocation=poison),
                    partial(manager.normalize_model_name, poison),
                )
                for operation in operations:
                    with self.assertRaisesRegex(CodingContractError, "^CODING_PROFILE_ENTRY_REQUIRED$"):
                        operation()
                with self.assertRaisesRegex(CodingContractError, "^CODING_SHARED_GATE_REQUIRED$"):
                    manager.generate_coding(poison, poison, poison, live_binding=poison)

    def test_strict_coding_ambiguous_constructor_denied_before_io(self):
        with self.ambient_guard():
            for backend in ("CODEX", "META_MUSE", "OPENROUTER"):
                profile = synthetic_profile(backend)
                for options in ({"meta_only": True}, {"meta_only": 0}, {"meta_only": None},
                                {"state_dir": Untouchable()},
                                {"fixture_base_url": Untouchable()},
                                {"meta_only": True, "state_dir": Untouchable(), "fixture_base_url": Untouchable()}):
                    with self.subTest(backend=backend, fields=tuple(options)), self.assertRaises(CodingContractError):
                        provider_config.ProviderManager(Untouchable(), strict_coding=profile, **options)
            for value in ({}, True, "CODEX", Untouchable()):
                with self.assertRaises(CodingContractError):
                    provider_config.ProviderManager(Untouchable(), strict_coding=value)

    def test_coding_codec_invalid_wire_matrix(self):
        invalid = []
        def changed(path, value):
            wire = synthetic_profile_wire("OPENROUTER")
            target = wire
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            invalid.append(wire)
        for key in synthetic_profile_wire("OPENROUTER"):
            wire = synthetic_profile_wire("OPENROUTER")
            del wire[key]
            invalid.append(wire)
        for key in ("selection_digest", "callback", "command", "approval"):
            changed((key,), "forbidden")
        for section in ("host_source", "limits", "pricing_evidence", "protocol_options"):
            changed((section, "unknown"), None)
            changed((section,), [])
        for path, values in (
            (("selection_revision",), (True, False, 0, -1, 1.0, "1")),
            (("selection_id",), ("A" * 32, "a" * 31, None)),
            (("backend",), ("NEBIUS", "codex", None)),
            (("provider_id",), ("meta_model_api", "openrouter ", 1)),
            (("model_id",), ("openrouter/auto", "owner/model:free", "router", "https://model", "x" * 10000)),
            (("endpoint",), ("https://example.invalid/v1/chat/completions", "https://openrouter.ai/api/v1", None)),
            (("auth_ref",), ("MUSE_EXISTING_PRIVATE_KEY_REF", "/owned/key", None)),
            (("capability_digest",), (None, "d" * 63, "D" * 64)),
            (("adapter_contract_digest",), ("c" * 65, True)),
            (("host_source", "source_sha"), ("a" * 39, "a" * 64, 1)),
            (("host_source", "capsule_digest"), (None, "z" * 64)),
            (("pricing_evidence", "schema"), ("unknown", None)),
            (("pricing_evidence", "provider_id"), ("meta_model_api",)),
            (("pricing_evidence", "model_id"), ("owner/other",)),
            (("pricing_evidence", "endpoint_digest"), ("f" * 64,)),
            (("pricing_evidence", "currency"), ("EUR",)),
            (("pricing_evidence", "checked_at_utc"), ("2025-01-01", "2025-01-01T00:00:00+01:00", "2025-02-30T00:00:00Z")),
            (("pricing_evidence", "valid_until_utc"), ("2024-01-01T00:00:00Z",)),
            (("pricing_evidence", "reasoning_accounting"), ("none", None)),
            (("protocol_options", "api"), ("RESPONSES", None)),
            (("protocol_options", "upstream_endpoint_slug"), ("provider", "auto", "provider/endpoint:free", "https://provider/endpoint")),
            (("protocol_options", "allow_fallbacks"), (True, 0, "false")),
            (("protocol_options", "require_parameters"), (False, 1, "true")),
            (("protocol_options", "output_token_parameter"), ("max_output_tokens", None)),
            (("protocol_options", "reasoning_effort"), ("none", "auto", 0)),
        ):
            for value in values:
                changed(path, value)
        limits = {"max_input_bytes": (1, 16384), "max_input_units": (1, 16896),
                  "max_output_tokens": (1, 4096), "max_response_bytes": (1, 65536),
                  "timeout_seconds": (1, 15), "max_events": (3, 64)}
        for field, (low, high) in limits.items():
            for value in (True, False, low - 1, high + 1, float(low), None, "1"):
                changed(("limits", field), value)
        for field in ("input_nano_usd_per_million", "output_nano_usd_per_million", "fixed_nano_usd"):
            for value in (True, -1, 0.0, float("nan"), float("inf"), None):
                changed(("pricing_evidence", field), value)
        for backend, path, value in (
            ("CODEX", ("model_id",), "gpt-other"),
            ("CODEX", ("protocol_options", "effort"), "none"),
            ("CODEX", ("protocol_options", "model_provider"), "provider/path"),
            ("CODEX", ("protocol_options", "binary_sha256"), None),
            ("META_MUSE", ("model_id",), "muse-other"),
            ("META_MUSE", ("protocol_options", "reasoning_effort"), "none"),
            ("META_MUSE", ("protocol_options", "output_token_parameter"), "max_tokens"),
        ):
            wire = synthetic_profile_wire(backend)
            target = wire
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            invalid.append(wire)
        with self.ambient_guard():
            for index, wire in enumerate(invalid):
                with self.subTest(case=index), self.assertRaisesRegex(CodingContractError, "^CODING_PROFILE_DENIED$"):
                    SelectedCodingProfileV2.from_dict(wire)
            for value in (None, [], True, Untouchable()):
                with self.assertRaises(CodingContractError):
                    SelectedCodingProfileV2.from_dict(value)

    def test_strict_json_rejects_duplicate_unknown_nonfinite_and_invalid_utf8(self):
        raw = _WIRES["OPENROUTER"].encode()
        duplicate_root = raw.replace(b'{', b'{"backend":"CODEX",', 1)
        duplicate_nested = raw.replace(b'"limits":{', b'"limits":{"max_output_tokens":1,', 1)
        malformed = (duplicate_root, duplicate_nested, b'[]', b'null', b'{', b'\xff',
                     br'"\ud800"', raw + b' garbage', b' ' * 100000 + raw,
                     raw.replace(b'"fixed_nano_usd":0', b'"fixed_nano_usd":NaN'),
                     raw.replace(b'"fixed_nano_usd":0', b'"fixed_nano_usd":Infinity'))
        with self.ambient_guard():
            for value in (*malformed, raw.decode(), bytearray(raw), Untouchable()):
                with self.assertRaisesRegex(CodingContractError, "^CODING_PROFILE_DENIED$"):
                    SelectedCodingProfileV2.from_json(value)

    def test_every_v2_wire_field_and_null_is_in_the_full_hash(self):
        with self.ambient_guard():
            for backend in ("CODEX", "META_MUSE", "OPENROUTER"):
                wire = synthetic_profile_wire(backend)
                profile = SelectedCodingProfileV2.from_dict(wire)
                self.assertEqual(profile.selection_digest, _EXPECTED_HASHES[backend])
                self.assertEqual(profile.to_dict(), wire)
                self.assertEqual(SelectedCodingProfileV2.from_json(canonical_json_bytes(wire)).selection_digest,
                                 _EXPECTED_HASHES[backend])
                self.assertEqual(SelectedCodingProfileV2.from_json(json.dumps(wire).encode()).to_dict(), wire)
                self.assertNotIn("selection_digest", profile.to_dict())
                for path in [("auth_ref",), ("capability_digest",)] + [
                    ("protocol_options", key) for key in wire["protocol_options"]]:
                    mutation = copy.deepcopy(wire)
                    parent = mutation if len(path) == 1 else mutation[path[0]]
                    old = parent[path[-1]]
                    parent[path[-1]] = not old if type(old) is bool else ("low" if old is None else str(old) + "_changed")
                    self.assertNotEqual(canonical_sha256(mutation), profile.selection_digest)
                    try:
                        revised = SelectedCodingProfileV2.from_dict(mutation)
                    except CodingContractError as error:
                        self.assertEqual(str(error), "CODING_PROFILE_DENIED")
                    else:
                        self.assertEqual(revised.selection_digest, canonical_sha256(mutation))
                        self.assertNotEqual(revised.selection_digest, profile.selection_digest)
                changed = copy.deepcopy(wire)
                changed["capability_digest"] = "f" * 64
                self.assertNotEqual(SelectedCodingProfileV2.from_dict(changed).selection_digest, profile.selection_digest)

    def test_status_and_public_views_are_data_only(self):
        expected_axes = {"schema": "aioa.coding-provider-status.v1", "configured": True,
            "mock_status": "NOT_RUN", "protocol_status": "NOT_RUN", "live_status": "NOT_CERTIFIED",
            "billing_status": "UNVERIFIED", "automatic_fallback": False, "retry": False,
            "authority": "NONE", "verified": False}
        with self.ambient_guard():
            for backend in ("CODEX", "META_MUSE", "OPENROUTER"):
                wire = synthetic_profile_wire(backend)
                for reasoning in ("BOUNDED_IN_OUTPUT", "UNSUPPORTED"):
                    wire["pricing_evidence"]["reasoning_accounting"] = reasoning
                    profile = SelectedCodingProfileV2.from_dict(wire)
                    manager = provider_config.ProviderManager(self.owned_root, strict_coding=profile)
                    expected = {**expected_axes, "backend": backend, "provider_id": wire["provider_id"],
                        "model_id": wire["model_id"], "selection_digest": profile.selection_digest}
                    self.assertEqual(manager.coding_status(), expected)
                    self.assertEqual(manager.strict_status(), expected)
                    full_name = wire["provider_id"] + "/" + wire["model_id"]
                    manager.current_model = "ambient/must-not-select"
                    manager.last_used_model = "ambient/must-not-retarget"
                    self.assertEqual(manager.describe(), full_name)
                    self.assertEqual(manager.available_models(), [full_name])
                    self.assertEqual(manager.active_fallback_chain(), [])
                    rows = manager.provider_status()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["full_name"], full_name)
                    self.assertFalse(rows[0]["available"])
                    self.assertFalse(rows[0]["live_verified"])
                    self.assertEqual(rows[0]["coding_status"], expected)
                    status = manager.coding_status()
                    status["verified"] = True
                    rows[0]["coding_status"]["live_status"] = "CERTIFIED"
                    self.assertEqual(manager.coding_status(), expected)
                    self.assertEqual(manager.model_notice(Untouchable()),
                        "Coding profile is configured data only; LIVE is NOT_CERTIFIED and billing is UNVERIFIED.")
                    with self.assertRaisesRegex(CodingContractError, "^CODING_SHARED_GATE_REQUIRED$"):
                        manager.generate_coding(None, None, None, live_binding=None)

    def test_supported_data_variants_do_not_grant_live_authority(self):
        with self.ambient_guard():
            for backend in ("CODEX", "META_MUSE", "OPENROUTER"):
                wire = synthetic_profile_wire(backend)
                wire["pricing_evidence"]["checked_at_utc"] = "2099-01-01T00:00:00Z"
                wire["pricing_evidence"]["valid_until_utc"] = "2099-01-02T00:00:00Z"
                wire["pricing_evidence"]["input_nano_usd_per_million"] = 1000000
                profile = SelectedCodingProfileV2.from_dict(wire)
                manager = provider_config.ProviderManager(self.owned_root, strict_coding=profile)
                self.assertEqual(manager.coding_status()["live_status"], "NOT_CERTIFIED")
                self.assertEqual(manager.coding_status()["billing_status"], "UNVERIFIED")
                with self.assertRaisesRegex(CodingContractError, "^CODING_SHARED_GATE_REQUIRED$"):
                    manager.generate_coding(Untouchable(), Untouchable(), Untouchable(), live_binding=Untouchable())

    def test_supported_profile_bounds_and_efforts_remain_data_only(self):
        bounds = {"max_input_bytes": (1, 16384), "max_input_units": (1, 16896),
                  "max_output_tokens": (1, 4096), "max_response_bytes": (1, 65536),
                  "timeout_seconds": (1, 15), "max_events": (3, 64)}
        with self.ambient_guard():
            for field, values in bounds.items():
                for value in values:
                    wire = synthetic_profile_wire("OPENROUTER")
                    wire["limits"][field] = value
                    profile = SelectedCodingProfileV2.from_dict(wire)
                    self.assertEqual(profile.to_dict(), wire)
                    self.assertEqual(profile.selection_digest, canonical_sha256(wire))
            for backend in ("META_MUSE", "OPENROUTER"):
                for effort in ("minimal", "low", "medium", "high", "xhigh", "max"):
                    wire = synthetic_profile_wire(backend)
                    wire["protocol_options"]["reasoning_effort"] = effort
                    profile = SelectedCodingProfileV2.from_dict(wire)
                    self.assertEqual(profile.to_dict(), wire)
                    manager = provider_config.ProviderManager(self.owned_root, strict_coding=profile)
                    with self.assertRaisesRegex(CodingContractError, "^CODING_SHARED_GATE_REQUIRED$"):
                        manager.generate_coding(None, None, None, live_binding=None)
            for token in ("A", "SYNTHETIC_TEST_ONLY", "A" * 64):
                wire = synthetic_profile_wire("CODEX")
                wire["protocol_options"]["model_provider"] = token
                self.assertEqual(SelectedCodingProfileV2.from_dict(wire).to_dict(), wire)
            for token in ("", "1provider", "A" * 65, "provider.name", "provider:account",
                          "provider/path", "provider name", "éprovider"):
                wire = synthetic_profile_wire("CODEX")
                wire["protocol_options"]["model_provider"] = token
                with self.assertRaisesRegex(CodingContractError, "^CODING_PROFILE_DENIED$"):
                    SelectedCodingProfileV2.from_dict(wire)

    def test_plain_input_types_and_manager_recompute_the_profile_hash(self):
        class ForeignDict(dict):
            def items(self):
                raise AssertionError("FOREIGN_CALLBACK_MUST_NOT_RUN")

        with self.ambient_guard():
            with self.assertRaisesRegex(CodingContractError, "^CODING_PROFILE_DENIED$"):
                SelectedCodingProfileV2.from_dict(ForeignDict(synthetic_profile_wire("CODEX")))
            wire = synthetic_profile_wire("CODEX")
            wire["limits"] = ForeignDict(wire["limits"])
            with self.assertRaisesRegex(CodingContractError, "^CODING_PROFILE_DENIED$"):
                SelectedCodingProfileV2.from_dict(wire)
            # Frozen dataclasses are data, not a Python security boundary. Even
            # an explicit in-process object mutation cannot forge the manager hash.
            profile = synthetic_profile("CODEX")
            object.__setattr__(profile, "_digest", "0" * 64)
            manager = provider_config.ProviderManager(self.owned_root, strict_coding=profile)
            self.assertEqual(manager.coding_status()["selection_digest"], _EXPECTED_HASHES["CODEX"])

    def test_owned_legacy_arbitrary_exception_fallback_logs_only_fixed_redaction(self):
        secret_marker = "BES1_SYNTHETIC_SECRET_MUST_NOT_APPEAR"
        events, records, formatted = [], [], []

        class SyntheticProviderFailure(Exception):
            pass

        class SyntheticProvider:
            def __init__(self, name, *, key_path, fail):
                self.full_name, self.key_path, self.fail = name, key_path, fail

            def generate(self, prompt):
                events.append(self.full_name)
                if self.fail:
                    raise SyntheticProviderFailure(secret_marker)
                return "synthetic-success"

        class OwnedHandler(logging.Handler):
            def emit(self, record):
                records.append(record)
                formatted.append(self.format(record))

        owned_logger = logging.getLogger("synthetic.bes1.owned." + self.owned_root.name)
        owned_logger.propagate = False
        handler = OwnedHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        owned_logger.addHandler(handler)
        self.addCleanup(owned_logger.removeHandler, handler)
        providers = {
            "synthetic/first": SyntheticProvider("synthetic/first",
                key_path=self.owned_root / "owned-first-synthetic-key", fail=True),
            "synthetic/second": SyntheticProvider("synthetic/second",
                key_path=self.owned_root / "owned-second-synthetic-key", fail=False),
        }
        with mock.patch.dict(os.environ, {"AIOA_COMPETITION_PROFILE": ""}), mock.patch.object(
                provider_config, "load_api_environment", return_value=None):
            manager = provider_config.ProviderManager(self.owned_root, state_dir=self.owned_root / "fallback-state")
        with mock.patch.object(provider_config, "logger", owned_logger, create=True), mock.patch.object(
                manager, "_fallback_candidates", return_value=list(providers)), mock.patch.object(
                manager, "_build_provider", side_effect=providers.__getitem__):
            self.assertEqual(manager.generate_with_fallback("synthetic-prompt"), "synthetic-success")
        self.assertEqual(events, ["synthetic/first", "synthetic/second"])
        self.assertEqual(manager.describe(), "synthetic/second")
        self.assertIs(manager.provider, providers["synthetic/second"])
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.getMessage(), "Legacy provider attempt failed; original exception details redacted")
        self.assertEqual(record.args, ())
        self.assertEqual(record.exc_info[0], Exception)
        self.assertEqual(str(record.exc_info[1]), "Provider failure details redacted")
        self.assertIsNone(record.exc_info[2])
        self.assertIsNone(record.exc_info[1].__context__)
        self.assertIsNone(record.exc_info[1].__cause__)
        self.assertIsNone(record.exc_info[1].__traceback__)
        rendered = "\\n".join(formatted)
        self.assertNotIn(secret_marker, rendered)
        self.assertNotIn("SyntheticProviderFailure", rendered)
        self.assertNotIn("Traceback", rendered)
        self.assertNotIn("synthetic-prompt", rendered)
        self.assertNotIn("synthetic/first", rendered)

    def test_none_preserves_owned_legacy_fixture_behavior(self):
        expected_chain = ["openrouter/synthetic-legacy", "openrouter/google/gemma-3-27b-it",
                          "gemini/gemini-2.5-flash", "xai/grok-4.3", "deepseek/deepseek-chat"]
        for explicit_none in (False, True):
            state = self.owned_root / ("explicit-none" if explicit_none else "omitted")
            directory = state / "state"
            directory.mkdir(parents=True)
            config = directory / "model_config.json"
            providers = directory / "providers.json"
            config.write_bytes(b'{"model":"openrouter/synthetic-legacy"}')
            providers.write_bytes(b'{"providers":[{"name":"openrouter","model":"synthetic-legacy","enabled":true}]}')
            before_providers = providers.read_bytes()
            options = {"strict_coding": None} if explicit_none else {}
            with mock.patch.dict(os.environ, {"AIOA_COMPETITION_PROFILE": ""}), \
                    mock.patch.object(provider_config, "load_api_environment", side_effect=AssertionError("NO_HYDRATION")), \
                    mock.patch.object(provider_config.ProviderManager, "_build_provider", side_effect=AssertionError("NO_TRANSPORT")):
                manager = provider_config.ProviderManager(self.owned_root, fixture_base_url="http://127.0.0.1:1",
                                                         state_dir=state, **options)
                self.assertEqual(manager.describe(), "openrouter/synthetic-legacy")
                self.assertEqual(manager.active_fallback_chain(), expected_chain)
                self.assertEqual(manager.strict_status(), {"provider": "openrouter", "enabled": True,
                    "mode": "TEST", "configured": True, "fallback": False, "retry": False})
                self.assertEqual(manager.strict_known_secrets(), ("fixture-key-not-a-real-credential",))
                with self.assertRaisesRegex(RuntimeError, "^TEST_TRANSPORT_ONLY"):
                    manager.generate("inert")
                with self.assertRaisesRegex(RuntimeError, "^TEST_TRANSPORT_ONLY"):
                    manager.generate_with_fallback("inert")
                with self.assertRaisesRegex(CodingContractError, "^CODING_PROFILE_REQUIRED$"):
                    manager.coding_status()
                with self.assertRaisesRegex(CodingContractError, "^CODING_SHARED_GATE_REQUIRED$"):
                    manager.generate_coding(None, None, None, live_binding=None)
                self.assertEqual(manager.switch_model("deepseek"), "deepseek/deepseek-chat")
                self.assertEqual(config.read_bytes(), b'{\n  "model": "deepseek/deepseek-chat"\n}')
                self.assertEqual(providers.read_bytes(), before_providers)


if __name__ == "__main__":
    unittest.main()
