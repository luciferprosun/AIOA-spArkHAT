"""Inert Google Desktop OAuth + PKCE handshake preparation.

NO network, token exchange, local HTTP listener, credential file I/O, or
approval authority. A successful callback is only a short-lived in-memory
exchange ticket; it does not authorize a Gmail send.

Desktop Google OAuth requires a SYSTEM browser and loopback redirect. Android
is only an operator interface; it never receives PKCE verifier or tokens.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit


SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
CALLBACK_PATH = "/oauth2callback"
CALLBACK_TTL_SECONDS = 180

_CLIENT_ID = re.compile(r"[0-9]+-[A-Za-z0-9_-]{6,}\.apps\.googleusercontent\.com\Z")
_CODE = re.compile(r"[A-Za-z0-9_./~-]{5,2048}\Z")
_DESKTOP_AUTH_URIS = frozenset({
    "https://accounts.google.com/o/oauth2/auth",
    AUTHORIZATION_ENDPOINT,
})
_DESKTOP_REDIRECTS = frozenset({"http://localhost", "http://127.0.0.1"})
_DESKTOP_FIELDS = frozenset({
    "client_id", "client_secret", "project_id", "auth_uri", "token_uri",
    "auth_provider_x509_cert_url", "redirect_uris", "universe_domain",
})
_CALLBACK_KEYS = frozenset({
    "state", "code", "scope", "authuser", "prompt", "iss",
    "error", "error_description",
})


class GmailOAuthError(ValueError):
    """Fixed external denial code; never echoes tokens, codes or config."""

    def __init__(self, code: str = "GMAIL_OAUTH_DENIED") -> None:
        super().__init__(code)


def _require(condition: bool, reason: str = "GMAIL_OAUTH_DENIED") -> None:
    if not condition:
        raise GmailOAuthError(reason)


@dataclass(frozen=True, slots=True, repr=False)
class DesktopOAuthClient:
    """PUBLIC desktop OAuth client ID only, never stores the client secret."""

    client_id: str = field(repr=False)

    def __post_init__(self) -> None:
        _require(type(self.client_id) is str and
                 _CLIENT_ID.fullmatch(self.client_id) is not None,
                 "GMAIL_OAUTH_CLIENT_DENIED")

    def __repr__(self) -> str:
        return "DesktopOAuthClient(<public-id-redacted>)"


def parse_desktop_client_json(raw: bytes) -> DesktopOAuthClient:
    """Inspect a Google desktop client export in RAM; discard its secret.

    Never pass secrets, file contents, or client export to a model, log or Git.
    A Google Gemini API key and OAuth web client are intentionally not valid.
    """
    _require(type(raw) is bytes and 2 <= len(raw) <= 16384,
             "GMAIL_OAUTH_CONFIG_DENIED")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "GMAIL_OAUTH_CONFIG_DENIED")
            result[key] = value
        return result

    def reject_nonfinite(_value):
        raise GmailOAuthError("GMAIL_OAUTH_CONFIG_DENIED")

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                            parse_constant=reject_nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        raise GmailOAuthError("GMAIL_OAUTH_CONFIG_DENIED") from None
    _require(type(parsed) is dict and set(parsed) == {"installed"},
             "GMAIL_OAUTH_CONFIG_DENIED")
    config = parsed["installed"]
    _require(type(config) is dict and
             {"client_id", "auth_uri", "token_uri", "redirect_uris"} <= set(config)
             and set(config) <= _DESKTOP_FIELDS, "GMAIL_OAUTH_CONFIG_DENIED")
    _require(type(config["auth_uri"]) is str and
             type(config["token_uri"]) is str and
             config["auth_uri"] in _DESKTOP_AUTH_URIS and
             config["token_uri"] == TOKEN_ENDPOINT, "GMAIL_OAUTH_CONFIG_DENIED")
    redirects = config["redirect_uris"]
    _require(type(redirects) is list and
             1 <= len(redirects) <= 4 and
             all(type(uri) is str and uri in _DESKTOP_REDIRECTS for uri in redirects),
             "GMAIL_OAUTH_CONFIG_DENIED")
    if "universe_domain" in config:
        _require(config["universe_domain"] == "googleapis.com",
                 "GMAIL_OAUTH_CONFIG_DENIED")
    if "client_secret" in config:
        _require(type(config["client_secret"]) is str and
                 0 < len(config["client_secret"]) <= 4096,
                 "GMAIL_OAUTH_CONFIG_DENIED")
    return DesktopOAuthClient(config["client_id"])


@dataclass(frozen=True, slots=True, repr=False)
class OAuthExchangeTicket:
    """In-memory data for a FUTURE token exchanger, not a Gmail capability."""

    authorization_code: str = field(repr=False)
    code_verifier: str = field(repr=False)
    redirect_uri: str
    client_id: str = field(repr=False)
    scope: str = SEND_SCOPE

    def __repr__(self) -> str:
        return "OAuthExchangeTicket(<redacted>, scope=gmail.send)"


class DesktopOAuthSession:
    """One-use PKCE intent tied to this Linux process and monotonic segment."""

    __slots__ = ("authorization_url", "redirect_uri", "_client_id", "_port",
                 "_state", "_verifier", "_issued_ns", "_lock", "_used")

    def __init__(self, client_id: str, port: int) -> None:
        DesktopOAuthClient(client_id)
        _require(type(port) is int and 1024 <= port <= 65535,
                 "GMAIL_OAUTH_PORT_DENIED")
        self._client_id = client_id
        self._port = port
        self.redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
        self._state = secrets.token_urlsafe(32)
        self._verifier = secrets.token_urlsafe(48)
        _require(43 <= len(self._verifier) <= 128)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self._verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        self._issued_ns = time.monotonic_ns()
        self._lock = threading.Lock()
        self._used = False
        params = {
            "client_id": client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": SEND_SCOPE,
            "state": self._state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
        }
        self.authorization_url = AUTHORIZATION_ENDPOINT + "?" + urlencode(params)

    def __repr__(self) -> str:
        return "DesktopOAuthSession(<secrets-redacted>)"

    def cancel(self) -> None:
        """Cancel locally, no Google API/token revocation occurs here."""
        with self._lock:
            self._used = True
            self._verifier = None
            self._state = None

    def consume_callback(self, callback_url: str) -> OAuthExchangeTicket:
        """Validate exact loopback redirect and one-use state; never exchange tokens."""
        with self._lock:
            _require(not self._used, "GMAIL_OAUTH_REPLAY_DENIED")
            observed = time.monotonic_ns()
            _require(type(observed) is int and
                     self._issued_ns <= observed <
                     self._issued_ns + CALLBACK_TTL_SECONDS * 1_000_000_000,
                     "GMAIL_OAUTH_EXPIRED")
            _require(type(callback_url) is str, "GMAIL_OAUTH_CALLBACK_DENIED")
            try:
                _require(1 <= len(callback_url.encode("utf-8")) <= 4096,
                         "GMAIL_OAUTH_CALLBACK_DENIED")
                url = urlsplit(callback_url)
                _require(url.scheme == "http" and url.netloc ==
                         f"127.0.0.1:{self._port}" and
                         url.path == CALLBACK_PATH and not url.fragment,
                         "GMAIL_OAUTH_CALLBACK_DENIED")
                entries = parse_qsl(url.query, keep_blank_values=True,
                                    strict_parsing=True, encoding="utf-8",
                                    errors="strict", max_num_fields=8)
                result = {}
                for key, value in entries:
                    _require(key in _CALLBACK_KEYS and key not in result and
                             len(value) <= 2048, "GMAIL_OAUTH_CALLBACK_DENIED")
                    result[key] = value
            except (ValueError, UnicodeError, RecursionError):
                raise GmailOAuthError("GMAIL_OAUTH_CALLBACK_DENIED") from None
            _require("state" in result and
                     hmac.compare_digest(result["state"], self._state),
                     "GMAIL_OAUTH_STATE_DENIED")
            if "error" in result:
                self._used = True
                self._verifier = None
                self._state = None
                raise GmailOAuthError("GMAIL_OAUTH_CONSENT_DENIED")
            _require("code" in result and _CODE.fullmatch(result["code"]) is not None,
                     "GMAIL_OAUTH_CODE_DENIED")
            if "scope" in result:
                _require(result["scope"] == SEND_SCOPE, "GMAIL_OAUTH_SCOPE_DENIED")
            if "iss" in result:
                _require(result["iss"] in ("https://accounts.google.com",
                                            "accounts.google.com"),
                         "GMAIL_OAUTH_ISSUER_DENIED")
            ticket = OAuthExchangeTicket(result["code"], self._verifier,
                                         self.redirect_uri, self._client_id)
            self._used = True
            # Release the flow secrets from this session. Ticket remains
            # ephemeral and can be used by an independently audited exchanger.
            self._verifier = None
            self._state = None
            return ticket


def new_oauth_session(client: DesktopOAuthClient, port: int) -> DesktopOAuthSession:
    """Construct an inert client-side authorization request. No browser opens."""
    _require(type(client) is DesktopOAuthClient, "GMAIL_OAUTH_CLIENT_DENIED")
    return DesktopOAuthSession(client.client_id, port)
