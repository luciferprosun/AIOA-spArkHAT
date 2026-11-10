"""Primitive identities cannot be replaced by Python equality callbacks.

The small invalid payload is never parsed. Exact rejection codes distinguish
the identity fence from a later byte/hash failure; real pinned bytes belong to
the separate inert public-wheel acceptance.
"""
import importlib
import unittest


class EqualityMasquerade(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


class FrameworkWheelTypeTests(unittest.TestCase):
    def values(self):
        return {'distribution': 'pytest', 'version': '9.2.0',
                'filename': 'pytest-9.2.0-py3-none-any.whl',
                'sha256': '07acdcf88ec174f907dc01af70bf52d49b014bbab03faeeade31c96b18c2e588',
                'content': b'inert invalid payload; archive parser must not run'}

    def reject_identity(self, field):
        module = importlib.import_module('runtime.mission.dependency_lock')
        self.assertTrue(hasattr(module, 'FrameworkWheel'))
        for raw in ('different underlying serialized text', self.values()[field]):
            values = self.values()
            values[field] = EqualityMasquerade(raw)
            with self.subTest(field=field, raw=raw), \
                    self.assertRaisesRegex(ValueError, '^FRAMEWORK_PIN_MISMATCH$'):
                module.FrameworkWheel(**values)

    def test_version_is_an_exact_primitive_before_byte_validation(self):
        self.reject_identity('version')

    def test_filename_is_an_exact_primitive_before_byte_validation(self):
        self.reject_identity('filename')

    def test_digest_is_an_exact_primitive_before_byte_validation(self):
        self.reject_identity('sha256')

    def test_ordinary_approved_identities_reach_the_separate_byte_fence(self):
        module = importlib.import_module('runtime.mission.dependency_lock')
        self.assertTrue(hasattr(module, 'FrameworkWheel'))
        with self.assertRaisesRegex(ValueError, '^FRAMEWORK_BYTES_MISMATCH$'):
            module.FrameworkWheel(**self.values())
