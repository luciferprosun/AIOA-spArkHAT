"""Disposable real Git fixtures; never production repository or authority state."""

import subprocess
from pathlib import Path


class BareRepository:
    def __init__(self, root, files):
        self.path = Path(root)
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.path.parent),
            "LANG": "C.UTF-8",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
        subprocess.run(
            ["/usr/bin/git", "init", "--bare", "--initial-branch=main", str(self.path)],
            env=self.env,
            capture_output=True,
            check=True,
            timeout=10,
        )
        self.path.chmod(0o700)
        self.files = dict(files)
        self.base = self.commit(files)
        self.git("update-ref", "refs/heads/main", self.base)

    def mark_disposable(self):
        marker = self.path / ".aioa-disposable-bare"
        with marker.open("xb") as stream:
            stream.write(b"AIOA_DISPOSABLE_BARE_PATCH_V1\n")
        marker.chmod(0o600)

    def git(self, *args, data=None):
        result = subprocess.run(
            [
                "/usr/bin/git",
                "--no-replace-objects",
                "--git-dir=" + str(self.path),
                *args,
            ],
            input=data,
            env=self.env,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if result.returncode:
            raise RuntimeError("FIXTURE_GIT_FAILED")
        return result.stdout

    def commit(self, files, parent=None):
        root = {}
        for path, data in sorted(files.items()):
            cursor = root
            *parents, name = path.split("/")
            for part in parents:
                cursor = cursor.setdefault(part, {})
            cursor[name] = data

        def tree(node):
            records = []
            for name, value in sorted(node.items()):
                if isinstance(value, dict):
                    mode, kind, sha = "040000", "tree", tree(value)
                else:
                    mode, kind = "100644", "blob"
                    sha = (
                        self.git("hash-object", "-w", "--stdin", data=value)
                        .decode()
                        .strip()
                    )
                records.append(f"{mode} {kind} {sha}\t{name}".encode() + b"\0")
            return self.git("mktree", "-z", data=b"".join(records)).decode().strip()

        source = "tree " + tree(root) + "\n"
        if parent is not None:
            source += "parent " + parent + "\n"
        source += (
            "author Fixture <fixture@example.invalid> 100 +0000\n"
            "committer Fixture <fixture@example.invalid> 100 +0000\n\n"
            "Owner-approved Python fixture\n"
        )
        return (
            self.git(
                "hash-object", "-w", "-t", "commit", "--stdin", data=source.encode()
            )
            .decode()
            .strip()
        )
