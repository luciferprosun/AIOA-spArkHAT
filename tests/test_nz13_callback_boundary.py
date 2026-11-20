"""Typed UI callback boundaries preserve legacy denials and process signals."""
import inspect
import unittest

from runtime import failure_boundary as boundary


class DomainDenial(RuntimeError):
    pass


class ForeignFailure(Exception):
    pass


class CallbackBoundaryTests(unittest.TestCase):
    def context(self, *, preserve=()):
        self.assertIn('preserve', inspect.signature(boundary.failure_boundary).parameters,
                      'Missing explicit typed callback-denial preservation')
        return boundary.failure_boundary('CALLBACK_FAILED', preserve=preserve)

    def cause(self, error):
        method = getattr(boundary, 'boundary_cause', None)
        self.assertTrue(callable(method), 'Missing local legacy error-identity adapter')
        return method(error)

    def test_default_typed_value_error_keeps_identity(self):
        error = ValueError('KNOWN_DENIAL')
        with self.assertRaises(ValueError) as failed, boundary.failure_boundary('CALLBACK_FAILED'):
            raise error
        self.assertIs(error, failed.exception)

    def test_explicit_domain_denial_keeps_its_original_type_and_identity(self):
        context = self.context(preserve=(DomainDenial,))
        error = DomainDenial('EXACT_DOMAIN_DENIED')
        with self.assertRaises(DomainDenial) as failed, context:
            raise error
        self.assertIs(error, failed.exception)

    def test_unknown_foreign_exception_has_fixed_public_code_and_original_local_cause(self):
        context = self.context(preserve=(DomainDenial,))
        original = ForeignFailure('synthetic private callback detail')
        with self.assertRaises(boundary.RepairBoundaryError) as failed, context:
            raise original
        self.assertEqual('CALLBACK_FAILED', str(failed.exception))
        self.assertIs(original, self.cause(failed.exception))

    def test_process_signals_are_never_wrapped_or_swallowed(self):
        for error in (KeyboardInterrupt(), SystemExit(7), GeneratorExit()):
            with self.subTest(kind=type(error).__name__):
                context = self.context()
                with self.assertRaises(type(error)) as failed, context:
                    raise error
                self.assertIs(error, failed.exception)

    def test_invalid_or_catch_all_preservation_is_denied_before_the_callback(self):
        for preserve in ([], 'all', (Exception,), (BaseException,), (KeyboardInterrupt,),
                         ('ValueError',), tuple([DomainDenial] * 9)):
            with self.subTest(kind=type(preserve).__name__):
                context = self.context(preserve=preserve)
                entered = False
                with self.assertRaises(ValueError), context:
                    entered = True
                self.assertFalse(entered)

    def test_unwrapped_and_nested_callback_errors_keep_legacy_error_identity(self):
        original = ValueError('KNOWN_PUBLIC_CODE')
        self.assertIs(original, self.cause(original))
        wrapper = boundary.RepairBoundaryError('INNER_CALLBACK_FAILED')
        wrapper.__cause__ = original
        with self.assertRaises(boundary.RepairBoundaryError) as failed, self.context():
            raise wrapper
        self.assertIs(wrapper, self.cause(failed.exception))
