"""META-P1-02 hermetic offline adapter tests (stdlib unittest only)."""

from __future__ import annotations

import ast
import hashlib
import pathlib
import unittest
from datetime import datetime, timezone

from runtime.browser_agent.offline_adapter import (
    FIXTURE_CAPTURED_AT_UTC,
    FIXTURE_ORIGIN,
    FIXTURE_TEXT,
    FIXTURE_URL,
    OfflineAdapterDenied,
    OfflineFixtureAdapter,
    preview_task,
    read_fixture,
)
from runtime.core_admission import (
    Capability,
    CoreAdmission,
    LocalOwnerAssignment,
    OwnerScope,
)
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.meta_hackathon.contracts import BrowserTaskV1
from runtime.meta_hackathon.policy import GateEffect, screen_observation

SOURCE_SHA = "1998eefd3f9be14cbc06edbe4016cf8148c11961"
OTHER_SHA = "0" * 40
OTHER_DIGEST = hashlib.sha256(b"meta-p1-02-other-scope").hexdigest()
FORGED_DIGEST = hashlib.sha256(b"meta-p1-02-forged-scope").hexdigest()
DEADLINE = "2026-12-31T23:59:59Z"
NOW = datetime(2026, 6, 1, 13, 0, 0, tzinfo=timezone.utc)


def make_scope() -> OwnerScope:
    return OwnerScope(
        tenant_id="tenant-t", owner_id="owner-o", space_id="space-s", slot_id="slot-1"
    )


OWNER_DIGEST = canonical_sha256(make_scope())


def make_admission(scope: OwnerScope) -> CoreAdmission:
    assignment = LocalOwnerAssignment(
        scope=scope,
        allowed_capabilities=frozenset({Capability.READ}),
        hat_ids=frozenset({"hat-1"}),
        model_binding_ids=frozenset({"model-1"}),
        operator_approved=True,
    )
    return CoreAdmission(assignment, clock=lambda: NOW)


def make_task(owner_digest: str = OWNER_DIGEST) -> BrowserTaskV1:
    return BrowserTaskV1(
        task_id="meta-p1-02-fixture",
        owner_scope_digest=owner_digest,
        source_sha=SOURCE_SHA,
        allowed_origins=(FIXTURE_ORIGIN,),
        target_url=FIXTURE_URL,
        deadline_utc=DEADLINE,
    )


class OfflineAdapterTest(unittest.TestCase):
    def test_positive_fixture_read(self) -> None:
        scope = make_scope()
        admission = make_admission(scope)
        principal = admission.local_operator(Capability.READ)
        obs = read_fixture(
            make_task(),
            admission=admission,
            principal=principal,
            scope=scope,
            core_owner_scope_digest=OWNER_DIGEST,
            core_source_sha=SOURCE_SHA,
            stopped=False,
            now=NOW,
        )
        self.assertEqual(obs.status, "OBSERVED")
        self.assertEqual(obs.environment, "OFFLINE_FIXTURE")
        self.assertEqual(obs.observed_url, FIXTURE_URL)
        self.assertEqual(
            obs.content_sha256, hashlib.sha256(FIXTURE_TEXT.encode()).hexdigest()
        )
        review = screen_observation(obs, make_task())
        self.assertEqual(review.effect, GateEffect.UNVERIFIED_EVIDENCE)
        self.assertFalse(review.dispatch_allowed)

    def test_absent_principal_denied(self) -> None:
        scope = make_scope()
        with self.assertRaises(OfflineAdapterDenied):
            read_fixture(
                make_task(),
                admission=make_admission(scope),
                principal=None,  # type: ignore[arg-type]
                scope=scope,
                core_owner_scope_digest=OWNER_DIGEST,
                core_source_sha=SOURCE_SHA,
                stopped=False,
                now=NOW,
            )

    def test_forged_principal_denied(self) -> None:
        scope = make_scope()
        other = CoreAdmission(
            LocalOwnerAssignment(
                scope=scope,
                allowed_capabilities=frozenset({Capability.READ}),
                hat_ids=frozenset({"hat-1"}),
                model_binding_ids=frozenset({"model-1"}),
                operator_approved=True,
            ),
            clock=lambda: NOW,
        )
        forged = other.local_operator(Capability.READ)
        with self.assertRaises(OfflineAdapterDenied):
            read_fixture(
                make_task(),
                admission=make_admission(scope),
                principal=forged,
                scope=scope,
                core_owner_scope_digest=OWNER_DIGEST,
                core_source_sha=SOURCE_SHA,
                stopped=False,
                now=NOW,
            )

    def test_stop_denied(self) -> None:
        scope = make_scope()
        admission = make_admission(scope)
        with self.assertRaises(OfflineAdapterDenied):
            read_fixture(
                make_task(),
                admission=admission,
                principal=admission.local_operator(Capability.READ),
                scope=scope,
                core_owner_scope_digest=OWNER_DIGEST,
                core_source_sha=SOURCE_SHA,
                stopped=True,
                now=NOW,
            )

    def test_owner_drift_denied(self) -> None:
        scope = make_scope()
        admission = make_admission(scope)
        with self.assertRaises(OfflineAdapterDenied):
            read_fixture(
                make_task(),
                admission=admission,
                principal=admission.local_operator(Capability.READ),
                scope=scope,
                core_owner_scope_digest=OTHER_DIGEST,
                core_source_sha=SOURCE_SHA,
                stopped=False,
                now=NOW,
            )

    def test_consistent_forgery_denied(self) -> None:
        # Adversarial: task owner_digest and supplied core digest are both
        # forged consistently, but the admitted OwnerScope is real -> DENY.
        scope = make_scope()
        admission = make_admission(scope)
        self.assertNotEqual(FORGED_DIGEST, canonical_sha256(scope))
        with self.assertRaises(OfflineAdapterDenied):
            read_fixture(
                make_task(owner_digest=FORGED_DIGEST),
                admission=admission,
                principal=admission.local_operator(Capability.READ),
                scope=scope,
                core_owner_scope_digest=FORGED_DIGEST,
                core_source_sha=SOURCE_SHA,
                stopped=False,
                now=NOW,
            )

    def test_sha_drift_denied(self) -> None:
        scope = make_scope()
        admission = make_admission(scope)
        with self.assertRaises(OfflineAdapterDenied):
            read_fixture(
                make_task(),
                admission=admission,
                principal=admission.local_operator(Capability.READ),
                scope=scope,
                core_owner_scope_digest=OWNER_DIGEST,
                core_source_sha=OTHER_SHA,
                stopped=False,
                now=NOW,
            )

    def test_wrong_origin_denied(self) -> None:
        scope = make_scope()
        admission = make_admission(scope)
        with self.assertRaises(OfflineAdapterDenied):
            read_fixture(
                make_task(),
                admission=admission,
                principal=admission.local_operator(Capability.READ),
                scope=scope,
                core_owner_scope_digest=OWNER_DIGEST,
                core_source_sha=SOURCE_SHA,
                stopped=False,
                now=NOW,
                observed_url="https://other.example.org/elsewhere",
            )

    def test_content_bounds_denied(self) -> None:
        scope = make_scope()
        admission = make_admission(scope)
        for bad in ("", "x" * 3001):
            with self.assertRaises(OfflineAdapterDenied, msg=f"len={len(bad)}"):
                read_fixture(
                    make_task(),
                    admission=admission,
                    principal=admission.local_operator(Capability.READ),
                    scope=scope,
                    core_owner_scope_digest=OWNER_DIGEST,
                    core_source_sha=SOURCE_SHA,
                    stopped=False,
                    now=NOW,
                    fixture_text=bad,
                )

    def test_digest_mismatch_denied(self) -> None:
        scope = make_scope()
        admission = make_admission(scope)
        with self.assertRaises(OfflineAdapterDenied):
            read_fixture(
                make_task(),
                admission=admission,
                principal=admission.local_operator(Capability.READ),
                scope=scope,
                core_owner_scope_digest=OWNER_DIGEST,
                core_source_sha=SOURCE_SHA,
                stopped=False,
                now=NOW,
                expected_content_sha256="0" * 64,
            )

    def test_expired_deadline_denied(self) -> None:
        scope = make_scope()
        admission = make_admission(scope)
        late = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        with self.assertRaises(OfflineAdapterDenied):
            read_fixture(
                make_task(),
                admission=admission,
                principal=admission.local_operator(Capability.READ),
                scope=scope,
                core_owner_scope_digest=OWNER_DIGEST,
                core_source_sha=SOURCE_SHA,
                stopped=False,
                now=late,
            )

    def test_future_capture_denied(self) -> None:
        # Fixture captured_at_utc in the future relative to trusted now,
        # but still within the task deadline -> DENY.
        scope = make_scope()
        admission = make_admission(scope)
        with self.assertRaises(OfflineAdapterDenied):
            read_fixture(
                make_task(),
                admission=admission,
                principal=admission.local_operator(Capability.READ),
                scope=scope,
                core_owner_scope_digest=OWNER_DIGEST,
                core_source_sha=SOURCE_SHA,
                stopped=False,
                now=NOW,
                captured_at_utc="2026-06-01T14:00:00Z",
            )

    def test_dispatch_always_false(self) -> None:
        gate = preview_task(
            make_task(),
            core_owner_scope_digest=OWNER_DIGEST,
            core_source_sha=SOURCE_SHA,
            stopped=False,
            now=NOW,
        )
        self.assertFalse(gate.dispatch_allowed)
        stopped_gate = preview_task(
            make_task(),
            core_owner_scope_digest=OWNER_DIGEST,
            core_source_sha=SOURCE_SHA,
            stopped=True,
            now=NOW,
        )
        self.assertFalse(stopped_gate.dispatch_allowed)
        self.assertFalse(OfflineFixtureAdapter().dispatch_allowed)

    def test_no_browser_import(self) -> None:
        src = pathlib.Path("runtime/browser_agent/offline_adapter.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        banned = {"selenium", "playwright", "browser_bridge"}
        found_imports: set[str] = set()
        dynamic_imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found_imports.add(alias.name.split(".")[0].lower())
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    found_imports.add(node.module.split(".")[0].lower())
            elif isinstance(node, ast.Call):
                func = node.func
                is_import_call = (
                    isinstance(func, ast.Name)
                    and func.id in ("__import__", "import_module")
                ) or (
                    isinstance(func, ast.Attribute) and func.attr == "import_module"
                )
                if is_import_call and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        dynamic_imports.append(first.value.split(".")[0].lower())
        for mod in banned:
            self.assertNotIn(mod, found_imports)
            self.assertNotIn(mod, dynamic_imports)
        self.assertEqual(FIXTURE_CAPTURED_AT_UTC, "2026-06-01T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
