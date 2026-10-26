"""META-G2 preparation: offline route/DNS guard tests, no sockets or browser."""
from dataclasses import replace
from datetime import datetime, timezone
import unittest

from runtime.meta_hackathon.contracts import BrowserTaskV1, MetaContractError
from runtime.meta_hackathon.network_admission import (
    BrowserNetworkRequestV1, NetworkEffect, review_browser_network,
)

NOW = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)
ORIGIN = "https://docs.python.org"
URL = ORIGIN + "/3/library/urllib.parse.html"
TASK = BrowserTaskV1(
    "meta-browser-001", "a"*64, "1"*40, (ORIGIN,), URL,
    "2026-10-27T23:00:00Z",
)


def req(**kwargs):
    return replace(BrowserNetworkRequestV1(URL, "GET", "document", True), **kwargs)


def screen(r=None, ips=("93.184.216.34",), *, now=NOW):
    return review_browser_network(TASK, r or req(), ips, stopped=False, now=now)


class NetworkAdmissionTests(unittest.TestCase):
    def test_public_read_is_still_only_preview(self):
        result = screen()
        self.assertEqual(NetworkEffect.CORE_AND_EGRESS_POLICY_REQUIRED, result.effect)
        self.assertFalse(result.dispatch_allowed)
        self.assertEqual(TASK.digest, result.task_digest)

    def test_stop_and_expiry_fail_closed(self):
        self.assertEqual("STOP", review_browser_network(
            TASK, req(), ["8.8.8.8"], stopped=True, now=NOW).reason)
        later = datetime(2026, 10, 28, tzinfo=timezone.utc)
        self.assertEqual("TASK_EXPIRED", screen(now=later).reason)

    def test_no_other_http_methods_even_on_allowed_host(self):
        for method in ("POST","PUT","DELETE","HEAD","PATCH","CONNECT","OPTIONS","get"):
            with self.subTest(method=method):
                self.assertEqual("NON_GET_DENIED", screen(req(method=method)).reason)

    def test_subresources_and_iframes_blocked(self):
        for typ in ("image", "script", "stylesheet", "font", "xhr", "fetch", "websocket"):
            with self.subTest(resource=typ):
                self.assertEqual("SUBRESOURCE_OR_FRAME_DENIED",
                                 screen(req(resource_type=typ)).reason)
        self.assertEqual("SUBRESOURCE_OR_FRAME_DENIED",
                         screen(req(is_main_frame=False)).reason)

    def test_never_accept_cookies_or_authorization_forwarding(self):
        self.assertEqual("CREDENTIALS_DENIED",
                         screen(req(carries_credentials=True)).reason)

    def test_scope_and_redirects_fail_closed(self):
        for url in ("https://www.wikipedia.org/wiki/Python",
                    "https://docs.python.org/3/index.html",
                    URL + "?query=secret",
                    URL + "#token",
                    "http://docs.python.org/3/library/urllib.parse.html",
                    "https://docs.python.org.evil.com/3/library/urllib.parse.html",
                    "https://127.0.0.1/admin",
                    "file:///etc/passwd"):
            with self.subTest(url=url):
                self.assertIn(screen(req(url=url)).reason,
                              ("URL_OUTSIDE_SCOPE", "UNPLANNED_NAVIGATION_DENIED"))

    def test_private_loopback_linklocal_reserved_and_mixed_dns_denied(self):
        bad = [("127.0.0.1",), ("10.0.0.1",), ("172.16.0.1",),
               ("192.168.1.1",), ("169.254.169.254",), ("::1",), ("fc00::1",),
               ("192.0.2.1",), ("93.184.216.34", "10.0.0.9"),
               ("::ffff:127.0.0.1",)]
        for ips in bad:
            with self.subTest(ips=ips):
                self.assertEqual("UNSAFE_DNS_RESPONSE", screen(ips=ips).reason)

    def test_invalid_or_missing_dns_fail_closed(self):
        for ips in ((), [], ("invalid",), ("999.1.1.1",), (True,),
                    tuple(["8.8.8.8"] * 17), "8.8.8.8", None):
            with self.subTest(value=ips):
                self.assertEqual("UNSAFE_DNS_RESPONSE", screen(ips=ips).reason)

    def test_known_ipv4_and_ipv6_do_not_grant_authority(self):
        for ips in (("8.8.8.8",), ("2606:4700:4700::1111",),
                    ("8.8.8.8", "1.1.1.1")):
            with self.subTest(ips=ips):
                self.assertEqual(NetworkEffect.CORE_AND_EGRESS_POLICY_REQUIRED,
                                 screen(ips=ips).effect)
                self.assertFalse(screen(ips=ips).dispatch_allowed)

    def test_missing_and_invalid_host_metadata_rejected(self):
        for change in ({"is_main_frame": "True"}, {"carries_credentials": 1},
                       {"method": ""}, {"resource_type": None}, {"url": None}):
            with self.subTest(change=change), self.assertRaises(MetaContractError):
                req(**change)

    def test_untrusted_stop_type_denied(self):
        with self.assertRaisesRegex(MetaContractError, "META_NETWORK_INPUT_DENIED"):
            review_browser_network(TASK, req(), ("8.8.8.8",), stopped="false", now=NOW)

    def test_naive_clock_rejected(self):
        with self.assertRaisesRegex(MetaContractError, "META_CLOCK_DENIED"):
            screen(now=datetime(2026, 10, 26, 20))

    def test_fake_browser_claim_does_not_create_capability(self):
        evil = req(url=URL, resource_type="document", method="GET")
        self.assertFalse(screen(evil).dispatch_allowed)


if __name__ == "__main__":
    unittest.main()
