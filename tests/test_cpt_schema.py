from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace

from runtime.critical_loop.cpt.schema import CriticTransformationRecord
from runtime.critical_loop.cpt.transformer import transform_prompt


class CptSchemaTests(unittest.TestCase):
    def test_valid_record_can_be_constructed_via_transformer(self) -> None:
        record = transform_prompt("Review my app and tell me if it is good.")

        self.assertIsInstance(record, CriticTransformationRecord)
        self.assertEqual("balanced_critic", record.critic_mode)
        self.assertFalse(record.provider_call_permitted)
        self.assertFalse(record.execution_permitted)
        self.assertFalse(record.browser_action_permitted)
        self.assertTrue(record.human_review_required)
        self.assertEqual("DRAFT", record.canonical_status)

    def test_record_is_frozen(self) -> None:
        record = transform_prompt("Review this deployment plan.")

        with self.assertRaises(FrozenInstanceError):
            record.canonical_status = "CANONICAL"

    def test_unsafe_flags_cannot_be_true(self) -> None:
        record = transform_prompt("Review this patch.")
        bad_flags = {
            "provider_call_permitted": True,
            "execution_permitted": True,
            "browser_action_permitted": True,
            "human_review_required": False,
        }

        for field, value in bad_flags.items():
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    replace(record, **{field: value})

    def test_canonical_status_cannot_be_canonical(self) -> None:
        record = transform_prompt("Review this release note.")

        with self.assertRaises(ValueError):
            replace(record, canonical_status="CANONICAL")
        with self.assertRaises(ValueError):
            replace(record, canonical_status="HUMAN_APPROVED")

    def test_mode_other_than_balanced_critic_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            transform_prompt("Review this.", mode="epistemic_auditor")

    def test_empty_prompt_fails_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty|whitespace"):
            transform_prompt("")

    def test_record_serializes_to_dict_and_json_cleanly(self) -> None:
        record = transform_prompt("Review this test plan.")

        payload = record.to_dict()
        encoded = record.to_json()
        decoded = json.loads(encoded)

        self.assertEqual(payload["transformation_id"], decoded["transformation_id"])
        self.assertEqual("balanced_critic", decoded["critic_mode"])

    def test_required_sections_and_forbidden_behaviors_cannot_be_empty(self) -> None:
        record = transform_prompt("Review this deployment checklist.")

        with self.assertRaises(ValueError):
            replace(record, required_sections=())
        with self.assertRaises(ValueError):
            replace(record, forbidden_behaviors=())

    def test_serialization_roundtrip_has_stable_expected_fields(self) -> None:
        record = transform_prompt("Review this schema roundtrip.")
        payload = record.to_dict()
        decoded = json.loads(record.to_json())

        self.assertEqual(set(payload), set(decoded))
        self.assertEqual(tuple(decoded["required_sections"]), record.required_sections)
        self.assertEqual(tuple(decoded["forbidden_behaviors"]), record.forbidden_behaviors)


if __name__ == "__main__":
    unittest.main()
