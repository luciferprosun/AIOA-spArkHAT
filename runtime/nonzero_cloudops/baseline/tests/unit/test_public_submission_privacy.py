from __future__ import annotations

from pathlib import Path

from scripts.scan_public_submission import scan_tree


def test_public_scan_passes_safe_tree_and_reviews_synthetic_test_fixtures(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("public candidate\n", encoding="utf-8")
    fixture = tmp_path / "tests" / "fixture.py"
    fixture.parent.mkdir()
    fixture.write_text(
        "ACCOUNT = '111122223333'\n"
        "EMAIL = 'reviewer@example.invalid'\n"
        "PATH = '/" + "home/tester/fixture'\n",
        encoding="utf-8",
    )
    image = tmp_path / "screenshot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n\0fixture")

    receipt = scan_tree(tmp_path)

    assert receipt["status"] == "PASS"
    assert receipt["findings_count"] == 0
    assert receipt["reviewed_synthetic_fixtures_count"] == 3
    assert receipt["binary_files_reviewed"] == 1
    assert receipt["secret_values_emitted"] is False
    assert receipt["personal_values_emitted"] is False


def test_public_scan_fails_closed_without_emitting_values(tmp_path: Path) -> None:
    secret_value = "AK" + "IA" + "A" * 16
    personal_value = "person@real-domain.example"
    (tmp_path / "unsafe.txt").write_text(
        f"{secret_value}\n{personal_value}\n",
        encoding="utf-8",
    )
    (tmp_path / "personal.pdf").write_bytes(b"%PDF-fixture")

    receipt = scan_tree(tmp_path)
    rendered = str(receipt)

    assert receipt["status"] == "FAIL"
    assert receipt["findings_count"] == 3
    assert secret_value not in rendered
    assert personal_value not in rendered
    assert receipt["secret_values_emitted"] is False
    assert receipt["emails_emitted"] is False


def test_public_scan_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("safe\n", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(target)

    receipt = scan_tree(tmp_path)

    assert receipt["status"] == "FAIL"
    assert {item["category"] for item in receipt["findings"]} == {"SYMLINK_FORBIDDEN"}
