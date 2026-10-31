"""Injected, bounded READ surface. Real Chrome is blocked without containment.

Reuses the legacy browser bridge's visible-text/screenshot/timeout ideas,
not its persistent personal profile, click/type actions or global session.
No browser process, package or network connection is started by this module.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import base64
import hashlib
import ipaddress
from pathlib import Path
import stat
import tempfile
import time
from urllib.parse import urlsplit

from runtime.meta_hackathon.contracts import valid_page_url
from runtime.meta_hackathon.network_admission import _public_ips
from runtime.providers.exact import CancellationToken
from .offline_adapter import FIXTURE_TEXT, FIXTURE_URL, read_fixture


class BrowserReadError(ValueError):
    def __init__(self, code='BROWSER_READ_DENIED'):
        self.code = code
        super().__init__(code)


def require(value, code='BROWSER_READ_DENIED'):
    if not value: raise BrowserReadError(code)


def public_url(url, origins):
    try:
        require(type(url) is str and type(origins) is tuple and bool(origins))
        url.encode('ascii')
        parsed = urlsplit(url); host = parsed.hostname or ''
        require(parsed.scheme == 'https' and parsed.port in (None, 443) and host
            and not parsed.username and not parsed.password and not parsed.fragment and not parsed.query
            and host == parsed.netloc and '%' not in host and '\\' not in url
            and not any(part.startswith('xn--') for part in host.split('.')))
        require(host != 'localhost' and not host.endswith(('.localhost', '.local', '.internal')))
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise BrowserReadError()
        valid_page_url(url, origins)
    except BrowserReadError: raise
    except Exception: raise BrowserReadError() from None


@dataclass(frozen=True)
class DriverReadback:
    final_url: str
    text: str
    screenshot: bytes
    resolved_ips: tuple[str, ...] = ('93.184.216.34',)
    subresources: tuple[str, ...] = ()
    download: bool = False
    service_worker: bool = False
    websocket: bool = False
    status: int = 200


@dataclass(frozen=True)
class ChromeReadResult:
    final_url: str
    text: str
    content_sha256: str
    screenshot_sha256: str
    captured_at_utc: str
    profile_sha256: str
    environment: str = 'OFFLINE_FIXTURE'
    live_verified: bool = False


class FixtureReadDriver:
    """Explicit no-network driver for the one public synthetic document."""
    environment = 'OFFLINE_FIXTURE'

    def __init__(self, *, overrides=None, delay_seconds=0, text=FIXTURE_TEXT):
        self.overrides = dict(overrides or {})
        self.delay_seconds, self.text = delay_seconds, text
        self.read_count = 0
        self.last_profile = None
        self.profile_mode = None

    def read(self, url, profile, cancel, timeout_ms):
        require(url == FIXTURE_URL)
        self.read_count += 1
        self.last_profile = str(profile)
        self.profile_mode = stat.S_IMODE(Path(profile).stat().st_mode)
        require(self.profile_mode == 0o700)
        deadline = time.monotonic()+min(self.delay_seconds, timeout_ms/1000)
        while time.monotonic() < deadline:
            require(not cancel.cancelled, 'BROWSER_STOPPED')
            time.sleep(min(.02, max(0, deadline-time.monotonic())))
        require(self.delay_seconds < timeout_ms/1000, 'BROWSER_TIMEOUT_UNKNOWN')
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9SsAAAAASUVORK5CYII=')
        return replace(DriverReadback(url, self.text, png), **self.overrides)

    def close(self, profile):
        pass


class ChromeReadAdapter:
    """Only read and STOP. No attach-to-existing-session or effect surface."""
    def __init__(self, driver):
        self.driver, self._cancel = driver, None

    def stop(self):
        if self._cancel is not None: self._cancel.cancel()

    def read(self, url, *, allowed_origins, max_chars, timeout_ms, cancel):
        require(type(cancel) is CancellationToken)
        require(not cancel.cancelled, 'BROWSER_STOPPED')
        require(getattr(self.driver, 'environment', None) == 'OFFLINE_FIXTURE',
                'CHROME_LIVE_BLOCKED_CONTAINMENT')
        require(type(max_chars) is int and 200 <= max_chars <= 1600
                and type(timeout_ms) is int and 1000 <= timeout_ms <= 15000)
        public_url(url, allowed_origins)
        self._cancel = cancel
        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix='aioa-meta-browser-fixture-') as profile:
                Path(profile).chmod(0o700)
                try:
                    observed = self.driver.read(url, profile, cancel, timeout_ms)
                    require(not cancel.cancelled, 'BROWSER_STOPPED')
                    require((time.monotonic()-started)*1000 < timeout_ms, 'BROWSER_TIMEOUT_UNKNOWN')
                    require(type(observed) is DriverReadback)
                    public_url(observed.final_url, allowed_origins)
                    require(observed.final_url == url and _public_ips(observed.resolved_ips))
                    require(observed.subresources == () and observed.download is False
                            and observed.service_worker is False and observed.websocket is False
                            and observed.status == 200)
                    require(type(observed.text) is str and 0 < len(observed.text) <= max_chars
                            and type(observed.screenshot) is bytes and 0 < len(observed.screenshot) <= 262144)
                    return ChromeReadResult(url, observed.text,
                        hashlib.sha256(observed.text.encode()).hexdigest(),
                        hashlib.sha256(observed.screenshot).hexdigest(),
                        datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                        hashlib.sha256(profile.encode()).hexdigest())
                finally:
                    self.driver.close(profile)
        except BrowserReadError: raise
        except Exception: raise BrowserReadError('BROWSER_READ_UNKNOWN') from None
        finally:
            self._cancel = None


class OfflineFixtureRead:
    """Typed P01 observer seam; this adapter can only return fixture evidence."""
    def __init__(self, adapter, cancel, clock, source_guard):
        require(type(adapter) is ChromeReadAdapter and type(cancel) is CancellationToken)
        self.adapter, self.cancel, self.clock, self.source_guard = adapter, cancel, clock, source_guard
        self.last_receipt = None

    def __call__(self, task, **kwargs):
        from runtime.core_admission import Capability
        kwargs['admission'].require(kwargs['principal'], Capability.READ, scope=kwargs['scope'])
        require(self.source_guard(), 'BROWSER_SOURCE_DRIFT')
        result = self.adapter.read(task.target_url, allowed_origins=task.allowed_origins,
            max_chars=task.max_chars, timeout_ms=task.timeout_ms, cancel=self.cancel)
        require(self.source_guard(), 'BROWSER_SOURCE_DRIFT')
        kwargs.update(fixture_text=result.text, observed_url=result.final_url,
                      captured_at_utc=result.captured_at_utc, now=self.clock())
        observation = read_fixture(task, **kwargs)
        self.last_receipt = {'task_digest': task.digest, 'owner_scope_digest': task.owner_scope_digest,
            'source_sha': task.source_sha, 'content_sha256': result.content_sha256,
            'screenshot_sha256': result.screenshot_sha256, 'profile_sha256': result.profile_sha256,
            'captured_at_utc': result.captured_at_utc, 'observed_url': result.final_url,
            'environment': 'OFFLINE_FIXTURE', 'live_verified': False}
        return observation
