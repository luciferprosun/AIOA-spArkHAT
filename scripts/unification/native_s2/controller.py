"""Off-guest libvirt supervisor for one explicitly pinned, disposable VM."""

import argparse
import json
import os
import re
import socket
import stat
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from runtime.mobile_gateway.wire import Identity
from runtime.red_hat.authenticated_boundary import AUTHORIZATION, _open_seal
from runtime.red_hat.broker_protocol import digest, require
from runtime.red_hat.execution_binding import NativeExecutionBindingV1
from runtime.red_hat.role_storage import RoleStorage
from runtime.red_hat.s2_receipt import _read
from scripts.unification.native_s1.host import canonical, sha
from scripts.unification.native_s1.roles import enrollment_of
from scripts.unification.native_s2 import storage
from scripts.unification.native_s2.guest import BARRIERS, CHANNEL, packet, send_packet
from scripts.unification.noble_preflight import pinned_json


class RunLog:
    def __init__(self, directory):
        self.path = directory
        self.path.mkdir(mode=0o700)
        self._sync(self.path.parent)

    @staticmethod
    def _sync(parent):
        fd = os.open(parent, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def record(self, name, value):
        with (self.path / (name + ".json")).open("xb") as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(canonical({"utc_ns": time.time_ns(), "value": value}))
            out.flush()
            os.fsync(out.fileno())
        self._sync(self.path)


def config_digest(raw):
    domain = ET.fromstring(raw)
    for target in domain.findall("devices/channel/target"):
        if target.get("name") == CHANNEL.name:
            target.attrib.pop("state", None)  # Live virtio channel connect/disconnect status.
    return sha(ET.canonicalize(ET.tostring(domain, encoding="unicode")).encode("utf-8"))


def inspect_xml(raw, plan, xml_pin, socket_dir, nbd_socket, root):
    require(config_digest(raw) == xml_pin, "S2_DOMAIN_XML_CHANGED")
    domain = ET.fromstring(raw)
    require(domain.findtext("uuid") == plan["vm_uuid"], "S2_DOMAIN_ID")
    channel = [node for node in domain.findall("devices/channel") if
               node.get("type") == "unix" and node.find("target") is not None
               and node.find("target").get("name") == CHANNEL.name]
    require(len(channel) == 1, "S2_DOMAIN_CHANNEL")
    source = channel[0].find("source")
    require(source is not None and source.get("mode") == "bind" and source.get("path"), "S2_DOMAIN_CHANNEL")
    path = Path(source.get("path"))
    require(path.is_absolute() and path.parent.resolve(strict=True) == socket_dir.resolve(strict=True),
            "S2_DOMAIN_CHANNEL_PATH")
    disks = []
    volume = plan["volume"]
    for disk in domain.findall("devices/disk"):
        src = disk.find("source")
        if (src is not None and src.get("protocol") == "nbd" and
                (src.get("name") or "").startswith(f"{volume['volume_sha256']}/{volume['generation']}/")):
            disks.append(disk)
    require(len(disks) == 1 and disks[0].get("type") == "network" and disks[0].get("device") == "disk",
            "S2_DOMAIN_VOLUME")
    host = disks[0].find("source/host")
    driver = disks[0].find("driver")
    require(driver is not None and driver.get("type") == "raw" and driver.get("cache") in ("none", "directsync")
            and host is not None and host.get("transport") == "unix" and host.get("socket"),
            "S2_DOMAIN_FLUSH_MODEL")
    backend = Path(host.get("socket"))
    require(backend.is_absolute() and backend.samefile(nbd_socket)
            and stat.S_ISSOCK(nbd_socket.stat().st_mode), "S2_DOMAIN_BACKEND_SOCKET")
    storage.check_attached(root, volume["volume_sha256"], disks[0].find("source").get("name"))
    return path, {"name": domain.findtext("name"), "uuid": plan["vm_uuid"], "xml_sha256": xml_pin,
                  "cache": driver.get("cache"), "filesystem_uuid": volume["filesystem_uuid"]}


def original_start(event, plan):
    require(event.get("event") == "authorized" and event.get("plan") == plan, "S2_CONTROLLER_PLAN")
    original = event["original"]
    grant = event["grant"]
    require(sha(canonical(original)) == event["original_sha256"]
            and sha(canonical({"grant": grant, "initial": event["initial"]})) == event["start_sha256"],
            "S2_CONTROLLER_ORIGINAL_FILES")
    aperture = RoleStorage.from_dict(original["storage"])
    signed = _open_seal(grant, original["core_spki"], AUTHORIZATION)
    binding = NativeExecutionBindingV1.from_wire(signed["binding"])
    require(original["vm_uuid"] == plan["vm_uuid"] and original["trial"] == plan["case"]
            and original["source"] == plan["source_sha"] and original["tree"] == plan["tree"]
            and original["predecessor_boot"] == plan["boot_sha256"] == sha(binding.boot_id.encode("ascii"))
            and original["storage"]["persistent"] == plan["volume"]
            and binding.storage_digest == aperture.digest and binding.request.exact_ref == aperture.exact_ref
            and binding.request.repository == (aperture.repository.device, aperture.repository.inode)
            and binding.request.ref_directory == (aperture.ref_parent.device, aperture.ref_parent.inode)
            and binding.request.executor_key_id == enrollment_of(original["enrollment"]).executor.key_id,
            "S2_CONTROLLER_START")
    require(event["initial"]["outbox"] == "HELD" and event["initial"]["intent"] == "Unknown"
            and event["initial"]["reservation"] == "UNKNOWN"
            and event["initial"]["reservation_digest"] == binding.request.reservation_digest, "S2_CONTROLLER_HELD")
    return binding


def supervise(stream, plan, root, signer, log, cut):
    first = packet(stream)
    binding = original_start(first, plan)
    volume = plan["volume"]
    require(signer.spki == plan["authority_spki"].strip() and
            sha(plan["authority_spki"].encode("ascii")) == volume["authority_spki_sha256"], "S2_CONTROLLER_KEY")
    log.record("authorized", first)
    storage.arm(root, volume["volume_sha256"], volume["generation"], plan["boot_sha256"],
                binding.storage_digest, binding.request.exact_ref, digest(binding.to_wire()))
    send_packet(stream, {"status": "armed"})
    count = 0
    while True:
        message = packet(stream)
        if message.get("event") == "barrier":
            break
        require(message.get("event") == "admission" and count < 16, "S2_CONTROLLER_ADMISSION")
        signed = storage.writer_readback(root, message["query"], signer)
        count += 1
        log.record("admission-" + str(count), signed)
        send_packet(stream, signed)
    require(count > 0 and message.get("point") == BARRIERS[plan["case"]]
            and message.get("session") == plan["session"] and message.get("start") == binding.request.start_digest
            and message.get("ref_oid") == binding.request.new_oid and message.get("ack_received") is False
            and all(type(message.get(k)) is int and message[k] == 1
                    for k in ("publications", "dispatch_requests", "link_attempts")), "S2_CONTROLLER_BARRIER")
    if plan["case"] == "C4b":
        require(all(re.fullmatch("[0-9a-f]{64}", message.get(key, "")) for key in (
            "witness_sha256", "completion_sha256", "writer_closed_sha256")), "S2_CONTROLLER_CLOSURE")
    log.record("barrier", message)
    cut()  # Fixed controller-selected domain, never a UUID or command received from a role.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("plan", "root", "receipts", "socket-dir", "nbd-socket", "key"):
        parser.add_argument("--" + arg, type=Path, required=True)
    for arg in ("plan-sha256", "domain-xml-sha256", "libvirt-uri"):
        parser.add_argument("--" + arg, required=True)
    args = parser.parse_args(argv)
    plan = pinned_json(args.plan, args.plan_sha256)
    session = plan["session"]
    require(re.fullmatch("[a-f0-9]{32}", session) and plan["case"] in BARRIERS, "S2_CONTROLLER_PLAN")
    import uuid
    require(str(uuid.UUID(plan["vm_uuid"])) == plan["vm_uuid"], "S2_DOMAIN_ID")

    def virsh(action):
        return subprocess.run(["virsh", "--connect", args.libvirt_uri, action, plan["vm_uuid"]],
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                              env={**os.environ, "LC_ALL": "C"}).stdout

    def topology():
        # Independently pinned live XML, checked again immediately before the cut.
        return inspect_xml(virsh("dumpxml"), plan, args.domain_xml_sha256, args.socket_dir, args.nbd_socket, args.root)

    path, facts = topology()
    require(virsh("domstate").strip() == b"running", "S2_DOMAIN_NOT_RUNNING")
    require(args.key.stat().st_mode & 0o077 == 0, "S2_MANAGEMENT_KEY_PERMISSIONS")
    signer = Identity(serialization.load_pem_private_key(_read(args.key), password=None))
    log = RunLog(args.receipts / session)
    log.record("domain", facts)

    def cut():
        require(topology() == (path, facts) and virsh("domstate").strip() == b"running", "S2_DOMAIN_CHANGED")
        log.record("power-requested", {"uuid": plan["vm_uuid"], "action": "destroy"})
        virsh("destroy")
        state = virsh("domstate").decode("ascii").strip()
        log.record("power-returned", {"uuid": plan["vm_uuid"], "state": state})
        require(state == "shut off", "S2_POWER_CUT_UNCONFIRMED")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(900)
        sock.connect(str(path))
        with sock.makefile("rwb", buffering=0) as stream:
            supervise(stream, plan, args.root, signer, log, cut)
    print(json.dumps({"session": session, "case": plan["case"], "power": "CONFIRMED_OFF"}))


if __name__ == "__main__":
    main()
