"""META-P1-04 OFFLINE network-vector rejection tests (stdlib unittest only).

No sockets, no browser, no network, no effects. Every dispatch_allowed is False.
"""
from dataclasses import replace
from datetime import datetime, timezone
import unittest

from runtime.browser_agent.offline_state import (
    OfflineState,
    OfflineTaskState,
)
from runtime.meta_hackathon.contracts import BrowserTaskV1
from runtime.meta_hackathon.network_admission import (
    BrowserNetworkRequestV1,
    NetworkEffect,
    review_browser_network,
)

NOW = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 28, tzinfo=timezone.utc)
ORIGIN = "https://docs.python.org"
OTHER = "https://www.wikipedia.org"
URL = ORIGIN + "/3/library/urllib.parse.html"
OTHER_URL = OTHER + "/wiki/Python"
TASK = BrowserTaskV1(
    "meta-p1-04", "a" * 64, "6" * 40, (ORIGIN,), URL,
    "2026-10-27T23:00:00Z",
)
PUB = ("8.8.8.8",)


def req(**kw):
    base = BrowserNetworkRequestV1(URL, "GET", "document", True)
    return replace(base, **kw) if kw else base


def screen(r=None, ips=PUB, **kw):
    return review_browser_network(
        TASK, r or req(), ips,
        stopped=kw.get("stopped", False), now=kw.get("now", NOW))


def offline_state(now=NOW):
    return OfflineTaskState(
        task_digest=TASK.digest, allowed_origins=(ORIGIN,),
        core_owner_scope_digest="a" * 64, core_source_sha="6" * 40,
        task_owner_scope_digest="a" * 64, task_source_sha="6" * 40,
        initial_utc=NOW, deadline_utc=datetime(2026, 10, 27, 23, tzinfo=timezone.utc),
        timeout_ms=8000)


class NonGetVectors(unittest.TestCase):
    def test_non_get_denied(self):
        for m in ("POST", "PUT", "DELETE", "HEAD", "PATCH", "CONNECT",
                  "OPTIONS", "get", "Get"):
            with self.subTest(method=m):
                r = screen(req(method=m))
                self.assertEqual("NON_GET_DENIED", r.reason)
                self.assertFalse(r.dispatch_allowed)


class CredentialVectors(unittest.TestCase):
    def test_credentials_denied(self):
        r = screen(req(carries_credentials=True))
        self.assertEqual("CREDENTIALS_DENIED", r.reason)
        self.assertFalse(r.dispatch_allowed)


class PrivateIpVectors(unittest.TestCase):
    def test_private_ipv4_ipv6_mapped_denied(self):
        bad = [("10.0.0.1",), ("172.16.5.4",), ("192.168.0.1",),
               ("127.0.0.1",), ("169.254.169.254",), ("0.0.0.0",),
               ("::1",), ("fe80::1",), ("fc00::1",),
               ("::ffff:10.0.0.1",), ("::ffff:127.0.0.1",),
               ("::ffff:8.8.8.8",), ("8.8.8.8", "10.0.0.9"),
               ("ff02::1",), ("ff0e::1",), ("224.0.0.1",),
               ("239.255.255.250",),
               ("8.8.8.8", "ff02::1"), ("8.8.8.8", "239.255.255.250")]
        for ips in bad:
            with self.subTest(ips=ips):
                r = screen(ips=ips)
                self.assertEqual("UNSAFE_DNS_RESPONSE", r.reason)
                self.assertFalse(r.dispatch_allowed)


class PathMismatchVectors(unittest.TestCase):
    def test_mismatched_target_path_denied(self):
        for u in (ORIGIN + "/3/index.html",
                  ORIGIN + "/3/library/urllib.parse.html/",
                  URL + "x"):
            with self.subTest(url=u):
                r = screen(req(url=u))
                self.assertIn(r.reason, ("URL_OUTSIDE_SCOPE",
                                         "UNPLANNED_NAVIGATION_DENIED"))
                self.assertFalse(r.dispatch_allowed)


class RedirectVectors(unittest.TestCase):
    def test_cross_origin_redirect_denied_offline_state(self):
        st = offline_state()
        st.preview(stopped=False, now=NOW)
        self.assertEqual(OfflineState.DENIED,
                         st.follow_redirect(redirect_url=OTHER_URL))
        self.assertFalse(st.dispatch_allowed)

    def test_same_origin_wrong_path_redirect_is_not_auto_followed(self):
        # Admission layer requires exact target_url match; any other
        # same-origin path is UNPLANNED_NAVIGATION_DENIED here.
        r = screen(req(url=ORIGIN + "/3/index.html"))
        self.assertEqual("UNPLANNED_NAVIGATION_DENIED", r.reason)
        self.assertFalse(r.dispatch_allowed)

    def test_offline_state_redirect_stays_previewed_on_same_plan(self):
        st = offline_state()
        st.preview(stopped=False, now=NOW)
        # follow_redirect only revalidates scope; same plan URL stays PREVIEWED.
        self.assertEqual(OfflineState.PREVIEWED,
                         st.follow_redirect(redirect_url=URL))
        self.assertFalse(st.dispatch_allowed)


class StopDeadlineVectors(unittest.TestCase):
    def test_stop_denied(self):
        r = screen(stopped=True)
        self.assertEqual("STOP", r.reason)
        self.assertFalse(r.dispatch_allowed)

    def test_expired_deadline_denied(self):
        r = screen(now=LATER)
        self.assertEqual("TASK_EXPIRED", r.reason)
        self.assertFalse(r.dispatch_allowed)


class WouldBeAllowedStillNoDispatch(unittest.TestCase):
    def test_preview_effect_still_no_dispatch(self):
        r = screen()
        self.assertEqual(NetworkEffect.CORE_AND_EGRESS_POLICY_REQUIRED, r.effect)
        self.assertFalse(r.dispatch_allowed)


class SyntheticRedirectDenial(unittest.TestCase):
    def test_synthetic_redirect_out_of_scope_denied(self):
        st = offline_state()
        st.preview(stopped=False, now=NOW)
        self.assertEqual(OfflineState.DENIED,
                         st.follow_redirect(redirect_url=OTHER_URL))
        self.assertFalse(st.dispatch_allowed)


class ServiceWorkerSubresourceVectors(unittest.TestCase):
    def test_subresource_frame_serviceworker_denied(self):
        cases = [dict(resource_type="service_worker"),
                 dict(resource_type="script"),
                 dict(resource_type="fetch"),
                 dict(is_main_frame=False)]
        for kw in cases:
            with self.subTest(kw=kw):
                r = screen(req(**kw))
                self.assertEqual("SUBRESOURCE_OR_FRAME_DENIED", r.reason)
                self.assertFalse(r.dispatch_allowed)


if __name__ == "__main__":
    unittest.main()
