"""Prepare an unsigned cold expectation from the controller's original run and current storage."""

import argparse
import json
import os
import secrets
from pathlib import Path

from runtime.mobile_gateway.wire import public_key, unbase64
from runtime.red_hat.broker_protocol import digest, require
from runtime.red_hat.s2_receipt import _read
from scripts.unification.native_s1.host import canonical, sha
from scripts.unification.native_s2 import controller, storage
from scripts.unification.noble_preflight import pinned_json


def from_controller(root, log, plan, verifier_spki, current_epoch):
    original = json.loads((log / "authorized.json").read_bytes())["value"]
    before = original["plan"]
    binding = controller.original_start(original, before)
    request = binding.request
    require(before["case"] == plan["case"] == "C4b"
            and all(before[k] == plan[k] for k in ("session", "source_sha", "tree", "vm_uuid", "authority_spki"))
            and before["boot_sha256"] != plan["boot_sha256"] and type(current_epoch) is int
            and current_epoch >= request.core_epoch, "S2_EXPECTED_SESSION")
    old, new = before["volume"], plan["volume"]
    require(all(old[k] == new[k] for k in ("volume_sha256", "authority_spki_sha256", "filesystem_uuid"))
            and new["generation"] > old["generation"], "S2_EXPECTED_VOLUME")
    barrier = json.loads((log / "barrier.json").read_bytes())["value"]
    stopped = json.loads((log / "power-returned.json").read_bytes())["value"]
    require(stopped == {"uuid": plan["vm_uuid"], "state": "shut off"} and barrier["start"] == request.start_digest
            and barrier["point"] == controller.BARRIERS["C4b"] and barrier["session"] == plan["session"]
            and barrier["ref_oid"] == request.new_oid and barrier["ack_received"] is False, "S2_EXPECTED_CUT")
    with storage._transaction(root) as db:
        live = storage._row(db, new["volume_sha256"], new["generation"])
        retired = db.execute("SELECT * FROM retired WHERE generation=?", (old["generation"],)).fetchone()
        require(live["attached"] == 1 and live["posture"] == "COLD_READ" and not live["faulted"]
                and retired is not None and not retired["faulted"] and retired["posture"] == "WRITER"
                and retired["binding"] == digest(binding.to_wire()) and retired["storage"] == binding.storage_digest
                and retired["boot"] == before["boot_sha256"] and retired["ref"] == request.exact_ref,
                "S2_EXPECTED_EXCLUSIVE_SUCCESSION")
    public_key(verifier_spki)
    return {"start_sha256": request.start_digest, "intent_sha256": request.intent_digest,
            "reservation_sha256": request.reservation_digest, "original_policy_epoch": request.core_epoch,
            "volume_sha256": new["volume_sha256"], "predecessor_boot_sha256": before["boot_sha256"],
            "predecessor_generation": old["generation"], "predecessor_spki_sha256": request.executor_key_id,
            "witness_sha256": barrier["witness_sha256"], "completion_sha256": barrier["completion_sha256"],
            "writer_closed_sha256": barrier["writer_closed_sha256"], "current_boot_sha256": plan["boot_sha256"],
            "current_generation": new["generation"], "current_policy_epoch": current_epoch,
            "reader_identity_sha256": sha(unbase64(verifier_spki)), "challenge": secrets.token_hex(32)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("root", "log", "plan", "verifier-spki", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--current-epoch", required=True, type=int)
    args = parser.parse_args(argv)
    data = from_controller(args.root, args.log, pinned_json(args.plan, args.plan_sha256),
                           _read(args.verifier_spki).decode("ascii").strip(), args.current_epoch)
    raw = canonical(data)
    with os.fdopen(os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    print(json.dumps({"expected_sha256": sha(raw), "status": "UNSIGNED_EXPECTATION"}))


if __name__ == "__main__":
    main()
