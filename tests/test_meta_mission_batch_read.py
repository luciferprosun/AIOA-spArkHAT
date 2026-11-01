"""One bounded Core READ transaction, same mission view, no effects."""
import tempfile
import unittest
from pathlib import Path
from runtime.core_admission import Capability,AdmissionError
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
from runtime.meta_hackathon.mission_service import MissionError
from runtime.browser_agent.offline_adapter import FIXTURE_URL


class MissionBatchReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.host=OfflineMetaComposition(Path(self.tmp.name),source_probe=lambda:('a'*40,'b'*64))
        self.addCleanup(self.host.close)
        self.reader=self.host.core.local_operator(Capability.READ)
        self.assertTrue(hasattr(self.host.missions,'evidence_many'),'bounded existing Core READ port missing')

    def preview(self):
        return self.host.missions.preview({'instruction':'fixture','mode':'OFFLINE_FIXTURE','target_url':FIXTURE_URL},self.reader)

    def test_same_evidence_one_transaction_without_execution(self):
        first=self.preview();self.host.missions.stop(first['task_id'],self.reader);second=self.preview()
        expected=tuple(self.host.missions.evidence(t['task_id'],self.reader) for t in (first,second))
        before=self.host.runner._factory.opens
        actual=self.host.missions.evidence_many((first['task_id'],second['task_id']),self.reader)
        self.assertEqual(before+1,self.host.runner._factory.opens)
        self.assertEqual(expected,actual);self.assertEqual(0,self.host.driver.read_count)

    def test_bounds_duplicates_missing_principal_and_missing_row_fail_closed(self):
        task=self.preview()
        with self.assertRaises(AdmissionError):self.host.missions.evidence_many((task['task_id'],),None)
        for values in ((),(task['task_id'],)*17,(task['task_id'],)*2,('meta-'+'f'*32,)):
            with self.assertRaises(MissionError):self.host.missions.evidence_many(values,self.reader)


if __name__=='__main__':unittest.main()
