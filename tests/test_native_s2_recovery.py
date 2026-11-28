"""Synthetic boots and one UID; real Git, producer signatures, verifier IPC and Core transactions."""

import hashlib
import json
import multiprocessing
import os
import socket
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
from runtime.mission.coding_tasks import CoreCodingTasks
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mobile_gateway.wire import Identity
from runtime.red_hat import authenticated_boundary as boundary
from runtime.red_hat import writer_lifecycle as lifecycle
from runtime.red_hat.broker_protocol import Peer, authenticate, digest, read_record
from runtime.red_hat.core_adapter import CoreIntentAdapter
from runtime.red_hat.execution_binding import capture_binding
from runtime.red_hat.fixture_repository import open_repository
from runtime.red_hat.native_bootstrap import ColdNativeBootstrap
from runtime.red_hat.role_storage import PersistentVolume, RoleStorage, StorageActor
from runtime.red_hat.s2_continuity import ColdSuccession, boot_hash, require_successor
from runtime.red_hat.s2_receipt import SCHEMA, ManagementEvidence
from scripts.unification.native_s1.roles import pinned_directory
from test_redhat_broker_protocol import NOW
from test_redhat_rh04_native_task_gate import Fixture, _prepare_native_task_case


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class NativeS2RecoveryTests(unittest.TestCase):
    def setUp(self):
        from test_redhat_native_cas_broker import CasBrokerTests
        self.broker = CasBrokerTests("test_lost_ack_one_settlement_zero_actual_redispatch")
        self.addCleanup(self.broker.doCleanups)
        self.broker.workspace()
        self.root = self.broker.root
        (self.root / "staging").mkdir()
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.manager = Identity(ec.generate_private_key(ec.SECP256R1()))
        self.reader = Identity(ec.generate_private_key(ec.SECP256R1()))
        self.volume = PersistentVolume("1" * 64, str(uuid.uuid4()), 7, sha(self.manager.spki.encode()))
        self.old_boot = str(uuid.uuid4())
        case = _prepare_native_task_case(self.root, self.broker, rh06_fixture=self.metadata,
                                         native_plan_ref=True, durable_role=True)
        original = case["fx"]
        self.enrollment, self.identity = case["enrollment"], case["identity"]
        self.warrant = original.warrant
        self.binding = capture_binding(case["adapter"], original.p(), self.warrant, self.enrollment,
                                     trusted_device_id=case["request"].device_id, now=NOW,
                                     broker_epoch=case["request"].broker_epoch)
        self.broker.request = self.binding.request
        self.broker.spec["request"] = self.binding.request.to_wire()
        (self.root / "fixture.json").write_text(json.dumps(self.broker.spec))
        case["tasks"].close()
        original.close()
        self.assertIsNone(self.broker.run_broker("witness_durable", crash=True))
        self.fresh = Fixture(self.root / "native-core.json")
        self.addCleanup(self.fresh.close)
        self.task = self.warrant.task_id
        self.journal = CoreIntentJournal(self.fresh.ledger, self.fresh.journal.governor, recovery_task_id=self.task)
        self.runner = self.fresh.ledger.runner
        self.key = object()
        self.runner._write_key = self.key
        self.tasks = CoreCodingTasks(self.journal, CorePatchCapsules(self.journal, self.identity, source_probe=lambda: None))
        self.addCleanup(self.tasks.close)
        self.adapter = CoreIntentAdapter(self.journal, run_verified_settlement=lambda p, f: self.runner.run(
            TransactionContext(p, Capability.COMMIT), f, write_key=self.key))
        self.current = replace(self.old, mount_namespace=self.old.mount_namespace + 1,
                               persistent=replace(self.volume, generation=8))
        capsule = case["capsule"]
        project = SimpleNamespace(**{k: getattr(capsule, k) for k in
                                  ("repository_id", "workspace_id", "source_base_sha", "base_tree_sha256")})
        self.config = NativeHostCompositionConfig(
            json.dumps({"profile": "OWNED_OFFLINE_PROOF_V1", "git_target_repository": str(self.root / "repo")}).encode(),
            project, None, None, None).with_qualification_target(self.current.core_target().pre_capsule())
        self.expected = self.place_terminal_records()
        self.succession = self.seal(self.expected)

    def metadata(self, request):
        actors = [StorageActor(uid, gid, f"aioa-{role} (enforce)", f"0::/native/{role}")
                  for role, uid, gid in (("core", 61001, 61001), ("broker", os.getuid(), 61002),
                                          ("verifier", 61003, 61003))]
        repo = self.root / "repo"
        self.old = RoleStorage(*actors, 61004, os.stat("/proc/self/ns/mnt").st_ino, request.exact_ref,
            *(pinned_directory(p) for p in (self.root, repo, (repo / request.exact_ref).parent, self.root / "evidence")),
            staging=pinned_directory(self.root / "staging"), state=pinned_directory(self.root / "state"),
            policy_sha256="a" * 64, writer_cgroup=pinned_directory(self.root), persistent=self.volume)
        return {**{k: getattr(request, k) for k in
                   ("executor_id", "executor_key_id", "key_epoch", "broker_epoch", "issued_at", "expires_at")},
                "nonce": "a" * 64, "boot_id": self.old_boot, "repository_mount": self.old.repository.mount,
                "ref_parent_mount": self.old.ref_parent.mount, "storage_digest": self.old.digest}

    def place_terminal_records(self):
        request = self.binding.request
        name = request.witness_binding().witness_id
        proof = self.root / "evidence"
        completion = sha((proof / ("completion-" + name)).read_bytes())
        launch = lifecycle._launch(self.old, self.old_boot)
        process = {"schema": "aioa.redhat.s1.writer-process.v1", "launch": digest(launch), "pid": 250, "start_ticks": 1}
        closed = lifecycle._closure(self.binding, self.old, process, completion, boot=self.old_boot)
        signer = Identity(serialization.load_pem_private_key((self.root / "fixture-key").read_bytes(), password=None))
        stage = boundary._seal(signer, {"schema": lifecycle.COMPLETION_STAGE, "binding": digest(self.binding.to_wire()),
                                        "completion_sha256": completion})
        records = {"writer-launch": launch, "writer-process": process, "writer-closed": closed,
                   "writer-completion-stage": stage, "writer-closed-synced": lifecycle._closure_synced(self.binding, closed)}
        for filename, body in records.items():
            path = self.root / filename
            path.write_bytes(canonical_json_bytes(body))
            path.chmod(0o400)
        return {"start_sha256": request.start_digest, "intent_sha256": request.intent_digest,
                "reservation_sha256": request.reservation_digest, "original_policy_epoch": request.core_epoch,
                "volume_sha256": self.volume.volume_sha256, "predecessor_boot_sha256": sha(self.old_boot.encode()),
                "predecessor_generation": 7, "predecessor_spki_sha256": self.enrollment.executor.key_id,
                "witness_sha256": sha((proof / name).read_bytes()), "completion_sha256": completion,
                "writer_closed_sha256": digest(closed), "current_boot_sha256": boot_hash(), "current_generation": 8,
                "current_policy_epoch": request.core_epoch, "reader_identity_sha256": self.reader.audience,
                "challenge": "e" * 64}

    def seal(self, expected):
        data = dict(expected, schema=SCHEMA, authority="EXCLUSIVE_READBACK_PREDECESSOR_FENCED",
                    issued_at=NOW + 995, expires_at=NOW + 1100)
        raw = canonical_json_bytes(expected)
        receipt = canonical_json_bytes({"payload": data, "signature": self.manager.sign(data)})
        return ColdSuccession(self.old, ManagementEvidence(raw, sha(raw), receipt, self.manager.spki.encode(),
                                                          self.volume.authority_spki_sha256), self.reader.spki)

    @contextmanager
    def one_uid(self):
        # The fixture's actual files are private to one UID. Substitute only
        # confinement/ownership inputs and keep content, FD, PID and signature checks.
        def private_record(directory, name, _uid, *, reader_gid=None, **kwargs):
            return read_record(directory, name, os.getuid(), **kwargs)

        @contextmanager
        def repository(root, request, uid, *, storage, role):
            with open_repository(root, request, uid) as target:
                yield SimpleNamespace(root=target.root, repo=target.repo, ref_parent=target.ref_parent, writer=False,
                    storage=storage, observe=target.observe, check=target.check, record=target.record,
                    check_commit=target.check_commit)

        def peer(stream, expected):
            return authenticate(stream, Peer(expected.pid, os.getuid(), os.getgid()))

        with ExitStack() as stack:
            for name in ("require_anchor", "require_evidence"):
                attr = "anchor" if name == "require_anchor" else "evidence"
                stack.enter_context(patch.object(RoleStorage, name, lambda s, fd, a=attr: getattr(s, a).require_fd(fd)))
            stack.enter_context(patch.object(RoleStorage, "require_role"))
            stack.enter_context(patch.object(boundary, "authenticate", peer))
            for name in ("writer_lifecycle.read_record", "s2_continuity.read_record"):
                stack.enter_context(patch("runtime.red_hat." + name, private_record))
            for name in ("fixture_repository.open_repository", "verifier.open_repository"):
                stack.enter_context(patch("runtime.red_hat." + name, repository))
            stack.enter_context(patch("time.time", return_value=NOW + 1000))
            yield

    def bootstrap(self, proof):
        req = self.binding.request
        return ColdNativeBootstrap(self.task, self.fd, self.current, self.enrollment, req.device_id,
                                   req.broker_epoch, self.identity.spki, succession=proof)

    def state(self):
        def read(tx):
            row, state = self.journal._load(tx, self.warrant)
            box = tx.get(RecordKind.OUTBOX, self.journal._key(self.warrant))
            return row.revision, state["outcome"]["contract_type"], box.revision
        return self.journal._run(self.fresh.p(Capability.READ), Capability.READ, read)

    def test_missing_closure_stale_snapshot_and_cloned_volume_keep_original(self):
        before = self.state()
        with self.one_uid():
            for field, value in (("start_sha256", "0" * 64), ("volume_sha256", "0" * 64),
                                 ("current_boot_sha256", self.expected["predecessor_boot_sha256"]),
                                 ("current_policy_epoch", self.expected["current_policy_epoch"] + 1)):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    self.bootstrap(self.seal(dict(self.expected, **{field: value}))).bind(self.journal, self.identity, self.config)
            with self.assertRaises(ValueError):
                require_successor(self.old, replace(self.current, persistent=self.volume))
            with self.assertRaises(ValueError):
                require_successor(self.old, replace(self.current, persistent=replace(self.current.persistent, volume_sha256="b"*64)))
            (self.root / "writer-closed-synced").unlink()
            with self.assertRaisesRegex(ValueError, "CLOSURE_UNAVAILABLE"):
                self.bootstrap(self.succession).bind(self.journal, self.identity, self.config)
        self.assertEqual(before, self.state())
        self.assertEqual(1, len(self.broker.dispatches()))

    def test_controller_records_barrier_before_power_and_derives_only_an_unsigned_expectation(self):
        import io
        from scripts.unification.native_s1.host import canonical
        from scripts.unification.native_s2 import controller, expected, storage

        root = self.root / "manager"
        root.mkdir(mode=0o700)
        disk = root / "disk.raw"
        disk.write_bytes(bytes(8192))
        disk.chmod(0o600)
        volume = self.volume.volume_sha256
        storage.initialize(root, volume)
        for predecessor in range(self.volume.generation):
            credential = storage.advance(root, volume, predecessor)
        with ExitStack() as stack:
            export = storage.Export(root, credential)
            stack.callback(export.close)
            plan = {"case": "C4b", "session": "a" * 32, "volume": asdict(self.volume),
                    "source_sha": "a" * 40, "tree": "b" * 40, "vm_uuid": str(uuid.uuid4()),
                    "boot_sha256": self.expected["predecessor_boot_sha256"], "authority_spki": self.manager.spki}
            original = {"vm_uuid": plan["vm_uuid"], "trial": plan["case"], "source": plan["source_sha"],
                        "tree": plan["tree"], "predecessor_boot": plan["boot_sha256"], "storage": self.old.to_dict(),
                        "core_spki": self.identity.spki, "enrollment": asdict(self.enrollment)}
            grant = boundary._seal(self.identity, {"schema": boundary.AUTHORIZATION, "binding": self.binding.to_wire(),
                                                 "object_batch": {"bytes": 1, "sha256": "d" * 64}})
            initial = {"intent": "Unknown", "outbox": "HELD", "reservation": "UNKNOWN",
                       "reservation_digest": self.binding.request.reservation_digest}
            first = {"event": "authorized", "plan": plan, "original": original, "initial": initial, "grant": grant,
                     "original_sha256": sha(canonical(original)), "start_sha256": sha(canonical({"grant": grant, "initial": initial}))}
            query = {"schema": "aioa.native.s2-writer-readback.v1", "volume_sha256": volume, "generation": 7,
                     "boot_sha256": plan["boot_sha256"], "storage_sha256": self.old.digest,
                     "exact_ref": self.old.exact_ref, "binding_sha256": digest(self.binding.to_wire()), "challenge": "f" * 64}
            barrier = {"event": "barrier", "point": controller.BARRIERS["C4b"], "session": plan["session"],
                       "start": self.binding.request.start_digest, "ref_oid": self.binding.request.new_oid,
                       "ack_received": False, "publications": 1, "dispatch_requests": 1, "link_attempts": 1,
                       **{k: self.expected[k] for k in ("witness_sha256", "completion_sha256", "writer_closed_sha256")}}
            entered = []
            log = controller.RunLog(root / "trial")
            def observe_cut():
                self.assertTrue((log.path / "barrier.json").is_file())
                entered.append(True)
            # These streams carry data only. No hypervisor is invoked.
            stream = SimpleNamespace(readline=io.BytesIO(b"".join(map(canonical, (
                first, {"event": "admission", "query": query}, barrier)))).readline,
                write=io.BytesIO().write, flush=lambda: None)
            controller.supervise(stream, plan, root, self.manager, log, observe_cut)
            self.assertEqual([True], entered)
            next_plan = dict(plan, volume=asdict(self.current.persistent), boot_sha256=boot_hash())
            with self.assertRaises(FileNotFoundError):
                expected.from_controller(root, log.path, next_plan, self.reader.spki, self.binding.request.core_epoch)
            log.record("power-returned", {"uuid": plan["vm_uuid"], "state": "shut off"})
            new = storage.Export(root, storage.advance(root, volume, 7, cold_read=True))
            stack.callback(new.close)
            with self.assertRaises(storage.Fenced):
                storage.arm(root, volume, 8, boot_hash(), self.current.digest, self.old.exact_ref, "d" * 64)
            derived = expected.from_controller(root, log.path, next_plan, self.reader.spki, self.binding.request.core_epoch)
            self.assertNotEqual(self.expected["challenge"], derived["challenge"])
            self.assertEqual(self.expected, dict(derived, challenge=self.expected["challenge"]))

    def test_racing_cold_readers_use_original_journal_and_one_atomic_settlement(self):
        boot = self.bootstrap(self.succession)
        before = self.state()
        listener_path = str(self.root / "fresh-reader.sock")
        reader, ready = multiprocessing.get_context("fork").Pipe(duplex=False)
        def verify_requests():
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(listener_path)
                listener.listen(4)
                ready.send(True)
                for _ in range(3):
                    boundary.serve_role_verifier_once(listener, root_fd=self.fd, storage=self.current,
                        enrollment=self.enrollment, identity=self.reader,
                        core_peer=Peer(os.getppid(), self.current.core.uid, self.current.core.gid),
                        core_spki=self.identity.spki, enabled=True, succession=self.succession)
        with self.one_uid():
            self.assertEqual(self.binding.request.exact_ref, boot.bind(
                self.journal, self.identity, self.config).qualification_target.exact_ref)
            process = multiprocessing.get_context("fork").Process(target=verify_requests)
            process.start()
            try:
                self.assertTrue(reader.poll(5) and reader.recv())
                port = boot.recovery_port(self.adapter, self.tasks, endpoint=listener_path,
                    peer=Peer(process.pid, self.current.verifier.uid, self.current.verifier.gid),
                    verifier_spki=self.reader.spki, identity=self.identity)
                self.tasks.native_witness_recovery_port = port
                def reconcile():
                    return self.tasks.request(self.fresh.p(), "reconcile", {"task_id": self.task})
                rendezvous = threading.Barrier(2, timeout=5)
                def concurrent(_):
                    rendezvous.wait()
                    return reconcile()
                with ThreadPoolExecutor(2) as pool:
                    left, right = pool.map(concurrent, range(2))
                after = self.state()
                repeated = reconcile()
                self.assertEqual(after, self.state())
                self.assertEqual((before[0] + 1, "Applied", before[2] + 1), after)
                for result in (left, right, repeated):
                    self.assertEqual(left["intent"], result["intent"])
                    self.assertEqual(process.pid, result["verification_process_pid"])
                process.join(timeout=5)
                self.assertEqual(0, process.exitcode)
            finally:
                if process.is_alive():
                    process.terminate()
                process.join()
                reader.close()
                ready.close()
        self.assertEqual(1, len(self.broker.dispatches()))
