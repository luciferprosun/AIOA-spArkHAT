from __future__ import annotations

import socket
import stat
from pathlib import Path

import pytest
from scripts.phase3.run_jury_demo import _write_private, run_jury_demo

from aioa_cloudops_agent.release.post_deploy_verifier import PostDeployVerifierError


def test_jury_demo_covers_complete_story_comfortably_under_five_minutes(tmp_path: Path) -> None:
    payload = run_jury_demo(tmp_path / "demo")

    assert payload["status"] == "PASS"
    assert payload["mode"] == "MOCK_OFFLINE_NEVER_LIVE"
    assert payload["duration_seconds"] < 300
    assert payload["within_target"] is True
    assert payload["approved"]["final_state"] == "SUCCESS_WITH_EVIDENCE"  # type: ignore[index]
    assert payload["approved"]["mock_mutations"] == 1  # type: ignore[index]
    assert payload["denied"]["final_state"] == "DENIED_BY_HUMAN"  # type: ignore[index]
    assert payload["denied"]["mock_mutations"] == 0  # type: ignore[index]
    assert payload["pending_approval_recovered_after_restart"] is True
    assert payload["replay"]["rejected"] is True  # type: ignore[index]
    assert payload["replay"]["mutation_delta"] == 0  # type: ignore[index]
    assert payload["recovery"]["reconciled"] is True  # type: ignore[index]
    assert payload["recovery"]["mock_mutations_after_restart"] == 0  # type: ignore[index]
    assert len(payload["fail_closed_probes"]) == 5  # type: ignore[arg-type]
    assert payload["external_network_connections"] == payload["aws_mutations"] == 0
    assert payload["provider_network_calls"] == payload["live_receipts"] == 0


def test_jury_demo_opens_no_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("jury demo attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    assert run_jury_demo(tmp_path / "guarded")["status"] == "PASS"


def test_jury_demo_private_output_writer_rejects_symlink(tmp_path: Path) -> None:
    output = tmp_path / "demo.json"
    _write_private(output, "{}\n")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    target = tmp_path / "target"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(PostDeployVerifierError, match="JURY_DEMO_OUTPUT_SYMLINK_FORBIDDEN"):
        _write_private(link, "changed")
    assert target.read_text(encoding="utf-8") == "preserve"
