"""Sequential, credentialless CI acceptance of the existing Core and broker.

Run through nz12_source_runner.py on an explicitly prepared Linux CI host.
No optional fallback converts a missing kernel prerequisite into a PASS.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from runtime.mission.project_recipe import snapshot_python_runtime

ROOT = Path(__file__).resolve().parents[1]


def main(output, codex):
    os.umask(0o077)
    output = output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    home, temporary = output / "home", output / "tmp"
    home.mkdir(mode=0o700)
    temporary.mkdir(mode=0o700)
    node = shutil.which("node")
    if node is None or subprocess.check_output(
        [node, "--version"], text=True, env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"},
    ).strip() != "v22.23.3":
        raise ValueError("PINNED_NODE_REQUIRED")
    environment = {
        "PATH": str(Path(sys.executable).parent) + ":" + str(Path(node).parent) + ":/usr/bin:/bin",
        "HOME": str(home), "TMPDIR": str(temporary), "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "AWS_CONFIG_FILE": "/dev/null", "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
        "AWS_EC2_METADATA_DISABLED": "true", "OTEL_TRACES_EXPORTER": "none",
        "OTEL_METRICS_EXPORTER": "none", "OTEL_LOGS_EXPORTER": "none",
        "XDG_RUNTIME_DIR": os.environ["XDG_RUNTIME_DIR"],
        "DBUS_SESSION_BUS_ADDRESS": os.environ["DBUS_SESSION_BUS_ADDRESS"],
    }
    manifest = snapshot_python_runtime(output / "runtime", include_git=True)
    manifest_file = output / "runtime.json"
    manifest_file.write_text(json.dumps({"manifest": manifest}, sort_keys=True) + "\n")
    matrix = output / "sandbox-matrix"
    matrix.mkdir(mode=0o700)
    (matrix / "PYTHON_RUNTIME_PREPARATION.json").write_bytes(manifest_file.read_bytes())
    commands = (
        ("repository-core-git-recovery-stop", sys.executable, "tests/nz11_kernel_acceptance.py",
         str(manifest_file), str(output / "kernel")),
        ("adversarial-observer", sys.executable, "tests/nz12_observer_acceptance.py",
         str(manifest_file), str(output / "observer")),
        ("mcp", sys.executable, "tests/host_unified_mcp.py"),
        ("local-git", sys.executable, "tests/host_unified_git.py"),
        ("chrome-rest", "/usr/bin/python3", "tests/mobile_device_console_browser.py"),
        ("sandbox-policy-matrix", sys.executable, "tests/sandbox_linux_acceptance.py",
         str(matrix), str(ROOT)),
        ("codex-protocol-no-inference", sys.executable, "tests/nz11_codex_acceptance.py",
         str(codex.resolve(strict=True)), str(output / "codex.json")),
    )
    receipts = []
    for label, python, script, *arguments in commands:
        log = output / (label + ".log")
        with log.open("xb") as stream:
            result = subprocess.run(
                [python, "-B", "tests/nz12_source_runner.py", script, *arguments],
                cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, timeout=1800, check=False,
            )
        row = {"gate": label, "exit_code": result.returncode,
               "status": "PASS" if result.returncode == 0 else "FAIL",
               "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        receipts.append(row)
        (output / "result.json").write_text(json.dumps(receipts, indent=2) + "\n")
        print(json.dumps(row), flush=True)
        if result.returncode:
            # These controlled fixtures never contain credentials; include only
            # the bounded diagnostic tail, not process environment or home files.
            print(log.read_text(errors="replace")[-12000:], file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--codex", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.output, args.codex))
