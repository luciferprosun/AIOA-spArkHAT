"""Bounded Core-context corruption controls on an inert synthetic target."""

import json
import unittest

import test_nz13_target_settlement_port as support

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.target_settlement import TARGET_BINDING_KIND


class TargetBindingCorruptionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.TargetSettlementPortTests(
            'test_fresh_start_and_release_share_existing_journal_and_liability')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.base = self.fixture.base
        self.base.dispatch()

    def corrupt(self, change):
        def write(tx):
            row = tx.get(RecordKind.OPERATION, self.base.route._context_key(self.base.warrant))
            state = json.loads(canonical_json_bytes(row.payload))
            refs = state['target_ddr']['evidence_refs']
            self.assertEqual(1, sum(ref['kind'] == TARGET_BINDING_KIND for ref in refs))
            state['target_ddr']['evidence_refs'] = change(refs)
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1, state),
                       expected_revision=row.revision)
        self.base.fx.ledger._run(self.base.fx.p(), Capability.COMMIT, write)

    def require_denials(self):
        before = self.base.path.read_bytes()
        for route in (self.base.route, self.fixture.new_route(None)):
            route.verifier = self.base.verify
            for operation in ('inspect', 'dispatch', 'reconcile'):
                with (self.subTest(port=route.target_settlement is not None, operation=operation),
                      self.assertRaisesRegex(ValueError, 'TOOL_CONTEXT_INTEGRITY')):
                    if operation == 'inspect':
                        route.inspect(self.base.fx.p(Capability.READ), self.base.warrant)
                    elif operation == 'dispatch':
                        route.dispatch(self.base.fx.p(), session_id=self.base.grant.session_id,
                            warrant=self.base.warrant, operation=self.base.operation,
                            reservation=self.base.request, completion=self.base.binding)
                    else:
                        route.reconcile(self.base.fx.p(), self.base.warrant, 1)
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual('Unknown', self.base.fx.journal.inspect(
            self.base.fx.p(Capability.READ), self.base.warrant)['outcome']['contract_type'])
        self.assertEqual(1, len(self.base.calls))
        self.assertEqual([], self.base.verifications)
        self.assertEqual('RELEASED', self.fixture.fact()[1]['state'])

    def test_stripping_context_tag_does_not_remove_signed_warrant_binding(self):
        self.corrupt(lambda refs: [ref for ref in refs if ref['kind'] != TARGET_BINDING_KIND])
        self.require_denials()

    def test_substituted_context_tag_digest_cannot_be_adopted_by_either_route(self):
        self.corrupt(lambda refs: [{**ref, 'digest': 'sha256:' + '0' * 64}
                                   if ref['kind'] == TARGET_BINDING_KIND else ref for ref in refs])
        self.require_denials()

    def test_renamed_reserved_tag_cannot_make_bound_context_legacy(self):
        self.corrupt(lambda refs: [{**ref, 'kind': 'ordinary-caller-evidence'}
                                   if ref['kind'] == TARGET_BINDING_KIND else ref for ref in refs])
        self.require_denials()
