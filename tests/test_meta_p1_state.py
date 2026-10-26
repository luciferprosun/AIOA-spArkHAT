"""META-P1-03 hermetic offline state-machine tests (stdlib unittest only)."""

from __future__ import annotations

import ast
import hashlib
import pathlib
import unittest
from datetime import datetime, timedelta, timezone

from runtime.browser_agent.offline_adapter import FIXTURE_ORIGIN, FIXTURE_URL
from runtime.browser_agent.offline_state import (
    OfflineState,
    OfflineStateTransitionDenied,
    OfflineTaskState,
)
from runtime.core_admission import Capability, CoreAdmission, LocalOwnerAssignment, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.meta_hackathon.contracts import BrowserTaskV1

SOURCE_SHA = "1998eefd3f9be14cbc06edbe4016cf8148c11961"
DEADLINE = "2026-12-31T23:59:59Z"
NOW = datetime(2026, 6, 1, 13, 0, 0, tzinfo=timezone.utc)
INITIAL = NOW - timedelta(seconds=2)
CAPTURED = "2026-06-01T12:59:59Z"


def make_scope() -> OwnerScope:
    return OwnerScope(tenant_id="t", owner_id="o", space_id="s", slot_id="s1")


OWNER_DIGEST = canonical_sha256(make_scope())


def make_task(owner_digest: str = OWNER_DIGEST) -> BrowserTaskV1:
    return BrowserTaskV1(
        task_id="meta-p1-03-t", owner_scope_digest=owner_digest,
        source_sha=SOURCE_SHA, allowed_origins=(FIXTURE_ORIGIN,),
        target_url=FIXTURE_URL, deadline_utc=DEADLINE,
    )


def make_state(task: BrowserTaskV1 | None = None, owner: str = OWNER_DIGEST,
               sha: str = SOURCE_SHA, timeout_ms: int = 8000) -> OfflineTaskState:
    task = task or make_task()
    return OfflineTaskState(
        task_digest=task.digest, allowed_origins=task.allowed_origins,
        core_owner_scope_digest=owner, core_source_sha=sha,
        task_owner_scope_digest=task.owner_scope_digest,
        task_source_sha=task.source_sha,
        initial_utc=INITIAL,
        deadline_utc=datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        timeout_ms=timeout_ms,
    )


def previewed(**kw) -> OfflineTaskState:
    st = make_state(**kw)
    st.preview(stopped=False, now=NOW)
    return st


class OfflineStateTest(unittest.TestCase):
    def test_success_preview_observe(self) -> None:
        st = make_state()
        self.assertEqual(st.preview(stopped=False, now=NOW), OfflineState.PREVIEWED)
        self.assertEqual(st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                                    captured_at_utc=CAPTURED, stopped=False, now=NOW),
                         OfflineState.OBSERVED)
        self.assertEqual(st.environment, "OFFLINE_FIXTURE")
        self.assertFalse(st.dispatch_allowed)

    def test_timeout_cannot_become_done(self) -> None:
        st = make_state(timeout_ms=1000)
        late = INITIAL + timedelta(seconds=2)
        self.assertEqual(st.preview(stopped=False, now=late), OfflineState.TIMED_OUT)
        with self.assertRaises(OfflineStateTransitionDenied):
            st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                       captured_at_utc=CAPTURED, stopped=False, now=late)
        self.assertEqual(st.state, OfflineState.TIMED_OUT)

    def test_stale_stop_after_observed(self) -> None:
        st = previewed()
        st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                   captured_at_utc=CAPTURED, stopped=False, now=NOW)
        with self.assertRaises(OfflineStateTransitionDenied):
            st.stop()
        self.assertEqual(st.state, OfflineState.OBSERVED)

    def test_cancel_blocks_observe(self) -> None:
        st = make_state()
        st.preview(stopped=False, now=NOW)
        st.cancel()
        self.assertEqual(st.state, OfflineState.CANCELLED)
        with self.assertRaises(OfflineStateTransitionDenied):
            st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                       captured_at_utc=CAPTURED, stopped=False, now=NOW)

    def test_stop_blocks_observe(self) -> None:
        st = make_state()
        st.preview(stopped=False, now=NOW)
        st.stop()
        with self.assertRaises(OfflineStateTransitionDenied):
            st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                       captured_at_utc=CAPTURED, stopped=False, now=NOW)

    def test_off_origin_redirect_denied(self) -> None:
        st = previewed()
        self.assertEqual(st.follow_redirect(redirect_url="https://evil.example.org/x"),
                         OfflineState.DENIED)
        with self.assertRaises(OfflineStateTransitionDenied):
            st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                       captured_at_utc=CAPTURED, stopped=False, now=NOW)

    def test_duplicate_observe_denied(self) -> None:
        st = previewed()
        st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                   captured_at_utc=CAPTURED, stopped=False, now=NOW)
        with self.assertRaises(OfflineStateTransitionDenied):
            st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                       captured_at_utc=CAPTURED, stopped=False, now=NOW)

    def test_wrong_task_digest_denied(self) -> None:
        st = previewed()
        self.assertEqual(st.observe(task_digest="0" * 64, observed_url=FIXTURE_URL,
                                    captured_at_utc=CAPTURED, stopped=False, now=NOW),
                         OfflineState.DENIED)

    def test_concurrent_task_isolation(self) -> None:
        a = previewed()
        b = previewed()
        a.cancel()
        self.assertEqual(b.state, OfflineState.PREVIEWED)
        b.observe(task_digest=b.task_digest, observed_url=FIXTURE_URL,
                  captured_at_utc=CAPTURED, stopped=False, now=NOW)
        self.assertEqual((a.state, b.state),
                         (OfflineState.CANCELLED, OfflineState.OBSERVED))

    def test_age_deadline_and_malformed_owner(self) -> None:
        st = previewed()
        self.assertEqual(st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                                    captured_at_utc="2027-01-01T00:00:00Z",
                                    stopped=False, now=NOW), OfflineState.TIMED_OUT)
        bad_owner = make_state(owner=hashlib.sha256(b"other").hexdigest())
        self.assertEqual(bad_owner.preview(stopped=False, now=NOW), OfflineState.DENIED)
        with self.assertRaises(ValueError):
            OfflineTaskState(
                task_digest="not-a-digest", allowed_origins=(FIXTURE_ORIGIN,),
                core_owner_scope_digest=OWNER_DIGEST, core_source_sha=SOURCE_SHA,
                task_owner_scope_digest=OWNER_DIGEST, task_source_sha=SOURCE_SHA,
                initial_utc=INITIAL,
                deadline_utc=datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
                timeout_ms=8000)

    def test_no_replay_no_live_imports(self) -> None:
        st = previewed()
        st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                   captured_at_utc=CAPTURED, stopped=False, now=NOW)
        with self.assertRaises(OfflineStateTransitionDenied):
            st.preview(stopped=False, now=NOW)
        with self.assertRaises(OfflineStateTransitionDenied):
            st.check_timeout(NOW)
        src = pathlib.Path("runtime/browser_agent/offline_state.py").read_text()
        tree = ast.parse(src)
        mods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0].lower() for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0].lower())
        for banned in ("selenium", "playwright", "browser_bridge", "browser_tools",
                       "socket", "urllib", "http"):
            self.assertNotIn(banned, mods)
        self.assertNotIn("browser_tools", src)

    def test_core_admission_read_only(self) -> None:
        scope = make_scope()
        adm = CoreAdmission(LocalOwnerAssignment(
            scope=scope, allowed_capabilities=frozenset({Capability.READ}),
            hat_ids=frozenset({"h"}), model_binding_ids=frozenset({"m"}),
            operator_approved=True), clock=lambda: NOW)
        principal = adm.local_operator(Capability.READ)
        self.assertTrue(principal is not None)
        self.assertFalse(make_state().dispatch_allowed)


    def test_future_capture_denied(self) -> None:
        st = previewed()
        future = (NOW + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(st.observe(task_digest=st.task_digest, observed_url=FIXTURE_URL,
                                    captured_at_utc=future, stopped=False, now=NOW),
                         OfflineState.DENIED)
        self.assertEqual(st.state, OfflineState.DENIED)


if __name__ == "__main__":
    unittest.main()
