"""Explicit trusted Linux sandbox broker. Imports and default routes never execute tools.

Only Core's live START branch supplies the release callback. Typed requests and
on-disk receipts are bindings/evidence, never replayable execution authority.
"""

import array
import errno
import hashlib
import json
import os
import select
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.mission.sandbox_contracts import (
    RESOURCE_CEILINGS,
    SandboxDispatchRequest,
    SandboxOperation,
    SandboxRecipe,
    SandboxRegistry,
)
from runtime.mission.warrant import require


def now():
    return datetime.now(UTC).isoformat()


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_evidence_file(directory, name, maximum=1048576):
    """Pinned directory/file descriptors; evidence links never become truth."""
    directory = Path(directory)
    require(not directory.is_symlink(), "READBACK_DIRECTORY_DENIED")
    dfd = os.open(
        directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    fd = None
    try:
        fd = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dfd
        )
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and before.st_uid == os.getuid()
            and 0 < before.st_size <= maximum,
            "READBACK_FILE_TYPE_DENIED",
        )
        chunks = []
        size = 0
        while size <= maximum:
            part = os.read(fd, min(65536, maximum + 1 - size))
            if not part:
                break
            chunks.append(part)
            size += len(part)
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        identity = lambda info: (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
            info.st_nlink,
        )
        require(
            identity(before) == identity(after) == identity(named)
            and size == before.st_size,
            "READBACK_FILE_CHANGED",
        )
        return b"".join(chunks)
    finally:
        if fd is not None:
            os.close(fd)
        os.close(dfd)


def exact_cgroup(unit):
    return f"0::/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/app.slice/{unit}/work"


def mountid(fd):
    for line in Path("/proc/self/fdinfo/" + str(fd)).read_text().splitlines():
        if line.startswith("mnt_id:"):
            return int(line.split(":")[1])
    raise ValueError("MISSING_MOUNT_ID")


def populated(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    values = dict(line.split() for line in os.read(fd, 4096).decode().splitlines())
    require(values.get("populated") in ("0", "1"), "INVALID_CGROUP_EVENTS")
    return values["populated"]


def command_result(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=4, check=False)
        return {
            "argv": argv,
            "exit_code": r.returncode,
            "stdout": r.stdout[:2048],
            "stderr": r.stderr[:1024],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "argv": argv,
            "error": type(exc).__name__,
            "errno": getattr(exc, "errno", None),
        }


def bounded_line(stream, seconds=8, *, cancel=None):
    data = bytearray()
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and len(data) < 65536:
        require(cancel is None or not cancel.cancelled, "SANDBOX_CANCELLED")
        ready, _, _ = select.select(
            [stream.fileno()], [], [], min(0.05, max(0, deadline - time.monotonic()))
        )
        if not ready:
            continue
        byte = os.read(stream.fileno(), 1)
        if not byte:
            break
        data.extend(byte)
        if byte == b"\n":
            value = json.loads(data)
            require(
                value.get("stage") != "CHILD_FAILED",
                "TRUSTED_SUPERVISOR_FAILED:" + str(value)[:1024],
            )
            return value
    raise ValueError("BOUNDED_PROTOCOL_LINE_MISSING")


def build_filter(*, final):
    # Linux x86_64 only. Each filter rejects other ABIs and x32 first.
    rows = [
        (0x20, 0, 0, 4),
        (0x15, 1, 0, 0xC000003E),
        (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0),
        (0x35, 0, 1, 0x40000000),
        (0x06, 0, 0, 0x80000000),
    ]
    deny = {
        101,
        133,
        259,
        320,
        428,
        429,
        430,
        431,
        432,
        433,
        165,
        166,
        167,
        168,
        169,
        170,
        171,
        172,
        173,
        174,
        175,
        176,
        178,
        179,
        180,
        181,
        182,
        183,
        184,
        185,
        246,
        248,
        249,
        250,
        272,
        298,
        300,
        303,
        304,
        308,
        310,
        311,
        313,
        317,
        321,
        323,
        425,
        426,
        427,
        438,
        442,
    }
    if final:
        deny.update(
            {41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 288, 299, 307}
        )
    for number in sorted(deny):
        rows.extend([(0x15, 0, 1, number), (0x06, 0, 0, 0x00050001)])
    rows.extend([(0x15, 0, 1, 435), (0x06, 0, 0, 0x00050026)])  # clone3 ENOSYS
    # Legacy clone: forbid high bits and all CLONE_NEW flags, including NEWTIME.
    rows.extend(
        [
            (0x15, 0, 8, 56),
            (0x20, 0, 0, 20),
            (0x15, 1, 0, 0),
            (0x06, 0, 0, 0x00050001),
            (0x20, 0, 0, 16),
            (0x54, 0, 0, 0x7E020080),
            (0x15, 1, 0, 0),
            (0x06, 0, 0, 0x00050001),
            (0x06, 0, 0, 0x7FFF0000),
            (0x06, 0, 0, 0x7FFF0000),
        ]
    )
    return b"".join(struct.pack("<HBBI", *row) for row in rows)


@dataclass(frozen=True, slots=True)
class TrustedSandboxConfig:
    root: Path
    profile_bytes: bytes
    profile_digest: str
    registry: SandboxRegistry
    inputs_bytes: bytes
    runtime_bytes: bytes

    def profile(self):
        return json.loads(self.profile_bytes)

    def inputs(self):
        return json.loads(self.inputs_bytes)

    def runtime(self):
        return json.loads(self.runtime_bytes)


def _host_json(value):
    """Private host locators, never public authority/contract data."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def save_host_config(config):
    """Private host preparation descriptor, never an approval or replay permit."""
    require(
        type(config) is TrustedSandboxConfig, "TRUSTED_SANDBOX_CONFIGURATION_REQUIRED"
    )
    value = {
        "schema": "aioa.linux-sandbox-host-cache.v1",
        "profile": config.profile(),
        "profile_digest": config.profile_digest,
        "workspace": config.registry.workspace,
        "recipes": [asdict(recipe) for recipe in config.registry.recipes],
        "inputs": config.inputs(),
        "runtime": config.runtime(),
    }
    fd = os.open(
        config.root / "host-config.json",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            # Private host locators include home paths. They are never public
            # authority/contract data; keep that serializer's path guard intact.
            stream.write(_host_json(value))
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    sync_directory(config.root)


def load_host_config(root, *, trusted_root):
    root = Path(root).absolute()
    trusted = Path(trusted_root).absolute()

    def private(path, *, directory=False):
        path = Path(path).absolute()
        require(
            path.is_relative_to(trusted) and path.resolve() == path,
            "SANDBOX_CACHE_PATH_DENIED",
        )
        info = path.lstat()
        require(
            info.st_uid == os.getuid()
            and (
                stat.S_ISDIR(info.st_mode)
                if directory
                else stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            )
            and not info.st_mode & 0o077,
            "SANDBOX_PRIVATE_CACHE_REQUIRED",
        )
        return info

    private(trusted, directory=True)
    private(root, directory=True)
    path = root / "host-config.json"
    info = private(path)
    require(info.st_size <= 4194304, "SANDBOX_CACHE_BOUNDS")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(4194305)
    finally:
        os.close(fd)
    value = json.loads(raw)
    require(
        set(value)
        == {
            "schema",
            "profile",
            "profile_digest",
            "workspace",
            "recipes",
            "inputs",
            "runtime",
        }
        and value["schema"] == "aioa.linux-sandbox-host-cache.v1"
        and value["profile_digest"] == canonical_sha256(value["profile"]),
        "SANDBOX_CACHE_INTEGRITY",
    )
    require(
        value["profile"]["backend_sha256"] == sha(__file__)
        and value["profile"]["worker_sha256"]
        == sha(Path(__file__).with_name("sandbox_worker.py")),
        "SANDBOX_CACHE_SOURCE_CHANGED",
    )
    for name in ("worker_gate", "bootstrap", "setup_filter.bpf", "final_filter.bpf"):
        private(root / name)
    for entry in value["runtime"].values():
        private(entry["snapshot"])
    for entry in value["inputs"].values():
        for path in entry["files"].values():
            require(
                Path(path).absolute().is_relative_to(root), "SANDBOX_CACHE_INPUT_DENIED"
            )
            private(path)
    recipes = tuple(
        SandboxRecipe(**{**r, "argv": tuple(r["argv"])}) for r in value["recipes"]
    )
    return TrustedSandboxConfig(
        root,
        canonical_json_bytes(value["profile"]),
        value["profile_digest"],
        SandboxRegistry(value["workspace"], recipes),
        _host_json(value["inputs"]),
        _host_json(value["runtime"]),
    )


def prepare_linux_sandbox(root, runtime_manifest, *, workspace, recipes):
    """Explicit operator preparation: compile packaged trusted C, pin runtime/inputs.

    recipes is a trusted mapping id -> {files:{name:bytes},expected:{artifact:bytes}}.
    Nothing in a proposal can supply this configuration or add a recipe.
    """
    require(
        isinstance(root, Path)
        and type(runtime_manifest) is dict
        and type(recipes) is dict
        and 0 < len(recipes) <= 32
        and sys.platform == "linux"
        and os.uname().machine == "x86_64"
        and not sys.flags.optimize,
        "TRUSTED_SANDBOX_CONFIGURATION_REQUIRED",
    )
    root = root.absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    native = Path(__file__).parent / "native"
    pins = {}
    runtime = {}
    for name in ("worker_gate", "bootstrap"):
        source = native / (name + ".c")
        destination = root / name
        result = subprocess.run(
            [
                "/usr/bin/cc",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fstack-protector-strong",
                "-D_FORTIFY_SOURCE=2",
                "-Wl,-z,relro,-z,now",
                str(source),
                "-o",
                str(destination),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        require(result.returncode == 0, "TRUSTED_SANDBOX_COMPILATION_FAILED")
        destination.chmod(0o500)
        pins[name] = {"source_sha256": sha(source), "binary_sha256": sha(destination)}
    for name, final in [("setup_filter", False), ("final_filter", True)]:
        path = root / (name + ".bpf")
        path.write_bytes(build_filter(final=final))
        path.chmod(0o400)
        pins[name] = sha(path)
    for target, entry in runtime_manifest.items():
        require(
            type(target) is str
            and (
                target == "/usr/lib/python312.zip"
                or target.startswith(
                    ("/usr/lib/python3.12/", "/usr/bin/python3.12", "/lib/", "/lib64/")
                )
            )
            and ".." not in target.split("/"),
            "UNAPPROVED_RUNTIME_PATH",
        )
        path = Path(entry["snapshot"])
        metadata = path.lstat()
        require(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_size == entry["bytes"]
            and sha(path) == entry["sha256"],
            "PINNED_RUNTIME_CHANGED",
        )
        runtime[target] = {**entry, "mode": stat.S_IMODE(metadata.st_mode)}
    require("/usr/bin/python3.12" in runtime, "PINNED_RUNTIME_REQUIRED")
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "HOME": "/nonexistent",
        "TMPDIR": "/tmp",
    }
    profile = {
        "schema": "aioa.linux-sandbox-profile.v1",
        "platform": "linux-x86_64",
        "runtime": {
            key: {
                "sha256": entry["sha256"],
                "bytes": entry["bytes"],
                "mode": entry["mode"],
            }
            for key, entry in runtime.items()
        },
        "native": pins,
        "bwrap_sha256": sha("/usr/bin/bwrap"),
        "worker_sha256": sha(Path(__file__).with_name("sandbox_worker.py")),
        "backend_sha256": sha(__file__),
        "resources": dict(RESOURCE_CEILINGS),
        "env": env,
        "network": "OFF",
        "namespaces": 7,
        "retained_python_extensions": "manifest exact; includes host test and Tk extension closure",
    }
    digest = canonical_sha256(profile)
    env_digest = canonical_sha256(env)
    inputs = {}
    approved = []
    for identity, spec in recipes.items():
        require(
            type(spec) is dict
            and set(spec) == {"files", "expected"}
            and type(spec["files"]) is dict
            and "recipe.py" in spec["files"]
            and 0 < len(spec["files"]) <= 16
            and type(spec["expected"]) is dict
            and 0 < len(spec["expected"]) <= 8,
            "INVALID_TRUSTED_RECIPE",
        )
        directory = root / ("input-" + str(len(inputs)))
        directory.mkdir(mode=0o700)
        files = {}
        manifest = {}
        for name, data in spec["files"].items():
            require(
                type(name) is str
                and name.isascii()
                and "/" not in name
                and name not in (".", "..")
                and type(data) is bytes
                and len(data) <= 1048576,
                "INVALID_TRUSTED_INPUT",
            )
            destination = directory / name
            destination.write_bytes(data)
            destination.chmod(0o400)
            files[name] = str(destination)
            manifest[name] = hashlib.sha256(data).hexdigest()
        expected = {}
        for name, data in spec["expected"].items():
            require(
                type(name) is str
                and name.isascii()
                and "/" not in name
                and name not in (".", "..")
                and type(data) is bytes
                and len(data) <= 1048576,
                "INVALID_EXPECTED_ARTIFACT",
            )
            expected[name] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        input_digest = canonical_sha256({"files": manifest, "expected": expected})
        inputs[identity] = {
            "files": files,
            "manifest": manifest,
            "expected": expected,
            "digest": input_digest,
        }
        approved.append(
            SandboxRecipe(
                identity,
                "trusted-input-" + input_digest[:24],
                digest,
                input_digest,
                env_digest,
            )
        )
    return TrustedSandboxConfig(
        root,
        canonical_json_bytes(profile),
        digest,
        SandboxRegistry(workspace, tuple(approved)),
        json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode(),
        json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode(),
    )


# Fixed system-runtime closure for the offline bare-Git profile. A host update
# requires explicit requalification, never a PATH/helper/protocol fallback.
GIT_RUNTIME_PINS = {
    "/usr/bin/bwrap": "e318903862396f96de3df57264e0158682b952fd3fb53ac23d876413e7b30f71",
    "/usr/bin/prlimit": "17064f67e650d6152a6902b013aab496b54c87587c8eea6f5023aafee6154069",
    "/lib/x86_64-linux-gnu/libpcre2-8.so.0": "e00576d71d81d3ba0cfa4903c835a44a8723aac96f72f79ff75200b4cff9071b",
    "/lib/x86_64-linux-gnu/libz.so.1": "f61677c7bdb7c2aa2a243ea781bfd16afcb361cede7b4ef76127a9d8eb9a5242",
    "/lib/x86_64-linux-gnu/libc.so.6": "3a15d66867d83762c7f2f1e37359cb8f6c5743edb369c65285cb0b1c4f7498bf",
    "/lib64/ld-linux-x86-64.so.2": "c20a2dc8917c755f02b94049356320fe1f62ac7d9f8994731f807d9df39302da",
}
GIT_CRITICAL_DIRECTORIES = (
    "objects",
    "objects/info",
    "objects/pack",
    "refs",
    "refs/heads",
    "refs/tags",
)


def git_storage_identity(root):
    """Complete no-follow topology check on an already pinned bare directory.

    Identity contains only stable storage directories, not mutable object bytes.
    This preflight is paired with kernel confinement at use; it is not a lock.
    """
    origin = os.fstat(root)
    require(
        stat.S_ISDIR(origin.st_mode)
        and origin.st_uid == os.getuid()
        and not origin.st_mode & 0o7077,
        "GIT_REPOSITORY_OWNER_DENIED",
    )
    origin_mount = mountid(root)
    identities = {}
    count = 0
    total = 0

    def walk(directory, prefix, depth):
        nonlocal count, total
        require(depth <= 16, "GIT_STORAGE_BOUNDS")
        before = os.fstat(directory)
        # scandir is consumed incrementally; no unbounded directory list.
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                require(count <= 4096, "GIT_STORAGE_BOUNDS")
                name = prefix + entry.name
                require(
                    name
                    not in (
                        "objects/info/alternates",
                        "objects/info/http-alternates",
                        "commondir",
                        "gitdir",
                    )
                    and not name.startswith("worktrees/"),
                    "GIT_STORAGE_REDIRECTION",
                )
                fd = os.open(
                    entry.name,
                    os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory,
                )
                try:
                    info = os.fstat(fd)
                    # Git may retain group bits from the operator's umask.
                    # The mandatory private 0700 root excludes group traversal.
                    require(
                        info.st_uid == os.getuid()
                        and info.st_dev == origin.st_dev
                        and mountid(fd) == origin_mount
                        and not info.st_mode & 0o7002,
                        "GIT_STORAGE_OWNER_OR_MOUNT",
                    )
                    if stat.S_ISDIR(info.st_mode):
                        if name in GIT_CRITICAL_DIRECTORIES:
                            identities[name] = (info.st_dev, info.st_ino, origin_mount)
                        walk(fd, name + "/", depth + 1)
                    else:
                        require(
                            stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                            "GIT_STORAGE_FILE_TYPE",
                        )
                        total += info.st_size
                        require(
                            info.st_size <= 8388608 and total <= 67108864,
                            "GIT_STORAGE_BOUNDS",
                        )
                        if name.startswith("refs/"):
                            require(
                                info.st_size <= 41
                                and not os.pread(fd, 41, 0).startswith(b"ref:"),
                                "GIT_STORAGE_SYMBOLIC_REF",
                            )
                    named = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
                    require(
                        (
                            info.st_dev,
                            info.st_ino,
                            info.st_mode,
                            info.st_nlink,
                            info.st_size,
                            info.st_mtime_ns,
                            info.st_ctime_ns,
                        )
                        == (
                            named.st_dev,
                            named.st_ino,
                            named.st_mode,
                            named.st_nlink,
                            named.st_size,
                            named.st_mtime_ns,
                            named.st_ctime_ns,
                        ),
                        "GIT_STORAGE_CHANGED",
                    )
                finally:
                    os.close(fd)
        after = os.fstat(directory)
        require(
            (before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_mtime_ns, after.st_ctime_ns),
            "GIT_STORAGE_CHANGED",
        )

    try:
        walk(root, "", 0)
    except OSError as error:
        raise ValueError("GIT_STORAGE_LINK_OR_CHANGE") from error
    require(set(identities) == set(GIT_CRITICAL_DIRECTORIES), "GIT_STORAGE_REQUIRED")
    return tuple((name, identities[name]) for name in GIT_CRITICAL_DIRECTORIES)


class LinuxSandboxBroker:
    def __init__(self, config=None):
        require(
            type(config) is TrustedSandboxConfig and not sys.flags.optimize,
            "TRUSTED_SANDBOX_CONFIGURATION_REQUIRED",
        )
        require(
            config.profile_digest == canonical_sha256(config.profile()),
            "PINNED_PROFILE_CHANGED",
        )
        self.config = config

    def __call__(self, request):
        raise ValueError("LIVE_CORE_GATE_REQUIRED")

    @staticmethod
    def _git_directory(anchor, parts, *, create, cancel):
        """No-follow directories beneath a descriptor-bound storage anchor."""
        from contextlib import ExitStack

        require(len(parts) <= 16, "GIT_STORAGE_BOUNDS")
        origin = os.fstat(anchor)
        origin_mount = mountid(anchor)
        with ExitStack() as stack:
            current = anchor
            for part in parts:
                require(
                    cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED"
                )
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=current)
                        os.fsync(current)
                    except FileExistsError:
                        pass
                fd = os.open(
                    part,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | os.O_NOATIME
                    | os.O_CLOEXEC,
                    dir_fd=current,
                )
                stack.callback(os.close, fd)
                info = os.fstat(fd)
                require(
                    info.st_uid == os.getuid()
                    and info.st_dev == origin.st_dev
                    and mountid(fd) == origin_mount
                    and not info.st_mode & 0o7002,
                    "GIT_STORAGE_OWNER_OR_MOUNT",
                )
                current = fd
            return os.dup(current)

    @staticmethod
    def _git_publish_new(parent, name, data, *, cancel):
        """Atomic create-only publication of a fully written unnamed inode.

        No truncation, chmod, utime, append or write to an existing pathname.
        O_TMPFILE keeps incomplete bytes unnameable. linkat's exclusive create
        is the zero-old-value CAS; unsupported filesystems fail closed.
        """
        require(
            type(data) is bytes and len(data) <= 2097152, "GIT_PLUMBING_INPUT_BOUND"
        )
        fd = os.open(".", os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC, 0o400, dir_fd=parent)
        try:
            offset = 0
            while offset < len(data):
                require(
                    cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED"
                )
                written = os.write(fd, data[offset:])
                require(written > 0, "GIT_OBJECT_WRITE_FAILED")
                offset += written
            os.fsync(fd)
            require(os.fstat(fd).st_nlink == 0, "GIT_UNNAMED_FILE_REQUIRED")
            require(cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED")
            try:
                os.link(
                    "/proc/self/fd/" + str(fd),
                    name,
                    dst_dir_fd=parent,
                    follow_symlinks=True,
                )
            except FileExistsError:
                return False
            os.fsync(parent)
            return True
        finally:
            os.close(fd)

    @staticmethod
    def _git_existing_object(parent, name, expected):
        import zlib

        fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOATIME | os.O_CLOEXEC,
            dir_fd=parent,
        )
        try:
            info = os.fstat(fd)
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and info.st_nlink == 1
                and 0 < info.st_size <= 2097152,
                "GIT_STORAGE_FILE_TYPE",
            )
            compressed = os.pread(fd, info.st_size + 1, 0)
            decoder = zlib.decompressobj()
            observed = decoder.decompress(compressed, len(expected) + 1)
            require(
                observed == expected
                and decoder.eof
                and not decoder.unconsumed_tail
                and not decoder.unused_data,
                "GIT_EXISTING_OBJECT_MISMATCH",
            )
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            after = os.fstat(fd)
            identity = lambda row: (
                row.st_dev,
                row.st_ino,
                row.st_size,
                row.st_mtime_ns,
                row.st_ctime_ns,
                row.st_nlink,
            )
            require(
                identity(info) == identity(after) == identity(named),
                "GIT_STORAGE_CHANGED",
            )
        finally:
            os.close(fd)

    @classmethod
    def _git_plumbing(
        cls,
        root,
        arguments,
        *,
        git_sha256,
        data=None,
        cancel=None,
        expected_storage=None,
        binding_check=None,
    ):
        """Fixed offline profile on THIS broker and the route's single START.

        Git sees a synthetic, entirely read-only repository view. Native object
        and ref publication uses descriptor-bound create-only syscalls: Git's
        existing-object freshening/reflog/config-setup paths never get host RW.
        No credentials, shell, network, generic argv or second authority store.
        """
        import configparser
        import fcntl
        import re
        import selectors
        import time
        import zlib
        from contextlib import ExitStack

        require(
            sys.platform == "linux" and os.uname().machine == "x86_64",
            "GIT_PLATFORM_DENIED",
        )
        require(
            type(arguments) is tuple and all(type(v) is str for v in arguments),
            "GIT_PLUMBING_COMMAND_DENIED",
        )
        oid = lambda value: re.fullmatch("[a-f0-9]{40}", value) is not None
        ref = lambda value: (
            re.fullmatch(r"refs/heads/[A-Za-z0-9][A-Za-z0-9/_-]{0,127}", value)
            is not None
            and "//" not in value
            and not value.endswith("/")
        )
        publish = None
        git_arguments = arguments
        if (
            arguments == ("rev-parse", "--is-bare-repository")
            or len(arguments) == 3
            and arguments[:2] == ("rev-parse", "--verify")
            and ref(arguments[2])
            or len(arguments) == 3
            and arguments[0] == "cat-file"
            and arguments[1] in ("commit", "blob", "-s")
            and oid(arguments[2])
            or len(arguments) == 5
            and arguments[:4] == ("ls-tree", "-r", "-t", "-z")
            and oid(arguments[4])
        ):
            pass
        elif (
            len(arguments) == 5
            and arguments[:3] == ("hash-object", "-w", "-t")
            and arguments[3] in ("blob", "tree", "commit")
            and arguments[4] == "--stdin"
        ):
            require(
                type(data) is bytes and len(data) <= 1048576, "GIT_PLUMBING_INPUT_BOUND"
            )
            git_arguments = ("hash-object", "-t", arguments[3], "--stdin")
            publish = "object"
        elif len(arguments) in (4, 5) and arguments[0] == "update-ref":
            tail = arguments[2:] if arguments[1] == "--no-deref" else arguments[1:]
            require(
                len(tail) == 3
                and ref(tail[0])
                and oid(tail[1])
                and tail[2] == "0" * 40,
                "GIT_PLUMBING_COMMAND_DENIED",
            )
            git_arguments = ("cat-file", "commit", tail[1])
            publish = ("ref", *tail)
        else:
            raise ValueError("GIT_PLUMBING_COMMAND_DENIED")
        require(
            data is None or arguments[0] == "hash-object", "GIT_PLUMBING_INPUT_BOUND"
        )
        require(cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED")
        topology = git_storage_identity(root)
        require(
            expected_storage is None or topology == expected_storage, "GIT_TARGET_MOVED"
        )
        storage = dict(topology)
        with ExitStack() as stack:
            held = []

            def hold(fd):
                held.append(fd)
                stack.callback(os.close, fd)
                return fd

            def sealed(name, raw):
                fd = hold(os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING))
                view = memoryview(raw)
                while view:
                    count = os.write(fd, view)
                    require(count > 0, "GIT_RUNTIME_COPY_FAILED")
                    view = view[count:]
                os.lseek(fd, 0, os.SEEK_SET)
                # Linux x86_64 UAPI (linux/fcntl.h): some supported Python
                # builds omit these names although the kernel supports them.
                # Numeric ABI use is not an unsealed fallback: verify all four
                # mandatory seals in the kernel before any descriptor is used.
                seals = 0x000F  # SEAL_SEAL | SEAL_SHRINK | SEAL_GROW | SEAL_WRITE
                fcntl.fcntl(fd, 1033, seals)  # F_ADD_SEALS
                require(
                    fcntl.fcntl(fd, 1034) & seals == seals, "GIT_RUNTIME_UNSEALED"
                )  # F_GET_SEALS
                return fd

            # Descriptor copies are immutable after their exact hash is checked;
            # unlike an inode owner number, this also survives outer userns UID
            # remapping in installed-artifact/source-hidden qualification.
            descriptors = {}
            for path, expected in {
                "/usr/bin/git": git_sha256,
                **GIT_RUNTIME_PINS,
            }.items():
                fd = os.open(
                    Path(path).resolve(strict=True),
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                )
                try:
                    info = os.fstat(fd)
                    require(
                        stat.S_ISREG(info.st_mode)
                        and not info.st_mode & 0o7022
                        and info.st_size <= 8388608,
                        "GIT_RUNTIME_TYPE",
                    )
                    raw = os.pread(fd, info.st_size + 1, 0)
                finally:
                    os.close(fd)
                require(
                    len(raw) == info.st_size
                    and hashlib.sha256(raw).hexdigest() == expected,
                    "GIT_RUNTIME_CHANGED",
                )
                descriptors[path] = sealed("aioa-fixed-git-runtime", raw)

            anchors = {}
            for name in GIT_CRITICAL_DIRECTORIES:
                fd = hold(
                    cls._git_directory(
                        root, name.split("/"), create=False, cancel=cancel
                    )
                )
                info = os.fstat(fd)
                require(
                    (info.st_dev, info.st_ino, mountid(fd)) == storage[name],
                    "GIT_TARGET_MOVED",
                )
                anchors[name] = fd

            # Inspect a bounded local bare config as inert data. Git receives a
            # static safe config in a new tmpfs, never a mount over host files.
            def read_local(name, maximum):
                fd = os.open(
                    name,
                    os.O_RDONLY
                    | os.O_NOFOLLOW
                    | os.O_NONBLOCK
                    | os.O_NOATIME
                    | os.O_CLOEXEC,
                    dir_fd=root,
                )
                try:
                    info = os.fstat(fd)
                    require(
                        stat.S_ISREG(info.st_mode)
                        and info.st_uid == os.getuid()
                        and info.st_nlink == 1
                        and info.st_size <= maximum,
                        "GIT_STORAGE_FILE_TYPE",
                    )
                    raw = os.pread(fd, maximum + 1, 0)
                    require(
                        len(raw) == info.st_size and os.fstat(fd).st_nlink == 1,
                        "GIT_STORAGE_CHANGED",
                    )
                    return raw
                finally:
                    os.close(fd)

            config = configparser.ConfigParser(interpolation=None, strict=True)
            try:
                config.read_string(read_local("config", 4096).decode("ascii"))
            except (UnicodeError, configparser.Error) as error:
                raise ValueError("GIT_BARE_CONFIG_DENIED") from error
            require(
                config.sections() == ["core"]
                and not config.defaults()
                and set(config["core"])
                <= {"repositoryformatversion", "filemode", "bare", "logallrefupdates"}
                and config["core"].get("repositoryformatversion") == "0"
                and config["core"].get("bare") == "true"
                and config["core"].get("logallrefupdates", "false") == "false",
                "GIT_BARE_CONFIG_DENIED",
            )
            head = read_local("HEAD", 192)
            require(
                re.fullmatch(
                    rb"(?:ref: refs/heads/[A-Za-z0-9][A-Za-z0-9/_-]{0,127}|[a-f0-9]{40})\n",
                    head,
                ),
                "GIT_HEAD_DENIED",
            )
            config_fd = sealed(
                "aioa-fixed-git-config",
                b"[core]\nrepositoryformatversion = 0\nbare = true\nlogAllRefUpdates = false\n",
            )
            head_fd = sealed("aioa-fixed-git-head", head)
            filter_fd = sealed("aioa-fixed-git-filter", build_filter(final=True))
            fd_path = lambda fd: "/proc/self/fd/" + str(fd)
            command = [
                fd_path(descriptors["/usr/bin/prlimit"]),
                "--as=268435456",
                "--cpu=8",
                "--fsize=8388608",
                "--nofile=64",
                "--",
                fd_path(descriptors["/usr/bin/bwrap"]),
                "--unshare-all",
                "--unshare-user",
                "--unshare-cgroup",
                "--disable-userns",
                "--assert-userns-disabled",
                "--new-session",
                "--die-with-parent",
                "--cap-drop",
                "ALL",
                "--clearenv",
                "--proc",
                "/proc",
                "--remount-ro",
                "/proc",
                "--dev",
                "/dev",
                "--size",
                "8388608",
                "--tmpfs",
                "/tmp",
                "--size",
                "8388608",
                "--tmpfs",
                "/repo",
                "--ro-bind-fd",
                str(anchors["objects"]),
                "/repo/objects",
                "--ro-bind-fd",
                str(anchors["refs"]),
                "/repo/refs",
                "--ro-bind-data",
                str(config_fd),
                "/repo/config",
                "--ro-bind-data",
                str(head_fd),
                "/repo/HEAD",
            ]
            try:
                packed = read_local("packed-refs", 1048576)
            except FileNotFoundError:
                pass
            else:
                command += [
                    "--ro-bind-data",
                    str(sealed("aioa-fixed-packed-refs", packed)),
                    "/repo/packed-refs",
                ]
            for path, fd in descriptors.items():
                if path not in ("/usr/bin/bwrap", "/usr/bin/prlimit"):
                    command += ["--perms", "0555", "--ro-bind-data", str(fd), path]
            environment = {
                "PATH": "/usr/bin",
                "HOME": "/nonexistent",
                "LANG": "C.UTF-8",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_ALLOW_PROTOCOL": "",
            }
            for name, value in environment.items():
                command += ["--setenv", name, value]
            command += [
                "--remount-ro",
                "/repo",
                "--remount-ro",
                "/",
                "--chdir",
                "/repo",
                "--seccomp",
                str(filter_fd),
                "--",
                "/usr/bin/git",
                "--no-replace-objects",
                "--git-dir=/repo",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.attributesFile=/dev/null",
                *git_arguments,
            ]
            source = stack.enter_context(tempfile.TemporaryFile())
            if data is not None:
                source.write(data)
                source.seek(0)
            require(cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED")
            if binding_check is not None:
                binding_check()
            child = subprocess.Popen(
                command,
                stdin=source,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                pass_fds=tuple(held),
            )
            selector = selectors.DefaultSelector()
            output, errors = bytearray(), bytearray()
            try:
                for stream, target in ((child.stdout, output), (child.stderr, errors)):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, target)
                deadline = time.monotonic() + 10
                while selector.get_map():
                    require(time.monotonic() < deadline, "GIT_PLUMBING_TIMEOUT")
                    require(
                        cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED"
                    )
                    for key, _ in selector.select(0.05):
                        chunk = os.read(key.fd, 16384)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        require(
                            len(output) + len(errors) + len(chunk) <= 1048576,
                            "GIT_PLUMBING_OUTPUT_BOUND",
                        )
                        key.data.extend(chunk)
                code = child.wait(timeout=max(0.1, deadline - time.monotonic()))
                require(code == 0, "GIT_PLUMBING_FAILED")
            finally:
                selector.close()
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=2)
                child.stdout.close()
                child.stderr.close()
            require(git_storage_identity(root) == topology, "GIT_STORAGE_CHANGED")
            if binding_check is not None:
                binding_check()
            require(cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED")
            if publish == "object":
                object_id = bytes(output).decode("ascii").strip()
                raw = (
                    arguments[3].encode()
                    + b" "
                    + str(len(data)).encode()
                    + b"\0"
                    + data
                )
                require(
                    oid(object_id) and hashlib.sha1(raw).hexdigest() == object_id,
                    "GIT_OBJECT_READBACK",
                )
                parent = hold(
                    cls._git_directory(
                        anchors["objects"], [object_id[:2]], create=True, cancel=cancel
                    )
                )
                if not cls._git_publish_new(
                    parent, object_id[2:], zlib.compress(raw), cancel=cancel
                ):
                    cls._git_existing_object(parent, object_id[2:], raw)
            elif publish is not None:
                _, target_ref, object_id, _ = publish
                raw = b"commit " + str(len(output)).encode() + b"\0" + bytes(output)
                require(
                    hashlib.sha1(raw).hexdigest() == object_id, "GIT_OBJECT_READBACK"
                )
                parent = hold(
                    cls._git_directory(
                        anchors["refs/heads"],
                        target_ref.split("/")[2:-1],
                        create=True,
                        cancel=cancel,
                    )
                )
                require(
                    cls._git_publish_new(
                        parent,
                        target_ref.rsplit("/", 1)[1],
                        object_id.encode() + b"\n",
                        cancel=cancel,
                    ),
                    "GIT_REF_ALREADY_EXISTS",
                )
                output = b""
            require(git_storage_identity(root) == topology, "GIT_STORAGE_CHANGED")
            return bytes(output)

    def dispatch(self, request, release_check, *, cancel=None):
        require(
            type(request) is SandboxDispatchRequest and callable(release_check),
            "LIVE_CORE_GATE_REQUIRED",
        )
        self.config.registry.validate(
            SandboxOperation(request.operation_bytes).to_dict()
        )
        p = self.config.profile()
        inputs = self.config.inputs()[
            json.loads(request.operation_bytes)["payload"]["recipe_id"]
        ]
        require(
            canonical_sha256(p) == self.config.profile_digest, "PINNED_PROFILE_CHANGED"
        )
        for name, pin in p["native"].items():
            path = self.config.root / (
                name + (".bpf" if name.endswith("filter") else "")
            )
            expected = pin["binary_sha256"] if type(pin) is dict else pin
            require(sha(path) == expected, "PINNED_NATIVE_CHANGED")
        require(
            sha(__file__) == p["backend_sha256"]
            and sha("/usr/bin/bwrap") == p["bwrap_sha256"]
            and sha(Path(__file__).with_name("sandbox_worker.py"))
            == p["worker_sha256"],
            "PINNED_BACKEND_CHANGED",
        )
        require(
            {
                key: {
                    "sha256": entry["sha256"],
                    "bytes": entry["bytes"],
                    "mode": entry["mode"],
                }
                for key, entry in self.config.runtime().items()
            }
            == p["runtime"],
            "PINNED_RUNTIME_CHANGED",
        )
        for entry in self.config.runtime().values():
            require(
                sha(entry["snapshot"]) == entry["sha256"]
                and stat.S_IMODE(Path(entry["snapshot"]).lstat().st_mode)
                == entry["mode"],
                "PINNED_RUNTIME_CHANGED",
            )
        for name, path in inputs["files"].items():
            require(sha(path) == inputs["manifest"][name], "PINNED_INPUT_CHANGED")
        release_check()  # early check; independent second check immediately before project ACK
        run = self.config.root / ("run-" + request.digest)
        run.mkdir(mode=0o700, exist_ok=False)
        sync_directory(self.config.root)
        worker_config = {
            "runtime": self.config.runtime(),
            "inputs": inputs["files"],
            "limits": json.loads(request.operation_bytes)["payload"],
            "gate": str(self.config.root / "worker_gate"),
            "bootstrap": str(self.config.root / "bootstrap"),
            "setup_filter": str(self.config.root / "setup_filter.bpf"),
            "final_filter": str(self.config.root / "final_filter.bpf"),
        }
        config_path = run / "worker.json"
        config_path.write_bytes(
            json.dumps(worker_config, sort_keys=True, separators=(",", ":")).encode()
        )
        config_path.chmod(0o400)
        return self._run(
            request, release_check, config_path, run, inputs, cancel=cancel
        )

    def _run(self, request, release_check, config_path, run, inputs, *, cancel=None):
        from runtime.mission.repair import RepairBoundaryError, failure_boundary

        unit = "aioa-sandbox-" + uuid.uuid4().hex + ".service"
        nonce = uuid.uuid4().hex
        receipt = {
            "started_at": now(),
            "unit": unit,
            "status": "UNKNOWN",
            "project_code_started": False,
            "operation_digest": request.operation_digest,
            "dispatch_digest": request.digest,
            "request": request.to_dict(),
            "warrant_digest": request.warrant_digest,
            "profile_digest": self.config.profile_digest,
            "stage": "PREPARED",
            "observations": {},
            "cleanup": [],
        }
        proc = None
        peer = None
        listener = None
        directory = None
        peerpidfd = None
        procdir = None
        proof = None
        work_events = None
        fds = []
        private = Path(tempfile.mkdtemp(prefix="aioa-handoff-"))
        os.chmod(private, 0o700)
        control = private / "control"
        try:
            with failure_boundary("SANDBOX_BROKER_FAILURE"):
                listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                listener.settimeout(5)
                listener.bind(str(control))
                os.chmod(control, 0o600)
                listener.listen(1)
                argv = [
                    "/usr/bin/systemd-run",
                    "--user",
                    "--quiet",
                    "--wait",
                    "--pipe",
                    "--service-type=exec",
                    "--expand-environment=no",
                    "--unit=" + unit,
                ]
                for prop in [
                    "Delegate=yes",
                    "DelegateSubgroup=supervisor",
                    "Slice=app.slice",
                    "MemoryMax=536870912",
                    "MemorySwapMax=0",
                    "TasksMax=16",
                    "CPUQuota=100%",
                    "CPUQuotaPeriodSec=100ms",
                    "NoNewPrivileges=yes",
                    "LimitAS=536870912",
                    "LimitCPU=15",
                    "LimitFSIZE=8388608",
                    "LimitCORE=0",
                    "LimitNOFILE=64",
                    "RuntimeMaxSec=32s",
                    "TimeoutStopSec=2s",
                    "KillMode=control-group",
                    "UMask=0077",
                ]:
                    argv += ["--property=" + prop]
                argv += [
                    "/usr/bin/env",
                    "-i",
                    "PATH=/usr/bin:/bin",
                    "LANG=C.UTF-8",
                    "/usr/bin/python3.12",
                    "-I",
                    "-S",
                    "-B",
                    str(Path(__file__).with_name("sandbox_worker.py")),
                    unit,
                    str(control),
                    nonce,
                    str(config_path),
                ]
                receipt["argv"] = argv
                proc = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                )
                receipt["stage"] = "WAITING_FOR_TRUSTED_KEEPER"
                ready = bounded_line(proc.stdout, cancel=cancel)
                assert (
                    ready["stage"] == "WORK_READY"
                    and ready["before_exec_placement"] is True
                )
                expected_path = "/sys/fs/cgroup/" + exact_cgroup(unit).split("::", 1)[
                    1
                ].lstrip("/")
                assert ready["work_cgroup"] == expected_path
                work_events = os.open(
                    expected_path + "/cgroup.events",
                    os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                )
                assert populated(work_events) == "1"
                kernel_limits = {
                    name: Path(expected_path).parent.joinpath(name).read_text().strip()
                    for name in ("memory.max", "memory.swap.max", "pids.max", "cpu.max")
                }
                require(kernel_limits == ready["limits"], "KERNEL_LIMITS_MISMATCH")
                receipt["observations"]["aggregate_kernel_limits"] = kernel_limits
                receipt["observations"]["worker_gate"] = ready
                receipt["observations"]["worker_events_fd_pinned_before_exec"] = True
                proc.stdin.write(b"G")
                proc.stdin.flush()
                peer, _ = listener.accept()
                peer.settimeout(3)
                listener.close()
                listener = None
                control.unlink()
                receipt["stage"] = "PEER_KERNEL_IDENTITY"
                pid, uid, gid = struct.unpack(
                    "3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                )
                assert pid > 0 and uid == os.getuid() and gid == os.getgid()
                peerpidfd = struct.unpack(
                    "i", peer.getsockopt(socket.SOL_SOCKET, 77, 4)
                )[0]
                os.set_inheritable(peerpidfd, False)
                assert not select.select([peerpidfd], [], [], 0)[0]
                procdir = os.open(
                    "/proc/" + str(pid), os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC
                )
                cgfd = os.open("cgroup", os.O_RDONLY | os.O_CLOEXEC, dir_fd=procdir)
                try:
                    cg = os.read(cgfd, 4096).decode().strip()
                finally:
                    os.close(cgfd)
                assert cg == exact_cgroup(unit)
                receipt["observations"]["peer"] = {
                    "pid": pid,
                    "uid": uid,
                    "gid": gid,
                    "pidfd_pinned": True,
                    "cgroup": cg,
                }
                receipt["stage"] = "RECEIVE_EXACT_DIRECTORY_FD"
                payload, ancillary, flags, _ = peer.recvmsg(
                    33, socket.CMSG_SPACE(4), socket.MSG_CMSG_CLOEXEC
                )
                for level, kind, data in ancillary:
                    if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                        integers = array.array("i")
                        integers.frombytes(
                            data[: len(data) - len(data) % integers.itemsize]
                        )
                        fds.extend(integers)
                assert (
                    not flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC)
                    and payload == nonce.encode()
                    and len(fds) == 1
                    and len(ancillary) == 1
                )
                directory = fds[0]
                metadata = os.fstat(directory)
                vfs = os.fstatvfs(directory)
                assert (
                    stat.S_ISDIR(metadata.st_mode)
                    and metadata.st_uid == os.getuid()
                    and not os.get_inheritable(directory)
                )
                assert (
                    vfs.f_blocks * vfs.f_frsize == 8388608
                    and not vfs.f_flag & os.ST_RDONLY
                )
                mid = mountid(directory)
                receipt["stage"] = "INDEPENDENT_PEER_MOUNTINFO"
                mfd = os.open("mountinfo", os.O_RDONLY | os.O_CLOEXEC, dir_fd=procdir)
                with os.fdopen(mfd) as stream:
                    mountinfo = stream.read(1048576)
                require(len(mountinfo) < 1048576, "MOUNTINFO_LIMIT_EXCEEDED")
                candidates = []
                for line in mountinfo.splitlines():
                    left, right = line.split(" - ", 1)
                    fields = left.split()
                    kind = right.split()
                    if fields[4] == "/artifacts":
                        candidates.append((fields, kind))
                assert len(candidates) == 1
                fields, kind = candidates[0]
                assert (
                    int(fields[0]) == mid
                    and fields[3] == "/"
                    and kind[0] == "tmpfs"
                    and "rw" in fields[5].split(",")
                )
                assert (
                    fields[2]
                    == f"{os.major(metadata.st_dev)}:{os.minor(metadata.st_dev)}"
                )
                receipt["observations"]["artifact_mount"] = {
                    "mount_id": mid,
                    "mountinfo_fields": fields,
                    "filesystem": kind,
                    "tmpfs_bytes": vfs.f_blocks * vfs.f_frsize,
                }
                receipt["stage"] = "INDEPENDENT_PROC_ROOT_ARTIFACT_OPEN"
                independent = os.open(
                    "root/artifacts",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
                    dir_fd=procdir,
                )
                try:
                    other = os.fstat(independent)
                    assert (metadata.st_dev, metadata.st_ino, mid) == (
                        other.st_dev,
                        other.st_ino,
                        mountid(independent),
                    )
                finally:
                    os.close(independent)
                receipt["stage"] = "INDEPENDENT_BOOTSTRAP_IDENTITY"
                exe = os.open("exe", os.O_RDONLY | os.O_CLOEXEC, dir_fd=procdir)
                with os.fdopen(exe, "rb") as stream:
                    assert (
                        hashlib.sha256(stream.read(1048576)).hexdigest()
                        == self.config.profile()["native"]["bootstrap"]["binary_sha256"]
                    )
                assert not select.select([peerpidfd], [], [], 0)[0]
                status = Path("/proc/" + str(pid) + "/status").read_text()
                values = dict(
                    line.split(":", 1) for line in status.splitlines() if ":" in line
                )
                require(
                    values["NoNewPrivs"].strip() == "1"
                    and values["Seccomp"].strip() == "2"
                    and all(
                        int(values[key].strip(), 16) == 0
                        for key in ("CapEff", "CapPrm", "CapBnd")
                    ),
                    "KERNEL_PRIVILEGES_MISMATCH",
                )
                namespaces = {
                    name: {
                        "host": os.readlink("/proc/self/ns/" + name),
                        "worker": os.readlink("/proc/" + str(pid) + "/ns/" + name),
                    }
                    for name in ("user", "mnt", "pid", "net", "ipc", "uts", "cgroup")
                }
                require(
                    all(
                        entry["host"] != entry["worker"]
                        for entry in namespaces.values()
                    ),
                    "KERNEL_NAMESPACE_MISMATCH",
                )
                receipt["observations"]["namespaces"] = namespaces
                receipt["observations"]["privileges"] = {
                    key: values[key].strip()
                    for key in ("NoNewPrivs", "Seccomp", "CapEff", "CapPrm", "CapBnd")
                }
                mounts = {}
                for line in mountinfo.splitlines():
                    left, right = line.split(" - ", 1)
                    fields = left.split()
                    mounts[fields[4]] = {
                        "options": fields[5].split(","),
                        "kind": right.split()[0],
                    }
                require(
                    "ro" in mounts["/"]["options"]
                    and "ro" in mounts["/proc"]["options"],
                    "KERNEL_ROOT_READONLY_REQUIRED",
                )
                for target in self.config.profile()["runtime"]:
                    require(
                        "ro" in mounts[target]["options"],
                        "KERNEL_RUNTIME_READONLY_REQUIRED",
                    )
                for name in inputs["files"]:
                    require(
                        "ro" in mounts["/inputs/" + name]["options"],
                        "KERNEL_INPUT_READONLY_REQUIRED",
                    )
                scratch = {}
                for target, key in [("work", "work_bytes"), ("tmp", "tmp_bytes")]:
                    scratch_fd = os.open(
                        "root/" + target,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
                        dir_fd=procdir,
                    )
                    try:
                        vfs = os.fstatvfs(scratch_fd)
                        size = vfs.f_blocks * vfs.f_frsize
                        require(
                            size == json.loads(request.operation_bytes)["payload"][key]
                            and not vfs.f_flag & os.ST_RDONLY
                            and mounts["/" + target]["kind"] == "tmpfs",
                            "KERNEL_SCRATCH_LIMIT_MISMATCH",
                        )
                        scratch[target] = size
                    finally:
                        os.close(scratch_fd)
                receipt["observations"]["readonly_mounts_verified"] = (
                    len(self.config.profile()["runtime"]) + len(inputs["files"]) + 2
                )
                receipt["observations"]["scratch_tmpfs_bytes"] = scratch
                release_check()
                peer.sendall(b"Y")
                receipt["project_code_started"] = True
                peer.close()
                peer = None
                receipt["stage"] = "FINAL_FILTER_AND_TEARDOWN"
                empty = bounded_line(proc.stdout, 24, cancel=cancel)
                assert (
                    empty["stage"] == "WORK_EMPTY"
                    and empty["spawn_and_migration_sealed"] is True
                )
                assert populated(work_events) == "0"
                receipt["observations"]["worker_populated_zero_before_readback"] = True
                receipt["observations"]["worker_terminal"] = empty
                receipt["stage"] = "PINNED_READBACK_AFTER_CHILD_EXIT"
                readback = {}
                for name, expected in inputs["expected"].items():
                    proof = os.open(
                        name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                        dir_fd=directory,
                    )
                    try:
                        metadata = os.fstat(proof)
                        require(
                            stat.S_ISREG(metadata.st_mode)
                            and metadata.st_nlink == 1
                            and metadata.st_size == expected["bytes"],
                            "INVALID_ARTIFACT_METADATA",
                        )
                        value = os.read(proof, expected["bytes"] + 1)
                        require(
                            len(value) == expected["bytes"]
                            and hashlib.sha256(value).hexdigest() == expected["sha256"],
                            "ARTIFACT_DIGEST_MISMATCH",
                        )
                        readback[name] = {
                            "sha256": hashlib.sha256(value).hexdigest(),
                            "bytes": len(value),
                            "nofollow": True,
                            "single_link": True,
                        }
                        destination = run / ("artifact-" + name)
                        with destination.open("xb") as copied:
                            copied.write(value)
                            copied.flush()
                            os.fchmod(copied.fileno(), 0o400)
                            os.fsync(copied.fileno())
                        sync_directory(run)
                    finally:
                        os.close(proof)
                        proof = None
                receipt["observations"]["pinned_readback"] = readback
                assert populated(work_events) == "0"
                receipt["observations"]["worker_populated_zero_after_readback"] = True
                proc.stdin.write(b"R")
                proc.stdin.flush()
                out, err = proc.communicate(timeout=4)
                receipt.update(
                    exit_code=proc.returncode,
                    stdout=out[:8192].decode(errors="replace"),
                    stderr=err[:4096].decode(errors="replace"),
                )
                assert proc.returncode == 0
                require(
                    empty["child_exit_code"] == 0
                    and empty["termination_reason"] == "EXITED",
                    "SANDBOX_UNSUCCESSFUL",
                )
                receipt["status"] = "READBACK_VERIFIED"
        except (ValueError, RepairBoundaryError) as exc:
            cause = exc.__cause__ if isinstance(exc, RepairBoundaryError) else exc
            receipt["error"] = {
                "type": type(exc).__name__,
                "errno": getattr(cause, "errno", None),
                "name": errno.errorcode.get(getattr(cause, "errno", None)),
                "message": str(exc)[:512],
            }
        finally:

            def guarded_cleanup(stage, callback):
                try:
                    with failure_boundary("SANDBOX_CLEANUP_FAILURE"):
                        callback()
                except (ValueError, RepairBoundaryError) as exc:
                    cause = (
                        exc.__cause__ if isinstance(exc, RepairBoundaryError) else exc
                    )
                    receipt["cleanup"].append(
                        {
                            "stage": stage,
                            "error": type(exc).__name__,
                            "errno": getattr(cause, "errno", None),
                        }
                    )

            if peer is not None:
                try:
                    peer.sendall(b"N")
                except OSError:
                    pass
                guarded_cleanup("PEER_CLOSE", peer.close)
            if listener is not None:
                guarded_cleanup("LISTENER_CLOSE", listener.close)
            receipt["cleanup"].append(
                command_result(["/usr/bin/systemctl", "--user", "stop", unit])
            )
            if proc is not None:

                def reap_owned():
                    try:
                        out, err = proc.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        out, err = proc.communicate(timeout=3)
                        receipt["owned_client_killed"] = True
                    receipt.setdefault("stdout", out[:8192].decode(errors="replace"))
                    receipt.setdefault("stderr", err[:4096].decode(errors="replace"))
                    receipt["exit_code"] = proc.returncode

                guarded_cleanup("OWNED_CLIENT_REAP", reap_owned)
            receipt["cleanup"].append(
                command_result(["/usr/bin/systemctl", "--user", "reset-failed", unit])
            )
            shown = command_result(
                [
                    "/usr/bin/systemctl",
                    "--user",
                    "show",
                    unit,
                    "--property=LoadState,ActiveState,SubState,MainPID",
                ]
            )
            receipt["cleanup"].append(shown)
            cgpath = Path("/sys/fs/cgroup") / exact_cgroup(unit).split("::", 1)[
                1
            ].lstrip("/").removesuffix("/work")
            receipt["cgroup_absent_after_cleanup"] = not cgpath.exists()
            receipt["cgroup_populated_zero_directly_observed"] = receipt[
                "observations"
            ].get("worker_populated_zero_before_readback", False) and receipt[
                "observations"
            ].get("worker_populated_zero_after_readback", False)
            if control.exists():
                guarded_cleanup("SOCKET_UNLINK", control.unlink)
            guarded_cleanup("PRIVATE_DIRECTORY_REMOVE", private.rmdir)
            for fd in set(
                fds
                + [v for v in [peerpidfd, procdir, proof, work_events] if v is not None]
            ):
                guarded_cleanup("DESCRIPTOR_CLOSE", lambda fd=fd: os.close(fd))
            terminal = shown.get("exit_code") == 0 and all(
                s in shown.get("stdout", "")
                for s in ["ActiveState=inactive", "SubState=dead", "MainPID=0"]
            )
            clean = (
                terminal
                and receipt["cgroup_absent_after_cleanup"]
                and not any("error" in c for c in receipt["cleanup"])
            )
            receipt["unit_terminal_observed"] = terminal
            if not clean:
                receipt["status"] = "UNKNOWN"
                receipt["cleanup_incomplete"] = True
            receipt["finished_at"] = now()
            with (run / "receipt.json").open("x") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(receipt, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            sync_directory(run)
            sync_directory(self.config.root)
        return receipt

    def verify(self, operation, warrant):
        from lab.archaioa.evidence import EvidenceRef
        from lab.archaioa.outcome import Applied
        from runtime.mission.liability import Reconciliation

        # Never bless exit code/model text. Require the independent pinned readback receipt.
        digest = "sha256:" + canonical_sha256(operation)
        require(digest == warrant.operation_hash, "READBACK_BINDING")
        inner = operation
        if operation.get("payload", {}).get("schema") == "aioa.local-operation.v2":
            inner = operation["payload"]["sandbox_operation"]
            require(
                inner["target_fingerprint"] == operation["target_fingerprint"]
                and inner["expected_target_revision"]
                == operation["expected_target_revision"]
                and inner["payload"]["task_id"] == warrant.task_id,
                "READBACK_BINDING",
            )
        self.config.registry.validate(inner)
        inner_digest = SandboxOperation.parse(inner).digest
        candidates = []
        for run in self.config.root.glob("run-*"):
            path = run / "receipt.json"
            if not path.exists() and not path.is_symlink():
                continue
            raw = read_evidence_file(run, "receipt.json")
            receipt = json.loads(raw)
            if (
                receipt.get("operation_digest") == inner_digest
                and receipt.get("warrant_digest") == warrant.digest()
            ):
                candidates.append((run, receipt, raw))
        require(len(candidates) == 1, "READBACK_REQUIRED")
        run, receipt, raw = candidates[0]
        stored = dict(receipt["request"])
        require(stored.pop("schema") == "aioa.sandbox-dispatch.v1", "READBACK_BINDING")
        stored["operation_bytes"] = canonical_json_bytes(stored.pop("operation"))
        request = SandboxDispatchRequest(**stored)
        require(
            request.digest == receipt["dispatch_digest"]
            and run.name == "run-" + request.digest
            and request.operation_digest == inner_digest
            and request.warrant_digest == warrant.digest()
            and request.operation_bytes == canonical_json_bytes(inner),
            "READBACK_BINDING",
        )
        require(
            receipt["status"] == "READBACK_VERIFIED"
            and receipt["cgroup_populated_zero_directly_observed"]
            and receipt["cgroup_absent_after_cleanup"]
            and receipt["unit_terminal_observed"]
            and receipt["profile_digest"] == self.config.profile_digest,
            "UNRESOLVED_READBACK",
        )
        expected = self.config.inputs()[inner["payload"]["recipe_id"]]["expected"]
        for name, pin in expected.items():
            fd = os.open(
                run / ("artifact-" + name),
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            )
            try:
                meta = os.fstat(fd)
                data = os.read(fd, pin["bytes"] + 1)
                require(
                    stat.S_ISREG(meta.st_mode)
                    and meta.st_nlink == 1
                    and len(data) == pin["bytes"]
                    and hashlib.sha256(data).hexdigest() == pin["sha256"],
                    "ARTIFACT_DIGEST_MISMATCH",
                )
            finally:
                os.close(fd)
        receipt_id = "sandbox-" + receipt["dispatch_digest"][:32]
        return Reconciliation(
            digest,
            Applied(receipt_id),
            EvidenceRef(
                receipt_id, "receipt", "sha256:" + hashlib.sha256(raw).hexdigest(), "v1"
            ),
            EvidenceRef(
                "sandbox-readback-" + receipt["dispatch_digest"][:24],
                "independent-readback",
                "sha256:"
                + canonical_sha256(receipt["observations"]["pinned_readback"]),
                "v1",
            ),
        )
