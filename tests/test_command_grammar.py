import inspect
import unittest

from runtime.tools import command_grammar
from runtime.tools.command_grammar import validate_command_shape


class CommandGrammarTests(unittest.TestCase):
    def assert_required_shape(self, result):
        self.assertIsInstance(result, dict)
        self.assertEqual(
            {
                "status",
                "family",
                "base",
                "confidence",
                "danger",
                "reasons",
                "matched_pattern_id",
            },
            set(result),
        )

    def test_valid_common_shapes(self):
        cases = [
            ("systemctl status sshd", "systemctl"),
            ("systemctl restart httpd", "systemctl"),
            ("dnf install httpd", "dnf"),
            ("dnf search nginx", "dnf"),
            ("firewall-cmd --list-all", "firewall-cmd"),
            ("semanage port -l", "semanage"),
            ("chmod 640 /etc/example.conf", "chmod"),
            ("podman ps", "podman"),
        ]
        for command, base in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertEqual(base, result["base"])
                self.assertIn(result["status"], {"family", "exact"})
                self.assertNotEqual("grammar_reject", result["confidence"])

    def test_low_risk_read_only_families(self):
        cases = [
            ("cat /etc/hosts", "cat"),
            ("less /var/log/messages", "less"),
            ("head -n 20 /var/log/messages", "head"),
            ("tail -f /var/log/messages", "tail"),
            ("ls -l /etc", "ls"),
            ("pwd", "pwd"),
            ("tree /etc", "tree"),
            ("basename /etc/passwd", "basename"),
            ("dirname /etc/passwd", "dirname"),
            ("grep root /etc/passwd", "grep"),
            ("grep -R sshd /etc", "grep"),
            ('find /var/log -type f -name "*.log"', "find"),
            ("journalctl -u sshd", "journalctl"),
            ("journalctl -xe", "journalctl"),
            ("journalctl --since today", "journalctl"),
            ("rpm -qa", "rpm"),
            ("rpm -q bash", "rpm"),
            ("rpm -qi bash", "rpm"),
            ("rpm -ql bash", "rpm"),
        ]
        for command, base in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertEqual(base, result["base"])
                self.assertIn(result["status"], {"exact", "family", "partial"})
                self.assertNotEqual("reject", result["status"])
                self.assertNotEqual("suspicious", result["status"])
                self.assertEqual("read_only", result["danger"])

    def test_suspicious_or_rejected_shapes(self):
        cases = [
            ("systemctl install nginx", "suspicious"),
            ("dnf status httpd", "suspicious"),
            ("journalctl restart sshd", "suspicious"),
            ("chmod user file", "suspicious"),
            ("/etc/passwd", "reject"),
            ("--reload", "reject"),
            ("$PATH", "reject"),
            ("*.log", "reject"),
            ("systemctl status 'unterminated", "reject"),
        ]
        for command, status in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertEqual(status, result["status"])

    def test_low_risk_families_reject_ambiguous_or_destructive_shapes(self):
        cases = [
            "find / -delete",
            "find /tmp -exec rm -rf {} \\;",
            "grep",
            "cat",
            "journalctl restart sshd",
            "rpm install bash",
            "tree --delete /tmp",
        ]
        for command in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertIn(result["status"], {"suspicious", "reject"})
                self.assertNotEqual("exact", result["status"])

    def test_gt14_inspection_families_are_read_only(self):
        cases = [
            ("df -h", "df"),
            ("du -sh /var/log", "du"),
            ("free -m", "free"),
            ("uname -a", "uname"),
            ("uptime -p", "uptime"),
            ("dmesg -T", "dmesg"),
            ("lsblk", "lsblk"),
            ("blkid", "blkid"),
            ("smartctl -a /dev/sda", "smartctl"),
            ("nvme list", "nvme"),
            ("nvme smart-log /dev/nvme0", "nvme"),
            ("id", "id"),
            ("id root", "id"),
            ("whoami", "whoami"),
            ("groups", "groups"),
            ("groups root", "groups"),
            ("getent passwd root", "getent"),
            ("getent group wheel", "getent"),
            ("passwd -S root", "passwd"),
            ("chage -l root", "chage"),
            ("ss -tuln", "ss"),
            ("ping -c 4 8.8.8.8", "ping"),
            ("dig example.com", "dig"),
            ("host example.com", "host"),
            ("tracepath 8.8.8.8", "tracepath"),
            ("ethtool eth0", "ethtool"),
            ("ethtool -S eth0", "ethtool"),
            ("nmcli connection show", "nmcli"),
            ("nmcli device status", "nmcli"),
        ]
        for command, base in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertEqual(base, result["base"])
                self.assertIn(result["status"], {"exact", "family", "partial"})
                self.assertEqual("read_only", result["danger"])

    def test_gt14_state_changing_forms_are_not_read_only_safe(self):
        cases = [
            "smartctl -t short /dev/sda",
            "dmesg -C",
            "nvme format /dev/nvme0",
            "passwd root",
            "passwd --stdin user",
            "chage -E 0 user",
            "useradd testuser",
            "usermod -aG wheel user",
            "userdel user",
            "groupadd devs",
            "groupdel devs",
            "nmcli connection modify eth0 ipv4.addresses 192.168.1.10/24",
            "nmcli connection down eth0",
            "nmcli connection up eth0",
            "ping -f 8.8.8.8",
            "ip link set eth0 down",
            "ip addr add 192.168.1.10/24 dev eth0",
            "ip route add default via 192.168.1.1",
            "ethtool -s eth0 speed 1000",
            "fdisk /dev/sdb",
            "parted mklabel gpt /dev/sdb",
            "pvcreate /dev/sdb",
            "vgcreate vg0 /dev/sdb",
            "lvcreate -n data -L 1G vg0",
            "mkfs.xfs /dev/sdb1",
            "mkswap /dev/sdb2",
            "swapon /dev/sdb2",
            "swapoff /dev/sdb2",
            "cryptsetup luksFormat /dev/sdb1",
            "setenforce 0",
            "firewall-cmd --panic-on",
            "auditctl -w /etc/passwd -p wa",
            "wipefs -a /dev/sdb",
            "virsh destroy vm1",
            "git reset --hard",
            "curl -H 'Authorization: Bearer TOKEN' https://example.com",
        ]
        for command in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertFalse(
                    result["status"] in {"exact", "family", "partial"}
                    and result["danger"] == "read_only",
                    result,
                )

    def test_gt15_systemctl_read_only_expansion(self):
        cases = [
            "systemctl list-units",
            "systemctl list-unit-files",
            "systemctl is-active sshd",
            "systemctl is-enabled sshd",
            "systemctl is-failed sshd",
            "systemctl cat sshd",
            "systemctl show sshd",
            "systemctl show -p MainPID sshd",
            "systemctl --user status sshd",
        ]
        for command in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertEqual("systemctl", result["base"])
                self.assertIn(result["status"], {"exact", "family", "partial"})
                self.assertEqual("read_only", result["danger"])

    def test_gt15_systemctl_state_changes_remain_non_read_only(self):
        cases = [
            "systemctl start sshd",
            "systemctl stop sshd",
            "systemctl restart sshd",
            "systemctl reload sshd",
            "systemctl enable sshd",
            "systemctl disable sshd",
            "systemctl mask sshd",
            "systemctl unmask sshd",
            "systemctl isolate rescue.target",
            "systemctl poweroff",
            "systemctl reboot",
            "systemctl install nginx",
        ]
        for command in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertFalse(
                    result["status"] in {"exact", "family", "partial"}
                    and result["danger"] == "read_only",
                    result,
                )

    def test_gt16_package_query_forms_are_read_only(self):
        cases = [
            ("dnf history", "dnf"),
            ("dnf history list", "dnf"),
            ("dnf history info", "dnf"),
            ("dnf list installed", "dnf"),
            ("dnf list available", "dnf"),
            ("dnf info bash", "dnf"),
            ("dnf search httpd", "dnf"),
            ("dnf provides /usr/bin/python3", "dnf"),
            ("dnf repoquery bash", "dnf"),
            ("repoquery --requires bash", "repoquery"),
            ("repoquery --list bash", "repoquery"),
            ("rpm -q bash", "rpm"),
            ("rpm -qi bash", "rpm"),
            ("rpm -ql bash", "rpm"),
            ("rpm -qf /usr/bin/bash", "rpm"),
            ("rpm -Va", "rpm"),
        ]
        for command, base in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertEqual(base, result["base"])
                self.assertIn(result["status"], {"exact", "family", "partial"})
                self.assertNotEqual("reject", result["status"])
                self.assertEqual("read_only", result["danger"])

    def test_gt16_package_state_changes_remain_non_read_only(self):
        cases = [
            "dnf install httpd",
            "dnf remove httpd",
            "dnf update",
            "dnf upgrade",
            'dnf groupinstall "Server with GUI"',
            "dnf history undo 5",
            "dnf history rollback 5",
            "rpm -i package.rpm",
            "rpm -Uvh package.rpm",
            "rpm -e package",
            "flatpak install flathub org.gimp.GIMP",
            "flatpak update",
            "snap install package_name",
            "snap refresh",
            "snap remove package_name",
            "rpm2cpio package.rpm | cpio -idmv",
        ]
        for command in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertFalse(
                    result["status"] in {"exact", "family", "partial"}
                    and result["danger"] == "read_only",
                    result,
                )

    def test_gt17_tar_listing_forms_are_read_only(self):
        cases = [
            "tar -tf archive.tar",
            "tar -tvf archive.tar",
            "tar --list -f archive.tar",
            "tar --list --file archive.tar",
        ]
        for command in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertEqual("tar", result["base"])
                self.assertIn(result["status"], {"exact", "family", "partial"})
                self.assertNotEqual("reject", result["status"])
                self.assertEqual("read_only", result["danger"])

    def test_gt17_archive_write_or_extract_forms_remain_non_read_only(self):
        cases = [
            "tar -xvf archive.tar",
            "tar -cvf archive.tar file",
            "tar -rvf archive.tar file",
            "tar -uvf archive.tar file",
            "tar --extract -f archive.tar",
            "tar --create -f archive.tar file",
            "tar --delete -f archive.tar file",
            "rpm2cpio package.rpm | cpio -idmv",
            "gzip file",
            "gunzip file.gz",
            "zip archive.zip file",
            "unzip archive.zip",
        ]
        for command in cases:
            with self.subTest(command=command):
                result = validate_command_shape(command)
                self.assert_required_shape(result)
                self.assertFalse(
                    result["status"] in {"exact", "family", "partial"}
                    and result["danger"] == "read_only",
                    result,
                )

    def test_unknown_base_is_not_exact(self):
        result = validate_command_shape("journalctl restart sshd")
        self.assert_required_shape(result)
        self.assertIn(result["status"], {"suspicious", "reject"})
        self.assertNotEqual("exact", result["status"])

    def test_pipeline_is_suspicious(self):
        result = validate_command_shape("systemctl status sshd | grep Active")
        self.assert_required_shape(result)
        self.assertEqual("suspicious", result["status"])
        self.assertIn("shell_composition_present", result["reasons"])

    def test_parser_never_executes_commands(self):
        source = inspect.getsource(command_grammar)
        forbidden = ["subprocess", "os.system", "Popen", "run(", "exec("]
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_module_documents_shellcheck_and_tree_sitter_boundary(self):
        doc = command_grammar.__doc__ or ""
        self.assertIn("does not replace ShellCheck", doc)
        self.assertIn("tree-sitter-bash", doc)
        self.assertIn("non-executing", doc)

    def test_no_shellcheck_or_tree_sitter_dependency(self):
        source = inspect.getsource(command_grammar)
        self.assertNotIn("import shellcheck", source.lower())
        self.assertNotIn("tree_sitter", source)
        self.assertNotIn("tree-sitter", source.replace("tree-sitter-bash", "documented-boundary"))


if __name__ == "__main__":
    unittest.main()
