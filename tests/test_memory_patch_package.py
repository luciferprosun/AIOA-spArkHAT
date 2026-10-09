"""One distribution, inert import and reviewable static source attribution."""

from __future__ import annotations

import ast
import hashlib
import importlib.resources
import json
import unittest
from pathlib import Path

import tomllib

import runtime.memory_patch

ROOT = Path(__file__).resolve().parent.parent


class NativePackageTests(unittest.TestCase):
    def test_single_distribution_exact_nonzero_extra_and_existing_entry_points(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual("aioa-sparkhat", project["project"]["name"])
        self.assertEqual([], project["project"]["dependencies"])
        self.assertEqual(
            ["pydantic==2.13.4", "uuid6==2025.0.1"],
            project["project"]["optional-dependencies"]["nonzero"],
        )
        self.assertEqual(
            {
                "aioa-sparkhat": "runtime.cli:main",
                "aioa-sparkhat-web": "runtime.web_cli:main",
            },
            project["project"]["scripts"],
        )
        self.assertIn(
            "LICENSE-MEMORY-PATCH.txt",
            project["tool"]["setuptools"]["package-data"]["runtime.memory_patch"],
        )

    def test_packaged_exact_source_mit_notice(self):
        data = (
            importlib.resources.files(runtime.memory_patch)
            .joinpath("LICENSE-MEMORY-PATCH.txt")
            .read_bytes()
        )
        self.assertIn(b"MIT License", data)
        source_map = json.loads(
            (ROOT / "docs/provenance/memory_patch_source_map.json").read_text()
        )
        self.assertEqual(
            source_map["license"]["notice_sha256"], hashlib.sha256(data).hexdigest()
        )

    def test_every_source_blob_has_exact_native_destination_or_final_exclusion(self):
        source_map = json.loads(
            (ROOT / "docs/provenance/memory_patch_source_map.json").read_text()
        )
        self.assertEqual(847, len(source_map["source_files"]))
        self.assertEqual(847, len({row["path"] for row in source_map["source_files"]}))
        units = {u["target_path"]: u for u in source_map["native_units"]}
        self.assertEqual(63, sum(u["phase"] == "C4" for u in units.values()))
        self.assertEqual(27, sum(u["phase"] == "C5" for u in units.values()))
        self.assertEqual(1, sum(u["phase"] == "C6" for u in units.values()))
        migrated = 0
        for row in source_map["source_files"]:
            self.assertEqual(40, len(row["source_blob_sha"]))
            self.assertEqual(64, len(row["sha256"]))
            self.assertNotIn(row["migration_action"], {"UNKNOWN", "NEEDS_REVIEW"})
            if row["primary_class"] == "MIGRATE_NATIVE":
                migrated += 1
                self.assertTrue(row["planned_destinations"])
                self.assertTrue(
                    all(path in units for path in row["planned_destinations"])
                )
            if row["migration_action"] in {"BLOCK", "ARCHIVE"}:
                self.assertFalse(row["active_runtime_import"])
        self.assertEqual(231, migrated)
        self.assertFalse(source_map["frozen_source_executed"])

    def test_native_import_graph_has_no_second_app_provider_driver_or_source_checkout(
        self,
    ):
        module_root = Path(runtime.memory_patch.__file__).resolve().parent
        forbidden = {
            "aioa_memory_kernel",
            "fastapi",
            "flask",
            "uvicorn",
            "psycopg",
            "psycopg2",
            "asyncpg",
            "boto3",
            "botocore",
            "openai",
            "anthropic",
            "transformers",
            "sentence_transformers",
            "dotenv",
        }
        for path in module_root.rglob("*.py"):
            if "adapters" in path.parts:
                continue  # C5 adapter imports are checked by the disposable certification.
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse(
                        any(
                            alias.name.split(".")[0] in forbidden
                            for alias in node.names
                        ),
                        path.name,
                    )
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn(
                        (node.module or "").split(".")[0], forbidden, path.name
                    )
                elif isinstance(node, ast.Call):
                    self.assertNotIn(
                        ast.unparse(node.func),
                        {
                            "eval",
                            "exec",
                            "os.getenv",
                            "os.environ.get",
                            "subprocess.run",
                            "subprocess.Popen",
                            "socket.create_connection",
                            "ProviderManager",
                        },
                        path.name,
                    )
        self.assertFalse(any(p.name == ".git" for p in module_root.rglob(".git")))
        self.assertFalse((module_root / "pyproject.toml").exists())

    def test_public_views_do_not_serialize_durable_objects_generically(self):
        path = Path(runtime.memory_patch.__file__).parent / "views.py"
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"__dict__", "model_dump", "asdict"})
            if isinstance(node, ast.Name):
                self.assertNotIn(
                    node.id, {"asdict", "to_canonical_data", "canonical_json_bytes"}
                )
