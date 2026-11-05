import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class CommandGrammarCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "runtime.tools.command_grammar_cli", *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_systemctl_status_returns_json_family_or_exact(self):
        result = self.run_cli("systemctl status sshd")
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("systemctl status sshd", payload[0]["input"])
        self.assertEqual("systemctl", payload[0]["base"])
        self.assertIn(payload[0]["status"], {"exact", "family"})

    def test_dnf_status_is_not_exact(self):
        result = self.run_cli("dnf status httpd")
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("dnf", payload[0]["base"])
        self.assertIn(payload[0]["status"], {"suspicious", "reject"})
        self.assertNotEqual("exact", payload[0]["status"])

    def test_no_args_exits_two_and_prints_usage(self):
        result = self.run_cli()
        self.assertEqual(2, result.returncode)
        self.assertIn("Usage:", result.stderr)

    def test_output_parses_as_json(self):
        result = self.run_cli("podman ps")
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsInstance(payload, list)
        self.assertEqual("podman ps", payload[0]["input"])

    def test_cli_does_not_execute_shell_commands(self):
        marker = Path("/tmp/aoia_should_not_exist")
        if marker.exists():
            marker.unlink()

        result = self.run_cli("echo safe && touch /tmp/aoia_should_not_exist")
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("suspicious", payload[0]["status"])
        self.assertFalse(marker.exists())

    def test_direct_file_execution_works(self):
        result = subprocess.run(
            [
                sys.executable,
                "runtime/tools/command_grammar_cli.py",
                "firewall-cmd --list-all",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("firewall-cmd", payload[0]["base"])

    def test_stdin_mode_classifies_two_commands(self):
        result = subprocess.run(
            [sys.executable, "-m", "runtime.tools.command_grammar_cli", "--stdin"],
            cwd=REPO_ROOT,
            input="systemctl status sshd\ndnf status httpd\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(2, len(payload))
        self.assertEqual("systemctl", payload[0]["base"])
        self.assertEqual("dnf", payload[1]["base"])
        self.assertNotEqual("exact", payload[1]["status"])

    def test_stdin_mode_classifies_new_read_only_families(self):
        result = subprocess.run(
            [sys.executable, "-m", "runtime.tools.command_grammar_cli", "--stdin"],
            cwd=REPO_ROOT,
            input="cat /etc/hosts\njournalctl -u sshd\nrpm -q bash\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(3, len(payload))
        self.assertEqual(["cat", "journalctl", "rpm"], [item["base"] for item in payload])
        self.assertEqual(["read_only", "read_only", "read_only"], [item["danger"] for item in payload])

    def test_stdin_mode_classifies_gt14_inspection_families(self):
        result = subprocess.run(
            [sys.executable, "-m", "runtime.tools.command_grammar_cli", "--stdin"],
            cwd=REPO_ROOT,
            input="df -h\nss -tuln\nid root\ngetent passwd root\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(4, len(payload))
        self.assertEqual(["df", "ss", "id", "getent"], [item["base"] for item in payload])
        self.assertEqual(["read_only", "read_only", "read_only", "read_only"], [item["danger"] for item in payload])

    def test_stdin_mode_classifies_gt15_systemctl_readouts(self):
        result = subprocess.run(
            [sys.executable, "-m", "runtime.tools.command_grammar_cli", "--stdin"],
            cwd=REPO_ROOT,
            input="systemctl list-units\nsystemctl is-active sshd\nsystemctl show sshd\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(3, len(payload))
        self.assertEqual(["systemctl", "systemctl", "systemctl"], [item["base"] for item in payload])
        self.assertEqual(["read_only", "read_only", "read_only"], [item["danger"] for item in payload])

    def test_stdin_mode_classifies_gt16_package_queries(self):
        result = subprocess.run(
            [sys.executable, "-m", "runtime.tools.command_grammar_cli", "--stdin"],
            cwd=REPO_ROOT,
            input="dnf info bash\nrepoquery --requires bash\nrpm -q bash\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(3, len(payload))
        self.assertEqual(["dnf", "repoquery", "rpm"], [item["base"] for item in payload])
        self.assertEqual(["read_only", "read_only", "read_only"], [item["danger"] for item in payload])

    def test_stdin_mode_classifies_gt17_tar_listing(self):
        result = subprocess.run(
            [sys.executable, "-m", "runtime.tools.command_grammar_cli", "--stdin"],
            cwd=REPO_ROOT,
            input="tar -tf archive.tar\ntar -tvf archive.tar\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(2, len(payload))
        self.assertEqual(["tar", "tar"], [item["base"] for item in payload])
        self.assertEqual(["read_only", "read_only"], [item["danger"] for item in payload])

    def test_stdin_mode_ignores_empty_lines(self):
        result = subprocess.run(
            [sys.executable, "-m", "runtime.tools.command_grammar_cli", "--stdin"],
            cwd=REPO_ROOT,
            input="\nsystemctl status sshd\n\n  \npodman ps\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(2, len(payload))
        self.assertEqual(["systemctl status sshd", "podman ps"], [item["input"] for item in payload])

    def test_stdin_mode_does_not_execute_shell_commands(self):
        marker = Path("/tmp/aoia_grammar_should_not_exist")
        if marker.exists():
            marker.unlink()

        result = subprocess.run(
            [sys.executable, "-m", "runtime.tools.command_grammar_cli", "--stdin"],
            cwd=REPO_ROOT,
            input="echo safe && touch /tmp/aoia_grammar_should_not_exist\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("suspicious", payload[0]["status"])
        self.assertFalse(marker.exists())

    def test_positional_multi_command_mode_still_works(self):
        result = self.run_cli("systemctl status sshd", "dnf status httpd")
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(2, len(payload))
        self.assertEqual("systemctl", payload[0]["base"])
        self.assertEqual("dnf", payload[1]["base"])


if __name__ == "__main__":
    unittest.main()
