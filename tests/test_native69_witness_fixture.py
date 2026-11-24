"""Fixture-only comparison of real publication, acknowledgement and signed custody."""
import base64
import hashlib
import json
import os
import stat
import select
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

if __name__ == "__main__":
    checkout = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(checkout), str(checkout / "tests")]

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.mission.sandbox_linux import LinuxSandboxBroker
from runtime.mobile_gateway.wire import Identity, MobileError, verify
from runtime.red_hat.witness import (
    RegisteredExecutor, WitnessBinding, persist_witness, verify_witness, witness_payload,
)
from test_nz25_intent_cold_read import git

REF = "refs/heads/fixture-publication"
RECEIPT = "fixture-publication-receipt.json"
SCHEMA = "aioa.fixture-cas-custody.v1"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def new_identity():
    return Identity(ec.generate_private_key(ec.SECP256R1()))


def directory(path):
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)


def inode(info):
    return [info.st_dev, info.st_ino]


def receipt_write(path, payload):
    parent = directory(path)
    try:
        fd = os.open(RECEIPT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical_json_bytes(payload))
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)
    finally:
        os.close(parent)


def receipt_read(path):
    parent = directory(path)
    try:
        try:
            fd = os.open(RECEIPT, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            assert stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            assert info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
            assert 0 < info.st_size <= 8192
            raw = stream.read(8193)
            assert len(raw) == info.st_size
            current = os.stat(RECEIPT, follow_symlinks=False, dir_fd=parent)
            assert inode(info) == inode(current) and info.st_ctime_ns == current.st_ctime_ns
            return json.loads(raw)
    finally:
        os.close(parent)


def observed(envelope, expected, trusted_spki, *, published_inode=None):
    if envelope is None or set(envelope) != {"payload", "signature"}:
        return False
    payload = envelope["payload"]
    immutable = {k: v for k, v in payload.items() if k != "published_inode"}
    if immutable != expected or type(payload.get("published_inode")) is not list:
        return False
    if len(payload["published_inode"]) != 2 or not all(
        type(value) is int and value > 0 for value in payload["published_inode"]
    ):
        return False
    if payload["published_inode"] != published_inode:
        return False
    try:
        verify(trusted_spki, envelope["signature"], payload)
    except MobileError:
        return False
    return True


def sign_candidate(signer, payload):
    signature = signer.key.sign(canonical_json_bytes(payload), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode("ascii")


def candidate_binding(expected, executor):
    return WitnessBinding(
        executor=executor.executor, key_id=executor.key_id, nonce=expected["invocation"],
        start_digest=expected["start"], intent_digest=expected["intent"],
        warrant_digest=expected["warrant"], reservation_digest=expected["reservation"],
        epoch=1, repository=tuple(expected["repository"]),
        ref_directory=tuple(expected["ref_directory"]), ref=expected["ref"],
        old_oid=expected["old_oid"], new_oid=expected["new_oid"],
        issued_at=100, expires_at=200,
    )


def broker(root, scenario, expected):
    signer = new_identity()
    print(signer.spki, flush=True)
    assert sys.stdin.read(1) == "Y"
    if scenario == "lost-before-cas":
        os._exit(74)
    repo = root / "repo.git"
    parent = directory(repo / "refs/heads")
    try:
        assert inode(os.fstat(parent)) == expected["ref_directory"]
        assert inode(repo.stat()) == expected["repository"]
        original_link = os.link
        publication = []

        def observe_link(source, name, *, dst_dir_fd, follow_symlinks):
            handle = os.stat(source)
            assert handle.st_nlink == 0 and dst_dir_fd == parent
            original_link(source, name, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks)
            publication.append(inode(handle))

        # Only the private test wraps a kernel call. The descriptor and actual syscall
        # stay in the broker subprocess.
        with patch.object(os, "link", observe_link):
            published = LinuxSandboxBroker._git_publish_new(
                parent, REF.rsplit("/", 1)[1], (expected["new_oid"] + "\n").encode(), cancel=None
            )
        if not published:
            assert not publication
            print("CONFLICT", flush=True)
            return
        if scenario == "lost-before-witness":
            os._exit(75)
        assert publication == [inode(
            os.stat(REF.rsplit("/", 1)[1], follow_symlinks=False, dir_fd=parent)
        )]
        payload = {**expected, "published_inode": publication[0]}
        receipt_write(root, {"payload": payload, "signature": signer.sign(payload)})
        executor = RegisteredExecutor("fixture-executor", os.geteuid(), signer.spki)
        binding = candidate_binding(expected, executor)
        published_inode = tuple(publication[0])
        candidate = witness_payload(binding, published_inode=published_inode, published_at=123)
        witness_directory = directory(root)
        try:
            persist_witness(
                witness_directory, binding, executor, signature=sign_candidate(signer, candidate),
                published_inode=published_inode, published_at=123,
            )
        finally:
            os.close(witness_directory)
        if scenario == "lost-after-witness":
            os._exit(76)
        print("ACK", flush=True)
    finally:
        os.close(parent)


def readback(root, expected, trusted_spki):
    repo = root / "repo.git"
    ref_path = repo / REF
    executor = RegisteredExecutor("fixture-executor", os.geteuid(), trusted_spki)
    witness_directory = directory(root)
    try:
        return verify_witness(
            witness_directory, candidate_binding(expected, executor), executor,
            repository=tuple(inode(repo.stat())),
            ref_directory=tuple(inode(ref_path.parent.stat())),
            published_inode=tuple(inode(ref_path.lstat())),
        )
    finally:
        os.close(witness_directory)


def compare(root, scenario):
    root.mkdir(mode=0o700)
    repo = root / "repo.git"
    repo.mkdir(mode=0o700)
    git(repo, "init", "--bare", "--object-format=sha1")
    commit = git(repo, "commit-tree", git(repo, "mktree", input=""), "-m", "Custody fixture")
    expected = {
        "schema": SCHEMA, "authority": "NONE", "stage": "EXCLUSIVE_LINK_AND_DIRECTORY_FSYNC",
        "invocation": os.urandom(32).hex(), "operation": digest(b"fixture operation"),
        "warrant": digest(b"fixture warrant"), "reservation": digest(b"fixture reservation"),
        "start": digest(b"fixture durable START"), "intent": digest(b"fixture intent"),
        "repository": inode(repo.stat()), "ref_directory": inode((repo / "refs/heads").stat()),
        "ref": REF, "old_oid": "0" * 40, "new_oid": commit,
    }
    if scenario == "foreign-same-oid":
        git(repo, "update-ref", REF, commit, "0" * 40)
    if scenario == "older-unknown":
        git(repo, "update-ref", REF, commit, "0" * 40)
        assert not observed(receipt_read(root), expected, new_identity().spki)
        return {"ref_matches": True, "witness_verified": False, "broker_started": False}
    with subprocess.Popen(
        [sys.executable, "-I", "-B", __file__, "broker", str(root), scenario, json.dumps(expected)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) as child:
        # The enrolled key is a fixture handshake separate from the receipt file.
        try:
            ready, _, _ = select.select([child.stdout], [], [], 10)
            assert ready, "fixture broker enrollment timeout"
            trusted_spki = child.stdout.readline(257).strip()
            assert trusted_spki and len(trusted_spki) <= 256
            ack, stderr = child.communicate("Y", timeout=15)
            result = child.returncode, ack.strip()
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)
    assert not stderr, stderr
    assert result == {
        "lost-before-cas": (74, ""), "known-success": (0, "ACK"), "lost-after-witness": (76, ""),
        "lost-before-witness": (75, ""), "foreign-same-oid": (0, "CONFLICT"),
    }[scenario], result
    ref_path = repo / REF
    if scenario == "lost-before-cas":
        assert not ref_path.exists()
        assert receipt_read(root) is None
        return {"ref_matches": False, "witness_verified": False}
    assert git(repo, "rev-parse", "--verify", REF) == commit
    published_inode = inode(ref_path.lstat())
    envelope = receipt_read(root)
    valid = scenario in {"known-success", "lost-after-witness"}
    def verify_observation(candidate, bindings=expected, key=trusted_spki):
        return observed(candidate, bindings, key, published_inode=published_inode)

    assert verify_observation(envelope) is valid
    assert readback(root, expected, trusted_spki) is valid
    if scenario == "lost-after-witness":
        readback_process = subprocess.run(
            [sys.executable, "-I", "-B", __file__, "readback", str(root),
             json.dumps(expected), trusted_spki],
            capture_output=True, text=True, timeout=15,
        )
        assert readback_process.returncode == 0, readback_process.stderr
        assert readback_process.stdout.strip() == "VERIFIED_FIXTURE"
    if valid:
        for field in ("operation", "warrant", "reservation", "start", "intent", "ref", "old_oid", "new_oid", "invocation"):
            assert not verify_observation(envelope, {**expected, field: "mismatch"}), field
        for field in ("repository", "ref_directory"):
            assert not verify_observation(envelope, {**expected, field: [1, 2]})
        assert not verify_observation(envelope, key=new_identity().spki)
        altered = {"payload": {**envelope["payload"], "published_inode": [1, 2]},
                   "signature": envelope["signature"]}
        assert not verify_observation(altered)
        # Verify the signature even when the caller's inode observation agrees
        # with the tampered payload.
        assert not observed(altered, expected, trusted_spki, published_inode=[1, 2])

        for duplicate in (envelope, altered):
            with unittest.TestCase().assertRaises(FileExistsError):
                receipt_write(root, duplicate)
            assert receipt_read(root) == envelope

        replacement = ref_path.with_suffix(".replacement")
        replacement.write_bytes(ref_path.read_bytes())
        replacement.replace(ref_path)
        assert git(repo, "rev-parse", "--verify", REF) == commit
        assert not readback(root, expected, trusted_spki)
        assert not observed(
            envelope, expected, trusted_spki, published_inode=inode(ref_path.lstat())
        )
    return {"ref_matches": True, "witness_verified": valid, "process_status": result[0], "ack": result[1]}


class NativeWitnessCustodyFixtureTests(unittest.TestCase):
    def test_same_ref_state_only_accepts_a_durable_witness_from_enrolled_broker(self):
        expected = {
            "known-success": True, "lost-after-witness": True, "lost-before-witness": False,
            "lost-before-cas": False, "foreign-same-oid": False, "older-unknown": False,
        }
        with tempfile.TemporaryDirectory(prefix="native69-custody-artifacts-") as scratch:
            for scenario, verified in expected.items():
                with self.subTest(scenario=scenario):
                    result = compare(Path(scratch) / scenario, scenario)
                    self.assertEqual(scenario != "lost-before-cas", result["ref_matches"])
                    self.assertEqual(verified, result["witness_verified"])


class NativeWitnessContractTests(unittest.TestCase):
    def setUp(self):
        scratch = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(scratch)
        self.directory_fd = directory(self.root)
        self.addCleanup(os.close, self.directory_fd)
        self.signer = new_identity()
        self.executor = RegisteredExecutor("fixture-executor", os.geteuid(), self.signer.spki)
        self.binding = WitnessBinding(
            executor=self.executor.executor, key_id=self.executor.key_id,
            nonce=digest(b"nonce"), start_digest=digest(b"START"), intent_digest=digest(b"intent"),
            warrant_digest=digest(b"warrant"), reservation_digest=digest(b"reservation"),
            epoch=1, repository=(1, 2), ref_directory=(1, 3), ref=REF,
            old_oid="0" * 40, new_oid="1" * 40, issued_at=100, expires_at=200,
        )
        self.inode = (1, 4)

    def persist(self, *, published_at=123, published_inode=None):
        published_inode = self.inode if published_inode is None else published_inode
        payload = witness_payload(
            self.binding, published_inode=published_inode, published_at=published_at
        )
        persist_witness(
            self.directory_fd, self.binding, self.executor, signature=sign_candidate(self.signer, payload),
            published_inode=published_inode, published_at=published_at,
        )

    def verify(self, *, binding=None, executor=None, **changes):
        observation = {
            "repository": self.binding.repository,
            "ref_directory": self.binding.ref_directory,
            "published_inode": self.inode,
        }
        return verify_witness(
            self.directory_fd, binding or self.binding, executor or self.executor,
            **{**observation, **changes},
        )

    def test_create_only_witness_and_exact_readback(self):
        self.assertFalse(self.verify())
        self.persist()
        self.assertTrue(self.verify())
        witness = self.root / self.binding.witness_id
        original = witness.read_bytes()
        for inode_override in (self.inode, (1, 5)):
            with self.subTest(inode=inode_override), self.assertRaises(FileExistsError):
                self.persist(published_inode=inode_override)
        self.assertEqual(original, witness.read_bytes())

    def test_changed_bindings_observations_and_registered_key_are_rejected(self):
        self.persist()
        raw = (self.root / self.binding.witness_id).read_bytes()
        for field in ("nonce", "start_digest", "intent_digest", "warrant_digest", "reservation_digest"):
            other = replace(self.binding, **{field: digest(b"substitution")})
            with self.subTest(field=field):
                candidate = self.root / other.witness_id
                candidate.write_bytes(raw)
                candidate.chmod(0o400)
                self.assertFalse(self.verify(binding=other))
        stale = replace(self.binding, epoch=self.binding.epoch + 1)
        (self.root / stale.witness_id).write_bytes(raw)
        (self.root / stale.witness_id).chmod(0o400)
        self.assertFalse(self.verify(binding=stale))
        for field in ("repository", "ref_directory", "published_inode"):
            with self.subTest(field=field):
                self.assertFalse(self.verify(**{field: (1, 5)}))
        self.assertFalse(self.verify(executor=replace(self.executor, spki=new_identity().spki)))
        self.assertFalse(self.verify(executor=replace(self.executor, executor="foreign-executor")))

    def test_expiry_corruption_truncation_and_symlink_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "CAS_WITNESS_PUBLICATION"):
            self.persist(published_at=self.binding.expires_at)
        self.assertFalse(self.verify())
        self.persist()
        witness = self.root / self.binding.witness_id
        raw = witness.read_bytes()
        envelope = json.loads(raw)
        envelope["signature"] = sign_candidate(new_identity(), envelope["payload"])
        for corrupt in (raw[:len(raw) // 2], canonical_json_bytes(envelope)):
            witness.chmod(0o600)
            witness.write_bytes(corrupt)
            witness.chmod(0o400)
            self.assertFalse(self.verify())
        witness.unlink()
        target = self.root / "foreign"
        target.write_bytes(raw)
        target.chmod(0o400)
        witness.symlink_to(target)
        self.assertFalse(self.verify())


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "broker":
        broker(Path(sys.argv[2]), sys.argv[3], json.loads(sys.argv[4]))
    elif len(sys.argv) == 5 and sys.argv[1] == "readback":
        if not readback(Path(sys.argv[2]), json.loads(sys.argv[3]), sys.argv[4]):
            sys.exit(1)
        print("VERIFIED_FIXTURE")
    else:
        unittest.main()
