#!/usr/bin/env python3
"""Scan one exact exported B5 root filesystem without printing secret values."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aioa_cloudops_agent.persistence.local_integrity import (  # noqa: E402
    LocalIntegrityError,
    atomic_write_private_json,
)

DEFAULT_OUTPUT: Final = ROOT / ".local" / "b5-b6" / "image-privacy-scan.json"
_SHA256: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_ID: Final = re.compile(r"^[0-9a-f]{64}$")
_COMMIT: Final = re.compile(r"^[0-9a-f]{40}$")
_AWS_ACCESS_KEY: Final = re.compile(rb"(?:AKIA|ASIA)[0-9A-Z]{16}")
_AWS_SECRET_VALUE: Final = re.compile(
    rb"(?i)aws_secret_access_key\s*[=:]\s*([A-Za-z0-9/+=]{20,})"
)
_PRIVATE_KEY_BLOCK: Final = re.compile(
    rb"-----BEGIN (?P<kind>(?:RSA |EC |OPENSSH )?PRIVATE KEY)-----\r?\n"
    rb"(?:[A-Za-z0-9+/=]{32,}\r?\n){2,}"
    rb"-----END (?P=kind)-----"
)
_PUBLIC_EXAMPLE_ACCESS_KEY_SHA256: Final = frozenset(
    {
        "1a5d44a2dca19669d72edf4c4f1c27c4c1ca4b4408fbb17f6ce4ad452d78ddb3",
        "843e06a72dff62a6b86729f8f55cfcfdd2d102105f2fba88b7401be239827d3e",
        "a9792a142a82899acc92c05206f4d26e80fb39d037bbfdbd4b17bd58c87dd248",
        "c6ea27c534f993d31f0aef882e3d200e7b87470c379ae79c8f9b19d3bd363dc9",
    }
)
_PUBLIC_EXAMPLE_SECRET_VALUE_SHA256: Final = frozenset(
    {
        "78314b11be2e581549ac1c4f616563fad3fdf0c3b71678f6e2299182080e0598",
    }
)
_FORBIDDEN_SUFFIXES: Final = frozenset({".key", ".p12", ".pfx"})


class ImageScanError(RuntimeError):
    """A public-safe image scan setup or output failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _walk_regular_files(rootfs: Path) -> Iterator[tuple[PurePosixPath, Path, int]]:
    for directory, names, filenames in os.walk(rootfs, topdown=True, followlinks=False):
        names[:] = sorted(
            name for name in names if not (Path(directory) / name).is_symlink()
        )
        for name in sorted(filenames):
            path = Path(directory) / name
            try:
                metadata = path.lstat()
            except OSError as error:
                raise ImageScanError("B5_IMAGE_SCAN_PATH_UNREADABLE") from error
            relative = PurePosixPath(path.relative_to(rootfs).as_posix())
            if stat.S_ISLNK(metadata.st_mode):
                continue
            if stat.S_ISREG(metadata.st_mode):
                yield relative, path, metadata.st_size


def _path_finding(relative: PurePosixPath) -> str | None:
    name = relative.name
    if ".git" in relative.parts:
        return "GIT_METADATA"
    if name == ".env" or name.startswith(".env."):
        return "ENV_FILE"
    if name == "operator.token":
        return "BAKED_OPERATOR_TOKEN"
    if relative.suffix.casefold() in _FORBIDDEN_SUFFIXES:
        return "PRIVATE_KEY_FILE"
    if ".aws" in relative.parts and name in {"config", "credentials"}:
        return "AWS_CREDENTIAL_FILE"
    return None


def _content_findings(path: Path) -> tuple[str, ...]:
    findings: set[str] = set()
    overlap = b""
    try:
        with path.open("rb") as handle:
            current: bytes | None = handle.read(1024 * 1024)
            if b"\0" in current:
                return ()
            while True:
                if not current:
                    break
                sample = overlap + current
                if any(
                    hashlib.sha256(match.group()).hexdigest()
                    not in _PUBLIC_EXAMPLE_ACCESS_KEY_SHA256
                    for match in _AWS_ACCESS_KEY.finditer(sample)
                ):
                    findings.add("AWS_ACCESS_KEY")
                if any(
                    hashlib.sha256(match.group(1)).hexdigest()
                    not in _PUBLIC_EXAMPLE_SECRET_VALUE_SHA256
                    for match in _AWS_SECRET_VALUE.finditer(sample)
                ):
                    findings.add("AWS_SECRET_VALUE")
                if _PRIVATE_KEY_BLOCK.search(sample) is not None:
                    findings.add("PRIVATE_KEY_MATERIAL")
                overlap = sample[-16_384:]
                current = handle.read(1024 * 1024)
    except OSError as error:
        raise ImageScanError("B5_IMAGE_SCAN_FILE_UNREADABLE") from error
    return tuple(sorted(findings))


def scan_rootfs(
    rootfs: Path,
    *,
    image_id: str,
    image_digest: str,
    source_commit: str,
) -> dict[str, object]:
    """Return a deterministic image-export privacy receipt with no matched values."""

    if (
        not isinstance(rootfs, Path)
        or not rootfs.is_absolute()
        or rootfs.is_symlink()
        or not rootfs.is_dir()
        or rootfs == Path("/")
        or _IMAGE_ID.fullmatch(image_id) is None
        or _SHA256.fullmatch(image_digest) is None
        or _COMMIT.fullmatch(source_commit) is None
    ):
        raise ImageScanError("B5_IMAGE_SCAN_INPUT_INVALID")
    application_root = rootfs / "usr/local/lib/python3.12/site-packages/aioa_cloudops_agent"
    python_binary = rootfs / "usr/local/bin/python"
    if not application_root.is_dir() or not python_binary.exists():
        raise ImageScanError("B5_IMAGE_SCAN_ROOTFS_CONTRACT_INVALID")

    findings: list[dict[str, str]] = []
    regular_files = 0
    scanned_bytes = 0
    application_files = 0
    for relative, path, size in _walk_regular_files(rootfs):
        regular_files += 1
        scanned_bytes += size
        if relative.parts[:5] == (
            "usr",
            "local",
            "lib",
            "python3.12",
            "site-packages",
        ) and len(relative.parts) > 5 and relative.parts[5] == "aioa_cloudops_agent":
            application_files += 1
        path_reason = _path_finding(relative)
        if path_reason is not None:
            findings.append({"path": relative.as_posix(), "reason": path_reason})
        for reason in _content_findings(path):
            findings.append({"path": relative.as_posix(), "reason": reason})

    findings.sort(key=lambda item: (item["path"], item["reason"]))
    material: dict[str, object] = {
        "application_files_scanned": application_files,
        "aws_calls": 0,
        "aws_mutations": 0,
        "checks": {
            "baked_operator_token_absent": not any(
                finding["reason"] == "BAKED_OPERATOR_TOKEN" for finding in findings
            ),
            "credential_files_absent": not any(
                finding["reason"] in {"AWS_CREDENTIAL_FILE", "ENV_FILE"}
                for finding in findings
            ),
            "git_metadata_absent": not any(
                finding["reason"] == "GIT_METADATA" for finding in findings
            ),
            "private_key_material_absent": not any(
                finding["reason"] in {"PRIVATE_KEY_FILE", "PRIVATE_KEY_MATERIAL"}
                for finding in findings
            ),
            "raw_aws_credentials_absent": not any(
                finding["reason"] in {"AWS_ACCESS_KEY", "AWS_SECRET_VALUE"}
                for finding in findings
            ),
        },
        "external_network_connections": 0,
        "findings": findings,
        "findings_count": len(findings),
        "image_digest": image_digest,
        "image_id": image_id,
        "receipt_type": "AIOA_B5_IMAGE_EXPORT_PRIVACY_SCAN",
        "regular_files_scanned": regular_files,
        "remote_pushes": 0,
        "scanned_bytes": scanned_bytes,
        "schema_version": 1,
        "source_commit": source_commit,
        "status": "PASS" if not findings and application_files > 0 else "FAIL",
    }
    return {
        **material,
        "receipt_sha256": hashlib.sha256(_canonical_bytes(material)).hexdigest(),
    }


def _write(path: Path, receipt: Mapping[str, object]) -> None:
    private_root = (ROOT / ".local").resolve(strict=False)
    if (
        not path.resolve(strict=False).is_relative_to(private_root)
        or path.is_symlink()
        or any(parent.is_symlink() for parent in path.parents if parent.exists())
    ):
        raise ImageScanError("B5_IMAGE_SCAN_OUTPUT_UNSAFE")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        atomic_write_private_json(path, dict(receipt))
    except (LocalIntegrityError, OSError, TypeError, ValueError) as error:
        raise ImageScanError("B5_IMAGE_SCAN_OUTPUT_UNAVAILABLE") from error


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        receipt = scan_rootfs(
            args.rootfs.resolve(strict=True),
            image_id=args.image_id,
            image_digest=args.image_digest,
            source_commit=args.source_commit,
        )
        _write(args.output, receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0 if receipt["status"] == "PASS" else 1
    except (ImageScanError, OSError) as error:
        reason = error.reason if isinstance(error, ImageScanError) else "B5_IMAGE_SCAN_UNAVAILABLE"
        print(
            json.dumps(
                {
                    "aws_mutations": 0,
                    "reason": reason,
                    "remote_pushes": 0,
                    "status": "FAIL",
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
