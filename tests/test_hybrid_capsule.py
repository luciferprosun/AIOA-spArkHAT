"""Capsule advice cannot replace canonical validation or owner admission."""

import importlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from q09_support import Fixture
from test_hybrid_repair import DirectoryProducer, FaultBackend

from runtime.core_admission import Capability
from runtime.mission import repair
from runtime.mission.patchset import observe_source
from runtime.mission.worker import CandidateFile, CandidatePatch, Task
from runtime.mobile_gateway.wire import Identity


class CapsuleTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("runtime.mission.patch_capsule")
        except ModuleNotFoundError:
            self.fail("Core patch capsule is not implemented")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "base"
        self.base.mkdir(mode=0o700)
        (self.base / "calc.py").write_text("def add(a,b):\n    return a-b\n")
        (self.base / "calc.py").chmod(0o644)
        self.fx = Fixture(self.root / "core.json")
        self.addCleanup(self.fx.close)
        self.source = observe_source(
            self.base,
            repository_id="repo-1",
            workspace_id="workspace-1",
            source_base_sha="a" * 40,
        )
        self.task = Task(
            "task-1", "run-1", "workspace-1", "repo-1", "a" * 40, "Fix addition.", 200
        )
        self.identity = Identity(ec.generate_private_key(ec.SECP256R1()))

    def capsule(self):
        api = self.api()
        return api.ExecutionCapsule(
            "task-1",
            "run-1",
            "workspace-1",
            "repo-1",
            "worker-1",
            "a" * 40,
            "b" * 64,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            "f" * 64,
            "1" * 64,
            "2" * 64,
            ("sha256:" + "3" * 64, "sha256:" + "4" * 64, "sha256:" + "5" * 64),
            ("6" * 64, "7" * 64, "8" * 64),
            100,
            180,
            "sha256:" + "9" * 64,
            "revision-1",
        )

    def test_capsule_is_inert_canonical_and_detects_frozen_tamper(self):
        capsule = self.capsule()
        self.assertEqual(capsule.authority, "NONE")
        self.assertEqual(len(capsule.digest), 64)
        from runtime.mobile_gateway.wire import verify

        verify(
            self.identity.spki, self.identity.sign(capsule.payload()), capsule.payload()
        )
        object.__setattr__(capsule, "repository_id", "other")
        with self.assertRaises(ValueError):
            capsule.verify_digest()

    def test_capsule_denies_bool_time_wide_window_duplicate_proof_and_bad_target(self):
        capsule = self.capsule()
        for changes in (
            {"issued_at": True},
            {"expires_at": 100},
            {"expires_at": 401},
            {"target_fingerprint": "main"},
            {"validation_warrants": capsule.validation_warrants[:2]},
            {"validation_receipts": ("6" * 64,) * 3},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(capsule, **changes)

    def test_one_core_and_existing_signing_identity_are_required(self):
        api = self.api()
        for journal, identity in (({}, self.identity), (self.fx.journal, None)):
            with self.assertRaises(ValueError):
                api.CorePatchCapsules(
                    journal, identity, source_probe=lambda: self.source
                )

    def test_parser_success_without_core_evidence_cannot_create_capsule(self):
        api = self.api()
        producer = DirectoryProducer(
            repair,
            self.base,
            self.root,
            self.task,
            (
                CandidatePatch(
                    (CandidateFile("calc.py", "def add(a,b):\n    return a+b\n"),)
                ),
            ),
        )
        result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
            task=self.task,
            source=self.source,
            base_root=self.base,
            producer=producer,
            validator=FaultBackend(repair, ["PASS"]),
        )
        self.assertEqual(result.status, "PATCH_READY")
        service = api.CorePatchCapsules(
            self.fx.journal, self.identity, source_probe=lambda: self.source
        )
        before = self.fx.path.read_bytes() if hasattr(self.fx, "path") else None
        with self.assertRaises(ValueError):
            service.prepare(
                self.fx.p(),
                task=self.task,
                source=self.source,
                base_root=self.base,
                final_root=self.root / "attempt-0",
                result=result,
                target_fingerprint=self.fx.warrant.target_fingerprint,
                target_revision="revision-1",
                expires_at=180,
            )
        if before is not None:
            self.assertEqual(before, self.fx.path.read_bytes())

    def test_unadmitted_principal_is_denied_before_source_probe(self):
        api = self.api()
        calls = []
        service = api.CorePatchCapsules(
            self.fx.journal, self.identity, source_probe=lambda: calls.append(1)
        )
        for principal in (
            None,
            {"approved": True},
            self.fx.core.critic_candidate(),
            self.fx.p(Capability.READ),
        ):
            with self.assertRaises(ValueError):
                service.prepare(
                    principal,
                    task=None,
                    source=None,
                    base_root=None,
                    final_root=None,
                    result=None,
                    target_fingerprint=None,
                    target_revision=None,
                    expires_at=180,
                )
        self.assertEqual(calls, [])

    def test_transaction_denial_keeps_a_typed_public_failure(self):
        api = self.api()
        service = api.CorePatchCapsules(
            self.fx.journal, self.identity, source_probe=lambda: self.source
        )
        with self.assertRaises(ValueError):
            service.approve(self.fx.p(Capability.OWNER_APPROVAL), "a" * 64, None)


if __name__ == "__main__":
    unittest.main()
