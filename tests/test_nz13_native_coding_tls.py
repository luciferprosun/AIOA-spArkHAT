"""Causal Native transport seam; generic mobile must never issue coding authority."""
from nz13_native_coding_support import NativeCompletionCase, require_parameter

from runtime.webapp import WebRuntimeService


class NativeCodingTLSTests(NativeCompletionCase):
    def test_conditional_coding_entry_uses_native_session_authority(self):
        require_parameter(self, WebRuntimeService, "native_access",
                          "NATIVE_COOKIE_TLS_CODING_ENTRY_BINDING_MISSING")

    def test_exact_route_set_rejects_generic_mobile_plain_session_and_traversal(self):
        from runtime.webapp import _native_coding_route
        self.assertTrue(_native_coding_route('GET', '/coding'))
        self.assertTrue(_native_coding_route('GET', '/api/agent/coding/tasks/task-1'))
        self.assertTrue(_native_coding_route('POST', '/api/agent/coding/start'))
        for method, path in (('GET', '/api/session'), ('GET', '/devices'),
                ('POST', '/api/mobile/v2/run'), ('POST', '/api/native-operator/execution_capacity_apply'),
                ('GET', '/api/agent/coding/tasks/../foreign'), ('GET', '/api/agent/coding/runtime?run=1'),
                ('POST', '/api/agent/coding/start/extra'), ('GET', '/api/agent/coding/start')):
            with self.subTest(method=method, path=path):
                self.assertFalse(_native_coding_route(method, path))

    def test_explicit_service_never_falls_back_to_global_runtime(self):
        from unittest.mock import patch
        from runtime import webapp
        handler = object.__new__(webapp.AOIAWebHandler)
        handler.runtime_service = False
        with patch.object(webapp, 'get_service', side_effect=AssertionError('AMBIENT_RUNTIME_FALLBACK')):
            self.assertIs(False, handler._service())

    def test_native_access_rejects_absent_runtime_before_default_construction(self):
        from unittest.mock import patch
        from runtime import webapp
        with patch.object(webapp, 'create_runtime', side_effect=AssertionError('DEFAULT_RUNTIME_CONSTRUCTED')):
            with self.assertRaises(ValueError):
                WebRuntimeService(native_access=object())
