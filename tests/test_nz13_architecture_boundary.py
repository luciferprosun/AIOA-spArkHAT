"""The exact HTTP failure boundary does not enable NonZero public effects."""
import ast
import tempfile
import unittest
from pathlib import Path

import nonzero_cloudops
from tools.nonzero_architecture import verify_ownership

FILES = ('main.py', 'commands/local_commands.py', 'webapp.py',
         'nonzero_cloudops/provenance.py', 'nonzero_cloudops/service.py',
         'nonzero_cloudops/execution.py')
CONTEXT = "with failure_boundary('HTTP_CALLBACK_FAILED', preserve=(NonZeroError,)):"


class ExactHttpBoundaryArchitectureTests(unittest.TestCase):
    def inspect(self, transform):
        source = Path(nonzero_cloudops.__file__).parent.parent
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in FILES:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((source / name).read_bytes())
            web = root / 'webapp.py'
            text = web.read_text()
            self.assertIn(CONTEXT, text)
            changed = transform(text)
            ast.parse(changed)
            web.write_text(changed)
            return verify_ownership(root)

    def denied(self, transform):
        self.assertEqual([], self.inspect(lambda text: text), 'positive control must pass before mutation')
        self.assertIn('NONZERO_PUBLIC_DISPATCH_NOT_DISABLED',
                      {finding['code'] for finding in self.inspect(transform)})

    def test_current_exact_wrapper_keeps_status_read_and_effect_denial(self):
        self.assertEqual([], self.inspect(lambda text: text))

    def test_plain_historical_handler_remains_supported(self):
        def remove_wrapper(text):
            tree = ast.parse(text)
            handler = next(node for node in ast.walk(tree)
                           if isinstance(node, ast.FunctionDef) and node.name == '_handle_nonzero')
            wrapper = next(node for node in ast.walk(handler) if isinstance(node, ast.With))
            lines = text.splitlines(keepends=True)
            lines[wrapper.lineno - 1:wrapper.end_lineno] = [
                line[4:] for line in lines[wrapper.lineno:wrapper.end_lineno]]
            return ''.join(lines)
        self.assertEqual([], self.inspect(remove_wrapper))

    def test_restored_effect_dispatch_inside_wrapper_is_denied(self):
        self.denied(lambda text: text.replace(CONTEXT, CONTEXT +
            '\n                self._service().runtime.nonzero_cloudops.request(method, parsed.path, payload, operator=True)'))

    def test_missing_effect_denial_is_rejected_with_exact_wrapper(self):
        self.assertEqual([], self.inspect(lambda text: text))
        findings = self.inspect(lambda text: text.replace('UNSUPPORTED_EFFECT_ROUTE', 'WRONG_STATE'))
        self.assertIn('NONZERO_PUBLIC_DENIAL_MISSING', {finding['code'] for finding in findings})

    def test_different_boundary_error_code_is_denied(self):
        self.denied(lambda text: text.replace(CONTEXT, CONTEXT.replace('HTTP_CALLBACK_FAILED', 'OTHER_FAILURE')))

    def test_dynamic_boundary_error_code_is_denied(self):
        self.denied(lambda text: text.replace(CONTEXT, "with failure_boundary(payload, preserve=(NonZeroError,)):"))

    def test_preserved_exception_shape_is_closed(self):
        for preserve in ('(Exception,)', '(NonZeroError, ValueError)', 'errors', '[NonZeroError]', '(NonZeroError, NonZeroError)'):
            with self.subTest(preserve=preserve):
                self.denied(lambda text, preserve=preserve: text.replace(CONTEXT, f"with failure_boundary('HTTP_CALLBACK_FAILED', preserve={preserve}):"))

    def test_extra_keyword_is_denied(self):
        self.denied(lambda text: text.replace(CONTEXT, "with failure_boundary('HTTP_CALLBACK_FAILED', preserve=(NonZeroError,), extra=True):"))

    def test_keyword_expansion_is_denied(self):
        self.denied(lambda text: text.replace(CONTEXT, "with failure_boundary('HTTP_CALLBACK_FAILED', preserve=(NonZeroError,), **payload):"))

    def test_context_value_binding_is_denied(self):
        self.denied(lambda text: text.replace(CONTEXT, CONTEXT[:-1] + ' as handle:'))

    def test_same_named_call_outside_context_is_denied(self):
        self.denied(lambda text: text.replace(CONTEXT, "failure_boundary('HTTP_CALLBACK_FAILED', preserve=(NonZeroError,))\n            " + CONTEXT))

    def test_duplicate_exact_context_is_denied(self):
        self.denied(lambda text: text.replace(CONTEXT, CONTEXT + '\n                ' + CONTEXT + '\n                    pass'))

    def test_noncanonical_import_is_denied(self):
        self.denied(lambda text: text.replace('from runtime.failure_boundary import (', 'from replacement_boundary import ('))

    def test_local_rebinding_is_denied(self):
        self.denied(lambda text: text.replace("        from nonzero_cloudops import NonZeroError\n",
            "        from nonzero_cloudops import NonZeroError\n        failure_boundary = payload\n"))

    def test_module_rebinding_is_denied(self):
        self.denied(lambda text: text + '\nfailure_boundary = replacement\n')

    def test_parameter_shadowing_is_denied(self):
        self.denied(lambda text: text.replace('def _handle_nonzero(self, method, parsed, payload):',
            'def _handle_nonzero(self, method, parsed, payload, failure_boundary=None):'))

    def test_function_rebinding_is_denied(self):
        self.denied(lambda text: text + '\ndef failure_boundary(*args, **kwargs):\n    return replacement\n')

    def test_effect_hidden_in_exception_handler_is_denied(self):
        self.denied(lambda text: text.replace('        except NonZeroError as error:\n',
            '        except NonZeroError as error:\n            self._service().runtime.nonzero_cloudops.request(method, parsed.path, payload, operator=True)\n'))

    def test_attribute_boundary_callee_is_denied(self):
        self.denied(lambda text: text.replace(CONTEXT, "with adapter.failure_boundary('HTTP_CALLBACK_FAILED', preserve=(NonZeroError,)):"))

    def test_preserved_exception_import_must_be_canonical(self):
        self.denied(lambda text: text.replace('        from nonzero_cloudops import NonZeroError\n',
            '        from replacement_errors import NonZeroError\n'))


if __name__ == '__main__':
    unittest.main()
