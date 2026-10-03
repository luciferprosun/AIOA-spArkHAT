#!/usr/bin/env python3
"""Offline static/security checks with no source or secret values in output."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import py_compile
import subprocess
import tempfile

from check_changed_secrets import changed_paths, scan_files


def strict_json(raw: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("nonfinite")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="628f9ccb2f9ada475bf2c27a2c377ed04458d1df")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
    if branch != "nebius-personal-ai":
        print(json.dumps({"status": "BLOCKED", "category": "BRANCH_INTEGRITY"}))
        return 1
    paths = changed_paths(root, args.base)
    rows = []
    diff = subprocess.run(["git", "diff", "--check", "main"], cwd=root, capture_output=True)
    rows.append({"path": ".", "category": "GIT_DIFF_CHECK", "status": "PASS" if diff.returncode == 0 else "FAIL"})
    with tempfile.TemporaryDirectory(prefix="aioa-static-") as temporary:
        # The existing application JS remains relevant even when unmodified.
        for index, relative in enumerate(sorted(set(paths + ["web/app.js"]))):
            path = root / relative
            if not path.is_file():
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                rows.append({"path": relative, "category": "UNSAFE_PATH", "status": "FAIL"})
                continue
            category = None
            passed = True
            try:
                if path.suffix == ".py":
                    category = "PYTHON_COMPILE"
                    py_compile.compile(str(path), cfile=str(Path(temporary) / f"{index}.pyc"), doraise=True)
                elif path.suffix == ".json":
                    category = "JSON_VALIDATION"
                    strict_json(path.read_text())
                elif path.suffix == ".js":
                    category = "JAVASCRIPT_SYNTAX"
                    result = subprocess.run(["node", "--check", str(path)], capture_output=True, timeout=20)
                    passed = result.returncode == 0
                elif path.suffix == ".sh":
                    category = "SHELL_SYNTAX"
                    result = subprocess.run(["bash", "-n", str(path)], capture_output=True, timeout=20)
                    passed = result.returncode == 0
            except (OSError, ValueError, py_compile.PyCompileError, subprocess.TimeoutExpired):
                passed = False
            if category:
                rows.append({"path": relative, "category": category, "status": "PASS" if passed else "FAIL"})
    scan = scan_files(root, paths)
    report = {"schema": "aioa.prompt03-static.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
              "branch": branch, "base_sha": args.base,
              "tested_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
              "status": "PASS" if all(row["status"] == "PASS" for row in rows) and scan["status"] == "PASS" else "FAIL",
              "static_checks": rows, "secret_scan": scan}
    output = args.output or root / "evidence/personal_ai_vertical_slice" / (
        "prompt03_static_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    if not output.is_absolute():
        output = root / output
    if not output.resolve().is_relative_to(root):
        print(json.dumps({"status": "BLOCKED", "category": "OUTPUT_PATH_OUTSIDE_REPOSITORY"}))
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": report["status"], "checks": len(rows), "secret_scan_status": scan["status"],
                      "files_scanned": scan["files_checked"], "evidence": str(output.relative_to(root)),
                      "failures": [row for row in [*rows, *scan["results"]] if row["status"] == "FAIL"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
