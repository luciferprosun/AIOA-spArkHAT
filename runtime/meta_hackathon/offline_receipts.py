"""META-P2-02: hermetic, strictly synthetic budget and receipt contracts.

This module never imports a network transport, makes a provider request or
enforces actual Meta billing. Monetary limits apply ONLY to mock receipts.
The owner must separately authorize a live API probe and real spending cap.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re
from threading import Lock

from .contracts import MetaContractError, _hash, _identifier, canonical_digest, utc_timestamp
from .provider_offline import MAX_OUTPUT_TOKENS, OFFLINE_MODEL, OfflineMuseEnvelope

RESERVATION_SCHEMA = "aioa.meta.mock-budget-reservation.v1"
MOCK_RESPONSE_SCHEMA = "aioa.meta.mock-provider-result.v1"
RECEIPT_SCHEMA = "aioa.meta.mock-provider-receipt.v1"
OFFLINE_ENVIRONMENT = "OFFLINE_MOCK_ONLY"
_STATUSES = frozenset({"MOCK_DONE", "MOCK_FAILED", "MOCK_UNKNOWN", "MOCK_STOPPED"})
_USD = re.compile(r"(?:0\.[0-9]{2}|1\.00)\Z")
_MAX_FIXTURE_CHARS = 4096
_MOCK_FIELDS = frozenset({
    "schema", "model", "task_digest", "owner_scope_digest", "source_sha",
    "attempt_id", "nonce_sha256", "completion_tokens", "status",
})


def _deny(ok: bool, reason: str) -> None:
    if not ok:
        raise MetaContractError(reason)


def _cents(value: object) -> int:
    """Only canonical cent-denominated strings; never floats/NaN/bools."""
    _deny(type(value) is str and _USD.fullmatch(value) is not None,
          "META_MOCK_BUDGET_DENIED")
    return int(value[0]) * 100 + int(value[2:])


def _mock_json(value: object) -> dict:
    """Reject huge JSON, NaN/Infinity, duplicate keys, and schema drift."""
    _deny(type(value) is str and 1 <= len(value) <= _MAX_FIXTURE_CHARS,
          "META_MOCK_RESPONSE_DENIED")

    def unique_object(items):
        out = {}
        for key, field in items:
            _deny(key not in out, "META_MOCK_RESPONSE_DENIED")
            out[key] = field
        return out

    def invalid_constant(_value):
        raise MetaContractError("META_MOCK_RESPONSE_DENIED")

    try:
        result = json.loads(value, object_pairs_hook=unique_object,
                            parse_constant=invalid_constant)
    except (TypeError, ValueError, OverflowError):
        raise MetaContractError("META_MOCK_RESPONSE_DENIED") from None
    _deny(type(result) is dict and frozenset(result) == _MOCK_FIELDS,
          "META_MOCK_RESPONSE_DENIED")
    return result


@dataclass(frozen=True, slots=True, repr=False)
class BudgetReservation:
    """Trusted-host synthetic allocation. Nonce is NOT an approval token."""

    task_digest: str
    owner_scope_digest: str
    source_sha: str
    model: str
    attempt_id: str
    nonce: str
    issued_at_utc: str
    expires_at_utc: str
    max_output_tokens: int
    max_usd: str
    schema: str = RESERVATION_SCHEMA

    def __post_init__(self) -> None:
        _deny(self.schema == RESERVATION_SCHEMA and self.model == OFFLINE_MODEL,
              "META_MOCK_BINDING_DENIED")
        _hash(self.task_digest)
        _hash(self.owner_scope_digest)
        _hash(self.source_sha, sha40=True)
        _identifier(self.attempt_id)
        _hash(self.nonce)
        issued = utc_timestamp(self.issued_at_utc)
        expires = utc_timestamp(self.expires_at_utc)
        _deny(issued < expires <= issued + timedelta(minutes=15),
              "META_MOCK_TIME_DENIED")
        _deny(type(self.max_output_tokens) is int
              and 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS,
              "META_MOCK_BUDGET_DENIED")
        _cents(self.max_usd)

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))

    @property
    def nonce_sha256(self) -> str:
        return sha256(self.nonce.encode("ascii")).hexdigest()

    @property
    def dispatch_allowed(self) -> bool:
        return False

    def matches_envelope(self, envelope: OfflineMuseEnvelope) -> bool:
        return (
            type(envelope) is OfflineMuseEnvelope
            and not envelope.dispatch_allowed
            and self.task_digest == envelope.task_digest
            and self.owner_scope_digest == envelope.owner_scope_digest
            and self.source_sha == envelope.source_sha
            and self.model == envelope.model
            and self.max_output_tokens <= envelope.max_output_tokens
            and _cents(self.max_usd) <=
            int(Decimal(str(envelope.budget_usd_limit)) * 100)
        )


@dataclass(frozen=True, slots=True, repr=False)
class ProviderReceipt:
    """Public-safe simulated metadata. Never certifies real execution."""

    task_digest: str
    owner_scope_digest: str
    source_sha: str
    model: str
    attempt_id: str
    nonce_sha256: str
    reservation_sha256: str
    expires_at_utc: str
    max_output_tokens: int
    completion_tokens: int
    reserved_usd: str
    mock_cost_usd: str
    status: str
    schema: str = RECEIPT_SCHEMA
    environment: str = OFFLINE_ENVIRONMENT

    def __post_init__(self) -> None:
        _deny(self.schema == RECEIPT_SCHEMA and
              self.environment == OFFLINE_ENVIRONMENT and
              self.status in _STATUSES and self.model == OFFLINE_MODEL,
              "META_MOCK_RECEIPT_DENIED")
        _hash(self.task_digest)
        _hash(self.owner_scope_digest)
        _hash(self.source_sha, sha40=True)
        _identifier(self.attempt_id)
        _hash(self.nonce_sha256)
        _hash(self.reservation_sha256)
        utc_timestamp(self.expires_at_utc)
        _deny(type(self.max_output_tokens) is int and
              type(self.completion_tokens) is int and
              0 <= self.completion_tokens <= self.max_output_tokens <= MAX_OUTPUT_TOKENS,
              "META_MOCK_RECEIPT_DENIED")
        _deny(_cents(self.mock_cost_usd) <= _cents(self.reserved_usd),
              "META_MOCK_BUDGET_DENIED")

    @property
    def dispatch_allowed(self) -> bool:
        return False

    @property
    def verified(self) -> bool:
        return False

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_public_dict())

    def to_public_dict(self) -> dict:
        """Allowlisted hashes/labels only; no nonce, prompt, response or key."""
        return asdict(self)

    def to_public_json(self) -> str:
        return json.dumps(self.to_public_dict(), sort_keys=True,
                          separators=(",", ":"), allow_nan=False)


class OfflineReceiptLedger:
    """One-shot in-memory ledger with atomic mock caps and replay denial.

    It does NOT authorize a model, track real invoices, perform I/O,
    or reserve money with a provider. Uncertain outcomes are never retried.
    """

    def __init__(self, *, max_total_usd: str = "1.00") -> None:
        self._max_cents = _cents(max_total_usd)
        self._spent_cents = 0
        self._attempts: set[str] = set()
        self._nonces: set[str] = set()
        self._lock = Lock()

    @property
    def mock_spent_usd(self) -> str:
        with self._lock:
            return f"{self._spent_cents // 100}.{self._spent_cents % 100:02d}"

    @property
    def dispatch_allowed(self) -> bool:
        return False

    def record_once(
        self,
        reservation: BudgetReservation,
        envelope: OfflineMuseEnvelope,
        *,
        mock_response_json: str,
        mock_cost_usd: str,
        now_utc: str,
        stopped: bool = False,
    ) -> ProviderReceipt:
        _deny(type(reservation) is BudgetReservation and
              type(envelope) is OfflineMuseEnvelope and
              type(stopped) is bool, "META_MOCK_INPUT_DENIED")
        _deny(reservation.matches_envelope(envelope), "META_MOCK_BINDING_DENIED")
        now = utc_timestamp(now_utc)
        _deny(utc_timestamp(reservation.issued_at_utc) <= now <
              utc_timestamp(reservation.expires_at_utc),
              "META_MOCK_TIME_DENIED")

        fixture = _mock_json(mock_response_json)
        _deny(fixture["schema"] == MOCK_RESPONSE_SCHEMA and
              fixture["model"] == reservation.model and
              fixture["task_digest"] == reservation.task_digest and
              fixture["owner_scope_digest"] == reservation.owner_scope_digest and
              fixture["source_sha"] == reservation.source_sha and
              fixture["attempt_id"] == reservation.attempt_id and
              fixture["nonce_sha256"] == reservation.nonce_sha256,
              "META_MOCK_BINDING_DENIED")
        tokens = fixture["completion_tokens"]
        status = fixture["status"]
        _deny(type(tokens) is int and
              0 <= tokens <= reservation.max_output_tokens and
              type(status) is str and status in _STATUSES,
              "META_MOCK_RESPONSE_DENIED")
        _deny((status == "MOCK_STOPPED") == stopped,
              "META_MOCK_STOP_DENIED")
        _deny(status not in ("MOCK_UNKNOWN", "MOCK_STOPPED") or tokens == 0,
              "META_MOCK_RESPONSE_DENIED")

        cost_cents = _cents(mock_cost_usd)
        _deny(cost_cents <= _cents(reservation.max_usd),
              "META_MOCK_BUDGET_DENIED")

        receipt = ProviderReceipt(
            task_digest=reservation.task_digest,
            owner_scope_digest=reservation.owner_scope_digest,
            source_sha=reservation.source_sha,
            model=reservation.model,
            attempt_id=reservation.attempt_id,
            nonce_sha256=reservation.nonce_sha256,
            reservation_sha256=reservation.digest,
            expires_at_utc=reservation.expires_at_utc,
            max_output_tokens=reservation.max_output_tokens,
            completion_tokens=tokens,
            reserved_usd=reservation.max_usd,
            mock_cost_usd=mock_cost_usd,
            status=status,
        )
        with self._lock:
            _deny(reservation.attempt_id not in self._attempts and
                  reservation.nonce_sha256 not in self._nonces,
                  "META_MOCK_REPLAY_DENIED")
            _deny(self._spent_cents + cost_cents <= self._max_cents,
                  "META_MOCK_BUDGET_DENIED")
            self._attempts.add(reservation.attempt_id)
            self._nonces.add(reservation.nonce_sha256)
            self._spent_cents += cost_cents
        return receipt
