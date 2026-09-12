from __future__ import annotations

import errno
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.day15 import build_lambda_artifact as artifact


def test_runtime_lock_is_complete_exact_and_hash_locked() -> None:
    entries = artifact.validate_runtime_lock()

    assert len(entries) == 55
    assert artifact.REQUIRED_DIRECT_DISTRIBUTIONS.issubset({entry.name for entry in entries})
    assert all(entry.hashes for entry in entries)
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", digest) for entry in entries for digest in entry.hashes
    )


@pytest.mark.parametrize(
    "line,reason",
    [
        ("demo>=1\n", "RUNTIME_LOCK_HAS_UNPINNED_ENTRY"),
        ("demo==1\n", "RUNTIME_LOCK_ENTRY_MISSING_HASH"),
        ("-e ../demo\n", "RUNTIME_LOCK_HAS_EXTERNAL_OR_LOCAL_REFERENCE"),
        ("demo @ file:///tmp/demo.whl\n", "RUNTIME_LOCK_HAS_EXTERNAL_OR_LOCAL_REFERENCE"),
        (
            "--index-url https://example.invalid/simple\n",
            "RUNTIME_LOCK_HAS_EXTERNAL_OR_LOCAL_REFERENCE",
        ),
    ],
)
def test_runtime_lock_rejects_unreproducible_entries(
    tmp_path: Path,
    line: str,
    reason: str,
) -> None:
    lock = tmp_path / "runtime.txt"
    lock.write_text(line, encoding="utf-8")

    with pytest.raises(artifact.ArtifactFailure, match=reason):
        artifact.validate_runtime_lock(lock)


def test_deterministic_zip_ignores_tree_creation_order_mtime_and_output_name(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for root, order in ((first, ("b.py", "a.py")), (second, ("a.py", "b.py"))):
        for index, name in enumerate(order):
            path = root / name
            path.write_bytes(f"VALUE = {name!r}\n".encode())
            os.utime(path, (index + 1, index + 1))

    first_zip = tmp_path / "one.zip"
    second_zip = tmp_path / "two.zip"
    assert artifact.write_deterministic_zip(first, first_zip) == artifact.write_deterministic_zip(
        second,
        second_zip,
    )
    assert first_zip.read_bytes() == second_zip.read_bytes()
    assert artifact.inspect_archive(first_zip) == artifact.inspect_archive(second_zip)


def test_artifact_publish_copies_locally_before_same_filesystem_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "temporary-build"
    source_root.mkdir()
    source = source_root / "candidate.zip"
    source.write_bytes(b"complete-artifact")
    destination = tmp_path / "separate-mount" / "artifact.zip"
    destination.parent.mkdir()
    destination.write_bytes(b"previous-artifact")
    real_replace = artifact.os.replace
    replace_calls: list[tuple[Path, Path]] = []

    def simulated_cross_device_replace(
        source_path: os.PathLike[str], target_path: os.PathLike[str]
    ) -> None:
        resolved_source = Path(source_path)
        resolved_target = Path(target_path)
        if resolved_source.parent != resolved_target.parent:
            raise OSError(errno.EXDEV, "simulated cross-device move")
        replace_calls.append((resolved_source, resolved_target))
        real_replace(resolved_source, resolved_target)

    monkeypatch.setattr(artifact.os, "replace", simulated_cross_device_replace)

    artifact._atomic_publish_artifact(source, destination)

    assert source.read_bytes() == b"complete-artifact"
    assert destination.read_bytes() == b"complete-artifact"
    assert destination.stat().st_mode & 0o777 == 0o644
    assert len(replace_calls) == 1
    assert replace_calls[0][0].parent == destination.parent
    assert replace_calls[0][1] == destination
    assert not tuple(destination.parent.glob("day15-artifact-*.tmp"))


def test_artifact_publish_failure_keeps_previous_file_and_cleans_partial_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "candidate.zip"
    source.write_bytes(b"complete-artifact")
    destination = tmp_path / "dist" / "artifact.zip"
    destination.parent.mkdir()
    destination.write_bytes(b"previous-artifact")

    def interrupted_copy(_source: object, target: object, _length: int = 0) -> None:
        target.write(b"partial")  # type: ignore[attr-defined]
        raise OSError("sensitive operating-system detail")

    monkeypatch.setattr(artifact.shutil, "copyfileobj", interrupted_copy)

    with pytest.raises(artifact.ArtifactFailure) as failure:
        artifact._atomic_publish_artifact(source, destination)

    assert failure.value.reason == "ARTIFACT_PUBLISH_FAILED"
    assert str(failure.value) == "ARTIFACT_PUBLISH_FAILED"
    assert destination.read_bytes() == b"previous-artifact"
    assert not tuple(destination.parent.glob("day15-artifact-*.tmp"))


def test_artifact_publish_rejects_symlink_destination(tmp_path: Path) -> None:
    source = tmp_path / "candidate.zip"
    source.write_bytes(b"complete-artifact")
    symlink_target = tmp_path / "real-artifact.zip"
    symlink_target.write_bytes(b"previous-artifact")
    destination = tmp_path / "artifact.zip"
    destination.symlink_to(symlink_target)

    with pytest.raises(artifact.ArtifactFailure) as failure:
        artifact._atomic_publish_artifact(source, destination)

    assert failure.value.reason == "BUILD_OUTPUT_SYMLINK_FORBIDDEN"
    assert symlink_target.read_bytes() == b"previous-artifact"


def test_runtime_rebuild_uses_two_distinct_clean_installs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    package = source / "aioa_cloudops_agent"
    package.mkdir(parents=True)
    module = package / "module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    lock = tmp_path / "runtime.txt"
    lock.write_text("unused-by-fake-installer\n", encoding="utf-8")
    temporary_root = tmp_path / "build"
    temporary_root.mkdir()
    install_calls: list[Path] = []
    initially_present: list[tuple[str, ...]] = []

    def fake_install(
        _lock: Path,
        stage: Path,
        *,
        wheelhouse: Path | None,
    ) -> None:
        assert wheelhouse is None
        install_calls.append(stage)
        initially_present.append(tuple(candidate.name for candidate in stage.iterdir()))
        metadata = stage / "demo-1.dist-info" / "METADATA"
        metadata.parent.mkdir()
        metadata.write_text("Name: demo\nVersion: 1\n", encoding="utf-8")
        (stage / "installed.txt").write_text("stable\n", encoding="utf-8")
        synthetic_key = b"AK" + b"IA" + (b"A" * 16)
        for relative in artifact.NONRUNTIME_DEPENDENCY_EXAMPLE_PATHS:
            example = stage / relative
            example.parent.mkdir(parents=True, exist_ok=True)
            example.write_bytes(synthetic_key)
        runtime_model = stage / "botocore/data/iam/2010-05-08/service-2.json"
        runtime_model.write_text("{}\n", encoding="utf-8")
        retained_doc = stage / "boto3/examples/s3.rst"
        retained_doc.write_text("runtime-near-miss\n", encoding="utf-8")

    monkeypatch.setattr(artifact, "install_locked_dependencies", fake_install)
    monkeypatch.setattr(artifact, "_repo_relative", lambda _path: "src/module.py")
    monkeypatch.setattr(artifact, "_git", lambda *_arguments: "VALUE = 1\n")

    result = artifact._build_independent_runtime(
        temporary_root,
        lock,
        source,
        (artifact.LockEntry("demo", "1", ("a" * 64,)),),
        wheelhouse=None,
    )

    assert install_calls == [temporary_root / "stage", temporary_root / "rebuild-stage"]
    assert initially_present == [(), ()]
    assert result.primary.root == install_calls[0]
    assert result.artifact_sha256 == result.rebuild_sha256
    assert artifact.inspect_archive(result.artifact)["status"] == "PASS"
    for stage in install_calls:
        assert all(
            not (stage / relative).exists()
            for relative in artifact.NONRUNTIME_DEPENDENCY_EXAMPLE_PATHS
        )
        assert (stage / "botocore/data/iam/2010-05-08/service-2.json").is_file()
        assert (stage / "boto3/examples/s3.rst").is_file()
        assert artifact._read_distribution_inventory(stage) == (("demo", "1"),)


def test_runtime_rebuild_rejects_difference_from_second_clean_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src"
    package = source / "aioa_cloudops_agent"
    package.mkdir(parents=True)
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    lock = tmp_path / "runtime.txt"
    lock.write_text("unused-by-fake-installer\n", encoding="utf-8")
    temporary_root = tmp_path / "build"
    temporary_root.mkdir()
    install_count = 0

    def fake_install(
        _lock: Path,
        stage: Path,
        *,
        wheelhouse: Path | None,
    ) -> None:
        nonlocal install_count
        assert wheelhouse is None
        install_count += 1
        metadata = stage / "demo-1.dist-info" / "METADATA"
        metadata.parent.mkdir()
        metadata.write_text("Name: demo\nVersion: 1\n", encoding="utf-8")
        (stage / "installed.txt").write_text(f"install-{install_count}\n", encoding="utf-8")

    monkeypatch.setattr(artifact, "install_locked_dependencies", fake_install)
    monkeypatch.setattr(artifact, "_repo_relative", lambda _path: "src/module.py")
    monkeypatch.setattr(artifact, "_git", lambda *_arguments: "VALUE = 1\n")

    with pytest.raises(artifact.ArtifactFailure) as mismatch:
        artifact._build_independent_runtime(
            temporary_root,
            lock,
            source,
            (artifact.LockEntry("demo", "1", ("a" * 64,)),),
            wheelhouse=None,
        )

    assert mismatch.value.reason == "DETERMINISTIC_REBUILD_MISMATCH"
    assert install_count == 2


def test_source_copy_normalizes_line_endings_and_rejects_unknown_binary(tmp_path: Path) -> None:
    source = tmp_path / "src"
    package = source / "aioa_cloudops_agent"
    package.mkdir(parents=True)
    (package / "module.py").write_bytes(b"A = 1\r\nB = 2\r")
    stage = tmp_path / "stage"
    stage.mkdir()

    assert artifact.copy_runtime_source(source, stage) == ("aioa_cloudops_agent/module.py",)
    assert (stage / "aioa_cloudops_agent" / "module.py").read_bytes() == b"A = 1\nB = 2\n"

    (package / "native.so").write_bytes(b"not-reviewed")
    with pytest.raises(artifact.ArtifactFailure, match="SOURCE_FILE_TYPE_NOT_ALLOWLISTED"):
        artifact.copy_runtime_source(source, stage)


@pytest.mark.parametrize("name", ["escape.pth", "direct_url.json", "payload.pem", "module.pyc"])
def test_staging_scan_rejects_host_or_executable_install_metadata(
    tmp_path: Path, name: str
) -> None:
    (tmp_path / name).write_text("unsafe", encoding="utf-8")

    with pytest.raises(artifact.ArtifactFailure, match="ARTIFACT_FORBIDDEN_RUNTIME_PATH"):
        artifact.inspect_staging_tree(tmp_path)


def test_staging_scan_allows_only_exact_runtime_ca_bundle_paths(tmp_path: Path) -> None:
    for relative in artifact.RUNTIME_CA_BUNDLE_PATHS:
        bundle = tmp_path / relative
        bundle.parent.mkdir(parents=True, exist_ok=True)
        bundle.write_text("-----BEGIN CERTIFICATE-----\npublic-ca\n", encoding="utf-8")

    assert artifact.inspect_staging_tree(tmp_path) == tuple(
        sorted(path.as_posix() for path in artifact.RUNTIME_CA_BUNDLE_PATHS)
    )


@pytest.mark.parametrize(
    "relative",
    [
        "cacert.pem",
        "botocore/cacert-copy.pem",
        "certifi/CACERT.pem",
        "certifi/nested/cacert.pem",
        "other/cacert.pem",
    ],
)
def test_staging_scan_rejects_renamed_or_extra_pem_paths(
    tmp_path: Path,
    relative: str,
) -> None:
    candidate = tmp_path / relative
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("-----BEGIN CERTIFICATE-----\npublic-ca\n", encoding="utf-8")

    with pytest.raises(artifact.ArtifactFailure, match="ARTIFACT_FORBIDDEN_RUNTIME_PATH"):
        artifact.inspect_staging_tree(tmp_path)


@pytest.mark.parametrize("relative", artifact.RUNTIME_CA_BUNDLE_PATHS)
def test_staging_scan_rejects_private_key_content_in_allowed_ca_bundle_path(
    tmp_path: Path,
    relative: Path,
) -> None:
    bundle = tmp_path / relative
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_bytes(artifact.PRIVATE_KEY_PEM_MARKER + b"\nnot-a-ca\n")

    with pytest.raises(artifact.ArtifactFailure, match="ARTIFACT_CREDENTIAL_PATTERN"):
        artifact.inspect_staging_tree(tmp_path)


def test_staging_scan_rejects_symlink_and_credential_patterns(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("safe", encoding="utf-8")
    (tmp_path / "link.py").symlink_to(target)
    with pytest.raises(artifact.ArtifactFailure, match="ARTIFACT_SYMLINK_FORBIDDEN"):
        artifact.inspect_staging_tree(tmp_path)

    (tmp_path / "link.py").unlink()
    target.write_bytes(artifact.PRIVATE_KEY_PEM_MARKER)
    with pytest.raises(artifact.ArtifactFailure, match="ARTIFACT_CREDENTIAL_PATTERN"):
        artifact.inspect_staging_tree(tmp_path)


def test_clean_import_proves_every_declared_callable_from_archive(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "demo.py").write_text(
        "def handler(event, context):\n    return True\n", encoding="utf-8"
    )
    archive = tmp_path / "demo.zip"
    artifact.write_deterministic_zip(stage, archive)

    assert artifact.clean_import_handlers(archive, ("demo.handler",)) == "PASS"


def test_dependency_scan_and_container_absence_are_blocking_not_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifact.importlib.util, "find_spec", lambda _name: None)
    scan = artifact.dependency_security_scan(
        tmp_path,
        artifact_sha256="a" * 64,
        expected_inventory=(),
        lock_sha256="b" * 64,
        enabled=True,
    )
    container = artifact.lambda_container_validation(
        tmp_path,
        (),
        toolchain={
            "lambda_compatible_container": {
                "reason": "CONTAINER_ENGINE_UNAVAILABLE",
                "status": "BLOCKED",
            }
        },
    )

    assert scan["status"] == "BLOCKED"
    assert container["status"] == "BLOCKED"
    assert artifact.combine_build_status(str(scan["status"]), str(container["status"])) == "BLOCKED"


def _fake_dependency_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    *,
    returncode: int = 0,
) -> dict[str, object]:
    monkeypatch.setattr(artifact.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(artifact.importlib.metadata, "version", lambda _name: "2.10.1")
    monkeypatch.setattr(
        artifact.subprocess,
        "run",
        lambda *_args, **_kwargs: artifact.subprocess.CompletedProcess(
            args=(),
            returncode=returncode,
            stdout=artifact.json.dumps(payload),
            stderr="",
        ),
    )
    return artifact.dependency_security_scan(
        tmp_path,
        artifact_sha256="a" * 64,
        expected_inventory=(("alpha", "1"), ("beta", "2")),
        lock_sha256="b" * 64,
        enabled=True,
        toolchain=artifact._read_toolchain(),
    )


def test_dependency_scan_pass_requires_exact_complete_locked_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _fake_dependency_scan(
        tmp_path,
        monkeypatch,
        {
            "dependencies": [
                {"name": "Alpha", "version": "1", "vulns": []},
                {"name": "beta", "version": "2", "vulns": []},
            ]
        },
    )

    assert report["status"] == "PASS"
    assert report["audited_dependency_count"] == 2
    assert report["expected_dependency_count"] == 2


def test_dependency_scan_rejects_installed_scanner_version_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifact.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(artifact.importlib.metadata, "version", lambda _name: "2.10.0")

    report = artifact.dependency_security_scan(
        tmp_path,
        artifact_sha256="a" * 64,
        expected_inventory=(),
        lock_sha256="b" * 64,
        enabled=True,
        toolchain=artifact._read_toolchain(),
    )

    assert report["status"] == "FAIL"
    assert report["reasons"] == ["PIP_AUDIT_VERSION_MISMATCH"]


def test_container_validation_binds_engine_version_platform_and_manifest_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolchain = artifact._read_toolchain()
    contract = toolchain["lambda_compatible_container"]
    assert isinstance(contract, dict)
    image = str(contract["image"])
    digest = image.rsplit("@", 1)[1]
    monkeypatch.setattr(artifact.shutil, "which", lambda _name: "/usr/bin/podman")
    calls: list[tuple[str, ...]] = []

    def fake_run(command: object, **_kwargs: object) -> SimpleNamespace:
        arguments = tuple(command)  # type: ignore[arg-type]
        calls.append(arguments)
        if arguments[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="podman version 4.9.3\n")
        if arguments[1:3] == ("image", "inspect"):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"Architecture": "amd64", "Digest": digest}]),
            )
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(artifact.subprocess, "run", fake_run)

    result = artifact.lambda_container_validation(tmp_path, (), toolchain=toolchain)

    assert result == {
        "architecture": "amd64",
        "engine": "podman",
        "engine_version": "4.9.3",
        "image_digest": digest,
        "status": "PASS",
        "validator": "lambda-python3.12-x86_64-container",
    }
    run_command = next(arguments for arguments in calls if "run" in arguments)
    assert {
        "--cap-drop=ALL",
        "--cgroups=disabled",
        "--ipc=none",
        "--mount=type=bind,src=/dev/pts,dst=/dev/pts,ro=true",
        "--network=none",
        "--read-only",
        "--security-opt=no-new-privileges",
    } <= set(run_command)
    assert "--pull=never" in run_command
    assert "--platform=linux/amd64" in run_command

    changed = dict(toolchain)
    changed["lambda_compatible_container"] = {**contract, "engine_version": "4.9.2"}
    mismatch = artifact.lambda_container_validation(tmp_path, (), toolchain=changed)
    assert mismatch == {"reason": "CONTAINER_ENGINE_VERSION_MISMATCH", "status": "FAIL"}


@pytest.mark.parametrize(
    "dependencies,reason",
    [
        ([], "PIP_AUDIT_INVENTORY_MISMATCH"),
        ([{"name": "alpha", "version": "1", "vulns": []}], "PIP_AUDIT_INVENTORY_MISMATCH"),
        (
            [
                {"name": "alpha", "version": "1", "vulns": []},
                {"name": "beta", "version": "2", "vulns": []},
                {"name": "gamma", "version": "3", "vulns": []},
            ],
            "PIP_AUDIT_INVENTORY_MISMATCH",
        ),
        (
            [
                {"name": "alpha", "version": "1", "vulns": []},
                {"name": "beta", "version": "999", "vulns": []},
            ],
            "PIP_AUDIT_INVENTORY_MISMATCH",
        ),
        (
            [
                {"name": "alpha", "version": "1", "vulns": []},
                {"name": "alpha", "version": "1", "vulns": []},
            ],
            "PIP_AUDIT_INVENTORY_DUPLICATE",
        ),
    ],
)
def test_dependency_scan_rejects_incomplete_extra_wrong_or_duplicate_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dependencies: list[object],
    reason: str,
) -> None:
    report = _fake_dependency_scan(
        tmp_path,
        monkeypatch,
        {"dependencies": dependencies},
    )

    assert report["status"] == "FAIL"
    assert report["reasons"] == [reason]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"dependencies": [None]},
        {"dependencies": [{"name": "alpha", "version": "1"}]},
    ],
)
def test_dependency_scan_blocks_malformed_scanner_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    report = _fake_dependency_scan(tmp_path, monkeypatch, payload)

    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["PIP_AUDIT_OUTPUT_INVALID"]


def _fake_clean_git(arguments_log: list[tuple[str, ...]]):
    oid = "a" * 40

    def fake_git(*arguments: str) -> str:
        arguments_log.append(arguments)
        if arguments[:2] == ("rev-parse", "--show-toplevel"):
            return f"{artifact.ROOT}\n"
        if arguments[:2] == ("rev-parse", "--verify"):
            return f"{'b' * 40}\n"
        if arguments[:2] == ("status", "--porcelain=v1"):
            return ""
        if arguments[:2] == ("ls-files", "--stage"):
            paths = arguments[arguments.index("--") + 1 :]
            return "".join(f"100644 {oid} 0\t{path}\n" for path in paths)
        if arguments[:3] == ("ls-tree", "-r", "HEAD"):
            paths = arguments[arguments.index("--") + 1 :]
            return "".join(f"100644 blob {oid}\t{path}\n" for path in paths)
        if arguments[:2] == ("hash-object", "--"):
            return "".join(f"{oid}\n" for _ in arguments[2:])
        if arguments == ("rev-parse", "HEAD:src/aioa_cloudops_agent"):
            return f"{'c' * 40}\n"
        raise AssertionError(arguments)

    return fake_git


def test_repository_provenance_binds_clean_head_index_worktree_and_source_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(artifact, "_git", _fake_clean_git(calls))
    paths = artifact.BuildPaths(
        lock=artifact.DEFAULT_LOCK,
        source=artifact.DEFAULT_SOURCE,
        template=artifact.DEFAULT_TEMPLATE,
        artifact=artifact.DEFAULT_ARTIFACT,
        manifest=artifact.DEFAULT_MANIFEST,
        scan_report=artifact.DEFAULT_SCAN_REPORT,
    )

    provenance = artifact.validate_repository_inputs(paths)

    assert provenance["status"] == "CLEAN"
    assert provenance["commit_oid"] == "b" * 40
    assert provenance["source_tree_oid"] == "c" * 40
    assert all(not str(item["path"]).startswith("/") for item in provenance["input_objects"])
    assert any(call[:2] == ("hash-object", "--") for call in calls)


def test_repository_provenance_rejects_dirty_or_noncanonical_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    fake_git = _fake_clean_git(calls)

    def dirty_git(*arguments: str) -> str:
        if arguments[:2] == ("status", "--porcelain=v1"):
            return " M src/example.py\n"
        return fake_git(*arguments)

    monkeypatch.setattr(artifact, "_git", dirty_git)
    canonical = artifact.BuildPaths(
        lock=artifact.DEFAULT_LOCK,
        source=artifact.DEFAULT_SOURCE,
        template=artifact.DEFAULT_TEMPLATE,
        artifact=artifact.DEFAULT_ARTIFACT,
        manifest=artifact.DEFAULT_MANIFEST,
        scan_report=artifact.DEFAULT_SCAN_REPORT,
    )
    with pytest.raises(artifact.ArtifactFailure) as dirty:
        artifact.validate_repository_inputs(canonical)
    assert dirty.value.reason == "REPOSITORY_NOT_CLEAN"
    assert dirty.value.status == "BLOCKED"

    alternate = artifact.BuildPaths(
        lock=tmp_path / "lock.txt",
        source=canonical.source,
        template=canonical.template,
        artifact=canonical.artifact,
        manifest=canonical.manifest,
        scan_report=canonical.scan_report,
    )
    with pytest.raises(artifact.ArtifactFailure, match="NONCANONICAL_BUILD_INPUT_FORBIDDEN"):
        artifact.validate_repository_inputs(alternate)


def test_exact_builder_identity_is_loaded_from_toolchain() -> None:
    toolchain = artifact._read_toolchain()
    identity = artifact._validate_builder_identity(toolchain)

    assert identity == toolchain["artifact_builder"]

    changed = dict(toolchain)
    changed["artifact_builder"] = {**identity, "pip_version": "0"}
    with pytest.raises(artifact.ArtifactFailure) as mismatch:
        artifact._validate_builder_identity(changed)
    assert mismatch.value.reason == "BUILDER_IDENTITY_NOT_PINNED"
    assert mismatch.value.status == "BLOCKED"


def test_toolchain_parser_rejects_self_fulfilling_version_or_digest_drift() -> None:
    toolchain = artifact._read_toolchain()
    changed = dict(toolchain)
    changed["dependency_scanner"] = {
        "name": "pip-audit",
        "status": "PASS",
        "version": "999.0.0",
    }

    with pytest.raises(artifact.ArtifactFailure) as failure:
        artifact._parse_toolchain((artifact.canonical_json(changed) + "\n").encode())

    assert failure.value.reason == "TOOLCHAIN_RECORD_INVALID"
    assert failure.value.status == "BLOCKED"


def test_builder_source_contains_no_literal_account_placeholder_or_legacy_tag_contract() -> None:
    text = artifact.BUILDER_PATH.read_text(encoding="utf-8")

    assert "0" * 12 not in text
    assert "SANDBOX_REQUIRED_TAG_" not in text


def test_local_builder_subprocess_environments_do_not_repurpose_home() -> None:
    assert "HOME" not in artifact._git_environment()
    assert "HOME" not in artifact._pip_environment()
    assert "HOME" not in artifact._handler_environment()
