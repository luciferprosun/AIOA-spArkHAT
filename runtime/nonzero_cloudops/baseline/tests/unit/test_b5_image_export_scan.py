from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.scan_b5_image_export import ImageScanError, scan_rootfs

IMAGE_ID = "1" * 64
IMAGE_DIGEST = f"sha256:{'2' * 64}"
SOURCE_COMMIT = "dbea5411b1c0d81de0035d9ef08e28211fb79e79"


def _rootfs(tmp_path: Path) -> Path:
    rootfs = tmp_path / "rootfs"
    python = rootfs / "usr/local/bin/python"
    application = (
        rootfs / "usr/local/lib/python3.12/site-packages/aioa_cloudops_agent/app.py"
    )
    python.parent.mkdir(parents=True)
    application.parent.mkdir(parents=True)
    python.write_bytes(b"python-binary")
    application.write_text("SAFE = True\n", encoding="utf-8")
    return rootfs


def test_image_export_scan_is_deterministic_and_hash_bound(tmp_path: Path) -> None:
    rootfs = _rootfs(tmp_path)

    first = scan_rootfs(
        rootfs.resolve(),
        image_id=IMAGE_ID,
        image_digest=IMAGE_DIGEST,
        source_commit=SOURCE_COMMIT,
    )
    second = scan_rootfs(
        rootfs.resolve(),
        image_id=IMAGE_ID,
        image_digest=IMAGE_DIGEST,
        source_commit=SOURCE_COMMIT,
    )

    assert first == second
    assert first["status"] == "PASS"
    assert first["findings_count"] == 0
    material = {name: value for name, value in first.items() if name != "receipt_sha256"}
    canonical = json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert first["receipt_sha256"] == hashlib.sha256(canonical).hexdigest()


@pytest.mark.parametrize(
    ("relative_path", "content", "reason"),
    [
        ("app/.env", b"safe-looking-name", "ENV_FILE"),
        ("app/operator.token", b"not-printed", "BAKED_OPERATOR_TOKEN"),
        (
            "app/private.txt",
            b"-----BEGIN "
            + b"PRIVATE KEY-----\n"
            + b"A" * 64
            + b"\n"
            + b"B" * 64
            + b"\n-----END "
            + b"PRIVATE KEY-----",
            "PRIVATE_KEY_MATERIAL",
        ),
        ("app/value.txt", b"AKIA" + b"1234567890ABCDEF", "AWS_ACCESS_KEY"),
    ],
)
def test_image_export_scan_reports_only_path_and_reason(
    tmp_path: Path,
    relative_path: str,
    content: bytes,
    reason: str,
) -> None:
    rootfs = _rootfs(tmp_path)
    target = rootfs / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    receipt = scan_rootfs(
        rootfs.resolve(),
        image_id=IMAGE_ID,
        image_digest=IMAGE_DIGEST,
        source_commit=SOURCE_COMMIT,
    )

    assert receipt["status"] == "FAIL"
    assert {finding["reason"] for finding in receipt["findings"]} == {reason}
    assert content.decode("utf-8") not in json.dumps(receipt)


def test_image_export_scan_rejects_unbound_or_incomplete_rootfs(tmp_path: Path) -> None:
    rootfs = tmp_path / "empty"
    rootfs.mkdir()

    with pytest.raises(ImageScanError, match="B5_IMAGE_SCAN_ROOTFS_CONTRACT_INVALID"):
        scan_rootfs(
            rootfs.resolve(),
            image_id=IMAGE_ID,
            image_digest=IMAGE_DIGEST,
            source_commit=SOURCE_COMMIT,
        )
