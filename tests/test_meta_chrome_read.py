"""P02 injected browser contract. No actual browser or external networking."""
from dataclasses import replace
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

from runtime.browser_agent.offline_adapter import FIXTURE_URL
from runtime.providers.exact import CancellationToken


class ChromeReadTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.browser_agent.chrome_read_adapter'),
                             'bounded injected browser adapter missing')
        self.api = importlib.import_module('runtime.browser_agent.chrome_read_adapter')

    def test_offline_profile_is_private_temporary_and_receipt_has_real_hashes(self):
        driver = self.api.FixtureReadDriver()
        adapter = self.api.ChromeReadAdapter(driver)
        result = adapter.read(FIXTURE_URL, allowed_origins=('https://docs.example.org',),
                              max_chars=1600, timeout_ms=8000, cancel=CancellationToken())
        self.assertEqual('OFFLINE_FIXTURE', result.environment)
        self.assertFalse(result.live_verified)
        self.assertEqual(64, len(result.screenshot_sha256))
        self.assertEqual(64, len(result.content_sha256))
        self.assertFalse(Path(driver.last_profile).exists())
        self.assertEqual(0o700, driver.profile_mode)

    def test_private_or_noncanonical_targets_are_denied_without_driver(self):
        for url in ('file:///etc/passwd', 'data:text/plain,x', 'javascript:alert(1)',
                    'http://localhost/x', 'https://127.0.0.1/x', 'https://10.0.0.1/x',
                    'https://169.254.169.254/x', 'https://[::1]/x', 'https://xn--example-9d0b.org/x'):
            driver = self.api.FixtureReadDriver(); adapter = self.api.ChromeReadAdapter(driver)
            with self.subTest(url=url), self.assertRaises(self.api.BrowserReadError):
                adapter.read(url, allowed_origins=(url.rsplit('/', 1)[0],), max_chars=1600,
                             timeout_ms=8000, cancel=CancellationToken())
            self.assertEqual(0, driver.read_count)

    def test_redirect_private_dns_subresource_download_and_serviceworker_deny(self):
        for change in ({'final_url': 'https://evil.example/x'}, {'resolved_ips': ('127.0.0.1',)},
                       {'subresources': ('https://evil.example/script.js',)}, {'download': True},
                       {'service_worker': True}, {'websocket': True}):
            driver = self.api.FixtureReadDriver(overrides=change); adapter = self.api.ChromeReadAdapter(driver)
            with self.subTest(change=change), self.assertRaises(self.api.BrowserReadError):
                adapter.read(FIXTURE_URL, allowed_origins=('https://docs.example.org',), max_chars=1600,
                             timeout_ms=8000, cancel=CancellationToken())

    def test_live_driver_without_containment_never_launches(self):
        driver = self.api.FixtureReadDriver(); driver.environment = 'LIVE_BROWSER_UNVERIFIED'
        adapter = self.api.ChromeReadAdapter(driver)
        with self.assertRaisesRegex(self.api.BrowserReadError, 'CONTAINMENT'):
            adapter.read(FIXTURE_URL, allowed_origins=('https://docs.example.org',), max_chars=1600,
                         timeout_ms=8000, cancel=CancellationToken())
        self.assertEqual(0, driver.read_count)

    def test_stop_before_read_has_no_dispatch_and_no_write_surface(self):
        driver = self.api.FixtureReadDriver(); adapter = self.api.ChromeReadAdapter(driver)
        cancel = CancellationToken(); cancel.cancel()
        with self.assertRaisesRegex(self.api.BrowserReadError, 'STOPPED'):
            adapter.read(FIXTURE_URL, allowed_origins=('https://docs.example.org',), max_chars=1600,
                         timeout_ms=8000, cancel=cancel)
        self.assertEqual(0, driver.read_count)
        for name in ('click', 'type', 'submit', 'shell', 'send'): self.assertFalse(hasattr(adapter, name))


if __name__ == '__main__': unittest.main()
