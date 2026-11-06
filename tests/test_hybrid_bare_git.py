"""Existing CoreRemoteGitRoute with real objects in a disposable bare repo.

Only this test transport runs Git. The production API/route remains unchanged.
PR metadata is a fixture; no request reaches GitHub.
"""

import base64
import json
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import test_github_remote_execution as protocol
from cryptography.hazmat.primitives.asymmetric import ec
from q09_support import Fixture

from lab.archaioa.authority import Money
from runtime.core_admission import Capability
from runtime.mcp_bridge.github_remote import PREFIX
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.git_publish import CoreRemoteGitRoute, GitTreeSnapshot, git_object
from runtime.mission.warrant import approval_digest
from runtime.mobile_gateway.wire import Identity, verify


class BareGitTests(unittest.TestCase):
    def git(self, *args, data=None):
        command = ["/usr/bin/git", "--git-dir=" + str(self.bare), *args]
        result = subprocess.run(
            command,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        if result.returncode:
            raise ValueError("FIXTURE_GIT_COMMAND_FAILED")
        return result.stdout

    def object(self, kind, data):
        return (
            self.git("hash-object", "-w", "-t", kind, "--stdin", data=data)
            .decode()
            .strip()
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bare = self.root / "remote.git"
        subprocess.run(
            ["/usr/bin/git", "init", "--bare", "--initial-branch=main", str(self.bare)],
            capture_output=True,
            check=True,
            timeout=10,
        )
        self.p = protocol.RemoteExecutionTests()
        self.p.setUp()
        empty = self.object("tree", b"")
        self.base = self.object(
            "commit",
            (
                "tree "
                + empty
                + "\nauthor Fixture <fixture@example.invalid> 100 +0000\n"
                "committer Fixture <fixture@example.invalid> 100 +0000\n\nInitial fixture\n"
            ).encode(),
        )
        self.git("update-ref", "refs/heads/main", self.base)
        self.p.plan = replace(
            self.p.plan,
            files=dict(self.p.plan.files),
            base_sha=self.base,
            source_sha=self.base,
        )
        self.p.commit = self.p.plan.commit_sha_for_tree(self.p.tree.sha)
        self.fx = Fixture(self.root / "core.json")
        self.addCleanup(self.fx.close)
        self.identity = Identity(ec.generate_private_key(ec.SECP256R1()))
        self.posts = []
        self.lost_ack = False
        self.factories = 0
        self.route = CoreRemoteGitRoute(
            self.fx.journal,
            plan=self.p.plan,
            base=self.p.base,
            identity=self.identity,
            api_factory=self.factory,
            check=self.p.check,
            target_guard=nullcontext,
            mode="OFFLINE_FIXTURE",
        )
        op = self.route.operation(self.fx.p().actor_session_id, 1)
        self.fx.operation = op
        scope = replace(
            self.fx.warrant.authority_scope,
            operation_classes=(op["operation_class"],),
            target_scope=op["target_fingerprint"],
            monetary_ceiling=Money(Decimal(0), "USD"),
            expires_at=self.fx.warrant.issued_at + timedelta(seconds=240),
        )
        w = replace(
            self.fx.warrant,
            operation_class=op["operation_class"],
            authority_scope=scope,
            target_fingerprint=op["target_fingerprint"],
            expected_target_revision=op["expected_target_revision"],
            decision_dependency_root=self.route.dependency_root,
            money_reservation_id="NONE",
            operation_hash="sha256:" + canonical_sha256(op),
            expires_at=scope.expires_at,
        )
        self.fx.warrant = replace(w, approval_digest=approval_digest(w))
        self.fx.request = replace(
            self.fx.request,
            money_nano=0,
            request_digest=canonical_sha256(op),
            risk_units=1,
        )
        self.fx.init()
        self.p.marker_assertion = self.require_marker

    def require_marker(self):
        from runtime.memory_patch.persistence.ports import RecordKind

        self.assertTrue(
            self.fx.journal._run(
                self.fx.p(Capability.READ),
                Capability.READ,
                lambda tx: any(
                    r.payload.get("state") == "GITHUB_STEP_UNKNOWN"
                    for r in tx.scan(RecordKind.OPERATION, limit=1024)
                ),
            )
        )

    def snapshot(self, sha):
        entries = {}
        for row in self.git("ls-tree", "-r", "-t", "-z", sha).split(b"\0"):
            if not row:
                continue
            metadata, name = row.split(b"\t", 1)
            mode, kind, object_id = metadata.decode().split()
            entries[name.decode()] = (mode, kind, object_id)
        return GitTreeSnapshot(sha, entries)

    def transport(self, method, path, payload, bearer, cancel, timeout):
        # Existing fixture supplies only fixed repository metadata and PR data.
        # Object/ref responses below always come from fresh Git reads.
        if method == "POST":
            from runtime.memory_patch.persistence.ports import RecordKind

            self.assertTrue(
                self.fx.journal._run(
                    self.fx.p(Capability.READ),
                    Capability.READ,
                    lambda tx: any(
                        r.payload.get("state") == "GITHUB_STEP_UNKNOWN"
                        for r in tx.scan(RecordKind.OPERATION, limit=1024)
                    ),
                )
            )
            self.posts.append(path)
            if path.endswith("/trees"):
                blob = self.object("blob", self.p.plan.files["agent-demo/proposal.py"])
                child = self.object(
                    "tree", b"100644 proposal.py\0" + bytes.fromhex(blob)
                )
                self.assertEqual(
                    self.p.tree.sha,
                    self.object("tree", b"40000 agent-demo\0" + bytes.fromhex(child)),
                )
            elif path.endswith("/commits"):
                raw = (
                    "tree " + self.p.tree.sha + "\nparent " + self.base + "\n"
                ).encode()
                identity = (
                    b"AIOA Core <aioa-core@aioa.invalid> "
                    + str(self.p.plan.issued_at).encode()
                    + b" +0000"
                )
                raw += (
                    b"author "
                    + identity
                    + b"\ncommitter "
                    + identity
                    + b"\n\n"
                    + self.p.plan.message.encode()
                )
                self.assertEqual(self.p.commit, self.object("commit", raw))
            elif path.endswith("/refs"):
                self.git(
                    "update-ref",
                    "refs/heads/" + self.p.plan.branch,
                    self.p.commit,
                    "0" * 40,
                )
            result = self.p.transport(method, path, payload, bearer, cancel, timeout)
            if self.lost_ack and path.endswith("/pulls"):
                raise TimeoutError("OFFLINE_ACK_LOST_AFTER_FIXTURE_PR")
            return result
        if path == PREFIX + "/git/ref/heads/main":
            sha = self.git("rev-parse", "refs/heads/main").decode().strip()
            return 200, json.dumps(
                {"ref": "refs/heads/main", "object": {"type": "commit", "sha": sha}}
            ).encode()
        if path.startswith(PREFIX + "/git/ref/heads/"):
            try:
                sha = (
                    self.git("rev-parse", "refs/heads/" + self.p.plan.branch)
                    .decode()
                    .strip()
                )
            except ValueError:
                return 404, b""
            return 200, json.dumps(
                {
                    "ref": "refs/heads/" + self.p.plan.branch,
                    "object": {"type": "commit", "sha": sha},
                }
            ).encode()
        if path.startswith(PREFIX + "/git/trees/"):
            sha = path.rsplit("/", 1)[1].split("?")[0]
            return 200, json.dumps(self.p.tree_value(self.snapshot(sha))).encode()
        if path.startswith(PREFIX + "/git/blobs/"):
            sha = path.rsplit("/", 1)[1]
            data = self.git("cat-file", "blob", sha)
            self.assertEqual(sha, git_object("blob", data))
            return 200, json.dumps(
                {
                    "sha": sha,
                    "size": len(data),
                    "encoding": "base64",
                    "content": base64.b64encode(data).decode(),
                }
            ).encode()
        if path.startswith(PREFIX + "/git/commits/"):
            sha = path.rsplit("/", 1)[1]
            try:
                raw = self.git("cat-file", "commit", sha)
            except ValueError:
                return 404, b""
            self.assertEqual(sha, git_object("commit", raw))
            tree = raw.splitlines()[0].split()[1].decode()
            if sha == self.base:
                return 200, json.dumps({"sha": sha, "tree": {"sha": tree}}).encode()
            parents = [
                {"sha": line.split()[1].decode()}
                for line in raw.splitlines()
                if line.startswith(b"parent ")
            ]
            value = {
                **self.p.plan.commit_payload(tree),
                "sha": sha,
                "tree": {"sha": tree},
                "parents": parents,
            }
            self.assertEqual(self.p.plan.message.encode(), raw.split(b"\n\n", 1)[1])
            return 200, json.dumps(value).encode()
        return self.p.transport(method, path, payload, bearer, cancel, timeout)

    def factory(self, check, cancel):
        from runtime.mcp_bridge.github_remote import GitHubCreateOnly

        check()
        self.factories += 1
        return GitHubCreateOnly(
            self.p.plan,
            self.p.base,
            self.p.credential,
            mode="OFFLINE_FIXTURE",
            transport=self.transport,
        )

    def dispatch(self):
        return self.route.dispatch(
            self.fx.p(),
            self.fx.warrant,
            self.fx.operation,
            self.fx.request,
            cancel=self.p.cancel,
        )

    def test_real_bare_commit_signed_core_receipt_readback_and_no_duplicate(self):
        self.assertEqual("Applied", self.dispatch()["outcome"]["contract_type"])
        signed = self.route.result(self.fx.p(Capability.READ))
        verify(self.identity.spki, signed["signature"], signed["receipt"])
        self.assertEqual(self.p.commit, signed["receipt"]["commit_sha"])
        self.assertEqual(
            b"VALUE = 1\n",
            self.git("show", self.p.plan.branch + ":agent-demo/proposal.py"),
        )
        self.assertEqual(
            self.base, self.git("rev-parse", "refs/heads/main").decode().strip()
        )
        before = self.git("rev-list", "--all", "--count")
        posts = len(self.posts)
        self.dispatch()
        self.assertEqual(posts, len(self.posts))
        self.assertEqual(before, self.git("rev-list", "--all", "--count"))
        self.assertEqual(b"2\n", before)
        self.assertEqual(1, self.factories)

    def test_lost_ack_real_commit_is_reconciled_without_post_or_new_commit(self):
        self.lost_ack = True
        with self.assertRaises(ValueError):
            self.dispatch()
        self.assertEqual("Unknown", self.fx.inspect()["outcome"]["contract_type"])
        posts = len(self.posts)
        count = self.git("rev-list", "--all", "--count")
        api = self.factory(self.p.check, self.p.cancel)
        self.assertEqual(
            "Applied",
            self.route.reconcile(
                self.fx.p(), self.fx.warrant, cancel=self.p.cancel, api=api
            )["outcome"]["contract_type"],
        )
        self.assertEqual(posts, len(self.posts))
        self.assertEqual(count, self.git("rev-list", "--all", "--count"))

    def test_preexisting_branch_denies_before_any_post(self):
        self.git("update-ref", "refs/heads/" + self.p.plan.branch, self.base)
        with self.assertRaises(ValueError):
            self.dispatch()
        self.assertEqual([], self.posts)
        self.assertEqual(
            self.base, self.git("rev-parse", "refs/heads/main").decode().strip()
        )

    def test_actual_base_drift_denies_before_any_post(self):
        raw = self.git("cat-file", "commit", self.base) + b"Changed base\n"
        changed = self.object("commit", raw)
        self.git("update-ref", "refs/heads/main", changed, self.base)
        with self.assertRaises(ValueError):
            self.dispatch()
        self.assertEqual([], self.posts)
        self.assertEqual(
            changed, self.git("rev-parse", "refs/heads/main").decode().strip()
        )


if __name__ == "__main__":
    unittest.main()
