import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError
from strands.types.exceptions import StorageError

from aioa_cloudops_agent.config import SandboxRemediationSettings
from aioa_cloudops_agent.deployment import (
    JUDGE_MAX_ELAPSED_SECONDS,
    JUDGE_MAX_TOKENS,
    JUDGE_MAX_TURNS,
    JUDGE_TOKEN_MAX_LIFETIME_SECONDS,
    DynamoDbJudgeQuotaRepository,
    DynamoDbSnapshotStorage,
    DynamoDbStatusObservationLimiter,
    InMemoryJudgeQuotaRepository,
    InMemoryStatusObservationLimiter,
    JudgeInvestigationRequest,
    JudgeQuotaPolicy,
    JudgeRuntimeSettings,
    JudgeTokenAuthorizer,
    ReadOnlyRunStatusService,
    SecretsManagerJudgeTokenProvider,
    StatusPollingPolicy,
    new_judge_budget,
)
from aioa_cloudops_agent.domain import ContractValidationError
from aioa_cloudops_agent.nz import BudgetCounters, Run, WorkflowState
from aioa_cloudops_agent.nz.errors import StorageDependencyError

NOW = datetime(2026, 8, 24, 14, 0, tzinfo=UTC)
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PLACEHOLDER_TOKEN = "unit-test-placeholder-xxxxxxxxxxxxxxxx"


def _secret_value(
    token: str,
    *,
    not_after: datetime = NOW + timedelta(hours=1),
) -> str:
    return json.dumps(
        {"not_after": not_after.isoformat(), "token": token},
        sort_keys=True,
        separators=(",", ":"),
    )


class FakeSecretClient:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[dict[str, object]] = []

    def get_secret_value(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"SecretString": self.value}


def _token_provider(client: FakeSecretClient, *, now: datetime = NOW):
    return SecretsManagerJudgeTokenProvider(
        client,
        secret_id="arn:aws:secretsmanager:eu-central-1:account:secret:judge",
        not_after=NOW + timedelta(hours=1),
        clock=lambda: now,
    )


def _run(state: WorkflowState = WorkflowState.RECEIVED) -> Run:
    return Run(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key=f"judge:{RUN_ID}",
        state=state,
        created_at=NOW,
        updated_at=NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=8192, max_elapsed_seconds=60),
        version=1,
    )


def test_server_owned_judge_budget_is_exact_and_fresh() -> None:
    first = new_judge_budget()
    second = new_judge_budget()

    assert first == BudgetCounters(
        max_turns=JUDGE_MAX_TURNS,
        max_tokens=JUDGE_MAX_TOKENS,
        max_elapsed_seconds=JUDGE_MAX_ELAPSED_SECONDS,
    )
    assert (first.max_turns, first.max_tokens, first.max_elapsed_seconds) == (8, 8192, 60)
    assert first is not second


@pytest.mark.parametrize(
    "extra",
    (
        {"max_turns": 9},
        {"max_tokens": 999_999},
        {"max_elapsed_seconds": 600},
        {"instance_id": "i-0123456789abcdef0"},
        {"approval": True},
    ),
)
def test_judge_schema_rejects_caller_authority_and_budget_fields(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        JudgeInvestigationRequest.model_validate(
            {"intent": "investigate_idle_sandbox", **extra}
        )


def test_runtime_settings_load_one_canonical_target_and_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    account_id = "1" * 12
    environment = {
        "APP_STAGE": "hackathon",
        "AWS_REGION": "eu-central-1",
        "BEDROCK_MODEL_ID": "eu.amazon.nova-2-lite-v1:0",
        "BEDROCK_REGION": "eu-central-1",
        "MODEL_MAX_OUTPUT_TOKENS": "1024",
        "STATE_TABLE_NAME": "aioa-state",
        "SANDBOX_INSTANCE_ID": "i-0123456789abcdef0",
        "SANDBOX_REGION": "eu-central-1",
        "SANDBOX_TAG_KEY": "AIOACloudOpsSandbox",
        "SANDBOX_TAG_VALUE": "true",
        "PRIVATE_REMEDIATION_FUNCTION_NAME": (
            f"arn:aws:lambda:eu-central-1:{account_id}:function:private-executor:live"
        ),
        "JUDGE_TOKEN_SECRET_ARN": (
            f"arn:aws:secretsmanager:eu-central-1:{account_id}:secret:judge"
        ),
        "JUDGE_TOKEN_NOT_AFTER": "2026-08-24T16:00:00Z",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    settings = JudgeRuntimeSettings.from_environment(clock=lambda: NOW)

    assert settings.target.instance_id == "i-0123456789abcdef0"
    assert settings.target.region == settings.bedrock.region == "eu-central-1"
    assert settings.target.required_tag_key == "AIOACloudOpsSandbox"
    assert settings.target.required_tag_value == "true"
    assert settings.private_executor_alias_arn.endswith(":live")
    assert SandboxRemediationSettings.from_environment().target == settings.target


@pytest.mark.parametrize(
    ("alias_template", "secret_template"),
    (
        (
            "arn:aws:lambda:us-east-1:{account}:function:private-executor:live",
            "arn:aws:secretsmanager:eu-central-1:{account}:secret:judge",
        ),
        (
            "arn:aws:lambda:eu-central-1:{account}:function:private-executor:$LATEST",
            "arn:aws:secretsmanager:eu-central-1:{account}:secret:judge",
        ),
        (
            "arn:aws:lambda:eu-central-1:{account}:function:private-executor:live",
            "arn:aws:secretsmanager:eu-central-1:{other}:secret:judge",
        ),
    ),
)
def test_runtime_settings_reject_cross_region_unqualified_or_cross_account_arns(
    alias_template: str,
    secret_template: str,
) -> None:
    account_id = "1" * 12
    with pytest.raises(ContractValidationError):
        JudgeRuntimeSettings(
            stage="hackathon",
            state_table=SimpleNamespace(table_name="aioa-state"),
            target=SimpleNamespace(region="eu-central-1"),
            bedrock=SimpleNamespace(region="eu-central-1"),
            idle_policy=SimpleNamespace(),
            private_executor_alias_arn=alias_template.format(account=account_id),
            judge_token_secret_arn=secret_template.format(
                account=account_id,
                other="2" * 12,
            ),
            judge_token_not_after=NOW + timedelta(hours=1),
        )


def test_runtime_settings_reject_lambda_region_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    with pytest.raises(Exception, match="AWS_REGION must be eu-central-1"):
        JudgeRuntimeSettings.from_environment()


def test_runtime_settings_reject_far_future_token_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = "1" * 12
    environment = {
        "APP_STAGE": "hackathon",
        "AWS_REGION": "eu-central-1",
        "BEDROCK_MODEL_ID": "eu.amazon.nova-2-lite-v1:0",
        "BEDROCK_REGION": "eu-central-1",
        "MODEL_MAX_OUTPUT_TOKENS": "1024",
        "STATE_TABLE_NAME": "aioa-state",
        "SANDBOX_INSTANCE_ID": "i-0123456789abcdef0",
        "SANDBOX_REGION": "eu-central-1",
        "SANDBOX_TAG_KEY": "AIOACloudOpsSandbox",
        "SANDBOX_TAG_VALUE": "true",
        "PRIVATE_REMEDIATION_FUNCTION_NAME": (
            f"arn:aws:lambda:eu-central-1:{account_id}:function:private-executor:live"
        ),
        "JUDGE_TOKEN_SECRET_ARN": (
            f"arn:aws:secretsmanager:eu-central-1:{account_id}:secret:judge"
        ),
        "JUDGE_TOKEN_NOT_AFTER": (
            NOW + timedelta(seconds=JUDGE_TOKEN_MAX_LIFETIME_SECONDS + 1)
        ).isoformat(),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ContractValidationError, match="maximum lifetime"):
        JudgeRuntimeSettings.from_environment(clock=lambda: NOW)


def test_authorizer_requires_header_only_exact_bearer_and_never_echoes_token() -> None:
    client = FakeSecretClient(_secret_value(PLACEHOLDER_TOKEN))
    authorizer = JudgeTokenAuthorizer(_token_provider(client))

    assert authorizer.authorize({"Authorization": f"Bearer {PLACEHOLDER_TOKEN}"}) is not None
    assert authorizer.authorize({"Authorization": "Bearer wrong-placeholder-value"}) is None
    assert authorizer.authorize({"X-Judge-Token": PLACEHOLDER_TOKEN}) is None
    assert authorizer.authorize({"Authorization": f"Bearer {PLACEHOLDER_TOKEN} "}) is None
    assert all(PLACEHOLDER_TOKEN not in repr(call) for call in client.calls)


def test_expired_or_malformed_secret_fails_closed_with_redacted_error() -> None:
    expired = _token_provider(
        FakeSecretClient(_secret_value(PLACEHOLDER_TOKEN)),
        now=NOW + timedelta(hours=2),
    )
    malformed = _token_provider(FakeSecretClient(_secret_value("short")))
    expiry_mismatch = _token_provider(
        FakeSecretClient(
            _secret_value(
                PLACEHOLDER_TOKEN,
                not_after=NOW + timedelta(hours=2),
            )
        )
    )

    for provider in (expired, malformed, expiry_mismatch):
        with pytest.raises(RuntimeError) as captured:
            provider.get_token()
        assert str(captured.value) == "judge credential is unavailable"
        assert PLACEHOLDER_TOKEN not in str(captured.value)


def test_token_provider_uses_bounded_warm_cache_and_short_candidates_do_not_fetch() -> None:
    client = FakeSecretClient(_secret_value(PLACEHOLDER_TOKEN))
    clock_value = [NOW]
    provider = SecretsManagerJudgeTokenProvider(
        client,
        secret_id="arn:aws:secretsmanager:eu-central-1:account:secret:judge",
        not_after=NOW + timedelta(hours=1),
        clock=lambda: clock_value[0],
        cache_ttl_seconds=60,
    )
    authorizer = JudgeTokenAuthorizer(provider)

    assert authorizer.authorize({"Authorization": "Bearer too-short"}) is None
    assert client.calls == []
    assert authorizer.authorize({"Authorization": f"Bearer {PLACEHOLDER_TOKEN}"})
    assert authorizer.authorize({"Authorization": f"Bearer {PLACEHOLDER_TOKEN}"})
    assert len(client.calls) == 1

    clock_value[0] += timedelta(seconds=61)
    assert authorizer.authorize({"Authorization": f"Bearer {PLACEHOLDER_TOKEN}"})
    assert len(client.calls) == 2


def test_in_memory_quota_atomically_enforces_request_token_and_cost_caps() -> None:
    policy = JudgeQuotaPolicy(
        max_requests_per_day=2,
        max_reserved_tokens_per_day=16_384,
        max_reserved_cost_microusd_per_day=100_000,
        tokens_per_request=8_192,
        cost_microusd_per_request=50_000,
    )
    repository = InMemoryJudgeQuotaRepository(policy=policy, clock=lambda: NOW)

    assert repository.reserve() is not None
    second = repository.reserve()
    assert second is not None
    assert (second.requests, second.reserved_tokens, second.reserved_cost_microusd) == (
        2,
        16_384,
        100_000,
    )
    assert repository.reserve() is None


def test_dynamodb_quota_uses_one_conditional_update_for_all_caps() -> None:
    calls: list[dict[str, object]] = []

    def update_item(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "Attributes": {
                "requests": {"N": "1"},
                "reserved_tokens": {"N": "8192"},
                "reserved_cost_microusd": {"N": "50000"},
            }
        }

    repository = DynamoDbJudgeQuotaRepository(
        SimpleNamespace(update_item=update_item),
        "aioa-state",
        clock=lambda: NOW,
    )

    reservation = repository.reserve()

    assert reservation is not None and reservation.requests == 1
    assert len(calls) == 1
    call = calls[0]
    assert call["ReturnValues"] == "ALL_NEW"
    assert "#requests" in call["ConditionExpression"]
    assert "#tokens" in call["ConditionExpression"]
    assert "#cost" in call["ConditionExpression"]


def test_dynamodb_quota_distinguishes_cap_denial_from_dependency_failure() -> None:
    class ConditionalError(Exception):
        def __init__(self) -> None:
            self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}

    denied = DynamoDbJudgeQuotaRepository(
        SimpleNamespace(update_item=lambda **_: (_ for _ in ()).throw(ConditionalError())),
        "aioa-state",
        clock=lambda: NOW,
    )
    unavailable = DynamoDbJudgeQuotaRepository(
        SimpleNamespace(update_item=lambda **_: (_ for _ in ()).throw(RuntimeError())),
        "aioa-state",
        clock=lambda: NOW,
    )

    assert denied.reserve() is None
    with pytest.raises(StorageDependencyError):
        unavailable.reserve()


def test_dynamodb_snapshot_storage_round_trips_bytes_without_scan_or_delete() -> None:
    items: dict[tuple[str, str], dict[str, object]] = {}

    def put_item(**kwargs: object) -> dict[str, object]:
        item = kwargs["Item"]
        assert isinstance(item, dict)
        items[(item["PK"]["S"], item["SK"]["S"])] = item
        return {}

    def get_item(**kwargs: object) -> dict[str, object]:
        key = kwargs["Key"]
        assert isinstance(key, dict)
        return {"Item": items.get((key["PK"]["S"], key["SK"]["S"]))}

    storage = DynamoDbSnapshotStorage(
        SimpleNamespace(put_item=put_item, get_item=get_item),
        "aioa-state",
    )

    asyncio.run(storage.write("session/run/snapshot_latest.json", b"opaque"))
    assert asyncio.run(storage.read("session/run/snapshot_latest.json")) == b"opaque"
    with pytest.raises(StorageError, match="deletion is not authorized"):
        asyncio.run(storage.delete("session/run/snapshot_latest.json"))
    with pytest.raises(StorageError, match="listing is not authorized"):
        asyncio.run(storage.list("session/"))


def test_status_is_one_read_redacted_and_never_replays_execution() -> None:
    class Repository:
        def __init__(self) -> None:
            self.calls: list[UUID] = []

        def get_run(self, run_id: UUID) -> Run:
            self.calls.append(run_id)
            return _run(WorkflowState.VERIFYING)

    repository = Repository()
    service = ReadOnlyRunStatusService(
        repository,
        observation_limiter=InMemoryStatusObservationLimiter(),
        clock=lambda: NOW,
    )

    status = service.get(RUN_ID)

    assert status is not None
    assert status.outcome_class == "read_only_reconciliation_pending"
    assert status.next_poll_after_seconds == 15
    assert repository.calls == [RUN_ID]
    assert set(status.model_dump()) == {
        "run_id",
        "state",
        "terminal",
        "outcome_class",
        "next_poll_after_seconds",
    }


@pytest.mark.parametrize(
    "state",
    (WorkflowState.REMEDIATION_PROPOSED, WorkflowState.AWAITING_APPROVAL),
)
def test_public_status_closes_proposal_without_exposing_resume(state: WorkflowState) -> None:
    repository = SimpleNamespace(get_run=lambda _: _run(state))

    status = ReadOnlyRunStatusService(
        repository,
        observation_limiter=InMemoryStatusObservationLimiter(),
        clock=lambda: NOW,
    ).get(RUN_ID)

    assert status is not None
    assert status.terminal is True
    assert status.outcome_class == "proposal_ready_no_execution"
    assert status.next_poll_after_seconds is None


def test_reconciliation_status_times_out_as_non_success_without_replay() -> None:
    repository = SimpleNamespace(get_run=lambda _: _run(WorkflowState.RECOVERY_REQUIRED))
    service = ReadOnlyRunStatusService(
        repository,
        observation_limiter=InMemoryStatusObservationLimiter(),
        clock=lambda: NOW + timedelta(seconds=300),
    )

    status = service.get(RUN_ID)

    assert status is not None
    assert status.terminal is True
    assert status.outcome_class == "status_window_timeout_non_success"
    assert status.next_poll_after_seconds is None


def test_status_observation_cap_is_server_enforced_for_every_nonterminal_state() -> None:
    repository = SimpleNamespace(get_run=lambda _: _run(WorkflowState.RECEIVED))
    service = ReadOnlyRunStatusService(
        repository,
        observation_limiter=InMemoryStatusObservationLimiter(),
        policy=StatusPollingPolicy(max_observations=2),
        clock=lambda: NOW,
    )

    assert service.get(RUN_ID).terminal is False
    assert service.get(RUN_ID).terminal is False
    capped = service.get(RUN_ID)

    assert capped is not None
    assert capped.terminal is True
    assert capped.outcome_class == "status_observation_cap_non_success"
    assert capped.next_poll_after_seconds is None


def test_dynamodb_status_limiter_uses_one_conditional_per_run_update() -> None:
    calls: list[dict[str, object]] = []
    limiter = DynamoDbStatusObservationLimiter(
        SimpleNamespace(update_item=lambda **kwargs: calls.append(kwargs) or {}),
        "aioa-state",
    )

    assert limiter.reserve(RUN_ID, max_observations=20) is True
    assert len(calls) == 1
    assert calls[0]["Key"] == {
        "PK": {"S": f"JUDGE_STATUS#{RUN_ID}"},
        "SK": {"S": "PUBLIC_OBSERVATIONS"},
    }
    assert calls[0]["ConditionExpression"] == (
        "attribute_not_exists(#observations) OR #observations < :maximum"
    )


def test_status_polling_policy_is_realistic_finite_and_separate_from_run_budget() -> None:
    policy = StatusPollingPolicy()

    assert (policy.interval_seconds, policy.max_observations, policy.max_window_seconds) == (
        15,
        20,
        300,
    )
    assert policy.max_window_seconds > JUDGE_MAX_ELAPSED_SECONDS
