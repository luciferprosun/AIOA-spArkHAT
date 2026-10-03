#!/usr/bin/env python3
"""Offline changed-file secret check. Output never includes matched values."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import subprocess


PATTERNS = {
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "BEARER_LITERAL": re.compile(r"(?i)\bBearer[ \t]+[A-Za-z0-9_.~+/=-]{16,}"),
    "NEBIUS_KEY": re.compile(r"\b(?:neb_[A-Za-z0-9_-]{20,}|nebius_(?=[A-Za-z0-9_-]*[A-Z])[A-Za-z0-9_-]{20,}|v1\.[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{20,})\b"),
    "OPENAI_KEY": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    "AWS_ACCESS_KEY": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}
ASSIGNMENT = re.compile(
    r"(?im)\b(?:[a-z0-9_]*(?:api[_-]?(?:key|token)|access[_-]?token|auth[_-]?token|secret|password)[a-z0-9_]*|(?:[a-z0-9_]+_)?token)"
    r"[\"']?\s*[:=]\s*[\"']([A-Za-z0-9_+/=.-]{20,})[\"']"
)
SHELL_ASSIGNMENT = re.compile(
    r"(?m)^[ \t]*(?:export[ \t]+)?[A-Z0-9_]*(?:API_?KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*="
    r"([A-Za-z0-9_+/=.-]{20,})(?=[ \t\r\n#;]|$)"
)


def entropy(value: str) -> float:
    counts = Counter(value)
    return -sum((n / len(value)) * math.log2(n / len(value)) for n in counts.values())


def scan_text(text: str) -> tuple[str, ...]:
    """Return category names only; callers cannot accidentally print candidates."""
    categories = [name for name, pattern in PATTERNS.items() if pattern.search(text)]
    assignments = [*ASSIGNMENT.finditer(text), *SHELL_ASSIGNMENT.finditer(text)]
    if any(entropy(match.group(1)) >= 3.5 for match in assignments):
        categories.append("HIGH_ENTROPY_TOKEN_ASSIGNMENT")
    return tuple(sorted(categories))


def changed_paths(root: Path, base: str) -> list[str]:
    def git(*args: str) -> list[str]:
        result = subprocess.run(["git", "-C", str(root), *args], check=True,
                                capture_output=True)
        return [item.decode("utf-8", "surrogateescape")
                for item in result.stdout.split(b"\0") if item]
    return sorted(set(git("diff", "--name-only", "-z", "--diff-filter=ACMRTUXB", base)
                      + git("ls-files", "--others", "--exclude-standard", "-z")))


def scan_files(root: Path, paths: list[str]) -> dict:
    results = []
    for relative in sorted(set(paths)):
        path = root / relative
        # Never follow a changed symlink to secrets outside the repository.
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            results.append({"path": relative, "category": "UNSAFE_PATH", "status": "FAIL"})
            continue
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("size")
            raw = path.read_bytes()
            categories = scan_text(raw.decode("utf-8", "replace"))
        except (OSError, ValueError):
            categories = ("UNREADABLE_OR_OVERSIZED_FILE",)
        for category in categories or ("ALL_REQUIRED_CATEGORIES",):
            results.append({"path": relative, "category": category,
                            "status": "FAIL" if categories else "PASS"})
    return {"schema": "aioa.changed-file-secret-scan.v1",
            "status": "FAIL" if any(row["status"] == "FAIL" for row in results) else "PASS",
            "categories_checked": sorted([*PATTERNS, "HIGH_ENTROPY_TOKEN_ASSIGNMENT"]),
            "files_checked": len(set(row["path"] for row in results)), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    try:
        report = scan_files(args.root, args.paths or changed_paths(args.root, args.base))
    except (OSError, subprocess.CalledProcessError):
        report = {"schema": "aioa.changed-file-secret-scan.v1", "status": "FAIL",
                  "results": [{"path": ".", "category": "GIT_ENUMERATION", "status": "FAIL"}]}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
