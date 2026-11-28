"""Install and measure the Native S1 operator kit on an approved Noble guest."""

import hashlib
import json
import os
import platform
import re
import stat
import subprocess
from pathlib import Path

from scripts.unification import noble_preflight as preflight
from scripts.unification.native_role_supervisor import installed_tree, trusted

SOURCE = preflight.SOURCE
CONFIG = Path("/etc/aioa-native-s1")
INSTALL = Path("/usr/local/libexec/aioa-native-s1")
BASE = Path("/run/aioa-qualification")
UNIT = Path("/etc/systemd/system/aioa-native-s1-cgroup@.service")
S1_SCHEMA = "aioa.native-s1.operator.v2"
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent",
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0",
       "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1"}
require = preflight.require


def run(command, *, data=None, timeout=15):
    proc = subprocess.run(command, env=ENV, input=data, capture_output=True, check=False, timeout=timeout)
    if proc.returncode:
        raise ValueError(f"NATIVE_S1_TOOL:{Path(command[0]).name}:{proc.returncode}")
    return proc.stdout


def write_new(path, raw, *, mode=0o600, uid=0, gid=0):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode), "wb") as stream:
        os.fchown(stream.fileno(), uid, gid)
        os.fchmod(stream.fileno(), mode)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def management_receipt(*, image, boot, signed_packages, output):
    """Encode evidence supplied by the external management plane, never probe this host."""
    require(all(preflight.SHA256.fullmatch(value) for value in (image, boot, signed_packages)),
            "NATIVE_S1_MANAGEMENT_PROVENANCE")
    raw = canonical({"schema": "aioa.disposable-host-receipt.v1", "disposable": True,
                     "image_sha256": image, "boot_sha256": boot, "signed_package_manifest_sha256": signed_packages})
    with output.open("xb") as handle:
        handle.write(raw)
    return sha(raw)


def manifest(*, source, tree, kernel, receipt, runtime_digest, wheels_digest, core_uid, output):
    require(preflight.SHA1.fullmatch(source) and preflight.SHA1.fullmatch(tree)
            and preflight.SHA256.fullmatch(runtime_digest) and preflight.SHA256.fullmatch(wheels_digest)
            and 0 < core_uid < 2**31,
            "NATIVE_S1_MANIFEST_PROVENANCE")
    raw = receipt.read_bytes()
    approved = json.loads(raw)
    required = ("image_sha256", "boot_sha256", "signed_package_manifest_sha256")
    require(set(approved) == {"schema", "disposable", *required}
            and approved["schema"] == "aioa.disposable-host-receipt.v1" and approved["disposable"] is True
            and all(preflight.SHA256.fullmatch(approved[k]) for k in required), "NATIVE_S1_MANAGEMENT_PROVENANCE")
    value = {"schema": "aioa.noble-operator-pins.v1",
             "host": {"source": source, "tree": tree, "kernel": kernel,
                      "management_receipt_sha256": sha(raw), **{name: approved[name] for name in required}},
             "s1": {"schema": S1_SCHEMA, "core_uid": core_uid, "runtime_sha256": runtime_digest,
                    "wheels_lock_sha256": wheels_digest}}
    raw = canonical(value)
    with output.open("xb") as handle:
        handle.write(raw)
    return sha(raw)


def host_release():
    value = platform.freedesktop_os_release()
    require((value.get("ID"), value.get("VERSION_ID"), value.get("VERSION_CODENAME"), platform.machine())
            == ("ubuntu", "24.04", "noble", "x86_64"), "UBUNTU_24_04_NOBLE")


def host_pins(path, digest, receipt, *, system=False):
    observed = preflight.observe()
    gaps = preflight.host_gaps(observed, system_service=system)
    if system:
        gaps = [gap for gap in gaps if gap != "UNPRIVILEGED_ROLE"]
    require(not gaps, "BLOCKED_HOST:" + ",".join(gaps))
    value = preflight.pinned_json(path, digest)
    require(type(value) is dict and set(value) == {"schema", "host", "s1"}, "NATIVE_S1_MANIFEST")
    spec = value["s1"]
    require(type(spec) is dict and set(spec) == {"schema", "core_uid", "runtime_sha256", "wheels_lock_sha256"}
            and spec["schema"] == S1_SCHEMA and type(spec["core_uid"]) is int and 0 < spec["core_uid"] < 2**31
            and all(preflight.SHA256.fullmatch(spec[name]) for name in ("runtime_sha256", "wheels_lock_sha256")),
            "NATIVE_S1_MANIFEST")
    preflight.compare_manifest(value, observed, receipt)
    return value, observed


def runtime_allowlist():
    """Trusted package paths for the existing Python sandbox. Report bytes only."""
    host_release()
    python = "/usr/bin/python3.12"
    roots = ["/usr/lib/python3.12"]
    pathnames = {python}
    for dirname in roots:
        for path in Path(dirname).rglob("*"):
            if path.is_file() and path.suffix in (".py", ".so") and "__pycache__" not in path.parts:
                pathnames.add(str(path))
    dependencies = [python, *(name for name in pathnames if Path(name).name.split('.', 1)[0] in ('_hashlib', '_ssl'))]
    for binary in dependencies:
        loader = run(("/usr/bin/ldd", binary)).decode("ascii")
        require("not found" not in loader, "NATIVE_S1_RUNTIME_LIBRARY")
        pathnames.update(re.findall(r"(?:^|=>)\s+(/lib(?:64)?/\S+)", loader, re.M))
    entries = {}
    for name in sorted(pathnames):
        path = Path(name).resolve(strict=True)
        row = trusted(path)
        require(0 < row.st_size <= 32 * 1024 * 1024, "NATIVE_S1_RUNTIME_SIZE")
        entries[name] = {"bytes": row.st_size, "sha256": sha(path.read_bytes()),
                         "mode": stat.S_IMODE(row.st_mode) & 0o755}
    return entries


def stage_runtime(root, manifest_path, expected):
    value = preflight.pinned_json(manifest_path, expected, maximum=2 * 1024 * 1024)
    require(set(value) == {"schema", "files"} and value["schema"] == "aioa.native-s1.runtime.v1"
            and type(value["files"]) is dict and 2 <= len(value["files"]) <= 4096
            and "/usr/bin/python3.12" in value["files"]
            and sum(e["bytes"] for e in value["files"].values()) <= 96 * 1024 * 1024, "NATIVE_S1_RUNTIME")
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    staged = {}
    for index, (name, entry) in enumerate(sorted(value["files"].items())):
        path = Path(name)
        require(str(path) == name and ".." not in path.parts
                and (name == "/usr/bin/python3.12" or name.startswith(
                    ("/usr/lib/python3.12/", "/lib/", "/lib64/")))
                and set(entry) == {"bytes", "sha256", "mode"}
                and type(entry["bytes"]) is int and 0 < entry["bytes"] <= 32 * 1024 * 1024
                and type(entry["mode"]) is int and entry["mode"] in (0o644, 0o755)
                and preflight.SHA256.fullmatch(entry["sha256"]), "NATIVE_S1_RUNTIME_ENTRY")
        file = path.resolve(strict=True)
        row = trusted(file)
        content = file.read_bytes()
        require(row.st_size == len(content) == entry["bytes"] and sha(content) == entry["sha256"]
                and stat.S_IMODE(row.st_mode) == entry["mode"], "NATIVE_S1_RUNTIME_DRIFT")
        snapshot = root / str(index)
        write_new(snapshot, content, mode=entry["mode"])
        staged[name] = {**entry, "snapshot": str(snapshot)}
    write_new(root / "manifest.json", canonical(staged), mode=0o644)


def install(path, digest, receipt, runtime, *, wheelhouse):
    require(os.getresuid() == (0, 0, 0), "NATIVE_S1_INSTALL_ROOT")
    host_release()
    pinned, _ = host_pins(path, digest, receipt, system=True)
    source = pinned["host"]
    require(not CONFIG.exists() and not INSTALL.exists() and not UNIT.exists(), "NATIVE_S1_ALREADY_INSTALLED")
    checkout = Path("/opt/aioa/native-qualification") / source["source"]
    vendor = Path("/opt/aioa/native-s1-deps") / source["source"]
    require(not checkout.exists() and not vendor.exists(), "NATIVE_S1_ALREADY_INSTALLED")
    for tool in ("/usr/bin/cc", "/usr/bin/pkttyagent", "/usr/bin/pkcheck", "/usr/bin/bwrap",
                 "/usr/sbin/apparmor_parser", "/usr/bin/systemctl", "/usr/bin/python3.12"):
        trusted(Path(tool).resolve(strict=True))
    require(sha(runtime.read_bytes()) == pinned["s1"]["runtime_sha256"], "NATIVE_S1_RUNTIME_MANIFEST_DIGEST")
    lock = wheelhouse / "requirements.lock"
    require(trusted(wheelhouse, directory=True) and trusted(lock)
            and sha(lock.read_bytes()) == pinned["s1"]["wheels_lock_sha256"], "NATIVE_S1_WHEELHOUSE")
    os.umask(0o022)
    checkout.mkdir(mode=0o755, parents=True)
    run(("/usr/bin/git", "-C", str(checkout), "init", "--template="))
    run(("/usr/bin/git", "-C", str(checkout), "-c", "protocol.file.allow=always", "fetch",
         "--no-tags", "--depth=1", SOURCE.as_uri(), source["source"]), timeout=120)
    run(("/usr/bin/git", "-C", str(checkout), "checkout", "--detach", source["source"]))
    require(installed_tree(checkout) == source["tree"], "NATIVE_S1_SOURCE_TREE")
    vendor.mkdir(mode=0o755, parents=True)
    run(("/usr/bin/python3.12", "-I", "-m", "pip", "--isolated", "--disable-pip-version-check",
         "install", "--no-index", "--only-binary=:all:",
         "--require-hashes", "--no-compile", "--find-links", str(wheelhouse), "--target", str(vendor),
         "-r", str(lock)), timeout=180)
    check = ("import sys; sys.path[:0]=[" + repr(str(vendor)) + "]; "
             "import cryptography, pydantic, uuid6, yaml")
    run(("/usr/bin/python3.12", "-IB", "-c", check))
    CONFIG.mkdir(mode=0o700)
    write_new(CONFIG / "manifest.json", path.read_bytes())
    write_new(CONFIG / "management.json", receipt.read_bytes())
    write_new(CONFIG / "runtime.json", runtime.read_bytes())
    bootstrap = ("#!/usr/bin/python3.12 -IBS\nimport runpy, sys\n"
                 f"sys.path[:0] = [{str(checkout)!r}, {str(vendor)!r}, '/usr/lib/python3/dist-packages']\n"
                 "runpy.run_module('scripts.unification.native_s1', run_name='__main__')\n")
    INSTALL.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    write_new(INSTALL, bootstrap.encode("ascii"), mode=0o755)
    write_new(UNIT, (checkout / "scripts/unification/native_s1" / UNIT.name).read_bytes(), mode=0o644)
    run(("/usr/bin/systemctl", "daemon-reload"))
    return {"source": source["source"], "tree": source["tree"], "manifest_sha256": digest,
            "launcher_sha256": sha(INSTALL.read_bytes()), "cgroup_unit_sha256": sha(UNIT.read_bytes())}
