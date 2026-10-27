"""META-P3-01: strictly OFFLINE, non-authoritative evidence correlation.

This contract links trusted-host task bindings, an offline browser observation
and an offline synthetic provider receipt. No network, browser, provider, effect,
owner approval, or LIVE evidence verification exists in this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from threading import Lock

from runtime.meta_hackathon.contracts import (
    BrowserObservationV1,
    BrowserTaskV1,
    MetaContractError,
    _hash,
    _url_parts,
    canonical_digest,
    utc_timestamp,
    valid_page_url,
)
from runtime.meta_hackathon.offline_receipts import (
    OFFLINE_ENVIRONMENT as MOCK_ENVIRONMENT,
    ProviderReceipt,
)

CORRELATION_SCHEMA = "aioa.meta.offline-correlation.v1"
CORRELATION_ENVIRONMENT = "OFFLINE_FIXTURE"
_LINKED = "OFFLINE_LINKED_UNVERIFIED"
_UNKNOWN = "UNKNOWN"
_ALLOWED_STATES = frozenset({_LINKED, _UNKNOWN})


def _deny(ok: bool, code: str) -> None:
    if not ok:
        raise MetaContractError(code)


@dataclass(frozen=True, slots=True, repr=False)
class OfflineCorrelation:
    """Public-safe provenance metadata; NEVER an authority or verified result."""

    task_digest: str
    owner_scope_digest: str
    source_sha: str
    observed_url: str
    content_sha256: str
    observation_sha256: str
    provider_receipt_sha256: str | None
    captured_at_utc: str
    correlated_at_utc: str
    status: str
    schema: str = CORRELATION_SCHEMA
    environment: str = CORRELATION_ENVIRONMENT

    def __post_init__(self) -> None:
        _hash(self.task_digest)
        _hash(self.owner_scope_digest)
        _hash(self.source_sha, sha40=True)
        _hash(self.content_sha256)
        _hash(self.observation_sha256)
        if self.provider_receipt_sha256 is not None:
            _hash(self.provider_receipt_sha256)
        utc_timestamp(self.captured_at_utc)
        utc_timestamp(self.correlated_at_utc)
        _deny(self.schema == CORRELATION_SCHEMA and
              self.environment == CORRELATION_ENVIRONMENT and
              type(self.status) is str and self.status in _ALLOWED_STATES,
              "META_CORRELATION_INPUT_DENIED")
        _deny(self.status != _LINKED or self.provider_receipt_sha256 is not None,
              "META_CORRELATION_EVIDENCE_DENIED")
        # Re-check URL syntax here; the ledger additionally checks the
        # trusted task's owner allowlist and exact target URL.
        _url_parts(self.observed_url)

    @property
    def verified(self) -> bool:
        return False

    @property
    def dispatch_allowed(self) -> bool:
        return False

    def to_public_dict(self) -> dict:
        """Never exposes page content, browser cookies, prompts or raw receipts."""
        return asdict(self)

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_public_dict())

    def to_public_json(self) -> str:
        return json.dumps(self.to_public_dict(), sort_keys=True,
                          separators=(",", ":"), allow_nan=False)


class OfflineCorrelationLedger:
    """One-shot offline task-to-observation-to-receipt correlation.

    The caller must originate task, observation and receipt from its own
    trusted inputs. A matching hash proves internal consistency only; it
    does not certify origin authenticity or that a browser was ever run.
    """

    def __init__(self) -> None:
        self._seen_tasks: set[str] = set()
        self._seen_receipts: set[str] = set()
        self._lock = Lock()

    @property
    def dispatch_allowed(self) -> bool:
        return False

    def correlate_once(
        self,
        task: BrowserTaskV1,
        observation: BrowserObservationV1,
        receipt: ProviderReceipt | None,
        *,
        observed_content: str | None,
        now_utc: str,
        stopped: bool = False,
    ) -> OfflineCorrelation:
        _deny(type(task) is BrowserTaskV1
              and type(observation) is BrowserObservationV1
              and (receipt is None or type(receipt) is ProviderReceipt)
              and type(stopped) is bool,
              "META_CORRELATION_INPUT_DENIED")
        _deny(not stopped, "META_CORRELATION_STOP_DENIED")

        now = utc_timestamp(now_utc)
        captured = utc_timestamp(observation.captured_at_utc)
        _deny(now < utc_timestamp(task.deadline_utc) and captured <= now,
              "META_CORRELATION_TIME_DENIED")
        _deny(observation.environment == CORRELATION_ENVIRONMENT,
              "META_CORRELATION_ENV_DENIED")
        _deny(observation.task_digest == task.digest,
              "META_CORRELATION_BINDING_DENIED")
        valid_page_url(observation.observed_url, task.allowed_origins)
        # The fixture has no signed redirect chain; permit only exact target.
        _deny(observation.observed_url == task.target_url,
              "META_CORRELATION_URL_DENIED")

        if observed_content is not None:
            _deny(type(observed_content) is str
                  and len(observed_content) <= task.max_chars,
                  "META_CORRELATION_CONTENT_DENIED")
            try:
                computed = sha256(observed_content.encode("utf-8")).hexdigest()
            except UnicodeError:
                raise MetaContractError("META_CORRELATION_CONTENT_DENIED") from None
            _deny(computed == observation.content_sha256,
                  "META_CORRELATION_CONFLICT")
        evidence_present = observed_content is not None

        if receipt is not None:
            _deny(receipt.environment == MOCK_ENVIRONMENT
                  and not receipt.dispatch_allowed
                  and not receipt.verified
                  and receipt.task_digest == task.digest
                  and receipt.owner_scope_digest == task.owner_scope_digest
                  and receipt.source_sha == task.source_sha,
                  "META_CORRELATION_BINDING_DENIED")
            _deny(now < utc_timestamp(receipt.expires_at_utc),
                  "META_CORRELATION_TIME_DENIED")

        status = (
            _LINKED if receipt is not None
            and receipt.status == "MOCK_DONE"
            and observation.status == "OBSERVED"
            and evidence_present else _UNKNOWN
        )
        proof = OfflineCorrelation(
            task_digest=task.digest,
            owner_scope_digest=task.owner_scope_digest,
            source_sha=task.source_sha,
            observed_url=observation.observed_url,
            content_sha256=observation.content_sha256,
            observation_sha256=canonical_digest(asdict(observation)),
            provider_receipt_sha256=None if receipt is None else receipt.digest,
            captured_at_utc=observation.captured_at_utc,
            correlated_at_utc=now_utc,
            status=status,
        )
        with self._lock:
            _deny(task.digest not in self._seen_tasks,
                  "META_CORRELATION_REPLAY_DENIED")
            if receipt is not None:
                _deny(receipt.digest not in self._seen_receipts,
                      "META_CORRELATION_REPLAY_DENIED")
                self._seen_receipts.add(receipt.digest)
            self._seen_tasks.add(task.digest)
        return proof
