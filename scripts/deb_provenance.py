"""Bounded offline SPDX/source/archive evidence for the existing diagnostic builder.

This module verifies bytes, not authority. It cannot certify a host or a signer.
"""
from __future__ import annotations

import datetime
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
from urllib.parse import quote

MAX_DEB_BYTES = 16 * 1024 * 1024
MAX_TAR_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_MEMBERS = 1024
BUILD_INPUTS = (
    "packaging/deb_source_allowlist.txt", "pyproject.toml",
    "scripts/build_deb_candidate.py", "scripts/check_changed_secrets.py",
    "scripts/deb_provenance.py", "scripts/verify_deb_candidate.py",
)
PRIVATE_PARTS = frozenset({".git", ".env", ".venv", "venv", "__pycache__",
                           "keys", "private", "node_modules", "home"})
GIT_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
# These distro packages share a version-matched canonical copyright owner.
# Open only the canonical regular file; never follow the alias directory.
NOTICE_OWNERS = {"libgcc-s1": "gcc-14-base", "libncursesw6": "libtinfo6",
                 "libpython3.12-stdlib": "libpython3.12-minimal"}


def need(value, code):
    if not value:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical_json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode()


def safe_bytes(path, limit=MAX_FILE_BYTES):
    """Open a bounded regular file without following any path component."""
    path = Path(path).absolute()
    need(path == path.resolve(), "REGULAR_FILE_REQUIRED")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    fd = None
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            fd = None
            before = os.fstat(stream.fileno())
            need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and before.st_size <= limit, "REGULAR_FILE_REQUIRED")
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            need(len(raw) == before.st_size and (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                 == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "REGULAR_FILE_CHANGED")
            return raw
    finally:
        os.close(parent)
        if fd is not None:
            os.close(fd)


def git(root, *args):
    result = subprocess.run(["/usr/bin/git", "-c", "core.fsmonitor=false", "-c",
                             "core.hooksPath=/dev/null", *args], cwd=root, env=GIT_ENV,
                            capture_output=True, timeout=30)
    need(result.returncode == 0, "SOURCE_GIT_REQUIRED")
    return result.stdout


def pin_source(root, commit, tree, names, reader):
    root = Path(root).absolute()
    need(root == root.resolve(), "SOURCE_PATH_REQUIRED")
    need(all(type(v) is str and re.fullmatch(r"[0-9a-f]{40}", v) for v in (commit, tree)),
         "SOURCE_IDENTITY_MISMATCH")
    need(not git(root, "status", "--porcelain=v1", "--untracked-files=all"), "CLEAN_SOURCE_REQUIRED")
    need(git(root, "rev-parse", "HEAD").decode().strip() == commit and
         git(root, "rev-parse", "HEAD^{tree}").decode().strip() == tree,
         "SOURCE_IDENTITY_MISMATCH")
    need(git(root, "rev-parse", "--show-object-format").strip() == b"sha1", "SOURCE_GIT_REQUIRED")
    tracked = {}
    for item in git(root, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if item:
            header, name = item.split(b"\t", 1)
            tracked[name.decode("utf-8")] = header.decode("ascii").split()
    records = []
    for name in sorted(set(names)):
        need(name in tracked and tracked[name][0] in ("100644", "100755")
             and tracked[name][1] == "blob", "TRACKED_SOURCE_REQUIRED")
        raw = reader(root, name)
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        need(blob == tracked[name][2], "SOURCE_BLOB_MISMATCH")
        records.append({"path": name, "sha256": sha(raw), "git_blob": blob, "bytes": len(raw)})
    # Cached status must not hide changes elsewhere in the tested source tree.
    need(all(not row or (row[:1] != b"S" and not row[:1].islower())
             for row in git(root, "ls-files", "-v", "-z").split(b"\0")), "SOURCE_FLAGS_DENIED")
    return {"commit": commit, "tree": tree,
            "epoch": int(git(root, "show", "-s", "--format=%ct", commit)), "inputs": records}


def validate_abi(abi, architecture):
    need(abi == "cp312" and architecture == "amd64", "CANDIDATE_ABI_REQUIRED")


def validate_version(version, project_name, project_version):
    need(project_name == "aioa-sparkhat" and project_version == "0.2.0"
         and version == project_version + "~u13.1", "CANDIDATE_VERSION_MISMATCH")


def validate_lock(records):
    need(type(records) is list and 0 < len(records) <= 128, "DEPENDENCY_PIN_REQUIRED")
    names = []
    for item in records:
        need(type(item) is dict and re.fullmatch(r"[a-z0-9][a-z0-9+.-]{0,80}", item.get("name", ""))
             and re.fullmatch(r"[0-9][0-9A-Za-z.+:~_-]{0,99}", item.get("version", ""))
             and item.get("architecture") in ("amd64", "all")
             and item.get("delivery") == "OS_PROVIDED_NOT_BUNDLED", "DEPENDENCY_PIN_REQUIRED")
        names.append(item["name"])
    need(names == sorted(set(names)), "DEPENDENCY_PIN_REQUIRED")


def dependency_notices(records, docroot=Path("/usr/share/doc")):
    validate_lock(records)
    by_name = {r["name"]: r for r in records}
    notices = []
    for item in records:
        owner = NOTICE_OWNERS.get(item["name"], item["name"])
        need(owner in by_name and by_name[owner]["version"] == item["version"], "DEPENDENCY_LICENSE_REQUIRED")
        path = Path(docroot) / owner / "copyright"
        try:
            raw = safe_bytes(path)
            text = raw.decode("utf-8", "strict")
            lower = text.lower()
            need(bool(text.strip()) and len(raw) >= 32 and "copyright" in lower
                 and any(word in lower for word in ("license", "permission", "redistribution", "public domain")),
                 "DEPENDENCY_LICENSE_REQUIRED")
        except (OSError, UnicodeError, ValueError):
            raise ValueError("DEPENDENCY_LICENSE_REQUIRED") from None
        # Distro copyright files often contain several licenses and exceptions.
        # Preserve the evidence; no guessed SPDX expression or legal clearance.
        notices.append({"name": item["name"], "notice_owner": owner, "path": "/usr/share/doc/" + owner + "/copyright",
                        "sha256": sha(raw), "text": text, "status": "REVIEW_REQUIRED",
                        "license_concluded": "NOASSERTION"})
    return notices


def check_scope(scope):
    need(scope == "diagnostic", "RELEASE_NOT_ACCEPTED_SIGNER_AND_CLEAN_HOST_REQUIRED")
    return "PASS_LOCAL_LIMITED"


def archive_path(name):
    need(type(name) is str and len(name) <= 420 and not name.startswith("/"), "ARCHIVE_PATH_DENIED")
    if name in (".", "./"):
        return ""
    relative = name[2:] if name.startswith("./") else name
    relative = relative[:-1] if relative.endswith("/") else relative
    path = PurePosixPath(relative)
    need(bool(relative) and str(path) == relative and ".." not in path.parts
         and not path.is_absolute() and re.fullmatch(r"[A-Za-z0-9_./~+:-]+", relative)
         and all(not p.startswith(".") and p not in PRIVATE_PARTS for p in path.parts),
         "ARCHIVE_PATH_DENIED")
    return relative


def read_tar(compressed):
    try:
        decoder = lzma.LZMADecompressor()
        raw = decoder.decompress(compressed, max_length=MAX_TAR_BYTES + 1)
        need(len(raw) <= MAX_TAR_BYTES and decoder.eof and not decoder.unused_data, "ARCHIVE_SIZE_DENIED")
        # tarfile accepts extensions and ignores bytes after the end marker.
        # Reject both before interpreting entries, including hidden extra data.
        offset, pending_long_name, header_count = 0, None, 0
        need(len(raw) % 512 == 0, "ARCHIVE_INVALID")
        while offset + 512 <= len(raw) and any(raw[offset:offset + 512]):
            header = raw[offset:offset + 512]
            kind = header[156:157]
            header_count += 1
            need(header_count <= MAX_MEMBERS * 2, "ARCHIVE_SIZE_DENIED")
            need(kind in (b"\0", b"0", b"5", b"L"), "ARCHIVE_TYPE_DENIED")
            size_text = header[124:136].strip(b"\0 ")
            need(re.fullmatch(rb"[0-7]{1,12}", size_text), "ARCHIVE_INVALID")
            size = int(size_text, 8)
            need(size <= MAX_FILE_BYTES, "ARCHIVE_SIZE_DENIED")
            if kind == b"L":
                # dpkg-deb uses GNU's long-name record for names >100 bytes.
                # It is metadata, never a payload file or a link target.
                need(pending_long_name is None and header[:100].rstrip(b"\0") == b"././@LongLink"
                     and 101 < size <= 421, "ARCHIVE_TYPE_DENIED")
                data = raw[offset + 512:offset + 512 + size]
                need(len(data) == size and data.endswith(b"\0") and data.count(b"\0") == 1
                     and all(v < 128 for v in data), "ARCHIVE_PATH_DENIED")
                pending_long_name = data[:-1]
                archive_path(pending_long_name.decode("ascii"))
            elif pending_long_name is not None:
                need(header[:100].rstrip(b"\0") == pending_long_name[:100], "ARCHIVE_PATH_DENIED")
                pending_long_name = None
            next_offset = offset + 512 + ((size + 511) // 512) * 512
            need(not any(raw[offset + 512 + size:next_offset]), "ARCHIVE_INVALID")
            offset = next_offset
        need(pending_long_name is None and offset + 1024 <= len(raw) and not any(raw[offset:]), "ARCHIVE_INVALID")
        files, directories, entries = {}, {}, {}
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
            for item in tar:
                need(len(entries) < MAX_MEMBERS, "ARCHIVE_SIZE_DENIED")
                name = archive_path(item.name)
                need(name not in entries, "ARCHIVE_DUPLICATE_PATH")
                need(not item.pax_headers and (item.isreg() or item.isdir()), "ARCHIVE_TYPE_DENIED")
                need(item.uid == item.gid == 0 and item.uname == item.gname == "root"
                     and item.mode in ((0o755,) if item.isdir() else (0o644, 0o755)), "ARCHIVE_MODE_DENIED")
                need(item.size <= MAX_FILE_BYTES and item.size >= 0, "ARCHIVE_SIZE_DENIED")
                entries[name] = {"mtime": item.mtime, "mode": item.mode}
                if item.isdir():
                    need(item.size == 0, "ARCHIVE_TYPE_DENIED")
                    directories[name] = item.mode
                else:
                    need(bool(name), "ARCHIVE_PATH_DENIED")
                    stream = tar.extractfile(item)
                    need(stream is not None, "ARCHIVE_TYPE_DENIED")
                    data = stream.read(MAX_FILE_BYTES + 1)
                    need(len(data) == item.size, "ARCHIVE_SIZE_DENIED")
                    files[name] = (data, item.mode)
        return files, directories, entries
    except (tarfile.TarError, lzma.LZMAError, EOFError):
        raise ValueError("ARCHIVE_INVALID") from None


def read_deb(raw, *, expected_sha256=None):
    need(type(raw) is bytes and 0 < len(raw) <= MAX_DEB_BYTES, "ARTIFACT_SIZE_DENIED")
    if expected_sha256 is not None:
        need(re.fullmatch(r"[0-9a-f]{64}", expected_sha256) and sha(raw) == expected_sha256,
             "ARTIFACT_HASH_MISMATCH")
    need(raw.startswith(b"!<arch>\n"), "ARCHIVE_INVALID")
    offset, members, epochs = 8, {}, []
    while offset < len(raw):
        need(len(members) < 3 and offset + 60 <= len(raw), "ARCHIVE_INVALID")
        header = raw[offset:offset + 60]
        need(header[58:] == b"`\n", "ARCHIVE_INVALID")
        try:
            name = header[:16].decode("ascii").strip().removesuffix("/")
            size = int(header[48:58])
            epoch = int(header[16:28])
            need(int(header[28:34]) == int(header[34:40]) == 0
                 and int(header[40:48], 8) == 0o100644, "ARCHIVE_MODE_DENIED")
        except (UnicodeError, ValueError):
            raise ValueError("ARCHIVE_INVALID") from None
        need(name not in members and size >= 0 and offset + 60 + size <= len(raw), "ARCHIVE_INVALID")
        offset += 60
        members[name] = raw[offset:offset + size]
        epochs.append(epoch)
        offset += size
        if size % 2:
            need(raw[offset:offset + 1] == b"\n", "ARCHIVE_INVALID")
            offset += 1
    need(list(members) == ["debian-binary", "control.tar.xz", "data.tar.xz"]
         and members["debian-binary"] == b"2.0\n", "ARCHIVE_INVALID")
    files, directories, entries = read_tar(members["data.tar.xz"])
    controls, control_dirs, control_entries = read_tar(members["control.tar.xz"])
    need("control" in controls, "CONTROL_MISMATCH")
    return {"files": files, "directories": directories, "entries": entries,
            "control_files": controls, "control_directories": control_dirs,
            "control_entries": control_entries, "control": controls["control"][0], "ar_epochs": epochs}


def verify_contents(contents, expected, control, epoch):
    need(contents["control_files"] == {"control": (control, 0o644)}, "CONTROL_MISMATCH")
    need(set(contents["files"]) == set(expected), "PAYLOAD_PATH_MISMATCH")
    need(contents["files"] == expected, "PAYLOAD_HASH_OR_MODE_MISMATCH")
    directories = {""}
    for name in expected:
        directories.update(str(p) for p in PurePosixPath(name).parents if str(p) != ".")
    need(contents["directories"] == {p: 0o755 for p in directories}
         and contents["control_directories"] == {"": 0o755}, "PAYLOAD_DIRECTORY_MISMATCH")
    need(all(e["mtime"] == epoch for e in (*contents["entries"].values(),
         *contents["control_entries"].values())) and contents["ar_epochs"] == [epoch] * 3,
         "ARCHIVE_EPOCH_MISMATCH")


def spdx_sbom(context, artifact_sha256):
    need(re.fullmatch(r"[0-9a-f]{64}", artifact_sha256), "ARTIFACT_HASH_MISMATCH")
    source, inventory, abi = context["source"], context["source_inventory"], context["abi"]
    validate_abi(abi["python_abi"], abi["architecture"])
    validate_lock(abi["os_dependencies"])
    comment = {"scope": "UNSIGNED_LOCAL_DIAGNOSTIC_ONLY", "source_commit": source["commit"],
               "source_tree": source["tree"], "python_abi": abi["python_abi"],
               "architecture": abi["architecture"], "toolchain": context["toolchain"],
               "release": "NOT_ACCEPTED", "license_review": "OS_PROVIDED_NOT_BUNDLED_REVIEW_REQUIRED"}
    result = {"spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
              "name": "aioa-sparkhat-" + context["version"],
              "documentNamespace": "https://spdx.org/spdxdocs/aioa-sparkhat-" + sha(canonical_json(comment) + artifact_sha256.encode()),
              "creationInfo": {"creators": ["Tool: aioa-deb-provenance-1"],
                  "created": datetime.datetime.fromtimestamp(source["epoch"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
              "comment": canonical_json(comment).decode().strip(), "packages": [], "files": [],
              "relationships": [], "hasExtractedLicensingInfos": []}
    def package(identifier, name, version, license_value="NOASSERTION", **extra):
        return {"SPDXID": identifier, "name": name, "versionInfo": version,
                "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
                "licenseConcluded": license_value, "licenseDeclared": license_value,
                "copyrightText": "NOASSERTION", **extra}
    def relationship(first, kind, second):
        result["relationships"].append({"spdxElementId": first, "relationshipType": kind, "relatedSpdxElement": second})
    result["packages"].append(package("SPDXRef-Artifact", "aioa-sparkhat", context["version"],
        checksums=[{"algorithm": "SHA256", "checksumValue": artifact_sha256}],
        primaryPackagePurpose="APPLICATION", comment="Owned source MIT notices are in SPDXRef-Source; OS notice texts require review. Unsigned; no signer/clean-host certification; no production release."))
    result["packages"].append(package("SPDXRef-Source", "aioa-sparkhat-source", source["commit"], "MIT",
        filesAnalyzed=True, licenseInfoFromFiles=["MIT"],
        packageVerificationCode={"packageVerificationCodeValue": hashlib.sha1("".join(sorted(i["sha1"] for i in inventory)).encode()).hexdigest()},
        comment="Exact Git tree " + source["tree"] + "; positive source allowlist only."))
    relationship("SPDXRef-DOCUMENT", "DESCRIBES", "SPDXRef-Artifact")
    relationship("SPDXRef-Artifact", "GENERATED_FROM", "SPDXRef-Source")
    for index, item in enumerate(inventory):
        need(item["license"] == "MIT" and bool(item["notice"]), "SOURCE_LICENSE_REQUIRED")
        identifier = "SPDXRef-File-" + str(index)
        result["files"].append({"SPDXID": identifier, "fileName": "./" + item["path"],
            "checksums": [{"algorithm": "SHA256", "checksumValue": item["sha256"]},
                          {"algorithm": "SHA1", "checksumValue": item["sha1"]}],
            "licenseConcluded": "MIT", "licenseInfoInFiles": ["MIT"], "copyrightText": "NOASSERTION",
            "comment": "Attribution preserved in " + item["notice"]})
        relationship("SPDXRef-Source", "CONTAINS", identifier)
    notices = {n["name"]: n for n in context["notices"]}
    for name, notice in sorted(notices.items()):
        need(sha(notice["text"].encode()) == notice["sha256"], "DEPENDENCY_LICENSE_REQUIRED")
        license_ref = "LicenseRef-OS-" + name
        result["hasExtractedLicensingInfos"].append({"licenseId": license_ref,
            "extractedText": notice["text"], "name": name + " distro copyright evidence",
            "comment": "REVIEW_REQUIRED; evidence identifier, no inferred license. SHA256 " + notice["sha256"]})
    for item in abi["os_dependencies"]:
        need(item["name"] in notices, "DEPENDENCY_LICENSE_REQUIRED")
        notice = notices[item["name"]]
        identifier = "SPDXRef-OS-" + item["name"]
        license_ref = "LicenseRef-OS-" + item["name"]
        result["packages"].append(package(identifier, item["name"], item["version"],
            externalRefs=[{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                "referenceLocator": "pkg:deb/" + item["name"] + "@" + quote(item["version"], safe="") + "?arch=" + item["architecture"]}],
            primaryPackagePurpose="LIBRARY", comment="OS_PROVIDED_NOT_BUNDLED; REVIEW_REQUIRED; " +
                license_ref + "; " + notice["path"] + "; SHA256 " + notice["sha256"]))
        relationship("SPDXRef-Artifact", "DEPENDS_ON", identifier)
    for index, tool in enumerate(context["toolchain"]):
        need(tool["package"] in notices and tool["license_evidence_sha256"] == notices[tool["package"]]["sha256"],
             "DEPENDENCY_LICENSE_REQUIRED")
        identifier = "SPDXRef-Tool-" + str(index)
        result["packages"].append(package(identifier, tool["name"], tool["version"],
            checksums=[{"algorithm": "SHA256", "checksumValue": tool["sha256"]}],
            primaryPackagePurpose="APPLICATION", comment="BUILD_TOOL_NOT_BUNDLED; " + tool["path"] +
                "; owner " + tool["package"] + "; REVIEW_REQUIRED; LicenseRef-OS-" + tool["package"]))
        relationship(identifier, "BUILD_TOOL_OF", "SPDXRef-Artifact")
    validate_spdx(result)
    return result


def validate_spdx(document):
    """Validate the bounded SPDX 2.3 subset emitted here; no external schema fetch."""
    need(type(document) is dict and document.get("spdxVersion") == "SPDX-2.3"
         and document.get("dataLicense") == "CC0-1.0" and document.get("SPDXID") == "SPDXRef-DOCUMENT"
         and type(document.get("name")) is str and document.get("documentNamespace", "").startswith("https://spdx.org/spdxdocs/")
         and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", document.get("creationInfo", {}).get("created", ""))
         and bool(document.get("creationInfo", {}).get("creators")), "SPDX_REQUIRED")
    ids = {"SPDXRef-DOCUMENT"}
    for kind in ("packages", "files"):
        need(type(document.get(kind)) is list and 0 < len(document[kind]) <= MAX_MEMBERS, "SPDX_REQUIRED")
        for item in document[kind]:
            identifier = item.get("SPDXID", "")
            need(re.fullmatch(r"SPDXRef-[A-Za-z0-9.-]+", identifier) and identifier not in ids
                 and item.get("licenseConcluded") in ("MIT", "NOASSERTION")
                 and "copyrightText" in item, "SPDX_REQUIRED")
            ids.add(identifier)
            if kind == "packages":
                need(bool(item.get("name")) and bool(item.get("versionInfo"))
                     and item.get("downloadLocation") == "NOASSERTION"
                     and type(item.get("filesAnalyzed")) is bool
                     and item.get("licenseDeclared") in ("MIT", "NOASSERTION"), "SPDX_REQUIRED")
            else:
                need(item.get("fileName", "").startswith("./") and item.get("licenseInfoInFiles") == ["MIT"]
                     and bool(item.get("checksums")), "SPDX_REQUIRED")
            for digest in item.get("checksums", []):
                size = {"SHA256": 64, "SHA1": 40}.get(digest.get("algorithm"))
                need(size and re.fullmatch(r"[0-9a-f]{" + str(size) + "}", digest.get("checksumValue", "")), "SPDX_REQUIRED")
    for relation in document.get("relationships", []):
        need(relation.get("spdxElementId") in ids and relation.get("relatedSpdxElement") in ids
             and relation.get("relationshipType") in ("DESCRIBES", "GENERATED_FROM", "CONTAINS", "DEPENDS_ON", "BUILD_TOOL_OF"), "SPDX_REQUIRED")
    for notice in document.get("hasExtractedLicensingInfos", []):
        need(re.fullmatch(r"LicenseRef-[A-Za-z0-9.-]+", notice.get("licenseId", ""))
             and bool(notice.get("extractedText")), "SPDX_REQUIRED")


def provenance(context, artifact_sha256, sbom_sha256, artifact_bytes):
    return {"schema": "aioa.deb-provenance.v1", "version": context["version"],
            "source": context["source"], "python_abi": context["abi"]["python_abi"],
            "architecture": context["abi"]["architecture"], "toolchain": context["toolchain"],
            "dependency_lock_sha256": sha(canonical_json(context["abi"])),
            "source_inventory_sha256": sha(canonical_json(context["source_inventory"])),
            "artifact_name": "aioa-sparkhat_" + context["version"] + "_amd64.deb",
            "artifact_bytes": artifact_bytes, "artifact_sha256": artifact_sha256, "sbom_sha256": sbom_sha256,
            "source_date_epoch": context["source"]["epoch"], "compression": "xz-level6-uniform",
            "scope": "LOCAL_DIAGNOSTICS_ONLY", "unsigned": True, "signer": "ABSENT",
            "clean_host_certification": "ABSENT", "release_gate": "BLOCKED_OR_PENDING",
            "license_review": "REVIEW_REQUIRED_OS_PROVIDED_NOT_BUNDLED"}
