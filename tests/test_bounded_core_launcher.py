"""Exercise the selected bounded mode through the public web entry point."""

from contextlib import contextmanager
import hashlib
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import select
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

BASE = "c43a269afcd5cd6e49b934a297d7ae7ccaf2d9e9"
TREE = "fe27e1b8736c911337e7009cadf16861bdc7dde9"
SCHEMA = "aioa-core-bounded-v1"
LICENSE_DIGEST = "a039f83d1d59d97624c355653e0eab74a45b867a091d3d10d12ac1183535e14c"
PROFILE = {
    "schema": SCHEMA,
    "base_sha": BASE,
    "base_tree": TREE,
    "mode": "OFFLINE_FIXTURE",
    "capabilities": ["inspection", "worker-fixture", "task-continuation", "mcp-read"],
}


class BoundedCoreLauncherTests(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.profile = self.root / "profile.json"
        self.write_profile(PROFILE)

    def write_profile(self, value):
        self.profile.write_text(json.dumps(value), encoding="utf-8")
        self.profile.chmod(0o600)

    def entrypoint(self, entry="web_cli"):
        installed = os.environ.get("NZ23B_INSTALLED_ROOT")
        if installed:
            script = "aioa-sparkhat-web" if entry == "web_cli" else "aioa-sparkhat"
            return [
                sys.executable, "-I", "-B", "-c",
                "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); "
                "sys.argv[0]=sys.argv.pop(1); runpy.run_path(sys.argv[0],run_name='__main__')",
                installed, str(Path(installed) / "bin" / script),
            ]
        source = str(Path(__file__).resolve().parents[1])
        return [
            sys.executable, "-I", "-B", "-c",
            f"import sys; sys.path.insert(0,sys.argv.pop(1)); from runtime.{entry} import main; main()",
            source,
        ]

    def arguments(self, *extra, path=None, host="127.0.0.1", state=None):
        return [
            "--bounded-core-offline", str(path or self.profile),
            "--state-dir", str(state or self.state), "--host", host, "--port", "0", *extra,
        ]

    def reject(self, args, expected, *, entry="web_cli"):
        job = subprocess.run(
            self.entrypoint(entry) + args, text=True, capture_output=True, timeout=12,
        )
        self.assertNotEqual(0, job.returncode)
        self.assertIn(expected, job.stderr)
        self.assertNotIn("BOUNDED_CORE_READY", job.stdout)
        return job

    def stop(self, process, *, abrupt=False):
        if process.poll() is None:
            process.kill() if abrupt else process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)

    @contextmanager
    def running(self, *, state=None):
        process = subprocess.Popen(
            self.entrypoint() + self.arguments(state=state),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self.assertTrue(select.select([process.stdout], [], [], 10)[0], "launcher startup timed out")
            line = process.stdout.readline()
            if not line:
                process.wait(timeout=5)
                self.fail(f"bounded entry point did not start: {process.stderr.read()}")
            ready = json.loads(line)
            self.assertEqual("BOUNDED_CORE_READY", ready["status"])
            self.assertEqual(SCHEMA, ready["profile"])
            self.assertEqual((BASE, TREE), (ready["base_sha"], ready["base_tree"]))
            self.assertEqual("127.0.0.1", ready["host"])
            yield process, ready["port"]
        finally:
            self.stop(process)

    def request(self, port, method, path, *, headers=None, body=None):
        conn = HTTPConnection("127.0.0.1", port, timeout=4)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            data = response.read()
            return response.status, json.loads(data) if data else None
        finally:
            conn.close()

    def test_real_launcher_serves_only_fixed_offline_inspection(self):
        with self.running() as (_, port):
            status, view = self.request(port, "GET", "/api/bounded/status")
            self.assertEqual(200, status)
            self.assertEqual(SCHEMA, view["profile"])
            self.assertEqual((BASE, TREE), (view["base_sha"], view["base_tree"]))
            self.assertEqual("MOCK", view["provider"])
            self.assertEqual("BOUND_OFFLINE_FIXTURE", view["core"])
            self.assertEqual("NONE", view["effect_authority"])
            self.assertFalse(view["live_verified"])
            status, worker = self.request(port, "GET", "/api/bounded/worker")
            self.assertEqual(200, status)
            self.assertEqual(["STARTED", "CANDIDATE", "COMPLETED"], worker["events"])
            self.assertEqual("NONE", worker["authority"])
            self.assertFalse(worker["verified"])
            status, planner = self.request(port, "GET", "/api/bounded/continuation")
            self.assertEqual(200, status)
            self.assertEqual(BASE, planner["base_sha"])
            self.assertEqual("NEXT", planner["selection"]["status"])
            self.assertEqual("NONE", planner["effect_authority"])
            status, content = self.request(port, "GET", "/api/bounded/license")
            self.assertEqual(200, status)
            self.assertEqual(("LICENSE", 1074), (content["path"], content["bytes"]))
            self.assertEqual(LICENSE_DIGEST, hashlib.sha256(content["text"].encode()).hexdigest())
            self.assertEqual("NONE", content["authority"])
            self.assertFalse(content["live_verified"])

    def test_http_denies_all_other_routes_verbs_and_inputs(self):
        with self.running() as (_, port):
            for method, path in (
                ("GET", "/"), ("HEAD", "/api/bounded/status"), ("OPTIONS", "/api/bounded/status"),
                ("TRACE", "/api/bounded/status"), ("PUT", "/api/bounded/license"),
                ("POST", "/api/bounded/license"), ("POST", "/api/chat"),
                ("GET", "/api/session"), ("GET", "/api/meta/status"),
                ("GET", "/api/native-operator/readiness"), ("POST", "/api/agent/mcp/submit"),
                ("POST", "/api/memory-patch/apply"),
                ("GET", "/api/bounded/license?path=LICENSE"), ("GET", "/api/bounded/%6cicense"),
                ("GET", "//api/bounded/status"),
            ):
                with self.subTest(method=method, path=path):
                    status, view = self.request(port, method, path)
                    self.assertEqual(403, status)
                    if method != "HEAD":
                        self.assertEqual("BOUNDED_ROUTE_DENIED", view["error"])
            for fields in (
                {"X-AIOA-Intent": "fixture"}, {"Authorization": "fixture"},
                {"Cookie": "fixture=owner"},
                {"Origin": "https://example.invalid"}, {"Host": "example.invalid"},
                {"Transfer-Encoding": "chunked"}, {"Content-Length": "1"},
            ):
                with self.subTest(fields=fields):
                    status, _ = self.request(port, "GET", "/api/bounded/status", headers=fields)
                    self.assertEqual(403, status)
            self.assertEqual(200, self.request(port, "GET", "/api/bounded/status")[0])

    def test_invalid_profiles_are_rejected_before_state_open(self):
        self.reject(self.arguments(path=self.root / "missing"), "BOUNDED_PROFILE_DENIED")
        for update in (
            {"base_sha": "a" * 40}, {"base_tree": "b" * 40}, {"schema": "future"},
            {"mode": "LIVE"}, {"capabilities": ["inspection", "COMMIT"]}, {"approved": True},
        ):
            with self.subTest(update=update):
                self.write_profile({**PROFILE, **update})
                self.reject(self.arguments(), "BOUNDED_PROFILE_DENIED")
        self.profile.write_text('{"schema":', encoding="utf-8")
        self.reject(self.arguments(), "BOUNDED_PROFILE_DENIED")
        text = json.dumps(PROFILE).replace("{", '{"schema": "aioa-core-bounded-v1",', 1)
        self.profile.write_text(text, encoding="utf-8")
        self.reject(self.arguments(), "BOUNDED_PROFILE_DENIED")
        self.write_profile(PROFILE)
        self.profile.chmod(0o660)
        self.reject(self.arguments(), "BOUNDED_PROFILE_DENIED")
        self.assertEqual([], list(self.state.iterdir()))

    def test_conflicting_cli_arguments_do_not_start_any_service(self):
        for option in ("--meta-offline", "--unified-offline", "--mobile-native", "--cpl-fixture"):
            with self.subTest(option=option):
                self.reject(self.arguments(option), "not allowed with argument")
        self.reject(self.arguments("--cpl-live-policy", str(self.root / "fixture")), "not allowed with argument")
        self.reject(self.arguments("--budget-usd", "148"), "BOUNDED_OPTION_DENIED")
        self.reject(self.arguments("--mobile-chat"), "BOUNDED_OPTION_DENIED")
        self.reject(["--bounded-core-off", *self.arguments()[1:]], "BOUNDED_OPTION_DENIED")
        self.reject(self.arguments("--port=0"), "BOUNDED_OPTION_DENIED")
        self.reject(self.arguments(host="0.0.0.0"), "BOUNDED_LOOPBACK_REQUIRED")
        self.assertEqual([], list(self.state.iterdir()))

    def test_bad_state_roots_are_denied_without_touching_foreign_files(self):
        link = self.root / "link"
        link.symlink_to(self.state, target_is_directory=True)
        self.reject(self.arguments(state=link), "BOUNDED_STATE_DENIED")
        self.state.chmod(0o755)
        self.reject(self.arguments(), "BOUNDED_STATE_DENIED")
        self.state.chmod(0o700)
        record = self.state / "core-records.json"
        record.write_bytes(b'{"fixture_result":"UNKNOWN"}')
        for _ in range(2):
            self.reject(self.arguments(), "BOUNDED_STATE_DENIED")
            self.assertEqual(b'{"fixture_result":"UNKNOWN"}', record.read_bytes())
        self.assertFalse((self.state / "runtime.lock").exists())

    def test_packaged_license_checks_both_layouts_and_rejects_ambiguous_data(self):
        self.profile_token()
        from runtime import bounded_core

        install = self.root / "site-packages"
        dist = install / "aioa_sparkhat-0.2.0.dist-info"
        dist.mkdir(parents=True)
        module = install / "runtime" / "bounded_core.py"
        source_record = bounded_core._license_fixture()
        legacy_license = dist / "LICENSE"
        new_license = dist / "licenses" / "LICENSE"
        new_license.parent.mkdir()
        with patch.object(bounded_core, "__file__", str(module)):
            for path in (legacy_license, new_license):
                with self.subTest(layout=path.parent.name):
                    path.write_text(source_record["text"], encoding="utf-8")
                    try:
                        self.assertEqual(LICENSE_DIGEST, bounded_core._license_fixture()["sha256"])
                    finally:
                        path.unlink()
            for path in (legacy_license, new_license):
                path.write_text(source_record["text"], encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "BOUNDED_LICENSE_DENIED"):
                bounded_core._license_fixture()
            legacy_license.unlink()
            new_license.write_text("changed fixture", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "BOUNDED_LICENSE_DENIED"):
                bounded_core._license_fixture()

    def test_active_writer_denies_duplicate_and_crashed_fixture_restarts(self):
        with self.running() as (first, port):
            _, old_view = self.request(port, "GET", "/api/bounded/status")
            self.reject(self.arguments(), "META_RUNTIME_ALREADY_ACTIVE")
            self.stop(first, abrupt=True)
        with self.running() as (_, port):
            _, new_view = self.request(port, "GET", "/api/bounded/status")
            self.assertEqual(old_view, new_view)
        self.assertEqual(["runtime.lock"], sorted(path.name for path in self.state.iterdir()))

    def profile_token(self):
        try:
            from runtime.bounded_core import BoundedCoreProfile
        except ImportError:
            self.fail("bounded profile is absent from the real web service")
        return BoundedCoreProfile.load(self.profile)

    def test_web_service_requires_real_offline_core_and_rejects_extra_bindings(self):
        from runtime.core_admission import AdmissionError, Capability
        from runtime.mission.contracts import MissionError
        from runtime.providers.meta_model_api import MetaModelProvider
        from runtime.webapp import WebRuntimeService

        profile = self.profile_token()
        from runtime.bounded_core import BoundedInspection

        with patch("runtime.webapp.create_runtime", side_effect=AssertionError("unbounded fallback")):
            with self.assertRaisesRegex(ValueError, "BOUNDED_COMPOSITION_REQUIRED"):
                WebRuntimeService(bounded_profile=profile)

        owner = BoundedInspection(profile)
        self.addCleanup(owner.close)
        args = dict(runtime=owner.runtime, meta_owner=owner, bounded_profile=profile)
        service = WebRuntimeService(**args)
        self.assertIs(owner.runtime, service.runtime)
        self.assertIs(owner.core, service.runtime._memory_patch_admission)
        reader = owner.core.local_operator(Capability.READ)
        for capability in set(Capability) - {Capability.READ}:
            with self.subTest(capability=capability), self.assertRaises(AdmissionError):
                owner.core.local_operator(capability)
        with self.assertRaises(AdmissionError):
            owner.core.require(reader, Capability.COMMIT)
        with self.assertRaisesRegex(MissionError, "INSPECTION_ONLY"):
            owner.runtime.run_text_request("fixture observation")
        with self.assertRaisesRegex(ValueError, "CODING_WEB_BINDING_REQUIRED"):
            service.coding_request("apply", {}, intent="coding-apply-v1")

        for extra in (
            {"native_access": object()}, {"coding_principals": {"READ": object()}},
            {"mobile_gateway": object()}, {"cpl_cost_policy": object()}, {"personal_ai": object()},
            {"native_console": object()}, {"cpl_fixture": True},
        ):
            with self.subTest(extra=tuple(extra)):
                with self.assertRaisesRegex(ValueError, "BOUNDED_BINDING_DENIED"):
                    WebRuntimeService(**args, **extra)
        for holder, field, value in (
            (owner, "foundation", object()), (owner, "github_write_route", object()),
            (owner.runtime, "_coding_tasks", object()), (owner.runtime, "executor", object()),
            (owner.manager, "_meta_provider", MetaModelProvider(mode="LIVE")),
            (owner.manager._meta_provider, "transport", object()),
        ):
            with self.subTest(field=field), patch.object(holder, field, value, create=True):
                with self.assertRaisesRegex(ValueError, "BOUNDED_BINDING_DENIED"):
                    WebRuntimeService(**args)

    def test_explicit_server_profile_cannot_fall_back_to_legacy_service(self):
        from runtime.webapp import WebRuntimeService, make_server

        profile = self.profile_token()
        from runtime.bounded_core import BoundedInspection

        with self.assertRaisesRegex(ValueError, "BOUNDED_COMPOSITION_REQUIRED"):
            make_server("127.0.0.1", 0, bounded_profile=profile)
        owner = BoundedInspection(profile)
        self.addCleanup(owner.close)
        service = WebRuntimeService(runtime=owner.runtime, meta_owner=owner, bounded_profile=profile)
        with patch("runtime.webapp.ThreadingHTTPServer", side_effect=AssertionError("opened socket")):
            for binding in ("mobile_gateway", "native_access", "_coding_principals", "core_mcp",
                            "github_write_route"):
                with self.subTest(binding=binding), patch.object(service, binding, object(), create=True):
                    with self.assertRaisesRegex(ValueError, "BOUNDED_BINDING_DENIED"):
                        make_server("127.0.0.1", 0, service)

    def test_console_entrypoint_keeps_bounded_option_unrecognized(self):
        self.reject(self.arguments(), "unrecognized arguments", entry="cli")
        self.assertEqual([], list(self.state.iterdir()))
