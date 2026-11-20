"""Render uses the existing validator/Core; negative tests never start a process."""
import tempfile
import unittest
from pathlib import Path

import test_nz11_general_recipe as support
from cryptography.hazmat.primitives.asymmetric import ec
from q09_support import Fixture

from runtime.core_admission import AdmissionError, Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission import repair_validation
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mobile_gateway.wire import Identity


class CoreRenderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fx = Fixture(self.root / 'core.json')
        self.addCleanup(self.fx.close)
        self.validator = repair_validation.CoreSandboxValidation(
            self.fx.journal, lambda *_: self.fail('No preparation/dispatch in negative contracts'))

    def api(self):
        self.assertTrue(callable(getattr(self.validator, 'render', None)),
                        'Existing Core validator has no pinned render path')
        self.assertTrue(callable(getattr(self.validator, 'read_render', None)),
                        'Missing read-only canonical render receipt projection')

    def test_model_data_cannot_supply_a_principal_or_default_authority(self):
        self.api()
        for principal in (None, {}, {'approved': True}):
            with self.subTest(principal=principal), self.assertRaises(AdmissionError):
                self.validator.render(principal, None, {'status': 'PASS'})

    def test_foreign_core_principal_is_denied_before_recipe_or_step_inspection(self):
        self.api()
        other = Fixture(self.root / 'other.json')
        self.addCleanup(other.close)
        with self.assertRaises(AdmissionError):
            self.validator.render(other.p(), None, None)

    def test_http_or_model_dict_cannot_become_an_approved_render_recipe(self):
        self.api()
        for recipe in ({'html': '<p>PASS</p>'}, {'approved': True, 'argv': ['chrome']}, None):
            with self.subTest(recipe=recipe), self.assertRaisesRegex(ValueError, 'RENDER_OPERATOR_RECIPE_REQUIRED'):
                self.validator.render(self.fx.p(), None, recipe)

    def test_python_validation_profile_cannot_be_retagged_as_a_renderer(self):
        self.api()
        case = support.GeneralRecipeTests('runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        validator = repair_validation.CoreSandboxValidation(self.fx.journal, lambda *_: (), profile=case.profile())
        with self.assertRaisesRegex(ValueError, 'RENDER_PROFILE_REQUIRED'):
            validator.render(self.fx.p(), None, None)

    def test_missing_canonical_receipt_stays_missing_without_fabricating_pass(self):
        self.api()
        self.assertIsNone(self.validator.read_render(self.fx.p(Capability.READ), 'sha256:' + 'a' * 64))
        with self.assertRaisesRegex(ValueError, 'INVALID_DIGEST'):
            self.validator.read_render(self.fx.p(Capability.READ), 'not-a-warrant')

    def test_foreign_owner_cannot_read_even_the_absence_of_a_render_receipt(self):
        self.api()
        other = Fixture(self.root / 'foreign-read.json')
        self.addCleanup(other.close)
        with self.assertRaises(AdmissionError):
            self.validator.read_render(other.p(Capability.READ), 'a' * 64)

    def capsules(self, fixture=None, identity=None):
        fixture = self.fx if fixture is None else fixture
        identity = Identity(ec.generate_private_key(ec.SECP256R1())) if identity is None else identity
        return CorePatchCapsules(fixture.journal, identity, source_probe=lambda: None)

    def forged_record(self, signer):
        warrant = self.fx.warrant
        data = {'schema': 'aioa.trusted-render-validation.v1', 'status': 'PASS', 'authority': 'NONE',
                'profile_digest': 'c' * 64, 'sandbox_profile_digest': 'd' * 64,
                'warrant_digest': warrant.digest(), 'operation_digest': warrant.operation_hash,
                'warrant': warrant.to_dict(), 'evidence_digest': 'e' * 64,
                'oracle': {'status': 'PASS', 'authority': 'NONE', 'recipe_digest': 'c' * 64}}
        data['signature'] = signer.sign(data)
        key = canonical_sha256([data['schema'], warrant.digest()])
        self.fx.journal._run(self.fx.p(), Capability.COMMIT,
                             lambda tx: tx.insert(StoredRecord(RecordKind.OPERATION, key,
                                                              self.fx.ledger.scope, 1, data)))
        return warrant.digest()

    def test_a_second_core_cannot_supply_render_signing_or_receipt_authority(self):
        self.api()
        other = Fixture(self.root / 'foreign-signing.json')
        self.addCleanup(other.close)
        with self.assertRaisesRegex(ValueError, 'RENDER_CAPSULE_BINDING_REQUIRED'):
            repair_validation.CoreSandboxValidation(
                self.fx.journal, lambda *_: self.fail('dispatch'), render_capsules=self.capsules(other))

    def test_public_readback_rejects_a_pass_signed_by_an_unbound_identity(self):
        self.api()
        capsules = self.capsules()
        validator = repair_validation.CoreSandboxValidation(
            self.fx.journal, lambda *_: self.fail('dispatch'), render_capsules=capsules)
        foreign = Identity(ec.generate_private_key(ec.SECP256R1()))
        warrant_digest = self.forged_record(foreign)
        with self.assertRaises(MemoryPatchError) as failure:
            validator.read_render(self.fx.p(Capability.READ), warrant_digest)
        self.assertEqual(failure.exception.code, 'TRANSACTION_FAILED')

    def test_even_a_trusted_signature_cannot_replace_missing_canonical_broker_resolution(self):
        self.api()
        capsules = self.capsules()
        validator = repair_validation.CoreSandboxValidation(
            self.fx.journal, lambda *_: self.fail('dispatch'), render_capsules=capsules)
        warrant_digest = self.forged_record(capsules.identity)
        with self.assertRaises(MemoryPatchError) as failure:
            validator.read_render(self.fx.p(Capability.READ), warrant_digest)
        self.assertEqual(failure.exception.code, 'TRANSACTION_FAILED')
