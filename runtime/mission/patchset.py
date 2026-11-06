"""Actual-tree coding proposals, owned by the existing Core and never authority.

Adapted from NonZero W7A patchset/{policy,contracts}.py and workspace/jail.py,
commit 392487849eddc7444f5159994b66b72e73f15934. MIT attribution is shipped in
runtime/nonzero_cloudops/LICENSE-NONZERO.txt. Roots are trusted host locators;
only opaque identities and digests cross the model boundary. Plain exported
trees are required: this module never reads a .git directory or credentials.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import stat
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.contracts import bounded_int, logical_id
from runtime.mission.worker import Task
from runtime.nonzero_cloudops.models.redaction import contains_sensitive_material

MAX_FILES_CHANGED = 3
MAX_CHANGED_LINES = 300
MAX_DELETED_FILES = 1
MAX_DELETED_LINES = 150
MAX_TREE_FILES = 256
MAX_TREE_ENTRIES = 1024
MAX_TREE_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_DIFF_BYTES = 262144
POLICY_VERSION = "aioa-core-bounded-patchset-v1"


class PatchSetPolicyDenied(ValueError):
    """Value-free public failure; no file contents or private host locators."""


def _require(value, code):
    if not value:
        raise PatchSetPolicyDenied(code)


def _digest(value, length=64):
    _require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value),
        "PATCHSET_DIGEST_INVALID",
    )


def normalize_patch_relative_path(value):
    _require(
        type(value) is str and value and value == value.strip(), "PATCHSET_PATH_INVALID"
    )
    _require(
        value == unicodedata.normalize("NFC", value), "PATCHSET_PATH_UNICODE_AMBIGUOUS"
    )
    _require(
        "\\" not in value
        and not any(unicodedata.category(c).startswith("C") for c in value),
        "PATCHSET_PATH_INVALID",
    )
    path = PurePosixPath(value)
    _require(
        not path.is_absolute()
        and path.as_posix() == value
        and path.parts
        and len(path.parts) <= 32
        and len(value) <= 1024
        and all(p not in (".", "..", "") and len(p) <= 128 for p in path.parts),
        "PATCHSET_PATH_TRAVERSAL_DENIED",
    )
    return value


def _secret_path(path):
    parts = tuple(p.casefold() for p in PurePosixPath(path).parts)
    _require(".git" not in parts, "PATCHSET_GIT_PATH_DENIED")
    _require(
        not any(
            p
            in (
                ".aws",
                ".ssh",
                "secrets",
                "credentials",
                "tokens",
                "auth.json",
                "id_rsa",
                "id_ed25519",
                "known_hosts",
            )
            or p.startswith(".env")
            or "credential" in p
            or p.endswith((".key", ".pem", ".p12", ".pfx"))
            for p in parts
        ),
        "PATCHSET_SECRET_PATH_DENIED",
    )


def _protected_change(path):
    parts = tuple(p.casefold() for p in PurePosixPath(path).parts)
    name = parts[-1]
    _secret_path(path)
    _require(
        not any(
            p
            in (
                "tests",
                "test",
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
                "node_modules",
                "dist",
                "build",
            )
            for p in parts
        )
        and not name.startswith("test_")
        and not name.endswith(("_test.py", ".test.js", ".spec.ts")),
        "PATCHSET_TEST_OR_GENERATED_CHANGE_DENIED",
    )
    _require(
        parts[0] not in (".github", ".circleci")
        and name
        not in (
            "pyproject.toml",
            "requirements.txt",
            "uv.lock",
            "package.json",
            "package-lock.json",
            "pytest.ini",
            "tox.ini",
            "ruff.toml",
            ".gitignore",
            ".gitmodules",
            ".gitattributes",
            ".gitconfig",
            ".npmrc",
        ),
        "PATCHSET_POLICY_CONFIGURATION_DENIED",
    )
    _require(
        not path.startswith(
            (
                "runtime/mission/",
                "runtime/service_guard/",
                "runtime/memory_patch/persistence/",
                "docs/provenance/",
            )
        )
        and path
        not in (
            "runtime/core_admission.py",
            "runtime/nonzero_cloudops/models/redaction.py",
        ),
        "PATCHSET_CORE_POLICY_DENIED",
    )


@dataclass(frozen=True, slots=True)
class FileIdentity:
    sha256: str
    size: int
    mode: int

    def __post_init__(self):
        _digest(self.sha256)
        bounded_int(self.size, 0, MAX_FILE_BYTES)
        bounded_int(self.mode, 0, 0o777)


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    operation: str
    before: FileIdentity | None
    after: FileIdentity | None
    lines_added: int
    lines_deleted: int

    def __post_init__(self):
        normalize_patch_relative_path(self.path)
        bounded_int(self.lines_added, 0, MAX_CHANGED_LINES)
        bounded_int(self.lines_deleted, 0, MAX_CHANGED_LINES)
        _require(self.operation in ("ADD", "MODIFY", "DELETE"), "PATCHSET_OPERATION")
        _require(
            (self.before is None or type(self.before) is FileIdentity)
            and (self.after is None or type(self.after) is FileIdentity),
            "PATCHSET_FILE_IDENTITY",
        )
        _require(
            (self.operation == "ADD" and self.before is None and self.after is not None)
            or (
                self.operation == "DELETE"
                and self.before is not None
                and self.after is None
            )
            or (
                self.operation == "MODIFY"
                and self.before is not None
                and self.after is not None
                and self.before != self.after
            ),
            "PATCHSET_OPERATION_SHAPE",
        )


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    repository_id: str
    workspace_id: str
    source_base_sha: str
    base_tree_sha256: str

    def __post_init__(self):
        logical_id(self.repository_id)
        logical_id(self.workspace_id)
        _digest(self.source_base_sha, 40)
        _digest(self.base_tree_sha256)


@dataclass(frozen=True, slots=True)
class PatchSet:
    task_id: str
    run_id: str
    workspace_id: str
    repository_id: str
    task_digest: str
    worker_session_id: str
    source_base_sha: str
    base_tree_sha256: str
    final_tree_sha256: str
    files: tuple[FileChange, ...]
    canonical_diff: str = field(repr=False)
    patchset_sha256: str = field(init=False, default="")

    def __post_init__(self):
        self._validate()
        object.__setattr__(self, "patchset_sha256", canonical_sha256(self.payload()))

    def _validate(self):
        for value in (
            self.task_id,
            self.run_id,
            self.workspace_id,
            self.repository_id,
            self.worker_session_id,
        ):
            logical_id(value)
        for value in (self.task_digest, self.base_tree_sha256, self.final_tree_sha256):
            _digest(value)
        _digest(self.source_base_sha, 40)
        _require(
            type(self.files) is tuple
            and 1 <= len(self.files) <= MAX_FILES_CHANGED
            and all(type(f) is FileChange for f in self.files),
            "PATCHSET_FILE_BOUND",
        )
        paths = [f.path for f in self.files]
        _require(paths == sorted(set(paths)), "PATCHSET_FILE_ORDER")
        _require(
            self.lines_added + self.lines_deleted <= MAX_CHANGED_LINES,
            "PATCHSET_LINE_BOUND",
        )
        _require(
            sum(f.operation == "DELETE" for f in self.files) <= MAX_DELETED_FILES
            and self.lines_deleted <= MAX_DELETED_LINES,
            "PATCHSET_MASS_DELETE_DENIED",
        )
        _require(
            type(self.canonical_diff) is str
            and 0 < len(self.canonical_diff.encode("utf-8")) <= MAX_DIFF_BYTES
            and not contains_sensitive_material(self.canonical_diff),
            "PATCHSET_DIFF_DENIED",
        )

    @property
    def lines_added(self):
        return sum(f.lines_added for f in self.files)

    @property
    def lines_deleted(self):
        return sum(f.lines_deleted for f in self.files)

    @property
    def authority(self):
        return "NONE"

    def payload(self):
        value = asdict(self)
        value.pop("patchset_sha256", None)
        return {**value, "schema": POLICY_VERSION, "authority": "NONE"}

    def verify_digest(self):
        self._validate()
        _require(
            self.patchset_sha256 == canonical_sha256(self.payload()),
            "PATCHSET_HASH_ALTERED",
        )


@dataclass(frozen=True, slots=True)
class _TreeFile:
    identity: FileIdentity
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Tree:
    digest: str
    files: dict[str, _TreeFile] = field(repr=False)


def _stamp(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _regular(info):
    _require(
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and info.st_uid == os.getuid()
        and not info.st_mode & 0o7022,
        "PATCHSET_FILE_TYPE_OR_MODE_DENIED",
    )


def _open_root(root):
    _require(isinstance(root, Path) and root.is_absolute(), "PATCHSET_ROOT_INVALID")
    _require(root.resolve(strict=True) == root, "PATCHSET_ROOT_LINK_DENIED")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for part in root.parts[1:]:
            _require(part not in (".", ".."), "PATCHSET_ROOT_INVALID")
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        _require(
            info.st_uid == os.getuid() and not info.st_mode & 0o7022,
            "PATCHSET_ROOT_OWNER_OR_MODE_DENIED",
        )
        return fd, info
    except BaseException:
        os.close(fd)
        raise


def _read_regular(directory, name, expected, *, maximum=MAX_FILE_BYTES):
    _regular(expected)
    _require(expected.st_size <= maximum, "PATCHSET_FILE_SIZE_BOUND")
    fd = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=directory,
    )
    try:
        before = os.fstat(fd)
        _regular(before)
        _require(_stamp(before) == _stamp(expected), "PATCHSET_FILE_CHANGED")
        chunks, size = [], 0
        while True:
            part = os.read(fd, min(65536, maximum + 1 - size))
            if not part:
                break
            chunks.append(part)
            size += len(part)
            _require(size <= maximum, "PATCHSET_FILE_SIZE_BOUND")
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        _require(
            _stamp(os.fstat(fd)) == _stamp(before) == _stamp(named)
            and size == before.st_size,
            "PATCHSET_FILE_CHANGED",
        )
        return b"".join(chunks)
    finally:
        os.close(fd)


def _tree_digest(records):
    return canonical_sha256(
        [
            [p, f.identity.sha256, f.identity.size, f.identity.mode]
            for p, f in sorted(records.items())
        ]
    )


def _snapshot(root):
    """Descriptor-confined DFS, followed by a fresh independent fwalk census."""
    root_fd = None
    try:
        root_fd, before_root = _open_root(root)
        files, folded, entries = {}, {}, [0]
        total = [0]

        def walk(fd, prefix):
            before = os.fstat(fd)
            names = []
            with os.scandir(fd) as iterator:
                for entry in iterator:
                    entries[0] += 1
                    _require(
                        entries[0] <= MAX_TREE_ENTRIES, "PATCHSET_TREE_ENTRY_BOUND"
                    )
                    names.append(entry.name)
            for name in sorted(names):
                path = normalize_patch_relative_path(prefix + name)
                _secret_path(path)
                prior = folded.setdefault(path.casefold(), path)
                _require(prior == path, "PATCHSET_CASE_AMBIGUITY")
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                _require(
                    info.st_uid == os.getuid() and info.st_dev == before_root.st_dev,
                    "PATCHSET_ENTRY_OWNER_OR_DEVICE",
                )
                if stat.S_ISDIR(info.st_mode):
                    _require(not info.st_mode & 0o7022, "PATCHSET_DIRECTORY_MODE")
                    child = os.open(
                        name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC,
                        dir_fd=fd,
                    )
                    try:
                        _require(
                            _stamp(os.fstat(child)) == _stamp(info),
                            "PATCHSET_DIRECTORY_CHANGED",
                        )
                        walk(child, path + "/")
                        _require(
                            _stamp(os.fstat(child)) == _stamp(info),
                            "PATCHSET_DIRECTORY_CHANGED",
                        )
                    finally:
                        os.close(child)
                else:
                    _regular(info)
                    _require(
                        len(files) < MAX_TREE_FILES
                        and total[0] + info.st_size <= MAX_TREE_BYTES,
                        "PATCHSET_TREE_SIZE_BOUND",
                    )
                    content = _read_regular(
                        fd,
                        name,
                        info,
                        maximum=min(MAX_FILE_BYTES, MAX_TREE_BYTES - total[0]),
                    )
                    total[0] += len(content)
                    files[path] = _TreeFile(
                        FileIdentity(
                            hashlib.sha256(content).hexdigest(),
                            len(content),
                            stat.S_IMODE(info.st_mode),
                        ),
                        content,
                    )
            _require(
                _stamp(os.fstat(fd)) == _stamp(before), "PATCHSET_DIRECTORY_CHANGED"
            )

        walk(root_fd, "")
        _require(
            _stamp(os.fstat(root_fd)) == _stamp(before_root)
            and _stamp(root.lstat()) == _stamp(before_root),
            "PATCHSET_ROOT_CHANGED",
        )
        digest = _tree_digest(files)
        _require(
            independent_tree_digest(root) == digest,
            "PATCHSET_INDEPENDENT_TREE_MISMATCH",
        )
        return _Tree(digest, files)
    except OSError:
        raise PatchSetPolicyDenied("PATCHSET_OBSERVATION_FAILED") from None
    finally:
        if root_fd is not None:
            os.close(root_fd)


def independent_tree_digest(root):
    """Fresh top-down fwalk readback; no first-pass file content is reused."""
    root_fd = None
    try:
        root_fd, root_info = _open_root(root)
        records, folded, entries, size = {}, {}, 0, 0
        for directory, dirs, names, fd in os.fwalk(
            ".", topdown=True, follow_symlinks=False, dir_fd=root_fd
        ):
            prefix = "" if directory == "." else directory[2:] + "/"
            for name in sorted(dirs + names):
                entries += 1
                _require(entries <= MAX_TREE_ENTRIES, "PATCHSET_TREE_ENTRY_BOUND")
                path = normalize_patch_relative_path(prefix + name)
                _secret_path(path)
                _require(
                    folded.setdefault(path.casefold(), path) == path,
                    "PATCHSET_CASE_AMBIGUITY",
                )
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                _require(
                    info.st_uid == os.getuid() and info.st_dev == root_info.st_dev,
                    "PATCHSET_ENTRY_OWNER_OR_DEVICE",
                )
                if name in dirs:
                    _require(
                        stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o7022,
                        "PATCHSET_DIRECTORY_TYPE",
                    )
                    continue
                _regular(info)
                _require(
                    len(records) < MAX_TREE_FILES
                    and size + info.st_size <= MAX_TREE_BYTES,
                    "PATCHSET_TREE_SIZE_BOUND",
                )
                data = _read_regular(
                    fd, name, info, maximum=min(MAX_FILE_BYTES, MAX_TREE_BYTES - size)
                )
                size += len(data)
                records[path] = _TreeFile(
                    FileIdentity(
                        hashlib.sha256(data).hexdigest(),
                        len(data),
                        stat.S_IMODE(info.st_mode),
                    ),
                    b"",
                )
        _require(_stamp(root.lstat()) == _stamp(root_info), "PATCHSET_ROOT_CHANGED")
        return _tree_digest(records)
    except OSError:
        raise PatchSetPolicyDenied("PATCHSET_INDEPENDENT_READ_FAILED") from None
    finally:
        if root_fd is not None:
            os.close(root_fd)


def observe_source(base_root, *, repository_id, workspace_id, source_base_sha):
    """Observe a Core-selected export. The host separately verifies its Git SHA."""
    tree = _snapshot(base_root)
    return SourceIdentity(repository_id, workspace_id, source_base_sha, tree.digest)


def _text(record):
    if record is None:
        return ""
    _require(b"\0" not in record.content, "PATCHSET_BINARY_DENIED")
    try:
        text = record.content.decode("utf-8")
    except UnicodeDecodeError:
        raise PatchSetPolicyDenied("PATCHSET_ENCODING_DENIED") from None
    _require(not contains_sensitive_material(text), "PATCHSET_SECRET_CONTENT_DENIED")
    return text


def _counts(before, after):
    added, deleted = 0, 0
    for tag, start, end, new_start, new_end in difflib.SequenceMatcher(
        a=before.splitlines(), b=after.splitlines(), autojunk=False
    ).get_opcodes():
        if tag in ("replace", "delete"):
            deleted += end - start
        if tag in ("replace", "insert"):
            added += new_end - new_start
    return added, deleted


def _diff(path, before, after, left, right):
    def identity(record):
        return "0" * 64 if record is None else record.identity.sha256

    header = (
        f"diff --aioa a/{path} b/{path}\nindex {identity(before)}..{identity(after)}\n"
        f"eof-newline {int(left.endswith(chr(10)))}->{int(right.endswith(chr(10)))}\n"
    )
    return header + "".join(
        line + "\n"
        for line in difflib.unified_diff(
            left.splitlines(),
            right.splitlines(),
            fromfile="/dev/null" if before is None else "a/" + path,
            tofile="/dev/null" if after is None else "b/" + path,
            lineterm="",
        )
    )


class BoundedPatchSetPolicy:
    """Fixed conservative profile. Models cannot choose limits or protected paths."""

    def evaluate(self, base_root, final_root, *, source, task, worker_session_id):
        _require(
            type(source) is SourceIdentity and type(task) is Task,
            "PATCHSET_CONTEXT_REQUIRED",
        )
        _require(
            isinstance(base_root, Path) and isinstance(final_root, Path),
            "PATCHSET_ROOT_INVALID",
        )
        logical_id(worker_session_id)
        _require(
            source.repository_id == task.repository_id
            and source.workspace_id == task.workspace_id
            and source.source_base_sha == task.source_base_sha,
            "PATCHSET_SOURCE_BINDING",
        )
        _require(
            base_root != final_root
            and not base_root.is_relative_to(final_root)
            and not final_root.is_relative_to(base_root),
            "PATCHSET_DISTINCT_ROOTS_REQUIRED",
        )
        base, final = _snapshot(base_root), _snapshot(final_root)
        _require(base.digest == source.base_tree_sha256, "PATCHSET_STALE_SOURCE")
        folded = {}
        for path in sorted(set(base.files) | set(final.files)):
            _require(
                folded.setdefault(path.casefold(), path) == path,
                "PATCHSET_CASE_AMBIGUITY",
            )
        changed = [
            path
            for path in sorted(set(base.files) | set(final.files))
            if (base.files[path].identity if path in base.files else None)
            != (final.files[path].identity if path in final.files else None)
        ]
        _require(changed, "PATCHSET_EMPTY_DENIED")
        _require(len(changed) <= MAX_FILES_CHANGED, "PATCHSET_FILE_BOUND")
        _require(final.files, "PATCHSET_MASS_DELETE_DENIED")
        files, diff = [], []
        for path in changed:
            _protected_change(path)
            before, after = base.files.get(path), final.files.get(path)
            if before is not None and after is not None:
                _require(
                    before.identity.mode == after.identity.mode,
                    "PATCHSET_MODE_CHANGE_DENIED",
                )
            _require(
                after is None or not after.identity.mode & 0o111,
                "PATCHSET_EXECUTABLE_DENIED",
            )
            left, right = _text(before), _text(after)
            # Conservative initial coding profile: test-framework mutation and
            # suppression belong to a separately reviewed host profile.
            _require(
                not re.search(
                    r"(?i)\b(?:pytest|unittest)\b|__builtins__|__debug__", right
                ),
                "PATCHSET_TEST_WEAKENING_DENIED",
            )
            added, deleted = _counts(left, right)
            operation = (
                "ADD" if before is None else "DELETE" if after is None else "MODIFY"
            )
            files.append(
                FileChange(
                    path,
                    operation,
                    None if before is None else before.identity,
                    None if after is None else after.identity,
                    added,
                    deleted,
                )
            )
            diff.append(_diff(path, before, after, left, right))
        return PatchSet(
            task.task_id,
            task.run_id,
            task.workspace_id,
            task.repository_id,
            task.digest,
            worker_session_id,
            task.source_base_sha,
            base.digest,
            final.digest,
            tuple(files),
            "".join(diff),
        )

    def recheck(
        self, patchset, *, base_root, final_root, source, task, worker_session_id
    ):
        _require(type(patchset) is PatchSet, "PATCHSET_REQUIRED")
        patchset.verify_digest()
        _require(
            patchset.task_digest == task.digest
            and patchset.task_id == task.task_id
            and patchset.run_id == task.run_id
            and patchset.worker_session_id == worker_session_id,
            "PATCHSET_CONTEXT_REPLAY_DENIED",
        )
        current = self.evaluate(
            base_root,
            final_root,
            source=source,
            task=task,
            worker_session_id=worker_session_id,
        )
        _require(current == patchset, "PATCHSET_TOCTOU_DRIFT")
        return current.patchset_sha256
