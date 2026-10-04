import unittest
from datetime import datetime, timezone, timedelta
from dataclasses import FrozenInstanceError


class EvidenceTests(unittest.TestCase):
    def api(self):
        from lab.archaioa.evidence import EvidenceRef
        from lab.archaioa.contracts import ContractValidationError
        return EvidenceRef, ContractValidationError

    def test_evidence_roundtrip_and_immutable(self):
        EvidenceRef, _ = self.api()
        ref = EvidenceRef('e1', 'fixture', 'sha256:' + 'a' * 64, 'r1')
        self.assertEqual(EvidenceRef.from_dict(ref.to_dict()), ref)
        self.assertEqual(EvidenceRef.from_json(ref.to_json()), ref)
        self.assertEqual(hash(ref), hash(EvidenceRef.from_json(ref.to_json())))
        with self.assertRaises(FrozenInstanceError):
            ref.digest = 'sha256:' + 'b' * 64

    def test_evidence_rejects_bad_ids_and_digests(self):
        EvidenceRef, Error = self.api()
        valid = dict(evidence_id='e1', kind='fixture', digest='sha256:' + 'a' * 64, source_version='r1')
        for field in valid:
            for bad in ('', ' ', None, 12):
                with self.subTest(field=field, bad=bad), self.assertRaises(Error):
                    EvidenceRef(**(valid | {field: bad}))
        for bad in ('a' * 64, 'sha256:ABC', 'sha256:' + 'A' * 64, 'md5:' + 'a' * 32):
            with self.subTest(bad=bad), self.assertRaises(Error):
                EvidenceRef(**(valid | {'digest': bad}))

    def test_evidence_time_is_utc_only(self):
        EvidenceRef, Error = self.api()
        for bad in (datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))):
            with self.subTest(bad=bad), self.assertRaises(Error):
                EvidenceRef('e1', 'fixture', 'sha256:' + 'a' * 64, 'r1', valid_time=bad)
        value = EvidenceRef('e1', 'fixture', 'sha256:' + 'a' * 64, 'r1', valid_time=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(value.to_dict()['valid_time'], '2026-01-01T00:00:00.000000Z')

    def test_wire_rejects_unknown_missing_and_versions(self):
        EvidenceRef, Error = self.api()
        ref = EvidenceRef('e1', 'fixture', 'sha256:' + 'a' * 64, 'r1')
        wire = ref.to_dict()
        cases = [wire | {'payload': 'raw'}, wire | {'schema_version': 2}, wire | {'schema_version': True}, wire | {'contract_type': 'Unknown'}]
        for field in wire:
            cases.append({k: v for k, v in wire.items() if k != field})
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(Error):
                EvidenceRef.from_dict(bad)

    def test_errors_are_typed_and_do_not_echo_input(self):
        EvidenceRef, Error = self.api()
        with self.assertRaises(Error) as caught:
            EvidenceRef(' fixture-sensitive-text ', 'fixture', 'bad', 'r1')
        self.assertNotIn('fixture-sensitive-text', str(caught.exception))
        self.assertTrue(caught.exception.code)
        self.assertTrue(caught.exception.field)


class BundleTests(unittest.TestCase):
    def bundle(self):
        from lab.archaioa.fixtures import contract_bundle
        return contract_bundle()

    def test_fixture_bundle_references_compose_and_roundtrip(self):
        bundle = self.bundle()
        self.assertEqual(bundle.warrant.decision_dependency_root, bundle.decision_root)
        self.assertEqual(bundle.outcome.liability_id, bundle.liability.liability_id)
        self.assertEqual(bundle.warrant.task_id, bundle.liability.task_id)
        self.assertEqual(type(bundle).from_json(bundle.to_json()), bundle)
        for contract in (bundle, bundle.warrant, bundle.liability, bundle.decision_root, bundle.warrant.authority_scope, bundle.warrant.authority_scope.monetary_ceiling, bundle.outcome, *bundle.evidence_refs):
            with self.subTest(contract=type(contract).__name__):
                clone = type(contract).from_json(contract.to_json())
                self.assertEqual(clone, contract)
                self.assertEqual(clone.contract_digest(), contract.contract_digest())
                self.assertEqual(hash(clone), hash(contract))

    def test_every_contract_rejects_unknown_fields_and_versions(self):
        from lab.archaioa.contracts import ContractValidationError
        bundle = self.bundle()
        for contract in (bundle, bundle.warrant, bundle.liability, bundle.decision_root, bundle.warrant.authority_scope, bundle.warrant.authority_scope.monetary_ceiling, bundle.outcome, *bundle.evidence_refs):
            for extra in ({'unknown': 'fixture'}, {'schema_version': 2}, {'schema_version': True}):
                with self.subTest(contract=type(contract).__name__, extra=extra), self.assertRaises(ContractValidationError):
                    type(contract).from_dict(contract.to_dict() | extra)

    def test_bundle_rejects_inconsistent_cross_references(self):
        from dataclasses import replace
        from lab.archaioa.contracts import ContractValidationError
        from lab.archaioa.outcome import Unknown
        bundle = self.bundle()
        for changes in ({'outcome': Unknown('unrelated-liability')}, {'liability': replace(bundle.liability, task_id='other')}, {'decision_root': type(bundle.decision_root)(())}):
            with self.subTest(changes=changes), self.assertRaises(ContractValidationError):
                replace(bundle, **changes)

    def test_public_import_is_standalone_and_no_runtime_modules_loaded(self):
        import os
        import subprocess
        import sys
        from pathlib import Path
        root = str(Path(__file__).resolve().parents[2])
        code = '''
import sys
class BlockRuntime:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "runtime" or fullname.startswith("runtime."):
            raise AssertionError("production runtime import attempted")
sys.meta_path.insert(0, BlockRuntime())
from lab.archaioa import EffectWarrant, LiabilityRecord, Unknown
from lab.archaioa.fixtures import contract_bundle
value = contract_bundle()
assert type(value).from_json(value.to_json()) == value
assert not any(name == "runtime" or name.startswith("runtime.") for name in sys.modules)
print(value.contract_digest())
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], env={'PATH': os.defpath, 'PYTHONPATH': root}, cwd=root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith('sha256:'))

    def test_digests_are_independent_of_process_hash_seed(self):
        import os
        import subprocess
        import sys
        from pathlib import Path
        root = str(Path(__file__).resolve().parents[2])
        code = 'from lab.archaioa.fixtures import contract_bundle; print(contract_bundle().to_json()); print(contract_bundle().contract_digest())'
        outputs = []
        for seed in ('1', '98765'):
            result = subprocess.run([sys.executable, '-B', '-c', code], env={'PATH': os.defpath, 'PYTHONPATH': root, 'PYTHONHASHSEED': seed}, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(result.stdout)
        self.assertEqual(outputs[0], outputs[1])

    def test_hash_values_are_stable_across_process_seeds(self):
        import os
        import subprocess
        import sys
        from pathlib import Path
        root = str(Path(__file__).resolve().parents[2])
        code = '''
from lab.archaioa.fixtures import contract_bundle
from lab.archaioa import Applied, NotApplied
b = contract_bundle()
values = (b, b.warrant, b.liability, b.decision_root, b.outcome, *b.evidence_refs,
          b.warrant.authority_scope, b.warrant.authority_scope.monetary_ceiling,
          Applied("receipt-1"), NotApplied())
print([hash(value) for value in values])
'''
        outputs = []
        for seed in ('1', '98765'):
            result = subprocess.run([sys.executable, '-B', '-c', code], env={'PATH': os.defpath, 'PYTHONPATH': root, 'PYTHONHASHSEED': seed}, cwd=root, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(result.stdout)
        self.assertEqual(outputs[0], outputs[1])

    def test_mutable_tzinfo_cannot_change_existing_contracts(self):
        from datetime import tzinfo
        from dataclasses import replace
        class MutableUTC(tzinfo):
            offset = timedelta(0)
            def utcoffset(self, dt):
                return self.offset
            def dst(self, dt):
                return timedelta(0)
        zone = MutableUTC()
        time = datetime(2026, 10, 4, tzinfo=zone)
        b = self.bundle()
        values = (
            replace(b.evidence_refs[0], valid_time=time, transaction_time=time),
            replace(b.warrant.authority_scope, not_before=time),
            replace(b.warrant, issued_at=time),
            replace(b.liability, opened_at=time),
        )
        before = [value.contract_digest() for value in values]
        zone.offset = timedelta(hours=1)
        self.assertEqual([value.contract_digest() for value in values], before)
        for value in values:
            for name in value.TIME_FIELDS + value.OPTIONAL_TIME_FIELDS:
                if getattr(value, name) is not None:
                    self.assertIs(getattr(value, name).tzinfo, timezone.utc)

    def test_constructor_rejects_non_utf8_identifiers(self):
        from lab.archaioa import EvidenceRef, ContractValidationError
        valid = dict(evidence_id='e1', kind='fixture', digest='sha256:' + 'a' * 64, source_version='r1')
        for field in ('evidence_id', 'kind', 'source_version'):
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                EvidenceRef(**(valid | {field: '\ud800'}))
