"""A single durable API quota for proposal, credential, publication and readback."""

import unittest
from unittest.mock import patch

import test_github_remote_credential as credentials
import test_github_remote_execution as execution
import test_native_github_write as native
from runtime.core_admission import Capability
from runtime.mcp_bridge import github_remote as remote
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.meta_hackathon import github_write as github
from runtime.mobile_gateway.service import plain


class SessionBudgetTests(unittest.TestCase):
    setUp = native.NativeGitHubWriteTests.setUp
    start = native.NativeGitHubWriteTests.start
    tearDown = native.NativeGitHubWriteTests.tearDown
    proposal = native.NativeGitHubWriteTests.proposal

    def prepare(self):
        # The Native fixture mocks the public base lookup only while proposing;
        # exercise the actual four-GET proposal adapter below against inert data.
        self.proposal()
        self.operation = plain(github._get(self.app, "d" * 32).payload)
        self.window = github._request_budget(self.app, self.operation)
        self.port = execution.RemoteExecutionTests()
        self.port.setUp()
        self.port.plan, self.port.base = github._decode(self.operation)
        self.port.tree = self.port.base.add_files(self.port.plan.files)
        self.port.commit = self.port.plan.commit_sha_for_tree(self.port.tree.sha)
        self.duration = 0
        self.enterContext(
            patch.object(
                github,
                "_elapsed_clock_ms",
                side_effect=lambda: (
                    self.operation["request_window"]["start_ms"] + self.duration
                ),
            )
        )

    def count(self):
        return github._run(
            self.app,
            Capability.READ,
            lambda tx: plain(
                tx.get(
                    RecordKind.OPERATION,
                    "github-request-count-" + self.operation["operation_id"],
                ).payload
            ),
        )

    def api(self, transport=None):
        return remote.GitHubCreateOnly(
            self.port.plan,
            self.port.base,
            self.port.credential,
            mode="OFFLINE_FIXTURE",
            transport=transport or self.port.transport,
            request_budget=self.window,
        )

    def test_one_window_counts_proposal_mint_scope_proof_four_posts_and_readback(self):
        self.prepare()

        def public(method, path, payload, bearer, cancel, timeout):
            self.assertIsNone(bearer)
            return self.port.transport(
                method, path, payload, self.port.credential.bearer, cancel, timeout
            )

        base = remote.read_demo_base(
            check=self.port.check,
            cancel=self.port.cancel,
            mode="OFFLINE_FIXTURE",
            transport=public,
            request_budget=self.window,
        )
        self.assertEqual((self.port.plan.base_sha, self.port.base), base)
        self.assertEqual(4, self.count()["used"])
        cred = credentials.GitHubCredentialTests()
        cred.setUp()
        self.addCleanup(cred.doCleanups)
        cred.provider().mint(
            cancel=self.port.cancel, check=self.port.check, request_budget=self.window
        )
        self.assertEqual((6, 1), (self.count()["used"], self.count()["token_mints"]))
        result = self.port.execute(self.api())
        self.assertEqual("COMMIT_AND_DRAFT_PR_VERIFIED", result["state"])
        count = self.count()
        self.assertEqual(4, count["repository_posts"])
        self.assertEqual(len(self.port.calls) + len(cred.calls), count["used"])
        self.assertIn(remote.PREFIX + "/pulls/1", [call[1] for call in self.port.calls])
        self.assertLessEqual(count["used"], 48)
        signed_view = github.view(self.app, self.operation["operation_id"])
        self.assertEqual(
            {
                "charged_requests": count["used"],
                "repository_post_attempts": 4,
                "token_mint_attempts": 1,
                "max_requests": 48,
                "max_seconds": 120,
            },
            signed_view["session_requests"],
        )

    def test_last_ordinal_is_spent_once_and_rebinding_does_not_reset_count(self):
        self.prepare()
        for _ in range(44):
            self.window.consume("GET", remote.PREFIX)
        calls = []

        def transport(*args):
            calls.append(args[:2])
            return 201, b"{}"

        for path in ("/git/trees", "/git/commits", "/git/refs", "/pulls"):
            self.window.send(
                transport, "POST", remote.PREFIX + path, {}, None, self.port.cancel, 15
            )
        again = github._request_budget(self.app, self.operation)
        with self.assertRaisesRegex(ValueError, "GITHUB_SESSION_REQUEST_LIMIT"):
            again.send(
                transport, "GET", remote.PREFIX, None, None, self.port.cancel, 15
            )
        self.assertEqual(
            (48, 4, 4),
            (self.count()["used"], self.count()["repository_posts"], len(calls)),
        )

    def test_late_final_post_has_unknown_ack_and_no_dispatch_after_deadline(self):
        self.prepare()

        def late(method, path, payload, bearer, cancel, timeout):
            if method == "POST" and path == remote.PREFIX + "/pulls":
                self.duration = 120001
            return self.port.transport(method, path, payload, bearer, cancel, timeout)

        with self.assertRaisesRegex(ValueError, "GITHUB_WRITE_UNKNOWN_NO_RETRY"):
            self.port.execute(self.api(late))
        self.assertIn(remote.PREFIX + "/pulls", self.port.objects)
        before = self.count()
        self.assertEqual(4, before["repository_posts"])
        with self.assertRaises(ValueError):
            self.port.execute(self.api())
        with self.assertRaises(ValueError):
            self.api().readback(check=self.port.check, cancel=self.port.cancel)
        self.assertEqual(before, self.count())

    def test_clock_and_boot_cannot_grant_new_time_or_send_another_request(self):
        self.prepare()
        self.duration = 119750
        observed = self.window.send(
            lambda *args: args[-1],
            "GET",
            remote.PREFIX,
            None,
            None,
            self.port.cancel,
            15,
        )
        self.assertEqual(0.25, observed)
        self.duration = -1
        with self.assertRaisesRegex(ValueError, "GITHUB_SESSION_CLOCK_CHANGED"):
            self.window.remaining()
        with patch.object(github, "_boot_digest", return_value="e" * 64):
            with self.assertRaisesRegex(ValueError, "GITHUB_SESSION_BOOT_CHANGED"):
                self.window.remaining()
        self.assertEqual(1, self.count()["used"])
