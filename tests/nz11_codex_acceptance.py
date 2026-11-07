"""Current official App Server, isolated diagnostics only; never a model turn."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).parent)]
from runtime.mission.codex_worker import OwnedCodexProtocol
from runtime.mission.worker import WorkerError


def main(binary, output):
    binary = binary.resolve(strict=True)
    environment = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"}
    args = [
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--cap-drop",
        "ALL",
        "--clearenv",
        "--tmpfs",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--dir",
        "/bin",
        "--ro-bind",
        str(binary),
        "/bin/codex",
        "--tmpfs",
        "/home",
        "--dir",
        "/home/probe",
        "--dir",
        "/home/probe/.codex",
        "--dir",
        "/tmp",
        "--dir",
        "/fixture",
        "--setenv",
        "HOME",
        "/home/probe",
        "--setenv",
        "CODEX_HOME",
        "/home/probe/.codex",
        "--setenv",
        "PATH",
        "/nonexistent",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--chdir",
        "/fixture",
        "--",
        "/bin/codex",
        "app-server",
        "--stdio",
        "-c",
        "analytics.enabled=false",
        "-c",
        "check_for_update_on_startup=false",
    ]
    child = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    transport = OwnedCodexProtocol(child.stdout.fileno(), child.stdin.fileno())
    try:
        initialized = transport.initialize()
        started = transport.thread_start()
        thread = started["thread"]["id"]
        assert isinstance(thread, str) and thread
        if not any(e["method"] == "thread/started" for e in transport.events):
            transport.next_event(seconds=3)
        assert any(e["method"] == "thread/started" for e in transport.events)
        transport.bind_turn(thread, "not-running-fixture-turn")
        try:
            transport.interrupt(thread, "not-running-fixture-turn")
            interrupt = "IDLE_ACKNOWLEDGED"
        except WorkerError as error:
            assert str(error) == "PROTOCOL_RPC_ERROR", str(error)
            interrupt = "NO_ACTIVE_TURN_REJECTED"
        timed_out = False
        for _ in range(10):
            try:
                transport.next_event(seconds=0.05)
            except WorkerError as error:
                assert str(error) == "PROTOCOL_TIMEOUT", str(error)
                timed_out = True
                break
        assert timed_out
        child.kill()
        child.wait(timeout=3)
        try:
            transport.next_event(seconds=1)
        except WorkerError as error:
            assert str(error) == "PROTOCOL_EOF", str(error)
        else:
            raise AssertionError("owned process crash was not detected")
        result = {
            "status": "PASS",
            "version": "0.167.0",
            "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "initialize": bool(initialized),
            "thread_start": True,
            "actual_event_methods": [e["method"] for e in transport.events],
            "interrupt_without_turn": interrupt,
            "timeout": "PASS",
            "owned_process_crash": "PASS",
            "isolated_network": "OFF",
            "host_files": "NONE_EXCEPT_PINNED_CODEX_BINARY",
            "host_shell": "ABSENT",
            "paid_calls": 0,
            "inference_turn": "NOT_RUN_OWNER_GO_REQUIRED",
            "worker_certification": "NOT_CERTIFIED",
            "synthetic_turn_cancel": "SEPARATE_UNIT_FIXTURE",
        }
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        return 0
    except WorkerError:
        if child.poll() is not None:
            detail = child.stderr.read(4096).decode(errors="replace")
            print("ISOLATED_PROBE_STARTUP:", detail, file=sys.stderr)
        raise
    finally:
        transport.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        child.stdin.close()
        child.stdout.close()
        child.stderr.close()


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
