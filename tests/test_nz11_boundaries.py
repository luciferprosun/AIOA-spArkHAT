"""Stable denials and typed callback failures must never grant patch authority."""

import unittest
from dataclasses import replace

import test_hybrid_capsule as capsule_support

from runtime.mission import repair
from runtime.mission.warrant import WarrantError


class ProofDenialTests(unittest.TestCase):
    def capsule(self):
        return capsule_support.CapsuleTests(
            "test_one_core_and_existing_signing_identity_are_required"
        ).capsule()

    def test_unhashable_proofs_have_stable_denial_before_set_construction(self):
        capsule = self.capsule()
        for field in ("validation_warrants", "validation_receipts"):
            for malformed in ([], {}, set()):
                with self.subTest(field=field, kind=type(malformed).__name__):
                    try:
                        replace(capsule, **{field: (malformed, "a" * 64, "b" * 64)})
                    except (TypeError, ValueError) as error:
                        self.assertIs(type(error), WarrantError)
                        self.assertEqual(str(error), "CAPSULE_PROOFS")
                    else:
                        self.fail("malformed proofs were accepted")

    def test_foreign_scalar_proofs_have_same_typed_denial(self):
        capsule = self.capsule()
        for field in ("validation_warrants", "validation_receipts"):
            for malformed in (None, True, 1, b"proof"):
                with (
                    self.subTest(field=field, value=malformed),
                    self.assertRaisesRegex(WarrantError, "^CAPSULE_PROOFS$"),
                ):
                    replace(capsule, **{field: (malformed, "a" * 64, "b" * 64)})

    def test_valid_proof_roundtrip_keeps_exact_capsule_digest(self):
        capsule = self.capsule()
        self.assertEqual(replace(capsule).digest, capsule.digest)
        self.assertEqual(capsule.authority, "NONE")


class CallbackBoundaryTests(unittest.TestCase):
    def boundary(self):
        boundary = getattr(repair, "failure_boundary", None)
        self.assertTrue(callable(boundary), "typed callback boundary is missing")
        return boundary

    def test_foreign_callback_error_is_typed_without_diagnostic_disclosure(self):
        boundary = self.boundary()
        try:
            with boundary("WORKER_PRODUCER_FAILED"):
                raise ArithmeticError("private callback diagnostic")
        except RuntimeError as error:
            self.assertIs(type(error), repair.RepairBoundaryError)
            self.assertEqual(str(error), "WORKER_PRODUCER_FAILED")
            self.assertNotIn("private callback diagnostic", str(error))
        else:
            self.fail("callback error was swallowed")

    def test_protocol_denial_keeps_its_original_code(self):
        boundary = self.boundary()
        with (
            self.assertRaisesRegex(ValueError, "^PATCHSET_SOURCE_CHANGED$"),
            boundary("VALIDATION_BACKEND_FAILURE"),
        ):
            raise ValueError("PATCHSET_SOURCE_CHANGED")

    def test_process_control_signals_are_never_converted_to_success(self):
        boundary = self.boundary()
        for kind in (KeyboardInterrupt, SystemExit):
            with (
                self.subTest(kind=kind.__name__),
                self.assertRaises(kind),
                boundary("WORKER_CLEANUP_FAILED"),
            ):
                raise kind()


if __name__ == "__main__":
    unittest.main()
