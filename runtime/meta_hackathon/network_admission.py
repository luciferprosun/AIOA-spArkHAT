"""META-G2 browser network admission PREVIEW; no network, no browser, no grants.

This intentionally admits *nothing* to execution. Chromium's eventual route
handler must invoke Core authority and revalidate every request and redirect.
DNS results here are a diagnostic guard, NOT reliable egress confinement:
a real browser may resolve an address again (DNS rebinding). Enforce outbound
network restrictions at the process/network layer before any LIVE use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import ipaddress

from .contracts import (
    BrowserTaskV1, MetaContractError, utc_timestamp, valid_page_url,
)


class NetworkEffect(str, Enum):
    DENY = "DENY"
    CORE_AND_EGRESS_POLICY_REQUIRED = "CORE_AND_EGRESS_POLICY_REQUIRED"


@dataclass(frozen=True, slots=True)
class BrowserNetworkRequestV1:
    """Host-collected metadata; never parse owner approval from a webpage."""

    url: str
    method: str
    resource_type: str
    is_main_frame: bool
    carries_credentials: bool = False

    def __post_init__(self) -> None:
        if not (
            type(self.url) is str and 0 < len(self.url) <= 1024
            and type(self.method) is str and 0 < len(self.method) <= 16
            and type(self.resource_type) is str and 0 < len(self.resource_type) <= 32
            and type(self.is_main_frame) is bool
            and type(self.carries_credentials) is bool
        ):
            raise MetaContractError("META_NETWORK_INPUT_DENIED")


@dataclass(frozen=True, slots=True)
class NetworkReview:
    effect: NetworkEffect
    reason: str
    task_digest: str

    @property
    def dispatch_allowed(self) -> bool:
        # An untrusted request, DNS check or model plan never grants networking.
        return False


def _public_ips(resolved_ips: object) -> bool:
    """All observed A/AAAA answers must be globally routable addresses.

    Accept data from a *host-owned* resolver only; still susceptible to
    rebinding unless egress is independently constrained.
    """
    if type(resolved_ips) not in (list, tuple) or not (1 <= len(resolved_ips) <= 16):
        return False
    for value in resolved_ips:
        if type(value) is not str or not value or len(value) > 45:
            return False
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            return False
        if not ip.is_global or (
            isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None
        ):
            return False
    return True


def review_browser_network(
    task: BrowserTaskV1,
    request: BrowserNetworkRequestV1,
    resolved_ips: tuple[str, ...] | list[str],
    *,
    stopped: bool,
    now: datetime | None = None,
) -> NetworkReview:
    if type(task) is not BrowserTaskV1 or type(request) is not BrowserNetworkRequestV1:
        raise MetaContractError("META_NETWORK_INPUT_DENIED")
    if type(stopped) is not bool:
        raise MetaContractError("META_NETWORK_INPUT_DENIED")
    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise MetaContractError("META_CLOCK_DENIED")

    def deny(reason: str) -> NetworkReview:
        return NetworkReview(NetworkEffect.DENY, reason, task.digest)

    if stopped:
        return deny("STOP")
    if now.astimezone(timezone.utc) >= utc_timestamp(task.deadline_utc):
        return deny("TASK_EXPIRED")
    if request.method != "GET":
        return deny("NON_GET_DENIED")
    if request.resource_type != "document" or not request.is_main_frame:
        return deny("SUBRESOURCE_OR_FRAME_DENIED")
    if request.carries_credentials:
        return deny("CREDENTIALS_DENIED")
    try:
        valid_page_url(request.url, task.allowed_origins)
    except MetaContractError:
        return deny("URL_OUTSIDE_SCOPE")
    if request.url != task.target_url:
        return deny("UNPLANNED_NAVIGATION_DENIED")
    if not _public_ips(resolved_ips):
        return deny("UNSAFE_DNS_RESPONSE")
    return NetworkReview(
        NetworkEffect.CORE_AND_EGRESS_POLICY_REQUIRED,
        "PREVIEW_ONLY_NO_NETWORK_DISPATCH",
        task.digest,
    )
