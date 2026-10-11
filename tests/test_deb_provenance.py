"""Offline supply-chain denial tests; fixtures confer no release authority."""
import copy
import hashlib
import importlib.util
import io
import json
import lzma
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("u13_builder", ROOT / "scripts/build_deb_candidate.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def deb_bytes(files, *, extra=None, control=None):
    """Independent tiny ar/tar fixture, including hostile entries when requested."""
    def archive(items):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            for name, raw, mode, kind in items:
                info = tarfile.TarInfo(name)
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                info.mtime = 1
                info.mode = mode
                info.type = kind
                if kind == tarfile.SYMTYPE:
                    info.linkname = "/etc/passwd"
                elif kind == tarfile.REGTYPE:
                    info.size = len(raw)
                tar.addfile(info, io.BytesIO(raw) if kind == tarfile.REGTYPE else None)
        return lzma.compress(stream.getvalue())
    directories = {"."}
    for name in files:
        directories.update(str(p) for p in Path(name).parents if str(p) != ".")
    payload = [("./" if n == "." else "./" + n, b"", 0o755, tarfile.DIRTYPE) for n in sorted(directories)]
    payload += [("./" + n, raw, mode, tarfile.REGTYPE) for n, (raw, mode) in files.items()]
    if extra:
        payload.append(extra)
    ctl = control or b"Package: aioa-sparkhat\nVersion: 1\nArchitecture: amd64\n"
    members = [("debian-binary", b"2.0\n"),
               ("control.tar.xz", archive([("./", b"", 0o755, tarfile.DIRTYPE), ("./control", ctl, 0o644, tarfile.REGTYPE)])),
               ("data.tar.xz", archive(payload))]
    result = b"!<arch>\n"
    for name, raw in members:
        header = f"{name + '/':<16}{1:<12}{0:<6}{0:<6}{'100644':<8}{len(raw):<10}`\n".encode()
        result += header + raw + (b"\n" if len(raw) % 2 else b"")
    return result


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.e = builder.evidence
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = {"usr/bin/aioa-sparkhat": (b"#!/bin/sh\nexit 4\n", 0o755),
                      "usr/share/doc/aioa-sparkhat/LICENSE": (b"MIT License\n", 0o644)}
        self.lock = [{"name": "fixture-lib", "version": "1.2.3-1", "architecture": "amd64",
                      "declared_dependencies": "", "declared_predependencies": "",
                      "delivery": "OS_PROVIDED_NOT_BUNDLED"}]

    def read(self, raw, **kwargs):
        return self.e.read_deb(raw, **kwargs)

    def test_unsigned_archive_checked_without_extracting(self):
        contents = self.read(deb_bytes(self.files))
        self.assertEqual(self.files, contents["files"])
        self.assertFalse(any(self.root.iterdir()))

    def test_exact_payload_modes_owners_and_epoch_accepted(self):
        contents = self.read(deb_bytes(self.files))
        self.e.verify_contents(contents, self.files, contents["control"], 1)

    def test_wrong_control_version_or_unpinned_dependency_rejected(self):
        contents = self.read(deb_bytes(self.files))
        for bad in (b"Version: other\n", b"Depends: python3.12 (>= 3.12)\n"):
            with self.subTest(control=bad), self.assertRaisesRegex(ValueError, "CONTROL_MISMATCH"):
                self.e.verify_contents(contents, self.files, bad, 1)

    def test_wrong_source_epoch_rejected(self):
        contents = self.read(deb_bytes(self.files))
        with self.assertRaisesRegex(ValueError, "ARCHIVE_EPOCH_MISMATCH"):
            self.e.verify_contents(contents, self.files, contents["control"], 2)

    def test_artifact_tamper_rejected_by_external_expected_digest(self):
        raw = deb_bytes(self.files)
        digest = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "ARTIFACT_HASH_MISMATCH"):
            self.read(raw + b"x", expected_sha256=digest)

    def test_digest_pin_required_to_match(self):
        raw = deb_bytes(self.files)
        self.assertEqual(self.files, self.read(raw, expected_sha256=hashlib.sha256(raw).hexdigest())["files"])
        with self.assertRaisesRegex(ValueError, "ARTIFACT_HASH_MISMATCH"):
            self.read(raw, expected_sha256="a" * 64)

    def test_unexpected_path_rejected_by_payload_comparison(self):
        contents = self.read(deb_bytes({**self.files, "usr/private.py": (b"private", 0o644)}))
        with self.assertRaisesRegex(ValueError, "PAYLOAD_PATH_MISMATCH"):
            self.e.verify_contents(contents, self.files, contents["control"], 1)

    def test_missing_license_rejected(self):
        contents = self.read(deb_bytes({n: v for n, v in self.files.items() if not n.endswith("LICENSE")}))
        with self.assertRaisesRegex(ValueError, "PAYLOAD_PATH_MISMATCH"):
            self.e.verify_contents(contents, self.files, contents["control"], 1)

    def test_modified_attribution_rejected(self):
        files = {**self.files, "usr/share/doc/aioa-sparkhat/LICENSE": (b"removed attribution", 0o644)}
        contents = self.read(deb_bytes(files))
        with self.assertRaisesRegex(ValueError, "PAYLOAD_HASH_OR_MODE_MISMATCH"):
            self.e.verify_contents(contents, self.files, contents["control"], 1)

    def test_non_executable_launcher_rejected(self):
        files = {**self.files, "usr/bin/aioa-sparkhat": (self.files["usr/bin/aioa-sparkhat"][0], 0o644)}
        contents = self.read(deb_bytes(files))
        with self.assertRaisesRegex(ValueError, "PAYLOAD_HASH_OR_MODE_MISMATCH"):
            self.e.verify_contents(contents, self.files, contents["control"], 1)

    def test_symlink_rejected_before_extraction(self):
        with self.assertRaisesRegex(ValueError, "ARCHIVE_TYPE_DENIED"):
            self.read(deb_bytes(self.files, extra=("./usr/alias", b"", 0o777, tarfile.SYMTYPE)))

    def test_traversal_absolute_and_private_paths_rejected(self):
        for path in ("./../outside", "/etc/passwd", "./usr/.env", "./home/owner/private.py", "./usr/.git/config"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "ARCHIVE_PATH_DENIED"):
                self.read(deb_bytes(self.files, extra=(path, b"private", 0o644, tarfile.REGTYPE)))

    def test_duplicate_archive_path_rejected(self):
        with self.assertRaisesRegex(ValueError, "ARCHIVE_DUPLICATE_PATH"):
            self.read(deb_bytes(self.files, extra=("./usr/bin/aioa-sparkhat", b"other", 0o755, tarfile.REGTYPE)))

    def test_archive_size_bounded(self):
        with self.assertRaisesRegex(ValueError, "ARTIFACT_SIZE_DENIED"):
            self.read(b"x" * (self.e.MAX_DEB_BYTES + 1))

    def test_compressed_payload_bomb_bounded(self):
        raw = deb_bytes({"usr/bomb": (b"x" * (self.e.MAX_TAR_BYTES + 1), 0o644)})
        with self.assertRaisesRegex(ValueError, "ARCHIVE_SIZE_DENIED"):
            self.read(raw)

    def test_hidden_trailing_tar_data_and_padding_rejected(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            item = tarfile.TarInfo("usr/data")
            item.size = 1
            item.mode = 0o644
            item.uname = item.gname = "root"
            tar.addfile(item, io.BytesIO(b"a"))
        raw = stream.getvalue()
        bad_padding = bytearray(raw)
        bad_padding[513] = 120
        for data in (raw + b"private".ljust(512, b"\0"), bytes(bad_padding)):
            with self.assertRaisesRegex(ValueError, "ARCHIVE_INVALID"):
                self.e.read_tar(lzma.compress(data))

    def test_maintainer_script_rejected(self):
        contents = self.read(deb_bytes(self.files))
        contents["control_files"]["postinst"] = (b"#!/bin/sh\n", 0o755)
        with self.assertRaisesRegex(ValueError, "CONTROL_MISMATCH"):
            self.e.verify_contents(contents, self.files, contents["control"], 1)

    def test_unpinned_dependency_rejected(self):
        for version in ("", ">=1.0", "*", "latest"):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "DEPENDENCY_PIN_REQUIRED"):
                self.e.validate_lock([{**self.lock[0], "version": version}])

    def test_dependency_duplicate_and_wrong_arch_rejected(self):
        for records in (self.lock * 2, [{**self.lock[0], "architecture": "arm64"}]):
            with self.assertRaisesRegex(ValueError, "DEPENDENCY_PIN_REQUIRED"):
                self.e.validate_lock(records)

    def test_actual_license_evidence_preserved_without_guessing(self):
        path = self.root / "fixture-lib/copyright"
        path.parent.mkdir()
        path.write_text("Copyright Fixture Authors\nUnclassified license text\n")
        notices = self.e.dependency_notices(self.lock, self.root)
        self.assertEqual("REVIEW_REQUIRED", notices[0]["status"])
        self.assertEqual("NOASSERTION", notices[0]["license_concluded"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), notices[0]["sha256"])
        self.assertEqual(path.read_text(), notices[0]["text"])

    def test_absent_dependency_license_blocks(self):
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_LICENSE_REQUIRED"):
            self.e.dependency_notices(self.lock, self.root)

    def test_notice_without_attribution_or_license_blocks(self):
        path = self.root / "fixture-lib/copyright"
        path.parent.mkdir()
        for text in ("License permission without attribution " * 2, "Copyright fixture, other unrelated text " * 2):
            path.write_text(text)
            with self.assertRaisesRegex(ValueError, "DEPENDENCY_LICENSE_REQUIRED"):
                self.e.dependency_notices(self.lock, self.root)

    def test_symlink_dependency_license_blocks(self):
        path = self.root / "fixture-lib/copyright"
        path.parent.mkdir()
        outside = self.root / "outside"
        outside.write_text("Copyright canary\n")
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_LICENSE_REQUIRED"):
            self.e.dependency_notices(self.lock, self.root)

    def test_shared_copyright_owner_must_be_pinned_to_same_version(self):
        record = {**self.lock[0], "name": "libgcc-s1"}
        for lock in ([record], [record, {**record, "name": "gcc-14-base", "version": "9.9"}]):
            with self.assertRaisesRegex(ValueError, "DEPENDENCY_LICENSE_REQUIRED"):
                self.e.dependency_notices(sorted(lock, key=lambda r: r["name"]), self.root)

    def test_unsupported_python_abi_and_architecture_block(self):
        for abi, arch in (("cp311", "amd64"), ("cp313", "amd64"), ("cp312", "arm64")):
            with self.assertRaisesRegex(ValueError, "CANDIDATE_ABI_REQUIRED"):
                self.e.validate_abi(abi, arch)

    def test_version_and_project_identity_mismatch_block(self):
        for args in (("0.2.0~u12.1", "aioa-sparkhat", "0.2.0"),
                     ("0.2.0~u13.1", "other", "0.2.0"), ("0.2.0~u13.1", "aioa-sparkhat", "0.3.0")):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "CANDIDATE_VERSION_MISMATCH"):
                self.e.validate_version(*args)

    def test_absent_signer_and_host_certification_do_not_accept_release(self):
        self.assertEqual("PASS_LOCAL_LIMITED", self.e.check_scope("diagnostic"))
        for scope in ("release", "production", "P1", "P3"):
            with self.assertRaisesRegex(ValueError, "RELEASE_NOT_ACCEPTED"):
                self.e.check_scope(scope)

    def sbom_context(self):
        raw = b"value = 5\n"
        return {"version": "0.2.0~u13.1", "source": {"commit": "a" * 40, "tree": "b" * 40,
                "epoch": 1, "inputs": []}, "source_inventory": [{"path": "runtime/main.py",
                "sha256": hashlib.sha256(raw).hexdigest(), "sha1": hashlib.sha1(raw).hexdigest(),
                "bytes": len(raw), "license": "MIT", "notice": "LICENSE"}],
                "abi": {"python_abi": "cp312", "architecture": "amd64", "os_dependencies": self.lock},
                "notices": [{"name": "fixture-lib", "path": "/usr/share/doc/fixture-lib/copyright",
                "sha256": hashlib.sha256(b"Copyright fixture").hexdigest(), "text": "Copyright fixture",
                "status": "REVIEW_REQUIRED", "license_concluded": "NOASSERTION"}], "toolchain": []}

    def test_spdx_is_deterministic_and_binds_artifact_source_abi_and_licenses(self):
        context = self.sbom_context()
        first = self.e.spdx_sbom(context, "c" * 64)
        self.assertEqual(self.e.canonical_json(first), self.e.canonical_json(self.e.spdx_sbom(context, "c" * 64)))
        self.assertEqual("SPDX-2.3", first["spdxVersion"])
        self.assertEqual("CC0-1.0", first["dataLicense"])
        self.e.validate_spdx(first)
        self.assertIn("a" * 40, first["comment"])
        self.assertIn("b" * 40, first["comment"])
        self.assertIn("cp312", first["comment"])
        package = next(p for p in first["packages"] if p["SPDXID"] == "SPDXRef-Artifact")
        self.assertEqual("c" * 64, package["checksums"][0]["checksumValue"])
        self.assertEqual("MIT", first["files"][0]["licenseConcluded"])
        self.assertEqual("Copyright fixture", first["hasExtractedLicensingInfos"][0]["extractedText"])

    def test_sbom_missing_license_or_dangling_relationship_denied(self):
        bom = self.e.spdx_sbom(self.sbom_context(), "c" * 64)
        for change in ("license", "relationship"):
            bad = copy.deepcopy(bom)
            if change == "license":
                del bad["files"][0]["licenseConcluded"]
            else:
                bad["relationships"][0]["relatedSpdxElement"] = "SPDXRef-Absent"
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "SPDX_REQUIRED"):
                self.e.validate_spdx(bad)

    def test_sbom_changes_with_package_hash_and_source_identity(self):
        context = self.sbom_context()
        bom = self.e.spdx_sbom(context, "c" * 64)
        self.assertNotEqual(bom, self.e.spdx_sbom(context, "d" * 64))
        context["source"]["tree"] = "e" * 40
        self.assertNotEqual(bom, self.e.spdx_sbom(context, "c" * 64))


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.e = builder.evidence
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        self.git("init", "--quiet")
        (self.root / "owned.py").write_text("value = 5\n")
        self.git("add", "owned.py")
        self.git("-c", "user.name=Offline Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.tree = self.git("rev-parse", "HEAD^{tree}").strip()

    def git(self, *args):
        return subprocess.check_output(["/usr/bin/git", *args], cwd=self.root, env=self.env, text=True)

    def pin(self, **changes):
        return self.e.pin_source(self.root, changes.get("head", self.head), changes.get("tree", self.tree),
                                 ["owned.py"], builder.regular_bytes)

    def test_exact_git_commit_tree_and_bytes_bound(self):
        result = self.pin()
        self.assertEqual(self.head, result["commit"])
        self.assertEqual(self.tree, result["tree"])
        self.assertEqual(hashlib.sha256((self.root / "owned.py").read_bytes()).hexdigest(), result["inputs"][0]["sha256"])

    def test_wrong_commit_and_tree_denied(self):
        for changes in ({"head": "a" * 40}, {"tree": "b" * 40}):
            with self.assertRaisesRegex(ValueError, "SOURCE_IDENTITY_MISMATCH"):
                self.pin(**changes)

    def test_dirty_source_denied(self):
        (self.root / "owned.py").write_text("value = 6\n")
        with self.assertRaisesRegex(ValueError, "CLEAN_SOURCE_REQUIRED"):
            self.pin()

    def test_assume_unchanged_does_not_hide_source_drift(self):
        self.git("update-index", "--assume-unchanged", "owned.py")
        (self.root / "owned.py").write_text("value = 6\n")
        self.assertEqual("", self.git("status", "--porcelain=v1"))
        with self.assertRaisesRegex(ValueError, "SOURCE_BLOB_MISMATCH"):
            self.pin()

    def test_untracked_outside_source_denied(self):
        (self.root / "private.py").write_text("private state\n")
        with self.assertRaisesRegex(ValueError, "CLEAN_SOURCE_REQUIRED"):
            self.pin()

    def test_source_symlink_denied(self):
        (self.root / "owned.py").unlink()
        (self.root / "owned.py").symlink_to("outside.py")
        (self.root / "outside.py").write_text("canary\n")
        with self.assertRaises(ValueError):
            self.pin()


if __name__ == "__main__":
    unittest.main()
