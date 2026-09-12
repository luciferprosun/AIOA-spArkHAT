from __future__ import annotations

import json
from pathlib import Path

from scripts.phase3.scan_secrets import scan_files


def test_safe_files_and_documented_synthetic_ids_pass_without_exposing_values(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "src/safe.py"
    safe.parent.mkdir(parents=True)
    safe.write_text("VALUE = 'not-a-secret'\n", encoding="utf-8")
    fixture = tmp_path / "tests/fixture.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        "ACCOUNT = '" + "123456789012" + "'\nINSTANCE = 'i-0123456789abcdef0'\n",
        encoding="utf-8",
    )

    receipt = scan_files(tmp_path, ("src/safe.py", "tests/fixture.py"))
    rendered = json.dumps(receipt)

    assert receipt["status"] == "PASS"
    assert receipt["findings_count"] == 0
    assert receipt["reviewed_synthetic_identifiers_count"] == 2
    assert receipt["secret_values_emitted"] is False
    assert "123456789012" not in rendered
    assert "i-0123456789abcdef0" not in rendered


def test_access_keys_private_keys_tokens_and_secret_assignments_fail_redacted(
    tmp_path: Path,
) -> None:
    path = tmp_path / "src/leak.txt"
    path.parent.mkdir(parents=True)
    leaked_values = (
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "-----BEGIN " + "PRIVATE KEY-----",
        "gh" + "p_abcdefghijklmnopqrstuvwxyz",
        "sk" + "-proj-abcdefghijklmnopqrstuvwxyz",
        "aws_secret_access_key=" + "A" * 40,
        "approval_token='" + "z" * 32 + "'",
    )
    path.write_text("\n".join(leaked_values), encoding="utf-8")

    receipt = scan_files(tmp_path, ("src/leak.txt",))
    rendered = json.dumps(receipt)

    assert receipt["status"] == "FAIL"
    assert receipt["findings_count"] == 6
    assert all(value not in rendered for value in leaked_values)


def test_raw_account_or_instance_identity_outside_fixture_paths_fails(tmp_path: Path) -> None:
    path = tmp_path / "src/config.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "ACCOUNT = '" + "123456789012" + "'\nTARGET = 'i-0123456789abcdef0'\n",
        encoding="utf-8",
    )

    receipt = scan_files(tmp_path, ("src/config.py",))

    assert receipt["status"] == "FAIL"
    assert {item["category"] for item in receipt["findings"]} == {  # type: ignore[index]
        "RAW_AWS_ACCOUNT_ID",
        "RAW_EC2_INSTANCE_ID",
    }


def test_env_key_symlink_oversized_and_missing_files_fail_closed(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SAFE=placeholder\n", encoding="utf-8")
    key = tmp_path / "client.pem"
    key.write_text("placeholder\n", encoding="utf-8")
    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = tmp_path / "linked.txt"
    link.symlink_to(target)
    oversized = tmp_path / "oversized.txt"
    oversized.write_bytes(b"x" * 5_000_001)

    receipt = scan_files(
        tmp_path,
        (".env", "client.pem", "linked.txt", "oversized.txt", "missing.txt"),
    )

    assert receipt["status"] == "FAIL"
    categories = {item["category"] for item in receipt["findings"]}  # type: ignore[index]
    assert categories == {
        "ENVIRONMENT_SECRET_FILE",
        "PRIVATE_KEY_FILE",
        "REPOSITORY_FILE_UNAVAILABLE",
        "SYMLINKED_REPOSITORY_FILE",
        "UNSCANNED_OVERSIZED_FILE",
    }


def test_scan_receipt_is_deterministic_and_records_zero_external_activity(tmp_path: Path) -> None:
    first = tmp_path / "b.txt"
    second = tmp_path / "a.txt"
    first.write_text("safe", encoding="utf-8")
    second.write_text("safe", encoding="utf-8")

    left = scan_files(tmp_path, ("b.txt", "a.txt"))
    right = scan_files(tmp_path, ("a.txt", "b.txt", "a.txt"))

    assert left == right
    assert left["network_connections"] == left["aws_mutations"] == left["live_receipts"] == 0
