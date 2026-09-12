#!/usr/bin/env python3
"""Build and inspect the deterministic Day 15 Lambda ZIP without contacting AWS."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Final

import yaml

ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_LOCK: Final = ROOT / "requirements" / "lambda-runtime.txt"
DEFAULT_LOCK_INPUT: Final = ROOT / "requirements" / "lambda-runtime.in"
DEFAULT_SOURCE: Final = ROOT / "src"
DEFAULT_TEMPLATE: Final = ROOT / "infra" / "sam" / "template.yaml"
DEFAULT_ARTIFACT: Final = ROOT / "dist" / "day15" / "aioa-lambda.zip"
DEFAULT_MANIFEST: Final = ROOT / "dist" / "day15" / "aioa-lambda.manifest.json"
DEFAULT_SCAN_REPORT: Final = ROOT / "dist" / "day15" / "pip-audit.json"
TOOLCHAIN_PATH: Final = ROOT / "requirements" / "day15-toolchain.json"
BUILDER_PATH: Final = Path(__file__).absolute()
EXPECTED_TOOLCHAIN: Final = {
    "artifact_builder": {
        "architecture": "x86_64",
        "pip_version": "26.2.1",
        "platform": "manylinux2014_x86_64",
        "python_version": "3.12.3",
        "runtime": "python3.12",
        "zip_compression": "stored",
    },
    "aws_cli": {"status": "PASS", "version": "2.36.11"},
    "cfn_lint": {"name": "cfn-lint", "status": "PASS", "version": "1.52.1"},
    "dependency_scanner": {
        "name": "pip-audit",
        "status": "PASS",
        "version": "2.10.1",
    },
    "lambda_compatible_container": {
        "engine": "podman",
        "engine_version": "4.9.3",
        "image": "public.ecr.aws/lambda/python@sha256:"
        "3b486b954ce91baf361174c15e3801ceeef6892d0b3301f71c0bfc94db9c6142",
        "status": "PASS",
    },
    "lock_generator": {
        "name": "pip-tools",
        "pip_version": "26.1.2",
        "python_version": "3.12.3",
        "version": "7.5.3",
    },
    "sam_cli": {"status": "PASS", "version": "1.165.0"},
    "sam_translator": {
        "name": "aws-sam-translator",
        "status": "PASS",
        "version": "1.111.0",
    },
    "schema_version": 1,
}

REQUIRED_DIRECT_DISTRIBUTIONS: Final = frozenset(
    {"boto3", "botocore", "pydantic", "strands-agents", "uuid6"}
)
TEXT_SOURCE_SUFFIXES: Final = frozenset(
    {".css", ".html", ".js", ".json", ".md", ".py", ".svg", ".txt"}
)
FIXED_ZIP_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)
SHA256_PATTERN: Final = re.compile(r"--hash=sha256:([0-9a-f]{64})(?:\s|$)")
REQUIREMENT_PATTERN: Final = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^\]]+\])?=="
    r"(?P<version>[^\s;]+)(?:\s*;[^\s].*?)?(?:\s+--hash=|$)"
)
AWS_ACCESS_KEY_PATTERN: Final = re.compile(rb"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")
PRIVATE_KEY_PEM_MARKER: Final = b"-----BEGIN " + b"PRIVATE " + b"KEY-----"
FORBIDDEN_ARCHIVE_SUFFIXES: Final = frozenset({".egg-link", ".pem", ".pfx", ".p12", ".pyc"})
FORBIDDEN_ARCHIVE_NAMES: Final = frozenset({"direct_url.json"})
RUNTIME_CA_BUNDLE_PATHS: Final = frozenset(
    {
        PurePosixPath("botocore/cacert.pem"),
        PurePosixPath("certifi/cacert.pem"),
    }
)
NONRUNTIME_DEPENDENCY_EXAMPLE_PATHS: Final = (
    PurePosixPath("boto3/examples/cloudfront.rst"),
    PurePosixPath("botocore/data/iam/2010-05-08/examples-1.json"),
    PurePosixPath("botocore/data/sts/2011-06-15/examples-1.json"),
)


class ArtifactFailure(RuntimeError):
    """A fixed-code failure that is safe to print without paths or subprocess output."""

    def __init__(self, reason: str, *, status: str = "FAIL") -> None:
        self.reason = reason
        self.status = status
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class LockEntry:
    name: str
    version: str
    hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BuildPaths:
    lock: Path
    source: Path
    template: Path
    artifact: Path
    manifest: Path
    scan_report: Path
    wheelhouse: Path | None = None


@dataclass(frozen=True, slots=True)
class RuntimeStage:
    """Content-derived facts for one clean dependency install and source copy."""

    copied_source: tuple[str, ...]
    files: tuple[str, ...]
    inventory: tuple[tuple[str, str], ...]
    root: Path
    source_sha256: str


@dataclass(frozen=True, slots=True)
class IndependentRuntimeBuild:
    """Primary artifact plus proof from a separate clean install and rebuild."""

    artifact: Path
    artifact_sha256: str
    primary: RuntimeStage
    rebuild_sha256: str


def canonical_json(value: object) -> str:
    """Return the repository's stable JSON representation."""

    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )


def _git_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


def _git(*arguments: str) -> str:
    try:
        result = subprocess.run(
            ("git", "-c", "core.quotepath=false", *arguments),
            cwd=ROOT,
            env=_git_environment(),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ArtifactFailure("GIT_PROVENANCE_UNAVAILABLE", status="BLOCKED") from error
    if result.returncode != 0:
        raise ArtifactFailure("GIT_PROVENANCE_UNAVAILABLE", status="BLOCKED")
    return result.stdout


def _repo_relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError as error:
        raise ArtifactFailure("BUILD_INPUT_OUTSIDE_REPOSITORY") from error


def _require_nonsymlink_chain(path: Path) -> None:
    current = path
    while current != ROOT:
        if current.is_symlink():
            raise ArtifactFailure("BUILD_INPUT_SYMLINK_FORBIDDEN")
        if ROOT not in current.parents:
            raise ArtifactFailure("BUILD_INPUT_OUTSIDE_REPOSITORY")
        current = current.parent


def validate_repository_inputs(paths: BuildPaths) -> dict[str, object]:
    """Bind canonical tracked inputs to one completely clean Git commit."""

    expected = {
        "lock": DEFAULT_LOCK,
        "source": DEFAULT_SOURCE,
        "template": DEFAULT_TEMPLATE,
    }
    actual = {"lock": paths.lock, "source": paths.source, "template": paths.template}
    for name, expected_path in expected.items():
        candidate = actual[name]
        if (
            candidate.absolute() != expected_path.absolute()
            or candidate.resolve() != expected_path.resolve()
        ):
            raise ArtifactFailure("NONCANONICAL_BUILD_INPUT_FORBIDDEN")
        _require_nonsymlink_chain(candidate)

    repository_root = Path(_git("rev-parse", "--show-toplevel").strip()).resolve()
    if repository_root != ROOT.resolve():
        raise ArtifactFailure("GIT_REPOSITORY_ROOT_MISMATCH")
    head = _git("rev-parse", "--verify", "HEAD").strip()
    if re.fullmatch(r"[0-9a-f]{40,64}", head) is None:
        raise ArtifactFailure("GIT_HEAD_INVALID")
    if _git("status", "--porcelain=v1", "--untracked-files=all").strip():
        raise ArtifactFailure("REPOSITORY_NOT_CLEAN", status="BLOCKED")

    fixed_inputs = (
        DEFAULT_LOCK,
        DEFAULT_LOCK_INPUT,
        DEFAULT_TEMPLATE,
        TOOLCHAIN_PATH,
        BUILDER_PATH,
    )
    for fixed in fixed_inputs:
        if not fixed.is_file():
            raise ArtifactFailure("TRACKED_BUILD_INPUT_MISSING")
        _require_nonsymlink_chain(fixed)
    source_paths = tuple(
        candidate
        for candidate in sorted(DEFAULT_SOURCE.joinpath("aioa_cloudops_agent").rglob("*"))
        if candidate.is_file()
        and "__pycache__" not in candidate.parts
        and candidate.suffix != ".pyc"
    )
    if not source_paths:
        raise ArtifactFailure("SOURCE_PACKAGE_EMPTY")
    tracked_paths = tuple(_repo_relative(item) for item in (*fixed_inputs, *source_paths))
    stage_lines = _git("ls-files", "--stage", "--", *tracked_paths).splitlines()
    index: dict[str, tuple[str, str]] = {}
    for line in stage_lines:
        try:
            metadata, relative = line.split("\t", 1)
            mode, oid, stage = metadata.split()
        except ValueError as error:
            raise ArtifactFailure("GIT_INDEX_RECORD_INVALID") from error
        if stage != "0" or mode not in {"100644", "100755"}:
            raise ArtifactFailure("BUILD_INPUT_NOT_TRACKED_REGULAR_FILE")
        index[relative] = (mode, oid)
    if set(index) != set(tracked_paths):
        raise ArtifactFailure("BUILD_INPUT_NOT_TRACKED_REGULAR_FILE")

    tree_lines = _git("ls-tree", "-r", "HEAD", "--", *tracked_paths).splitlines()
    head_objects: dict[str, str] = {}
    for line in tree_lines:
        try:
            metadata, relative = line.split("\t", 1)
            mode, object_type, oid = metadata.split()
        except ValueError as error:
            raise ArtifactFailure("GIT_HEAD_RECORD_INVALID") from error
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise ArtifactFailure("BUILD_INPUT_NOT_HEAD_REGULAR_FILE")
        head_objects[relative] = oid
    if set(head_objects) != set(tracked_paths):
        raise ArtifactFailure("BUILD_INPUT_NOT_IN_HEAD")
    for relative in tracked_paths:
        if index[relative][1] != head_objects[relative]:
            raise ArtifactFailure("BUILD_INPUT_INDEX_HEAD_MISMATCH")
    worktree_objects = _git("hash-object", "--", *tracked_paths).splitlines()
    if len(worktree_objects) != len(tracked_paths):
        raise ArtifactFailure("BUILD_INPUT_HASH_UNAVAILABLE")
    if any(
        oid != index[relative][1]
        for relative, oid in zip(tracked_paths, worktree_objects, strict=True)
    ):
        raise ArtifactFailure("BUILD_INPUT_WORKTREE_HEAD_MISMATCH")

    source_tree = _git("rev-parse", "HEAD:src/aioa_cloudops_agent").strip()
    return {
        "commit_oid": head,
        "input_objects": [
            {"git_oid": index[_repo_relative(item)][1], "path": _repo_relative(item)}
            for item in fixed_inputs
        ],
        "source_tree_oid": source_tree,
        "status": "CLEAN",
    }


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob_oid(data: bytes, *, oid_length: int) -> str:
    algorithm = "sha1" if oid_length == 40 else "sha256" if oid_length == 64 else None
    if algorithm is None:
        raise ArtifactFailure("GIT_OBJECT_FORMAT_INVALID")
    framed = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    return hashlib.new(algorithm, framed).hexdigest()


def _atomic_canonical_json(path: Path, value: object) -> None:
    if path.is_symlink():
        raise ArtifactFailure("BUILD_OUTPUT_SYMLINK_FORBIDDEN")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="day15-json-",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write((canonical_json(value) + "\n").encode())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_publish_artifact(source: Path, destination: Path) -> None:
    """Copy into the destination filesystem before atomically replacing the artifact."""

    if destination.is_symlink():
        raise ArtifactFailure("BUILD_OUTPUT_SYMLINK_FORBIDDEN")
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (
            source.open("rb") as source_handle,
            tempfile.NamedTemporaryFile(
                prefix="day15-artifact-",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as destination_handle,
        ):
            temporary = Path(destination_handle.name)
            shutil.copyfileobj(source_handle, destination_handle)
            destination_handle.flush()
            os.fchmod(destination_handle.fileno(), 0o644)
            os.fsync(destination_handle.fileno())
        os.replace(temporary, destination)
        temporary = None
    except OSError as error:
        raise ArtifactFailure("ARTIFACT_PUBLISH_FAILED") from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _logical_requirement_lines(text: str) -> tuple[str, ...]:
    result: list[str] = []
    pending = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        continued = stripped.endswith("\\")
        part = stripped[:-1].strip() if continued else stripped
        pending = f"{pending} {part}".strip()
        if not continued:
            result.append(pending)
            pending = ""
    if pending:
        raise ArtifactFailure("LOCK_CONTINUATION_UNTERMINATED")
    return tuple(result)


def validate_runtime_lock(path: Path = DEFAULT_LOCK) -> tuple[LockEntry, ...]:
    """Require an exact, hash-locked, index-neutral runtime dependency closure."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ArtifactFailure("RUNTIME_LOCK_UNAVAILABLE") from error
    lowered = text.casefold()
    forbidden_fragments = (
        "--editable",
        "--extra-index-url",
        "--index-url",
        "--trusted-host",
        "-e ",
        " @ ",
        "file:",
        "git+",
        "hg+",
        "svn+",
    )
    if any(fragment in lowered for fragment in forbidden_fragments):
        raise ArtifactFailure("RUNTIME_LOCK_HAS_EXTERNAL_OR_LOCAL_REFERENCE")

    entries: dict[str, LockEntry] = {}
    for logical_line in _logical_requirement_lines(text):
        match = REQUIREMENT_PATTERN.match(logical_line)
        if match is None:
            raise ArtifactFailure("RUNTIME_LOCK_HAS_UNPINNED_ENTRY")
        name = _normalized_name(match.group("name"))
        hashes = tuple(sorted(set(SHA256_PATTERN.findall(logical_line))))
        if not hashes:
            raise ArtifactFailure("RUNTIME_LOCK_ENTRY_MISSING_HASH")
        if name in entries:
            raise ArtifactFailure("RUNTIME_LOCK_DUPLICATE_DISTRIBUTION")
        entries[name] = LockEntry(name, match.group("version"), hashes)

    if not entries:
        raise ArtifactFailure("RUNTIME_LOCK_EMPTY")
    if not REQUIRED_DIRECT_DISTRIBUTIONS.issubset(entries):
        raise ArtifactFailure("RUNTIME_LOCK_DIRECT_PIN_MISSING")
    return tuple(entries[name] for name in sorted(entries))


def _safe_relative_path(path: str) -> PurePosixPath:
    try:
        path.encode("ascii")
    except UnicodeEncodeError as error:
        raise ArtifactFailure("ARTIFACT_PATH_UNSAFE") from error
    if "\\" in path or any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise ArtifactFailure("ARTIFACT_PATH_UNSAFE")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ArtifactFailure("ARTIFACT_PATH_UNSAFE")
    if any(part in {"", "."} for part in candidate.parts):
        raise ArtifactFailure("ARTIFACT_PATH_UNSAFE")
    return candidate


def _forbidden_runtime_path(path: PurePosixPath) -> bool:
    lowered_parts = tuple(part.casefold() for part in path.parts)
    forbidden_suffix = path.suffix.casefold() in FORBIDDEN_ARCHIVE_SUFFIXES
    if path in RUNTIME_CA_BUNDLE_PATHS:
        forbidden_suffix = False
    return (
        lowered_parts[0] == "bin"
        or "__pycache__" in lowered_parts
        or path.name.casefold() in FORBIDDEN_ARCHIVE_NAMES
        or forbidden_suffix
        or path.suffix.casefold() == ".pth"
    )


def inspect_staging_tree(stage: Path) -> tuple[str, ...]:
    """Reject path injection, executable entry points and host-local install metadata."""

    files: list[str] = []
    for candidate in sorted(stage.rglob("*"), key=lambda item: item.as_posix()):
        if candidate.is_symlink():
            raise ArtifactFailure("ARTIFACT_SYMLINK_FORBIDDEN")
        if not candidate.is_file():
            continue
        relative = _safe_relative_path(candidate.relative_to(stage).as_posix())
        if _forbidden_runtime_path(relative):
            raise ArtifactFailure("ARTIFACT_FORBIDDEN_RUNTIME_PATH")
        try:
            data = candidate.read_bytes()
        except OSError as error:
            raise ArtifactFailure("ARTIFACT_FILE_UNREADABLE") from error
        if PRIVATE_KEY_PEM_MARKER in data or AWS_ACCESS_KEY_PATTERN.search(data):
            raise ArtifactFailure("ARTIFACT_CREDENTIAL_PATTERN")
        files.append(relative.as_posix())
    if not files:
        raise ArtifactFailure("ARTIFACT_EMPTY")
    return tuple(files)


def _normalized_source_bytes(path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ArtifactFailure("SOURCE_FILE_UNREADABLE") from error
    if path.suffix.casefold() not in TEXT_SOURCE_SUFFIXES:
        raise ArtifactFailure("SOURCE_FILE_TYPE_NOT_ALLOWLISTED")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ArtifactFailure("SOURCE_TEXT_NOT_UTF8") from error
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def copy_runtime_source(source_root: Path, stage: Path) -> tuple[str, ...]:
    """Copy only the application package, normalizing text line endings."""

    package_root = source_root / "aioa_cloudops_agent"
    if not package_root.is_dir():
        raise ArtifactFailure("SOURCE_PACKAGE_UNAVAILABLE")
    copied: list[str] = []
    for source in sorted(package_root.rglob("*"), key=lambda item: item.as_posix()):
        if source.is_symlink():
            raise ArtifactFailure("SOURCE_SYMLINK_FORBIDDEN")
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        if "__pycache__" in relative.parts or source.suffix.casefold() == ".pyc":
            continue
        data = _normalized_source_bytes(source)
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        copied.append(relative.as_posix())
    if not copied:
        raise ArtifactFailure("SOURCE_PACKAGE_EMPTY")
    return tuple(copied)


def hash_tree(root: Path, paths: tuple[str, ...] | None = None) -> str:
    """Hash relative names and bytes without including the root path or metadata."""

    names = paths or tuple(
        candidate.relative_to(root).as_posix()
        for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if candidate.is_file() and not candidate.is_symlink()
    )
    digest = hashlib.sha256()
    for name in sorted(names):
        relative = _safe_relative_path(name)
        data = (root / relative).read_bytes()
        encoded = relative.as_posix().encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def write_deterministic_zip(stage: Path, output: Path) -> str:
    """Write byte-stable ZIP_STORED output with fixed timestamps and permissions."""

    files = inspect_staging_tree(stage)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="day15-zip-", suffix=".tmp", dir=output.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True
        ) as archive:
            for name in files:
                info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = (0o100644 & 0xFFFF) << 16
                archive.writestr(info, (stage / PurePosixPath(name)).read_bytes())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return _sha256_bytes(output.read_bytes())


def inspect_archive(path: Path) -> dict[str, object]:
    """Re-open and prove the deterministic archive safety contract."""

    try:
        raw = path.read_bytes()
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if names != sorted(names) or len(names) != len(set(names)):
                raise ArtifactFailure("ARTIFACT_ARCHIVE_ORDER_OR_DUPLICATE_INVALID")
            for entry in entries:
                relative = _safe_relative_path(entry.filename)
                if entry.is_dir() or _forbidden_runtime_path(relative):
                    raise ArtifactFailure("ARTIFACT_ARCHIVE_ENTRY_FORBIDDEN")
                if entry.date_time != FIXED_ZIP_TIMESTAMP:
                    raise ArtifactFailure("ARTIFACT_ARCHIVE_TIMESTAMP_DRIFT")
                if entry.compress_type != zipfile.ZIP_STORED:
                    raise ArtifactFailure("ARTIFACT_ARCHIVE_COMPRESSION_DRIFT")
                mode = entry.external_attr >> 16
                if entry.create_system != 3 or mode != 0o100644:
                    raise ArtifactFailure("ARTIFACT_ARCHIVE_MODE_DRIFT")
                data = archive.read(entry)
                if PRIVATE_KEY_PEM_MARKER in data or AWS_ACCESS_KEY_PATTERN.search(data):
                    raise ArtifactFailure("ARTIFACT_CREDENTIAL_PATTERN")
    except (OSError, zipfile.BadZipFile) as error:
        raise ArtifactFailure("ARTIFACT_ARCHIVE_UNREADABLE") from error
    return {
        "entry_count": len(names),
        "sha256": _sha256_bytes(raw),
        "status": "PASS",
        "zip_compression": "stored",
    }


def _read_distribution_inventory(stage: Path) -> tuple[tuple[str, str], ...]:
    inventory: dict[str, str] = {}
    for metadata_path in sorted(stage.glob("*.dist-info/METADATA")):
        try:
            metadata = Parser().parsestr(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as error:
            raise ArtifactFailure("DISTRIBUTION_METADATA_UNREADABLE") from error
        raw_name = metadata.get("Name")
        version = metadata.get("Version")
        if not raw_name or not version:
            raise ArtifactFailure("DISTRIBUTION_METADATA_INCOMPLETE")
        name = _normalized_name(raw_name)
        if name in inventory:
            raise ArtifactFailure("DISTRIBUTION_METADATA_DUPLICATE")
        inventory[name] = version
    if not inventory:
        raise ArtifactFailure("DISTRIBUTION_INVENTORY_EMPTY")
    return tuple(sorted(inventory.items()))


def validate_distribution_inventory(
    stage: Path,
    lock_entries: tuple[LockEntry, ...],
) -> tuple[tuple[str, str], ...]:
    """Require the installed distributions to equal the fully resolved lock."""

    inventory = _read_distribution_inventory(stage)
    expected = {(entry.name, entry.version) for entry in lock_entries}
    if set(inventory) != expected:
        raise ArtifactFailure("DISTRIBUTION_INVENTORY_LOCK_MISMATCH")
    return inventory


def discover_lambda_handlers(template_path: Path = DEFAULT_TEMPLATE) -> tuple[str, ...]:
    """Discover every declared Python Lambda handler instead of keeping a second list."""

    try:
        template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise ArtifactFailure("SAM_TEMPLATE_UNREADABLE") from error
    if not isinstance(template, dict) or not isinstance(template.get("Resources"), dict):
        raise ArtifactFailure("SAM_TEMPLATE_RESOURCES_INVALID")
    handlers: list[str] = []
    for resource in template["Resources"].values():
        if not isinstance(resource, dict) or resource.get("Type") not in {
            "AWS::Lambda::Function",
            "AWS::Serverless::Function",
        }:
            continue
        properties = resource.get("Properties")
        handler = properties.get("Handler") if isinstance(properties, dict) else None
        if isinstance(handler, str):
            if handler.count(".") < 1 or any(character.isspace() for character in handler):
                raise ArtifactFailure("LAMBDA_HANDLER_INVALID")
            handlers.append(handler)
    if not handlers:
        raise ArtifactFailure("LAMBDA_HANDLER_MISSING")
    return tuple(sorted(set(handlers)))


def _handler_environment() -> dict[str, str]:
    placeholder_account = "0" * 12
    placeholder_instance = "i-" + "0" * 17
    token_not_after = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    return {
        "AIOA_ALLOW_LIVE_SANDBOX_STOP": "false",
        "AIOA_EMERGENCY_EXECUTION_DISABLED": "true",
        "APP_STAGE": "hackathon",
        "AWS_CONFIG_FILE": os.devnull,
        "AWS_DEFAULT_REGION": "eu-central-1",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_MUTATIONS_ENABLED": "false",
        "AWS_REGION": "eu-central-1",
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "BEDROCK_MODEL_ID": "eu.amazon.nova-2-lite-v1:0",
        "BEDROCK_REGION": "eu-central-1",
        "JUDGE_TOKEN_SECRET_ARN": (
            f"arn:aws:secretsmanager:eu-central-1:{placeholder_account}:secret:day15-placeholder"
        ),
        "JUDGE_TOKEN_NOT_AFTER": token_not_after,
        "MODEL_MAX_OUTPUT_TOKENS": "1024",
        "PRIVATE_REMEDIATION_FUNCTION_NAME": "day15-remediation:live",
        "PYTHONNOUSERSITE": "1",
        "SANDBOX_INSTANCE_ID": placeholder_instance,
        "SANDBOX_REGION": "eu-central-1",
        "SANDBOX_TAG_KEY": "AIOACloudOpsSandbox",
        "SANDBOX_TAG_VALUE": "true",
        "STATE_TABLE_NAME": "day15-placeholder",
    }


def _handler_import_script(root: str, handlers: tuple[str, ...]) -> str:
    return (
        "import importlib,json,sys;"
        f"sys.path.insert(0,{json.dumps(root)});"
        f"handlers=json.loads({json.dumps(json.dumps(handlers))});"
        "[(lambda module,name: callable(getattr(module,name)) or "
        "(_ for _ in ()).throw(TypeError('not callable')))("
        "importlib.import_module(item.rsplit('.',1)[0]),item.rsplit('.',1)[1]) "
        "for item in handlers]"
    )


def clean_import_handlers(artifact: Path, handlers: tuple[str, ...]) -> str:
    """Import handler symbols with only stdlib and the extracted artifact on sys.path."""

    inspect_archive(artifact)
    with tempfile.TemporaryDirectory(prefix="aioa-day15-import-") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(artifact) as archive:
            archive.extractall(root)
        script = _handler_import_script(str(root), handlers)
        environment = _handler_environment()
        try:
            result = subprocess.run(
                (sys.executable, "-I", "-S", "-c", script),
                cwd=root,
                env=environment,
                check=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ArtifactFailure("LAMBDA_HANDLER_IMPORT_UNAVAILABLE") from error
    if result.returncode != 0:
        raise ArtifactFailure("LAMBDA_HANDLER_IMPORT_FAILED")
    return "PASS"


def lambda_container_validation(
    stage: Path,
    handlers: tuple[str, ...],
    *,
    toolchain: dict[str, object],
) -> dict[str, object]:
    """Import handlers in one locally present, digest-pinned Lambda base image."""

    contract = toolchain.get("lambda_compatible_container")
    if not isinstance(contract, dict) or contract.get("status") != "PASS":
        reason = contract.get("reason") if isinstance(contract, dict) else None
        return {
            "reason": reason if isinstance(reason, str) else "LAMBDA_CONTAINER_TOOLCHAIN_BLOCKED",
            "status": "BLOCKED",
        }
    engine = contract.get("engine")
    engine_version = contract.get("engine_version")
    image = contract.get("image")
    if (
        engine not in {"docker", "podman"}
        or not isinstance(engine_version, str)
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", engine_version) is None
        or not isinstance(image, str)
        or re.fullmatch(r"public\.ecr\.aws/lambda/python@sha256:[0-9a-f]{64}", image) is None
    ):
        return {"reason": "LAMBDA_CONTAINER_TOOLCHAIN_NOT_PINNED", "status": "BLOCKED"}
    executable = shutil.which(engine)
    if executable is None:
        return {"reason": "CONTAINER_ENGINE_UNAVAILABLE", "status": "BLOCKED"}
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    # Rootless engines require the caller's existing home for their local storage
    # metadata. Preserve it unchanged; it is never mounted or exported to Lambda.
    if (caller_home := os.environ.get("HOME")) is not None:
        environment["HOME"] = caller_home
    try:
        version_result = subprocess.run(
            (executable, "--version"),
            cwd=ROOT,
            env=environment,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
        inspect_result = subprocess.run(
            (executable, "image", "inspect", image),
            cwd=ROOT,
            env=environment,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"reason": "LAMBDA_CONTAINER_UNAVAILABLE", "status": "BLOCKED"}
    version_match = re.search(r"(?<![0-9])[0-9]+\.[0-9]+\.[0-9]+(?![0-9])", version_result.stdout)
    if (
        version_result.returncode != 0
        or version_match is None
        or version_match.group(0) != engine_version
    ):
        return {"reason": "CONTAINER_ENGINE_VERSION_MISMATCH", "status": "FAIL"}
    if inspect_result.returncode != 0:
        return {"reason": "LAMBDA_CONTAINER_IMAGE_UNAVAILABLE", "status": "BLOCKED"}
    try:
        inspect_payload = json.loads(inspect_result.stdout)
    except json.JSONDecodeError:
        return {"reason": "LAMBDA_CONTAINER_INSPECT_INVALID", "status": "FAIL"}
    inspected = (
        inspect_payload[0] if isinstance(inspect_payload, list) and inspect_payload else None
    )
    expected_digest = image.rsplit("@", 1)[1]
    if (
        not isinstance(inspected, dict)
        or inspected.get("Architecture") != "amd64"
        or inspected.get("Digest") != expected_digest
    ):
        return {"reason": "LAMBDA_CONTAINER_IDENTITY_MISMATCH", "status": "FAIL"}
    command = [
        executable,
        "run",
        "--rm",
        "--pull=never",
        "--platform=linux/amd64",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--cgroups=disabled",
        "--ipc=none",
        "--mount=type=bind,src=/dev/pts,dst=/dev/pts,ro=true",
        "--security-opt=no-new-privileges",
        "--entrypoint=/var/lang/bin/python3.12",
        f"--volume={stage}:/var/task:ro",
    ]
    for name, value in sorted(_handler_environment().items()):
        command.extend(("--env", f"{name}={value}"))
    command.extend((image, "-I", "-S", "-c", _handler_import_script("/var/task", handlers)))
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"reason": "LAMBDA_CONTAINER_VALIDATION_UNAVAILABLE", "status": "BLOCKED"}
    if result.returncode != 0:
        return {"reason": "LAMBDA_CONTAINER_IMPORT_FAILED", "status": "FAIL"}
    return {
        "architecture": "amd64",
        "engine": engine,
        "engine_version": engine_version,
        "image_digest": expected_digest,
        "status": "PASS",
        "validator": "lambda-python3.12-x86_64-container",
    }


def _pip_environment() -> dict[str, str]:
    environment = {
        "AWS_CONFIG_FILE": os.devnull,
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_CACHE_DIR": "1",
        "PYTHONNOUSERSITE": "1",
    }
    return environment


def install_locked_dependencies(
    lock: Path,
    stage: Path,
    *,
    wheelhouse: Path | None,
) -> None:
    """Install the lock for Lambda's Python 3.12/x86_64 wheel platform."""

    command = [
        sys.executable,
        "-m",
        "pip",
        "--isolated",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--require-hashes",
        "--no-deps",
        "--only-binary=:all:",
        "--platform=manylinux2014_x86_64",
        "--implementation=cp",
        "--python-version=3.12",
        "--abi=cp312",
        "--no-compile",
        f"--target={stage}",
    ]
    if wheelhouse is None:
        command.append("--index-url=https://pypi.org/simple")
    else:
        command.extend(("--no-index", f"--find-links={wheelhouse}"))
    command.extend(("--requirement", str(lock)))
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=_pip_environment(),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ArtifactFailure("DEPENDENCY_INSTALL_UNAVAILABLE", status="BLOCKED") from error
    if result.returncode != 0:
        raise ArtifactFailure("DEPENDENCY_INSTALL_FAILED", status="BLOCKED")
    bin_directory = stage / "bin"
    if bin_directory.exists():
        shutil.rmtree(bin_directory)


def prune_nonruntime_dependency_examples(stage: Path) -> tuple[str, ...]:
    """Remove only reviewed SDK documentation/example files not used at runtime."""

    removed: list[str] = []
    for relative in NONRUNTIME_DEPENDENCY_EXAMPLE_PATHS:
        candidate = stage / relative
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            candidate.unlink()
        except OSError as error:
            raise ArtifactFailure("DEPENDENCY_EXAMPLE_PRUNE_FAILED") from error
        removed.append(relative.as_posix())
    return tuple(removed)


def _assemble_clean_runtime_stage(
    lock: Path,
    source: Path,
    stage: Path,
    lock_entries: tuple[LockEntry, ...],
    *,
    wheelhouse: Path | None,
) -> RuntimeStage:
    """Install and assemble one runtime in a new, previously absent directory."""

    if stage.exists():
        raise ArtifactFailure("REBUILD_STAGE_NOT_CLEAN")
    stage.mkdir()
    install_locked_dependencies(lock, stage, wheelhouse=wheelhouse)
    prune_nonruntime_dependency_examples(stage)
    copied_source = copy_runtime_source(source, stage)
    if any(
        (stage / relative).read_bytes()
        != _git("show", f"HEAD:{_repo_relative(source / relative)}")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .encode("utf-8")
        for relative in copied_source
    ):
        raise ArtifactFailure("SOURCE_STAGE_HEAD_MISMATCH")
    files = inspect_staging_tree(stage)
    inventory = validate_distribution_inventory(stage, lock_entries)
    return RuntimeStage(
        copied_source=copied_source,
        files=files,
        inventory=inventory,
        root=stage,
        source_sha256=hash_tree(stage, copied_source),
    )


def _build_independent_runtime(
    temporary_root: Path,
    lock: Path,
    source: Path,
    lock_entries: tuple[LockEntry, ...],
    *,
    wheelhouse: Path | None,
) -> IndependentRuntimeBuild:
    """Build twice from two clean installs and require byte-identical archives."""

    primary = _assemble_clean_runtime_stage(
        lock,
        source,
        temporary_root / "stage",
        lock_entries,
        wheelhouse=wheelhouse,
    )
    candidate_artifact = temporary_root / "candidate.zip"
    artifact_sha256 = write_deterministic_zip(primary.root, candidate_artifact)

    rebuild = _assemble_clean_runtime_stage(
        lock,
        source,
        temporary_root / "rebuild-stage",
        lock_entries,
        wheelhouse=wheelhouse,
    )
    rebuild_artifact = temporary_root / "rebuild.zip"
    rebuild_sha256 = write_deterministic_zip(rebuild.root, rebuild_artifact)
    primary_facts = (
        primary.copied_source,
        primary.files,
        primary.inventory,
        primary.source_sha256,
    )
    rebuild_facts = (
        rebuild.copied_source,
        rebuild.files,
        rebuild.inventory,
        rebuild.source_sha256,
    )
    if (
        rebuild_facts != primary_facts
        or rebuild_sha256 != artifact_sha256
        or rebuild_artifact.read_bytes() != candidate_artifact.read_bytes()
    ):
        raise ArtifactFailure("DETERMINISTIC_REBUILD_MISMATCH")
    return IndependentRuntimeBuild(
        artifact=candidate_artifact,
        artifact_sha256=artifact_sha256,
        primary=primary,
        rebuild_sha256=rebuild_sha256,
    )


def dependency_security_scan(
    stage: Path,
    *,
    artifact_sha256: str,
    expected_inventory: tuple[tuple[str, str], ...],
    lock_sha256: str,
    enabled: bool,
    toolchain: dict[str, object] | None = None,
) -> dict[str, object]:
    """Run pip-audit and require it to report the exact locked inventory."""

    base: dict[str, object] = {
        "artifact_sha256": artifact_sha256,
        "lock_sha256": lock_sha256,
        "scanner": "pip-audit",
        "schema_version": 1,
    }
    if not enabled:
        return {**base, "reasons": ["DEPENDENCY_SCAN_NOT_REQUESTED"], "status": "BLOCKED"}
    active_toolchain = toolchain if toolchain is not None else _read_toolchain()
    scanner_contract = active_toolchain.get("dependency_scanner")
    if (
        not isinstance(scanner_contract, dict)
        or scanner_contract.get("status") != "PASS"
        or scanner_contract.get("name") != "pip-audit"
        or not isinstance(scanner_contract.get("version"), str)
    ):
        return {**base, "reasons": ["PIP_AUDIT_NOT_PINNED"], "status": "FAIL"}
    expected_scanner_version = str(scanner_contract["version"])
    if importlib.util.find_spec("pip_audit") is None:
        return {**base, "reasons": ["PIP_AUDIT_UNAVAILABLE"], "status": "BLOCKED"}
    try:
        version = importlib.metadata.version("pip-audit")
        result = subprocess.run(
            (
                sys.executable,
                "-I",
                "-m",
                "pip_audit",
                "--path",
                str(stage),
                "--format",
                "json",
                "--progress-spinner",
                "off",
            ),
            cwd=ROOT,
            env=_pip_environment(),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired, importlib.metadata.PackageNotFoundError):
        return {**base, "reasons": ["PIP_AUDIT_UNAVAILABLE"], "status": "BLOCKED"}
    if version != expected_scanner_version:
        return {
            **base,
            "reasons": ["PIP_AUDIT_VERSION_MISMATCH"],
            "scanner_version": version,
            "status": "FAIL",
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {**base, "reasons": ["PIP_AUDIT_OUTPUT_INVALID"], "status": "BLOCKED"}
    if isinstance(payload, dict):
        if "dependencies" not in payload:
            return {**base, "reasons": ["PIP_AUDIT_OUTPUT_INVALID"], "status": "BLOCKED"}
        dependencies = payload["dependencies"]
    else:
        dependencies = payload
    vulnerabilities: list[dict[str, object]] = []
    if not isinstance(dependencies, list):
        return {**base, "reasons": ["PIP_AUDIT_OUTPUT_INVALID"], "status": "BLOCKED"}
    audited_inventory: dict[str, str] = {}
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            return {**base, "reasons": ["PIP_AUDIT_OUTPUT_INVALID"], "status": "BLOCKED"}
        name = dependency.get("name")
        dependency_version = dependency.get("version")
        dependency_vulnerabilities = dependency.get("vulns")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(dependency_version, str)
            or not dependency_version.strip()
            or not isinstance(dependency_vulnerabilities, list)
        ):
            return {**base, "reasons": ["PIP_AUDIT_OUTPUT_INVALID"], "status": "BLOCKED"}
        normalized_name = _normalized_name(name)
        if normalized_name in audited_inventory:
            return {
                **base,
                "audited_dependency_count": len(dependencies),
                "expected_dependency_count": len(expected_inventory),
                "reasons": ["PIP_AUDIT_INVENTORY_DUPLICATE"],
                "scanner_version": version,
                "status": "FAIL",
            }
        audited_inventory[normalized_name] = dependency_version
        for vulnerability in dependency_vulnerabilities:
            if not isinstance(vulnerability, dict):
                return {
                    **base,
                    "reasons": ["PIP_AUDIT_OUTPUT_INVALID"],
                    "status": "BLOCKED",
                }
            identifier = vulnerability.get("id")
            fixes = vulnerability.get("fix_versions", [])
            if (
                not isinstance(identifier, str)
                or not identifier.strip()
                or not isinstance(fixes, list)
                or any(not isinstance(item, str) for item in fixes)
            ):
                return {
                    **base,
                    "reasons": ["PIP_AUDIT_OUTPUT_INVALID"],
                    "status": "BLOCKED",
                }
            vulnerabilities.append(
                {
                    "dependency": normalized_name,
                    "fixed_versions": sorted(fixes),
                    "id": identifier,
                    "version": dependency_version,
                }
            )
    expected = dict(expected_inventory)
    if len(expected) != len(expected_inventory):
        return {
            **base,
            "reasons": ["EXPECTED_DEPENDENCY_INVENTORY_INVALID"],
            "status": "BLOCKED",
        }
    inventory_summary = {
        "audited_dependency_count": len(audited_inventory),
        "expected_dependency_count": len(expected),
    }
    if audited_inventory != expected:
        return {
            **base,
            **inventory_summary,
            "reasons": ["PIP_AUDIT_INVENTORY_MISMATCH"],
            "scanner_version": version,
            "status": "FAIL",
        }
    vulnerabilities.sort(key=lambda item: (str(item["dependency"]), str(item["id"])))
    if vulnerabilities or result.returncode == 1:
        return {
            **base,
            **inventory_summary,
            "scanner_version": version,
            "status": "FAIL",
            "vulnerabilities": vulnerabilities,
            "vulnerability_count": len(vulnerabilities),
        }
    if result.returncode != 0:
        return {
            **base,
            **inventory_summary,
            "reasons": ["PIP_AUDIT_EXECUTION_FAILED"],
            "scanner_version": version,
            "status": "BLOCKED",
        }
    return {
        **base,
        **inventory_summary,
        "scanner_version": version,
        "status": "PASS",
        "vulnerabilities": [],
        "vulnerability_count": 0,
    }


def revalidate_artifact(
    artifact: Path,
    lock: Path,
    template: Path,
    toolchain_path: Path,
) -> dict[str, object]:
    """Freshly re-run every locally authoritative artifact proof used by D15-G04."""

    try:
        toolchain_raw = toolchain_path.read_bytes()
        lock_raw = lock.read_bytes()
    except OSError as error:
        raise ArtifactFailure(
            "ARTIFACT_REVALIDATION_INPUT_UNAVAILABLE", status="BLOCKED"
        ) from error
    toolchain = _parse_toolchain(toolchain_raw)
    builder = _validate_builder_identity(toolchain)
    lock_entries = validate_runtime_lock(lock)
    archive = inspect_archive(artifact)
    handlers = discover_lambda_handlers(template)
    artifact_sha256 = str(archive["sha256"])
    lock_sha256 = _sha256_bytes(lock_raw)
    with tempfile.TemporaryDirectory(prefix="aioa-day15-revalidate-") as temporary:
        stage = Path(temporary)
        try:
            with zipfile.ZipFile(artifact) as archive_file:
                archive_file.extractall(stage)
        except (OSError, zipfile.BadZipFile) as error:
            raise ArtifactFailure("ARTIFACT_ARCHIVE_UNREADABLE") from error
        inventory = validate_distribution_inventory(stage, lock_entries)
        clean_import = clean_import_handlers(artifact, handlers)
        container = lambda_container_validation(stage, handlers, toolchain=toolchain)
        scan = dependency_security_scan(
            stage,
            artifact_sha256=artifact_sha256,
            expected_inventory=inventory,
            lock_sha256=lock_sha256,
            enabled=True,
            toolchain=toolchain,
        )
    return {
        "archive_scan": archive,
        "builder": builder,
        "dependencies": [{"name": name, "version": version} for name, version in inventory],
        "handlers": list(handlers),
        "lambda_compatible_container_validation": container,
        "lambda_like_clean_import": clean_import,
        "scan": scan,
    }


def _parse_toolchain(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactFailure("TOOLCHAIN_RECORD_UNAVAILABLE", status="BLOCKED") from error
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or raw != (canonical_json(value) + "\n").encode()
        or value != EXPECTED_TOOLCHAIN
    ):
        raise ArtifactFailure("TOOLCHAIN_RECORD_INVALID", status="BLOCKED")
    return value


def _read_toolchain() -> dict[str, object]:
    try:
        raw = TOOLCHAIN_PATH.read_bytes()
    except OSError as error:
        raise ArtifactFailure("TOOLCHAIN_RECORD_UNAVAILABLE", status="BLOCKED") from error
    return _parse_toolchain(raw)


def _validate_builder_identity(toolchain: dict[str, object]) -> dict[str, str]:
    machine = platform.machine().casefold()
    try:
        pip_version = importlib.metadata.version("pip")
    except importlib.metadata.PackageNotFoundError as error:
        raise ArtifactFailure("PINNED_PIP_UNAVAILABLE", status="BLOCKED") from error
    identity = {
        "architecture": "x86_64",
        "pip_version": pip_version,
        "platform": "manylinux2014_x86_64",
        "python_version": platform.python_version(),
        "runtime": "python3.12",
        "zip_compression": "stored",
    }
    expected = toolchain.get("artifact_builder")
    if not isinstance(expected, dict) or expected != identity:
        raise ArtifactFailure("BUILDER_IDENTITY_NOT_PINNED", status="BLOCKED")
    if sys.version_info[:2] != (3, 12) or machine not in {"amd64", "x86_64"}:
        raise ArtifactFailure("BUILDER_IDENTITY_NOT_PINNED", status="BLOCKED")
    return identity


def build_artifact(
    paths: BuildPaths,
    *,
    run_dependency_scan: bool,
) -> dict[str, object]:
    """Build the artifact, deterministic manifest and separate sanitized scan report."""

    repository = validate_repository_inputs(paths)
    try:
        lock_bytes = paths.lock.read_bytes()
        template_bytes = paths.template.read_bytes()
        toolchain_bytes = TOOLCHAIN_PATH.read_bytes()
    except OSError as error:
        raise ArtifactFailure("CANONICAL_BUILD_INPUT_UNAVAILABLE") from error
    input_objects = {
        str(item["path"]): str(item["git_oid"])
        for item in repository["input_objects"]
        if isinstance(item, dict) and "path" in item and "git_oid" in item
    }
    captured_inputs = {
        _repo_relative(paths.lock): lock_bytes,
        _repo_relative(paths.template): template_bytes,
        _repo_relative(TOOLCHAIN_PATH): toolchain_bytes,
    }
    if any(
        relative not in input_objects
        or _git_blob_oid(data, oid_length=len(input_objects[relative])) != input_objects[relative]
        for relative, data in captured_inputs.items()
    ):
        raise ArtifactFailure("BUILD_INPUT_WORKTREE_HEAD_MISMATCH")
    toolchain = _parse_toolchain(toolchain_bytes)
    identity = _validate_builder_identity(toolchain)
    lock_sha256 = _sha256_bytes(lock_bytes)

    with tempfile.TemporaryDirectory(prefix="aioa-day15-build-") as temporary:
        temporary_root = Path(temporary)
        snapshot_lock = temporary_root / "runtime-lock.txt"
        snapshot_template = temporary_root / "template.yaml"
        snapshot_lock.write_bytes(lock_bytes)
        snapshot_template.write_bytes(template_bytes)
        lock_entries = validate_runtime_lock(snapshot_lock)
        handlers = discover_lambda_handlers(snapshot_template)
        independent_build = _build_independent_runtime(
            temporary_root,
            snapshot_lock,
            paths.source,
            lock_entries,
            wheelhouse=paths.wheelhouse,
        )
        stage = independent_build.primary.root
        copied_source = independent_build.primary.copied_source
        stage_files = independent_build.primary.files
        inventory = independent_build.primary.inventory
        source_sha256 = independent_build.primary.source_sha256
        candidate_artifact = independent_build.artifact
        artifact_sha256 = independent_build.artifact_sha256
        rebuild_sha256 = independent_build.rebuild_sha256

        archive_scan = inspect_archive(candidate_artifact)
        import_status = clean_import_handlers(candidate_artifact, handlers)
        container_validation = lambda_container_validation(
            stage,
            handlers,
            toolchain=toolchain,
        )
        scan_report = dependency_security_scan(
            stage,
            artifact_sha256=artifact_sha256,
            expected_inventory=tuple((entry.name, entry.version) for entry in lock_entries),
            lock_sha256=lock_sha256,
            enabled=run_dependency_scan,
            toolchain=toolchain,
        )

        repository_after = validate_repository_inputs(paths)
        if repository_after != repository:
            raise ArtifactFailure("BUILD_INPUT_COMMIT_CHANGED_DURING_BUILD")
        try:
            unchanged = (
                paths.lock.read_bytes() == lock_bytes
                and paths.template.read_bytes() == template_bytes
                and TOOLCHAIN_PATH.read_bytes() == toolchain_bytes
                and all(
                    (stage / relative).read_bytes()
                    == _normalized_source_bytes(paths.source / relative)
                    for relative in copied_source
                )
            )
        except OSError as error:
            raise ArtifactFailure("BUILD_INPUT_CHANGED_DURING_BUILD") from error
        if not unchanged:
            raise ArtifactFailure("BUILD_INPUT_CHANGED_DURING_BUILD")

        manifest = {
            "archive_scan": archive_scan,
            "artifact": {
                "code_sha256_base64": base64.b64encode(bytes.fromhex(artifact_sha256)).decode(
                    "ascii"
                ),
                "entry_count": len(stage_files),
                "filename": paths.artifact.name,
                "sha256": artifact_sha256,
                "size_bytes": candidate_artifact.stat().st_size,
            },
            "builder": identity,
            "dependencies": [{"name": name, "version": version} for name, version in inventory],
            "handlers": list(handlers),
            "inputs": {
                "lock_sha256": lock_sha256,
                "source_sha256": source_sha256,
            },
            "deterministic_rebuild": {
                "sha256": rebuild_sha256,
                "status": "PASS",
            },
            "lambda_compatible_container_validation": container_validation,
            "lambda_like_clean_import": import_status,
            "repository": repository,
            "schema_version": 1,
        }
        _atomic_publish_artifact(candidate_artifact, paths.artifact)
        _atomic_canonical_json(paths.manifest, manifest)
        _atomic_canonical_json(paths.scan_report, scan_report)

    scan_status = str(scan_report["status"])
    container_status = str(container_validation["status"])
    overall = combine_build_status(scan_status, container_status)
    return {
        "artifact_sha256": artifact_sha256,
        "dependency_scan": scan_status,
        "handler_count": len(handlers),
        "lambda_container_validation": container_status,
        "manifest_sha256": _sha256_bytes(paths.manifest.read_bytes()),
        "status": overall,
    }


def combine_build_status(*statuses: str) -> str:
    """A missing mandatory build proof blocks release; any negative proof fails it."""

    if "FAIL" in statuses:
        return "FAIL"
    if any(status != "PASS" for status in statuses):
        return "BLOCKED"
    return "PASS"


def _exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "PARTIAL": 2, "BLOCKED": 3}.get(status, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--scan-report", type=Path, default=DEFAULT_SCAN_REPORT)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--no-dependency-scan", action="store_true")
    parser.add_argument("--verify-lock", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.verify_lock:
            entries = validate_runtime_lock(args.lock)
            payload: dict[str, object] = {
                "distribution_count": len(entries),
                "lock_sha256": _sha256_bytes(args.lock.read_bytes()),
                "status": "PASS",
            }
        else:
            payload = build_artifact(
                BuildPaths(
                    lock=args.lock,
                    source=args.source,
                    template=args.template,
                    artifact=args.artifact,
                    manifest=args.manifest,
                    scan_report=args.scan_report,
                    wheelhouse=args.wheelhouse,
                ),
                run_dependency_scan=not args.no_dependency_scan,
            )
    except ArtifactFailure as error:
        payload = {"reasons": [error.reason], "status": error.status}
    if args.json:
        print(canonical_json(payload))
    else:
        reasons = ",".join(payload.get("reasons", [])) or "-"
        print(f"DAY15_ARTIFACT {payload['status']} reasons={reasons}")
    return _exit_code(str(payload["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
