"""Exercise the original synthetic START and the prestarted, fixed Native plan broker."""

import unittest
import zlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_redhat_rh07_sequence as sequence
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.red_hat.native_qualification import NativeQualificationPort
from test_redhat_broker_protocol import NOW


class PreparedChannelTests(unittest.TestCase):
    def test_lost_ack_requires_independent_recovery_of_original_intent(self):
        h = sequence.SequencedBoundaryTests("test_postwitness_lost_ack_settles_in_fresh_core_once")
        h.native_plan_ref = True
        self.addCleanup(h.doCleanups)
        h.setUp()
        f = h.fixture
        request = f.binding.request
        storage = f.root / "repo" / "objects"
        commit_path = storage / request.new_oid[:2] / request.new_oid[2:]
        commit = zlib.decompress(commit_path.read_bytes()).split(b"\0", 1)[1]
        tree_oid = commit.splitlines()[0].split()[1].decode("ascii")
        tree = zlib.decompress((storage / tree_oid[:2] / tree_oid[2:]).read_bytes()).split(b"\0", 1)[1]
        self.assertEqual(b"", tree)
        commit_path.unlink()
        broker, endpoint, _, _, gate = h.setup_triplet(broker_mode="prepared-native")
        route = SimpleNamespace(runner=f.fx.runner, journal=f.fx.journal, identity=f.core,
                                plan=SimpleNamespace(ref=request.exact_ref, commit_sha=request.new_oid,
                                                     digest=f.binding.plan_digest,
                                                     objects=(("tree", tree, tree_oid),
                                                              ("commit", commit, request.new_oid))),
                                capsule=f.case["capsule"])
        release = Mock()
        before = f.revision()
        with patch("time.time", return_value=NOW), patch.object(
                f.tasks, "_native_git_effect_check") as owned:
            port = NativeQualificationPort.prepare(
                gate=gate, enrollment=f.case["enrollment"], device_id=request.device_id,
                broker_peer=sequence.peer(broker.pid), endpoint=endpoint,
                release_listener=h.listener, anchor=f.anchor, lifetime=5, enabled=True)
            with self.assertRaisesRegex(ValueError, "NATIVE_QUALIFICATION_START_MISMATCH"):
                port.dispatch(route, f.tasks, h.principal, f.fx.warrant, release)
            release.assert_not_called()
            owned.reset_mock()
            port = replace(port, nonce=request.nonce, issued_at=request.issued_at, expires_at=request.expires_at)
            with self.assertRaises(CommitOutcomeUnknown):
                port.dispatch(route, f.tasks, h.principal, f.fx.warrant, release)
            owned.assert_called_once()
            release.assert_called_once_with()
        self.assertEqual(0, broker.wait(timeout=5))
        h.assert_link_count(1)
        self.assertTrue(commit_path.exists())
        f.assert_held()
        self.assertFalse(f.dispatch())
        first, second = f.recover(), f.recover()
        self.assertEqual("VERIFIED", first["task"]["state"])
        self.assertEqual(first["task"], second["task"])
        self.assertEqual(before + 1, f.revision())
        h.assert_link_count(1)
