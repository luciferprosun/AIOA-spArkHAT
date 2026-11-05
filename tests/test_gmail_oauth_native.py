"""Local-only OAuth Desktop/PKCE contracts; synthetic data, zero network."""

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit, quote
import unittest
from unittest.mock import patch

from runtime.communication.gmail.oauth_native import (
    GmailOAuthError, SEND_SCOPE, DesktopOAuthClient,
    parse_desktop_client_json, new_oauth_session,
)

GOOD_ID = "123456789-synthetic.apps.googleusercontent.com"
GOOD_JSON = {
    "installed": {
        "client_id": GOOD_ID, "project_id": "synthetic",
        "client_secret": "SYNTHETIC_DO_NOT_USE",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}


class GmailDesktopOAuthOfflineTests(unittest.TestCase):
    def client(self):
        return parse_desktop_client_json(json.dumps(GOOD_JSON).encode("utf-8"))

    def session(self):
        return new_oauth_session(self.client(), 47651)

    def callback(self, session, *, state=None, code="4/synthetic-oauth-code", **extra):
        parts = {
            "state": session._state if state is None else state, "code": code,
            "scope": SEND_SCOPE, **extra
        }
        from urllib.parse import urlencode
        return session.redirect_uri + "?" + urlencode(parts)

    def test_desktop_json_reads_public_id_and_ignores_secret(self):
        client = self.client()
        self.assertEqual(client.client_id, GOOD_ID)
        self.assertNotIn("SYNTHETIC_DO_NOT_USE", repr(client))
        self.assertNotIn("client_secret", repr(client))

    def test_wrong_web_and_api_key_json_are_not_desktop_oauth(self):
        for payload in ({"web": GOOD_JSON["installed"]}, {"api_key": "fake-gemini"}):
            with self.subTest(payload=list(payload)), self.assertRaises(GmailOAuthError):
                parse_desktop_client_json(json.dumps(payload).encode())

    def test_unknown_google_hosts_or_redirects_fail_closed(self):
        for change in (
            {"auth_uri": "https://evil.example/o/oauth2/auth"},
            {"token_uri": "https://evil.example/token"},
            {"redirect_uris": ["http://evil.example/callback"]},
            {"redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"]},
        ):
            payload = {"installed": {**GOOD_JSON["installed"], **change}}
            with self.subTest(change=change), self.assertRaises(GmailOAuthError):
                parse_desktop_client_json(json.dumps(payload).encode())

    def test_client_config_duplicate_fields_rejected(self):
        raw = ('{"installed":{"client_id":"'+ GOOD_ID +'",'
               '"client_id":"'+GOOD_ID+'",'
               '"auth_uri":"https://accounts.google.com/o/oauth2/auth",'
               '"token_uri":"https://oauth2.googleapis.com/token",'
               '"redirect_uris":["http://localhost"]}}').encode()
        with self.assertRaises(GmailOAuthError):
            parse_desktop_client_json(raw)

    def test_malformed_config_field_types_fail_closed(self):
        for bad in (
            {"auth_uri": {"url": "https://accounts.google.com/o/oauth2/auth"}},
            {"token_uri": []},
            {"redirect_uris": [17]},
        ):
            payload = {"installed": {**GOOD_JSON["installed"], **bad}}
            with self.subTest(bad=bad), self.assertRaises(GmailOAuthError):
                parse_desktop_client_json(json.dumps(payload).encode("utf-8"))

    def test_client_config_never_returns_client_secret(self):
        client = self.client()
        self.assertEqual(tuple(client.__dataclass_fields__), ("client_id",))
        self.assertNotIn("SYNTHETIC_DO_NOT_USE", repr(client))

    def test_default_url_has_only_send_scope_loopback_s256(self):
        session = self.session()
        url = urlsplit(session.authorization_url)
        self.assertEqual(url.scheme, "https")
        self.assertEqual(url.hostname, "accounts.google.com")
        query = parse_qs(url.query)
        self.assertEqual(query["scope"], [SEND_SCOPE])
        self.assertEqual(query["redirect_uri"], ["http://127.0.0.1:47651/oauth2callback"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotIn("client_secret", url.query)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(session._verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        self.assertEqual(query["code_challenge"], [expected])
        self.assertNotEqual(query["code_challenge"], [session._verifier])

    def test_two_sessions_have_independent_random_challenge_and_state(self):
        a, b = self.session(), self.session()
        self.assertNotEqual(a._verifier, b._verifier)
        self.assertNotEqual(a._state, b._state)

    def test_state_and_verifier_never_appear_in_repr(self):
        session = self.session()
        self.assertNotIn(session._verifier, repr(session))
        self.assertNotIn(session._state, repr(session))

    def test_valid_callback_yields_in_memory_ticket_only(self):
        session = self.session()
        original_verifier = session._verifier
        ticket = session.consume_callback(self.callback(session, authuser="0"))
        self.assertEqual(ticket.authorization_code, "4/synthetic-oauth-code")
        self.assertEqual(ticket.code_verifier, original_verifier)
        self.assertIsNone(session._verifier)
        self.assertIsNone(session._state)
        self.assertEqual(ticket.redirect_uri, session.redirect_uri)
        self.assertNotIn(ticket.authorization_code, repr(ticket))
        self.assertNotIn(ticket.code_verifier, repr(ticket))

    def test_replay_of_callback_denied(self):
        session = self.session()
        callback = self.callback(session)
        session.consume_callback(callback)
        with self.assertRaises(GmailOAuthError):
            session.consume_callback(callback)

    def test_cancel_blocks_valid_callback(self):
        session = self.session()
        session.cancel()
        with self.assertRaises(GmailOAuthError):
            session.consume_callback(self.callback(session))

    def test_wrong_state_denied_but_valid_callback_still_possible(self):
        session = self.session()
        with self.assertRaises(GmailOAuthError):
            session.consume_callback(self.callback(session, state="attacker"))
        ticket = session.consume_callback(self.callback(session))
        self.assertEqual(ticket.authorization_code, "4/synthetic-oauth-code")

    def test_extra_scope_in_response_denied(self):
        session = self.session()
        with self.assertRaises(GmailOAuthError):
            session.consume_callback(self.callback(
                session, scope=SEND_SCOPE + " https://www.googleapis.com/auth/gmail.readonly"))

    def test_duplicate_state_code_query_rejected(self):
        for suffix in ("&state=again", "&code=4/extra"):
            session = self.session()
            with self.subTest(suffix=suffix), self.assertRaises(GmailOAuthError):
                session.consume_callback(self.callback(session) + suffix)

    def test_wrong_address_scheme_path_userinfo_and_fragment_denied(self):
        session = self.session()
        callback = self.callback(session)
        for wrong in (
            callback.replace("127.0.0.1", "localhost"),
            callback.replace("http://", "https://", 1),
            callback.replace("/oauth2callback?", "/oauth2callback/extra?"),
            callback.replace("127.0.0.1:", "attacker@127.0.0.1:"),
            callback + "#fragment",
        ):
            with self.subTest(wrong=wrong[:50]), self.assertRaises(GmailOAuthError):
                session.consume_callback(wrong)

    def test_expiry_and_monotonic_rollback_denied(self):
        session = self.session()
        now = session._issued_ns
        with patch("runtime.communication.gmail.oauth_native.time.monotonic_ns",
                   return_value=now-1):
            with self.assertRaises(GmailOAuthError):
                session.consume_callback(self.callback(session))
        with patch("runtime.communication.gmail.oauth_native.time.monotonic_ns",
                   return_value=now+181*10**9):
            with self.assertRaises(GmailOAuthError):
                session.consume_callback(self.callback(session))

    def test_unexpected_callback_fields_denied(self):
        session = self.session()
        with self.assertRaises(GmailOAuthError):
            session.consume_callback(self.callback(session, client_secret="evil"))

    def test_consent_error_is_never_code_and_is_consumed(self):
        session = self.session()
        from urllib.parse import urlencode
        wrong = session.redirect_uri + "?" + urlencode({"state":session._state,"error":"access_denied"})
        with self.assertRaises(GmailOAuthError):
            session.consume_callback(wrong)
        with self.assertRaises(GmailOAuthError):
            session.consume_callback(self.callback(session))

    def test_concurrent_callback_consumed_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        session = self.session()
        callback = self.callback(session)
        barrier = Barrier(2)
        def consume():
            barrier.wait()
            try:
                return session.consume_callback(callback)
            except GmailOAuthError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(consume) for _ in range(2)]
            responses = [future.result(timeout=5) for future in futures]
        self.assertEqual(sum(x is not None for x in responses), 1)

    def test_unpaired_unicode_surrogate_callback_denied(self):
        session = self.session()
        with self.assertRaises(GmailOAuthError):
            session.consume_callback(self.callback(session) + "\ud800")

    def test_malformed_client_secret_is_not_treated_as_ready(self):
        invalid = {"installed": {**GOOD_JSON["installed"], "client_secret": {"oops": True}}}
        with self.assertRaises(GmailOAuthError):
            parse_desktop_client_json(json.dumps(invalid).encode())

    def test_invalid_client_port_and_inputs_denied(self):
        with self.assertRaises(GmailOAuthError):
            DesktopOAuthClient("https://fake.example/")
        for port in (0,80,65536,True,"47651"):
            with self.subTest(port=port), self.assertRaises(GmailOAuthError):
                new_oauth_session(self.client(), port)
        with self.assertRaises(GmailOAuthError):
            parse_desktop_client_json(b"\xff\xfe")
        with self.assertRaises(GmailOAuthError):
            parse_desktop_client_json(b"{" + b"x"*17000 + b"}")

    def test_no_socket_or_google_api_calls_in_offline_flow(self):
        with patch("socket.socket", side_effect=AssertionError("NO_NETWORK_ALLOWED")):
            session = self.session()
            session.consume_callback(self.callback(session))
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
