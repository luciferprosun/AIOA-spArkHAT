"""All fixtures are disposable local repos: never touch main, Nebius or Gmail."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import tempfile
import unittest

from runtime.meta_hackathon.worktree_guard import (
    META_PROJECT_BRANCH, META_PROJECT_DISPLAY_NAME,
    MetaCheckoutProof, MetaIsolationError, inspect_meta_checkout,
)
from runtime.meta_hackathon.mcp_offline_plan import preview_mcp_read


REMOTE = "https://github.com/luciferprosun/AIOA-spArkHAT.git"


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


class MetaBranchIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "AIOA-spArkHAT-META"
        self.root.mkdir()
        subprocess.run(["git", "-C", str(self.root), "init", "-q", "-b", META_PROJECT_BRANCH], check=True)
        git(self.root, "config", "user.name", "Meta Test")
        git(self.root, "config", "user.email", "meta-test@example.invalid")
        (self.root / "README.md").write_text("fixture\n")
        git(self.root, "add", "README.md")
        git(self.root, "commit", "-qm", "fixture")
        git(self.root, "remote", "add", "origin", REMOTE)
        self.sha = git(self.root, "rev-parse", "HEAD")

    def check(self, **kwargs):
        return inspect_meta_checkout(
            kwargs.get("path", self.root),
            owner_checkout_root=kwargs.get("owner_checkout_root", self.root),
            expected_meta_sha=kwargs.get("expected_meta_sha", self.sha),
        )

    def test_only_clean_pinned_meta_checkout_admitted_as_observation(self):
        result = self.check()
        self.assertEqual(self.sha, result.source_sha)
        self.assertEqual(META_PROJECT_BRANCH, result.branch)
        self.assertEqual("AIOA METAGuardiansSPARK", META_PROJECT_DISPLAY_NAME)
        self.assertFalse(result.dispatch_allowed)

    def test_main_and_nebius_branches_denied(self):
        for branch in ("meta", "main", "nebius-personal-ai", "codex/final-connect-20261023"):
            with self.subTest(branch=branch):
                git(self.root, "branch", "-m", branch)
                with self.assertRaises(MetaIsolationError):
                    self.check()
                git(self.root, "branch", "-m", META_PROJECT_BRANCH)

    def test_owner_path_mismatch_denied(self):
        other = Path(self.tmp.name) / "AIOA-spArkHAT-Companion"
        other.mkdir()
        with self.assertRaises(MetaIsolationError):
            self.check(owner_checkout_root=other)
        with self.assertRaises(MetaIsolationError):
            self.check(path=other)

    def test_checkout_naming_and_symlink_denied(self):
        renamed = self.root.with_name("AIOA-spArkHAT-Companion")
        self.root.rename(renamed)
        self.root = renamed
        with self.assertRaises(MetaIsolationError):
            self.check()
        alias = Path(self.tmp.name) / "meta-symlink"
        alias.symlink_to(renamed, target_is_directory=True)
        with self.assertRaises(MetaIsolationError):
            self.check(path=alias, owner_checkout_root=alias)

    def test_wrong_and_untrusted_remote_denied(self):
        git(self.root, "remote", "set-url", "origin", "https://github.com/other/private.git")
        with self.assertRaises(MetaIsolationError):
            self.check()

    def test_dirty_repo_rejected(self):
        (self.root / "new-file").write_text("untracked")
        with self.assertRaises(MetaIsolationError):
            self.check()

    def test_pinned_sha_drift_denied(self):
        with self.assertRaises(MetaIsolationError):
            self.check(expected_meta_sha="1"*40)
        with self.assertRaises(MetaIsolationError):
            self.check(expected_meta_sha="broken")

    def test_offline_mcp_read_is_never_execution(self):
        proof = self.check()
        proposal = preview_mcp_read(
            proof, operation="git.status", payload={"short": True},
            task_id="meta-read-001",
        )
        self.assertFalse(proposal.dispatch_allowed)
        self.assertEqual("PREVIEW_ONLY", proposal.status)
        self.assertEqual("NONE", proposal.authority)
        self.assertEqual(proof.source_sha, proposal.meta_source_sha)
        self.assertEqual(64, len(proposal.task_fingerprint))

    def test_effects_and_unverified_reads_denied(self):
        proof = self.check()
        for op in ("patch.request_apply", "recipe.request", "fs.read",
                   "approval.status", "provider.status", "unknown", "git.push"):
            with self.subTest(operation=op), self.assertRaises(MetaIsolationError):
                preview_mcp_read(proof, operation=op, payload={},
                                 task_id="meta-effect-001")

    def test_existing_mcp_read_schema_is_not_bypassed(self):
        proof = self.check()
        for bad in ({"path": "/etc/passwd"}, {"approved": True}, {"short": "yes"}):
            with self.subTest(value=bad), self.assertRaises(MetaIsolationError):
                preview_mcp_read(proof, operation="git.status", payload=bad,
                                 task_id="meta-bad-001")

    def test_only_core_sourced_meta_envelopes(self):
        proof = self.check()
        with self.assertRaises(MetaIsolationError):
            preview_mcp_read(proof, operation="git.status", payload={},
                             task_id="foreign")
        with self.assertRaises(MetaIsolationError):
            preview_mcp_read(replace(proof, branch="main"),
                             operation="git.status", payload={},
                             task_id="meta-read")

if __name__ == "__main__":
    unittest.main()
