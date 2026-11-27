"""Descriptor-relative access to the broker's disposable SHA-1 loose repository."""

import configparser
import hashlib
import os
import re
import stat
import zlib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass

from runtime.mission.sandbox_linux import git_storage_identity, mountid
from runtime.red_hat.broker_protocol import file_identity, read_record, require


_DIRECTORY = os.O_DIRECTORY | os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
_MARKER = b"AIOA_RED_HAT_FIXTURE_V1\n"
_MAX_COMMIT = 1024 * 1024


def require_private(directory, uid):
    info = os.fstat(directory)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == uid
            and stat.S_IMODE(info.st_mode) == 0o700, "BROKER_PRIVATE_DIRECTORY")


def open_dir(parent, name, stack):
    directory = os.open(name, _DIRECTORY, dir_fd=parent)
    stack.callback(os.close, directory)
    return directory


def require_named_directory(parent, name, directory):
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    require(stat.S_ISDIR(info.st_mode)
            and file_identity(info) == file_identity(os.fstat(directory))
            and mountid(parent) == mountid(directory),
            "BROKER_DIRECTORY_MOVED")


def native_parent_name(exact_ref):
    """Only the existing Native Git plan's namespace can add a parent."""
    pieces = exact_ref.split("/")
    require(pieces[:2] == ["refs", "heads"], "RH06_REF_NOT_DIRECT")
    if len(pieces) == 3:
        return None
    require(len(pieces) == 4 and pieces[2] == "aioa"
            and re.fullmatch(r"nz11-[0-9a-f]{32}", pieces[3]), "RH06_REF_NOT_DIRECT")
    return "aioa"


def absent(parent, name):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ValueError("BROKER_REPO_PACKED_OR_LOCKED")


@dataclass(frozen=True, slots=True)
class FixtureRepository:
    root: int
    repo: int
    refs: int
    heads: int
    ref_parent: int
    topology: tuple
    uid: int
    storage: object = None
    writer: bool = False

    def check(self, request, *, publishing=False):
        for directory, parent, name in (
            (self.repo, self.root, "repo"), (self.refs, self.repo, "refs"),
            (self.heads, self.refs, "heads"),
        ):
            require_named_directory(parent, name, directory)
        name = native_parent_name(request.exact_ref)
        if name is not None:
            require_named_directory(self.heads, name, self.ref_parent)
            if self.storage is None:
                info = os.fstat(self.ref_parent)
                require(info.st_uid == self.uid and not info.st_mode & 0o7022,
                        "BROKER_REF_PARENT_UNSAFE")
        require(file_identity(os.fstat(self.repo)) == request.repository
                and file_identity(os.fstat(self.ref_parent)) == request.ref_directory,
                "BROKER_REPOSITORY_BINDING")
        marker_uid = self.uid if self.storage is None else 0
        require(self.record(self.repo, ".redhat-disposable", marker_uid) == _MARKER,
                "BROKER_DISPOSABLE_MARKER")
        self.check_config()
        absent(self.repo, "packed-refs")
        observed = (git_storage_identity(self.repo) if self.storage is None
                    else self.storage.topology(self.repo, self.ref_parent))
        require(observed == self.topology, "BROKER_REPOSITORY_MOVED")
        if publishing:
            require(self.storage is None or self.writer, "NATIVE_STORAGE_READ_ONLY")
            if self.writer:
                self.storage.require_writer(self.root)
            absent(self.repo, "packed-refs.lock")
            absent(self.ref_parent, self.leaf(request) + ".lock")

    def record(self, directory, name, uid, **kwargs):
        gid = None if self.storage is None else self.storage.reader_gid
        return read_record(directory, name, uid, reader_gid=gid, **kwargs)

    def check_config(self):
        fd = os.open("config", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=self.repo)
        try:
            info = os.fstat(fd)
            owner = self.uid if self.storage is None else 0
            require(stat.S_ISREG(info.st_mode) and info.st_uid == owner
                    and info.st_nlink == 1 and 0 < info.st_size <= 4096, "BROKER_REPO_CONFIG")
            raw = os.pread(fd, 4097, 0)
            require(len(raw) == info.st_size, "BROKER_REPO_CONFIG")
            config = configparser.ConfigParser(interpolation=None, strict=True)
            try:
                config.read_string(raw.decode("ascii"))
            except (UnicodeError, configparser.Error):
                raise ValueError("BROKER_REPO_CONFIG") from None
            require(config.sections() == ["core"] and not config.defaults()
                    and set(config["core"]) <= {"repositoryformatversion", "filemode", "bare"}
                    and config["core"].get("repositoryformatversion") == "0"
                    and config["core"].get("bare") == "true", "BROKER_REPO_CONFIG")
        finally:
            os.close(fd)

    @staticmethod
    def leaf(request):
        return request.exact_ref.rsplit("/", 1)[1]

    def check_commit(self, request):
        with ExitStack() as stack:
            objects = open_dir(self.repo, "objects", stack)
            prefix = open_dir(objects, request.new_oid[:2], stack)
            fd = os.open(request.new_oid[2:], os.O_RDONLY | os.O_NOFOLLOW
                         | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=prefix)
            stack.callback(os.close, fd)
            row = os.fstat(fd)
            require(stat.S_ISREG(row.st_mode) and row.st_uid == self.uid
                    and row.st_nlink == 1 and 0 < row.st_size <= _MAX_COMMIT,
                    "BROKER_COMMIT_OBJECT")
            packed = os.pread(fd, _MAX_COMMIT + 1, 0)
            decoder = zlib.decompressobj()
            try:
                raw = decoder.decompress(packed, _MAX_COMMIT + 1)
            except zlib.error:
                raise ValueError("BROKER_COMMIT_OBJECT") from None
            header, separator, content = raw.partition(b"\0")
            require(len(packed) == row.st_size and len(raw) <= _MAX_COMMIT
                    and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
                    and separator and header == b"commit " + str(len(content)).encode("ascii")
                    and hashlib.sha1(raw).hexdigest() == request.new_oid,
                    "BROKER_COMMIT_OBJECT")

    def observe(self, request):
        leaf = self.leaf(request)
        before = os.stat(leaf, dir_fd=self.ref_parent, follow_symlinks=False)
        raw = self.record(self.ref_parent, leaf, self.uid, maximum=41)
        after = os.stat(leaf, dir_fd=self.ref_parent, follow_symlinks=False)
        require(file_identity(before) == file_identity(after)
                and before.st_ctime_ns == after.st_ctime_ns
                and raw == request.new_oid.encode("ascii") + b"\n", "BROKER_REF_OBSERVATION")
        return (*file_identity(after), after.st_ctime_ns)


@contextmanager
def open_repository(root, request, uid, *, storage=None, role=None, writer=False):
    require(type(writer) is bool, "NATIVE_STORAGE_ROLE")
    if storage is None:
        require(role is None and writer is False, "NATIVE_STORAGE_ROLE")
        require_private(root, uid)
    else:
        from runtime.red_hat.role_storage import RoleStorage

        require((role == "broker" if writer is True else role in ("core", "verifier"))
                and type(storage) is RoleStorage and uid == storage.broker.uid
                and request.exact_ref == storage.exact_ref
                and request.repository == (storage.repository.device, storage.repository.inode)
                and request.ref_directory == (storage.ref_parent.device, storage.ref_parent.inode),
                "NATIVE_STORAGE_ORIGINAL_TARGET")
        if writer:
            storage.require_writer(root)
        else:
            storage.require_role(role)
            storage.require_anchor(root)
    with ExitStack() as stack:
        repo = open_dir(root, "repo", stack)
        refs = open_dir(repo, "refs", stack)
        heads = open_dir(refs, "heads", stack)
        name = native_parent_name(request.exact_ref)
        parent = heads if name is None else open_dir(heads, name, stack)
        topology = (git_storage_identity(repo) if storage is None
                    else storage.topology(repo, parent))
        target = FixtureRepository(root, repo, refs, heads, parent, topology, uid, storage, writer)
        target.check(request)
        yield target
