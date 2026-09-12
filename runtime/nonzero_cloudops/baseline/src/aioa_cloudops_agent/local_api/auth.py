"""Constant-time, header-only authentication for the loopback Local-2 API."""

import hashlib
import hmac
from collections.abc import Mapping

from aioa_cloudops_agent.agent.local_hitl import LocalOperatorPrincipal

from .contracts import LOCAL_API_TOKEN_MAX_LENGTH, LOCAL_API_TOKEN_MIN_LENGTH

LOCAL_API_SESSION_COOKIE = "aioa_operator_session"
_COOKIE_HEADER_MAX_LENGTH = 4_096
_SESSION_DOMAIN_SEPARATOR = b"aioa-local-browser-session-v1\0"


class LocalApiTokenAuthorizer:
    """Derive a stable operator session from one local bearer token."""

    def __init__(self, token: str) -> None:
        if (
            not isinstance(token, str)
            or token != token.strip()
            or not LOCAL_API_TOKEN_MIN_LENGTH <= len(token) <= LOCAL_API_TOKEN_MAX_LENGTH
        ):
            raise ValueError("local API token length or shape is invalid")
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        self._token_digest = digest
        self._browser_session = hashlib.sha256(
            _SESSION_DOMAIN_SEPARATOR + digest
        ).hexdigest()
        self._principal = LocalOperatorPrincipal(
            actor_session_id=f"local-api:{digest.hex()[:32]}"
        )

    def _authorize_bearer(self, headers: Mapping[str, object]) -> bool:
        value = headers.get("authorization")
        if not isinstance(value, str) or not value.startswith("Bearer "):
            return False
        candidate = value.removeprefix("Bearer ")
        if (
            candidate != candidate.strip()
            or not LOCAL_API_TOKEN_MIN_LENGTH
            <= len(candidate)
            <= LOCAL_API_TOKEN_MAX_LENGTH
        ):
            return False
        candidate_digest = hashlib.sha256(candidate.encode("utf-8")).digest()
        return hmac.compare_digest(candidate_digest, self._token_digest)

    def issue_browser_session(self, headers: Mapping[str, object]) -> str | None:
        """Exchange the exact local bearer credential for one process-safe cookie value."""

        if not self._authorize_bearer(headers):
            return None
        return self._browser_session

    def _authorize_cookie(self, headers: Mapping[str, object]) -> bool:
        raw_cookie = headers.get("cookie")
        if (
            not isinstance(raw_cookie, str)
            or not raw_cookie
            or len(raw_cookie) > _COOKIE_HEADER_MAX_LENGTH
        ):
            return False
        candidate: str | None = None
        for segment in raw_cookie.split(";"):
            name, separator, value = segment.strip().partition("=")
            if not separator or name != LOCAL_API_SESSION_COOKIE:
                continue
            if candidate is not None or not value or value != value.strip():
                return False
            candidate = value
        return candidate is not None and hmac.compare_digest(
            candidate,
            self._browser_session,
        )

    def authorize(
        self,
        headers: Mapping[str, object],
    ) -> LocalOperatorPrincipal | None:
        """Accept exactly one well-shaped Bearer value and never retain the candidate."""

        if "authorization" in headers:
            accepted = self._authorize_bearer(headers)
        else:
            accepted = self._authorize_cookie(headers)
        if not accepted:
            return None
        return self._principal
