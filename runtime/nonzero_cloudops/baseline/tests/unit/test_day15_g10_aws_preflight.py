from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from botocore.config import Config
from scripts.day15.g10_aws_preflight import (
    BEDROCK_READ_TIMEOUT_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    EXPECTED_REGION,
    MAX_SYNTHETIC_TOKENS,
    READ_OPERATION_ALLOWLIST,
    READ_TIMEOUT_SECONDS,
    TOTAL_MAX_ATTEMPTS,
    ContractValidationError,
    PrivateObservationReceipt,
    observe_aws_preflight,
)
from scripts.day15.g10_candidate import COMPONENT_KEYS, derive_candidate_digest

from aioa_cloudops_agent.config import NOVA_2_LITE_MIN_TEMPERATURE

_ACCOUNT = "1" * 12
_OTHER_ACCOUNT = "2" * 12
_ROLE = f"arn:aws:iam::{_ACCOUNT}:role/AIOANonZeroCloudOpsDay15DeploymentRole"
_SECRET = (
    f"arn:aws:secretsmanager:eu-central-1:{_ACCOUNT}:"
    "secret:aioa-nonzero-cloudops-day15-JudgeTokenSecret-*"
)
_INSTANCE = "i-" + "a" * 17
_OWNER = "private-owner" + "@example.invalid"
_BUCKET = "aioa-day15-private-fixture"
_ARTIFACT_OBJECT = f"arn:aws:s3:::{_BUCKET}/day15/reviewed/aioa-lambda.zip"
_PREFIX = "day15/reviewed/"
_NOVA_PROFILE = "eu.amazon.nova-2-lite-v1:0"
_PROVIDER_OUTPUT = "provider-output-must-not-be-retained"
_OBSERVATION_TIME = datetime(2026, 8, 24, 12, 30, tzinfo=UTC)


@dataclass(slots=True)
class FakeClient:
    responses: dict[str, list[object]]
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def invoke(**kwargs: object) -> object:
            self.calls.append((name, copy.deepcopy(kwargs)))
            queue = self.responses.get(name)
            if not queue:
                raise AssertionError(f"unexpected fake operation: {name}")
            value = queue.pop(0)
            if isinstance(value, BaseException):
                raise value
            return copy.deepcopy(value)

        return invoke


@dataclass(slots=True)
class FakeSession:
    clients: dict[str, FakeClient]
    profile_name: str | None = "aioa-day15-deployer"
    constructions: list[tuple[str, str, Config]] = field(default_factory=list)

    def client(
        self,
        service_name: str,
        *,
        region_name: str,
        config: Config,
    ) -> FakeClient:
        self.constructions.append((service_name, region_name, config))
        return self.clients[service_name]


def _private_contract(*, synthetic_converse: bool = True) -> dict[str, object]:
    candidate = _candidate()
    return {
        "bootstrap": {
            "create_judge_secret": False,
            "create_packaging_bucket": False,
        },
        "budget_notification": {
            "budget_name": "aioa-day15-budget",
            "owner_binding": _OWNER,
            "owner_type": "EMAIL",
            "thresholds_usd": [10, 25, 40],
        },
        "candidate_digest": candidate["candidate_digest"],
        "cloudwatch": {
            "metric_name": "CPUUtilization",
            "minimum_datapoints": 6,
            "namespace": "AWS/EC2",
            "observation_window_minutes": 60,
            "period_seconds": 300,
        },
        "deployment_role_arn": _ROLE,
        "expected_account_id": _ACCOUNT,
        "judge_secret": {"creation_policy": "STACK_OWNED", "secret_name": None},
        "nova": {
            "allow_bounded_inference_probe": synthetic_converse,
            "inference_profile_id": _NOVA_PROFILE,
            "region": EXPECTED_REGION,
        },
        "operator_selection_timestamp": "2026-08-24T12:00:00Z",
        "packaging": {
            "artifact_path": "day15/reviewed/aioa-lambda.zip",
            "bucket_name": _BUCKET,
        },
        "region": EXPECTED_REGION,
        "sandbox": {
            "expected_state": "running",
            "instance_id": _INSTANCE,
            "require_ebs_backed": True,
            "tag_key": "AIOACloudOpsSandbox",
            "tag_value": "true",
        },
        "schema_version": 1,
        "selected_profile": "aioa-day15-deployer",
        "selection_source": "PRIVATE_CONTRACT",
        "stack_name": "aioa-nonzero-cloudops-day15",
    }


def _candidate() -> dict[str, object]:
    components = {name: hashlib.sha256(name.encode()).hexdigest() for name in COMPONENT_KEYS}
    source_commit = "c" * 40
    digest = derive_candidate_digest(
        source_commit=source_commit,
        region=EXPECTED_REGION,
        components=components,
    )
    return {
        "candidate_digest": digest,
        "components": {name: components[name] for name in sorted(components)},
        "region": EXPECTED_REGION,
        "schema_version": 1,
        "source_commit": source_commit,
    }


def _notification(threshold: int) -> dict[str, object]:
    return {
        "ComparisonOperator": "GREATER_THAN",
        "NotificationType": "ACTUAL",
        "Threshold": Decimal(threshold),
        "ThresholdType": "ABSOLUTE_VALUE",
    }


def _tls_policy() -> str:
    return json.dumps(
        {
            "Statement": [
                {
                    "Action": "s3:*",
                    "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                    "Effect": "Deny",
                    "Principal": "*",
                    "Resource": [
                        f"arn:aws:s3:::{_BUCKET}",
                        f"arn:aws:s3:::{_BUCKET}/*",
                    ],
                }
            ],
            "Version": "2012-10-17",
        },
        sort_keys=True,
    )


def _response_queues(contract: Mapping[str, object]) -> dict[str, dict[str, list[object]]]:
    budget = contract["budget_notification"]
    assert isinstance(budget, Mapping)
    notifications = [_notification(threshold) for threshold in (10, 25, 40)]
    return {
        "bedrock": {
            "get_inference_profile": [
                {
                    "inferenceProfileArn": "arn:aws:bedrock:eu-central-1:fixture:profile/nova",
                    "inferenceProfileId": _NOVA_PROFILE,
                    "models": [
                        {
                            "modelArn": (
                                f"arn:aws:bedrock:{region}::foundation-model/"
                                "amazon.nova-2-lite-v1:0"
                            )
                        }
                        for region in (
                            "eu-central-1",
                            "eu-north-1",
                            "eu-south-1",
                            "eu-south-2",
                            "eu-west-1",
                            "eu-west-3",
                        )
                    ],
                    "status": "ACTIVE",
                    "type": "SYSTEM_DEFINED",
                }
            ]
        },
        "bedrock-runtime": {
            "converse": [
                {
                    "output": {
                        "message": {
                            "content": [{"text": _PROVIDER_OUTPUT}],
                            "role": "assistant",
                        }
                    },
                    "stopReason": "end_turn",
                    "usage": {"inputTokens": 4, "outputTokens": 1},
                }
            ]
        },
        "budgets": {
            "describe_budget": [
                {
                    "Budget": {
                        "BudgetLimit": {"Amount": Decimal(40), "Unit": "USD"},
                        "BudgetName": budget["budget_name"],
                        "BudgetType": "COST",
                    }
                }
            ],
            "describe_notifications_for_budget": [{"Notifications": notifications}],
            "describe_subscribers_for_notification": [
                {
                    "Subscribers": [
                        {
                            "Address": budget["owner_binding"],
                            "SubscriptionType": budget["owner_type"],
                        }
                    ]
                }
                for _ in notifications
            ],
        },
        "cloudwatch": {
            "get_metric_statistics": [
                {
                    "Datapoints": [
                        {
                            "Average": Decimal(str(value)),
                            "Timestamp": _OBSERVATION_TIME - timedelta(minutes=index * 5),
                            "Unit": "Percent",
                        }
                        for index, value in enumerate((1, 2, 3, 4, 5, 6), start=1)
                    ],
                    "Label": "CPUUtilization",
                }
            ]
        },
        "ec2": {
            "describe_instances": [
                {
                    "Reservations": [
                        {
                            "Instances": [
                                {
                                    "BlockDeviceMappings": [
                                        {
                                            "DeviceName": "/dev/xvda",
                                            "Ebs": {"VolumeId": "vol-" + "e" * 17},
                                        }
                                    ],
                                    "InstanceId": _INSTANCE,
                                    "Placement": {"AvailabilityZone": "eu-central-1a"},
                                    "RootDeviceType": "ebs",
                                    "State": {"Name": "running"},
                                    "Tags": [
                                        {
                                            "Key": "AIOACloudOpsSandbox",
                                            "Value": "true",
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        },
        "iam": {
            "simulate_principal_policy": [
                {
                    "EvaluationResults": [
                        {
                            "EvalActionName": "secretsmanager:CreateSecret",
                            "EvalDecision": "allowed",
                            "EvalResourceName": _SECRET,
                        },
                        {
                            "EvalActionName": "secretsmanager:GetSecretValue",
                            "EvalDecision": "allowed",
                            "EvalResourceName": _SECRET,
                        },
                    ],
                    "IsTruncated": False,
                },
                {
                    "EvaluationResults": [
                        {
                            "EvalActionName": "s3:GetObject",
                            "EvalDecision": "allowed",
                            "EvalResourceName": _ARTIFACT_OBJECT,
                        },
                        {
                            "EvalActionName": "s3:PutObject",
                            "EvalDecision": "allowed",
                            "EvalResourceName": _ARTIFACT_OBJECT,
                        },
                    ],
                    "IsTruncated": False,
                },
            ]
        },
        "s3": {
            "get_bucket_encryption": [
                {
                    "ServerSideEncryptionConfiguration": {
                        "Rules": [
                            {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                        ]
                    }
                }
            ],
            "get_bucket_lifecycle_configuration": [
                {
                    "Rules": [
                        {
                            "Expiration": {"Days": 3},
                            "Filter": {"Prefix": _PREFIX},
                            "ID": "day15-short-life",
                            "NoncurrentVersionExpiration": {"NoncurrentDays": 3},
                            "Status": "Enabled",
                        }
                    ]
                }
            ],
            "get_bucket_location": [{"LocationConstraint": EXPECTED_REGION}],
            "get_bucket_ownership_controls": [
                {"OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}}
            ],
            "get_bucket_policy": [{"Policy": _tls_policy()}],
            "get_bucket_versioning": [{"Status": "Enabled"}],
            "get_public_access_block": [
                {
                    "PublicAccessBlockConfiguration": {
                        "BlockPublicAcls": True,
                        "BlockPublicPolicy": True,
                        "IgnorePublicAcls": True,
                        "RestrictPublicBuckets": True,
                    }
                }
            ],
        },
        "sts": {
            "get_caller_identity": [
                {
                    "Account": _ACCOUNT,
                    "Arn": (
                        f"arn:aws:sts::{_ACCOUNT}:assumed-role/"
                        "AIOANonZeroCloudOpsDay15DeploymentRole/fixture-session"
                    ),
                    "UserId": "fixture-user",
                }
            ]
        },
    }


def _session(
    contract: Mapping[str, object],
) -> tuple[FakeSession, dict[str, dict[str, list[object]]]]:
    queues = _response_queues(contract)
    session = FakeSession(
        clients={service: FakeClient(responses) for service, responses in queues.items()}
    )
    return session, queues


def _observe(
    contract: dict[str, object],
    session: FakeSession,
):
    candidate = _candidate()
    return observe_aws_preflight(
        session=session,
        private_contract=contract,
        candidate_descriptor=candidate,
        candidate_digest=str(candidate["candidate_digest"]),
        clock=lambda: _OBSERVATION_TIME,
    )


def _operations(receipt: PrivateObservationReceipt) -> tuple[str, ...]:
    return tuple(str(item["operation"]) for item in receipt.call_ledger)


def test_happy_path_has_exact_read_ledger_zero_writes_and_redacted_repr() -> None:
    contract = _private_contract()
    session, _ = _session(contract)

    receipt = _observe(contract, session)

    assert receipt.status == "PASS"
    assert receipt.reasons == ()
    assert receipt.write_operations == ()
    private = receipt.private_mapping()
    assert private["external_prerequisites_pass"] is True
    assert all(private["checks"].values())
    assert private["observed_at"].endswith("Z")
    assert len(private["receipt_nonce"]) == 32
    expected_operations = (
        "sts:GetCallerIdentity",
        "s3:GetBucketLocation",
        "s3:GetBucketEncryption",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketOwnershipControls",
        "s3:GetBucketVersioning",
        "s3:GetBucketLifecycleConfiguration",
        "s3:GetBucketPolicy",
        "iam:SimulatePrincipalPolicy",
        "iam:SimulatePrincipalPolicy",
        "ec2:DescribeInstances",
        "cloudwatch:GetMetricStatistics",
        "bedrock:GetInferenceProfile",
        "bedrock-runtime:Converse",
        "budgets:DescribeBudget",
        "budgets:DescribeNotificationsForBudget",
        "budgets:DescribeSubscribersForNotification",
        "budgets:DescribeSubscribersForNotification",
        "budgets:DescribeSubscribersForNotification",
    )
    assert _operations(receipt) == expected_operations
    assert set(expected_operations) <= READ_OPERATION_ALLOWLIST
    assert all(item["write"] is False for item in receipt.call_ledger)
    assert all(
        not any(verb in operation for verb in (":Put", ":Create", ":Delete", ":Update"))
        for operation in expected_operations
    )

    assert private["identifiers"]["expected_account_id"] == _ACCOUNT
    assert private["write_operations"] == []
    nova_probe = private["observations"]["nova_synthetic_converse"]
    assert nova_probe["called"] is True
    assert nova_probe["outcome_class"] == "SUCCESS"
    assert isinstance(nova_probe["latency_ms"], int)
    assert nova_probe["latency_ms"] >= 0
    assert nova_probe["response_persisted"] is False
    assert nova_probe["response_received"] is True
    private_text = json.dumps(private, sort_keys=True)
    assert _PROVIDER_OUTPUT not in private_text
    rendered = repr(receipt)
    assert "REDACTED" in rendered
    assert _ACCOUNT not in rendered
    assert _INSTANCE not in rendered
    assert _OWNER not in rendered

    ec2_calls = session.clients["ec2"].calls
    assert ec2_calls == [("describe_instances", {"InstanceIds": [_INSTANCE]})]
    assert all("Filters" not in parameters for _, parameters in ec2_calls)


def test_identity_mismatch_stops_before_any_resource_observation() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    session.clients["sts"].responses["get_caller_identity"][0] = {
        "Account": _OTHER_ACCOUNT,
        "Arn": _ROLE,
        "UserId": "wrong-account",
    }

    receipt = _observe(contract, session)

    assert receipt.status == "BLOCKED"
    assert "CALLER_ACCOUNT_MISMATCH" in receipt.reasons
    assert _operations(receipt) == ("sts:GetCallerIdentity",)
    assert [service for service, _, _ in session.constructions] == ["sts"]


@pytest.mark.parametrize(
    ("mutate", "digest_mutation", "reason"),
    (
        (
            lambda contract: contract.__setitem__("region", "us-east-1"),
            False,
            "REGION_MUST_BE_EU_CENTRAL_1",
        ),
        (lambda contract: None, True, "CANDIDATE_DIGEST_MISMATCH"),
    ),
)
def test_region_and_candidate_binding_fail_before_client_creation(
    mutate: Any,
    digest_mutation: bool,
    reason: str,
) -> None:
    contract = _private_contract()
    mutate(contract)
    session, _ = _session(_private_contract())
    candidate = _candidate()
    digest = "f" * 64 if digest_mutation else str(candidate["candidate_digest"])

    with pytest.raises(ContractValidationError) as error:
        observe_aws_preflight(
            session=session,
            private_contract=contract,
            candidate_descriptor=candidate,
            candidate_digest=digest,
        )

    assert error.value.reason == reason
    assert session.constructions == []


def test_describe_instances_rejects_a_response_for_any_other_target() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    response = session.clients["ec2"].responses["describe_instances"][0]
    assert isinstance(response, dict)
    response["Reservations"][0]["Instances"][0]["InstanceId"] = "i-" + "b" * 17

    receipt = _observe(contract, session)

    assert "SANDBOX_EXPLICIT_TARGET_MISMATCH" in receipt.reasons
    assert session.clients["ec2"].calls == [("describe_instances", {"InstanceIds": [_INSTANCE]})]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (
            lambda instance: instance.__setitem__("State", {"Name": "stopped"}),
            "SANDBOX_NOT_RUNNING",
        ),
        (
            lambda instance: instance.__setitem__(
                "Tags", [{"Key": "AIOACloudOpsSandbox", "Value": "false"}]
            ),
            "SANDBOX_TAG_MISMATCH",
        ),
        (
            lambda instance: (
                instance.__setitem__("RootDeviceType", "instance-store"),
                instance.__setitem__("BlockDeviceMappings", []),
            ),
            "SANDBOX_EBS_REQUIRED",
        ),
    ),
)
def test_sandbox_must_be_running_ebs_and_exactly_tagged(
    mutation: Any,
    reason: str,
) -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    response = session.clients["ec2"].responses["describe_instances"][0]
    instance = response["Reservations"][0]["Instances"][0]
    mutation(instance)

    receipt = _observe(contract, session)

    assert receipt.status == "BLOCKED"
    assert reason in receipt.reasons


@pytest.mark.parametrize("datapoints", ([], [{"Average": "not-numeric"}]))
def test_cloudwatch_requires_the_contract_minimum_numeric_datapoints(
    datapoints: list[object],
) -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    session.clients["cloudwatch"].responses["get_metric_statistics"][0] = {
        "Datapoints": datapoints,
        "Label": "CPUUtilization",
    }

    receipt = _observe(contract, session)

    assert "CLOUDWATCH_NUMERIC_DATAPOINTS_INSUFFICIENT" in receipt.reasons
    assert session.clients["cloudwatch"].calls[0][1] == {
        "Dimensions": [{"Name": "InstanceId", "Value": _INSTANCE}],
        "EndTime": session.clients["cloudwatch"].calls[0][1]["EndTime"],
        "MetricName": "CPUUtilization",
        "Namespace": "AWS/EC2",
        "Period": 300,
        "StartTime": session.clients["cloudwatch"].calls[0][1]["StartTime"],
        "Statistics": ["Average"],
        "Unit": "Percent",
    }


def test_nova_failure_never_falls_through_to_converse() -> None:
    contract = _private_contract(synthetic_converse=True)
    session, _ = _session(contract)
    session.clients["bedrock"].responses["get_inference_profile"][0] = RuntimeError(
        "private-provider-diagnostic"
    )

    receipt = _observe(contract, session)

    assert "AWS_CALL_FAILED:BEDROCK_GETINFERENCEPROFILE" in receipt.reasons
    assert _operations(receipt).count("bedrock:GetInferenceProfile") == 1
    assert "bedrock-runtime:Converse" not in _operations(receipt)
    assert session.clients["bedrock-runtime"].calls == []
    assert "private-provider-diagnostic" not in repr(receipt)
    assert "private-provider-diagnostic" not in json.dumps(receipt.private_mapping())


def test_nova_requires_every_exact_routed_model_and_skips_paid_probe_after_blocker() -> None:
    contract = _private_contract(synthetic_converse=True)
    session, _ = _session(contract)
    profile = session.clients["bedrock"].responses["get_inference_profile"][0]
    profile["models"].pop()

    receipt = _observe(contract, session)

    assert receipt.status == "BLOCKED"
    assert "NOVA_PROFILE_UNAVAILABLE" in receipt.reasons
    assert session.clients["bedrock-runtime"].calls == []

    contract = _private_contract(synthetic_converse=True)
    session, _ = _session(contract)
    public_block = session.clients["s3"].responses["get_public_access_block"][0]
    public_block["PublicAccessBlockConfiguration"]["BlockPublicPolicy"] = False

    receipt = _observe(contract, session)

    assert "S3_PUBLIC_ACCESS_BLOCK_INVALID" in receipt.reasons
    assert "NOVA_INVOCATION_PROBE_SKIPPED_DUE_TO_PRIOR_BLOCKER" in receipt.reasons
    assert session.clients["bedrock-runtime"].calls == []


def test_synthetic_converse_is_optional_bounded_and_called_at_most_once() -> None:
    disabled_contract = _private_contract(synthetic_converse=False)
    disabled_session, _ = _session(disabled_contract)

    disabled = _observe(disabled_contract, disabled_session)

    assert disabled.status == "BLOCKED"
    assert "NOVA_INVOCATION_ACCESS_UNPROVEN" in disabled.reasons
    assert "bedrock-runtime:Converse" not in _operations(disabled)
    assert disabled_session.clients["bedrock-runtime"].calls == []

    enabled_contract = _private_contract(synthetic_converse=True)
    enabled_session, _ = _session(enabled_contract)
    enabled = _observe(enabled_contract, enabled_session)
    converse_calls = enabled_session.clients["bedrock-runtime"].calls

    assert enabled.status == "PASS"
    assert len(converse_calls) == 1
    parameters = converse_calls[0][1]
    assert parameters["inferenceConfig"]["maxTokens"] == MAX_SYNTHETIC_TOKENS
    assert parameters["inferenceConfig"]["maxTokens"] <= 32
    assert parameters["inferenceConfig"]["temperature"] == NOVA_2_LITE_MIN_TEMPERATURE
    assert parameters["inferenceConfig"]["temperature"] > 0


def test_session_profile_mismatch_fails_before_client_creation() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    session.profile_name = "different-explicit-profile"

    with pytest.raises(ContractValidationError) as error:
        _observe(contract, session)

    assert error.value.reason == "SESSION_PROFILE_MISMATCH"
    assert session.constructions == []


def test_synthetic_token_budget_above_32_fails_before_client_creation() -> None:
    contract = _private_contract()
    nova = contract["nova"]
    assert isinstance(nova, dict)
    nova["max_tokens"] = 33
    session, _ = _session(_private_contract())

    with pytest.raises(ContractValidationError) as error:
        _observe(contract, session)

    assert error.value.reason == "NOVA_CONTRACT_INVALID"
    assert session.constructions == []


def test_budget_requires_explicit_owner_for_each_exact_threshold() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    subscriber_queues = session.clients["budgets"].responses[
        "describe_subscribers_for_notification"
    ]
    subscriber_queues[1] = {
        "Subscribers": [
            {
                "Address": "different-owner" + "@example.invalid",
                "SubscriptionType": "EMAIL",
            }
        ]
    }

    receipt = _observe(contract, session)

    assert "BUDGET_NOTIFICATION_OWNER_MISSING" in receipt.reasons
    subscriber_calls = [
        parameters
        for method, parameters in session.clients["budgets"].calls
        if method == "describe_subscribers_for_notification"
    ]
    assert len(subscriber_calls) == 3
    assert [call["Notification"]["Threshold"] for call in subscriber_calls] == [
        Decimal(10),
        Decimal(25),
        Decimal(40),
    ]


def test_budget_threshold_drift_stops_before_subscriber_queries() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    session.clients["budgets"].responses["describe_notifications_for_budget"][0] = {
        "Notifications": [_notification(value) for value in (10, 25, 41)]
    }

    receipt = _observe(contract, session)

    assert "BUDGET_THRESHOLDS_INVALID" in receipt.reasons
    assert not any(
        method == "describe_subscribers_for_notification"
        for method, _ in session.clients["budgets"].calls
    )


def test_s3_controls_and_secret_simulation_fail_closed() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    public_block = session.clients["s3"].responses["get_public_access_block"][0]
    public_block["PublicAccessBlockConfiguration"]["BlockPublicPolicy"] = False
    session.clients["s3"].responses["get_bucket_policy"][0] = {
        "Policy": json.dumps({"Statement": []})
    }
    simulation = session.clients["iam"].responses["simulate_principal_policy"][0]
    simulation["EvaluationResults"][1]["EvalDecision"] = "implicitDeny"

    receipt = _observe(contract, session)

    assert {
        "JUDGE_SECRET_CAPABILITY_NOT_ALLOWED",
        "S3_PUBLIC_ACCESS_BLOCK_INVALID",
        "S3_TLS_POLICY_INVALID",
    } <= set(receipt.reasons)
    assert session.clients["iam"].calls == [
        (
            "simulate_principal_policy",
            {
                "ActionNames": [
                    "secretsmanager:CreateSecret",
                    "secretsmanager:GetSecretValue",
                ],
                "PolicySourceArn": _ROLE,
                "ResourceArns": [_SECRET],
            },
        ),
        (
            "simulate_principal_policy",
            {
                "ActionNames": ["s3:GetObject", "s3:PutObject"],
                "PolicySourceArn": _ROLE,
                "ResourceArns": [_ARTIFACT_OBJECT],
            },
        ),
    ]


def test_every_client_is_region_pinned_endpoint_hardened_and_single_attempt() -> None:
    contract = _private_contract()
    session, _ = _session(contract)

    receipt = _observe(contract, session)

    assert receipt.status == "PASS"
    expected_services = {
        "bedrock",
        "bedrock-runtime",
        "budgets",
        "cloudwatch",
        "ec2",
        "iam",
        "s3",
        "sts",
    }
    assert {service for service, _, _ in session.constructions} == expected_services
    assert len(session.constructions) == len(expected_services)
    for service, region_name, config in session.constructions:
        assert region_name == EXPECTED_REGION
        assert config.region_name == EXPECTED_REGION
        assert config.connect_timeout == CONNECT_TIMEOUT_SECONDS
        assert config.read_timeout == (
            BEDROCK_READ_TIMEOUT_SECONDS
            if service in {"bedrock", "bedrock-runtime"}
            else READ_TIMEOUT_SECONDS
        )
        assert config.ignore_configured_endpoint_urls is True
        assert config.retries == {
            "mode": "standard",
            "total_max_attempts": TOTAL_MAX_ATTEMPTS,
        }
        assert config.retries["total_max_attempts"] == 1


def test_allowlist_contains_only_the_pdf_read_calls() -> None:
    assert {
        "bedrock-runtime:Converse",
        "bedrock:GetInferenceProfile",
        "budgets:DescribeBudget",
        "budgets:DescribeNotificationsForBudget",
        "budgets:DescribeSubscribersForNotification",
        "cloudwatch:GetMetricStatistics",
        "ec2:DescribeInstances",
        "iam:SimulatePrincipalPolicy",
        "s3:GetBucketEncryption",
        "s3:GetBucketLifecycleConfiguration",
        "s3:GetBucketLocation",
        "s3:GetBucketOwnershipControls",
        "s3:GetBucketPolicy",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketVersioning",
        "sts:GetCallerIdentity",
    } == READ_OPERATION_ALLOWLIST


def test_every_s3_observation_binds_the_expected_bucket_owner() -> None:
    contract = _private_contract()
    session, _ = _session(contract)

    assert _observe(contract, session).status == "PASS"
    assert len(session.clients["s3"].calls) == 7
    assert all(
        parameters == {"Bucket": _BUCKET, "ExpectedBucketOwner": _ACCOUNT}
        for _, parameters in session.clients["s3"].calls
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda response: response["EvaluationResults"][0].__setitem__(
            "EvalResourceName", "arn:aws:secretsmanager:eu-central-1:" + _ACCOUNT + ":secret:other"
        ),
        lambda response: response["EvaluationResults"][0].pop("EvalResourceName"),
        lambda response: response["EvaluationResults"][1].__setitem__(
            "EvalActionName", "secretsmanager:CreateSecret"
        ),
        lambda response: response.__setitem__("IsTruncated", True),
        lambda response: response.pop("IsTruncated"),
    ),
)
def test_secret_capability_is_exactly_action_and_resource_bound(mutate: Any) -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    simulation = session.clients["iam"].responses["simulate_principal_policy"][0]
    mutate(simulation)

    receipt = _observe(contract, session)

    assert receipt.status == "BLOCKED"
    assert "JUDGE_SECRET_CAPABILITY_NOT_ALLOWED" in receipt.reasons


def test_packaging_path_requires_exact_get_and_put_capability() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    simulation = session.clients["iam"].responses["simulate_principal_policy"][1]
    simulation["EvaluationResults"][1]["EvalDecision"] = "implicitDeny"

    receipt = _observe(contract, session)

    assert receipt.status == "BLOCKED"
    assert "ARTIFACT_PATH_CAPABILITY_NOT_ALLOWED" in receipt.reasons
    assert receipt.private_mapping()["checks"]["packaging_bucket_ready"] is False


def test_packaging_path_simulation_must_explicitly_be_not_truncated() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    simulation = session.clients["iam"].responses["simulate_principal_policy"][1]
    simulation.pop("IsTruncated")

    receipt = _observe(contract, session)

    assert receipt.status == "BLOCKED"
    assert "ARTIFACT_PATH_CAPABILITY_NOT_ALLOWED" in receipt.reasons


def test_versioned_artifact_lifecycle_expires_noncurrent_versions() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    lifecycle = session.clients["s3"].responses["get_bucket_lifecycle_configuration"][0]
    lifecycle["Rules"][0].pop("NoncurrentVersionExpiration")

    receipt = _observe(contract, session)

    assert receipt.status == "BLOCKED"
    assert "S3_LIFECYCLE_INVALID" in receipt.reasons


@pytest.mark.parametrize(
    "bucket_name",
    (
        "192.168.1.1",
        "xn--reserved-name",
        "sthree-reserved-name",
        "amzn-s3-demo-reserved",
        "reserved-s3alias",
        "reserved--ol-s3",
        "reserved.mrap",
        "reserved--x-s3",
        "reserved--table-s3",
    ),
)
def test_invalid_or_reserved_bucket_names_fail_before_client_creation(bucket_name: str) -> None:
    contract = _private_contract()
    contract["packaging"]["bucket_name"] = bucket_name
    session, _ = _session(_private_contract())

    with pytest.raises(ContractValidationError, match="BUCKET_INVALID"):
        _observe(contract, session)
    assert session.constructions == []


@pytest.mark.parametrize(
    "budget_name",
    ("x" * 101, "invalid:name", "invalid\\name", "prefix/action/name", "<script>x</script>"),
)
def test_sdk_invalid_budget_names_fail_before_client_creation(budget_name: str) -> None:
    contract = _private_contract()
    contract["budget_notification"]["budget_name"] = budget_name
    session, _ = _session(_private_contract())

    with pytest.raises(ContractValidationError, match="BUDGET_CONTRACT_INVALID"):
        _observe(contract, session)
    assert session.constructions == []


def test_budget_notifications_must_be_actual_and_match_name_and_owner_type() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    notifications = session.clients["budgets"].responses["describe_notifications_for_budget"][0][
        "Notifications"
    ]
    for notification in notifications:
        notification["NotificationType"] = "FORECASTED"
    assert "BUDGET_THRESHOLDS_INVALID" in _observe(contract, session).reasons

    contract = _private_contract()
    session, _ = _session(contract)
    session.clients["budgets"].responses["describe_budget"][0]["Budget"]["BudgetName"] = "other"
    assert "BUDGET_CONFIGURATION_INVALID" in _observe(contract, session).reasons

    contract = _private_contract()
    session, _ = _session(contract)
    subscribers = session.clients["budgets"].responses["describe_subscribers_for_notification"][0][
        "Subscribers"
    ]
    subscribers[0]["SubscriptionType"] = "SNS"
    assert "BUDGET_NOTIFICATION_OWNER_MISSING" in _observe(contract, session).reasons


def test_valid_same_account_sns_owner_is_supported() -> None:
    contract = _private_contract()
    contract["budget_notification"].update(
        {
            "owner_binding": f"arn:aws:sns:eu-central-1:{_ACCOUNT}:day15-budget-owner",
            "owner_type": "SNS",
        }
    )
    session, _ = _session(contract)

    assert _observe(contract, session).status == "PASS"


@pytest.mark.parametrize(
    "owner",
    (
        "arn:aws:sns:us-east-1:" + _ACCOUNT + ":wrong-region",
        "arn:aws:sns:eu-central-1:" + _OTHER_ACCOUNT + ":wrong-account",
    ),
)
def test_sns_owner_must_match_region_and_account(owner: str) -> None:
    contract = _private_contract()
    contract["budget_notification"].update({"owner_binding": owner, "owner_type": "SNS"})
    session, _ = _session(_private_contract())

    with pytest.raises(ContractValidationError, match="BUDGET_CONTRACT_INVALID"):
        _observe(contract, session)
    assert session.constructions == []


def test_same_account_wrong_role_stops_after_sts() -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    session.clients["sts"].responses["get_caller_identity"][0]["Arn"] = (
        f"arn:aws:sts::{_ACCOUNT}:assumed-role/AnotherRole/fixture-session"
    )

    receipt = _observe(contract, session)

    assert "CALLER_ROLE_MISMATCH" in receipt.reasons
    assert _operations(receipt) == ("sts:GetCallerIdentity",)


@pytest.mark.parametrize("minutes", (-2, 61))
def test_operator_selection_timestamp_has_bounded_freshness(minutes: int) -> None:
    contract = _private_contract()
    contract["operator_selection_timestamp"] = (
        (_OBSERVATION_TIME - timedelta(minutes=minutes))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    session, _ = _session(_private_contract())

    with pytest.raises(ContractValidationError, match="PRIVATE_CONTRACT_TIMESTAMP_STALE"):
        _observe(contract, session)
    assert session.constructions == []


@pytest.mark.parametrize("drift", ("missing_timestamp", "outside_window", "wrong_unit"))
def test_cloudwatch_counts_only_unique_valid_points_in_the_exact_window(drift: str) -> None:
    contract = _private_contract()
    session, _ = _session(contract)
    datapoints = session.clients["cloudwatch"].responses["get_metric_statistics"][0]["Datapoints"]
    if drift == "missing_timestamp":
        datapoints[0].pop("Timestamp")
    elif drift == "outside_window":
        datapoints[0]["Timestamp"] = _OBSERVATION_TIME - timedelta(hours=2)
    else:
        datapoints[0]["Unit"] = "Bytes"

    receipt = _observe(contract, session)

    assert "CLOUDWATCH_NUMERIC_DATAPOINTS_INSUFFICIENT" in receipt.reasons


def test_real_observer_receipt_is_accepted_by_closure_binding() -> None:
    from scripts.day15 import run_g10_closure as closure

    contract = _private_contract()
    session, _ = _session(contract)
    observed = _observe(contract, session)
    candidate = _candidate()

    public = closure.sanitized_receipt(
        candidate,
        contract,
        observed,
        selection_source="PRIVATE_CONTRACT",
    )

    assert public["status"] == "PASS"
    assert public["ready_for_change_set"] is True
