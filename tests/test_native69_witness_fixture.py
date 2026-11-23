"""Fixture-only comparison of real publication, acknowledgement and signed custody."""
import hashlib
import json
import os
import stat
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

if __name__ == "__main__":
    checkout = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(checkout), str(checkout / "tests")]

from cryptography.hazmat.primitives.asymmetric import ec

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.mission.sandbox_linux import LinuxSandboxBroker
from runtime.mobile_gateway.wire import Identity, MobileError, verify
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


def observed(envelope, expected, trusted_spki):
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
    try:
        verify(trusted_spki, envelope["signature"], payload)
    except MobileError:
        return False
    return True


def broker(root, scenario, expected):
    signer = new_identity()
    print(signer.spki, flush=True)
    assert sys.stdin.read(1) == "Y"
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
        if scenario == "lost-after-witness":
            os._exit(76)
        print("ACK", flush=True)
    finally:
        os.close(parent)


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
        "intent": digest(b"fixture durable START"),
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
        "known-success": (0, "ACK"), "lost-after-witness": (76, ""),
        "lost-before-witness": (75, ""), "foreign-same-oid": (0, "CONFLICT"),
    }[scenario], result
    assert git(repo, "rev-parse", "--verify", REF) == commit
    envelope = receipt_read(root)
    valid = scenario in {"known-success", "lost-after-witness"}
    assert observed(envelope, expected, trusted_spki) is valid
    if valid:
        for field in ("operation", "warrant", "reservation", "intent", "ref", "new_oid", "invocation"):
            assert not observed(envelope, {**expected, field: "mismatch"}, trusted_spki), field
        assert not observed(envelope, {**expected, "repository": [1, 2]}, trusted_spki)
        assert not observed(envelope, expected, new_identity().spki)
        altered = {"payload": {**envelope["payload"], "published_inode": [1, 2]},
                   "signature": envelope["signature"]}
        assert not observed(altered, expected, trusted_spki)
    return {"ref_matches": True, "witness_verified": valid, "process_status": result[0], "ack": result[1]}


class NativeWitnessCustodyFixtureTests(unittest.TestCase):
    def test_same_ref_state_only_accepts_a_durable_witness_from_enrolled_broker(self):
        expected = {
            "known-success": True, "lost-after-witness": True, "lost-before-witness": False,
            "foreign-same-oid": False, "older-unknown": False,
        }
        with tempfile.TemporaryDirectory(prefix="native69-custody-artifacts-") as scratch:
            for scenario, verified in expected.items():
                with self.subTest(scenario=scenario):
                    result = compare(Path(scratch) / scenario, scenario)
                    self.assertTrue(result["ref_matches"])
                    self.assertEqual(verified, result["witness_verified"])


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "broker":
        broker(Path(sys.argv[2]), sys.argv[3], json.loads(sys.argv[4]))
    else:
        unittest.main()
