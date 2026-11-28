"""Installed Noble supervisor for persistent Native qualifying trials."""

import ctypes
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

from runtime.mobile_gateway.wire import public_key
from runtime.red_hat.broker_protocol import require
from runtime.red_hat.execution_binding import NativeExecutionBindingV1
from runtime.red_hat.native_services import await_broker_completion
from runtime.red_hat.role_storage import PersistentVolume, RoleStorage
from runtime.red_hat.s2_admission import WRITER_SCHEMA
from runtime.red_hat.s2_continuity import ColdSuccession, boot_hash, require_successor
from runtime.red_hat.s2_receipt import ManagementEvidence, _read
from scripts.unification.native_role_supervisor import installed_tree, trusted
from scripts.unification.native_s1 import host, policy, roles
from scripts.unification.noble_preflight import pinned_json

BARRIERS = {"C1": "after_ref_link", "C2": "effect_synced", "C3": "before_completion",
            "C4a": "witness_durable", "C4b": "writer_closed_durable_before_ack"}
CHANNEL = Path("/dev/virtio-ports/org.aioa.native69.s2")
MAX_LINE = 32768


def park():
    while True:
        signal.pause()


def durable_json(path, value):
    host.write_new(path, host.canonical(value))
    fd = roles.directory(path.parent)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_spec(directory, body):
    # This file is read by the original Core UID's existing private-file reader.
    path = directory / "retained-spec.json"
    with path.open("xb") as out:
        os.fchmod(out.fileno(), 0o600)
        out.write(host.canonical(body))
        out.flush()
        os.fsync(out.fileno())
    fd = roles.directory(directory)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def packet(stream):
    raw = stream.readline(MAX_LINE + 1)
    require(0 < len(raw) <= MAX_LINE and raw.endswith(b"\n"), "NATIVE_S2_CONTROL_FRAME")
    value = json.loads(raw)
    require(type(value) is dict and host.canonical(value) == raw, "NATIVE_S2_CONTROL_FRAME")
    return value


def send_packet(stream, value):
    data = host.canonical(value)
    require(len(data) <= MAX_LINE, "NATIVE_S2_CONTROL_FRAME")
    written = 0
    while written < len(data):
        count = stream.write(data[written:])
        require(count and count > 0, "NATIVE_S2_CONTROL_WRITE")
        written += count
    stream.flush()


def plan_at(path, pin):
    trusted(path)
    data = pinned_json(path, pin)
    require(type(data) is dict and set(data) == {"vm_uuid", "session", "case", "volume", "authority_spki",
            "boot_sha256", "source_sha", "tree"} and str(uuid.UUID(data["vm_uuid"])) == data["vm_uuid"]
            and re.fullmatch("[0-9a-f]{32}", data["session"]) and data["case"] in BARRIERS
            and re.fullmatch("[0-9a-f]{64}", data["boot_sha256"])
            and all(re.fullmatch("[0-9a-f]{40}", data[key]) for key in ("source_sha", "tree")),
            "NATIVE_S2_PLAN")
    volume = PersistentVolume(**data["volume"])
    key = data["authority_spki"].encode("ascii")
    public_key(key.decode("ascii").strip())
    require(hashlib.sha256(key).hexdigest() == volume.authority_spki_sha256, "NATIVE_S2_AUTHORITY_PIN")
    return data


def require_mount(volume):
    # The controller authorizes the backing volume. The guest compares the block
    # device of the opened mount with the separately approved filesystem UUID.
    trusted(host.BASE, directory=True)
    dev = (Path("/dev/disk/by-uuid") / volume.filesystem_uuid).stat()
    info = host.BASE.stat()
    devno = f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"
    rows = [row.split() for row in Path("/proc/self/mountinfo").read_text().splitlines()]
    require(stat.S_ISBLK(dev.st_mode) and dev.st_rdev == info.st_dev
            and sum(row[4] == str(host.BASE) for row in rows) == 1
            and any(row[2:5] == [devno, "/", str(host.BASE)] and "rw" in row[5].split(",")
                    and row[row.index("-") + 1] in ("ext4", "xfs") for row in rows),
            "NATIVE_S2_PERSISTENT_MOUNT")


def volatile_dir(path, gid, mode):
    # Only the new, dedicated session's keys and sockets are volatile. Their
    # underlying directories on disk stay empty and can be re-mounted on boot B.
    require(path.parent.parent == host.BASE and path.name in ("io", "keys")
            and re.fullmatch("[0-9a-f]{32}", path.parent.name) and not list(path.iterdir()),
            "NATIVE_S2_VOLATILE_DIRECTORY")
    host.run(("/usr/bin/mount", "-t", "tmpfs", "-o",
              f"size=1m,nodev,nosuid,noexec,mode={mode:o},uid=0,gid={gid}", "tmpfs", str(path)))
    require(path.stat().st_dev != path.parent.stat().st_dev, "NATIVE_S2_VOLATILE_MOUNT")


def keep_original(root, cfg):
    durable_json(root / "operator/s2-original.json", cfg)


def _sync_preparation(root_fd):
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.syncfs(root_fd) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def control_trial(root, plan, core, broker, writer, enrollment, original):
    """Only the supervisor talks to the host. Application roles cannot request power control."""
    trial = plan["case"]
    original_path = root / "operator/s2-original.json"
    grant = roles.hear(core.control, 30)
    require(grant.get("status") == "S2_AUTHORIZED" and grant.get("dispatch") == {"routes": 1, "handoffs": 1}, "NATIVE_S2_START_REQUIRED")
    binding = NativeExecutionBindingV1.from_wire(grant["grant"]["payload"]["binding"])
    initial = grant["original"]
    require(initial["intent"] == "Unknown" and initial["outbox"] == "HELD" and initial["reservation"] == "UNKNOWN"
            and binding.storage_digest == RoleStorage.from_dict(original["storage"]).digest,
            "NATIVE_S2_HELD_START_REQUIRED")
    start_path = root / "operator/s2-start.json"
    durable_json(start_path, {"grant": grant["grant"], "initial": initial})
    # This is before the first handoff and any Git effect, never at the cut.
    _sync_preparation(writer.root_fd)
    with CHANNEL.open("r+b", buffering=0) as channel:
        require(stat.S_ISCHR(os.fstat(channel.fileno()).st_mode), "NATIVE_S2_CONTROLLER_CHANNEL")
        fcntl.flock(channel, fcntl.LOCK_EX | fcntl.LOCK_NB)
        send_packet(channel, {"event": "authorized", "plan": plan, "grant": grant["grant"],
                              "original_sha256": host.sha(original_path.read_bytes()), "start_sha256": host.sha(start_path.read_bytes()),
                              "original": original, "initial": initial})
        require(packet(channel) == {"status": "armed"}, "NATIVE_S2_CONTROLLER_REFUSED")
        roles.tell(core.control, action="writer-armed")
        events = []
        while True:
            event = roles.hear(broker.control, 15)
            if event.get("schema") == WRITER_SCHEMA:
                send_packet(channel, {"event": "admission", "query": event})
                roles.tell(broker.control, **packet(channel))
            elif event.get("status") == "PUBLISH_EVENT":
                events.append(event["point"])
            elif trial == "C4b" and event == {"status": "S2_BROKER_EXIT_BEFORE_ACK"}:
                await_broker_completion(writer, broker.completion, binding, enrollment, deadline=time.monotonic() + 10)
                require(broker.process.wait(timeout=3) == 0, "NATIVE_S2_WRITER_EXIT")
                break
            else:
                require(trial != "C4b" and event == {"status": "S2_BARRIER", "point": BARRIERS[trial]},
                        "NATIVE_S2_CUT_WINDOW")
                break
        require(events == ["before_ref_link", "after_ref_link"]
                and roles.hear(core.control, 10) == {"status": "S2_ACK_HELD"}, "NATIVE_S2_EFFECT_ORDER")
        target = root / "repo" / binding.request.exact_ref
        require(target.read_bytes() == (binding.request.new_oid + "\n").encode(), "NATIVE_S2_PRE_CUT_REF")
        observation = {"event": "barrier", "session": root.name, "point": BARRIERS[trial],
                       "start": binding.request.start_digest, "dispatch_requests": grant["dispatch"]["handoffs"],
                       "dispatch_routes": grant["dispatch"]["routes"],
                       "link_attempts": events.count("before_ref_link"), "publications": events.count("after_ref_link"),
                       "ack_received": False, "ref_oid": binding.request.new_oid}
        evidence = root / "evidence"
        name = binding.request.witness_binding().witness_id
        for label, path in (("witness_sha256", evidence / name), ("completion_sha256", evidence / ("completion-" + name))):
            observation[label] = host.sha(path.read_bytes()) if path.is_file() else None
        if trial == "C4b":
            from runtime.red_hat.writer_lifecycle import require_writer_closed
            closed = require_writer_closed(writer.root_fd, writer.storage, binding)
            require(closed == observation["completion_sha256"], "NATIVE_S2_TERMINAL_COMPLETION")
            observation["writer_closed_sha256"] = host.sha((root / "writer-closed").read_bytes())
        send_packet(channel, observation)
        park()


def load_cold_material(root, inputs):
    # Called by the trusted launcher before dropping privileges; only public
    # assertions cross into the verifier and the original Core's cold path.
    original = pinned_json(root / "operator/s2-original.json", inputs["original_sha256"])
    old = RoleStorage.from_dict(original["storage"])
    if inputs["expected_sha256"] is None:
        material = ManagementEvidence(b"", "", b"", inputs["authority_spki"].encode("ascii"),
                                      old.persistent.authority_spki_sha256)
    else:
        media = Path(inputs["media"])
        material = ManagementEvidence(_read(media / "expected.json"), inputs["expected_sha256"],
            _read(media / "receipt.json"), inputs["authority_spki"].encode("ascii"), old.persistent.authority_spki_sha256)
    return ColdSuccession(old, material, inputs["verifier_spki"])


def cold_read(args, plan):
    from cryptography.hazmat.primitives import serialization
    from runtime.mobile_gateway.wire import Identity
    from runtime.red_hat.authenticated_boundary import AUTHORIZATION, _open_seal
    from scripts.unification.native_s1 import coordinator as c

    manifest, observed = host.host_pins(args.manifest, args.manifest_sha256, args.management_receipt, system=True)
    trusted(host.INSTALL)
    trusted(host.UNIT)
    require(os.getresuid() == (0, 0, 0) and host.INSTALL.samefile(Path(os.path.abspath(sys.argv[0])))
            and installed_tree(host.SOURCE) == observed["tree"] == plan["tree"]
            and host.UNIT.read_bytes() == (host.SOURCE / "scripts/unification/native_s1" / host.UNIT.name).read_bytes()
            and observed["source"] == plan["source_sha"] and plan["boot_sha256"] == boot_hash(),
            "NATIVE_S2_COLD_HOST")
    volume = PersistentVolume(**plan["volume"])
    require_mount(volume)
    root = host.BASE / plan["session"]
    trusted(root, directory=True)
    original_file = root / "operator/s2-original.json"
    trusted(original_file)
    original = pinned_json(original_file, args.original_sha256)
    start_file = root / "operator/s2-start.json"
    trusted(start_file)
    start = pinned_json(start_file, args.start_sha256)
    require(original["vm_uuid"] == plan["vm_uuid"] and original["source"] == plan["source_sha"]
            and original["tree"] == plan["tree"] and original["trial"] == plan["case"]
            and original["predecessor_boot"] != boot_hash(), "NATIVE_S2_ORIGINAL_TRIAL")
    old = RoleStorage.from_dict(original["storage"])
    grant = _open_seal(start["grant"], original["core_spki"], AUTHORIZATION)
    binding = NativeExecutionBindingV1.from_wire(grant["binding"])
    require(binding.storage_digest == old.digest and binding.request.exact_ref == old.exact_ref,
            "NATIVE_S2_ORIGINAL_BINDING")
    uid = manifest["s1"]["core_uid"]
    gid, console = c._console(uid)
    c._airgap()
    os.umask(0o077)
    result = {"case": plan["case"], "session": root.name, "host": observed,
              "boot_a": original["predecessor_boot"], "boot_b": boot_hash(),
              "predecessor_generation": old.persistent.generation, "generation": volume.generation,
              "start": binding.request.start_digest, "original": start["initial"], "role_proofs": {},
              "settlements": None, "automatic_redispatches": None, "status": "INCOMPLETE"}
    with ExitStack() as stack:
        groups = c._cgroups(stack, root.name)
        actors, reader_gid = c._actors(root.name, uid, gid, console, groups, existing=True)
        namespace = os.stat("/proc/self/ns/mnt").st_ino
        pin = roles.pinned_directory
        current = RoleStorage(actors["core"], actors["broker"], actors["verifier"], reader_gid, namespace, old.exact_ref,
            pin(root), pin(root / "repo"), pin(root / "repo/refs/heads/aioa"), pin(root / "evidence"),
            staging=pin(root / "staging"), state=pin(root / "state"), policy_sha256=old.policy_sha256,
            writer_cgroup=pin(groups["broker"]), persistent=volume)
        require_successor(old, current)
        # No sequencer, broker, broker signer, or release socket is started on boot B.
        for role in ("core", "verifier"):
            profile = policy.profiles(root.name, observed["source"], uid, exact_ref=current.exact_ref,
                                      persistent=True)[role]
            c._install_policy(root, role, profile, retained=True)
        volatile_dir(root / "io", reader_gid, 0o750)
        for role in ("core", "verifier"):
            c._mkdir(root / "io" / policy.SOCKETS[role], actors[role].uid, reader_gid, 0o2750)
        volatile_dir(root / "keys", 0, 0o700)
        media = args.media
        trusted(media, directory=True)
        key_path = media / "verifier.pem"
        trusted(key_path)
        require(stat.S_IMODE(key_path.stat().st_mode) in (0o400, 0o600), "NATIVE_S2_VERIFIER_KEY_MODE")
        key = _read(key_path)
        identity = Identity(serialization.load_pem_private_key(key, password=None))
        host.write_new(root / "keys/verifier.pem", key, uid=actors["verifier"].uid, gid=actors["verifier"].gid,
                       mode=0o400)
        inputs = {"media": str(media), "authority_spki": plan["authority_spki"], "original_sha256": args.original_sha256,
                  "expected_sha256": args.expected_sha256, "verifier_spki": identity.spki}
        cfg = {key: original[key] for key in ("enrollment", "task_id", "origin", "core_spki", "case")}
        cfg.update(storage=current.to_dict(), verifier_spki=identity.spki, s2_read=inputs)
        zero = {"routes": 0, "handoffs": 0}
        # A surviving ref is an observation, not the disposition of the original warrant.
        target = root / "repo" / current.exact_ref
        result["ref_oid"] = target.read_text("ascii").strip() if target.exists() else None
        name = binding.request.witness_binding().witness_id
        result["evidence_sha256"] = {label: host.sha(path.read_bytes()) if path.is_file() else None
            for label, path in (("witness", root / "evidence" / name),
                                ("completion", root / "evidence" / ("completion-" + name)),
                                ("writer_closed", root / "writer-closed"))}
        repo = root / "repo"
        audit = subprocess.run(("/usr/bin/git", "-c", f"safe.directory={repo}", "--git-dir", str(repo), "fsck",
                                "--strict", "--no-reflogs", "--no-dangling", binding.request.new_oid),
                               env=host.ENV, user=actors["verifier"].uid, group=actors["verifier"].gid,
                               extra_groups=(reader_gid,), stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        result["git_fsck_exit"] = audit.returncode
        for repeat in (False, True):
            # Always admit the cold roles. Their actual rejection determines a negative result.
            cold, verifier, reply = c._cold_roles(stack, root, actors, reader_gid, namespace, groups, cfg,
                                                 result["role_proofs"], closure=True, repeat=repeat)
            result["repeat" if repeat else "readback"] = reply
            if reply["status"] == "COLD_DENIED":
                require(cold.process.wait(timeout=5) == 3 and reply["dispatch"] == zero, "NATIVE_S2_COLD_DENIAL")
                if not repeat and reply["original"] == start["initial"]:
                    result.update(settlements=0, automatic_redispatches=0, disposition="HELD")
                    if (plan["case"] != "C4b" and reply["reason"] == "NATIVE_S1_WRITER_CLOSURE_UNAVAILABLE"
                            and (result["ref_oid"] == binding.request.new_oid
                                 or plan["case"] == "C1" and result["ref_oid"] is None)
                            and (plan["case"] not in ("C1", "C2") or result["evidence_sha256"]["witness"] is None)
                            and (plan["case"] != "C4a" or all(result["evidence_sha256"][k] for k in ("witness", "completion")))
                            and (plan["case"] in ("C4a", "C4b") or result["evidence_sha256"]["completion"] is None)
                            and audit.returncode == 0):
                        result["status"] = "PASS"
                return result
            require(plan["case"] == "C4b" and audit.returncode == 0 and reply["status"] == "RECOVERED" and reply["dispatch"] == zero
                    and cold.process.wait(timeout=5) == 0 and verifier.process.wait(timeout=5) == 0
                    and reply["verifier_pid"] == verifier.peer.pid and result["ref_oid"] == binding.request.new_oid
                    and reply["first"] == reply["second"] and reply["after"] == reply["repeated"]
                    and reply["after"]["intent"] == "Applied" and reply["after"]["reservation"] == "COMMITTED"
                    and reply["after"]["task"] == "VERIFIED"
                    and reply["after"]["intent_revision"] == start["initial"]["intent_revision"] + 1
                    and reply["before"] == (result["readback"]["after"] if repeat else start["initial"]),
                    "NATIVE_S2_COLD_SETTLEMENT")
            if not repeat:
                os.unlink(roles.endpoint(root, "verifier"))
        result.update(settlements=1, automatic_redispatches=0, disposition="APPLIED", status="PASS")
    return result
