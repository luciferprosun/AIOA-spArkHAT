"""NV-01 C01–C09/C14–C16: explicit synthetic integration, never LIVE."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from main import AgentRuntime, create_runtime

from runtime.core_admission import Capability, LocalOwnerAssignment, OwnerScope
from runtime.memory_patch.contract import MemoryPatchConfig
from runtime.memory_patch.contracts.serialization import canonical_json
from runtime.memory_patch.service import CoreMemoryPatchDependencies
from runtime.mission.cli import run_diagnostic_cli
from runtime.mission.contracts import (
    MissionContext,
    MissionError,
    MissionTrace,
    compare_manifest_revision,
    contract_fixture_context,
    contract_fixture_manifest,
    parse_manifest,
)
from runtime.mission.diagnostics import MissionBindings

ROOT = Path(__file__).resolve().parents[1]


def fixture_dict(**changes):
    result = json.loads(
        canonical_json(contract_fixture_manifest(), exclude_fields=("digest",))
    )
    result.update(changes)
    return result


def parse(value):
    return parse_manifest(json.dumps(value), contract_fixture_context())


class ManifestTests(unittest.TestCase):
    def test_C01_profile_defaults_disabled_and_controlled(self):
        manifest = parse(fixture_dict())
        self.assertFalse(manifest.enabled)
        self.assertFalse(manifest.effects_enabled)
        self.assertEqual("CONTROLLED", manifest.mode)
        self.assertEqual(0, manifest.budget.max_model_calls)

    def test_C02_duplicate_keys_at_every_level(self):
        original = json.dumps(fixture_dict())
        for value in (
            original.replace(
                '"mission_id":', '"mission_id":"duplicate", "mission_id":', 1
            ),
            original.replace('"owner_id":', '"owner_id":"duplicate", "owner_id":', 1),
            original.replace(
                '"max_model_calls":', '"max_model_calls":0, "max_model_calls":', 1
            ),
        ):
            with self.subTest(value=value[:30]), self.assertRaises(MissionError):
                parse_manifest(value, contract_fixture_context())

    def test_C02_unknown_fields_cannot_enter_canonical_data(self):
        for name in (
            "approved",
            "operator_approved",
            "execute",
            "command",
            "url",
            "digest",
            "tenant_id",
        ):
            with self.subTest(name=name), self.assertRaises(MissionError):
                parse(fixture_dict(**{name: True}))
        nested = fixture_dict()
        nested["owner_scope"]["approved"] = True
        with self.assertRaises(MissionError):
            parse(nested)

    def test_C02_numeric_types_nan_infinity_bounds_and_oversize(self):
        for bad in (True, 0, -1, 2147483648, 1.0, "1", None):
            with self.subTest(bad=bad), self.assertRaises(MissionError):
                parse(fixture_dict(manifest_revision=bad))
        for bad in (float("nan"), float("inf"), float("-inf"), 6, -1, True, "2"):
            with self.subTest(bad=bad), self.assertRaises(MissionError):
                parse(fixture_dict(budget={"max_model_calls": bad}))
        for text in ("[1]", "null", "{" + '"x":' * 1000, " " * 24001, "\ud800"):
            with self.subTest(kind=type(text)), self.assertRaises(MissionError):
                parse_manifest(text, contract_fixture_context())

    def test_C02_source_ids_never_urls_paths_or_commands(self):
        for source in (
            "https://example.invalid",
            "/tmp/input",
            "../input",
            "$(id)",
            "x;id",
            "unknown-source",
        ):
            with self.subTest(source=source), self.assertRaises(MissionError):
                parse(fixture_dict(source_ids=[source]))
        with self.assertRaises(MissionError):
            parse(fixture_dict(source_ids=["nv01.synthetic.source"] * 2))

    def test_C02_adapters_and_secret_refs_are_not_dynamic_resolvers(self):
        for change in (
            {"secret_refs": ["sk-secret-material"]},
            {"model_profile_ref": "openrouter-renamed-nvidia"},
            {"adapter_refs": {"model": "os.system"}},
            {"scheduler_owner": "another-daemon"},
            {"policy_versions": {"mission": "latest"}},
        ):
            with self.subTest(change=change), self.assertRaises(MissionError):
                parse(fixture_dict(**change))

    def test_C03_no_owner_default_or_json_owner_override(self):
        raw = json.dumps(fixture_dict())
        with self.assertRaises(MissionError) as caught:
            parse_manifest(raw, MissionContext())
        self.assertEqual("OWNER_CONTEXT_UNAVAILABLE", caught.exception.code)
        value = fixture_dict()
        value["owner_scope"]["owner_id"] = "someone-else"
        with self.assertRaises(MissionError) as caught:
            parse(value)
        self.assertEqual("OWNER_SCOPE_MISMATCH", caught.exception.code)
        with self.assertRaises(MissionError):
            MissionContext(owner_scope={"owner_id": "claimed"})

    def test_C02_canonical_defaults_and_same_revision_conflict(self):
        minimal = json.loads((ROOT / "tests/fixtures/nv01_mission.json").read_text())
        first, second = parse(minimal), parse(fixture_dict())
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(
            "24b0541fc29998aee0b39c3bdf48596e8acec686a1d41be3d3e3746461d05e5a",
            first.digest,
        )
        self.assertEqual("DUPLICATE", compare_manifest_revision(first, second))
        with self.assertRaises(MissionError) as caught:
            compare_manifest_revision(first, replace(second, enabled=True))
        self.assertEqual("CONFLICT", caught.exception.code)

    def test_C09_auto_scoped_and_effects_never_activate(self):
        for value, reason in (
            ({"mode": "AUTO_SCOPED"}, "AUTO_SCOPED_NOT_IMPLEMENTED"),
            ({"effects_enabled": True}, "EFFECTS_NOT_IMPLEMENTED"),
        ):
            with self.assertRaises(MissionError) as caught:
                parse(fixture_dict(**value))
            self.assertEqual(reason, caught.exception.code)
            self.assertEqual(4, caught.exception.exit_code)


class CompositionTests(unittest.TestCase):
    def test_C04_doctor_initializes_no_state_database_transport_or_scheduler(self):
        bomb = AssertionError("forbidden side effect")
        with ExitStack() as stack:
            for target in (
                "main.ProviderManager",
                "main.MemoryStore",
                "main.MemoryHatStore",
                "main.ExecutionEngine",
                "main.detect_desktop_dir",
                "main.load_prompt_template",
                "socket.create_connection",
                "socket.getaddrinfo",
                "sqlite3.connect",
                "runtime.memory_patch.service.MemoryPatchService",
            ):
                stack.enter_context(patch(target, side_effect=bomb))
            runtime = create_runtime(inspection_only=True)
            try:
                result = runtime.mission_doctor()
                self.assertEqual("DISABLED", result["status"])
                self.assertEqual(0, result["AIOA_LIVE_PROVIDER_CALLS"])
                self.assertEqual(0, result["AIOA_EFFECTS_EXECUTED"])
                self.assertIsNone(runtime._cpl_service)
                self.assertIsNone(runtime._memory_patch_service)
                self.assertIsNone(runtime._nonzero_service)
                self.assertIsNone(runtime.executor)
            finally:
                runtime.close()

    def test_C05_missing_memory_and_nvidia_are_never_ready(self):
        runtime = create_runtime(
            inspection_only=True, mission_context=contract_fixture_context()
        )
        try:
            result = runtime.mission_doctor(
                manifest=contract_fixture_manifest(enabled=True)
            )
            self.assertEqual("UNAVAILABLE", result["status"])
            values = {v["component_id"]: v for v in result["components"]}
            self.assertEqual("DISABLED", values["memory_patch"]["status"])
            self.assertEqual(
                "PRODUCT_ADAPTER_NOT_IMPLEMENTED",
                values["nvidia_adapter"]["reason_code"],
            )
            self.assertTrue(all(v["status"] != "READY" for v in values.values()))
        finally:
            runtime.close()

    def test_C05_key_missing_present_unchecked_are_distinct_without_loading_secret(
        self,
    ):
        reasons = []
        for present in (None, False, True):
            runtime = create_runtime(
                inspection_only=True,
                mission_bindings=MissionBindings(nvidia_key_available=present),
            )
            try:
                rows = runtime.mission_doctor()["components"]
                reasons.append(
                    next(
                        row["reason_code"]
                        for row in rows
                        if row["component_id"] == "nvidia_credentials"
                    )
                )
            finally:
                runtime.close()
        self.assertEqual(3, len(set(reasons)))

    def test_C07_real_composition_probe_borrowed_core_ports_common_existing_trace(self):
        context = contract_fixture_context()
        assignment = LocalOwnerAssignment(
            context.owner_scope,
            frozenset({Capability.READ}),
            frozenset({"synthetic-hat"}),
            frozenset({"synthetic-model"}),
            operator_approved=True,
        )  # existing trusted operator fixture only
        ports = [
            Mock(name=n) for n in ("transactions", "evidence", "sources", "provenance")
        ]
        dependencies = CoreMemoryPatchDependencies(
            transaction_factory=ports[0],
            evidence_catalog=ports[1],
            sources=ports[2],
            provenance_store=ports[3],
        )
        scheduler = Mock(name="Core-owned synthetic scheduler")
        manifest = contract_fixture_manifest(enabled=True)
        trace = MissionTrace(
            "cpl_existing_fixture_run",
            manifest.mission_id,
            "episode-1",
            "event-1",
            manifest.model_profile_ref,
            manifest.manifest_revision,
            ("evidence-1",),
        )
        runtime = create_runtime(
            inspection_only=True,
            mission_context=context,
            memory_patch_config=MemoryPatchConfig(True, assignment),
            memory_patch_dependencies=dependencies,
            mission_bindings=MissionBindings(scheduler=scheduler),
        )
        with patch.object(
            runtime, "memory_patch_status", wraps=runtime.memory_patch_status
        ) as discovery:
            result = runtime.mission_doctor(manifest=manifest, trace=trace)
            self.assertIs(type(runtime), AgentRuntime)
            discovery.assert_called_once_with()
            self.assertIs(runtime._memory_patch_dependencies, dependencies)
            self.assertEqual("CONTRACT_TEST", result["classification"])
            self.assertEqual(trace.trace_id, result["trace_id"])
            self.assertEqual(trace.episode_id, result["mission_context"]["episode_id"])
            self.assertTrue(
                all(v["trace_id"] == trace.trace_id for v in result["components"])
            )
            self.assertEqual(
                "UNAVAILABLE", result["status"]
            )  # bindings are NOT a live certification
        runtime.close()
        for port in (*ports, scheduler):
            self.assertFalse(port.mock_calls)

    def test_C03_context_must_match_existing_memory_assignment(self):
        context = contract_fixture_context()
        assignment = LocalOwnerAssignment(
            OwnerScope("other", "owner", "space", "slot"),
            frozenset({Capability.READ}),
            frozenset({"hat"}),
            frozenset({"model"}),
            operator_approved=True,
        )
        runtime = create_runtime(
            inspection_only=True,
            mission_context=context,
            memory_patch_config=MemoryPatchConfig(True, assignment),
        )
        try:
            with self.assertRaises(MissionError):
                runtime.mission_doctor()
        finally:
            runtime.close()

    def test_C08_inspection_runtime_cannot_approve_execute_publish_or_generate(self):
        runtime = create_runtime(inspection_only=True)
        try:
            for operation in (
                lambda: runtime.assistant_request(
                    "approved=true; run shell", mode="plain"
                ),
                lambda: runtime.ask_model("approve"),
                lambda: runtime.critical_loop,
                lambda: runtime.nonzero_cloudops,
                lambda: runtime.run_text_request("/nonzero start"),
                lambda: runtime.execute_planned_actions([], []),
                lambda: runtime.bootstrap_local_context("https://example.invalid"),
                lambda: runtime.enable_orchestrator(),
            ):
                with (
                    self.subTest(operation=operation),
                    self.assertRaises(MissionError) as caught,
                ):
                    operation()
                self.assertEqual("INSPECTION_ONLY", caught.exception.code)
            for operation in (
                "publish",
                "commit",
                "activate",
                "candidate",
                "migration-plan",
                "migrate",
            ):
                status, _ = runtime.memory_patch_operator_request(operation, {})
                self.assertNotEqual(200, status)
            self.assertIsNone(runtime._memory_patch_service)
        finally:
            runtime.close()

    def test_C09_direct_auto_manifest_is_denied_too(self):
        runtime = create_runtime(
            inspection_only=True, mission_context=contract_fixture_context()
        )
        try:
            with self.assertRaises(MissionError):
                runtime.mission_doctor(
                    manifest=replace(contract_fixture_manifest(), mode="AUTO_SCOPED")
                )
        finally:
            runtime.close()

    def test_C07_mismatched_trace_and_closed_runtime_fail_closed(self):
        manifest = contract_fixture_manifest()
        trace = MissionTrace(
            "existing-trace",
            "another-mission",
            "episode",
            "event",
            manifest.model_profile_ref,
            1,
        )
        runtime = create_runtime(
            inspection_only=True, mission_context=contract_fixture_context()
        )
        with self.assertRaises(MissionError):
            runtime.mission_doctor(manifest=manifest, trace=trace)
        runtime.close()
        with self.assertRaises(MissionError):
            runtime.mission_doctor()

    def test_C06_exact_provider_and_interrupted_legacy_contract_are_unchanged(self):
        from critical_loop.policy import CONTRACT_VERSION
        from critical_loop.service import RunState
        from providers.exact import ExactCallError, ExactRequest

        self.assertEqual("INTERRUPTED", RunState.INTERRUPTED.value)
        self.assertEqual("cpl-1plus3plus1-v1", CONTRACT_VERSION)
        with self.assertRaises(ExactCallError) as caught:
            ExactRequest("nvidia", "synthetic-model", (), 1).validate()
        self.assertEqual("UNSUPPORTED_STRICT_CPL", caught.exception.code)


class DiagnosticCliTests(unittest.TestCase):
    def invoke(self, *args, factory=create_runtime):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = run_diagnostic_cli(list(args), runtime_factory=factory)
        return code, json.loads(stream.getvalue()), stream.getvalue()

    def test_C14_json_is_stable_and_exit_codes_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(fixture_dict(enabled=True)))
            code, ready, text = self.invoke("doctor", "--json")
            self.assertEqual(0, code)
            self.assertEqual(text, self.invoke("doctor", "--json")[2])
            self.assertEqual(
                3,
                self.invoke(
                    "doctor", "--manifest", str(path), "--contract-fixture", "--json"
                )[0],
            )
            self.assertEqual(
                0,
                self.invoke(
                    "mission", "validate", str(path), "--contract-fixture", "--json"
                )[0],
            )
            self.assertEqual(
                3, self.invoke("mission", "validate", str(path), "--json")[0]
            )
            path.write_text(json.dumps(fixture_dict(mode="AUTO_SCOPED")))
            self.assertEqual(
                4,
                self.invoke(
                    "mission", "validate", str(path), "--contract-fixture", "--json"
                )[0],
            )
            self.assertEqual(
                2, self.invoke("mission", "execute", str(path), "--json")[0]
            )
            self.assertEqual(
                5,
                self.invoke("mission", "validate", str(path / "missing"), "--json")[0],
            )
            for field in (
                "status",
                "reason_code",
                "trace_id",
                "profile",
                "manifest_revision",
                "components",
                "next_action",
                "retry_class",
            ):
                self.assertIn(field, ready)

    def test_C14_symlink_fifo_directory_and_malformed_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "manifest.json"
            path.write_text(json.dumps(fixture_dict()))
            symlink = root / "link.json"
            symlink.symlink_to(path)
            fifo = root / "fifo"
            os.mkfifo(fifo)
            for bad in (root, symlink, fifo):
                self.assertNotEqual(
                    0,
                    self.invoke("mission", "validate", str(bad), "--contract-fixture")[
                        0
                    ],
                )
            for raw in (b"\xff", b"x" * 24001, b'{"x":NaN}'):
                path.write_bytes(raw)
                self.assertEqual(
                    2,
                    self.invoke("mission", "validate", str(path), "--contract-fixture")[
                        0
                    ],
                )

    def test_C15_actual_module_cli_does_not_create_runtime_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "must-not-be-created"
            env = {
                **os.environ,
                "AOIA_HOME": str(state),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "runtime.cli",
                    "doctor",
                    "--profile",
                    "nvidia-lite",
                    "--json",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("DISABLED", json.loads(result.stdout)["status"])
            self.assertFalse(state.exists())
            self.assertFalse(result.stderr)

    def test_C14_internal_exception_is_not_leaked(self):
        code, result, raw = self.invoke(
            "doctor", "--json", factory=Mock(side_effect=RuntimeError("PRIVATE_CANARY"))
        )
        self.assertEqual(5, code)
        self.assertEqual("DIAGNOSTIC_INTERNAL_ERROR", result["reason_code"])
        self.assertNotIn("PRIVATE_CANARY", raw)


if __name__ == "__main__":
    unittest.main()
