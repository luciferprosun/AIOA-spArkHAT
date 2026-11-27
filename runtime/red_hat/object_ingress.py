"""Bounded loose object import for the authenticated Native qualification broker."""

import hashlib
import os
import re
import struct
import zlib
from contextlib import ExitStack

from runtime.mission.patchset import MAX_FILE_BYTES, MAX_TREE_BYTES, MAX_TREE_ENTRIES
from runtime.mission.sandbox_linux import LinuxSandboxBroker
from runtime.red_hat.broker_protocol import require
from runtime.red_hat.fixture_repository import open_dir, require_named_directory

_HEADER = struct.Struct("!BI")
_KINDS = (b"blob", b"tree", b"commit")
_MAX_COUNT = MAX_TREE_ENTRIES + 2
MAX_BATCH_BYTES = MAX_TREE_BYTES + 2 * MAX_FILE_BYTES + _MAX_COUNT * _HEADER.size
_OID = re.compile(r"[0-9a-f]{40}")


def encode_objects(objects):
    result = bytearray()
    require(0 < len(objects) <= _MAX_COUNT, "NATIVE_OBJECT_COUNT")
    for kind, data, oid in objects:
        require(type(data) is bytes and len(data) <= MAX_FILE_BYTES
                and kind in ("blob", "tree", "commit")
                and type(oid) is str and _OID.fullmatch(oid),
                "NATIVE_OBJECT_ENTRY")
        kind = kind.encode("ascii")
        require(hashlib.sha1(_loose(kind, data)).hexdigest() == oid, "NATIVE_OBJECT_OID")
        require(len(result) + _HEADER.size + len(data) <= MAX_BATCH_BYTES, "NATIVE_OBJECT_SIZE")
        result.extend(_HEADER.pack(_KINDS.index(kind), len(data)))
        result.extend(data)
    return bytes(result)


def _loose(kind, data):
    return kind + b" " + str(len(data)).encode("ascii") + b"\0" + data


def decode_objects(raw, *, expected_commit):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BATCH_BYTES, "NATIVE_OBJECT_SIZE")
    pending = {}
    count = offset = 0
    commit = None
    while offset < len(raw):
        count += 1
        require(count <= _MAX_COUNT and offset + _HEADER.size <= len(raw), "NATIVE_OBJECT_COUNT")
        tag, size = _HEADER.unpack_from(raw, offset)
        offset += _HEADER.size
        require(tag < len(_KINDS) and size <= MAX_FILE_BYTES
                and offset + size <= len(raw), "NATIVE_OBJECT_ENTRY")
        kind = _KINDS[tag]
        data = raw[offset:offset + size]
        offset += size
        loose = _loose(kind, data)
        oid = hashlib.sha1(loose).hexdigest()
        if kind == b"commit":
            tree = data.split(b"\n", 1)[0]
            require(commit is None and offset == len(raw) and oid == expected_commit
                    and re.fullmatch(rb"tree [0-9a-f]{40}", tree), "NATIVE_OBJECT_COMMIT")
            commit = tree[5:].decode("ascii")
        require(pending.setdefault(oid, (kind, data)) == (kind, data), "NATIVE_OBJECT_COLLISION")
    require(commit is not None, "NATIVE_OBJECT_COMMIT")
    visited = {expected_commit}
    work = [(commit, b"tree")]
    entries = 0
    while work:
        oid, kind = work.pop()
        require(oid in pending and pending[oid][0] == kind, "NATIVE_OBJECT_GRAPH")
        if oid in visited:
            continue
        visited.add(oid)
        if kind == b"tree":
            for link in _tree_links(pending[oid][1]):
                entries += 1
                require(entries <= MAX_TREE_ENTRIES, "NATIVE_OBJECT_TREE")
                work.append(link)
    require(visited == pending.keys(), "NATIVE_OBJECT_GRAPH")
    return tuple((oid, _loose(kind, data)) for oid, (kind, data) in pending.items())


def _tree_links(raw):
    offset = 0
    previous = b""
    names = set()
    while offset < len(raw):
        nul = raw.find(b"\0", offset)
        require(nul >= 0 and nul + 21 <= len(raw), "NATIVE_OBJECT_TREE")
        mode, _, leaf = raw[offset:nul].partition(b" ")
        require(mode in (b"40000", b"100644") and leaf.lower() not in (b"", b".", b"..", b".git")
                and b"/" not in leaf and b"\\" not in leaf, "NATIVE_OBJECT_TREE")
        key = leaf + (b"/" if mode == b"40000" else b"\0")
        require(key > previous and leaf not in names, "NATIVE_OBJECT_TREE")
        names.add(leaf)
        previous = key
        yield raw[nul + 1:nul + 21].hex(), b"tree" if mode == b"40000" else b"blob"
        offset = nul + 21


def import_objects(repo, uid, objects):
    """Create-only import below objects/. No ref, config, alternates, or subprocess."""
    with ExitStack() as stack:
        root = open_dir(repo, "objects", stack)
        _require_object_dir(root, uid)
        require_named_directory(repo, "objects", root)
        for oid, loose in objects:
            _import_object(repo, root, uid, oid, loose)
        os.fsync(root)
        require_named_directory(repo, "objects", root)


def _require_object_dir(fd, uid):
    info = os.fstat(fd)
    require(info.st_uid == uid and not info.st_mode & 0o7022, "NATIVE_OBJECT_DIRECTORY")


def _import_object(repo, root, uid, oid, loose):
    require(type(oid) is str and _OID.fullmatch(oid) and type(loose) is bytes
            and hashlib.sha1(loose).hexdigest() == oid, "NATIVE_OBJECT_OID")
    prefix_name, name = oid[:2], oid[2:]
    try:
        os.mkdir(prefix_name, 0o700, dir_fd=root)
    except FileExistsError:
        pass
    with ExitStack() as stack:
        prefix = open_dir(root, prefix_name, stack)
        _require_object_dir(prefix, uid)
        require_named_directory(root, prefix_name, prefix)
        def check_prefix():
            require_named_directory(repo, "objects", root)
            require_named_directory(root, prefix_name, prefix)

        published = LinuxSandboxBroker._git_publish_new(
            prefix, name, zlib.compress(loose), cancel=None, before_ref_link_check=check_prefix,
        )
        if not published:
            try:
                LinuxSandboxBroker._git_existing_object(prefix, name, loose, sync=True)
            except zlib.error:
                raise ValueError("NATIVE_OBJECT_EXISTING") from None
            os.fsync(prefix)
