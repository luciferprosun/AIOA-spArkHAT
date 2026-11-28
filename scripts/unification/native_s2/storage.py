"""Controller-side fenced raw volume. The guest only receives a virtual disk."""

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
from contextlib import closing, contextmanager
from pathlib import Path


class Fenced(ValueError):
    pass


def _check(condition, reason):
    if not condition:
        raise Fenced(reason)


def _private_root(root):
    root = Path(root).resolve(strict=True)
    info = root.stat()
    _check(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, "S2_CONTROLLER_DIRECTORY")
    return root


def _disk(fd):
    row = os.fstat(fd)
    _check(stat.S_ISREG(row.st_mode) and row.st_uid == os.geteuid() and row.st_nlink == 1
           and stat.S_IMODE(row.st_mode) == 0o600 and row.st_size >= 4096 and row.st_size % 512 == 0,
           "S2_RAW_VOLUME")
    return row.st_dev, row.st_ino, row.st_size


@contextmanager
def _transaction(root):
    # mode=rw prevents a lost controller database from becoming a fresh generation zero.
    root = _private_root(root)
    path = root / "controller.sqlite3"
    info = path.lstat()
    _check(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
           and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1, "S2_CONTROLLER_DATABASE")
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10, isolation_level=None)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=EXTRA")
        _check(db.execute("PRAGMA journal_mode").fetchone()[0] == "delete", "S2_CONTROLLER_DURABILITY")
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.execute("COMMIT")


def initialize(root, volume):
    """Register exactly one pre-provisioned private disk.raw. Never initialize on attach."""
    root = _private_root(root)
    _check(re.fullmatch(r"[0-9a-f]{64}", volume), "S2_VOLUME_ID")
    fd = os.open(root / "disk.raw", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        device, inode, size = _disk(fd)
        # This host inode is never part of a guest snapshot. A lost controller
        # catalogue cannot be silently re-initialized against an enrolled disk.
        os.setxattr(fd, "user.aioa.native69.volume", volume.encode("ascii"), flags=os.XATTR_CREATE)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.close(os.open(root / "controller.sqlite3", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600))
    with _transaction(root) as db:
        db.execute("""CREATE TABLE volume (
            id INTEGER PRIMARY KEY CHECK (id = 1), volume TEXT NOT NULL,
            device INTEGER NOT NULL, inode INTEGER NOT NULL, size INTEGER NOT NULL,
            generation INTEGER NOT NULL, token_hash TEXT, attached INTEGER NOT NULL,
            boot TEXT, storage TEXT, ref TEXT, binding TEXT, faulted INTEGER NOT NULL, posture TEXT NOT NULL)""")
        db.execute("""CREATE TABLE retired (generation INTEGER PRIMARY KEY, boot TEXT,
                      storage TEXT, ref TEXT, binding TEXT, faulted INTEGER NOT NULL, posture TEXT NOT NULL)""")
        db.execute("INSERT INTO volume VALUES(1, ?, ?, ?, ?, 0, NULL, 0, NULL, NULL, NULL, NULL, 0, 'UNATTACHED')",
                   (volume, device, inode, size))
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _row(db, volume, generation):
    row = db.execute("SELECT * FROM volume WHERE id=1").fetchone()
    _check(row is not None and row["volume"] == volume and type(generation) is int
           and row["generation"] == generation, "S2_GENERATION_FENCED")
    return row


def advance(root, volume, predecessor, *, cold_read=False):
    """Serialize every block request and succession under the same off-volume transaction."""
    root = _private_root(root)
    _check(type(cold_read) is bool, "S2_GENERATION_POSTURE")
    with _transaction(root) as db:
        row = _row(db, volume, predecessor)
        fd = os.open(root / "disk.raw", os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            _check(_disk(fd) == (row["device"], row["inode"], row["size"]), "S2_DISK_REPLACED")
            os.fsync(fd)
        finally:
            os.close(fd)
        _check(0 <= predecessor < 2**63 - 1, "S2_GENERATION_EXHAUSTED")
        token = secrets.token_hex(32)
        key = hashlib.sha256(token.encode("ascii")).hexdigest()
        db.execute("""INSERT INTO retired SELECT generation, boot, storage, ref, binding, faulted, posture
                      FROM volume WHERE id=1""")
        db.execute("""UPDATE volume SET generation=?, token_hash=?, attached=0,
                      boot=NULL, storage=NULL, ref=NULL, binding=NULL, faulted=0, posture=? WHERE id=1""",
                   (predecessor + 1, key, "COLD_READ" if cold_read else "WRITER"))
    return f"{volume}/{predecessor + 1}/{token}"


def check_attached(root, volume, export):
    parts = export.split("/")
    _check(len(parts) == 3 and parts[0] == volume and re.fullmatch("[1-9][0-9]{0,18}", parts[1])
           and re.fullmatch("[a-f0-9]{64}", parts[2]), "S2_DOMAIN_EXPORT")
    with _transaction(root) as db:
        row = _row(db, volume, int(parts[1]))
        _check(row["attached"] == 1 and not row["faulted"]
               and hmac.compare_digest(row["token_hash"], hashlib.sha256(parts[2].encode("ascii")).hexdigest()),
               "S2_DOMAIN_ATTACHMENT")


def arm(root, volume, generation, boot, storage, ref, binding):
    """The controller authorizes one independently checked START before the broker's final release."""
    _check(all(type(v) is str and re.fullmatch(r"[a-f0-9]{64}", v) for v in (boot, storage, binding))
           and re.fullmatch(r"refs/heads/aioa/nz11-[a-f0-9]{32}", ref), "S2_WRITER_SCOPE")
    with _transaction(root) as db:
        row = _row(db, volume, generation)
        _check(row["posture"] == "WRITER" and row["attached"] == 1 and not row["faulted"] and row["binding"] is None, "S2_ALREADY_ARMED_OR_DETACHED")
        db.execute("UPDATE volume SET boot=?, storage=?, ref=?, binding=? WHERE id=1", (boot, storage, ref, binding))


def writer_readback(root, query, signer):
    """Answer only a live, pre-approved writer query. Never sign cold succession here."""
    from runtime.red_hat.s2_admission import WRITER_SCHEMA

    fields = {"schema", "volume_sha256", "generation", "boot_sha256", "storage_sha256",
              "exact_ref", "binding_sha256", "challenge"}
    _check(type(query) is dict and set(query) == fields and query["schema"] == WRITER_SCHEMA
           and type(query["challenge"]) is str and re.fullmatch("[a-f0-9]{64}", query["challenge"]),
           "S2_WRITER_QUERY")
    with _transaction(root) as db:
        row = _row(db, query["volume_sha256"], query["generation"])
        _check(row["posture"] == "WRITER" and row["attached"] == 1 and not row["faulted"] and row["binding"] is not None and
               (row["boot"], row["storage"], row["ref"], row["binding"]) ==
               (query["boot_sha256"], query["storage_sha256"], query["exact_ref"], query["binding_sha256"]),
               "S2_WRITER_NOT_ARMED")
        return {"payload": query, "signature": signer.sign(query)}


class Export:
    """One consumed NBD attachment. Check generation inside each actual data operation."""

    def __init__(self, root, export_name):
        self.root = _private_root(root)
        match = re.fullmatch(r"([a-f0-9]{64})/([1-9][0-9]{0,18})/([a-f0-9]{64})", export_name)
        _check(match, "S2_EXPORT_CREDENTIAL")
        self.volume, digits, token = match.groups()
        self.generation = int(digits)
        self.token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        self.fd = os.open(self.root / "disk.raw", os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            with _transaction(self.root) as db:
                row = _row(db, self.volume, self.generation)
                _check(row["attached"] == 0 and hmac.compare_digest(self.token_hash, row["token_hash"]), "S2_ATTACH_REFUSED")
                _check(_disk(self.fd) == (row["device"], row["inode"], row["size"]), "S2_DISK_REPLACED")
                self.size = row["size"]
                db.execute("UPDATE volume SET attached=1 WHERE id=1")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _bounds(self, offset, size):
        _check(type(offset) is int and type(size) is int and 0 <= offset <= self.size
               and 0 <= size <= self.size - offset, "S2_IO_BOUNDS")

    @contextmanager
    def _operation(self):
        failure = None
        with _transaction(self.root) as db:
            row = _row(db, self.volume, self.generation)
            _check(row["attached"] == 1 and hmac.compare_digest(self.token_hash, row["token_hash"]),
                   "S2_GENERATION_FENCED")
            _check(not row["faulted"], "S2_VOLUME_IO_UNCERTAIN")
            try:
                yield
            except (OSError, Fenced) as error:
                db.execute("UPDATE volume SET faulted=1 WHERE id=1")
                failure = error
        if failure is not None:
            raise failure

    def read(self, size, offset):
        self._bounds(offset, size)
        with self._operation():
            data = os.pread(self.fd, size, offset)
            _check(len(data) == size, "S2_SHORT_READ")
            return data

    def write(self, data, offset):
        self._bounds(offset, len(data))
        with self._operation():
            _check(os.pwrite(self.fd, data, offset) == len(data), "S2_SHORT_WRITE")
            # Deliberately write-through for this qualification profile, including FUA.
            os.fsync(self.fd)

    def flush(self):
        with self._operation():
            os.fsync(self.fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--volume", required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("initialize")
    rotate = sub.add_parser("advance")
    rotate.add_argument("--cold-read", action="store_true")
    rotate.add_argument("--from-generation", required=True, type=int)
    rotate.add_argument("--credential-output", type=Path, required=True)
    approve = sub.add_parser("arm")
    approve.add_argument("--generation", required=True, type=int)
    for field in ("boot", "storage", "ref", "binding"):
        approve.add_argument("--" + field, required=True)
    args = parser.parse_args(argv)
    if args.action == "initialize":
        initialize(args.root, args.volume)
    elif args.action == "advance":
        with os.fdopen(os.open(args.credential_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
            out.write(advance(args.root, args.volume, args.from_generation, cold_read=args.cold_read) + "\n")
            out.flush()
            os.fsync(out.fileno())
    else:
        arm(args.root, args.volume, args.generation, args.boot, args.storage, args.ref, args.binding)
    print(json.dumps({"completed": args.action, "volume": args.volume}))


if __name__ == "__main__":
    main()
