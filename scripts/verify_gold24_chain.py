#!/usr/bin/env python3
"""Read-only chain checker. It does NOT certify physical uptime or live inference."""
import hashlib
import json
import sys
from pathlib import Path

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def main(root):
    root = Path(root)
    report_raw = (root / "final-report.json").read_bytes()
    manifest_raw = (root / "manifest.json").read_bytes()
    report = json.loads(report_raw)
    manifest = json.loads(manifest_raw)
    files = sorted(root.glob("checkpoint-*.json"))
    n = report["checkpoint_count"]
    assert type(n) is int and n >= 2 and len(files) == n, "checkpoint count"
    previous = None
    active = -1
    file_root = hashlib.sha256()
    for i, path in enumerate(files):
        assert path.name == f"checkpoint-{i:06d}.json", "sequence"
        raw = path.read_bytes()
        c = json.loads(raw)
        without_digest = {k: v for k, v in c.items() if k != "checkpoint_digest"}
        encoded = json.dumps(without_digest, sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        assert digest(encoded) == c["checkpoint_digest"], "digest"
        assert c["previous_checkpoint_digest"] == previous, "hash chain"
        assert c["gold_test_id"] == report["run_id"], "run ID"
        assert c["frozen_source_sha"] == report["candidate_sha"], "source SHA"
        assert c["harness_sha"] == report["harness_sha256"], "harness SHA"
        assert type(c["active_seconds"]) is int and c["active_seconds"] >= active, "active time"
        previous, active = c["checkpoint_digest"], c["active_seconds"]
        file_root.update(path.name.encode("ascii") + bytes((0,)) + hashlib.sha256(raw).digest())
    assert previous == report["final_checkpoint_digest"], "final hash"
    assert active == report["active_seconds"], "final active"
    assert manifest["run_id"] == report["run_id"], "manifest run ID"
    assert manifest["candidate_sha"] == report["candidate_sha"], "manifest source"
    assert manifest["harness_sha256"] == report["harness_sha256"], "manifest harness"
    wall = report["ended_at"] - report["started_at"]
    assert 0 <= active <= wall and active >= manifest["duration_seconds"], "clock accounting"
    print(json.dumps({
        "scope": "local_report_and_checkpoint_file_consistency_only",
        "status_from_report": report["status"],
        "run_id": report["run_id"],
        "active_seconds_from_report": active,
        "wall_seconds_from_report": wall,
        "checkpoints_verified": n,
        "predecessor_links_verified": n - 1,
        "sha256_final_report": digest(report_raw),
        "sha256_manifest": digest(manifest_raw),
        "checkpoint_file_set_sha256_v1": file_root.hexdigest(),
        "replay_attempts_from_report": report.get("replay_attempts"),
        "nvidia_gate_from_report": report.get("nvidia_gate"),
        "caveat": "Does NOT independently certify source, wall-clock truth, replay attack tests, providers or external effects."
    }, indent=2))
if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("Usage: verify_gold24_chain.py PATH_TO_RUN_DIR")
        main(sys.argv[1])
    except (AssertionError, ValueError, KeyError, OSError) as e:
        print("GOLD24_CHAIN_CHECK_FAILED:", str(e), file=sys.stderr)
        sys.exit(1)
