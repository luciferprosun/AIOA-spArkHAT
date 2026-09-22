"""Fresh-checkout launch regression for runtime/run_web.sh."""

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen


class RunWebWrapperTests(unittest.TestCase):
    def test_wrapper_launches_from_foreign_cwd_without_pythonpath(self):
        repo = Path(__file__).resolve().parents[1]
        wrapper = repo / "runtime" / "run_web.sh"

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        with tempfile.TemporaryDirectory() as foreign_cwd:
            process = subprocess.Popen(
                [str(wrapper), "--cpl-fixture", "--port", str(port)],
                cwd=foreign_cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                deadline = time.monotonic() + 15
                payload = None
                last_error = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
                            payload = json.load(response)
                        break
                    except (URLError, TimeoutError, OSError) as error:
                        last_error = error
                        time.sleep(0.2)

                if payload is None:
                    output = process.stdout.read() if process.stdout else ""
                    self.fail(f"web wrapper failed to become healthy: {last_error}\n{output}")
                self.assertEqual("ok", payload["status"])
                self.assertEqual("AIOA spArkHAT", payload["product_name"])
                self.assertEqual("local-only", payload["network"])
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
