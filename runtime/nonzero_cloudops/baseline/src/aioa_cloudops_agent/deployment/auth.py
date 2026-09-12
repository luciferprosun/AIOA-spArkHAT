"""Constant-time, header-only authorization for the read-only judge routes."""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from aioa_cloudops_agent.deployment.config import (
    JUDGE_TOKEN_MAX_LENGTH,
    JUDGE_TOKEN_MAX_LIFETIME_SECONDS,
    JUDGE_TOKEN_MIN_LENGTH,
)


class SecretsManagerGetSecretValueClient(Protocol):
    """Only the one secret read required by judge authentication."""

    def get_secret_value(self, **kwargs: object) -> Mapping[str, Any]: ...


class _JudgeTokenSecret(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    token: str = Field(min_length=JUDGE_TOKEN_MIN_LENGTH, max_length=JUDGE_TOKEN_MAX_LENGTH)
    not_after: datetime


class AuthenticatedJudgePrincipal(BaseModel):
    """Server-derived identity; no caller-supplied actor field is trusted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = "judge-token-principal"


class SecretsManagerJudgeTokenProvider:
    """Read one dedicated secret and enforce its server-configured expiration."""

    def __init__(
        self,
        client: SecretsManagerGetSecretValueClient,
        *,
        secret_id: str,
        not_after: datetime,
        clock: Callable[[], datetime],
        cache_ttl_seconds: int = 60,
    ) -> None:
        if not isinstance(secret_id, str) or not secret_id.startswith("arn:"):
            raise ValueError("secret_id must be an explicit ARN")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not 5 <= cache_ttl_seconds <= 300:
            raise ValueError("cache_ttl_seconds must be between 5 and 300")
        if not_after.tzinfo is None or not_after.utcoffset() != UTC.utcoffset(not_after):
            raise ValueError("not_after must be UTC")
        self._client = client
        self._secret_id = secret_id
        self._not_after = not_after
        self._clock = clock
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._cache_lock = Lock()
        self._cached_token: str | None = None
        self._cache_expires_at: datetime | None = None

    def get_token(self) -> str:
        """Return the token or fail with a redacted error."""

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise RuntimeError("judge credential is unavailable")
        if (
            now >= self._not_after
            or self._not_after - now
            > timedelta(seconds=JUDGE_TOKEN_MAX_LIFETIME_SECONDS)
        ):
            raise RuntimeError("judge credential is unavailable")
        with self._cache_lock:
            if (
                self._cached_token is not None
                and self._cache_expires_at is not None
                and now < self._cache_expires_at
            ):
                return self._cached_token
            try:
                response = self._client.get_secret_value(SecretId=self._secret_id)
                raw = response.get("SecretString")
                decoded = json.loads(raw) if isinstance(raw, str) else None
                secret = _JudgeTokenSecret.model_validate(decoded)
                if (
                    secret.not_after.tzinfo is None
                    or secret.not_after.utcoffset() != UTC.utcoffset(secret.not_after)
                    or secret.not_after != self._not_after
                ):
                    raise ValueError("secret expiry binding is invalid")
            except Exception:
                raise RuntimeError("judge credential is unavailable") from None
            self._cached_token = secret.token
            self._cache_expires_at = min(now + self._cache_ttl, self._not_after)
            return secret.token


class JudgeTokenAuthorizer:
    """Require one Bearer token and compare it without data-dependent early exit."""

    def __init__(self, token_provider: SecretsManagerJudgeTokenProvider | object) -> None:
        if not callable(getattr(token_provider, "get_token", None)):
            raise TypeError("token_provider must expose get_token")
        self._token_provider = token_provider

    def authorize(self, headers: Mapping[str, object]) -> AuthenticatedJudgePrincipal | None:
        """Return a trusted principal only for one exact Authorization header."""

        normalized = {
            str(name).casefold(): value
            for name, value in headers.items()
            if isinstance(name, str)
        }
        value = normalized.get("authorization")
        if not isinstance(value, str) or not value.startswith("Bearer "):
            return None
        candidate = value.removeprefix("Bearer ")
        if (
            len(candidate) < JUDGE_TOKEN_MIN_LENGTH
            or candidate != candidate.strip()
            or len(candidate) > JUDGE_TOKEN_MAX_LENGTH
        ):
            return None
        try:
            expected = self._token_provider.get_token()
        except Exception:
            return None
        if not hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8")):
            return None
        return AuthenticatedJudgePrincipal()
