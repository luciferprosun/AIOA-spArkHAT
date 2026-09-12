from __future__ import annotations

import hashlib
import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.day15 import run_day15_gate as day15_gate
from scripts.day15 import run_g10_closure as closure
from scripts.day15.g10_aws_preflight import PrivateObservationReceipt
from scripts.day15.g10_candidate import COMPONENT_KEYS, derive_candidate_digest
from scripts.day15.validate_template import canonical_json
from tests.day15_g10_receipt_fixture import valid_private_contract, valid_private_receipt

GATE_NOW = datetime(2026, 8, 24, 12, 2, tzinfo=UTC)


def _candidate() -> dict[str, object]:
    components = {name: hashlib.sha256(name.encode("utf-8")).hexdigest() for name in COMPONENT_KEYS}
    source_commit = "c" * 40
    digest = derive_candidate_digest(
        source_commit=source_commit,
        region=closure.REGION,
        components=components,
    )
    return {
        "candidate_digest": digest,
        "components": {name: components[name] for name in sorted(components)},
        "region": closure.REGION,
        "schema_version": 1,
        "source_commit": source_commit,
    }


def _contract(candidate: dict[str, object]) -> dict[str, object]:
    return valid_private_contract(candidate)


def _write_contract(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _private_receipt(
    candidate: dict[str, object], contract: dict[str, object]
) -> PrivateObservationReceipt:
    return valid_private_receipt(candidate, contract)


def test_no_private_binding_is_blocked_and_performs_no_aws_call(tmp_path: Path) -> None:
    candidate = _candidate()
    called = False

    def forbidden_session(_profile: str):
        nonlocal called
        called = True
        raise AssertionError("session creation is forbidden without operator authority")

    public = tmp_path / "public.json"
    payload = closure.run_closure(
        private_contract_path=tmp_path / "missing-private.json",
        private_receipt_path=tmp_path / "private-receipt.json",
        sanitized_receipt_path=public,
        environment={},
        configured_profiles=("unrelated-local-profile",),
        session_factory=forbidden_session,
        candidate_factory=lambda: candidate,
    )

    assert payload["status"] == "BLOCKED"
    assert payload["reasons"] == ["PRIVATE_DEPLOYMENT_CONTRACT_REQUIRED"]
    assert payload["selection_source"] == "NONE"
    assert payload["aws_calls_performed"] is False
    assert payload["api_operations"] == []
    assert payload["private_receipt_created"] is False
    assert called is False
    assert public.read_bytes() == (canonical_json(payload) + "\n").encode("utf-8")
    closure.validate_sanitized_receipt(payload, expected_candidate=candidate, private_receipt=None)


def test_conflicting_explicit_profiles_are_blocked_without_authentication(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    payload = closure.run_closure(
        private_contract_path=tmp_path / "missing.json",
        private_receipt_path=tmp_path / "private.json",
        sanitized_receipt_path=None,
        environment={"AWS_PROFILE": "first", "AWS_DEFAULT_PROFILE": "second"},
        configured_profiles=("first", "second"),
        session_factory=lambda _profile: pytest.fail("must not build a session"),
        candidate_factory=lambda: candidate,
    )

    assert payload["status"] == "BLOCKED"
    assert payload["multiple_ambiguous_profiles"] is True
    assert payload["selection_source"] == "NONE"
    assert payload["reasons"] == ["MULTIPLE_AMBIGUOUS_PROFILES"]


def test_pass_path_writes_mode_0600_private_receipt_and_sanitizes_every_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    contract = _contract(candidate)
    contract_path = tmp_path / "contract.json"
    private_path = tmp_path / "receipt.json"
    public_path = tmp_path / "public.json"
    _write_contract(contract_path, contract)
    observed = _private_receipt(candidate, contract)
    monkeypatch.setattr(closure, "observe_aws_preflight", lambda **_kwargs: observed)

    class Session:
        profile_name = "aioa-day15-deployer"

    payload = closure.run_closure(
        private_contract_path=contract_path,
        private_receipt_path=private_path,
        sanitized_receipt_path=public_path,
        environment={},
        configured_profiles=(),
        session_factory=lambda _profile: Session(),
        candidate_factory=lambda: candidate,
    )

    assert payload["status"] == "PASS"
    assert payload["external_prerequisites_pass"] is True
    assert payload["ready_for_change_set"] is True
    assert payload["ready_for_deployment"] is False
    assert payload["deployment_authorized"] is False
    assert payload["missing_prerequisites"] == []
    assert stat.S_IMODE(private_path.stat().st_mode) == 0o600
    private = json.loads(private_path.read_text(encoding="utf-8"))
    closure.validate_sanitized_receipt(
        payload,
        expected_candidate=candidate,
        private_receipt=private,
    )
    public_text = public_path.read_text(encoding="utf-8")
    for private_value in (
        contract["expected_account_id"],
        contract["deployment_role_arn"],
        contract["packaging"]["bucket_name"],
        contract["sandbox"]["instance_id"],
        contract["budget_notification"]["owner_binding"],
    ):
        assert str(private_value) not in public_text


def test_sanitized_validator_rejects_stale_private_receipt_and_identifiers() -> None:
    candidate = _candidate()
    contract = _contract(candidate)
    observed = _private_receipt(candidate, contract)
    payload = closure.sanitized_receipt(
        candidate,
        contract,
        observed,
        selection_source="PRIVATE_CONTRACT",
    )
    private = observed.private_mapping()
    private["candidate"]["descriptor"]["source_commit"] = "d" * 40
    with pytest.raises(closure.ClosureFailure, match="PRIVATE_RECEIPT_CANDIDATE_MISMATCH"):
        closure.validate_sanitized_receipt(
            payload,
            expected_candidate=candidate,
            private_receipt=private,
        )

    payload = closure.sanitized_receipt(
        candidate,
        contract,
        observed,
        selection_source="PRIVATE_CONTRACT",
    )
    payload["reasons"] = ["arn:aws:iam::" + "1" * 12 + ":role/private"]
    with pytest.raises(closure.ClosureFailure, match="SENSITIVE_VALUE_FORBIDDEN"):
        closure.validate_sanitized_receipt(
            payload,
            expected_candidate=candidate,
            private_receipt=observed.private_mapping(),
        )


def test_explicit_environment_selection_must_match_private_contract(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    contract = _contract(candidate)
    contract["selection_source"] = "EXPLICIT_AWS_PROFILE"
    path = tmp_path / "contract.json"
    _write_contract(path, contract)

    with pytest.raises(closure.ClosureFailure, match="EXPLICIT_PROFILE_SELECTION_MISMATCH"):
        closure.run_closure(
            private_contract_path=path,
            private_receipt_path=tmp_path / "private.json",
            sanitized_receipt_path=None,
            environment={"AWS_PROFILE": "different"},
            configured_profiles=("different",),
            candidate_factory=lambda: candidate,
        )


def test_day15_g10_accepts_only_candidate_bound_private_and_sanitized_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    contract = _contract(candidate)
    observed = _private_receipt(candidate, contract)
    private = observed.private_mapping()
    public = closure.sanitized_receipt(
        candidate,
        contract,
        observed,
        selection_source="PRIVATE_CONTRACT",
    )
    private_path = tmp_path / "private.json"
    public_path = tmp_path / "public.json"
    private_path.write_text(canonical_json(private) + "\n", encoding="utf-8")
    private_path.chmod(0o600)
    public_path.write_text(canonical_json(public) + "\n", encoding="utf-8")
    monkeypatch.setattr(day15_gate, "build_candidate_descriptor", lambda: candidate)

    assert (
        day15_gate._g10_candidate_receipt_result(
            public_path,
            private_path,
            clock=lambda: GATE_NOW,
        ).status
        == "PASS"
    )

    private["candidate"]["sha256"] = "f" * 64
    private_path.write_text(canonical_json(private) + "\n", encoding="utf-8")
    private_path.chmod(0o600)
    rejected = day15_gate._g10_candidate_receipt_result(
        public_path,
        private_path,
        clock=lambda: GATE_NOW,
    )
    assert rejected.status == "FAIL"
    assert rejected.reasons == ("PRIVATE_RECEIPT_CANDIDATE_MISMATCH",)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    (
        (
            lambda private: private.__setitem__("call_ledger", private["call_ledger"][:1]),
            "PRIVATE_RECEIPT_SCHEMA_INVALID",
        ),
        (
            lambda private: private["call_ledger"][1].__setitem__(
                "operation", "sts:GetCallerIdentity"
            ),
            "PRIVATE_RECEIPT_SCHEMA_INVALID",
        ),
        (
            lambda private: private["observations"]["sandbox"].__setitem__("tag_match", False),
            "PRIVATE_RECEIPT_STATUS_INVALID",
        ),
        (
            lambda private: private["observations"]["nova_synthetic_converse"].__setitem__(
                "raw_provider_response", "forbidden"
            ),
            "PRIVATE_RECEIPT_STATUS_INVALID",
        ),
    ),
)
def test_day15_g10_rejects_forged_or_semantically_edited_pass_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
    reason: str,
) -> None:
    candidate = _candidate()
    contract = _contract(candidate)
    observed = _private_receipt(candidate, contract)
    private = observed.private_mapping()
    public = closure.sanitized_receipt(
        candidate,
        contract,
        observed,
        selection_source="PRIVATE_CONTRACT",
    )
    mutate(private)
    private_path = tmp_path / "private.json"
    public_path = tmp_path / "public.json"
    private_path.write_text(canonical_json(private) + "\n", encoding="utf-8")
    private_path.chmod(0o600)
    public_path.write_text(canonical_json(public) + "\n", encoding="utf-8")
    monkeypatch.setattr(day15_gate, "build_candidate_descriptor", lambda: candidate)

    rejected = day15_gate._g10_candidate_receipt_result(
        public_path,
        private_path,
        clock=lambda: GATE_NOW,
    )

    assert rejected.status == "FAIL"
    assert rejected.reasons == (reason,)


def test_day15_g10_rejects_stale_authenticated_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    contract = _contract(candidate)
    observed = _private_receipt(candidate, contract)
    private = observed.private_mapping()
    public = closure.sanitized_receipt(
        candidate,
        contract,
        observed,
        selection_source="PRIVATE_CONTRACT",
    )
    private_path = tmp_path / "private.json"
    public_path = tmp_path / "public.json"
    private_path.write_text(canonical_json(private) + "\n", encoding="utf-8")
    private_path.chmod(0o600)
    public_path.write_text(canonical_json(public) + "\n", encoding="utf-8")
    monkeypatch.setattr(day15_gate, "build_candidate_descriptor", lambda: candidate)

    rejected = day15_gate._g10_candidate_receipt_result(
        public_path,
        private_path,
        clock=lambda: datetime(2026, 8, 24, 14, 2, tzinfo=UTC),
    )

    assert rejected.status == "FAIL"
    assert rejected.reasons == ("PRIVATE_RECEIPT_STALE",)


def test_output_symlink_is_rejected_before_session_or_aws_observation(tmp_path: Path) -> None:
    candidate = _candidate()
    contract_path = tmp_path / "contract.json"
    _write_contract(contract_path, _contract(candidate))
    public_target = tmp_path / "public-target.json"
    public_target.write_text("untouched", encoding="utf-8")
    public_link = tmp_path / "public-link.json"
    public_link.symlink_to(public_target)
    called = False

    def forbidden_session(_profile: str):
        nonlocal called
        called = True
        raise AssertionError("session construction must not occur")

    with pytest.raises(closure.ClosureFailure, match="SANITIZED_RECEIPT_SYMLINK_FORBIDDEN"):
        closure.run_closure(
            private_contract_path=contract_path,
            private_receipt_path=tmp_path / "private.json",
            sanitized_receipt_path=public_link,
            configured_profiles=(),
            environment={},
            session_factory=forbidden_session,
            candidate_factory=lambda: candidate,
        )

    assert called is False
    assert public_target.read_text(encoding="utf-8") == "untouched"


def test_one_command_refreshes_full_p0_p1_results_without_forwarding_aws_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_environments: list[dict[str, str]] = []

    def gate_payload(prefix: str, count: int) -> dict[str, object]:
        return {
            "gate_count": count,
            "gates": [],
            "gates_fail": 0,
            "gates_pass": count,
            "gates_skipped": 0,
            "matrix_reasons": [],
            "status": "PASS",
        }

    payloads = iter((gate_payload("P0", 15), gate_payload("P1", 6)))

    def fake_run(_command, **kwargs):
        observed_environments.append(kwargs["env"])
        return SimpleNamespace(
            returncode=0,
            stdout=canonical_json(next(payloads)),
            stderr="",
        )

    monkeypatch.setattr(closure.subprocess, "run", fake_run)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "must-not-propagate")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-propagate")
    p0 = tmp_path / "p0.json"
    p1 = tmp_path / "p1.json"

    closure.refresh_full_gate_results(p0_result_path=p0, p1_result_path=p1)

    assert stat.S_IMODE(p0.stat().st_mode) == 0o600
    assert stat.S_IMODE(p1.stat().st_mode) == 0o600
    assert all("AWS_ACCESS_KEY_ID" not in item for item in observed_environments)
    assert all("AWS_SECRET_ACCESS_KEY" not in item for item in observed_environments)
    assert all(item["AWS_EC2_METADATA_DISABLED"] == "true" for item in observed_environments)
