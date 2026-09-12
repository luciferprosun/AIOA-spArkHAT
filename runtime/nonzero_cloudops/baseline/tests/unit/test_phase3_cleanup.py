from __future__ import annotations

import json
import socket
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts.phase3 import build_cleanup_contract as builder
from scripts.phase3.plan_cleanup import _write_private

from aioa_cloudops_agent.release.cleanup import (
    CleanupAction,
    CleanupApproval,
    CleanupError,
    CleanupObservationFixture,
    CleanupPlan,
    CleanupPlanStatus,
    DeploymentPartialState,
    RollbackCleanupContract,
    authorize_cleanup_plan,
    cleanup_contract_sha256,
    load_cleanup_contract,
    load_cleanup_observations,
    plan_cleanup,
    render_cleanup_contract_markdown,
    render_cleanup_contract_schema,
    render_cleanup_plan_schema,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _contract() -> RollbackCleanupContract:
    return load_cleanup_contract(builder.DEFAULT_CLEANUP_CONTRACT)


def _observations() -> CleanupObservationFixture:
    return load_cleanup_observations(builder.DEFAULT_FIXTURE)


def _approval(plan: CleanupPlan, **changes: object) -> CleanupApproval:
    values: dict[str, object] = {
        "schema_version": 1,
        "decision": "APPROVED",
        "deployment_id": plan.binding.deployment_id,
        "plan_sha256": plan.plan_sha256,
        "destructive_action_ids": plan.destructive_action_ids,
        "operator_subject_sha256": "c" * 64,
        "approval_nonce_sha256": "d" * 64,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
    }
    values.update(changes)
    return CleanupApproval(**values)  # type: ignore[arg-type]


def _changed_observations(change) -> CleanupObservationFixture:
    value = _observations().model_dump(mode="json")
    change(value)
    return CleanupObservationFixture.model_validate_json(json.dumps(value))


def test_cleanup_contract_covers_all_resources_partial_states_and_safe_defaults() -> None:
    contract = _contract()

    assert len(contract.rules) == 22
    assert contract.partial_states == tuple(DeploymentPartialState)
    assert contract.execution_default_enabled is False
    assert contract.cli_emits_cloud_commands is False
    assert contract.network_connections == contract.aws_mutations == contract.live_receipts == 0
    assert {
        rule.logical_id
        for rule in contract.rules
        if rule.rollback_action is CleanupAction.RETAIN_PENDING_EXPLICIT_DISPOSITION
    } == {"StateTable", "OrchestratorVersion", "RemediationExecutorVersion"}


def test_partial_failure_plan_is_idempotent_ownership_bound_and_plan_only() -> None:
    first = plan_cleanup(
        _contract(),
        _observations(),
        deployment_state=DeploymentPartialState.ROLLBACK_PARTIALLY_FAILED,
    )
    second = plan_cleanup(
        _contract(),
        _observations(),
        deployment_state=DeploymentPartialState.ROLLBACK_PARTIALLY_FAILED,
    )
    items = {item.logical_id: item for item in first.items}

    assert first == second
    assert first.status is CleanupPlanStatus.READY_FOR_OPERATOR_REVIEW
    assert first.destructive_action_ids == ("CLEANUP_STACK_DELETE",)
    assert items["OrchestratorFunction"].action is CleanupAction.RETRY_CLOUDFORMATION_STACK_DELETE
    assert items["OrchestratorRole"].ownership_proven is True
    assert items["StateTable"].action is CleanupAction.RETAIN_PENDING_EXPLICIT_DISPOSITION
    assert items["JudgeTokenSecret"].action is CleanupAction.NO_OBSERVED_RESOURCE
    assert first.cloud_commands_emitted == first.network_connections == first.aws_mutations == 0


@pytest.mark.parametrize("state", tuple(DeploymentPartialState))
def test_every_partial_state_produces_an_explicit_deterministic_plan(
    state: DeploymentPartialState,
) -> None:
    plan = plan_cleanup(_contract(), _observations(), deployment_state=state)

    assert plan.deployment_state is state
    assert plan.requires_explicit_operator_approval is True
    assert plan.plan_sha256 == plan_cleanup(
        _contract(), _observations(), deployment_state=state
    ).plan_sha256


@pytest.mark.parametrize(
    "change",
    (
        lambda value: value["resources"][0].update({"stack_membership_confirmed": False}),
        lambda value: value["resources"][0].update({"stack_id_sha256": "e" * 64}),
        lambda value: value["resources"][0].update(
            {"deployment_id": "p3-deadbeef-dead-beef"}
        ),
        lambda value: value["resources"][0].update(
            {"ownership_tags": {"ManagedBy": "SomeoneElse"}}
        ),
        lambda value: value["resources"][0].update({"resource_type": "AWS::S3::Bucket"}),
    ),
)
def test_name_alone_never_authorizes_foreign_or_ambiguous_resource(change) -> None:
    observations = _changed_observations(change)

    plan = plan_cleanup(
        _contract(),
        observations,
        deployment_state=DeploymentPartialState.DEPLOYMENT_STARTED_THEN_FAILED,
    )

    assert plan.status is CleanupPlanStatus.BLOCKED_OWNERSHIP
    assert plan.destructive_action_ids == ()
    assert any(
        item.action is CleanupAction.DO_NOT_DELETE_OWNERSHIP_UNPROVEN
        for item in plan.items
    )
    with pytest.raises(CleanupError, match="CLEANUP_PLAN_NOT_AUTHORIZABLE"):
        authorize_cleanup_plan(
            plan,
            _approval(
                plan.model_copy(update={"destructive_action_ids": ("CLEANUP_STACK_DELETE",)})
            ),
            now=NOW,
            consumed_nonce_hashes=frozenset(),
        )


def test_unexpected_resource_is_preserved_and_blocks_the_whole_destructive_plan() -> None:
    def add_foreign(value: dict[str, object]) -> None:
        resources = value["resources"]
        assert isinstance(resources, list)
        example = dict(resources[0])
        example["logical_id"] = "UnexpectedForeignDatabase"
        example["resource_type"] = "AWS::RDS::DBInstance"
        resources.append(example)
        resources.sort(key=lambda item: item["logical_id"])

    plan = plan_cleanup(
        _contract(),
        _changed_observations(add_foreign),
        deployment_state=DeploymentPartialState.ROLLBACK_PARTIALLY_FAILED,
    )

    foreign = next(item for item in plan.items if item.logical_id == "UnexpectedForeignDatabase")
    assert plan.status is CleanupPlanStatus.BLOCKED_OWNERSHIP
    assert foreign.action is CleanupAction.DO_NOT_DELETE_OWNERSHIP_UNPROVEN
    assert foreign.destructive is False


def test_fresh_exact_approval_yields_only_a_nonexecuting_authorization_envelope() -> None:
    plan = plan_cleanup(
        _contract(),
        _observations(),
        deployment_state=DeploymentPartialState.ROLLBACK_PARTIALLY_FAILED,
    )
    approval = _approval(plan)

    envelope = authorize_cleanup_plan(
        plan,
        approval,
        now=NOW + timedelta(minutes=1),
        consumed_nonce_hashes=frozenset(),
    )

    assert envelope.status == "AUTHORIZED_BUT_NOT_EXECUTED"
    assert envelope.execution_default_enabled is False
    assert envelope.cloud_commands_emitted == envelope.network_connections == 0
    assert envelope.aws_mutations == envelope.live_receipts == 0


def test_cleanup_approval_replay_staleness_and_binding_mismatch_fail_closed() -> None:
    plan = plan_cleanup(
        _contract(),
        _observations(),
        deployment_state=DeploymentPartialState.RETRY,
    )
    approval = _approval(plan)

    with pytest.raises(CleanupError, match="CLEANUP_APPROVAL_REPLAYED"):
        authorize_cleanup_plan(
            plan,
            approval,
            now=NOW + timedelta(minutes=1),
            consumed_nonce_hashes=frozenset({approval.approval_nonce_sha256}),
        )
    with pytest.raises(CleanupError, match="CLEANUP_APPROVAL_STALE"):
        authorize_cleanup_plan(
            plan,
            approval,
            now=approval.expires_at,
            consumed_nonce_hashes=frozenset(),
        )
    with pytest.raises(CleanupError, match="CLEANUP_APPROVAL_DEPLOYMENT_MISMATCH"):
        authorize_cleanup_plan(
            plan,
            _approval(plan, deployment_id="p3-deadbeef-dead-beef"),
            now=NOW + timedelta(minutes=1),
            consumed_nonce_hashes=frozenset(),
        )
    with pytest.raises(CleanupError, match="CLEANUP_APPROVAL_PLAN_MISMATCH"):
        authorize_cleanup_plan(
            plan,
            _approval(plan, plan_sha256="f" * 64),
            now=NOW + timedelta(minutes=1),
            consumed_nonce_hashes=frozenset(),
        )


def test_cleanup_approval_contract_rejects_long_lifetime_and_unknown_fields() -> None:
    plan = plan_cleanup(
        _contract(),
        _observations(),
        deployment_state=DeploymentPartialState.RETRY,
    )
    with pytest.raises(ValidationError):
        _approval(plan, expires_at=NOW + timedelta(minutes=16))

    value = plan.model_dump(mode="json")
    value["execute_now"] = True
    with pytest.raises(ValidationError):
        CleanupPlan.model_validate_json(json.dumps(value))


def test_contract_and_observation_loaders_reject_duplicate_or_extra_fields(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(CleanupError, match="CLEANUP_CONTRACT_INVALID"):
        load_cleanup_contract(duplicate)

    value = _observations().model_dump(mode="json")
    value["unsafe"] = True
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(CleanupError, match="CLEANUP_OBSERVATIONS_INVALID"):
        load_cleanup_observations(extra)


def test_schemas_docs_and_generated_files_are_deterministic() -> None:
    contract = _contract()

    assert render_cleanup_contract_schema() == builder.DEFAULT_CONTRACT_SCHEMA.read_text(
        encoding="utf-8"
    )
    assert render_cleanup_plan_schema() == builder.DEFAULT_PLAN_SCHEMA.read_text(encoding="utf-8")
    assert render_cleanup_contract_markdown(contract) == builder.DEFAULT_DOCUMENT.read_text(
        encoding="utf-8"
    )
    assert cleanup_contract_sha256(contract) in builder.DEFAULT_DOCUMENT.read_text(encoding="utf-8")
    assert builder.build(check=True)["status"] == "PASS"


def test_private_plan_writer_is_owner_only_and_rejects_symlink(tmp_path: Path) -> None:
    output = tmp_path / "cleanup-plan.json"
    _write_private(output, "{}\n")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    target = tmp_path / "target"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(CleanupError, match="CLEANUP_OUTPUT_SYMLINK_FORBIDDEN"):
        _write_private(link, "changed")
    assert target.read_text(encoding="utf-8") == "preserve"


def test_cleanup_planning_and_authorization_open_no_network_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("cleanup tooling attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    plan = plan_cleanup(
        _contract(),
        _observations(),
        deployment_state=DeploymentPartialState.RETRY,
    )
    envelope = authorize_cleanup_plan(
        plan,
        _approval(plan),
        now=NOW + timedelta(seconds=1),
        consumed_nonce_hashes=frozenset(),
    )
    assert envelope.network_connections == envelope.aws_mutations == 0
