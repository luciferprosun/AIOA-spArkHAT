import unittest
from decimal import Decimal
from datetime import datetime, timezone


class CanonicalTests(unittest.TestCase):
    def api(self):
        from lab.archaioa.canonical import canonical_json, canonical_digest, parse_json
        from lab.archaioa.contracts import ContractValidationError
        return canonical_json, canonical_digest, parse_json, ContractValidationError

    def test_json_is_compact_sorted_and_utf8(self):
        canonical_json, _, _, _ = self.api()
        self.assertEqual(canonical_json({'z': ('ą', 2), 'a': Decimal('12.3400')}), '{"a":"12.34","z":["ą",2]}')
        self.assertEqual(canonical_json({'b': 2, 'a': 1}), canonical_json({'a': 1, 'b': 2}))
        self.assertEqual(canonical_json(Decimal('-0.000')), '"0"')

    def test_known_digest_vector_and_domain_separation(self):
        _, digest, _, _ = self.api()
        # Independently precomputed from b'PCAF/Vector/v1\0{"a":1,"b":2}'.
        self.assertEqual(digest('PCAF/Vector/v1', {'b': 2, 'a': 1}), 'sha256:e01c8d05fcbc7af7e1fc29e3a3d33b8605cb413a7533754895b8b9973a5ec5ad')
        self.assertNotEqual(digest('PCAF/Vector/v1', {}), digest('PCAF/Other/v1', {}))

    def test_rejects_floats_nonfinite_decimal_naive_time_and_bad_keys(self):
        canonical_json, _, _, Error = self.api()
        for value in (1.2, float('nan'), Decimal('NaN'), Decimal('Infinity'), datetime(2026, 1, 1), {1: 'x'}, object()):
            with self.subTest(type=type(value).__name__), self.assertRaises(Error):
                canonical_json(value)
        self.assertEqual(canonical_json(datetime(2026, 1, 1, tzinfo=timezone.utc)), '"2026-01-01T00:00:00.000000Z"')

    def test_json_parser_rejects_duplicates_floats_and_constants(self):
        _, _, parse_json, Error = self.api()
        for raw in ('{"a":1,"a":2}', '{"a":1.2}', '{"a":NaN}', '{broken', '[Infinity]'):
            with self.subTest(raw=raw), self.assertRaises(Error):
                parse_json(raw)

    def test_domain_is_explicit_and_nonblank(self):
        _, digest, _, Error = self.api()
        for bad in ('', None, 'abc\x00def'):
            with self.subTest(bad=bad), self.assertRaises(Error):
                digest(bad, {})

    def test_fixed_contract_vectors_match_independent_wire_payloads(self):
        import json
        from pathlib import Path
        from lab.archaioa.fixtures import contract_bundle
        bundle = contract_bundle()
        vectors = json.loads(Path(__file__).with_name('vectors.json').read_text())
        for key, contract in (('warrant', bundle.warrant), ('liability', bundle.liability), ('decision_root', bundle.decision_root)):
            with self.subTest(contract=key):
                self.assertEqual(contract.to_json(), vectors[key]['canonical_json'])
                self.assertEqual(contract.contract_digest(), vectors[key]['digest'])

    def test_malformed_extremes_always_raise_typed_errors(self):
        canonical_json, digest, parse_json, Error = self.api()
        cycle = []
        cycle.append(cycle)
        cases = (
            lambda: parse_json('{"n":' + '1' * 5000 + '}'),
            lambda: canonical_json(parse_json('[' * 2000 + '0' + ']' * 2000)),
            lambda: canonical_json({'\ud800': 1}),
            lambda: canonical_json({'a': '\ud800'}),
            lambda: digest('\ud800', {}),
            lambda: canonical_json(cycle),
        )
        for index, operation in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(Error):
                operation()
