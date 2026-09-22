"""NV05 canonical identity remains protected when optional bindings evolve."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    to_canonical_data,
)
from runtime.memory_patch.errors import ContractValidationError
from runtime.mission.contracts import MissionContext, MissionError
from runtime.mission.lite_contracts import LiteCadence, LiteProfile, parse_lite_profile

OPTIONAL_BINDINGS = (
    "memory_profile_digest",
    "cpl_profile_digest",
    "dynamics_profile_digest",
    "personal_profile_digest",
)


def historical_payload(profile):
    # An explicit compatibility contract, never a blanket exclusion of None.
    excluded = ("digest",) + tuple(
        name for name in OPTIONAL_BINDINGS if getattr(profile, name) is None
    )
    return to_canonical_data(profile, exclude_fields=frozenset(excluded))


class NV06ProfileCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.profile = LiteProfile(
            OwnerScope("nv03-tenant", "nv03-owner", "nv03-space", "nv03-slot"),
            "nv03-watch",
            "observation",
            enabled=True,
            cadence=LiteCadence(interval_seconds=1),
        )
        # Captured from the actual hash call in exact NV05 f994ca442891bd727223b146ea86f6b7bd7f9456.
        self.golden = json.loads(
            (Path(__file__).parent / "fixtures/nv05_lite_off_profile.json").read_text()
        )

    def test_off_payload_and_digest_match_exact_nv05_fixture(self):
        self.assertEqual(self.golden, historical_payload(self.profile))
        independent_bytes = json.dumps(
            self.golden, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(independent_bytes, canonical_json_bytes(historical_payload(self.profile)))
        self.assertEqual(hashlib.sha256(independent_bytes).hexdigest(), self.profile.digest)

    def test_explicit_unset_personal_binding_preserves_payload(self):
        explicit = replace(self.profile, personal_profile_digest=None)
        self.assertNotIn("personal_profile_digest", historical_payload(explicit))
        self.assertEqual(self.golden, historical_payload(explicit))
        self.assertEqual(self.profile.digest, explicit.digest)

    def test_present_personal_binding_changes_and_protects_identity(self):
        composed = replace(
            self.profile, memory_mode="ACTIVE", memory_profile_digest="1" * 64,
            cpl_mode="ACTIVE", cpl_profile_digest="2" * 64,
        )
        bound = replace(composed, personal_profile_digest="3" * 64)
        changed = replace(bound, personal_profile_digest="4" * 64)
        self.assertNotEqual(composed.digest, bound.digest)
        self.assertNotEqual(bound.digest, changed.digest)
        for profile in (bound, changed):
            self.assertEqual(
                profile.personal_profile_digest,
                historical_payload(profile)["personal_profile_digest"],
            )
            self.assertEqual(
                hashlib.sha256(canonical_json_bytes(historical_payload(profile))).hexdigest(),
                profile.digest,
            )

    def test_personal_binding_requires_valid_digest_and_active_composition(self):
        for value in ("", "bad", "A" * 64, 42):
            with self.subTest(value=value), self.assertRaises(ContractValidationError):
                replace(self.profile, personal_profile_digest=value)
        with self.assertRaisesRegex(MissionError, "PERSONAL_DELTA_COMPOSITION_REQUIRED"):
            replace(self.profile, personal_profile_digest="3" * 64)

    def test_future_unrelated_null_field_is_still_digest_protected(self):
        @dataclass(frozen=True, slots=True)
        class FutureProfile(LiteProfile):
            future_policy_binding: str | None = None

        future = FutureProfile(
            self.profile.owner_scope, self.profile.watch_id,
            self.profile.observation_source_ref, enabled=True,
            cadence=self.profile.cadence,
        )
        self.assertIsNone(historical_payload(future)["future_policy_binding"])
        self.assertNotEqual(self.profile.digest, future.digest)
        self.assertEqual(
            hashlib.sha256(canonical_json_bytes(historical_payload(future))).hexdigest(),
            future.digest,
        )
        self.assertNotEqual(
            future.digest, replace(future, future_policy_binding="future-value").digest
        )

    def test_unknown_manifest_field_cannot_be_silently_ignored(self):
        context = MissionContext(
            self.profile.owner_scope, frozenset({"observation"}), "CONTRACT_TEST"
        )
        for value in (None, "future-value"):
            with self.subTest(value=value), self.assertRaisesRegex(
                MissionError, "INVALID_LITE_MANIFEST"
            ):
                parse_lite_profile(
                    json.dumps({**self.golden, "future_policy_binding": value}), context
                )
