"""Closed v1 web profile for local observations of the existing Core."""

from contextlib import ExitStack, contextmanager
from enum import Enum
import fcntl
import json
import os
from pathlib import Path
import stat

from providers.exact import _unique_object
from runtime.core_admission import Capability, CoreAdmission, LocalOwnerAssignment, OwnerScope


BASE_SHA = "c43a269afcd5cd6e49b934a297d7ae7ccaf2d9e9"
BASE_TREE = "fe27e1b8736c911337e7009cadf16861bdc7dde9"
LOOPBACK = "127.0.0.1"
ROUTES = frozenset(("/api/bounded/status", "/api/bounded/worker",
                    "/api/bounded/continuation", "/api/bounded/license"))
_HTTP_HEADERS = frozenset((
    "host", "origin", "user-agent", "accept", "accept-encoding", "connection",
    "content-length", "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-user",
))
_LICENSE_SHA256 = "a039f83d1d59d97624c355653e0eab74a45b867a091d3d10d12ac1183535e14c"
_ASSIGNMENT = LocalOwnerAssignment(
    OwnerScope("offline-fixture", "offline-operator", "bounded-core", "inspection"),
    frozenset({Capability.READ}), frozenset({"offline-fixture"}),
    frozenset({"mock-fixture"}), operator_approved=True,
)


class BoundedCoreProfile(Enum):
    V1 = "aioa-core-bounded-v1"

    @classmethod
    def load(cls, path):
        """An exact data manifest selects the built-in profile."""
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o022 or info.st_size > 4096):
                    raise ValueError
                raw = stream.read(4097)
            if len(raw) > 4096 or json.loads(raw, object_pairs_hook=_unique_object) != {
                "schema": cls.V1.value,
                "base_sha": BASE_SHA,
                "base_tree": BASE_TREE,
                "mode": "OFFLINE_FIXTURE",
                "capabilities": ["inspection", "worker-fixture", "task-continuation", "mcp-read"],
            }:
                raise ValueError
        except (OSError, ValueError, RecursionError):
            raise ValueError("BOUNDED_PROFILE_DENIED") from None
        return cls.V1


def _check_lock(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size != 0):
        raise ValueError("BOUNDED_STATE_DENIED")


@contextmanager
def bounded_state(path):
    """Hold the usual runtime lease in a dedicated directory with no history."""
    if not path:
        raise ValueError("BOUNDED_STATE_DENIED")
    root = Path(path).absolute()
    with ExitStack() as handles:
        try:
            if root.resolve(strict=True) != root:
                raise ValueError("BOUNDED_STATE_DENIED")
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            handles.callback(os.close, directory)
            info = os.fstat(directory)
            contents = set(os.listdir(directory))
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or contents - {"runtime.lock"}:
                raise ValueError("BOUNDED_STATE_DENIED")
            if contents:
                _check_lock(os.stat("runtime.lock", dir_fd=directory, follow_symlinks=False))
            fd = os.open("runtime.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                         0o600, dir_fd=directory)
            handles.callback(os.close, fd)
            _check_lock(os.fstat(fd))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("META_RUNTIME_ALREADY_ACTIVE") from None
            named_lock = os.stat("runtime.lock", dir_fd=directory, follow_symlinks=False)
            if (not os.path.samestat(os.fstat(fd), named_lock)
                    or not os.path.samestat(info, root.lstat())
                    or set(os.listdir(directory)) != {"runtime.lock"}):
                raise ValueError("BOUNDED_STATE_DENIED")
        except (OSError, RuntimeError):
            raise ValueError("BOUNDED_STATE_DENIED") from None
        yield


def allows_request(method, target, headers):
    return (method == "GET" and target in ROUTES
            and not headers.defects
            and all(name.lower() in _HTTP_HEADERS for name in headers)
            and headers.get_all("Content-Length", []) in ([], ["0"]))


def _mock_dispatch(_payload, _cancel, _timeout):
    """Fixture transport has no caller-selected model or network client."""
    raise ValueError("BOUNDED_MODEL_DISPATCH_DENIED")


def _license_fixture():
    from runtime.mcp_bridge.adapter import build_task
    from runtime.mcp_bridge.policy import PolicyEffect, evaluate_task
    from runtime.mcp_bridge.read_ops import bounded_public_license

    task = build_task("fs.read", {"path": "LICENSE"}, task_id="bounded-license", source="bounded-core")
    if evaluate_task(task).effect is not PolicyEffect.ALLOW:
        raise ValueError("BOUNDED_LICENSE_DENIED")
    root = Path(__file__).resolve().parents[1]
    if not os.path.lexists(root / "LICENSE"):
        distributions = tuple(root.glob("aioa_sparkhat-*.dist-info"))
        if len(distributions) != 1:
            raise ValueError("BOUNDED_LICENSE_DENIED")
        dist, = distributions
        locations = [path for path in (dist, dist / "licenses") if os.path.lexists(path / "LICENSE")]
        if len(locations) != 1:
            raise ValueError("BOUNDED_LICENSE_DENIED")
        root, = locations
    try:
        evidence = bounded_public_license(root)
    except (OSError, ValueError):
        raise ValueError("BOUNDED_LICENSE_DENIED") from None
    if evidence["sha256"] != _LICENSE_SHA256:
        raise ValueError("BOUNDED_LICENSE_DENIED")
    return evidence


def _worker_fixture():
    from runtime.mission.worker import CandidateFile, CandidatePatch, SyntheticWorker, Task

    task = Task("bounded-task", "bounded-run", "fixture-workspace", "fixture-repository",
                BASE_SHA, "Suggest a fixture change.", 120, max_events=3)
    patch = CandidatePatch((CandidateFile("sample.py", "value = 1\n"),))
    worker = SyntheticWorker((patch,), clock=lambda: 100)
    try:
        session = worker.start(task)
        events = worker.poll(session)
        result = worker.result(session)
        return {"events": [event.kind for event in events], "authority": result.authority,
                "verified": result.verified}
    finally:
        worker.close()


def _continuation_fixture():
    from runtime.tools.task_continuation import (
        MANIFEST_SCHEMA, build_resume_summary, select_next_local_task,
    )

    manifest = {"schema": MANIFEST_SCHEMA, "base_sha": BASE_SHA,
                "tasks": [{"task_id": "inspect-fixture", "scope": "LOCAL_OFFLINE",
                           "status": "READY", "dependencies": [], "evidence_refs": []}]}
    decision = select_next_local_task(manifest, expected_base_sha=BASE_SHA)
    return json.loads(build_resume_summary(manifest, decision, expected_base_sha=BASE_SHA))


class BoundedInspection:
    """Bind one AgentRuntime to a READ-only fixture scope."""

    def __init__(self, profile):
        from main import create_runtime
        from runtime.providers.config import ProviderManager
        from runtime.providers.meta_model_api import MetaModelProvider

        if profile is not BoundedCoreProfile.V1:
            raise ValueError("BOUNDED_PROFILE_DENIED")
        self.profile = profile
        self._license = _license_fixture()
        self.manager = ProviderManager(Path(__file__).resolve().parents[1], meta_only=True)
        self.manager.configure_meta(MetaModelProvider(mode="MOCK", transport=_mock_dispatch))
        self.core = CoreAdmission(_ASSIGNMENT)
        self.runtime = create_runtime(inspection_only=True, borrowed_admission=self.core)
        self.runtime.provider_manager = self.manager

    def require_read(self, runtime):
        from main import AgentRuntime
        from runtime.providers.config import ProviderManager
        from runtime.providers.meta_model_api import MetaModelProvider

        if (type(runtime) is not AgentRuntime or runtime is not self.runtime
                or runtime._inspection_only is not True or runtime._agent_closed
                or runtime._memory_patch_admission is not self.core
                or type(self.core) is not CoreAdmission or self.core._assignment is not _ASSIGNMENT
                or any(getattr(runtime, name, None) is not None for name in (
                    "executor", "_agent_bindings", "_coding_tasks", "_mission_bindings",
                    "_lite_scheduler", "_cpl_service", "cpl_cost_policy", "_nonzero_service",
                    "_memory_patch_service", "native_access",
                ))
                or any(getattr(self, name, None) is not None for name in (
                    "foundation", "github_write_route", "mobile",
                ))
                or runtime.provider_manager is not self.manager
                or type(self.manager) is not ProviderManager or self.manager._meta_only is not True
                or self.manager.provider is not None or self.manager.fixture_base_url is not None):
            raise ValueError("BOUNDED_BINDING_DENIED")
        provider = self.manager._meta_provider
        if (type(provider) is not MetaModelProvider or provider.mode != "MOCK"
                or provider.transport is not _mock_dispatch or provider.receipt_view is not None):
            raise ValueError("BOUNDED_BINDING_DENIED")
        self.core.require(self.core.local_operator(Capability.READ), Capability.READ,
                          scope=_ASSIGNMENT.scope)

    def source_view(self):
        return {"profile": self.profile.value, "base_sha": BASE_SHA, "base_tree": BASE_TREE}

    def read(self, path):
        if path == "/api/bounded/status":
            return {**self.source_view(), "provider": "MOCK", "core": "BOUND_OFFLINE_FIXTURE",
                    "effect_authority": "NONE", "live_verified": False}
        if path == "/api/bounded/worker":
            return _worker_fixture()
        if path == "/api/bounded/continuation":
            return _continuation_fixture()
        if path == "/api/bounded/license":
            return dict(self._license)
        raise ValueError("BOUNDED_ROUTE_DENIED")

    def close(self):
        try:
            self.runtime.close()
        finally:
            self.core.close()
