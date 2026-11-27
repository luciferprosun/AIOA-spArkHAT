"""Pinned descriptor views for the disposable Native role split."""

import ctypes
import hashlib
import os
import re
import stat
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from runtime.mission.sandbox_linux import _scan_git_storage, mountid
from runtime.red_hat.broker_protocol import digest, file_identity, read_record, require

_ID_LIMIT = 2**32 - 1
_REF = re.compile(r"refs/heads/aioa/nz11-[0-9a-f]{32}")


def _positive(value, upper=2**63):
    return type(value) is int and 0 < value < upper


@dataclass(frozen=True, slots=True)
class StorageActor:
    uid: int
    gid: int
    apparmor: str
    cgroup: str

    def __post_init__(self):
        require(_positive(self.uid, _ID_LIMIT) and _positive(self.gid, _ID_LIMIT)
                and type(self.apparmor) is str
                and re.fullmatch(r"[A-Za-z0-9_./:-]+ \(enforce\)", self.apparmor)
                and self.apparmor != "unconfined (enforce)"
                and type(self.cgroup) is str
                and re.fullmatch(r"0::/(?:[A-Za-z0-9_.@:-]+/)*[A-Za-z0-9_.@:-]+", self.cgroup),
                "NATIVE_STORAGE_ACTOR")

    def require_process(self, reader_gid):
        require(os.getresuid() == (self.uid,) * 3
                and os.getresgid() == (self.gid,) * 3
                and set(os.getgroups()) == {reader_gid}, "NATIVE_STORAGE_ROLE")
        status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
        require(status["NoNewPrivs"].strip() == "1"
                and all(int(status[field], 16) == 0 for field in ("CapEff", "CapPrm", "CapAmb", "CapInh", "CapBnd"))
                and ctypes.CDLL(None).prctl(3, 0, 0, 0, 0) == 0
                and Path("/proc/self/attr/current").read_text().strip() == self.apparmor
                and Path("/proc/self/cgroup").read_text().strip() == self.cgroup,
                "NATIVE_STORAGE_ROLE_CONFINEMENT")


@dataclass(frozen=True, slots=True)
class DirectoryPin:
    device: int
    inode: int
    mount: int

    def __post_init__(self):
        require(all(_positive(value) for value in (self.device, self.inode, self.mount)),
                "NATIVE_STORAGE_DIRECTORY_PIN")

    def require_fd(self, fd):
        info = os.fstat(fd)
        require(stat.S_ISDIR(info.st_mode)
                and file_identity(info) == (self.device, self.inode)
                and mountid(fd) == self.mount, "NATIVE_STORAGE_DIRECTORY_MOVED")
        return info


@dataclass(frozen=True, slots=True)
class RoleStorage:
    """Operator configuration for one mount namespace and one create-only ref.

    Only a trusted launcher may supply this value. A label check identifies
    the enforcing domain; it does not authenticate the installed policy text.
    """

    core: StorageActor
    broker: StorageActor
    verifier: StorageActor
    reader_gid: int
    mount_namespace: int
    exact_ref: str
    anchor: DirectoryPin
    repository: DirectoryPin
    ref_parent: DirectoryPin
    evidence: DirectoryPin
    staging: DirectoryPin | None = None
    policy_sha256: str | None = None
    state: DirectoryPin | None = None

    def __post_init__(self):
        actors = (self.core, self.broker, self.verifier)
        pins = (self.anchor, self.repository, self.ref_parent, self.evidence)
        if self.staging is not None:
            pins += (self.staging, self.state)
        require((self.staging is None and self.policy_sha256 is None and self.state is None)
                or (type(self.staging) is DirectoryPin and type(self.state) is DirectoryPin
                    and type(self.policy_sha256) is str
                    and re.fullmatch(r"[0-9a-f]{64}", self.policy_sha256)),
                "NATIVE_STORAGE_WRITER_PINS")
        require(all(type(actor) is StorageActor for actor in actors)
                and len({actor.uid for actor in actors}) == 3
                and len({actor.gid for actor in actors}) == 3
                and len({actor.apparmor for actor in actors}) == 3
                and len({actor.cgroup for actor in actors}) == 3
                and _positive(self.reader_gid, _ID_LIMIT)
                and self.reader_gid not in {actor.gid for actor in actors}
                and _positive(self.mount_namespace)
                and type(self.exact_ref) is str and _REF.fullmatch(self.exact_ref)
                and all(type(pin) is DirectoryPin for pin in pins)
                and len({(pin.device, pin.mount) for pin in pins}) == 1
                and len({pin.inode for pin in pins}) == len(pins), "NATIVE_STORAGE_CONTRACT")

    @classmethod
    def from_dict(cls, value):
        require(type(value) is dict
                and set(value) == {"schema", *(field.name for field in fields(cls))}
                and value["schema"] == "aioa.redhat.role-storage.v1", "NATIVE_STORAGE_SCHEMA")
        decoded = {key: item for key, item in value.items() if key != "schema"}
        for names, kind in ((("core", "broker", "verifier"), StorageActor),
                            (("anchor", "repository", "ref_parent", "evidence", "staging", "state"), DirectoryPin)):
            keys = {field.name for field in fields(kind)}
            for name in names:
                item = value[name]
                if name in ("staging", "state") and item is None:
                    continue
                require(type(item) is dict and set(item) == keys, "NATIVE_STORAGE_SCHEMA")
                decoded[name] = kind(**item)
        return cls(**decoded)

    def to_dict(self):
        return {"schema": "aioa.redhat.role-storage.v1", **asdict(self)}

    @property
    def digest(self):
        return digest(self.to_dict())

    def require_role(self, role):
        require(role in ("core", "broker", "verifier")
                and os.stat("/proc/self/ns/mnt").st_ino == self.mount_namespace,
                "NATIVE_STORAGE_MOUNT_NAMESPACE")
        getattr(self, role).require_process(self.reader_gid)

    def require_anchor(self, fd):
        self._require_access(self.anchor.require_fd(fd), owner=0, mode=0o750)

    def require_writer(self, root_fd):
        """Recheck the writer policy input supplied by the trusted operator."""
        require(self.staging is not None, "NATIVE_STORAGE_WRITER_PINS")
        self.require_role("broker")
        self.require_anchor(root_fd)
        path = os.readlink(f"/proc/self/fd/{root_fd}")
        require(re.fullmatch(r"/run/aioa-qualification/[0-9a-f]{32}", path),
                "NATIVE_STORAGE_DISPOSABLE_ROOT")
        parent = Path(path).parent
        for directory in (parent, *parent.parents):
            info = directory.lstat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
                    and not info.st_mode & 0o022, "NATIVE_STORAGE_DISPOSABLE_ROOT")
        current = os.stat(path, follow_symlinks=False)
        require(stat.S_ISDIR(current.st_mode) and file_identity(current) == file_identity(os.fstat(root_fd)),
                "NATIVE_STORAGE_DISPOSABLE_ROOT")
        raw = read_record(root_fd, "writer-policy", 0, maximum=65536, reader_gid=self.reader_gid)
        require(hashlib.sha256(raw).hexdigest() == self.policy_sha256, "NATIVE_STORAGE_WRITER_POLICY")

    def require_staging(self, fd):
        require(self.staging is not None, "NATIVE_STORAGE_WRITER_PINS")
        self._require_access(self.staging.require_fd(fd), owner=self.broker.uid, mode=0o2700)

    def require_state(self, fd):
        require(self.state is not None, "NATIVE_STORAGE_WRITER_PINS")
        info = self.state.require_fd(fd)
        require(info.st_uid == self.broker.uid and info.st_gid == self.broker.gid
                and stat.S_IMODE(info.st_mode) == 0o700, "NATIVE_STORAGE_STATE")

    def require_evidence(self, fd):
        self._require_access(self.evidence.require_fd(fd), owner=self.broker.uid, mode=0o2750)

    def _require_access(self, info, *, owner, mode):
        require(info.st_uid == owner and info.st_gid == self.reader_gid
                and stat.S_IMODE(info.st_mode) == mode, "NATIVE_STORAGE_ACCESS")

    def entry_matches(self, name, info):
        directory = stat.S_ISDIR(info.st_mode)
        ref_parent = self.exact_ref.rsplit("/", 1)[0]
        oid_prefix = re.fullmatch(r"objects/[0-9a-f]{2}", name)
        loose_oid = re.fullmatch(r"objects/[0-9a-f]{2}/[0-9a-f]{38}", name)
        writable = (
            name in ("objects", ref_parent) or bool(oid_prefix)
            if directory else bool(loose_oid) or name == self.exact_ref
        )
        owner = self.broker.uid if writable else 0
        mode = (0o2750 if writable else 0o750) if directory else 0o440
        if name in ("packed-refs", "packed-refs.lock") or name.endswith(".lock"):
            return False
        return (info.st_uid == owner and info.st_gid == self.reader_gid
                and stat.S_IMODE(info.st_mode) == mode)

    def topology(self, repository, ref_parent):
        self.repository.require_fd(repository)
        info = self.ref_parent.require_fd(ref_parent)
        self._require_access(info, owner=self.broker.uid, mode=0o2750)
        return _scan_git_storage(repository, self.entry_matches)
