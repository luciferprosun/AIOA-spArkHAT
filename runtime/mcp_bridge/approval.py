"""Offline ApprovalToken v1 fixture verification; never an execution authority.

The pinned key is the PUBLIC RFC 8032 section 7.1 test-vector key. Its private
seed is public test data, so successful verification conveys no human approval.
No signer, key loading, transport, nonce consumption or effect path lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
import json
import re
import unicodedata
from uuid import UUID

from .contracts import ContractError, RiskClass, TaskEnvelope

VERSION = "mcp.approval.v1"
FIXTURE_KEY_ID = "fixture-rfc8032-1"
FIXTURE_PUBLIC_KEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)


def _text(value: object) -> None:
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ContractError("approval fields must be bounded nonempty strings")
    if unicodedata.normalize("NFC", value) != value or any(
        unicodedata.category(char) in {"Cc", "Cs"} for char in value
    ):
        raise ContractError("approval text must be NFC without controls or surrogates")


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ContractError("approval timestamp must be UTC seconds") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ContractError("approval timestamp is not canonical")
    return parsed


@dataclass(frozen=True)
class ApprovalToken:
    version: str
    approval_id: str
    task_id: str
    task_fingerprint: str
    nonce: str
    scope: str
    resource: str
    risk_class: str
    issued_at: str
    expires_at: str
    key_id: str
    signature: str

    def __post_init__(self) -> None:
        for field in fields(self):
            _text(getattr(self, field.name))
        if self.version != VERSION:
            raise ContractError("unsupported approval version")
        try:
            identifier = UUID(self.approval_id)
        except ValueError as exc:
            raise ContractError("approval_id must be a canonical UUID") from exc
        if str(identifier) != self.approval_id or identifier.int == 0:
            raise ContractError("approval_id must be a canonical nonnil UUID")
        for name, length in (("task_fingerprint", 64), ("nonce", 64), ("signature", 128)):
            if re.fullmatch(r"[0-9a-f]{%d}" % length, getattr(self, name)) is None:
                raise ContractError("approval digest, nonce or signature encoding is invalid")
        if self.risk_class not in {risk.value for risk in RiskClass}:
            raise ContractError("unknown approval risk class")
        if _utc(self.issued_at) >= _utc(self.expires_at):
            raise ContractError("approval validity interval is empty")

    @classmethod
    def from_dict(cls, value: dict) -> ApprovalToken:
        if type(value) is not dict or set(value) != {field.name for field in fields(cls)}:
            raise ContractError("approval requires exactly the v1 fields")
        return cls(**value)

    @classmethod
    def from_json(cls, wire: bytes) -> ApprovalToken:
        if type(wire) is not bytes or len(wire) > 8192:
            raise ContractError("approval wire must be bounded bytes")

        def unique(pairs: list) -> dict:
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ContractError("duplicate approval field")
                result[key] = value
            return result

        try:
            value = json.loads(wire.decode("utf-8"), object_pairs_hook=unique)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ContractError("invalid approval JSON") from exc
        token = cls.from_dict(value)
        if token.to_json() != wire:
            raise ContractError("approval wire is not canonical")
        return token

    def to_dict(self) -> dict[str, str]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    def signing_bytes(self) -> bytes:
        value = self.to_dict()
        del value["signature"]
        return _canonical(value)

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())


@dataclass(frozen=True)
class FixtureVerification:
    provenance: str = "OFFLINE_PUBLIC_TEST_KEY"
    grants_effect_authority: bool = False


def verify_fixture_approval(
    token: ApprovalToken, task: TaskEnvelope, *, scope: str, resource: str,
    now: datetime,
) -> FixtureVerification:
    """Verify against caller-supplied expected bindings and explicit offline time.

    Returned evidence cannot authorize WRITE_LOCAL/EXEC_LOCAL. Replays require a
    separate durable receipt/nonce barrier; this verifier deliberately has none.
    """
    if type(token) is not ApprovalToken or type(task) is not TaskEnvelope:
        raise ContractError("fixture verification requires typed contracts")
    _text(scope)
    _text(resource)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        raise ContractError("verification time must be aware UTC")
    if token.key_id != FIXTURE_KEY_ID:
        raise ContractError("approval key is not pinned fixture key")
    if not _utc(token.issued_at) <= now < _utc(token.expires_at):
        raise ContractError("approval is not currently valid")
    if (token.task_id != task.task_id or token.task_fingerprint != task.fingerprint
            or token.risk_class != task.risk.value or token.scope != scope
            or token.resource != resource):
        raise ContractError("approval task, scope, resource or risk binding mismatch")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise ContractError("Ed25519 backend unavailable; verification disabled") from exc
    try:
        Ed25519PublicKey.from_public_bytes(FIXTURE_PUBLIC_KEY).verify(
            bytes.fromhex(token.signature), token.signing_bytes()
        )
    except InvalidSignature as exc:
        raise ContractError("invalid fixture approval signature") from exc
    return FixtureVerification()
