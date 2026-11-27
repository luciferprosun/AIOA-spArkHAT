"""Explicit trusted Linux sandbox broker. Imports and default routes never execute tools.

Only Core's live START branch supplies the release callback. Typed requests and
on-disk receipts are bindings/evidence, never replayable execution authority.
"""

import array
import errno
import hashlib
import json
import os
import re
import select
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.ports import _IN_TRANSACTION
from runtime.mission import sandbox_contracts
from runtime.mission.sandbox_bindings import (
    CONFIG_DOMAIN,
    CapturedSandboxConfig,
    MaterializationBindingInput,
    ObservationBindingInput,
    SandboxJobBinding,
    TrustedSandboxBindingPolicy,
    root_member,
)
from runtime.mission.sandbox_contracts import (
    RENDER_PROFILE_CEILINGS,
    RESOURCE_CEILINGS,
    SandboxDispatchRequest,
    SandboxOperation,
    SandboxRecipe,
    SandboxRegistry,
)
from runtime.mission.warrant import WarrantError, require

# Preserve the earlier export while selection uses the shared closed map.
RENDER_RESOURCE_CEILINGS = sandbox_contracts.RENDER_RESOURCE_CEILINGS


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


def build_filter(*, final, ipc_profile=None):
    if ipc_profile is not None and (type(ipc_profile) is not str
            or ipc_profile not in ('RENDER_UNIX_SOCKETPAIR_V1', 'RENDER_UNIX_LISTENER_V1', 'RENDER_UNIX_MOJO_V1')
            or final is not True):
        raise ValueError('UNAPPROVED_SANDBOX_IPC_PROFILE')
    # Linux x86_64 only. Each filter rejects other ABIs and x32 first.
    rows = [
        (0x20, 0, 0, 4),
        (0x15, 1, 0, 0xC000003E),
        (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0),
        (0x35, 0, 1, 0x40000000),
        (0x06, 0, 0, 0x80000000),
    ]
    if ipc_profile in ('RENDER_UNIX_SOCKETPAIR_V1', 'RENDER_UNIX_LISTENER_V1', 'RENDER_UNIX_MOJO_V1'):
        # The original pair profile stays byte-identical. Both profiles deny
        # connect(), including the mounted host handoff socket. Bootstrap
        # closes all fd>=3 before untrusted code; no host socket is inherited.
        pair = [
            (0x20, 0, 0, 20), (0x15, 0, 11, 0),
            (0x20, 0, 0, 16), (0x15, 0, 9, 1),
            (0x20, 0, 0, 28), (0x15, 0, 7, 0),
            (0x20, 0, 0, 24), (0x54, 0, 0, 0xFFF7F7F0), (0x15, 0, 4, 0),
            (0x20, 0, 0, 24), (0x54, 0, 0, 0xF),
            (0x15, 2, 0, 1), (0x15, 1, 0, 5),
            (0x06, 0, 0, 0x00050001), (0x06, 0, 0, 0x7FFF0000),
        ]
        rows.append((0x15, 0, len(pair), 53))
        rows.extend(pair)
        # Crashpad configures credentials on its fresh private Unix pairs.
        # No host socket FD survives bootstrap. This option adds no socket
        # creation, connection, listener or other socket-option permissions.
        # SO_PASSCRED may auto-bind in the job's private network namespace.
        for socket_option_call in (54, 55):
            credentials = []
            conditions = []
            checks = ((20, 0), (28, 0), (24, 1), (36, 0), (32, 16))
            if socket_option_call == 54:
                checks += ((52, 0), (48, 4))
            # For getsockopt the value and length are both user pointers;
            # only the kernel can validate them. The selected option is the
            # private pair's SO_PASSCRED flag, never peer/owner identity.
            for offset, expected in checks:
                credentials.append((0x20, 0, 0, offset))
                conditions.append(len(credentials))
                credentials.append((0x15, 0, 0, expected))
            credentials.append((0x20, 0, 0, 16))
            descriptor_bound = len(credentials)
            credentials.append((0x35, 0, 0, 64))
            credentials.extend(((0x06, 0, 0, 0x7FFF0000), (0x06, 0, 0, 0x00050001)))
            denied = len(credentials) - 1
            for index in conditions:
                code, _, _, expected = credentials[index]
                credentials[index] = (code, 0, denied - index - 1, expected)
            credentials[descriptor_bound] = (0x35, denied - descriptor_bound - 1, 0, 64)
            rows.append((0x15, 0, len(credentials), socket_option_call))
            rows.extend(credentials)
        # Chrome half-closes each end of its private SandboxIPC pair. Only
        # SHUT_RD/SHUT_WR on bounded job descriptors; no full shutdown or
        # connection/socket creation is added by this rule. Host FDs are closed.
        half_close = [
            (0x20, 0, 0, 20), (0x15, 0, 7, 0),
            (0x20, 0, 0, 28), (0x15, 0, 5, 0),
            (0x20, 0, 0, 16), (0x35, 3, 0, 64),
            (0x20, 0, 0, 24), (0x35, 1, 0, 2),
            (0x06, 0, 0, 0x7FFF0000), (0x06, 0, 0, 0x00050001),
        ]
        rows.append((0x15, 0, len(half_close), 48))
        rows.extend(half_close)
    if ipc_profile in ('RENDER_UNIX_LISTENER_V1', 'RENDER_UNIX_MOJO_V1'):
        # A separate operator-pinned profile for Chrome's ProcessSingleton.
        # Fresh UNIX stream creation, bounded bind and backlog-five listen only.
        # No connect/accept, INET, peer identity or imported host FD authority.
        # The address is an opaque guest pointer. Its safety also requires the
        # private network/mount namespaces and bootstrap's closed FD lifecycle.
        def listener_call(number, checks):
            block, branches = [], []
            for offset, comparison, expected in checks:
                block.append((0x20, 0, 0, offset))
                if type(expected) is tuple:
                    mask, expected = expected
                    block.append((0x54, 0, 0, mask))
                branches.append((len(block), comparison))
                block.append((0x15 if comparison == 'eq' else 0x35, 0, 0, expected))
            block.extend(((0x06, 0, 0, 0x7FFF0000), (0x06, 0, 0, 0x00050001)))
            denied = len(block) - 1
            for index, comparison in branches:
                code, _, _, expected = block[index]
                jump = denied - index - 1
                block[index] = (code, jump if comparison == 'lt' else 0,
                                0 if comparison == 'lt' else jump, expected)
            rows.append((0x15, 0, len(block), number))
            rows.extend(block)

        listener_call(41, ((20, 'eq', 0), (16, 'eq', 1), (28, 'eq', 0),
                           (24, 'eq', (0xFFF7F7FE, 0)), (24, 'eq', (0xF, 1)),
                           (36, 'eq', 0), (32, 'eq', 0)))
        listener_call(49, ((20, 'eq', 0), (16, 'lt', 64), (36, 'eq', 0),
                           (32, 'ge', 2), (32, 'lt', 111)))
        listener_call(50, ((20, 'eq', 0), (16, 'lt', 64), (28, 'eq', 0), (24, 'eq', 5)))
        if ipc_profile == 'RENDER_UNIX_MOJO_V1':
            # glibc send() uses sendto(NULL, 0) on x86_64. This writes to an
            # existing private socket only, never an address/new peer. The
            # buffer pointer/length stay kernel validated, as with write().
            # UNIX provenance comes from bootstrap/creation/SCM isolation,
            # not from a descriptor number or this pointer predicate alone.
            listener_call(44, ((20, 'eq', 0), (16, 'lt', 256), (44, 'eq', 0),
                               (40, 'eq', (0xFFFFBFBF, 0)), (52, 'eq', 0),
                               (48, 'eq', 0), (60, 'eq', 0), (56, 'eq', 0)))
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
    if ipc_profile in ('RENDER_UNIX_SOCKETPAIR_V1', 'RENDER_UNIX_LISTENER_V1', 'RENDER_UNIX_MOJO_V1'):
        deny.difference_update({46, 47, 53})
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


def load_host_config(root, *, trusted_root, root_identity=None):
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
    raw = _private_bytes(path, trusted, 4194304,
        expected_root=(root,root_identity) if root_identity is not None else None)
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
        and value["profile"].get("binding_source_sha256")
        == sha(Path(__file__).with_name("sandbox_bindings.py"))
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


def prepare_linux_sandbox(root, runtime_manifest, *, workspace, recipes, resource_profile=None,
                          renderer_ipc=None, input_profile=None):
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
    require(resource_profile is None or type(resource_profile) is str
            and resource_profile in RENDER_PROFILE_CEILINGS,
            'INVALID_SANDBOX_RESOURCE_PROFILE')
    input_limits = sandbox_contracts.sandbox_input_limits(input_profile)
    require(input_profile is None or resource_profile is None,
            'INCOMPATIBLE_SANDBOX_INPUT_PROFILE')
    renderer = resource_profile is not None
    require(renderer_ipc is None or renderer and type(renderer_ipc) is str
            and (renderer_ipc == 'RENDER_UNIX_LISTENER_V1'
                 or renderer_ipc == 'RENDER_UNIX_MOJO_V1' and resource_profile == 'HEADLESS_RENDER_V3'),
            'UNAPPROVED_SANDBOX_IPC_PROFILE')
    ipc_profile = (renderer_ipc or 'RENDER_UNIX_SOCKETPAIR_V1') if renderer else None
    resource_ceilings = RENDER_PROFILE_CEILINGS[resource_profile] if renderer else RESOURCE_CEILINGS
    chrome_targets = frozenset('/opt/google/chrome/' + name for name in (
        'chrome', 'chrome_crashpad_handler', 'icudtl.dat', 'resources.pak',
        'chrome_100_percent.pak', 'chrome_200_percent.pak', 'v8_context_snapshot.bin',
        'locales/en-US.pak'))
    chrome_targets = chrome_targets | {'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'}
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
                *(['-DAIOA_RENDER_LISTENER=1'] if name == 'bootstrap'
                  and ipc_profile in ('RENDER_UNIX_LISTENER_V1', 'RENDER_UNIX_MOJO_V1') else []),
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
        path.write_bytes(build_filter(final=final, ipc_profile=(
            ipc_profile if final else None)))
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
                or renderer and target in chrome_targets
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
    require(not renderer or '/opt/google/chrome/chrome' in runtime, 'PINNED_RENDERER_REQUIRED')
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
        "binding_source_sha256": sha(Path(__file__).with_name("sandbox_bindings.py")),
        "resources": dict(resource_ceilings),
        "env": env,
        "network": "OFF",
        "namespaces": 7,
        "retained_python_extensions": "manifest exact; includes host test and Tk extension closure",
    }
    if renderer:
        profile.update(resource_profile=resource_profile, ipc_profile=ipc_profile,
                       host_socket_creation='DENIED', inherited_control_fds=0,
                       virtual_address_limit_bytes=4 * 1024**4)
        if ipc_profile in ('RENDER_UNIX_LISTENER_V1', 'RENDER_UNIX_MOJO_V1'):
            profile.update(private_listener_creation='UNIX_STREAM_ONLY', host_connect='DENIED')
        if ipc_profile == 'RENDER_UNIX_MOJO_V1':
            profile.update(private_connected_send='NULL_ADDRESS_ONLY', private_send_fd_limit=256)
        if resource_profile in ('HEADLESS_RENDER_V2', 'HEADLESS_RENDER_V3'):
            profile['descriptor_limit'] = 256
    if input_profile is not None:
        profile.update(input_profile=input_profile, input_limits=dict(input_limits))
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
            and 0 < len(spec["files"]) <= input_limits["files"]
            and type(spec["expected"]) is dict
            and 0 < len(spec["expected"]) <= 8,
            "INVALID_TRUSTED_RECIPE",
        )
        if input_profile is not None:
            require(all(type(data) is bytes for data in spec['files'].values()),
                    'INVALID_TRUSTED_INPUT')
            require(sum(len(data) for data in spec['files'].values()) <= input_limits['total_bytes'],
                    'TRUSTED_INPUT_SUM_BOUND')
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
                and len(data) <= input_limits["per_file_bytes"],
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
                pids_max=resource_ceilings['pids_max'],
                resource_profile=resource_profile,
                input_profile=input_profile,
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
    def owner_policy(name, info):
        if not name:
            return info.st_uid == os.getuid() and not info.st_mode & 0o7077
        return info.st_uid == os.getuid() and not info.st_mode & 0o7022

    return _scan_git_storage(root, owner_policy)


def _scan_git_storage(root, owner_policy):
    """Shared topology scanner. Its caller supplies the complete ownership policy."""
    origin = os.fstat(root)
    require(stat.S_ISDIR(origin.st_mode) and owner_policy("", origin),
            "GIT_REPOSITORY_OWNER_DENIED")
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
                    require(
                        owner_policy(name, info)
                        and info.st_dev == origin.st_dev
                        and mountid(fd) == origin_mount,
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
                            info.st_uid,
                            info.st_gid,
                            info.st_nlink,
                            info.st_size,
                            info.st_mtime_ns,
                            info.st_ctime_ns,
                        )
                        == (
                            named.st_dev,
                            named.st_ino,
                            named.st_mode,
                            named.st_uid,
                            named.st_gid,
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


def _parse_descriptor_limits(raw, *, expected):
    """Bounded kernel limits data, never a source of execution authority."""
    require(type(raw) is bytes and 0 < len(raw) <= 8192
            and type(expected) is int and expected in (64, 256), 'KERNEL_DESCRIPTOR_LIMIT_MISMATCH')
    try:
        text = raw.decode('ascii')
    except UnicodeDecodeError:
        raise ValueError('KERNEL_DESCRIPTOR_LIMIT_MISMATCH') from None
    rows = [line for line in text.splitlines() if line.startswith('Max open files')]
    require(len(rows) == 1, 'KERNEL_DESCRIPTOR_LIMIT_MISMATCH')
    value = str(expected)
    require(re.fullmatch(r'Max open files[ \t]+' + value + r'[ \t]+' + value + r'[ \t]+files[ \t]*',
                         rows[0]) is not None, 'KERNEL_DESCRIPTOR_LIMIT_MISMATCH')
    return expected, expected


def _observe_descriptor_limits(procdir, pidfd, *, expected):
    """Read the already pinned, live trusted bootstrap before project ACK."""
    require(type(procdir) is int and procdir >= 0 and type(pidfd) is int and pidfd >= 0
            and type(expected) is int and expected in (64, 256), 'KERNEL_DESCRIPTOR_LIMIT_MISMATCH')
    require(not select.select([pidfd], [], [], 0)[0], 'BOOTSTRAP_EXITED_BEFORE_DESCRIPTOR_PROOF')
    fd = os.open('limits', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=procdir)
    try:
        raw = os.read(fd, 8193)
    finally:
        os.close(fd)
    soft, hard = _parse_descriptor_limits(raw, expected=expected)
    require(not select.select([pidfd], [], [], 0)[0], 'BOOTSTRAP_EXITED_BEFORE_DESCRIPTOR_PROOF')
    return {'soft': soft, 'hard': hard, 'source': 'PINNED_BOOTSTRAP_PROC_LIMITS'}


def _systemd_properties(operation):
    """Properties for already registered operations; parsing grants no authority."""
    limits = SandboxOperation.parse(operation).to_dict()['payload']
    return (
        'Delegate=yes',
        'DelegateSubgroup=supervisor',
        'Slice=app.slice',
        'MemoryMax=536870912',
        'MemorySwapMax=0',
        "TasksMax=" + str(limits["pids_max"]),
        'CPUQuota=100%',
        'CPUQuotaPeriodSec=100ms',
        'NoNewPrivileges=yes',
        ('LimitAS=4398046511104' if limits.get('resource_profile') in RENDER_PROFILE_CEILINGS
         else 'LimitAS=536870912'),
        'LimitCPU=15',
        'LimitFSIZE=8388608',
        'LimitCORE=0',
        ('LimitNOFILE=256' if limits.get('resource_profile') in ('HEADLESS_RENDER_V2', 'HEADLESS_RENDER_V3')
         else 'LimitNOFILE=64'),
        'RuntimeMaxSec=32s',
        'TimeoutStopSec=2s',
        'KillMode=control-group',
        'UMask=0077',
    )


def _cache_identity(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_nlink,
            info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _directory_identity(info):
    return {'device':info.st_dev,'inode':info.st_ino,
            'uid':info.st_uid,'mode':stat.S_IMODE(info.st_mode)}


@contextmanager
def _private_descriptor(path, trusted, *, directory=False, expected_root=None):
    """Pin every component and recheck its name before accessing leaf bytes."""
    path,trusted=Path(path),Path(trusted)
    require(path.is_absolute() and trusted.is_absolute() and path.is_relative_to(trusted)
            and '..' not in path.parts and '..' not in trusted.parts,'SANDBOX_CACHE_PATH_DENIED')
    descriptors=[];ancestry=[]
    flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_DIRECTORY
    def check_ancestry():
        for parent,name,child,initial in ancestry:
            named=os.stat(name,dir_fd=parent,follow_symlinks=False)
            opened=os.fstat(child)
            identity=lambda info:(info.st_dev,info.st_ino,info.st_mode,info.st_uid)
            require(identity(named)==identity(opened)==identity(initial),'SANDBOX_CACHE_CHANGED')
    try:
        current=os.open('/',flags);descriptors.append(current)
        components=path.parts[1:] if directory else path.parent.parts[1:]
        for index,name in enumerate(components,1):
            before=os.stat(name,dir_fd=current,follow_symlinks=False)
            child=os.open(name,flags,dir_fd=current);descriptors.append(child)
            ancestry.append((current,name,child,before));current=child
            info=os.fstat(child)
            if expected_root is not None and Path(path.anchor,*components[:index])==expected_root[0]:
                require(_directory_identity(info)==expected_root[1],'SANDBOX_CAPTURE_CHANGED')
            if index>=len(trusted.parts)-1:
                # Owned transit remains below the private anchor. Preserve the
                # private-mode rule for that anchor and the final parent.
                require(info.st_uid==os.getuid() and (index not in (len(trusted.parts)-1,len(components))
                        or not info.st_mode & 0o077),
                        'SANDBOX_PRIVATE_CACHE_REQUIRED')
        if directory:
            info=os.fstat(current)
            require(info.st_uid==os.getuid() and not info.st_mode & 0o077,
                    'SANDBOX_PRIVATE_CACHE_REQUIRED')
            check_ancestry();yield current,info,check_ancestry;check_ancestry()
        else:
            before=os.stat(path.name,dir_fd=current,follow_symlinks=False)
            leaf=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,
                         dir_fd=current);descriptors.append(leaf)
            opened=os.fstat(leaf)
            require(stat.S_ISREG(opened.st_mode) and opened.st_nlink==1
                    and opened.st_uid==os.getuid() and not opened.st_mode & 0o077,
                    'SANDBOX_PRIVATE_CACHE_REQUIRED')
            def check_leaf():
                check_ancestry()
                named=os.stat(path.name,dir_fd=current,follow_symlinks=False)
                require(_cache_identity(before)==_cache_identity(os.fstat(leaf))==_cache_identity(named),
                        'SANDBOX_CACHE_CHANGED')
            check_leaf();yield leaf,opened,check_leaf;check_leaf()
    except OSError as error:
        raise ValueError('SANDBOX_CACHE_PATH_DENIED') from error
    finally:
        for descriptor in reversed(descriptors):os.close(descriptor)


def _private_path(path, trusted, *, directory=False, expected_root=None):
    with _private_descriptor(path,trusted,directory=directory,expected_root=expected_root) as (_fd,info,_check):
        return info


def _private_bytes(path, trusted, maximum, *, expected_root=None):
    with _private_descriptor(path,trusted,expected_root=expected_root) as (fd,before,check):
        require(before.st_size<=maximum,'SANDBOX_CACHE_BOUNDS')
        raw=bytearray()
        while len(raw)<=maximum:
            check()
            part=os.read(fd,min(65536,maximum+1-len(raw)))
            if not part:break
            raw.extend(part)
        check()
        require(len(raw)==before.st_size,'SANDBOX_CACHE_CHANGED')
        return bytes(raw)


def _config_identity(config):
    return canonical_json_bytes({'domain':CONFIG_DOMAIN,'profile_digest':config.profile_digest,
        'registry':{'workspace':config.registry.workspace,
                    'recipes':[asdict(r) for r in config.registry.recipes]},
        'inputs':{key:{field:value[field] for field in ('manifest','expected','digest')}
                  for key,value in config.inputs().items()}})


class LinuxSandboxBroker:
    def __init__(self, config=None, *, binding_policy=None):
        require(type(config) is TrustedSandboxConfig and not sys.flags.optimize,
                'TRUSTED_SANDBOX_CONFIGURATION_REQUIRED')
        require(config.profile_digest == canonical_sha256(config.profile()), 'PINNED_PROFILE_CHANGED')
        require(binding_policy is None or type(binding_policy) is TrustedSandboxBindingPolicy,
                'SANDBOX_BINDING_POLICY_REQUIRED')
        self._seed_config = config
        self._binding_policy = binding_policy
        self._binding_owner = None
        self._owner_objects = None
        self._captures = {}
        self._bindings = {}
        self._uncertain_bindings = set()
        self._closed = False
        self._active_cancel = None
        self._quarantined = False
        if binding_policy is not None:
            require(config.profile_digest == binding_policy.profile_digest
                    and config.registry.workspace == binding_policy.workspace,
                    'SANDBOX_BINDING_POLICY_REQUIRED')
            self._recipe_digest = binding_policy.recipe.digest
            self._binding_source = sha(Path(__file__).with_name('sandbox_bindings.py'))
            self._validate_config(config)

    @property
    def config(self):
        """The immutable legacy seed; never the currently selected job config."""
        return self._seed_config

    @property
    def binding_policy(self):
        return self._binding_policy

    def bind_route(self, route):
        require(self.binding_policy is not None and self._binding_owner is None,
                'SANDBOX_BINDING_OWNER')
        prior=getattr(route.core,'_sandbox_binding_owner',None)
        require(prior is None or prior._closed and prior._active_cancel is None,'SANDBOX_BINDING_OWNER')
        self._binding_owner = route
        route.core._sandbox_binding_owner=self
        self._owner_objects = (route.core,route.runner,route.journal,route.journal.ledger,
                               route.liability,route.journal.governor)
        self.require_route_binding(route)

    def require_route_binding(self, route):
        require(route is not None and route is self._binding_owner and route.executor is self
                and self._owner_objects is not None, 'SANDBOX_BINDING_OWNER')
        expected=(route.core,route.runner,route.journal,route.journal.ledger,
                  route.liability,route.journal.governor)
        require(all(a is b for a,b in zip(expected,self._owner_objects,strict=True))
                and route.core is route.journal.ledger.core is route.liability.core
                    is route.journal.governor.core
                and route.runner is route.journal.ledger.runner is route.liability.runner
                    is route.journal.governor.runner
                and route.workspace==self.binding_policy.workspace,
                'SANDBOX_BINDING_OWNER')

    def _source_check(self):
        policy=self.binding_policy
        require(policy.recipe.digest==self._recipe_digest
                and sha(Path(__file__).with_name('sandbox_bindings.py'))==self._binding_source,
                'SANDBOX_BINDING_SOURCE')
        policy.source_snapshot.verify(policy.source_repository)
        policy.source_snapshot.verify_export(policy.base_root)

    def _validate_config(self, config, *, root_identity=None):
        policy=self.binding_policy
        require(type(config) is TrustedSandboxConfig
                and config.root.parent==policy.trusted_root, 'SANDBOX_BINDING_ROOT_DENIED')
        root_member(config.root.name)
        _private_path(policy.trusted_root,policy.trusted_root,directory=True)
        info=_private_path(config.root,policy.trusted_root,directory=True,
            expected_root=(config.root,root_identity) if root_identity is not None else None)
        root_identity=_directory_identity(info)
        expected_root=(config.root,root_identity)
        profile=config.profile()
        require(config.profile_bytes==canonical_json_bytes(profile)
                and canonical_sha256(profile)==config.profile_digest==policy.profile_digest
                and config.registry.workspace==policy.workspace
                and profile.get('input_profile')==policy.recipe.sandbox_input_profile
                and 'resource_profile' not in profile, 'SANDBOX_BINDING_PROFILE')
        require(profile.get('binding_source_sha256')==self._binding_source
                and sha(__file__)==profile['backend_sha256']
                and sha(Path(__file__).with_name('sandbox_worker.py'))==profile['worker_sha256']
                and sha('/usr/bin/bwrap')==profile['bwrap_sha256'],'PINNED_BACKEND_CHANGED')
        for name,pin in profile['native'].items():
            require(name in ('worker_gate','bootstrap','setup_filter','final_filter'), 'SANDBOX_BINDING_PROFILE')
            filename=name+('.bpf' if name.endswith('filter') else '')
            raw=_private_bytes(config.root/filename,policy.trusted_root,4194304,expected_root=expected_root)
            require(hashlib.sha256(raw).hexdigest()==(pin['binary_sha256'] if type(pin) is dict else pin),
                    'PINNED_NATIVE_CHANGED')
            if type(pin) is dict:
                require(sha(Path(__file__).parent/'native'/(name+'.c'))==pin['source_sha256'],
                        'PINNED_NATIVE_CHANGED')
        runtime=config.runtime()
        require({key:{field:entry[field] for field in ('sha256','bytes','mode')}
                 for key,entry in runtime.items()}==profile['runtime'],'PINNED_RUNTIME_CHANGED')
        for entry in runtime.values():
            raw=_private_bytes(entry['snapshot'],policy.trusted_root,entry['bytes'],expected_root=expected_root)
            require(len(raw)==entry['bytes'] and hashlib.sha256(raw).hexdigest()==entry['sha256']
                    and stat.S_IMODE(Path(entry['snapshot']).lstat().st_mode)==entry['mode'],
                    'PINNED_RUNTIME_CHANGED')
        inputs=config.inputs()
        require(set(inputs)=={r.recipe_id for r in config.registry.recipes},'SANDBOX_BINDING_INPUT')
        limits=sandbox_contracts.sandbox_input_limits(profile.get('input_profile'))
        template=self.config.registry.recipes[0]
        for index,recipe in enumerate(config.registry.recipes):
            entry=inputs[recipe.recipe_id]
            require(set(entry)=={'files','manifest','expected','digest'}
                    and set(entry['files'])==set(entry['manifest'])
                    and 1<=len(entry['files'])<=limits['files']
                    and 1<=len(entry['expected'])<=8,'SANDBOX_BINDING_INPUT')
            size=0
            for name,filename in entry['files'].items():
                root_member(name)
                require(Path(filename)==config.root/('input-'+str(index))/name,
                        'SANDBOX_CACHE_INPUT_DENIED')
                raw=_private_bytes(filename,policy.trusted_root,limits['per_file_bytes'],expected_root=expected_root);size+=len(raw)
                require(hashlib.sha256(raw).hexdigest()==entry['manifest'][name],'PINNED_INPUT_CHANGED')
            require(size<=limits['total_bytes'],'TRUSTED_INPUT_SUM_BOUND')
            for name,pin in entry['expected'].items():
                root_member(name)
                require(type(pin) is dict and set(pin)=={'bytes','sha256'}
                        and type(pin['bytes']) is int and 0<=pin['bytes']<=1048576,
                        'INVALID_EXPECTED_ARTIFACT')
            input_digest=canonical_sha256({'files':entry['manifest'],'expected':entry['expected']})
            require(entry['digest']==input_digest and recipe==replace(template,
                    recipe_id=recipe.recipe_id,project_root_ref='trusted-input-'+input_digest[:24],
                    tool_input_digest=input_digest), 'SANDBOX_REGISTRY_BINDING')
        return canonical_json_bytes(root_identity)

    def _derive_binding(self, binding_input, recipe_stages):
        from runtime.mission.patchset import observe_source
        from runtime.mission.repair import TEST_STAGES
        policy=self.binding_policy
        self._source_check()
        require(type(recipe_stages) is tuple and 1<=len(recipe_stages)<=3
                and all(type(p) is tuple and len(p)==2 for p in recipe_stages)
                and len({p[0] for p in recipe_stages})==len(recipe_stages)
                and len({p[1] for p in recipe_stages})==len(recipe_stages),'SANDBOX_BINDING_STAGE')
        source=observe_source(policy.base_root,repository_id=policy.recipe.repository_id,
            workspace_id=policy.workspace,source_base_sha=policy.recipe.source_base_sha)
        require(all(p[1] in (*TEST_STAGES,'MATERIALIZE') for p in recipe_stages),
                'SANDBOX_BINDING_STAGE')
        if type(binding_input) is MaterializationBindingInput:
            binding_input.__post_init__()
            task,session=binding_input.task,binding_input.session
            require(task.workspace_id==policy.workspace and task.repository_id==source.repository_id
                    and task.source_base_sha==source.source_base_sha
                    and tuple(p[1] for p in recipe_stages)==('MATERIALIZE',),'SANDBOX_BINDING_TASK')
            patch,_archive,spec=policy.recipe.materialization_spec(policy.base_root,source=source,
                task=task,worker_session_id=session.session_id,candidate=binding_input.candidate)
            specs={recipe_stages[0][0]:spec};kind='MATERIALIZE'
        else:
            require(type(binding_input) is ObservationBindingInput,'SANDBOX_BINDING_INPUT')
            binding_input.__post_init__();patch=binding_input.patchset
            policy.recipe.validate_patch(patch)
            require(all(p[1] in TEST_STAGES for p in recipe_stages),'SANDBOX_BINDING_STAGE')
            specs={identity:policy.recipe.observation_spec(stage,binding_input.archive,patch)
                   for identity,stage in recipe_stages};kind='OBSERVE'
        require(patch.workspace_id==source.workspace_id and patch.repository_id==source.repository_id
                and patch.source_base_sha==source.source_base_sha
                and patch.base_tree_sha256==source.base_tree_sha256,'SANDBOX_BINDING_SOURCE')
        provenance={'kind':kind,'repository_recipe_digest':policy.recipe.digest,
            'source_snapshot_digest':policy.source_snapshot.digest,'source_identity':asdict(source),
            'coding_task_id':patch.task_id,'coding_run_id':patch.run_id,'coding_task_digest':patch.task_digest,
            'worker_session_id':patch.worker_session_id,'patchset_sha256':patch.patchset_sha256,
            'final_tree_sha256':patch.final_tree_sha256,'recipe_stages':recipe_stages}
        return specs,canonical_json_bytes(provenance)

    def _pin_specs(self, config, specs):
        require(tuple(specs)==tuple(r.recipe_id for r in config.registry.recipes),'SANDBOX_BINDING_STAGE')
        for identity,spec in specs.items():
            actual=config.inputs()[identity]
            require(actual['manifest']=={n:hashlib.sha256(v).hexdigest() for n,v in spec['files'].items()}
                    and actual['expected']=={n:{'sha256':hashlib.sha256(v).hexdigest(),'bytes':len(v)}
                                             for n,v in spec['expected'].items()},'VALIDATION_INPUTS')

    def capture_config(self, config, *, binding_input, recipe_stages):
        self.require_route_binding(self._binding_owner)
        require(not self._closed,'SANDBOX_BROKER_CLOSED')
        specs,provenance=self._derive_binding(binding_input,recipe_stages)
        prior=self._captures.get(config.root.name) if type(config) is TrustedSandboxConfig else None
        identity=self._validate_config(config,root_identity=json.loads(prior.root_identity_bytes) if prior else None)
        self._pin_specs(config,specs)
        value=_config_identity(config);config_digest=canonical_sha256(json.loads(value))
        for capture in self._captures.values():
            if capture.config_digest==config_digest:
                require(capture.identity_bytes==value,'SANDBOX_CONFIG_COLLISION')
            if capture.config.root==config.root:
                require(capture.config is config and capture.identity_bytes==value
                        and capture.provenance_bytes==provenance,'SANDBOX_CONFIG_REBIND')
                self.revalidate_capture(capture)
                return capture
        require(len(self._captures)<self.binding_policy.max_configs,'SANDBOX_CONFIG_QUOTA')
        save_host_config(config)
        raw=_private_bytes(config.root/'host-config.json',self.binding_policy.trusted_root,4194304,
            expected_root=(config.root,json.loads(identity)))
        capture=CapturedSandboxConfig(config,value,config_digest,hashlib.sha256(raw).hexdigest(),
                                      identity,provenance,binding_input)
        self._captures[config.root.name]=capture
        return capture

    def require_capture(self, capture):
        self.require_route_binding(self._binding_owner)
        require(type(capture) is CapturedSandboxConfig
                and self._captures.get(capture.config.root.name) is capture,'SANDBOX_CAPTURE_OWNER')
        return capture

    def revalidate_capture(self, capture):
        self.require_capture(capture)
        expected_root=(capture.config.root,json.loads(capture.root_identity_bytes))
        identity=self._validate_config(capture.config,root_identity=expected_root[1])
        self._source_check()
        if capture.binding_input is not None:
            stages=tuple(tuple(p) for p in json.loads(capture.provenance_bytes)['recipe_stages'])
            specs,provenance=self._derive_binding(capture.binding_input,stages)
            self._pin_specs(capture.config,specs)
            require(provenance==capture.provenance_bytes,'SANDBOX_BINDING_SOURCE')
        require(identity==capture.root_identity_bytes and _config_identity(capture.config)==capture.identity_bytes
                and hashlib.sha256(_private_bytes(capture.config.root/'host-config.json',
                    self.binding_policy.trusted_root,4194304,expected_root=expected_root)).hexdigest()==capture.host_config_sha256,
                'SANDBOX_CAPTURE_CHANGED')
        return capture.config

    def publish_binding(self, value, capture, *, historical=False, operations=()):
        self.require_capture(capture)
        task=value['task_id'];record=canonical_json_bytes(value)
        prior=self._bindings.get(task)
        if prior is not None:
            require(prior[0].record_bytes==record and prior[1] is capture
                    and (historical or prior[0].operation_bytes==operations),'SANDBOX_CONFIG_REBIND')
            return prior[0]
        require(len(self._bindings)<self.binding_policy.max_jobs,'SANDBOX_JOB_QUOTA')
        require(value['config_digest']==capture.config_digest
                and value['host_config_sha256']==capture.host_config_sha256
                and value['root_ref']==capture.config.root.name
                and value['root_identity']==json.loads(capture.root_identity_bytes)
                and value['provenance']==json.loads(capture.provenance_bytes),'SANDBOX_BINDING_INTEGRITY')
        require(historical or type(operations) is tuple and 1<=len(operations)<=32
                and all(type(op) is bytes for op in operations),'SANDBOX_OPERATION_BINDING')
        handle=SandboxJobBinding(record,'HISTORY_ONLY' if historical else 'LIVE',operations)
        self._bindings[task]=(handle,capture)
        return handle

    def binding_for_operation(self, operation, *, historical=False):
        self.require_route_binding(self._binding_owner)
        parsed=SandboxOperation.parse(operation);payload=parsed.to_dict()['payload']
        pair=self._bindings.get(payload['task_id'])
        require(pair is not None,'SANDBOX_JOB_BINDING_REQUIRED')
        handle,capture=pair;value=json.loads(handle.record_bytes)
        require(historical or handle.mode=='LIVE' and not self._closed and not self._quarantined,
                'SANDBOX_HISTORY_ONLY')
        require({'step_id':payload['step_id'],'operation_digest':parsed.digest} in value['allowed_operations'],
                'SANDBOX_OPERATION_BINDING')
        require(handle.mode=='HISTORY_ONLY' or parsed.operation_bytes in handle.operation_bytes,
                'SANDBOX_OPERATION_BINDING')
        capture.config.registry.validate(operation)
        return handle,capture

    def restore_capture(self, value):
        self.require_route_binding(self._binding_owner)
        root=self.binding_policy.trusted_root/root_member(value['root_ref'])
        expected_root=(root,value['root_identity'])
        config=load_host_config(root,trusted_root=self.binding_policy.trusted_root,root_identity=expected_root[1])
        identity=self._validate_config(config,root_identity=expected_root[1]);self._source_check()
        provenance=value['provenance'];policy=self.binding_policy
        from runtime.mission.patchset import observe_source
        source=observe_source(policy.base_root,repository_id=policy.recipe.repository_id,
            workspace_id=policy.workspace,source_base_sha=policy.recipe.source_base_sha)
        require(provenance['repository_recipe_digest']==policy.recipe.digest
                and provenance['source_snapshot_digest']==policy.source_snapshot.digest
                and provenance['source_identity']==asdict(source),'SANDBOX_BINDING_SOURCE')
        raw=_private_bytes(root/'host-config.json',policy.trusted_root,4194304,expected_root=expected_root)
        capture=CapturedSandboxConfig(config,_config_identity(config),value['config_digest'],
            hashlib.sha256(raw).hexdigest(),identity,canonical_json_bytes(provenance),None)
        require(canonical_sha256(json.loads(capture.identity_bytes))==value['config_digest'],
                'SANDBOX_CAPTURE_CHANGED')
        prior=self._captures.get(root.name)
        if prior is not None:
            require(prior.identity_bytes==capture.identity_bytes
                    and prior.provenance_bytes==capture.provenance_bytes,'SANDBOX_CONFIG_REBIND')
            capture=prior
        else:
            require(len(self._captures)<policy.max_configs,'SANDBOX_CONFIG_QUOTA')
            self._captures[root.name]=capture
        return capture

    def close(self):
        self._closed=True
        if self._active_cancel is not None:
            self._active_cancel.cancel()

    def __call__(self, request):
        raise ValueError("LIVE_CORE_GATE_REQUIRED")

    @staticmethod
    def _git_directory(anchor, parts, *, create, cancel, shared_reader=None):
        """No-follow directories beneath a descriptor-bound storage anchor."""
        from contextlib import ExitStack

        require(len(parts) <= 16, "GIT_STORAGE_BOUNDS")
        require(shared_reader is None or not create, "NATIVE_CORE_STORAGE_READ_ONLY")
        origin = os.fstat(anchor)
        origin_mount = mountid(anchor)
        with ExitStack() as stack:
            current = anchor
            for depth, part in enumerate(parts, 1):
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
                    | (os.O_NOATIME if shared_reader is None else 0)
                    | os.O_CLOEXEC,
                    dir_fd=current,
                )
                stack.callback(os.close, fd)
                info = os.fstat(fd)
                require(
                    (info.st_uid == os.getuid() and not info.st_mode & 0o7022
                     if shared_reader is None else shared_reader.entry_matches("/".join(parts[:depth]), info))
                    and info.st_dev == origin.st_dev
                    and mountid(fd) == origin_mount,
                    "GIT_STORAGE_OWNER_OR_MOUNT",
                )
                current = fd
            return os.dup(current)

    @staticmethod
    def _git_publish_new(parent, name, data, *, cancel, before_ref_link=None,
                         before_ref_link_guard=None, expected_parent_identity=None,
                         before_ref_link_check=None, reader_gid=None):
        """Atomic create-only publication of a fully written unnamed inode.

        No truncation, chmod, utime, append or write to an existing pathname.
        O_TMPFILE keeps incomplete bytes unnameable. linkat's exclusive create
        protects a new loose pathname; the ref transaction separately checks
        packed refs and Git name conflicts. Unsupported filesystems fail closed.
        """
        require(
            type(data) is bytes and len(data) <= 2097152, "GIT_PLUMBING_INPUT_BOUND"
        )
        fd = os.open(".", os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC,
                     0o400 if reader_gid is None else 0o440, dir_fd=parent)
        try:
            if reader_gid is not None:
                info = os.fstat(fd)
                require(info.st_uid == os.geteuid() and info.st_gid == reader_gid
                        and stat.S_IMODE(info.st_mode) == 0o440, "GIT_SHARED_FILE_MODE")
            if expected_parent_identity is not None:
                parent_info = os.fstat(parent)
                require(type(expected_parent_identity) is tuple
                        and len(expected_parent_identity) == 2
                        and all(type(value) is int and value > 0
                                for value in expected_parent_identity)
                        and (parent_info.st_dev, parent_info.st_ino) == expected_parent_identity,
                        "GIT_REF_DIRECTORY_CHANGED")
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
            if before_ref_link_guard is not None:
                require(before_ref_link is not None
                        and callable(getattr(before_ref_link_guard, "hold", None)),
                        "GIT_REF_RELEASE_CONTEXT_DENIED")
                gate = before_ref_link_guard.hold()
            else:
                from contextlib import nullcontext
                gate = nullcontext()
            with gate:
                if before_ref_link is not None:
                    require(not _IN_TRANSACTION.get(), "GIT_REF_RELEASE_CONTEXT_DENIED")
                    before_ref_link()
                    require(cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED")
                if before_ref_link_check is not None:
                    require(callable(before_ref_link_check), "GIT_REF_RELEASE_CONTEXT_DENIED")
                    before_ref_link_check()
                if expected_parent_identity is not None:
                    parent_info = os.fstat(parent)
                    require((parent_info.st_dev, parent_info.st_ino) == expected_parent_identity,
                            "GIT_REF_DIRECTORY_CHANGED")
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
            published = os.fstat(fd)
            try:
                named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                raise WarrantError("GIT_PUBLISHED_NAME_CHANGED") from None
            require(
                published.st_nlink == named.st_nlink == 1
                and (published.st_dev, published.st_ino) == (named.st_dev, named.st_ino),
                "GIT_PUBLISHED_NAME_CHANGED",
            )
            return True
        finally:
            os.close(fd)

    @staticmethod
    def _git_existing_object(parent, name, expected, *, sync=False, reader_gid=None):
        import zlib

        fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            | (os.O_NOATIME if reader_gid is None else 0),
            dir_fd=parent,
        )
        try:
            info = os.fstat(fd)
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and (reader_gid is None or (info.st_gid == reader_gid
                     and stat.S_IMODE(info.st_mode) == 0o440 and mountid(fd) == mountid(parent)))
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
            if sync:
                os.fsync(fd)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            after = os.fstat(fd)
            identity = lambda row: (
                row.st_dev,
                row.st_ino,
                row.st_size,
                row.st_mode,
                row.st_uid,
                row.st_gid,
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
        before_ref_link=None,
        before_ref_link_guard=None,
        expected_ref_directory=None,
        shared_reader=None,
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
            before_ref_link is None or (type(publish) is tuple and callable(before_ref_link)),
            "GIT_REF_RELEASE_CONTEXT_DENIED",
        )
        require(expected_ref_directory is None
                or type(expected_ref_directory) is tuple and len(expected_ref_directory) == 2
                and all(type(value) is int and value > 0 for value in expected_ref_directory),
                "GIT_REF_DIRECTORY_BINDING")
        require(
            data is None or arguments[0] == "hash-object", "GIT_PLUMBING_INPUT_BOUND"
        )
        require(cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED")
        if shared_reader is not None:
            from runtime.red_hat.role_storage import CoreTargetStorage

            require(type(shared_reader) is CoreTargetStorage and publish is None and data is None
                    and before_ref_link is None and before_ref_link_guard is None
                    and expected_ref_directory is None, "NATIVE_CORE_STORAGE_READ_ONLY")

        def observe_storage():
            return git_storage_identity(root) if shared_reader is None else shared_reader.observe(root)[1]

        topology = observe_storage()
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
            directory_options = {} if shared_reader is None else {"shared_reader": shared_reader}
            for name in GIT_CRITICAL_DIRECTORIES:
                fd = hold(cls._git_directory(root, name.split("/"), create=False, cancel=cancel,
                                             **directory_options))
                info = os.fstat(fd)
                require(
                    (info.st_dev, info.st_ino, mountid(fd)) == storage[name],
                    "GIT_TARGET_MOVED",
                )
                anchors[name] = fd

            # Inspect a bounded local bare config as inert data. Git receives a
            # static safe config in a new tmpfs, never a mount over host files.
            def read_local(name, maximum, *, optional=False, identity=False):
                try:
                    fd = os.open(
                        name,
                        os.O_RDONLY
                        | os.O_NOFOLLOW
                        | os.O_NONBLOCK
                        | (os.O_NOATIME if shared_reader is None else 0)
                        | os.O_CLOEXEC,
                        dir_fd=root,
                    )
                except FileNotFoundError:
                    if optional:
                        return None
                    raise
                try:
                    info = os.fstat(fd)
                    require(
                        stat.S_ISREG(info.st_mode)
                        and (info.st_uid == os.getuid() if shared_reader is None
                             else shared_reader.entry_matches(name, info) and mountid(fd) == mountid(root))
                        and info.st_nlink == 1
                        and info.st_size <= maximum,
                        "GIT_STORAGE_FILE_TYPE",
                    )
                    raw = os.pread(fd, maximum + 1, 0)
                    stamp = lambda row: (
                        row.st_dev,
                        row.st_ino,
                        row.st_mode,
                        row.st_uid,
                        row.st_gid,
                        row.st_nlink,
                        row.st_size,
                        row.st_mtime_ns,
                        row.st_ctime_ns,
                    )
                    try:
                        named = os.stat(name, dir_fd=root, follow_symlinks=False)
                    except OSError as error:
                        raise ValueError("GIT_STORAGE_CHANGED") from error
                    require(
                        len(raw) == info.st_size
                        and stamp(info) == stamp(os.fstat(fd)) == stamp(named),
                        "GIT_STORAGE_CHANGED",
                    )
                    return (raw, stamp(info)) if identity else raw
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
            locks = []

            def lock_stamp(info):
                return (
                    info.st_dev,
                    info.st_ino,
                    info.st_mode,
                    info.st_uid,
                    info.st_nlink,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                )

            def check_lock(parent, name, fd, expected):
                try:
                    named = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except OSError as error:
                    raise ValueError("GIT_REF_LOCK_CHANGED") from error
                require(
                    lock_stamp(os.fstat(fd)) == lock_stamp(named) == expected,
                    "GIT_REF_LOCK_CHANGED",
                )

            def check_lock_parent(parent):
                require(observe_storage() == topology, "GIT_STORAGE_CHANGED")
                if binding_check is not None:
                    binding_check()
                if (expected_ref_directory is not None and ref_parent is not None
                        and parent == ref_parent):
                    info = os.fstat(parent)
                    require((info.st_dev, info.st_ino) == expected_ref_directory,
                            "GIT_REF_DIRECTORY_CHANGED")
                if parent != root:
                    fresh = cls._git_directory(
                        anchors["refs/heads"],
                        target_ref.split("/")[2:-1],
                        create=False,
                        cancel=None,
                    )
                    try:
                        left, right = os.fstat(fresh), os.fstat(parent)
                        require(
                            (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino),
                            "GIT_TARGET_MOVED",
                        )
                    finally:
                        os.close(fresh)

            def lock_new(parent, name):
                require(
                    cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED"
                )
                # This RW descriptor never enters held/pass_fds. Only Native
                # owns it; Git receives neither a writable bind nor lock FD.
                fd = os.open(
                    ".", os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC, 0o400, dir_fd=parent
                )
                stack.callback(os.close, fd)
                os.fsync(fd)
                require(os.fstat(fd).st_nlink == 0, "GIT_UNNAMED_FILE_REQUIRED")
                try:
                    os.link(
                        "/proc/self/fd/" + str(fd),
                        name,
                        dst_dir_fd=parent,
                        follow_symlinks=True,
                    )
                except FileExistsError as error:
                    raise ValueError("GIT_REF_LOCKED") from error
                expected = lock_stamp(os.fstat(fd))
                require(expected[4] == 1, "GIT_REF_LOCK_CHANGED")

                def release():
                    # Never remove a substituted/pre-existing lock or mutate
                    # a directory that has left the approved target binding.
                    # Uncertain cleanup retains the lock and raises, fail-closed.
                    check_lock_parent(parent)
                    check_lock(parent, name, fd, expected)
                    os.unlink(name, dir_fd=parent)
                    os.fsync(parent)

                stack.callback(release)
                os.fsync(parent)
                locks.append((parent, name, fd, expected))

            ref_parent = None
            if isinstance(publish, tuple):
                _, target_ref, _, _ = publish
                if binding_check is not None:
                    binding_check()
                try:
                    ref_parent = hold(
                        cls._git_directory(
                            anchors["refs/heads"],
                            target_ref.split("/")[2:-1],
                            # A v3 publication names an already existing
                            # trusted ref parent. Never create directories in
                            # a replacement path before checking that binding.
                            create=expected_ref_directory is None,
                            cancel=cancel,
                        )
                    )
                except (FileExistsError, NotADirectoryError) as error:
                    raise ValueError("GIT_REF_CONFLICT") from error
                if expected_ref_directory is not None:
                    opened_parent = os.fstat(ref_parent)
                    require((opened_parent.st_dev, opened_parent.st_ino)
                            == expected_ref_directory,
                            "GIT_REF_DIRECTORY_CHANGED")
                    # Validate the pinned descriptor still names the path in
                    # the authorized repository before creating any lock file.
                    check_lock_parent(ref_parent)
                # Git's two files-backend locks serialize cooperating Git
                # writers, including pack-refs. No waiting or blind retry.
                lock_new(root, "packed-refs.lock")
            packed_snapshot = read_local(
                "packed-refs", 1048576, optional=True, identity=True
            )
            if isinstance(publish, tuple):
                requested = target_ref.encode("ascii")
                seen = set()
                peeled = False
                for index, line in enumerate(
                    (packed_snapshot[0] if packed_snapshot else b"").splitlines(
                        keepends=True
                    )
                ):
                    if index == 0 and line.startswith(b"# pack-refs with: "):
                        require(
                            re.fullmatch(rb"# pack-refs with: [a-z -]*\n", line)
                            is not None,
                            "GIT_PACKED_REFS_DENIED",
                        )
                        continue
                    if line.startswith(b"^"):
                        require(
                            peeled
                            and re.fullmatch(rb"\^[a-f0-9]{40}\n", line) is not None,
                            "GIT_PACKED_REFS_DENIED",
                        )
                        peeled = False
                        continue
                    record = re.fullmatch(
                        rb"[a-f0-9]{40} (refs/[^\x00-\x20\x7f]+)\n", line
                    )
                    require(record is not None, "GIT_PACKED_REFS_DENIED")
                    name = record[1]
                    require(
                        len(name) <= 256 and name not in seen and len(seen) < 4096,
                        "GIT_PACKED_REFS_DENIED",
                    )
                    seen.add(name)
                    peeled = True
                    require(name != requested, "GIT_REF_ALREADY_EXISTS")
                    require(
                        not name.startswith(requested + b"/")
                        and not requested.startswith(name + b"/"),
                        "GIT_REF_CONFLICT",
                    )
                ref_leaf = target_ref.rsplit("/", 1)[1]
                lock_new(ref_parent, ref_leaf + ".lock")
                try:
                    existing = os.stat(
                        ref_leaf, dir_fd=ref_parent, follow_symlinks=False
                    )
                except FileNotFoundError:
                    pass
                else:
                    require(
                        False,
                        "GIT_REF_CONFLICT"
                        if stat.S_ISDIR(existing.st_mode)
                        else "GIT_REF_ALREADY_EXISTS",
                    )

            def check_ref_transaction():
                for lock in locks:
                    check_lock(*lock)
                require(
                    read_local("packed-refs", 1048576, optional=True, identity=True)
                    == packed_snapshot,
                    "GIT_STORAGE_CHANGED",
                )
                if ref_parent is not None:
                    check_lock_parent(ref_parent)

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
            if packed_snapshot is not None:
                packed = packed_snapshot[0]
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
                *(() if shared_reader is None else ("-c", "safe.directory=/repo")),
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
            require(observe_storage() == topology, "GIT_STORAGE_CHANGED")
            if binding_check is not None:
                binding_check()
            require(cancel is None or not cancel.cancelled, "GIT_PLUMBING_CANCELLED")
            check_ref_transaction()
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
                require(
                    cls._git_publish_new(
                        ref_parent,
                        target_ref.rsplit("/", 1)[1],
                        object_id.encode() + b"\n",
                        cancel=cancel,
                        before_ref_link=before_ref_link,
                        before_ref_link_guard=before_ref_link_guard,
                        expected_parent_identity=expected_ref_directory,
                        before_ref_link_check=(
                            (lambda: check_ref_transaction())
                            if expected_ref_directory is not None else None
                        ),
                    ),
                    "GIT_REF_ALREADY_EXISTS",
                )
                output = b""
                check_ref_transaction()
            require(observe_storage() == topology, "GIT_STORAGE_CHANGED")
            return bytes(output)

    def dispatch(self, request, release_check, *, cancel=None):
        require(
            type(request) is SandboxDispatchRequest and callable(release_check),
            "LIVE_CORE_GATE_REQUIRED",
        )
        config=self.config
        binding=None
        if self.binding_policy is not None:
            binding,capture=self.binding_for_operation(SandboxOperation(request.operation_bytes).to_dict())
            config=self.revalidate_capture(capture)
            original_release=release_check
            def bound_release():
                require(self.binding_for_operation(SandboxOperation(request.operation_bytes).to_dict())
                        ==(binding,capture),'SANDBOX_OPERATION_BINDING')
                self.revalidate_capture(capture)
                require(cancel is None or not cancel.cancelled,'SANDBOX_CANCELLED')
                result=original_release()
                require(not self._closed and (cancel is None or not cancel.cancelled),
                        'SANDBOX_CANCELLED')
                return result
            release_check=bound_release
        require(not self._closed,'SANDBOX_BROKER_CLOSED')
        config.registry.validate(
            SandboxOperation(request.operation_bytes).to_dict()
        )
        p = config.profile()
        input_profile = json.loads(request.operation_bytes)['payload'].get('input_profile')
        require(p.get('input_profile') == input_profile, 'PINNED_INPUT_PROFILE_MISMATCH')
        input_limits = sandbox_contracts.sandbox_input_limits(input_profile)
        require(input_profile is None and 'input_limits' not in p
                or input_profile is not None and p.get('input_limits') == dict(input_limits),
                'PINNED_INPUT_LIMITS_MISMATCH')
        inputs = config.inputs()[
            json.loads(request.operation_bytes)["payload"]["recipe_id"]
        ]
        require(
            canonical_sha256(p) == config.profile_digest, "PINNED_PROFILE_CHANGED"
        )
        for name, pin in p["native"].items():
            path = config.root / (
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
                for key, entry in config.runtime().items()
            }
            == p["runtime"],
            "PINNED_RUNTIME_CHANGED",
        )
        for entry in config.runtime().values():
            require(
                sha(entry["snapshot"]) == entry["sha256"]
                and stat.S_IMODE(Path(entry["snapshot"]).lstat().st_mode)
                == entry["mode"],
                "PINNED_RUNTIME_CHANGED",
            )
        for name, path in inputs["files"].items():
            require(sha(path) == inputs["manifest"][name], "PINNED_INPUT_CHANGED")
        release_check()  # early check; independent second check immediately before project ACK
        run = config.root / ("run-" + request.digest)
        run.mkdir(mode=0o700, exist_ok=False)
        sync_directory(config.root)
        worker_config = {
            "runtime": config.runtime(),
            "inputs": inputs["files"],
            "limits": json.loads(request.operation_bytes)["payload"],
            "gate": str(config.root / "worker_gate"),
            "bootstrap": str(config.root / "bootstrap"),
            "setup_filter": str(config.root / "setup_filter.bpf"),
            "final_filter": str(config.root / "final_filter.bpf"),
        }
        config_path = run / "worker.json"
        config_path.write_bytes(
            json.dumps(worker_config, sort_keys=True, separators=(",", ":")).encode()
        )
        config_path.chmod(0o400)
        from runtime.providers.exact import CancellationToken
        token=cancel if cancel is not None else CancellationToken()
        self._active_cancel=token
        try:
            receipt=self._run(request,release_check,config_path,run,inputs,config=config,
                              binding=binding,cancel=token)
            if self.binding_policy is not None and not (receipt.get('cgroup_absent_after_cleanup') is True
                    and receipt.get('unit_terminal_observed') is True
                    and receipt.get('cgroup_populated_zero_directly_observed') is True):
                self._quarantined=True
            return receipt
        finally:
            self._active_cancel=None

    def _run(self, request, release_check, config_path, run, inputs, *, config, binding=None, cancel=None):
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
            "profile_digest": config.profile_digest,
            "stage": "PREPARED",
            "observations": {},
            "cleanup": [],
        }
        if binding is not None:
            receipt.update(job_config_binding_digest=binding.digest,
                           config_digest=canonical_sha256(json.loads(_config_identity(config))))
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
                for prop in _systemd_properties(json.loads(request.operation_bytes)):
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
                        == config.profile()["native"]["bootstrap"]["binary_sha256"]
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
                for target in config.profile()["runtime"]:
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
                    len(config.profile()["runtime"]) + len(inputs["files"]) + 2
                )
                receipt["observations"]["scratch_tmpfs_bytes"] = scratch
                resource_profile = json.loads(request.operation_bytes)['payload'].get('resource_profile')
                profile = config.profile()
                require(profile.get('resource_profile') == resource_profile, 'KERNEL_RESOURCE_PROFILE_MISMATCH')
                descriptor_limit = 256 if resource_profile in ('HEADLESS_RENDER_V2', 'HEADLESS_RENDER_V3') else 64
                if resource_profile in ('HEADLESS_RENDER_V2', 'HEADLESS_RENDER_V3'):
                    require(type(profile.get('descriptor_limit')) is int
                            and profile['descriptor_limit'] == descriptor_limit, 'KERNEL_DESCRIPTOR_PROFILE_MISMATCH')
                receipt['observations']['descriptor_limits_before_project_ack'] = _observe_descriptor_limits(
                    procdir, peerpidfd, expected=descriptor_limit)
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
            sync_directory(config.root)
        return receipt

    def verify(self, operation, warrant, *, request=None):
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
        config=self.config
        binding=None
        locator=request
        if self.binding_policy is not None:
            require(type(locator) is SandboxDispatchRequest,'SANDBOX_HISTORICAL_REQUEST_REQUIRED')
            binding,capture=self.binding_for_operation(inner,historical=True)
            config=self.revalidate_capture(capture)
        config.registry.validate(inner)
        inner_digest = SandboxOperation.parse(inner).digest
        candidates = []
        runs=(config.root/('run-'+locator.digest),) if locator is not None else config.root.glob('run-*')
        for run in runs:
            path = run / "receipt.json"
            if not path.exists() and not path.is_symlink():
                continue
            raw = (_private_bytes(path,self.binding_policy.trusted_root,1048576,
                       expected_root=(config.root,json.loads(capture.root_identity_bytes)))
                   if binding is not None else read_evidence_file(run, "receipt.json"))
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
        if locator is not None:
            require(request==locator,'READBACK_BINDING')
        if binding is not None:
            require(receipt.get('job_config_binding_digest')==binding.digest
                    and receipt.get('config_digest')==capture.config_digest,'READBACK_BINDING')
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
            and receipt["observations"].get("worker_populated_zero_before_readback") is True
            and receipt["observations"].get("worker_populated_zero_after_readback") is True
            and receipt["cgroup_absent_after_cleanup"]
            and receipt["unit_terminal_observed"]
            and receipt["profile_digest"] == config.profile_digest,
            "UNRESOLVED_READBACK",
        )
        expected = config.inputs()[inner["payload"]["recipe_id"]]["expected"]
        for name,pin in expected.items():
            if binding is not None:
                data=_private_bytes(run/('artifact-'+name),self.binding_policy.trusted_root,pin['bytes'],
                    expected_root=(config.root,json.loads(capture.root_identity_bytes)))
            else:
                # Preserve legacy v1 support for an empty expected artifact.
                fd=os.open(run/('artifact-'+name),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
                try:
                    meta=os.fstat(fd)
                    data=os.read(fd,pin['bytes']+1)
                    require(stat.S_ISREG(meta.st_mode) and meta.st_nlink==1,'ARTIFACT_DIGEST_MISMATCH')
                finally:
                    os.close(fd)
            require(len(data)==pin['bytes'] and hashlib.sha256(data).hexdigest()==pin['sha256'],
                    'ARTIFACT_DIGEST_MISMATCH')
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
