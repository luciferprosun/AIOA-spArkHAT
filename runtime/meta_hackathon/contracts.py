"""Strict additive Meta browser contracts. No authority or browser side effects.

Inputs arriving from Muse, MCP, webpages or GitHub are *data*. The canonical
fingerprint is a correlation commitment, NEVER an approval or bearer token.
A later Core-owned executor must independently check DNS (including every
redirect), owner scope, STOP, task lease and a one-use human warrant for effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit

SCHEMA = "aioa.meta.browser.v1"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PATH = re.compile(r"/[A-Za-z0-9._~/-]*\Z")
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".invalid", ".test",
                     ".example", ".onion", ".lan", ".home", ".arpa")
_ACTIONS = frozenset({"click", "type", "submit", "upload", "download", "login",
                     "gmail.send", "shell.exec", "git.push", "account.change"})


class MetaContractError(ValueError):
    """Constant non-sensitive error message; never echo an untrusted URL/key."""


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise MetaContractError(code)


def _identifier(value: object) -> None:
    _require(type(value) is str and _ID.fullmatch(value) is not None, "META_ID_DENIED")


def _hash(value: object, *, sha40: bool = False) -> None:
    pattern = _SHA40 if sha40 else _HEX64
    _require(type(value) is str and pattern.fullmatch(value) is not None,
             "META_HASH_DENIED")


def utc_timestamp(value: object) -> datetime:
    _require(type(value) is str and 20 <= len(value) <= 32 and value.endswith("Z"),
             "META_TIME_DENIED")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise MetaContractError("META_TIME_DENIED") from None
    _require(result.tzinfo is not None and result.utcoffset() == timedelta(0),
             "META_TIME_DENIED")
    return result.astimezone(timezone.utc)


def canonical_digest(payload: dict) -> str:
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise MetaContractError("META_JSON_DENIED") from None
    _require(len(encoded) <= 6144, "META_JSON_DENIED")
    return hashlib.sha256(encoded).hexdigest()


def _strict_fields(value: object, keys: frozenset[str]) -> dict:
    _require(type(value) is dict and frozenset(value) == keys, "META_INPUT_DENIED")
    return value


def _url_parts(value: object):
    _require(type(value) is str and 12 <= len(value) <= 1024, "META_URL_DENIED")
    _require(all(ord(c) < 127 and ord(c) >= 33 for c in value)
             and not any(char in value for char in ("\\", "@", "?", "#", "%")),
             "META_URL_DENIED")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except (ValueError, UnicodeError):
        raise MetaContractError("META_URL_DENIED") from None
    _require(parsed.scheme == "https" and host is not None and port is None
             and parsed.username is None and parsed.password is None
             and parsed.netloc == host and not parsed.query and not parsed.fragment,
             "META_URL_DENIED")
    # Avoid literal addresses, localhost aliases, names without public-style TLDs.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise MetaContractError("META_URL_DENIED")
    labels = host.split(".")
    _require(len(labels) >= 2 and len(host) <= 253 and all(_LABEL.fullmatch(x)
             for x in labels) and re.fullmatch(r"[a-z]{2,24}", labels[-1]) is not None
             and not host.endswith(_BLOCKED_SUFFIXES), "META_URL_DENIED")
    path = parsed.path
    _require(not path or (_PATH.fullmatch(path) is not None
             and "//" not in path and not any(piece in (".", "..")
             for piece in path.split("/"))), "META_URL_DENIED")
    return parsed, f"https://{host}"


def valid_origin(value: object) -> str:
    parsed, origin = _url_parts(value)
    _require(parsed.path == "" and value == origin, "META_ORIGIN_DENIED")
    return origin


def valid_page_url(value: object, allowed_origins: tuple[str, ...]) -> str:
    _, origin = _url_parts(value)
    _require(origin in allowed_origins, "META_URL_OUTSIDE_SCOPE")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class BrowserTaskV1:
    """Untrusted READ proposal; Core must independently admit a request."""

    task_id: str
    owner_scope_digest: str
    source_sha: str
    allowed_origins: tuple[str, ...]
    target_url: str
    deadline_utc: str
    operation: str = "navigate_read"
    max_pages: int = 1
    timeout_ms: int = 8000
    max_chars: int = 3000
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        _identifier(self.task_id)
        _hash(self.owner_scope_digest)
        _hash(self.source_sha, sha40=True)
        _require(self.schema == SCHEMA and self.operation == "navigate_read",
                 "META_OPERATION_DENIED")
        _require(type(self.allowed_origins) is tuple and 1 <= len(self.allowed_origins) <= 5
                 and len(set(self.allowed_origins)) == len(self.allowed_origins),
                 "META_ORIGINS_DENIED")
        for origin in self.allowed_origins:
            valid_origin(origin)
        valid_page_url(self.target_url, self.allowed_origins)
        utc_timestamp(self.deadline_utc)
        _require(type(self.max_pages) is int and 1 <= self.max_pages <= 4
                 and type(self.timeout_ms) is int and 1000 <= self.timeout_ms <= 15000
                 and type(self.max_chars) is int and 200 <= self.max_chars <= 5000,
                 "META_BUDGET_DENIED")
        canonical_digest(self.to_dict())

    @classmethod
    def parse(cls, value: object) -> BrowserTaskV1:
        value = _strict_fields(value, frozenset(cls.__dataclass_fields__))
        _require(type(value["allowed_origins"]) is list,
                 "META_ORIGINS_DENIED")
        return cls(**{**value, "allowed_origins": tuple(value["allowed_origins"])})

    def to_dict(self) -> dict:
        data = asdict(self)
        data["allowed_origins"] = list(self.allowed_origins)
        return data

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_dict())


@dataclass(frozen=True, slots=True, repr=False)
class BrowserObservationV1:
    """Evidence *candidate*, never certified by its own status text."""

    task_digest: str
    observed_url: str
    captured_at_utc: str
    content_sha256: str
    status: str
    environment: str
    text_excerpt: str = ""
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        _hash(self.task_digest)
        _hash(self.content_sha256)
        _url_parts(self.observed_url)
        utc_timestamp(self.captured_at_utc)
        _require(self.schema == SCHEMA and self.status in
                 ("OBSERVED", "FAILED", "STOPPED", "UNKNOWN"), "META_STATUS_DENIED")
        _require(self.environment in ("OFFLINE_FIXTURE", "LIVE_BROWSER_UNVERIFIED"),
                 "META_EVIDENCE_DENIED")
        _require(type(self.text_excerpt) is str and len(self.text_excerpt) <= 1600,
                 "META_EVIDENCE_DENIED")
        canonical_digest(asdict(self))

    @classmethod
    def parse(cls, value: object) -> BrowserObservationV1:
        value = _strict_fields(value, frozenset(cls.__dataclass_fields__))
        return cls(**value)


@dataclass(frozen=True, slots=True, repr=False)
class ActionProposalV1:
    """Representation for exact owner review; it cannot execute anything."""

    task_digest: str
    action: str
    target_url: str
    parameters_sha256: str
    expires_at_utc: str
    preview: str
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        _hash(self.task_digest)
        _hash(self.parameters_sha256)
        _url_parts(self.target_url)
        utc_timestamp(self.expires_at_utc)
        _require(self.schema == SCHEMA and self.action in _ACTIONS,
                 "META_ACTION_DENIED")
        _require(type(self.preview) is str and 1 <= len(self.preview) <= 500
                 and not any(ord(c) < 32 or ord(c) == 127 for c in self.preview),
                 "META_PREVIEW_DENIED")
        canonical_digest(asdict(self))

    @classmethod
    def parse(cls, value: object) -> ActionProposalV1:
        value = _strict_fields(value, frozenset(cls.__dataclass_fields__))
        return cls(**value)

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))
