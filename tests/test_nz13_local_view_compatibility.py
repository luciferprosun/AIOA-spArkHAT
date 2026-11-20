"""Portable DTO compatibility without introducing a server or approval path."""
import unittest

from pydantic import ValidationError

from runtime.nonzero_cloudops import contract, views


class LocalViewCompatibilityTests(unittest.TestCase):
    def browser(self, **values):
        cls = getattr(views, 'LocalBrowserSessionView', None)
        self.assertTrue(callable(cls), 'Missing non-secret browser session DTO')
        return cls(**values)

    def test_legacy_request_names_are_aliases_of_the_existing_core_requests(self):
        self.assertIs(getattr(views, 'LocalStartRunRequest', None), views.StartRunRequest)
        self.assertIs(getattr(views, 'LocalResumeRequest', None), views.ResumeRequest)

    def test_legacy_body_limit_uses_the_shared_dependency_free_contract(self):
        self.assertEqual(16_384, views.LOCAL_API_BODY_MAX_BYTES)
        self.assertEqual(contract.LOCAL_API_BODY_MAX_BYTES, views.LOCAL_API_BODY_MAX_BYTES)

    def test_browser_session_view_has_only_two_non_secret_fields(self):
        value = self.browser(authenticated=True, storage='http_only_session_cookie')
        self.assertEqual({'authenticated': True, 'storage': 'http_only_session_cookie'}, value.model_dump())
        self.assertEqual({'authenticated': False, 'storage': None}, self.browser(authenticated=False).model_dump())

    def test_browser_authentication_and_storage_must_agree(self):
        self.assertTrue(callable(getattr(views, 'LocalBrowserSessionView', None)))
        for values in ({'authenticated': True}, {'authenticated': False, 'storage': 'http_only_session_cookie'}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self.browser(**values)

    def test_browser_dto_never_coerces_text_flags_or_accepts_cookie_material(self):
        self.assertTrue(callable(getattr(views, 'LocalBrowserSessionView', None)))
        for values in ({'authenticated': 'true', 'storage': 'http_only_session_cookie'},
                       {'authenticated': 1, 'storage': 'http_only_session_cookie'},
                       {'authenticated': True, 'storage': 'http_only_session_cookie', 'cookie': 'SYNTHETIC_NOT_A_SECRET'}):
            with self.subTest(keys=list(values)), self.assertRaises(ValidationError):
                self.browser(**values)

    def test_public_error_dto_rejects_provider_payload_or_credential_as_failure_code(self):
        for code in ('Bearer ' + 'a' * 40, 'ghp_' + 'A' * 40, 'Traceback: /home/owner/private.py'):
            with self.subTest(kind=code.split()[0]), self.assertRaises(ValidationError):
                views.LocalApiErrorResponse(error=views.LocalApiErrorCode.INTERNAL_ERROR, failure_code=code)

    def test_error_code_and_existing_explicit_execution_gesture_remain_closed(self):
        self.assertIs(getattr(views, 'LocalResumeRequest', None), views.ResumeRequest)
        value = views.LocalApiErrorResponse(error=views.LocalApiErrorCode.POLICY_DENIED,
                                           failure_code='OWNER_APPROVAL_REQUIRED')
        self.assertEqual('OWNER_APPROVAL_REQUIRED', value.failure_code)
        self.assertFalse(value.ok)
        self.assertFalse(value.retryable)
        for value in (False, 'true', 1):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                views.LocalResumeRequest(confirm_execution=value)
