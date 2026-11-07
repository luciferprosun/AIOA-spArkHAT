"""Pinned repository recipe for the existing Linux sandbox, never host execution.

Materialization runs without importing candidate code. Observation runs are
untrusted data producers: expected answers and test verdicts exist only in Core.
"""

import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
import stat
import sys
import unicodedata
from pathlib import Path, PurePosixPath


def require(condition, code):
    if not condition:
        raise ValueError(code)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def path_parts(value):
    require(
        type(value) is str and value == unicodedata.normalize("NFC", value),
        "REPOSITORY_PATH",
    )
    path = PurePosixPath(value)
    require(
        not path.is_absolute()
        and path.as_posix() == value
        and len(path.parts) <= 32
        and all(part not in ("", ".", "..", ".git") for part in path.parts),
        "REPOSITORY_PATH",
    )
    return path.parts


def parent(root, parts, *, create=False):
    current = os.dup(root)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=current,
            )
            os.close(current)
            current = child
        return current
    except OSError:
        os.close(current)
        raise


def read_regular(directory, name):
    fd = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=directory,
    )
    try:
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and before.st_size <= 1048576,
            "REPOSITORY_FILE_TYPE",
        )
        data = bytearray()
        while len(data) <= before.st_size:
            chunk = os.read(fd, min(65536, before.st_size + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)

        def identity(info):
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

        require(
            len(data) == before.st_size
            and identity(before) == identity(after)
            and (named.st_dev, named.st_ino) == (before.st_dev, before.st_ino),
            "REPOSITORY_FILE_CHANGED",
        )
        return bytes(data), stat.S_IMODE(before.st_mode)
    finally:
        os.close(fd)


def write_new(directory, name, data, mode):
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory,
    )
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            require(written > 0, "REPOSITORY_SHORT_WRITE")
            view = view[written:]
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)


def inspect_tree(root):
    files = []
    folded = set()

    def walk(directory, prefix):
        for name in sorted(os.listdir(directory)):
            path = prefix + name
            path_parts(path)
            metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                try:
                    walk(child, path + "/")
                finally:
                    os.close(child)
            else:
                require(
                    path.casefold() not in folded and len(files) < 256,
                    "REPOSITORY_TREE_BOUND",
                )
                folded.add(path.casefold())
                data, mode = read_regular(directory, name)
                require(
                    mode in (0o600, 0o644) and b"\0" not in data, "REPOSITORY_FILE_MODE"
                )
                files.append({"path": path, "mode": mode, "text": data.decode("utf-8")})

    walk(root, "")
    require(
        sum(len(f["text"].encode()) for f in files) <= 1048576, "REPOSITORY_TREE_BOUND"
    )
    return {
        "schema": "aioa.validation-workspace.v1",
        "files": sorted(files, key=lambda f: f["path"]),
    }


def tree_digest(archive):
    return digest(
        canonical(
            [
                [
                    f["path"],
                    digest(f["text"].encode()),
                    len(f["text"].encode()),
                    f["mode"],
                ]
                for f in archive["files"]
            ]
        )
    )


def materialize():
    seed = json.loads(Path("/inputs/base.json").read_bytes())
    changes = json.loads(Path("/inputs/changes.json").read_bytes())
    receipt = json.loads(Path("/inputs/materialization.json").read_bytes())
    require(type(changes) is list and 1 <= len(changes) <= 3, "REPOSITORY_CHANGE_BOUND")
    root = Path("/work/project")
    root.mkdir(mode=0o700)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for item in seed["files"]:
            parts = path_parts(item["path"])
            fd = parent(directory, parts, create=True)
            try:
                require(item["mode"] in (0o600, 0o644), "REPOSITORY_FILE_MODE")
                write_new(fd, parts[-1], item["text"].encode(), item["mode"])
            finally:
                os.close(fd)
        before = inspect_tree(directory)
        require(
            tree_digest(before) == receipt["base_tree_sha256"], "REPOSITORY_BASE_DRIFT"
        )
        for index, change in enumerate(changes):
            parts = path_parts(change["path"])
            fd = parent(directory, parts, create=change["operation"] == "ADD")
            try:
                if change["operation"] != "ADD":
                    current, mode = read_regular(fd, parts[-1])
                    require(
                        digest(current) == change["before_sha256"],
                        "REPOSITORY_PREIMAGE",
                    )
                else:
                    require(change["before_sha256"] is None, "REPOSITORY_PREIMAGE")
                    mode = 0o644
                if change["operation"] == "DELETE":
                    require(change["text"] is None, "REPOSITORY_DELETE")
                    os.unlink(parts[-1], dir_fd=fd)
                else:
                    data = change["text"].encode()
                    require(
                        digest(data) == change["after_sha256"], "REPOSITORY_POSTIMAGE"
                    )
                    if change["operation"] == "ADD":
                        write_new(fd, parts[-1], data, mode)
                    else:
                        require(change["operation"] == "MODIFY", "REPOSITORY_OPERATION")
                        name = ".aioa-approved-" + str(index)
                        write_new(fd, name, data, mode)
                        last, _ = read_regular(fd, parts[-1])
                        require(last == current, "REPOSITORY_PREIMAGE_CHANGED")
                        os.rename(name, parts[-1], src_dir_fd=fd, dst_dir_fd=fd)
                        os.fsync(fd)
            finally:
                os.close(fd)
        after = inspect_tree(directory)
        require(
            tree_digest(after) == receipt["final_tree_sha256"], "REPOSITORY_POSTIMAGE"
        )
        Path("/artifacts/workspace.json").write_bytes(canonical(after))
        Path("/artifacts/materialization.json").write_bytes(canonical(receipt))
    finally:
        os.close(directory)


class ArchiveLoader(importlib.abc.SourceLoader):
    def __init__(self, path, data):
        self.path, self.data = path, data

    def get_filename(self, fullname):
        return "/repo/" + self.path

    def get_data(self, path):
        if path != "/repo/" + self.path:
            raise OSError("NO_BYTECODE_OR_HOST_FILE")
        return self.data.encode()


class ArchiveFinder(importlib.abc.MetaPathFinder):
    def __init__(self, files, roots):
        self.files, self.roots = files, roots

    def find_spec(self, fullname, path=None, target=None):
        relative = fullname.replace(".", "/")
        for root in self.roots:
            prefix = root + "/" if root else ""
            for name, package in (
                (prefix + relative + "/__init__.py", True),
                (prefix + relative + ".py", False),
            ):
                if name in self.files:
                    loader = ArchiveLoader(name, self.files[name])
                    return importlib.util.spec_from_loader(
                        fullname, loader, is_package=package
                    )
        return None


class CandidateCallError(RuntimeError):
    """Only a type name, not candidate exception details, crosses this port."""


def invoke(call):
    try:
        module = importlib.import_module(call["module"])
        value = getattr(module, call["function"])(*call["arguments"])
        json.dumps(value, allow_nan=False)
        return value
    except Exception as error:
        raise CandidateCallError(type(error).__name__) from error


def observe():
    archive = json.loads(Path("/inputs/workspace.json").read_bytes())
    context = json.loads(Path("/inputs/context.json").read_bytes())
    calls = json.loads(Path("/inputs/calls.json").read_bytes())
    roots = json.loads(Path("/inputs/imports.json").read_bytes())
    files = {item["path"]: item["text"] for item in archive["files"]}
    sys.meta_path.insert(0, ArchiveFinder(files, roots))
    results = []
    for call in calls:
        try:
            value = invoke(call)
        except CandidateCallError as error:
            results.append(
                {"case_id": call["case_id"], "kind": "raised", "type": str(error)}
            )
        else:
            results.append(
                {"case_id": call["case_id"], "kind": "returned", "value": value}
            )
    report = {
        "schema": "aioa.python-observation.v1",
        "profile_digest": context["profile_digest"],
        "patchset_sha256": context["patchset_sha256"],
        "stage": context["stage"],
        "results": results,
    }
    print(canonical(report).decode(), flush=True)
    Path("/artifacts/calls-complete.txt").write_bytes(b"PYTHON_CALLS_FINISHED\n")


if __name__ == "__main__":
    mode = json.loads(Path("/inputs/mode.json").read_bytes())
    if mode == {"mode": "materialize"}:
        materialize()
    elif mode == {"mode": "observe"}:
        observe()
    else:
        raise ValueError("REPOSITORY_MODE")
