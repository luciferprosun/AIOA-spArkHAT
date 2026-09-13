"""C5-01..04: discovery, admission, checksums, ordered recovery and replay."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from support.certification_manifest import inputs, make_core

from runtime.core_admission import AdmissionError, Capability
from runtime.memory_patch.adapters.cockroach import migration_controller as migration
from runtime.memory_patch.adapters.cockroach.pool import (
    DatabasePurpose,
)
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.persistence.migration_contract import (
    JuryDenylist,
    TargetAllowlist,
    canary_fingerprint,
    parse_target_uri,
)


class MigrationGateTests(unittest.TestCase):
    def test_01_c5_import_and_inert_construction_connect_zero(self):
        cfg = inputs()
        core = make_core()
        variables = {
            key: "untrusted-ambient-value"
            for key in (
                "DATABASE_URL",
                "DATABASE_URL_MIGRATOR",
                "DATABASE_URL_APP",
                "COCKROACH_URL",
                "PGHOST",
                "PGSERVICE",
                "PGDATABASE",
                "PGUSER",
                "PGPASSWORD",
                "AWS_ACCESS_KEY_ID",
                "CCLOUD_API_KEY",
                "RENDER_API_KEY",
            )
        }
        with (
            patch.dict(os.environ, variables),
            patch("psycopg.connect") as driver,
            patch("socket.create_connection") as socket,
        ):
            before = len(cfg.calls)
            code = """import importlib
+from unittest.mock import patch
+with patch('psycopg.connect') as driver, patch('socket.create_connection') as network:
+    for name in ('pool','transaction','repositories','migration_controller'):
+        importlib.import_module('runtime.memory_patch.adapters.cockroach.'+name)
+    driver.assert_not_called()
+    network.assert_not_called()
+""".replace("\n+", "\n")
            result = subprocess.run(
                [sys.executable, "-B", "-c", code], capture_output=True, timeout=30
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            ctl = cfg.controller(core)
            factory = cfg.factory(core)
            factory.close()
            ctl.close()
            self.assertEqual(len(cfg.calls), before)
            driver.assert_not_called()
            socket.assert_not_called()

    def test_02_reject_before_connector(self):
        cfg = inputs()
        core = make_core()
        ctl = cfg.controller(core)
        principal = core.local_operator(Capability.MIGRATE)
        before = len(cfg.calls)
        for confirmation in (False, None, 0, 1, "true", [], {}):
            with (
                self.subTest(confirmation=type(confirmation).__name__),
                self.assertRaises((MemoryPatchError, AdmissionError)),
            ):
                ctl.inspect(
                    principal, cfg.target, disposable_ownership_confirmed=confirmation
                )
        for invalid in (
            None,
            core.local_operator(Capability.READ),
            replace(principal, actor_session_id="forged"),
        ):
            with self.assertRaises((MemoryPatchError, AdmissionError)):
                ctl.inspect(invalid, cfg.target, disposable_ownership_confirmed=True)
        with self.assertRaises(MemoryPatchError):
            ctl.inspect(
                principal,
                replace(cfg.target, port=cfg.target.port + 1),
                disposable_ownership_confirmed=True,
            )
        self.assertEqual(len(cfg.calls), before)
        before = len(cfg.calls)
        for uri in (
            "postgresql://127.0.0.1:26257/aioa_disposable_x?hostaddr=127.0.0.1",
            "postgresql://127.0.0.1:26257/aioa_disposable_x?service=ambient",
            "postgresql://user@127.0.0.1:26257/aioa_disposable_x",
            "postgresql://127.0.0.1,localhost:26257/aioa_disposable_x",
            "postgresql://127.0.0.1:26257/aioa_disposable_x%2fother",
            "postgresql://127%2e0.0.1:26257/aioa_disposable_x",
        ):
            with self.assertRaises(MemoryPatchError):
                parse_target_uri(
                    uri,
                    address="127.0.0.1",
                    cluster_marker="fixture",
                    application_role="fixture_app",
                    migrator_role="fixture_migrator",
                    certificate_fingerprint="1" * 64,
                )
        self.assertEqual(len(cfg.calls), before)
        ctl.close()

    def test_02_all_canary_categories_and_role_substitution(self):
        cfg = inputs()
        core = make_core()
        p = core.local_operator(Capability.MIGRATE)
        cases = (
            ("hostname", cfg.target.host, cfg.target),
            ("database", cfg.target.database, cfg.target),
            ("cluster_marker", cfg.target.cluster_marker, cfg.target),
            (
                "account_id",
                "000000000001",
                replace(cfg.target, account_ids=("000000000001",)),
            ),
            (
                "resource_arn",
                "arn:aws:local:fixture:000000000001:test",
                replace(
                    cfg.target,
                    resource_arns=("arn:aws:local:fixture:000000000001:test",),
                ),
            ),
        )
        before = len(cfg.calls)
        for category, value, target in cases:
            deny = JuryDenylist(
                cfg.denylist.fingerprints
                | {(category, canary_fingerprint(category, value))}
            )
            ctl = migration.NativeMigrationController(
                core,
                TargetAllowlist(frozenset({target.fingerprint})),
                deny,
                cfg.handle("migrator", DatabasePurpose.MIGRATOR),
            )
            with self.assertRaises(MemoryPatchError):
                ctl.inspect(p, target, disposable_ownership_confirmed=True)
        with self.assertRaises(MemoryPatchError):
            migration.NativeMigrationController(
                core,
                cfg.allowlist,
                cfg.denylist,
                cfg.handle("app", DatabasePurpose.APPLICATION),
            )
        ctl = cfg.controller(core)
        ctl.handle = cfg.handle("app", DatabasePurpose.MIGRATOR)
        with self.assertRaises(MemoryPatchError):
            ctl.inspect(p, cfg.target, disposable_ownership_confirmed=True)
        self.assertEqual(len(cfg.calls), before)

    def test_02_sealed_snapshot_plan_and_authorization(self):
        cfg = inputs()
        core = make_core()
        p = core.local_operator(Capability.MIGRATE)
        ctl = cfg.controller(core)
        snapshot = ctl.inspect(p, cfg.target, disposable_ownership_confirmed=True)
        plan = ctl.plan(p, cfg.target, snapshot)
        auth = ctl.admission.admit(p, plan, disposable_ownership_confirmed=True)
        before = len(cfg.calls)
        for wrong in (
            replace(snapshot, catalog_fingerprint="0" * 64),
            replace(snapshot, manifest_digest="0" * 64),
            replace(snapshot, _seal=b"forged"),
        ):
            with self.assertRaises(MemoryPatchError):
                ctl.execute(p, plan, auth, wrong)
        for wrong in (
            replace(plan, expected_schema_fingerprint="0" * 64),
            replace(plan, before_schema_fingerprint="0" * 64),
        ):
            with self.assertRaises(MemoryPatchError):
                ctl.execute(p, wrong, auth, snapshot)
        for wrong in (
            replace(auth, disposable_ownership_confirmed=False),
            replace(auth, _seal=b"forged"),
        ):
            with self.assertRaises(MemoryPatchError):
                ctl.execute(p, plan, wrong, snapshot)
        with self.assertRaises(MemoryPatchError):
            replace(plan, mode="ambient")
        with patch.object(
            ctl, "clock", return_value=snapshot.expires_at + timedelta(seconds=1)
        ):
            with self.assertRaises(MemoryPatchError):
                ctl.execute(p, plan, auth, snapshot)
        with patch.object(
            ctl.admission, "_clock", return_value=auth.expires_at + timedelta(seconds=1)
        ):
            with self.assertRaises(MemoryPatchError):
                ctl.execute(p, plan, auth, snapshot)
        self.assertEqual(len(cfg.calls), before)
        ctl.close()

    def test_03_manifest_modified_sql_unknown_unit_denied(self):
        manifest, _, digest = migration.load_assets()
        root = importlib.resources.files("runtime.memory_patch")
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory)
            shutil.copytree(root.joinpath("sql"), candidate / "sql")
            file = candidate / "sql" / manifest["units"][0]["path"]
            original = file.read_bytes()
            file.write_bytes(original + b"\n-- altered\n")
            with (
                patch.object(
                    migration.importlib.resources, "files", return_value=candidate
                ),
                self.assertRaises(MemoryPatchError),
            ):
                migration.load_assets()
            file.write_bytes(original)
            bad = json.loads(json.dumps(manifest))
            bad["units"][0]["path"] = "../0019_unknown.sql"
            (candidate / "sql/manifest.json").write_text(json.dumps(bad))
            with (
                patch.object(
                    migration.importlib.resources, "files", return_value=candidate
                ),
                self.assertRaises(MemoryPatchError),
            ):
                migration.load_assets()
        self.assertEqual(migration.load_assets()[2], digest)

    def test_03_real_schema_catalog_and_explicit_replay(self):
        cfg = inputs()
        core = make_core()
        p = core.local_operator(Capability.MIGRATE)
        ctl = cfg.controller(core)
        snapshot = ctl.inspect(p, cfg.target, disposable_ownership_confirmed=True)
        self.assertEqual(len(snapshot.applied), 18)
        plan = ctl.plan(p, cfg.target, snapshot)
        auth = ctl.admission.admit(p, plan, disposable_ownership_confirmed=True)
        result = ctl.execute(p, plan, auth, snapshot)
        self.assertTrue(result["replayed"])
        self.assertEqual(result["applied_this_run"], 0)
        self.assertEqual(result["progress"], ())
        before = len(cfg.calls)
        with self.assertRaises(MemoryPatchError):
            ctl.execute(p, plan, auth, snapshot)
        self.assertEqual(len(cfg.calls), before)

    def test_04_all_database_and_role_interruption_evidence(self):
        cfg = inputs()
        record = json.loads((cfg.results / "C5_MIGRATION_RESULTS.json").read_text())
        self.assertEqual(record["STATUS"], "PASS")
        self.assertEqual(record["manifest_digest"], migration.load_assets()[2])
        expected = {
            (stage, n)
            for stage in ("role_before", "role_created", "role_after")
            for n in range(1, 10)
        }
        expected |= {
            (stage, n)
            for stage in ("unit_before", "unit_before_commit", "unit_after_commit")
            for n in range(1, 19)
        }
        expected |= {("certificate_before", 18), ("certificate_after", 18)}
        expected |= {
            (stage, unit["ordinal"] * 10000 + index)
            for unit in migration.load_assets()[0]["units"]
            if unit["ordinal"] > 1
            for index in range(1, unit["statement_count"] + 1)
            for stage in ("statement_before", "statement_after")
        }
        self.assertEqual(
            {(row["fault"], row["ordinal"]) for row in record["faults"]}, expected
        )
        self.assertTrue(all(row["STATUS"] == "PASS" for row in record["faults"]))
        self.assertFalse(record["cluster_role_DDL_atomicity_assumed"])
