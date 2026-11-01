"""META-P1-02 OFFLINE browser adapter skeleton (stdlib only).

Additive preview/fixture reader reusing existing CoreAdmission and
BrowserTaskV1/BrowserObservationV1 contracts. No live browser, no network,
and no import from any legacy bridge module.
Every dispatch_allowed here is ALWAYS False.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from runtime.core_admission import (
    AdmissionError,
    Capability,
    CoreAdmission,
    CorePrincipal,
    OwnerScope,
)
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.meta_hackathon.contracts import (
    BrowserObservationV1,
    BrowserTaskV1,
    MetaContractError,
    utc_timestamp,
)
from runtime.meta_hackathon.policy import (
    GateEffect,
    GateResult,
    screen_observation,
    screen_task,
)

FIXTURE_ORIGIN = "https://docs.example.org"
FIXTURE_URL = "https://docs.example.org/offline-fixture"
FIXTURE_CAPTURED_AT_UTC = "2026-06-01T12:00:00Z"
FIXTURE_TEXT = (
    "Synthetic public documentation fixture for offline adapter tests. "
    "This text is bundled with the repository and never fetched from a network. "
    "It describes a fictional document page used to exercise the read-only "
    "observation path end to end without a live browser."
)
MAX_FIXTURE_CHARS = 1600


class OfflineAdapterDenied(ValueError):
    """Fixed denial; never echoes untrusted URLs or keys."""

    def __init__(self) -> None:
        super().__init__("META_OFFLINE_ADAPTER_DENIED")


def _deny() -> OfflineAdapterDenied:
    return OfflineAdapterDenied()


def preview_task(
    task: BrowserTaskV1,
    *,
    core_owner_scope_digest: str,
    core_source_sha: str,
    stopped: bool,
    now: datetime | None = None,
) -> GateResult:
    """Screen a READ proposal. Never dispatches (dispatch_allowed is False)."""
    return screen_task(
        task,
        core_owner_scope_digest=core_owner_scope_digest,
        core_source_sha=core_source_sha,
        stopped=stopped,
        now=now,
    )


def read_fixture(
    task: BrowserTaskV1,
    *,
    admission: CoreAdmission,
    principal: CorePrincipal,
    scope: OwnerScope,
    core_owner_scope_digest: str,
    core_source_sha: str,
    stopped: bool,
    now: datetime | None = None,
    fixture_text: str = FIXTURE_TEXT,
    observed_url: str = FIXTURE_URL,
    captured_at_utc: str = FIXTURE_CAPTURED_AT_UTC,
    expected_content_sha256: str | None = None,
) -> BrowserObservationV1:
    """Build the trusted-fixture observation candidate after all Core gates pass."""
    if type(admission) is not CoreAdmission:
        raise _deny()
    try:
        admission.require(principal, Capability.READ, scope=scope)
    except AdmissionError:
        raise _deny() from None
    if type(scope) is not OwnerScope:
        raise _deny()
    try:
        bound_digest = canonical_sha256(scope)
    except Exception:
        raise _deny() from None
    if type(core_owner_scope_digest) is not str or core_owner_scope_digest != bound_digest:
        raise _deny()
    gate = screen_task(
        task,
        core_owner_scope_digest=core_owner_scope_digest,
        core_source_sha=core_source_sha,
        stopped=stopped,
        now=now,
    )
    if gate.effect is not GateEffect.CORE_ADMISSION_REQUIRED:
        raise _deny()
    if observed_url != task.target_url or observed_url != FIXTURE_URL:
        raise _deny()
    try:
        captured = utc_timestamp(captured_at_utc)
        deadline = utc_timestamp(task.deadline_utc)
    except MetaContractError:
        raise _deny() from None
    if captured > deadline:
        raise _deny()
    moment = now or datetime.now(timezone.utc)
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise _deny()
    if captured > moment.astimezone(timezone.utc):
        raise _deny()
    if moment.astimezone(timezone.utc) >= deadline:
        raise _deny()
    if (
        type(fixture_text) is not str
        or not fixture_text
        or len(fixture_text) > min(task.max_chars, MAX_FIXTURE_CHARS)
    ):
        raise _deny()
    content_sha = hashlib.sha256(fixture_text.encode("utf-8")).hexdigest()
    if expected_content_sha256 is not None and (
        type(expected_content_sha256) is not str
        or expected_content_sha256 != content_sha
    ):
        raise _deny()
    try:
        observation = BrowserObservationV1(
            task_digest=task.digest,
            observed_url=observed_url,
            captured_at_utc=captured_at_utc,
            content_sha256=content_sha,
            status="OBSERVED",
            environment="OFFLINE_FIXTURE",
            text_excerpt=fixture_text[:MAX_FIXTURE_CHARS],
        )
    except MetaContractError:
        raise _deny() from None
    review = screen_observation(observation, task)
    if review.effect is not GateEffect.UNVERIFIED_EVIDENCE:
        raise _deny()
    return observation


class OfflineFixtureAdapter:
    """Object wrapper around the fixture functions (still never dispatches)."""

    @property
    def dispatch_allowed(self) -> bool:
        return False

    def preview(
        self,
        task: BrowserTaskV1,
        *,
        core_owner_scope_digest: str,
        core_source_sha: str,
        stopped: bool,
        now: datetime | None = None,
    ) -> GateResult:
        return preview_task(
            task,
            core_owner_scope_digest=core_owner_scope_digest,
            core_source_sha=core_source_sha,
            stopped=stopped,
            now=now,
        )

    def read(
        self,
        task: BrowserTaskV1,
        *,
        admission: CoreAdmission,
        principal: CorePrincipal,
        scope: OwnerScope,
        core_owner_scope_digest: str,
        core_source_sha: str,
        stopped: bool,
        now: datetime | None = None,
    ) -> BrowserObservationV1:
        return read_fixture(
            task,
            admission=admission,
            principal=principal,
            scope=scope,
            core_owner_scope_digest=core_owner_scope_digest,
            core_source_sha=core_source_sha,
            stopped=stopped,
            now=now,
        )
