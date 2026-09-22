"""Offline checkpoint contracts; real SQL semantics require the live gate."""

from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from runtime.memory_patch.adapters.cockroach import migration_controller as migration
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError


class LearningMigrationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.statements, self.digest = migration.load_assets("learning-v1")
        self.unit = self.manifest["units"][-1]
        self.applied = tuple(
            (row["ordinal"], row["path"], row["sha256"], self.digest)
            for row in self.manifest["units"][:-1]
        )
        # Explicit catalog model for the checkpoint hash, not a SQL emulator.
        self.state = {
            "schema": [["aioa_memory_patch"]],
            "schema_permissions": [["fixture_schema_owner", True, True]],
            "tables": [["learning_records", True, True, "fixture_migrator"]],
        }

    def checkpoint(self, completed, state=None):
        return [19, self.unit["path"], self.unit["sha256"], self.digest,
                completed, canonical_sha256(state or self.state)]

    def inspect(self, rows, state=None):
        with patch.object(migration, "_rows", return_value=rows) as query:
            try:
                return migration.read_pending(
                    object(), state or self.state, self.manifest,
                    self.digest, self.applied,
                )
            finally:
                self.assertEqual(1, query.call_count)
                self.assertTrue(query.call_args.args[1].startswith("SELECT "))

    def test_acknowledged_grant_and_ownership_resume_at_next_statement(self):
        for completed, next_operation in ((9, "ALTER TABLE"), (10, "REVOKE CREATE")):
            with self.subTest(completed=completed):
                state = deepcopy(self.state)
                if completed == 10:
                    state["tables"][0][3] = "fixture_schema_owner"
                pending = self.inspect([self.checkpoint(completed, state)], state)
                self.assertEqual(completed, pending[4])
                self.assertTrue(self.statements[19][pending[4]].startswith(next_operation))

    def test_ownership_acknowledgement_gap_requires_read_only_recovery(self):
        checkpoint = self.checkpoint(9)
        changed = deepcopy(self.state)
        changed["tables"][0][3] = "fixture_schema_owner"
        with self.assertRaises(MemoryPatchError) as raised:
            self.inspect([checkpoint], changed)
        self.assertEqual(ErrorCode.RECOVERY_REQUIRED, raised.exception.code)

    def test_changed_manifest_or_unit_cannot_adopt_diagnostic_checkpoint(self):
        for field in (2, 3):
            with self.subTest(field=field):
                checkpoint = self.checkpoint(8)
                checkpoint[field] = "0" * 64
                with self.assertRaises(MemoryPatchError) as raised:
                    self.inspect([checkpoint])
                self.assertEqual(ErrorCode.RECOVERY_REQUIRED, raised.exception.code)

    def test_completed_revoke_is_recoverable_but_out_of_bounds_is_denied(self):
        state = deepcopy(self.state)
        state["schema_permissions"][0][2] = False
        state["tables"][0][3] = "fixture_schema_owner"
        self.assertEqual(11, self.inspect([self.checkpoint(11, state)], state)[4])
        for completed in (-1, self.unit["statement_count"] + 1):
            with self.subTest(completed=completed), self.assertRaises(MemoryPatchError):
                self.inspect([self.checkpoint(completed, state)], state)
