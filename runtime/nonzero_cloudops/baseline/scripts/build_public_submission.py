#!/usr/bin/env python3
"""Build a deterministic, sanitized local publication candidate from Git blobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
BUNDLE_NAME: Final = "aioa-agents-for-humans-publication-candidate"
ARCHIVE_NAME: Final = f"{BUNDLE_NAME}.zip"
_COMMIT: Final = re.compile(r"^[0-9a-f]{40}$")
_CLASSIFICATIONS: Final = frozenset(
    {
        "GENERATED",
        "LEGAL_REVIEW",
        "PRIVATE_INTERNAL",
        "PUBLIC_ALLOWED",
        "PUBLIC_REQUIRED",
        "SECRET_RISK",
    }
)
_SECRET_SUFFIXES: Final = frozenset(
    {".credential", ".credentials", ".key", ".p12", ".pem", ".pfx"}
)
_LEGAL_PATHS: Final = frozenset({"LICENSE", "PRIOR-ART.md"})
_REQUIRED_EXACT: Final = frozenset(
    {
        ".dockerignore",
        ".env.example",
        "Dockerfile",
        "MANIFEST.in",
        "docs/JUDGE_EXPERIENCE.md",
        "docs/JUDGE_SANDBOX.md",
        "docs/PORTABLE_RUNTIME.md",
        "docs/RELIABILITY_SECURITY.md",
        "docs/operations/container-judge-certification.md",
        "docs/submission/ARCHITECTURE.md",
        "docs/submission/DEMO_SCRIPT_DRAFT.md",
        "docs/submission/DEVPOST_CLAIMS_MATRIX.md",
        "docs/submission/PRIOR_ART_DISCLOSURE.md",
        "docs/submission/PUBLICATION_EXCLUSIONS.md",
        "docs/submission/REPRODUCIBILITY.md",
        "docs/submission/demo-runbook.md",
        "docs/submission/devpost-draft.md",
        "docs/submission/public/README.md",
        "pyproject.toml",
        "requirements/build.lock",
        "requirements/portable.lock",
        "scripts/build_public_submission.py",
        "scripts/run_b5_container_gate.py",
        "scripts/run_portable_demo.py",
        "scripts/scan_public_submission.py",
    }
)
_REQUIRED_PREFIXES: Final = (
    "docs/assets/",
    "docs/evidence/release/portable-b5-",
    "src/",
)
_PRIVATE_PREFIXES: Final = (
    "docs/audit/",
    "docs/audits/",
    "docs/evidence/deployment/",
    "docs/evidence/submission/",
    "docs/reports/",
    "scripts/day15/",
)
_PRIVATE_EXACT: Final = frozenset(
    {
        "docs/BOOTSTRAP_REPORT_2026-08-22.md",
        "docs/DECISIONS.md",
        "docs/PROJECT_CHARTER.md",
        "docs/ROADMAP_STATUS.md",
    }
)
_PRIVATE_NAME_PREFIXES: Final = (
    "docs/architecture/day-",
    "docs/operations/day15-",
    "requirements/day15-",
    "tests/unit/test_day15_",
)
_OVERLAY_README: Final = "docs/submission/public/README.md"
_EXCLUSIONS_DOC: Final = "docs/submission/PUBLICATION_EXCLUSIONS.md"
_B5_ATTESTATION: Final = "docs/evidence/release/portable-b5-build-complete-attestation.json"


class PublicBundleError(RuntimeError):
    """One deterministic export invariant failed closed."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class SourceEntry:
    path: str
    mode: int
    oid: str


@dataclass(frozen=True)
class Classification:
    name: str
    included: bool
    reason: str


def _canonical_bytes(value: object, *, pretty: bool = False) -> bytes:
    options: dict[str, object] = {
        "allow_nan": False,
        "ensure_ascii": True,
        "sort_keys": True,
    }
    if pretty:
        options["indent"] = 2
    else:
        options["separators"] = (",", ":")
    return (json.dumps(value, **options) + ("\n" if pretty else "")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise PublicBundleError("PUBLIC_BUNDLE_FILE_UNREADABLE") from error


def _git_environment() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _git(
    root: Path,
    arguments: Sequence[str],
    *,
    failure_reason: str,
) -> bytes:
    try:
        result = subprocess.run(
            ("git", *arguments),
            cwd=root,
            env=_git_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PublicBundleError(failure_reason) from error
    if result.returncode != 0 or len(result.stdout) > 25_000_000:
        raise PublicBundleError(failure_reason)
    return result.stdout


def _safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise PublicBundleError("PUBLIC_SOURCE_PATH_INVALID")
    return value


def source_entries(root: Path, source_ref: str) -> tuple[SourceEntry, ...]:
    """List every blob in one staged index or exact commit."""

    if source_ref == "INDEX":
        raw = _git(
            root,
            ("ls-files", "--stage", "-z"),
            failure_reason="PUBLIC_SOURCE_INVENTORY_FAILED",
        )
    elif _COMMIT.fullmatch(source_ref) is not None:
        resolved = _git(
            root,
            ("rev-parse", "--verify", f"{source_ref}^{{commit}}"),
            failure_reason="PUBLIC_SOURCE_COMMIT_UNAVAILABLE",
        ).decode("ascii").strip()
        if resolved != source_ref:
            raise PublicBundleError("PUBLIC_SOURCE_COMMIT_MISMATCH")
        raw = _git(
            root,
            ("ls-tree", "-r", "-z", source_ref),
            failure_reason="PUBLIC_SOURCE_INVENTORY_FAILED",
        )
    else:
        raise PublicBundleError("PUBLIC_SOURCE_REF_INVALID")

    entries: list[SourceEntry] = []
    seen: set[str] = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            path = _safe_path(encoded_path.decode("utf-8"))
            fields = metadata.decode("ascii").split()
            if source_ref == "INDEX":
                mode_text, oid, stage = fields
                if stage != "0":
                    raise ValueError("unmerged index")
            else:
                mode_text, object_type, oid = fields
                if object_type != "blob":
                    raise ValueError("non-blob")
            mode = int(mode_text, 8)
        except (UnicodeDecodeError, ValueError) as error:
            raise PublicBundleError("PUBLIC_SOURCE_INVENTORY_INVALID") from error
        if mode not in {0o100644, 0o100755}:
            raise PublicBundleError("PUBLIC_SOURCE_SYMLINK_OR_SPECIAL_FILE")
        if path in seen:
            raise PublicBundleError("PUBLIC_SOURCE_DUPLICATE_PATH")
        seen.add(path)
        entries.append(SourceEntry(path=path, mode=mode, oid=oid))
    if not entries:
        raise PublicBundleError("PUBLIC_SOURCE_INVENTORY_EMPTY")
    return tuple(sorted(entries, key=lambda item: item.path))


def _read_blob(root: Path, source_ref: str, path: str) -> bytes:
    object_name = f":{path}" if source_ref == "INDEX" else f"{source_ref}:{path}"
    return _git(
        root,
        ("show", object_name),
        failure_reason="PUBLIC_SOURCE_BLOB_UNAVAILABLE",
    )


def classify_path(path: str) -> Classification:
    """Classify one tracked path using the reviewed, ordered B6 policy."""

    name = PurePosixPath(path).name.casefold()
    suffix = PurePosixPath(path).suffix.casefold()
    if (
        name == ".env"
        or (name.startswith(".env.") and name != ".env.example")
        or suffix in _SECRET_SUFFIXES
    ):
        return Classification("SECRET_RISK", False, "credential-shaped path denied")
    if path == "README.md":
        return Classification(
            "GENERATED",
            False,
            "replaced at export by the reviewed public README overlay",
        )
    if path in _LEGAL_PATHS:
        return Classification(
            "LEGAL_REVIEW",
            True,
            "canonical MIT license or prior-art disclosure preserved",
        )
    if path in _PRIVATE_EXACT or path.startswith(_PRIVATE_PREFIXES) or path.startswith(
        _PRIVATE_NAME_PREFIXES
    ):
        return Classification(
            "PRIVATE_INTERNAL",
            False,
            "internal audit, historical operations, or deployment-recovery material",
        )
    if path in _REQUIRED_EXACT or path.startswith(_REQUIRED_PREFIXES):
        return Classification(
            "PUBLIC_REQUIRED",
            True,
            "required runtime, proof, license, asset, or judge documentation",
        )
    return Classification(
        "PUBLIC_ALLOWED",
        True,
        "reviewed functional source, test, infrastructure, or supporting documentation",
    )


def _write_new(path: Path, content: bytes, mode: int = 0o644) -> None:
    if path.is_symlink():
        raise PublicBundleError("PUBLIC_OUTPUT_SYMLINK_FORBIDDEN")
    try:
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.chmod(path, mode)
    except OSError as error:
        raise PublicBundleError("PUBLIC_OUTPUT_WRITE_FAILED") from error


def _b5_reference(attestation: Mapping[str, object]) -> dict[str, object]:
    required = {
        "attestation_sha256",
        "container_digest",
        "container_id",
        "limitations",
        "source_commit",
        "status",
    }
    if not required.issubset(attestation) or attestation.get("status") != "BUILD_COMPLETE":
        raise PublicBundleError("B5_BUILD_COMPLETE_REFERENCE_INVALID")
    return {
        "attestation_path": _B5_ATTESTATION,
        "attestation_sha256": attestation["attestation_sha256"],
        "aws_calls": attestation.get("aws_calls"),
        "aws_mutations": attestation.get("aws_mutations"),
        "container_digest": attestation["container_digest"],
        "container_id": attestation["container_id"],
        "document_type": "AIOA_B5_PUBLIC_BUILD_COMPLETE_REFERENCE",
        "limitations": attestation["limitations"],
        "local_image_reference": "localhost/aioa-portable:b5-c2",
        "publications": attestation.get("publications"),
        "schema_version": 1,
        "source_commit": attestation["source_commit"],
        "status": attestation["status"],
    }


def _tree_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise PublicBundleError("PUBLIC_OUTPUT_SYMLINK_FORBIDDEN")
        if path.is_file():
            files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _payload_inventory(root: Path) -> list[dict[str, object]]:
    return [
        {
            "bytes": path.stat().st_size,
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256_path(path),
        }
        for path in _tree_files(root)
    ]


def _make_archive(candidate: Path, archive: Path) -> None:
    if archive.exists() or archive.is_symlink():
        raise PublicBundleError("PUBLIC_ARCHIVE_ALREADY_EXISTS")
    try:
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as bundle:
            for path in _tree_files(candidate):
                relative = path.relative_to(candidate).as_posix()
                info = zipfile.ZipInfo(f"{BUNDLE_NAME}/{relative}", (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                executable = bool(path.stat().st_mode & stat.S_IXUSR)
                info.external_attr = (0o100755 if executable else 0o100644) << 16
                bundle.writestr(info, path.read_bytes())
    except (OSError, zipfile.BadZipFile) as error:
        raise PublicBundleError("PUBLIC_ARCHIVE_WRITE_FAILED") from error


def build_bundle(
    *,
    root: Path,
    source_ref: str,
    output_root: Path,
    certification_file: Path | None = None,
) -> dict[str, object]:
    """Create the sanitized directory, deterministic archive, and outer checksums."""

    resolved_root = root.resolve(strict=True)
    resolved_output = output_root.resolve(strict=False)
    if resolved_output == resolved_root or resolved_output.is_relative_to(resolved_root / ".git"):
        raise PublicBundleError("PUBLIC_OUTPUT_LOCATION_INVALID")
    candidate = resolved_output / BUNDLE_NAME
    archive = resolved_output / ARCHIVE_NAME
    outer_manifest = resolved_output / "PUBLICATION_MANIFEST.json"
    outer_exclusions = resolved_output / "PUBLICATION_EXCLUSIONS.md"
    outer_sums = resolved_output / "SHA256SUMS"
    if resolved_output.exists() and any(resolved_output.iterdir()):
        raise PublicBundleError("PUBLIC_OUTPUT_DIRECTORY_NOT_EMPTY")
    try:
        resolved_output.mkdir(mode=0o755, parents=True, exist_ok=True)
        candidate.mkdir(mode=0o755)
    except OSError as error:
        raise PublicBundleError("PUBLIC_OUTPUT_DIRECTORY_UNAVAILABLE") from error

    entries = source_entries(resolved_root, source_ref)
    inventory: list[dict[str, object]] = []
    source_blobs: dict[str, bytes] = {}
    source_modes: dict[str, int] = {}
    overlay_bytes: bytes | None = None
    exclusions_bytes: bytes | None = None
    for entry in entries:
        classification = classify_path(entry.path)
        if classification.name not in _CLASSIFICATIONS:
            raise PublicBundleError("PUBLIC_CLASSIFICATION_INVALID")
        blob = _read_blob(resolved_root, source_ref, entry.path)
        source_blobs[entry.path] = blob
        source_modes[entry.path] = 0o755 if entry.mode == 0o100755 else 0o644
        export_paths: list[str] = []
        if classification.included:
            _write_new(candidate / entry.path, blob, source_modes[entry.path])
            export_paths.append(entry.path)
        if entry.path == _OVERLAY_README:
            overlay_bytes = blob
        if entry.path == _EXCLUSIONS_DOC:
            exclusions_bytes = blob
        inventory.append(
            {
                "classification": classification.name,
                "export_paths": export_paths,
                "included": classification.included,
                "mode": f"{entry.mode:o}",
                "path": entry.path,
                "reason": classification.reason,
                "source_sha256": _sha256_bytes(blob),
            }
        )

    if overlay_bytes is None or exclusions_bytes is None:
        raise PublicBundleError("PUBLIC_DOCUMENT_OVERLAY_UNAVAILABLE")
    _write_new(candidate / "README.md", overlay_bytes)
    _write_new(candidate / "PUBLICATION_EXCLUSIONS.md", exclusions_bytes)

    try:
        b5_attestation = json.loads(source_blobs[_B5_ATTESTATION])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PublicBundleError("B5_BUILD_COMPLETE_REFERENCE_INVALID") from error
    if not isinstance(b5_attestation, dict):
        raise PublicBundleError("B5_BUILD_COMPLETE_REFERENCE_INVALID")
    _write_new(
        candidate / "B5_BUILD_COMPLETE_REFERENCE.json",
        _canonical_bytes(_b5_reference(b5_attestation), pretty=True),
    )

    certification_sha256: str | None = None
    if certification_file is not None:
        try:
            certification = certification_file.resolve(strict=True).read_bytes()
            parsed_certification = json.loads(certification)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise PublicBundleError("B6_CERTIFICATION_REPORT_INVALID") from error
        if not isinstance(parsed_certification, dict) or parsed_certification.get("status") != "PASS":
            raise PublicBundleError("B6_CERTIFICATION_REPORT_INVALID")
        certification_sha256 = _sha256_bytes(certification)
        _write_new(candidate / "B6_REPRODUCIBILITY_REPORT.json", certification)

    for item in inventory:
        if item["path"] == _OVERLAY_README:
            item["export_paths"] = [item["path"], "README.md"]
        elif item["path"] == _EXCLUSIONS_DOC:
            item["export_paths"] = [item["path"], "PUBLICATION_EXCLUSIONS.md"]

    payload = _payload_inventory(candidate)
    payload_tree_sha256 = _sha256_bytes(_canonical_bytes(payload))
    counts = Counter(str(item["classification"]) for item in inventory)
    manifest_material: dict[str, object] = {
        "archive_uploaded": False,
        "aws_calls": 0,
        "aws_mutations": 0,
        "b5_build_complete_reference": "B5_BUILD_COMPLETE_REFERENCE.json",
        "b6_certification_included": certification_file is not None,
        "b6_certification_sha256": certification_sha256,
        "classifications": dict(sorted(counts.items())),
        "document_type": "AIOA_B6_PUBLICATION_MANIFEST",
        "external_deployments": 0,
        "inventory": inventory,
        "inventory_count": len(inventory),
        "payload": payload,
        "payload_count_before_manifest_and_sums": len(payload),
        "payload_tree_sha256": payload_tree_sha256,
        "publication_actions": 0,
        "remote_pushes": 0,
        "root_readme_source": _OVERLAY_README,
        "schema_version": 1,
        "source_ref": source_ref if source_ref != "INDEX" else "STAGED_INDEX",
        "status": "SANITIZED_PUBLIC_CANDIDATE",
    }
    manifest_material["manifest_sha256"] = _sha256_bytes(_canonical_bytes(manifest_material))
    manifest_bytes = _canonical_bytes(manifest_material, pretty=True)
    _write_new(candidate / "PUBLICATION_MANIFEST.json", manifest_bytes)

    sums_entries = [
        f"{_sha256_path(path)}  {path.relative_to(candidate).as_posix()}"
        for path in _tree_files(candidate)
    ]
    _write_new(candidate / "SHA256SUMS", ("\n".join(sums_entries) + "\n").encode("ascii"))

    _write_new(outer_manifest, manifest_bytes)
    _write_new(outer_exclusions, exclusions_bytes)
    _make_archive(candidate, archive)
    outer_entries = (
        (ARCHIVE_NAME, _sha256_path(archive)),
        ("PUBLICATION_EXCLUSIONS.md", _sha256_path(outer_exclusions)),
        ("PUBLICATION_MANIFEST.json", _sha256_path(outer_manifest)),
    )
    _write_new(
        outer_sums,
        ("".join(f"{digest}  {path}\n" for path, digest in outer_entries)).encode("ascii"),
    )
    summary_material: dict[str, object] = {
        "archive": ARCHIVE_NAME,
        "archive_sha256": _sha256_path(archive),
        "aws_mutations": 0,
        "candidate_directory": BUNDLE_NAME,
        "external_deployments": 0,
        "inventory_count": len(inventory),
        "manifest_sha256": _sha256_path(outer_manifest),
        "payload_tree_sha256": payload_tree_sha256,
        "publication_actions": 0,
        "remote_pushes": 0,
        "source_ref": source_ref if source_ref != "INDEX" else "STAGED_INDEX",
        "status": "PASS",
    }
    return {
        **summary_material,
        "receipt_sha256": _sha256_bytes(_canonical_bytes(summary_material)),
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--certification-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        receipt = build_bundle(
            root=args.source_root,
            source_ref=args.source_ref,
            output_root=args.output_root,
            certification_file=args.certification_file,
        )
        code = 0
    except (OSError, PublicBundleError) as error:
        reason = error.reason if isinstance(error, PublicBundleError) else "PUBLIC_BUNDLE_IO_FAILED"
        receipt = {
            "aws_mutations": 0,
            "external_deployments": 0,
            "publication_actions": 0,
            "reason": reason,
            "remote_pushes": 0,
            "status": "FAIL",
        }
        code = 1
    print(json.dumps(receipt, allow_nan=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
