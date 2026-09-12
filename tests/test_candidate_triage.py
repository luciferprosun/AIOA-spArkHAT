from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from knowledge.tools.promote_candidates import run_triage, triage_record


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FILES = (
    PROJECT_ROOT / "runtime" / "knowledge" / "canonical" / "rhcsa_commands.json",
    PROJECT_ROOT / "runtime" / "knowledge" / "index" / "command_index.json",
)


def base_record(**overrides):
    record = {
        "command": "systemctl status sshd",
        "command_key": "systemctl status sshd",
        "base_command": "systemctl",
        "category": "Systemd",
        "description": "Show the current status of the sshd service.",
        "examples": ["systemctl status sshd"],
        "source_line": 100,
        "source_page": 12,
        "canonical_source": "runtime/knowledge/source/linux_master_library_v1.pdf",
        "source_files": ["LINUX COMMAND"],
        "status": "candidate",
        "duplicate_type": "",
        "duplicate_of": "",
        "quality_flags": [],
        "confidence": "high",
    }
    record.update(overrides)
    return record


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CandidateTriageTests(unittest.TestCase):
    def test_malformed_rejected(self) -> None:
        result = triage_record(base_record(status="malformed"))

        self.assertEqual(result.status, "REJECT")
        self.assertIn("malformed", result.reasons)

    def test_contamination_rejected(self) -> None:
        result = triage_record(base_record(quality_flags=["likely_contamination_or_comment"]))

        self.assertEqual(result.status, "REJECT")
        self.assertIn("likely_contamination_or_comment", result.reasons)

    def test_gemini_additions_isolated_for_review(self) -> None:
        result = triage_record(
            base_record(
                command="ctr",
                command_key="ctr",
                base_command="ctr",
                category="Gemini Expansion Additions",
                source_files=["GEMINI_EXPANSION"],
            )
        )

        self.assertEqual(result.status, "REVIEW")
        self.assertIn("gemini_expansion_addition", result.reasons)

    def test_provenance_required(self) -> None:
        result = triage_record(base_record(canonical_source=""))

        self.assertEqual(result.status, "REJECT")
        self.assertIn("missing_canonical_source", result.reasons)

    def test_weak_description_enters_review(self) -> None:
        result = triage_record(base_record(description="safe", quality_flags=["weak_description"]))

        self.assertEqual(result.status, "REVIEW")
        self.assertIn("weak_description", result.reasons)

    def test_accept_records_preserve_provenance(self) -> None:
        payload = {"records": [base_record()]}
        with tempfile.TemporaryDirectory() as temporary:
            temp_path = Path(temporary) / "candidate_triage_test.json"
            temp_path.write_text(json.dumps(payload), encoding="utf-8")
            result = run_triage(temp_path, write=False)

        accepted = result["buckets"]["ACCEPT"]
        self.assertEqual(len(accepted), 1)
        original = accepted[0]["original_record"]
        self.assertEqual(original["canonical_source"], "runtime/knowledge/source/linux_master_library_v1.pdf")
        self.assertEqual(original["source_line"], 100)
        self.assertEqual(original["source_page"], 12)
        self.assertIn("status_history", accepted[0])

    def test_canonical_indexes_untouched_by_triage(self) -> None:
        before = {path: sha256(path) for path in CANONICAL_FILES}

        run_triage(write=False)

        after = {path: sha256(path) for path in CANONICAL_FILES}
        self.assertEqual(before, after)

    def test_no_automatic_promotion_occurs(self) -> None:
        result = run_triage(write=False)

        self.assertIn("accept", result)
        self.assertFalse((PROJECT_ROOT / "runtime" / "knowledge" / "canonical" / "reviewed_promotions.json").exists())


if __name__ == "__main__":
    unittest.main()
