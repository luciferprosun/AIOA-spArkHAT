"""G07-B.1 machine gate contracts. Every permitted transport is local TEST."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from runtime.mission.lite_contracts import LiteBudget, MODEL
from runtime.providers.live_gate import (
    LiveCallBlocked,
    LiveCallGate,
    LiveCallPermit,
    LocalGateResult,
    PermitUsageLedger,
    RepositorySourceStateReader,
    issue_test_permit,
    require_transport_authorization,
    source_tree_digest,
)
from runtime.providers import live_gate as live_gate_module
from runtime.providers.nvidia import (
    HTTPTransport,
    NvidiaProvider,
    ProviderError,
    ProviderRequest,
)


GIT_SHA = "a" * 40
TEST_SUITE_DIGEST = "c" * 64
_DEFAULT_PERMIT = object()


class MockTransport:
    transport_scope = "TEST"

    def __init__(self):
        self.calls = []
        self.authorizations = []

    def __call__(self, payload, key, timeout, max_bytes, authorization=None):
        require_transport_authorization(
            authorization,
            "TEST",
            transport=self,
            payload=payload,
            timeout=timeout,
            max_bytes=max_bytes,
            provider_id="nvidia",
            model_id=MODEL,
        )
        self.authorizations.append(authorization)
        self.calls.append(json.loads(payload))
        response = {
            "id": "g07-b1-mock-response",
            "model": MODEL,
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "summary": "Shows service manager status for a unit.",
                    "needs_attention": False,
                })},
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return 200, json.dumps(response).encode("utf-8")


class G07LiveGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source_root = self.root / "source"
        self.source_root.mkdir()
        (self.source_root / "tracked_contract.py").write_text("CONTRACT = 1\n")
        self.current_git_sha = GIT_SHA
        self.current_test_suite_digest = TEST_SUITE_DIGEST
        self.transport = MockTransport()

    def worktree_digest(self):
        return source_tree_digest(self.source_root)

    def permit(self, **changes):
        values = {
            "permit_id": "g07-b1-local-test",
            "phase": "G07-B1-TEST",
            "git_sha": GIT_SHA,
            "worktree_digest": self.worktree_digest(),
            "test_suite_digest": TEST_SUITE_DIGEST,
            "gate_status": "PASS",
            "issued_at": 100,
            "expires_at": 200,
            "max_live_calls": 1,
            "provider_id": "nvidia",
            "model_id": MODEL,
            "transport_scope": "TEST",
        }
        values.update(changes)
        return LiveCallPermit(**values)

    def gate(
        self,
        permit=_DEFAULT_PERMIT,
        *,
        suffix="gate",
        now=150,
        git_sha=None,
        worktree_digest=None,
        test_suite_digest=None,
    ):
        return LiveCallGate(
            self.permit() if permit is _DEFAULT_PERMIT else permit,
            source_reader=(
                lambda: (
                    self.current_git_sha,
                    self.worktree_digest(),
                    self.current_test_suite_digest,
                )
                if git_sha is None and worktree_digest is None and test_suite_digest is None
                else lambda: (
                    self.current_git_sha if git_sha is None else git_sha(),
                    self.worktree_digest() if worktree_digest is None else worktree_digest(),
                    self.current_test_suite_digest
                    if test_suite_digest is None else test_suite_digest(),
                )
            ),
            usage_ledger=PermitUsageLedger((self.root / f"{suffix}.sqlite3").resolve()),
            clock=lambda: now,
        )

    def provider(self, live_gate, *, transport=None):
        return NvidiaProvider(
            LiteBudget(),
            secret_supplier=lambda: "fixture-key-not-real",
            transport=self.transport if transport is None else transport,
            clock=lambda: 150,
            live_gate=live_gate,
        )

    def request(self, **changes):
        values = {
            "request_id": "request-g07-b1",
            "trace_id": "trace-g07-b1",
            "provider_id": "nvidia",
            "model_id": MODEL,
            "input_text": '{"fixture":true}',
            "budget_reservation_id": "reservation-g07-b1",
            "max_output_tokens": 256,
            "request_timeout": 30,
        }
        values.update(changes)
        return ProviderRequest(**values)

    def authorization(self, gate, *, transport=None, request=None):
        transport = self.transport if transport is None else transport
        request = self.request() if request is None else request
        provider = self.provider(gate, transport=transport)
        payload = provider._payload(request)
        authorization = gate.authorize(
            request.provider_id,
            request.model_id,
            transport.transport_scope,
            transport=transport,
            payload=payload,
            timeout=request.request_timeout,
            max_bytes=provider.budget.max_response_bytes,
        )
        return provider, request, payload, authorization

    def assert_blocked(self, provider, reason, *, request=None, transport=None):
        with self.assertRaisesRegex(ProviderError, "LIVE_CALL_BLOCKED") as caught:
            provider.request(self.request() if request is None else request)
        self.assertEqual(reason, caught.exception.gate_reason)
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual([], (self.transport if transport is None else transport).calls)

    def test_d1_missing_permit_rejects_before_transport(self):
        self.assert_blocked(self.provider(None), "PERMIT_MISSING")

    def test_d2_nonpassing_gate_status_rejects_before_transport(self):
        self.assert_blocked(
            self.provider(self.gate(self.permit(gate_status="FAIL"))),
            "LOCAL_GATE_NOT_PASS",
        )

    def test_d3_current_git_sha_is_revalidated(self):
        gate = self.gate()
        self.current_git_sha = "d" * 40
        self.assert_blocked(self.provider(gate), "GIT_SHA_MISMATCH")

    def test_d4_current_worktree_digest_is_revalidated(self):
        gate = self.gate()
        (self.source_root / "tracked_contract.py").write_text("CONTRACT = 2\n")
        self.assert_blocked(self.provider(gate), "WORKTREE_DIGEST_MISMATCH")

    def test_current_test_suite_digest_is_revalidated(self):
        gate = self.gate()
        self.current_test_suite_digest = "d" * 64
        self.assert_blocked(self.provider(gate), "TEST_SUITE_DIGEST_MISMATCH")

    def test_d5_expired_permit_rejects_before_transport(self):
        self.assert_blocked(
            self.provider(self.gate(now=200)), "PERMIT_EXPIRED_OR_NOT_YET_VALID"
        )

    def test_d6_wrong_provider_or_model_rejects_before_transport(self):
        for field, value, reason in (
            ("provider_id", "other", "PROVIDER_MISMATCH"),
            ("model_id", "nvidia/other-model", "MODEL_MISMATCH"),
        ):
            with self.subTest(field=field):
                self.assert_blocked(
                    self.provider(self.gate(self.permit(**{field: value}), suffix=field)),
                    reason,
                )

    def test_valid_test_permit_is_one_mock_call_then_budget_exhausted(self):
        gate = self.gate()
        response = self.provider(gate).request(self.request())
        self.assertEqual("VALID", response.validation_result)
        self.assertEqual(1, len(self.transport.calls))
        with self.assertRaisesRegex(ProviderError, "LIVE_CALL_BLOCKED") as caught:
            self.provider(gate).request(self.request())
        self.assertEqual("CALL_BUDGET_EXHAUSTED", caught.exception.gate_reason)
        self.assertEqual(1, len(self.transport.calls))

    def test_call_budget_remains_exhausted_after_gate_reconstruction(self):
        permit = self.permit()
        first = self.gate(permit, suffix="durable")
        self.provider(first).request(self.request())
        second = self.gate(permit, suffix="durable")
        with self.assertRaisesRegex(ProviderError, "LIVE_CALL_BLOCKED") as caught:
            self.provider(second).request(self.request())
        self.assertEqual("CALL_BUDGET_EXHAUSTED", caught.exception.gate_reason)
        self.assertEqual(1, len(self.transport.calls))

    def test_failed_local_gate_returns_real_blocked_decision_and_no_permit(self):
        decision = issue_test_permit(
            permit_id="g07-b1-failed-local-gate",
            phase="G07-B1-TEST",
            git_sha=GIT_SHA,
            worktree_digest=self.worktree_digest(),
            local_gate=LocalGateResult("FAIL", TEST_SUITE_DIGEST),
            issued_at=100,
            expires_at=200,
            max_live_calls=1,
            provider_id="nvidia",
            model_id=MODEL,
        )
        self.assertEqual("BLOCKED", decision.phase_status)
        self.assertEqual("LOCAL_GATE_NOT_PASS", decision.reason)
        self.assertIsNone(decision.permit)
        gate = self.gate(decision.permit, suffix="failed")
        self.assert_blocked(self.provider(gate), "PERMIT_MISSING")

    def test_transport_authorization_is_single_use_at_effect_boundary(self):
        provider, request, payload, authorization = self.authorization(self.gate())
        result = self.transport(
            payload, "fixture-key-not-real", request.request_timeout,
            provider.budget.max_response_bytes, authorization,
        )
        self.assertEqual(200, result[0])
        with self.assertRaisesRegex(LiveCallBlocked, "LIVE_CALL_BLOCKED") as caught:
            self.transport(
                payload, "fixture-key-not-real", request.request_timeout,
                provider.budget.max_response_bytes, authorization,
            )
        self.assertEqual("TRANSPORT_AUTHORIZATION_REUSED", caught.exception.reason)
        self.assertEqual(1, len(self.transport.calls))

    def test_authorization_rejects_different_request_and_transport(self):
        gate = self.gate(suffix="request-binding")
        provider, request, payload, authorization = self.authorization(gate)
        with self.assertRaisesRegex(LiveCallBlocked, "LIVE_CALL_BLOCKED") as caught:
            self.transport(
                payload + b" ", "fixture-key-not-real", request.request_timeout,
                provider.budget.max_response_bytes, authorization,
            )
        self.assertEqual("TRANSPORT_REQUEST_MISMATCH", caught.exception.reason)
        self.assertEqual([], self.transport.calls)

        other = MockTransport()
        gate = self.gate(suffix="transport-binding")
        provider, request, payload, authorization = self.authorization(gate)
        with self.assertRaisesRegex(LiveCallBlocked, "LIVE_CALL_BLOCKED") as caught:
            other(
                payload, "fixture-key-not-real", request.request_timeout,
                provider.budget.max_response_bytes, authorization,
            )
        self.assertEqual("TRANSPORT_IDENTITY_MISMATCH", caught.exception.reason)
        self.assertEqual([], other.calls)

    def test_authorization_rejects_different_provider_and_model(self):
        for field, value, reason in (
            ("provider_id", "other", "PROVIDER_MISMATCH"),
            ("model_id", "nvidia/other-model", "MODEL_MISMATCH"),
        ):
            with self.subTest(field=field):
                gate = self.gate(suffix="binding-" + field)
                provider, request, payload, authorization = self.authorization(gate)
                values = {"provider_id": "nvidia", "model_id": MODEL}
                values[field] = value
                with self.assertRaisesRegex(LiveCallBlocked, "LIVE_CALL_BLOCKED") as caught:
                    require_transport_authorization(
                        authorization,
                        "TEST",
                        transport=self.transport,
                        payload=payload,
                        timeout=request.request_timeout,
                        max_bytes=provider.budget.max_response_bytes,
                        **values,
                    )
                self.assertEqual(reason, caught.exception.reason)
                self.assertEqual([], self.transport.calls)

    def test_source_change_after_authorize_is_blocked_at_transport_boundary(self):
        provider, request, payload, authorization = self.authorization(
            self.gate(suffix="toctou")
        )
        (self.source_root / "tracked_contract.py").write_text("CONTRACT = 2\n")
        with self.assertRaisesRegex(LiveCallBlocked, "LIVE_CALL_BLOCKED") as caught:
            self.transport(
                payload, "fixture-key-not-real", request.request_timeout,
                provider.budget.max_response_bytes, authorization,
            )
        self.assertEqual("WORKTREE_DIGEST_MISMATCH", caught.exception.reason)
        self.assertEqual([], self.transport.calls)

    def test_token_expiry_is_rechecked_at_transport_boundary(self):
        now = [150]
        permit = self.permit(issued_at=100, expires_at=200)
        gate = LiveCallGate(
            permit,
            source_reader=lambda: (
                self.current_git_sha,
                self.worktree_digest(),
                self.current_test_suite_digest,
            ),
            usage_ledger=PermitUsageLedger((self.root / "expiry.sqlite3").resolve()),
            clock=lambda: now[0],
        )
        provider, request, payload, authorization = self.authorization(gate)
        now[0] = 200
        with self.assertRaisesRegex(LiveCallBlocked, "LIVE_CALL_BLOCKED") as caught:
            self.transport(
                payload, "fixture-key-not-real", request.request_timeout,
                provider.budget.max_response_bytes, authorization,
            )
        self.assertEqual("PERMIT_EXPIRED_OR_NOT_YET_VALID", caught.exception.reason)
        self.assertEqual([], self.transport.calls)

    def test_untracked_source_added_after_permit_is_blocked(self):
        gate = self.gate(suffix="untracked")
        (self.source_root / "new_untracked_contract.py").write_text("NEW = True\n")
        self.assert_blocked(self.provider(gate), "WORKTREE_DIGEST_MISMATCH")

    def test_test_permit_cannot_authorize_http_or_direct_exchange(self):
        provider = self.provider(self.gate(suffix="http"), transport=HTTPTransport())
        with patch(
            "runtime.providers.nvidia.http.client.HTTPSConnection",
            side_effect=AssertionError("network boundary reached"),
        ) as constructor, self.assertRaisesRegex(ProviderError, "LIVE_CALL_BLOCKED") as caught:
            provider.request(self.request())
        self.assertEqual("TRANSPORT_SCOPE_MISMATCH", caught.exception.gate_reason)
        constructor.assert_not_called()

        gate = self.gate(suffix="direct-http")
        test_provider, request, payload, authorization = self.authorization(gate)
        http = HTTPTransport()
        with patch(
            "runtime.providers.nvidia.http.client.HTTPSConnection",
            side_effect=AssertionError("network boundary reached"),
        ) as constructor, self.assertRaisesRegex(ProviderError, "LIVE_CALL_BLOCKED") as caught:
            http._exchange(
                payload, "fixture-key-not-real", request.request_timeout,
                test_provider.budget.max_response_bytes, authorization,
            )
        self.assertEqual("TRANSPORT_IDENTITY_MISMATCH", caught.exception.gate_reason)
        constructor.assert_not_called()

    def test_forged_transport_authorization_is_rejected(self):
        forged = live_gate_module._TransportAuthorization(
            self.permit(),
            1,
            "d" * 64,
            self.transport,
            lambda: (GIT_SHA, self.worktree_digest(), TEST_SUITE_DIGEST),
            lambda: 150,
        )
        with self.assertRaisesRegex(LiveCallBlocked, "LIVE_CALL_BLOCKED") as caught:
            require_transport_authorization(
                forged,
                "TEST",
                transport=self.transport,
                payload=b"{}",
                timeout=30,
                max_bytes=1024,
                provider_id="nvidia",
                model_id=MODEL,
            )
        self.assertEqual("TRANSPORT_AUTHORIZATION_MISSING_OR_INVALID", caught.exception.reason)
        with self.assertRaisesRegex(LiveCallBlocked, "LIVE_CALL_BLOCKED") as caught:
            require_transport_authorization(
                object(),
                "TEST",
                transport=self.transport,
                payload=b"{}",
                timeout=30,
                max_bytes=1024,
                provider_id="nvidia",
                model_id=MODEL,
            )
        self.assertEqual("TRANSPORT_AUTHORIZATION_MISSING_OR_INVALID", caught.exception.reason)
        self.assertEqual([], self.transport.calls)

    def test_repository_reader_is_required_for_live_scope_and_rejects_callbacks(self):
        self.assertEqual(64, len(source_tree_digest(Path(self.source_root))))
        live_permit = self.permit(transport_scope="LIVE")
        with self.assertRaisesRegex(ValueError, "INVALID_LIVE_CALL_GATE"):
            LiveCallGate(
                live_permit,
                source_reader=lambda: (GIT_SHA, self.worktree_digest(), TEST_SUITE_DIGEST),
                usage_ledger=PermitUsageLedger((self.root / "live-static.sqlite3").resolve()),
                clock=lambda: 150,
            )
        with self.assertRaises(TypeError):
            RepositorySourceStateReader(
                self.source_root,
                git_sha_reader=lambda: GIT_SHA,
                test_suite_digest_reader=lambda: TEST_SUITE_DIGEST,
            )

    def test_permit_roundtrip_is_strict_and_schema_version_has_exact_type(self):
        permit = self.permit()
        self.assertEqual(permit, LiveCallPermit.from_json_bytes(permit.to_json_bytes()))
        document = permit.as_dict()
        for changed in (
            {**document, "unexpected": True},
            {**document, "git_sha": "d" * 40},
        ):
            with self.subTest(keys=sorted(changed)), self.assertRaisesRegex(
                ValueError, "INVALID_LIVE_CALL_PERMIT"
            ):
                LiveCallPermit.from_json_bytes(json.dumps(changed))
        for value in (True, False, 1.0, "1", None, 2):
            with self.subTest(schema_version=value), self.assertRaisesRegex(
                ValueError, "INVALID_LIVE_CALL_PERMIT"
            ):
                self.permit(schema_version=value)
        missing = permit.as_dict()
        missing.pop("schema_version")
        with self.assertRaisesRegex(ValueError, "INVALID_LIVE_CALL_PERMIT"):
            LiveCallPermit.from_json_bytes(json.dumps(missing))


class AuthoritativeRepositorySourceStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self._git("init", "-q")
        self._git("config", "user.email", "g07-b2@example.invalid")
        self._git("config", "user.name", "G07 B2 Fixture")
        (self.repository / "contract.py").write_text("VALUE = 1\n")
        self._git("add", "contract.py")
        self._git("commit", "-q", "-m", "fixture A")
        self.request = ProviderRequest(
            request_id="request-g07-b2-authority",
            trace_id="trace-g07-b2-authority",
            provider_id="nvidia",
            model_id=MODEL,
            input_text='{"fixture":true}',
            budget_reservation_id="reservation-g07-b2-authority",
            max_output_tokens=256,
            request_timeout=30,
        )

    def _git(self, *arguments):
        return subprocess.run(
            ("/usr/bin/git", "-C", str(self.repository), *arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        ).stdout.strip()

    def _head(self):
        return self._git("rev-parse", "HEAD")

    def _evidence_path(self):
        git_directory = Path(self._git("rev-parse", "--absolute-git-dir"))
        return git_directory / "aioa" / "accepted-test-evidence.json"

    def _write_evidence(self, *, completed_at=100, raw=None):
        path = self._evidence_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw is None:
            document = {
                "schema_version": 1,
                "status": "PASS",
                "git_sha": self._head(),
                "source_tree_digest": source_tree_digest(self.repository.resolve()),
                "tests_run": 1,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
                "unexpected_skips": 0,
                "completed_at": completed_at,
            }
            raw = json.dumps(
                document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ) + "\n"
        path.write_text(raw)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _reader(self):
        with patch.object(
            live_gate_module,
            "_CANONICAL_REPOSITORY_ROOT",
            self.repository.resolve(),
        ):
            return RepositorySourceStateReader()

    def _permit(self, state):
        return LiveCallPermit(
            permit_id="g07-b2-live-authority-fixture",
            phase="G07-B2-TEST",
            git_sha=state[0],
            worktree_digest=state[1],
            test_suite_digest=state[2],
            gate_status="PASS",
            issued_at=100,
            expires_at=200,
            max_live_calls=1,
            provider_id="nvidia",
            model_id=MODEL,
            transport_scope="LIVE",
        )

    def _accepted_reader_and_permit(self):
        self._write_evidence()
        reader = self._reader()
        state = reader()
        return reader, self._permit(state), state

    def _gate(self, reader, permit, suffix):
        return LiveCallGate(
            permit,
            source_reader=reader,
            usage_ledger=PermitUsageLedger(
                (self.root / f"{suffix}-permit.sqlite3").resolve()
            ),
            clock=lambda: 150,
        )

    def _commit_b(self):
        (self.repository / "contract.py").write_text("VALUE = 2\n")
        self._git("add", "contract.py")
        self._git("commit", "-q", "-m", "fixture B")

    def test_accepted_authoritative_evidence_unchanged_passes_local_gate(self):
        reader, permit, state = self._accepted_reader_and_permit()
        self.assertEqual(state, reader())
        self._gate(reader, permit, "accepted").require("nvidia", MODEL, "LIVE")

    def test_stale_head_callback_cannot_rescue_live_permit(self):
        reader, permit, stale_state = self._accepted_reader_and_permit()
        stale_callback = lambda: stale_state
        with self.assertRaisesRegex(ValueError, "INVALID_LIVE_CALL_GATE"):
            self._gate(stale_callback, permit, "stale-callback")

        self._commit_b()
        self._write_evidence(completed_at=101)
        gate = self._gate(reader, permit, "head-b")
        transport = HTTPTransport()
        provider = NvidiaProvider(
            LiteBudget(),
            secret_supplier=lambda: "fixture-key-not-real",
            transport=transport,
            clock=lambda: 150,
            live_gate=gate,
        )
        with patch(
            "runtime.providers.nvidia.http.client.HTTPSConnection",
            side_effect=AssertionError("network boundary reached"),
        ) as constructor, self.assertRaisesRegex(
            ProviderError, "LIVE_CALL_BLOCKED"
        ) as caught:
            provider.request(self.request)
        self.assertEqual("GIT_SHA_MISMATCH", caught.exception.gate_reason)
        constructor.assert_not_called()

    def test_test_evidence_change_remove_and_malformed_fail_closed(self):
        scenarios = ("changed", "removed", "malformed")
        for index, scenario in enumerate(scenarios):
            with self.subTest(scenario=scenario):
                reader, permit, _state = self._accepted_reader_and_permit()
                if scenario == "changed":
                    self._write_evidence(completed_at=101 + index)
                    expected = "TEST_SUITE_DIGEST_MISMATCH"
                elif scenario == "removed":
                    self._evidence_path().unlink()
                    expected = "SOURCE_STATE_UNAVAILABLE"
                else:
                    self._write_evidence(raw="{not-json\n")
                    expected = "SOURCE_STATE_UNAVAILABLE"
                with self.assertRaisesRegex(LiveCallBlocked, "LIVE_CALL_BLOCKED") as caught:
                    self._gate(reader, permit, f"evidence-{scenario}").require(
                        "nvidia", MODEL, "LIVE"
                    )
                self.assertEqual(expected, caught.exception.reason)

    def test_stale_evidence_for_previous_head_is_blocked(self):
        reader, permit, _state = self._accepted_reader_and_permit()
        self._commit_b()
        with self.assertRaisesRegex(LiveCallBlocked, "LIVE_CALL_BLOCKED") as caught:
            self._gate(reader, permit, "stale-evidence").require(
                "nvidia", MODEL, "LIVE"
            )
        self.assertEqual("SOURCE_STATE_UNAVAILABLE", caught.exception.reason)

    def test_symlinks_are_rejected_for_files_directories_and_external_targets(self):
        outside = self.root / "outside.py"
        outside.write_text("OUTSIDE = 1\n")
        for name, target, directory in (
            ("file-link.py", self.repository / "contract.py", False),
            ("outside-link.py", outside, False),
            ("directory-link", self.root, True),
        ):
            with self.subTest(name=name, directory=directory):
                link = self.repository / name
                link.symlink_to(target, target_is_directory=directory)
                with self.assertRaisesRegex(ValueError, "SOURCE_TREE_SYMLINK_REJECTED"):
                    source_tree_digest(self.repository.resolve())
                link.unlink()

    def test_regular_file_replaced_by_changed_symlink_blocks_actual_boundary(self):
        reader, permit, _state = self._accepted_reader_and_permit()
        gate = self._gate(reader, permit, "symlink-boundary")
        transport = HTTPTransport()
        provider = NvidiaProvider(
            LiteBudget(),
            secret_supplier=lambda: "fixture-key-not-real",
            transport=transport,
            clock=lambda: 150,
            live_gate=gate,
        )
        payload = provider._payload(self.request)
        authorization = gate.authorize(
            "nvidia",
            MODEL,
            "LIVE",
            transport=transport,
            payload=payload,
            timeout=self.request.request_timeout,
            max_bytes=provider.budget.max_response_bytes,
        )
        outside_a = self.root / "outside-a.py"
        outside_b = self.root / "outside-b.py"
        outside_a.write_text("VALUE = 'a'\n")
        outside_b.write_text("VALUE = 'b'\n")
        contract = self.repository / "contract.py"
        contract.unlink()
        contract.symlink_to(outside_a)
        contract.unlink()
        contract.symlink_to(outside_b)
        with patch(
            "runtime.providers.nvidia.http.client.HTTPSConnection",
            side_effect=AssertionError("network boundary reached"),
        ) as constructor, self.assertRaisesRegex(
            ProviderError, "LIVE_CALL_BLOCKED"
        ) as caught:
            transport._exchange(
                payload,
                "fixture-key-not-real",
                self.request.request_timeout,
                provider.budget.max_response_bytes,
                authorization,
            )
        self.assertEqual("SOURCE_STATE_UNAVAILABLE", caught.exception.gate_reason)
        constructor.assert_not_called()

    def test_regular_files_have_deterministic_source_digest(self):
        first = source_tree_digest(self.repository.resolve())
        second = source_tree_digest(self.repository.resolve())
        self.assertEqual(first, second)
        self.assertEqual(64, len(first))


if __name__ == "__main__":
    unittest.main()
