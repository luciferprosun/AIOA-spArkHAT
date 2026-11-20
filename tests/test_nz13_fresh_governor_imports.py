"""The governor, job store and public contracts must load in any cold order."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = """
import importlib
import sys
sys.path.insert(0, sys.argv[1])
importlib.import_module("runtime.mission." + sys.argv[2])
from runtime.mission import governor, job_contracts, jobs
from runtime.memory_patch.persistence.ports import _original_history_reader

assert _original_history_reader("JOB_ROWS") is jobs._validated_job_rows
assert _original_history_reader("GOVERNOR_STATE") is governor.CoreDualGovernor._load_history
assert jobs.JobClaim is job_contracts.JobClaim
assert jobs.JobEnvelope is job_contracts.JobEnvelope
assert jobs.ReservationRequest is governor.ReservationRequest
print("COLD_RUNTIME_IMPORT_AND_ORIGINAL_READERS")
"""


class FreshGovernorImportTests(unittest.TestCase):
    def check_first_import(self, module):
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", PROBE, str(ROOT), module],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "COLD_RUNTIME_IMPORT_AND_ORIGINAL_READERS"
        )

    def test_job_contracts_can_be_imported_before_governor(self):
        self.check_first_import("job_contracts")

    def test_job_store_can_be_imported_before_governor(self):
        self.check_first_import("jobs")

    def test_governor_first_keeps_original_reader_registration(self):
        self.check_first_import("governor")
