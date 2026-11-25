"""Read-only host qualification probe for the pinned Native #69 profile.

This module never creates files, changes sysctls, starts services, mounts
filesystems, switches users, or performs namespace/cgroup experiments.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _read(path, maximum=8192):
    try:
        with open(path, "rb") as stream:
            return stream.read(maximum).decode("utf-8", "replace").strip()
    except (OSError, UnicodeError):
        return None


def _version(command):
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, check=False, timeout=2,
                                env={"PATH": os.defpath, "LC_ALL": "C"})
        return result.stdout[:4096].decode("utf-8", "replace").splitlines()[0:3]
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def _binary(path):
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            while True:
                part = stream.read(1024 * 1024)
                if not part:
                    break
                digest.update(part)
        return {"path": path, "sha256": digest.hexdigest()}
    except OSError:
        return None


def _os_release():
    data = {}
    for line in (_read("/etc/os-release") or "").splitlines():
        key, sep, value = line.partition("=")
        if sep and key in {"ID", "ID_LIKE", "VERSION_ID", "PRETTY_NAME"}:
            data[key] = value.strip('"')
    return data


def _namespace_ids():
    values = {}
    for name in ("user", "mnt", "pid", "net", "cgroup"):
        try:
            values[name] = os.stat(f"/proc/self/ns/{name}").st_ino
        except OSError:
            values[name] = None
    return values


def _cgroup_view():
    current = None
    for line in (_read("/proc/self/cgroup") or "").splitlines():
        hierarchy, _, remainder = line.partition(":")
        controllers, _, path = remainder.partition(":")
        if hierarchy == "0" and controllers == "":
            current = path.lstrip("/")
            break
    base = Path("/sys/fs/cgroup") / (current or "")
    controllers = _read(base / "cgroup.controllers")
    delegated = _read(base / "cgroup.subtree_control")
    return {
        "current_cgroup_path": current,
        "controllers_visible": controllers.split() if controllers else [],
        "controllers_delegated_to_children": delegated.split() if delegated else [],
        "delegation_observed": bool(delegated),
    }


def _host_kind():
    detect = shutil.which("systemd-detect-virt")
    if detect:
        value = _version([detect, "--container"])
        if value:
            first = value[0].strip().lower()
            if first and first not in ("none", "failed to detect virtualization"):
                return "CONTAINER"
        value = _version([detect, "--vm"])
        if value:
            first = value[0].strip().lower()
            if first and first not in ("none", "failed to detect virtualization"):
                return "VM"
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return "CONTAINER"
    if Path("/sys/hypervisor/type").exists():
        return "VM"
    vendor = (_read("/sys/class/dmi/id/sys_vendor") or "").lower()
    if any(word in vendor for word in ("vmware", "virtualbox", "qemu", "kvm", "xen", "hyper-v")):
        return "VM"
    if Path("/sys/class/dmi/id/sys_vendor").exists():
        return "BARE_METAL_OR_UNIDENTIFIED"
    return "UNKNOWN"


def probe():
    os_release = _os_release()
    git = shutil.which("git")
    bwrap = shutil.which("bwrap")
    cg_controllers = _read("/sys/fs/cgroup/cgroup.controllers")
    apparmor = _read("/sys/module/apparmor/parameters/enabled")
    user_runtime = Path(f"/run/user/{os.getuid()}")
    user_manager_socket = user_runtime / "systemd" / "private"
    try:
        user_manager_socket_available = user_manager_socket.is_socket()
    except OSError:
        user_manager_socket_available = False
    try:
        memory_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError):
        memory_bytes = None
    try:
        disk = shutil.disk_usage(Path.cwd())
        free_disk_bytes = disk.free
    except OSError:
        free_disk_bytes = None
    noble = os_release.get("ID") == "ubuntu" and os_release.get("VERSION_ID") == "24.04"
    return {
        "schema": "aioa.redhat.native69.host-probe.v1",
        "read_only": True,
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "os_release": os_release,
        "python": platform.python_version(),
        "git": {"version": _version([git, "--version"])[0] if git and _version([git, "--version"]) else None,
                "binary": _binary(git) if git else None},
        "systemd": _version(["/usr/bin/systemctl", "--version"]) if Path("/usr/bin/systemctl").exists() else None,
        "systemd_user_manager_socket": user_manager_socket_available,
        "cgroup_v2": cg_controllers is not None,
        "cgroup_controllers": cg_controllers.split() if cg_controllers else [],
        "cgroup_view": _cgroup_view(),
        "namespaces": _namespace_ids(),
        "namespace_actions_tested": False,
        "user_max_user_namespaces": _read("/proc/sys/user/max_user_namespaces"),
        "unprivileged_userns_clone": _read("/proc/sys/kernel/unprivileged_userns_clone"),
        "apparmor_enabled_parameter": apparmor,
        "apparmor_status": _version([shutil.which("aa-status")]) if shutil.which("aa-status") else None,
        "bubblewrap": {"path": bwrap, "version": _version([bwrap, "--version"])[0]
                       if bwrap and _version([bwrap, "--version"]) else None},
        "uid": os.getuid(), "euid": os.geteuid(),
        "separate_executor_uid_tested": False,
        "memory_bytes": memory_bytes,
        "free_disk_bytes_at_cwd": free_disk_bytes,
        "host_kind": _host_kind(),
        "pinned_noble_os_profile_match": noble,
        "pinned_noble_environment_detected": noble,
        "privileged_actions_performed": False,
    }


if __name__ == "__main__":
    print(json.dumps(probe(), sort_keys=True, indent=2))
