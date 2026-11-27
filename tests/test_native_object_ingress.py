import hashlib
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.red_hat.broker_protocol import ProtocolError, read_frame, send_frame
from runtime.red_hat.object_ingress import decode_objects, encode_objects, import_objects


def obj(kind, data):
    raw = f"{kind} {len(data)}".encode() + b"\0" + data
    return kind, data, hashlib.sha1(raw).hexdigest()


class NativeObjectIngressTests(unittest.TestCase):
    def setUp(self):
        self.blob = obj("blob", b"approved\n")
        self.tree = obj("tree", b"100644 message\0" + bytes.fromhex(self.blob[2]))
        self.commit = obj("commit", b"tree " + self.tree[2].encode() + b"\n")
        self.objects = (self.blob, self.tree, self.commit)

    def test_import_is_create_only_and_readable_by_git(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["/usr/bin/git", "init", "--bare", "-q", directory], check=True)
            repo = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, repo)
            objects = decode_objects(encode_objects(self.objects), expected_commit=self.commit[2])
            import_objects(repo, os.getuid(), objects)
            prefix, leaf = self.blob[2][:2], self.blob[2][2:]
            path = Path(directory, "objects", prefix, leaf)
            original = path.stat().st_ino
            import_objects(repo, os.getuid(), objects)
            self.assertEqual(original, path.stat().st_ino)
            data = subprocess.check_output(["/usr/bin/git", "-C", directory, "cat-file", "blob", self.blob[2]])
            self.assertEqual(b"approved\n", data)
            self.assertEqual([], list(Path(directory, "refs", "heads").iterdir()))

    def test_existing_different_content_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, repo)
            path = Path(directory, "objects", self.blob[2][:2], self.blob[2][2:])
            path.parent.mkdir(parents=True)
            path.write_bytes(b"unexpected")
            objects = decode_objects(encode_objects(self.objects), expected_commit=self.commit[2])
            with self.assertRaisesRegex(ValueError, "NATIVE_OBJECT_EXISTING"):
                import_objects(repo, os.getuid(), objects)
            self.assertEqual(b"unexpected", path.read_bytes())

    def test_wrong_commit_missing_graph_unreferenced_object_and_truncation(self):
        other = obj("blob", b"unrelated")
        for objects, commit, cut in (
            (self.objects, "0" * 40, False),
            (self.objects[1:], self.commit[2], False),
            ((other, *self.objects), self.commit[2], False),
            (self.objects, self.commit[2], True),
        ):
            with self.subTest(objects=len(objects), cut=cut):
                raw = encode_objects(objects)
                with self.assertRaises(ProtocolError):
                    decode_objects(raw[:-1] if cut else raw, expected_commit=commit)

    def test_object_body_is_explicit_and_cannot_hide_trailing_bytes(self):
        for announced, code in ((3, None), (2, "TRAILING"), (4, "TRUNCATED")):
            with self.subTest(announced=announced):
                left, right = socket.socketpair()
                with left, right:
                    send_frame(left, {"size": announced}, body=b"abc")
                    def receive(frame, exact):
                        return exact(frame["size"])
                    if code is None:
                        self.assertEqual(b"abc", read_frame(right, receive_body=receive))
                    else:
                        with self.assertRaisesRegex(ProtocolError, code):
                            read_frame(right, receive_body=receive)
