"""Read-only source identity, high-signal credential and MIT provenance checks."""

import ast
import csv
import hashlib
import json
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    rb"gh[pousr]_[A-Za-z0-9]{36,}",
    rb"github_pat_[A-Za-z0-9_]{70,}",
    rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}",
    rb"\bnvapi-[A-Za-z0-9_-]{30,}",
    rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]{80,}",
)


def callee(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return callee(node.value) + "." + node.attr
    if isinstance(node, ast.Call):
        return callee(node.func) + "()"
    if isinstance(node, ast.Subscript):
        return callee(node.value) + "[data]"
    return "<dynamic>"


def verify_inventory(oids, hashes):
    directory = ROOT / "docs/unification"
    rows = list(csv.DictReader((directory / "NZ12_69_MODULE_INVENTORY.csv").open()))
    graph = json.loads((directory / "NZ12_SEMANTIC_TARGETS.json").read_text())
    assert len(rows) == len({row["SOURCE_PATH"] for row in rows}) == 69
    assert {row["SOURCE_SHA"] for row in rows} == {"392487849eddc7444f5159994b66b72e73f15934"}
    for row in rows:
        locations = row["TARGET_LOCATIONS"].split(";")
        blobs = row["TARGET_BLOBS"].split(";")
        assert len(locations) == len(blobs)
        for location, oid in zip(locations, blobs, strict=True):
            path = location.split("#", 1)[0].rsplit(":", 1)[0]
            assert oids[path] == oid, "TARGET_INVENTORY_DRIFT"
    for path, recorded in graph["target_modules"].items():
        assert oids[path] == recorded["git_blob"] and hashes[path] == recorded["sha256"]
        if path.endswith(".py"):
            tree = ast.parse((ROOT / path).read_bytes())
            sites = [{"callee": callee(node.func), "line": node.lineno}
                     for node in ast.walk(tree) if isinstance(node, ast.Call)]
            assert recorded["call_site_count"] == len(sites)
            assert recorded["symbolic_callees"] == sorted({item["callee"] for item in sites})
            assert recorded["call_sites_sha256"] == hashlib.sha256(json.dumps(sites, sort_keys=True).encode()).hexdigest()


def main():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    entries = subprocess.check_output(["git", "ls-tree", "-rz", "HEAD"], cwd=ROOT).split(b"\0")
    hashes, oids, findings = {}, {}, []
    for entry in entries:
        if not entry:
            continue
        descriptor, raw_path = entry.split(b"\t", 1)
        mode, kind, oid = descriptor.decode().split()
        name = raw_path.decode()
        path = ROOT / name
        assert kind == "blob" and mode in ("100644", "100755"), "UNSUPPORTED_SOURCE_MODE"
        assert stat.S_ISREG(path.lstat().st_mode), "SOURCE_SUBSTITUTION"
        data = path.read_bytes()
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == oid, "SOURCE_DRIFT"
        hashes[name] = hashlib.sha256(data).hexdigest()
        oids[name] = oid
        for index, pattern in enumerate(PATTERNS):
            if re.search(pattern, data):
                findings.append({"path": name, "pattern": index})
    assert not findings, findings  # Never print the matching credential bytes.
    license_path = "runtime/nonzero_cloudops/LICENSE-NONZERO.txt"
    assert hashes.get(license_path) == "4da5bfd2f6754d2a3882c931b3029887af57fa8dc8ebcc435de5c49269bb20a4"
    license_text = (ROOT / license_path).read_text()
    assert "Copyright (c) 2026 luciferprosun" in license_text
    assert "Permission is hereby granted, free of charge" in license_text
    verify_inventory(oids, hashes)
    print(json.dumps({"status": "PASS", "head": head, "files": len(hashes),
                      "source_manifest_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
                      "credential_findings": 0, "license_sha256": hashes[license_path],
                      "scope": "Tracked source identity and bounded high-signal patterns; not a universal secret proof"}))


if __name__ == "__main__":
    main()
