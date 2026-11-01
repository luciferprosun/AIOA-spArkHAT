"""Neutral MobileMissionV1 wire, ephemeral test identities only."""
import importlib
import importlib.util
import json
import unittest
from cryptography.hazmat.primitives.asymmetric import ec


class MobileWireTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mobile_gateway'), 'mobile typed port missing')
        self.wire=importlib.import_module('runtime.mobile_gateway.wire')

    def test_utf8_canonical_body_hash_has_no_floats_or_duplicate_keys(self):
        encoded=self.wire.canonical({'z':'Zażółć / \n','a':1})
        self.assertEqual(b'{"a":1,"z":"Za\xc5\xbc\xc3\xb3\xc5\x82\xc4\x87 / \\n"}',encoded)
        self.assertEqual({'a':1,'z':'Zażółć / \n'},self.wire.strict_json(encoded))
        for raw in [b'{"x":1,"x":2}',b'{"x":1.0}',b'{"x":NaN}',b'[]']:
            with self.subTest(raw=raw),self.assertRaises(self.wire.MobileError):self.wire.strict_json(raw)

    def test_body_bound_and_nesting_fail_closed(self):
        with self.assertRaises(self.wire.MobileError):self.wire.strict_json(b'x'*16385)
        with self.assertRaises(self.wire.MobileError):self.wire.strict_json(b'{"x":'*20+b'0'+b'}'*20)

    def test_der_p256_signatures_verify_and_reject_another_key(self):
        key=ec.generate_private_key(ec.SECP256R1());other=ec.generate_private_key(ec.SECP256R1())
        identity=self.wire.Identity(key)
        proof={'schema':'test','nonce':'a'*32}
        signature=identity.sign(proof)
        self.wire.verify(identity.spki,signature,proof)
        with self.assertRaises(self.wire.MobileError):self.wire.verify(self.wire.Identity(other).spki,signature,proof)

    def test_only_p256_and_canonical_base64_are_accepted(self):
        key=ec.generate_private_key(ec.SECP384R1())
        from cryptography.hazmat.primitives import serialization
        import base64
        encoded=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.DER,
                               serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        with self.assertRaises(self.wire.MobileError):self.wire.public_key(encoded)
        with self.assertRaises(self.wire.MobileError):self.wire.public_key('not base64')

    def test_https_origin_is_exact_and_cannot_carry_path_or_credentials(self):
        self.assertEqual('https://fixture.invalid',self.wire.origin('https://fixture.invalid'))
        for value in ['http://fixture.invalid','https://u:p@fixture.invalid','https://fixture.invalid/',
                      'https://fixture.invalid:443','https://127.0.0.1','https://fixture.invalid/?token=x',
                      'https://fixture.invalid#x','https://ф.example']:
            with self.subTest(value=value),self.assertRaises(self.wire.MobileError):self.wire.origin(value)

    def test_routes_are_closed_and_ids_are_opaque(self):
        self.assertEqual(('evidence','meta-'+'a'*32),self.wire.route('GET','/api/mobile/v1/evidence/meta-'+'a'*32))
        for method,path in [('GET','/api/mobile/v1/status?owner=x'),('GET','/api/mobile/v1/tasks/../x'),
            ('POST','/api/mobile/v1/owner/approve'),('GET','https://evil.example/api/mobile/v1/status')]:
            with self.subTest(path=path),self.assertRaises(self.wire.MobileError):self.wire.route(method,path)

    def test_request_proof_binds_exact_method_path_body_and_source(self):
        proof=self.wire.request_proof('POST','/api/mobile/v1/stop',b'{"task_id":"x"}',
            token='fixture-token',nonce='a'*32,issued_at=10,audience='b'*64,source_sha='c'*40,capsule_digest='d'*64)
        self.assertEqual('aioa.mobile.request-proof.v1',proof['schema'])
        self.assertEqual('c'*40,proof['source_sha'])
        self.assertNotIn('fixture-token',json.dumps(proof))
        changed=self.wire.request_proof('POST','/api/mobile/v1/stop',b'{ "task_id":"x"}',
            token='fixture-token',nonce='a'*32,issued_at=10,audience='b'*64,source_sha='c'*40,capsule_digest='d'*64)
        self.assertNotEqual(proof['body_sha256'],changed['body_sha256'])


if __name__=='__main__':unittest.main()
