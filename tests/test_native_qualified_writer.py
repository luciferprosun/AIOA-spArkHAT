"""Disposable writer tests. UID and AppArmor execution require separate host acceptance."""

import os
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from runtime.red_hat.authenticated_boundary import DurableRoleRecoveryPort
from runtime.red_hat.broker_service import _publish
from runtime.red_hat.broker_protocol import BrokerRequest, digest, publish_record, read_record
from runtime.red_hat.execution_binding import NativeExecutionBindingV1, ROLE_SCHEMA, SCHEMA
from runtime.red_hat.native_qualification import serve_qualified_native_once
from runtime.red_hat.object_ingress import decode_objects, encode_objects, import_objects
from scripts.unification.native_writer_policy import storage_rules
from test_native_object_ingress import obj
from test_redhat_broker_protocol import fixture_request


class NativeQualifiedWriterTests(unittest.TestCase):
    def test_group_modes_and_create_only_evidence_and_objects(self):
        with tempfile.TemporaryDirectory() as scratch:
            repo = Path(scratch)
            objects = repo / "objects"
            objects.mkdir()
            objects.chmod(0o2750)
            gid = objects.stat().st_gid
            tree = obj("tree", b"")
            commit = obj("commit", b"tree " + tree[2].encode() + b"\n")
            records = decode_objects(encode_objects((tree, commit)), expected_commit=commit[2])
            fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, fd)
            previous = os.umask(0o027)
            try:
                import_objects(fd, os.getuid(), records, reader_gid=gid)
                import_objects(fd, os.getuid(), records, reader_gid=gid)
                publish_record(fd, "proof", {"ok": True}, reader_gid=gid)
                with self.assertRaisesRegex(ValueError, "RECORD_EXISTS"):
                    publish_record(fd, "proof", {"ok": False}, reader_gid=gid)
            finally:
                os.umask(previous)
            path = objects / commit[2][:2] / commit[2][2:]
            self.assertEqual(0o440, path.stat().st_mode & 0o7777)
            self.assertEqual(0o2750, path.parent.stat().st_mode & 0o7777)
            self.assertEqual(b'{"ok":true}', read_record(fd, "proof", os.getuid(), reader_gid=gid, sync=True))

    def test_guarded_publish_links_from_staging_only_after_final_check(self):
        with tempfile.TemporaryDirectory() as scratch, ExitStack() as stack:
            base = Path(scratch)
            for name in ("refs", "staging"):
                (base / name).mkdir()
            (base / "staging").chmod(0o2700)
            gid = (base / "staging").stat().st_gid
            root, parent = (os.open(path, os.O_RDONLY | os.O_DIRECTORY)
                            for path in (base, base / "refs"))
            stack.callback(os.close, root)
            stack.callback(os.close, parent)
            req = fixture_request()
            ref = base / "refs" / "candidate"
            def observe(_):
                info = ref.stat()
                return info.st_dev, info.st_ino, info.st_ctime_ns
            store = SimpleNamespace(reader_gid=gid, require_staging=Mock())
            target = SimpleNamespace(root=root, ref_parent=parent, writer=True, storage=store,
                                     uid=os.getuid(), check=Mock(), check_commit=Mock(),
                                     leaf=lambda _: ref.name, observe=observe)
            guard = SimpleNamespace(locked=nullcontext, require_running=Mock())
            final_check = Mock(side_effect=lambda: self.assertFalse(ref.exists()))
            previous = os.umask(0o027)
            try:
                stamp, _ = _publish(target, req, guard, Mock(), lambda: req.issued_at,
                                    Mock(), stack, final_check)
            finally:
                os.umask(previous)
            final_check.assert_called_once_with()
            self.assertEqual(stamp, observe(req))
            self.assertEqual(req.new_oid + "\n", ref.read_text())
            self.assertEqual(0o440, ref.stat().st_mode & 0o777)

    def test_cold_resolver_reopens_original_applying_records_without_warrant_input(self):
        from runtime.core_admission import Capability
        from runtime.mission.coding_tasks import CoreCodingTasks
        from runtime.mission.patch_capsule import CorePatchCapsules
        from runtime.red_hat.core_adapter import CoreIntentAdapter
        from runtime.red_hat.execution_binding import physical_context
        from test_redhat_broker_protocol import NOW
        from test_redhat_native_cas_broker import CasBrokerTests
        from test_redhat_rh04_native_task_gate import Fixture, _prepare_native_task_case

        broker = CasBrokerTests("test_lost_ack_one_settlement_zero_actual_redispatch")
        self.addCleanup(broker.doCleanups)
        broker.workspace()
        root_fd = os.open(broker.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, root_fd)
        fields = ("executor_id", "executor_key_id", "key_epoch", "broker_epoch", "issued_at", "expires_at")
        storage_digest = "c"*64
        metadata = {**physical_context(root_fd), "nonce": "a"*64, "storage_digest": storage_digest,
                    **{name: getattr(broker.request, name) for name in fields}}
        case = _prepare_native_task_case(broker.root, broker, rh06_fixture=metadata,
                                         native_plan_ref=True, durable_role=True)
        task_id, identity, enrollment = case["task"].task_id, case["identity"], case["enrollment"]
        expected = case["fx"].warrant.digest()
        device, epoch = case["request"].device_id, case["request"].broker_epoch
        exact_ref = case["request"].exact_ref
        case["tasks"].close()
        case["fx"].close()

        fresh = Fixture(broker.root / "native-core.json")
        self.addCleanup(fresh.close)
        tasks = CoreCodingTasks(fresh.journal, CorePatchCapsules(fresh.journal, identity, source_probe=lambda: None))
        self.addCleanup(tasks.close)
        # This checks cold ledger lookup. UID/policy checks require the qualified host.
        port = DurableRoleRecoveryPort.__new__(DurableRoleRecoveryPort)
        port.task_id, port.core_spki, port.coding_tasks = task_id, identity.spki, tasks
        port.adapter = CoreIntentAdapter(fresh.journal)
        port.enrollment, port.device_id, port.broker_epoch, port.root_fd = enrollment, device, epoch, root_fd
        port.storage = SimpleNamespace(exact_ref=exact_ref, digest="e"*64)
        with self.assertRaisesRegex(ValueError, "RECOVERY_TASK"):
            port._read_original(fresh.p(), "foreign")
        from runtime.memory_patch.errors import MemoryPatchError
        with self.assertRaises(MemoryPatchError) as failed:
            port._read_original(fresh.p(), task_id)
        self.assertEqual("NATIVE_ROLE_RECOVERY_START", str(failed.exception.__cause__))
        port.storage.digest = storage_digest
        with patch("runtime.red_hat.authenticated_boundary.time.time", return_value=NOW):
            result = port._read_original(fresh.p(), task_id)
        self.assertEqual(expected, result["warrant"].digest())
        self.assertEqual(exact_ref, result["request"].exact_ref)
        self.assertEqual("Unknown", fresh.journal.inspect(fresh.p(Capability.READ), result["warrant"])["outcome"]["contract_type"])

    def test_binding_version_does_not_accept_old_or_incomplete_role_contract(self):
        req = fixture_request()
        meta = dict(operation_digest="1"*64, capsule_digest="2"*64, plan_digest="3"*64,
                    source_digest="4"*64, policy_digest="5"*64, reservation_id_digest="6"*64,
                    outbox_id_digest="7"*64, boot_id="12345678-abcd-abcd-abcd-123456789012",
                    repository_mount=4, ref_parent_mount=4)
        original = req.to_wire()
        for schema, configured in ((SCHEMA, meta), (ROLE_SCHEMA, {**meta, "storage_digest": "a"*64})):
            value = {k: v for k, v in original.items() if k not in ("schema", "commit_permit_digest")}
            binding = NativeExecutionBindingV1(
                BrokerRequest.for_fixture(**{**value, "challenge": digest(configured)}), **configured)
            self.assertEqual(schema, binding.to_wire()["schema"])
            self.assertEqual(binding, NativeExecutionBindingV1.from_wire(binding.to_wire()))
            if schema == ROLE_SCHEMA:
                for edited in (dict(binding.to_wire(), schema=SCHEMA), dict(binding.to_wire(), storage_digest="b"*64)):
                    with self.assertRaises(ValueError):
                        NativeExecutionBindingV1.from_wire(edited)

    def test_disabled_writer_closes_supplied_key_before_use(self):
        fd = os.open("/dev/null", os.O_RDONLY)
        with patch("runtime.red_hat.executor_custody.load_broker_signer") as load:
            with self.assertRaisesRegex(ValueError, "WRITER_CONFIGURATION"):
                serve_qualified_native_once(None, root_fd=-1, storage=None, device_id="fixture",
                                            sequence=None, release=None, core_peer=None, core_spki=None,
                                            signer_fd=fd, enrollment=None, core_epoch=1, broker_epoch=1)
            load.assert_not_called()
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_ref_policy_emits_only_exact_link_destination(self):
        ref = "refs/heads/aioa/nz11-" + "2"*32
        policy = storage_rules("1"*32, ref)
        targets = [rule for rule in policy.splitlines() if "/refs/" in rule]
        self.assertEqual(2, len(targets))
        self.assertIn("/repo/" + ref + " -> ", targets[1])
        with self.assertRaisesRegex(ValueError, "POLICY_SCOPE"):
            storage_rules("1"*32, "refs/heads/aioa/*")
