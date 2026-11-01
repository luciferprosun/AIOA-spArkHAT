"""Review I1: recorded revocation fences every new legacy authority use."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from q09_support import Fixture
from runtime.core_admission import Capability
from runtime.mission.warrant import KIND


class RevocationConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.fx=Fixture(Path(self.tmp.name)/'records.json');self.addCleanup(self.fx.close)
        self.fx.init()

    def revoke(self):self.fx.ledger.revoke(self.fx.p(Capability.OWNER_APPROVAL),self.fx.warrant)

    def test_legacy_consume_rejects_recorded_revocation_and_inspection_remains_read_only(self):
        self.revoke()
        with self.assertRaisesRegex(ValueError,'REVOKED'):
            self.fx.ledger.consume(self.fx.p(),self.fx.warrant)
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ),self.fx.warrant))

    def test_v1_start_rejects_revocation_before_consumption_or_risk_reservation(self):
        self.revoke()
        with self.assertRaisesRegex(ValueError,'REVOKED'):self.fx.start()
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ),self.fx.warrant))
        self.assertEqual({},self.fx.gov.inspect(self.fx.p(Capability.READ))['reservations'])

    def test_root_revocation_blocks_attenuated_child_and_further_delegation(self):
        parent=self.fx.warrant
        child=replace(parent,warrant_id='narrow-child',expires_at=parent.expires_at-timedelta(seconds=1))
        self.fx.ledger.delegate(self.fx.p(),parent,child);self.revoke()
        with self.assertRaisesRegex(ValueError,'REVOKED'):self.fx.ledger.consume(self.fx.p(),child)
        with self.assertRaisesRegex(ValueError,'REVOKED'):
            self.fx.ledger.delegate(self.fx.p(),child,replace(child,warrant_id='another-child'))
        self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ),parent))

    def test_historical_v1_without_new_witness_keeps_existing_approval_semantics(self):
        other=Fixture(Path(self.tmp.name)/'historical.json');self.addCleanup(other.close)
        other.gov.start_epoch(other.p(Capability.MANAGE))
        other.ledger._run(other.p(Capability.OWNER_APPROVAL),Capability.OWNER_APPROVAL,lambda tx:
            other.ledger._save(tx,other.warrant,{'schema':KIND,'root':other.warrant.to_dict(),
                'active':other.warrant.to_dict(),'consumption':None}))
        self.assertTrue(other.start()['fixture_step_now'])

    def test_inherited_read_release_denies_revoked_warrant_before_reader(self):
        from meta_migration_support import ReadFixture
        from runtime.meta_hackathon import mission_read_offline
        from runtime.providers import tool_calling
        f=ReadFixture(self.tmp.name,mission_read_offline,tool_calling);self.addCleanup(f.close)
        f.approve();f.ledger.revoke(f.principal(Capability.OWNER_APPROVAL),f.warrant)
        with patch.object(mission_read_offline,'read_fixture') as reader:
            with self.assertRaisesRegex(ValueError,'REVOKED'):f.run()
        reader.assert_not_called();self.assertIsNone(f.consumption())


if __name__=='__main__':unittest.main()
