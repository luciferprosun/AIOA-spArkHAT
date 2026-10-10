"""Atomic native START/G2 bridge; independently observed durable state, no host effect."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from q09_support import Fixture
from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import TransactionContext
from runtime.mission.liability import CoreLiabilityLedger


class CoreEffectTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.fx = Fixture(Path(self.tmp.name)/'state.json'); self.addCleanup(self.fx.close)
        self.fx.init()
        self.liability = CoreLiabilityLedger(self.fx.core, self.fx.runner, self.fx.ledger.scope)
        self.trace = FaultTrace(FaultKind.LOST_ACK, self.fx.warrant.task_id,
                                self.fx.request.request_id, self.fx.warrant.operation_hash)
        self.identity = classify_fault(self.trace).liability_id
        self.graph = DependencyGraph(self.trace.task_id, (
            DependencyNode('effect', NodeKind.OPERATION, liability_ids=(self.identity,)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('effect',))))
        self.liability.initialize(self.fx.p(), self.graph)

    def bridge(self):
        self.assertTrue(callable(getattr(self.fx.journal, 'start_in_transaction', None)),
                        'Native START has no composable transaction boundary')
        self.assertTrue(callable(getattr(self.liability, 'record_unknown_in_transaction', None)),
                        'G2 UNKNOWN has no composable transaction boundary')
        def change(tx):
            result = self.fx.journal.start_in_transaction(tx, self.fx.warrant,
                                                          self.fx.operation, self.fx.request)
            if result['fixture_step_now']:
                self.liability.record_unknown_in_transaction(tx, self.trace, self.graph,
                                                              self.fx.warrant.issued_at)
            return result
        return self.fx.runner.run(TransactionContext(self.fx.p(), Capability.COMMIT), change)

    def test_start_and_required_liability_are_one_durable_transaction(self):
        self.assertTrue(self.bridge()['fixture_step_now'])
        records = self.liability.inspect(self.fx.p(Capability.READ), self.trace.task_id)
        self.assertEqual(1, len(records))
        self.assertEqual(self.identity, records[0].liability_id)
        self.assertEqual('OPEN', records[0].status.value)
        self.assertFalse(self.bridge()['fixture_step_now'])
        self.assertEqual(50, self.fx.gov.inspect(self.fx.p(Capability.READ))['exposure']['global']['money_nano'])

    def test_liability_write_failure_rolls_back_consumption_reservation_and_start(self):
        # Missing predeclared slot is a real validation failure after START writes in the same tx.
        self.graph = DependencyGraph(self.trace.task_id, (
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE),))
        before = self.fx.path.read_bytes() if hasattr(self.fx, 'path') else Path(self.tmp.name,'state.json').read_bytes()
        with self.assertRaises(ValueError):
            self.bridge()
        self.assertEqual(before, Path(self.tmp.name,'state.json').read_bytes())
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ), self.fx.warrant))
        self.assertEqual({}, self.fx.gov.inspect(self.fx.p(Capability.READ))['reservations'])
