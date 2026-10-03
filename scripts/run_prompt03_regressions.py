#!/usr/bin/env python3
"""Sequential offline Prompt 03 regression groups with exact recorded counts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


GROUPS = {
    "nebius": ["nebius_provider", "nebius_live_probe", "nebius_safe_diagnostics", "nebius_cpl", "nebius_routing", "nebius_https_transport"],
    "cpl": ["cpl_service", "cpl_original_contract", "cpl_original_redaction", "cpl_generic", "cpl_evidence", "cpl_wait_contract", "cpl_preset", "cpl_web", "cpl_retrieval_root", "cpl_assistant_cli"],
    "lite_serviceguard_https": ["nv02_lite", "nv02_http", "nv09_service_guard", "serverless_effect_transport"],
    "nv10_recovery": ["nv10_guard", "nv10_memory", "nv10_recovery"],
    "private_memory_competition_web": ["nv07_chat", "nv07_isolation", "competition_view", "competition_evaluation", "webapp", "nebius_personal_ai"],
    "secret_scanner": ["changed_secrets"],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", action="append", choices=tuple(GROUPS))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip()
    if branch != "nebius-personal-ai":
        print(json.dumps({"status": "BLOCKED", "category": "BRANCH_INTEGRITY"}))
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or root / "evidence/personal_ai_vertical_slice" / f"prompt03_regression_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    groups = []
    for group in args.group or GROUPS:
        names = [f"tests.test_{name}" for name in GROUPS[group]]
        command = [sys.executable, "-m", "unittest", *names, "-v"]
        with tempfile.TemporaryDirectory(prefix="aioa-prompt03-home-") as home:
            env = dict(os.environ)
            # Tests cannot inherit the operator's provider credentials or home state.
            for key in list(env):
                if any(part in key.upper() for part in ("API_KEY", "AUTH_TOKEN", "ACCESS_TOKEN", "SECRET_KEY")):
                    env.pop(key)
            env.update(HOME=home, AOIA_HOME=str(Path(home) / "state"),
                       PYTHONPATH=os.pathsep.join([str(root / "runtime"), str(root / "tests"), str(root)]))
            started = time.monotonic()
            timed_out = False
            try:
                result = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                        text=True, timeout=args.timeout)
                log, exit_code = result.stdout + result.stderr, result.returncode
            except subprocess.TimeoutExpired as error:
                timed_out, exit_code = True, None
                log = (error.stdout or b"") + (error.stderr or b"")
                if isinstance(log, bytes):
                    log = log.decode("utf-8", "replace")
            elapsed = round(time.monotonic() - started, 3)
        log_path = output.with_name(f"{output.stem}_{group}.log")
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(log)
        run = re.search(r"Ran (\d+) tests? in", log)
        summary = re.search(r"(?:FAILED|OK)(?: \(([^\n]*)\))?\s*$", log)
        fields = dict(re.findall(r"(failures|errors|skipped|expected failures|unexpected successes)=(\d+)",
                                 summary.group(1) or "")) if summary else {}
        outcomes = re.findall(r"\.\.\. (ok|FAIL|ERROR|skipped|expected failure|unexpected success)", log)
        completed = len(outcomes)
        total = int(run.group(1)) if run else completed
        failed = int(fields.get("failures", 0)) + int(fields.get("errors", 0)) + int(fields.get("unexpected successes", 0))
        if not summary:
            failed = sum(outcome in ("FAIL", "ERROR", "unexpected success") for outcome in outcomes)
        # A process error or incomplete summary is never reported as PASS.
        if exit_code not in (0, None) and failed == 0:
            failed = 1
        skipped = int(fields.get("skipped", 0)) if summary else outcomes.count("skipped")
        passed = max(0, total - failed - skipped)
        row = {"group": group, "command": command, "fresh_temporary_home": True,
               "credentials_removed": True, "paid_requests_authorized": False,
               "status": "TIMEOUT" if timed_out else "PASS" if exit_code == 0 and summary else "FAIL",
               "tests_run": total, "pass": passed, "fail": failed, "skip": skipped,
               "timeout": int(timed_out), "exit_code": exit_code, "elapsed_seconds": elapsed,
               "log_path": str(log_path.relative_to(root))}
        groups.append(row)
        print(json.dumps({key: row[key] for key in ("group", "status", "pass", "fail", "skip", "timeout", "elapsed_seconds")} ), flush=True)
    report = {"schema": "aioa.prompt03-regression.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
              "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip(),
              "tested_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
              "status": "PASS" if all(group["status"] == "PASS" for group in groups) else "FAIL", "groups": groups,
              "totals": {field: sum(group[field] for group in groups) for field in ("pass", "fail", "skip", "timeout")}}
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(str(output.relative_to(root)), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
