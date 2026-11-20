"""All closed target histories fence adoption even if named records are absent."""
import unittest

import test_nz13_target_adoption as support

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.target_projection import (
    HISTORY,
    PHYSICAL_HISTORY,
    PHYSICAL_NO_RELEASE_HISTORY,
)


class PortableHistoryBarrierTests(unittest.TestCase):
    def setUp(self):
        self.f = support.TargetAdoptionTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.head_key = canonical_sha256(('aioa-core-target-head.v1', self.f.ledger.scope,
            'workspace-1', 'portable-inventory-1'))

    def insert_marker(self, schema):
        # Controlled incomplete history in this test's own SQLite, never a replay proof.
        row = StoredRecord(RecordKind.OPERATION, 'orphan-history-marker', self.f.ledger.scope,
                           1, {'schema': schema, 'target_key': self.head_key})
        self.f.run_tx(lambda tx: tx.insert(row))

    def check_prepare(self, schema):
        self.insert_marker(schema)
        before = self.f.records()
        with self.assertRaisesRegex(ValueError, '^TARGET_ADOPTION_BARRIER$'):
            self.f.prepare()
        self.assertEqual(before, self.f.records())
        self.f.assert_inventory_unchanged()

    def check_adopt(self, schema):
        port, request = self.f.prepare()
        warrant = self.f.approve(request)
        self.insert_marker(schema)
        before = self.f.records()
        with self.assertRaisesRegex(ValueError, '^TARGET_ADOPTION_BARRIER$'):
            self.f.adopt(port, request, warrant)
        self.assertEqual(before, self.f.records())
        _row, approval, _warrant = self.f.run_tx(lambda tx: self.f.ledger._load(tx, warrant), Capability.READ)
        self.assertIsNone(approval['consumption'])
        self.f.assert_inventory_unchanged()

    def test_prepare_rejects_generic_orphan_history(self):
        self.check_prepare(HISTORY)

    def test_prepare_rejects_physical_applied_orphan_history(self):
        self.check_prepare(PHYSICAL_HISTORY)

    def test_prepare_rejects_no_release_orphan_history(self):
        self.check_prepare(PHYSICAL_NO_RELEASE_HISTORY)

    def test_adopt_rejects_generic_orphan_history_without_consumption(self):
        self.check_adopt(HISTORY)

    def test_adopt_rejects_physical_applied_orphan_history_without_consumption(self):
        self.check_adopt(PHYSICAL_HISTORY)

    def test_adopt_rejects_no_release_orphan_history_without_consumption(self):
        self.check_adopt(PHYSICAL_NO_RELEASE_HISTORY)
