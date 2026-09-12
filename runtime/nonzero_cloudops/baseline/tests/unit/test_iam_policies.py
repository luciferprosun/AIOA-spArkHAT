import json
import re
from pathlib import Path

IAM_DIRECTORY = Path(__file__).parents[2] / "infra" / "iam"
READ_ONLY_POLICY_PATH = IAM_DIRECTORY / "cloudops-read-only-policy.json"
REMEDIATION_POLICY_PATH = IAM_DIRECTORY / "cloudops-remediation-policy.json"
ORCHESTRATOR_POLICY_PATH = IAM_DIRECTORY / "cloudops-orchestrator-policy.json"


def _policy(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _actions(policy: dict[str, object]) -> list[str]:
    actions: list[str] = []
    for statement in policy["Statement"]:
        value = statement["Action"]
        actions.extend([value] if isinstance(value, str) else value)
    return actions


def test_active_cloudops_policy_allows_only_targeted_read_apis() -> None:
    policy = _policy(READ_ONLY_POLICY_PATH)

    assert _actions(policy) == [
        "ec2:DescribeInstances",
        "cloudwatch:GetMetricStatistics",
    ]
    assert policy["Statement"][0]["Condition"] == {
        "StringEquals": {"aws:RequestedRegion": "eu-central-1"}
    }


def test_private_executor_policy_separates_fresh_read_from_scoped_stop() -> None:
    policy = _policy(REMEDIATION_POLICY_PATH)
    statements = {statement["Sid"]: statement for statement in policy["Statement"]}
    describe = statements["FreshConfiguredSandboxScopeRead"]
    stop = statements["StopConfiguredTaggedSandboxOnly"]

    assert _actions(policy) == [
        "ec2:DescribeInstances",
        "ec2:StopInstances",
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
    ]
    assert describe["Resource"] == "*"
    assert describe["Condition"] == {
        "StringEquals": {"aws:RequestedRegion": "eu-central-1"}
    }
    assert stop["Resource"] == (
        "arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:"
        "instance/${SandboxInstanceId}"
    )
    assert stop["Condition"] == {
        "StringEquals": {
            "aws:RequestedRegion": "eu-central-1",
            "aws:ResourceTag/AIOACloudOpsSandbox": "true",
        }
    }


def test_orchestrator_policy_is_exact_read_model_state_secret_and_alias_authority() -> None:
    policy = _policy(ORCHESTRATOR_POLICY_PATH)
    actions = set(_actions(policy))
    statements = {statement["Sid"]: statement for statement in policy["Statement"]}

    assert actions == {
        "ec2:DescribeInstances",
        "cloudwatch:GetMetricStatistics",
        "bedrock:InvokeModelWithResponseStream",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "lambda:InvokeFunction",
        "secretsmanager:GetSecretValue",
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
    }
    assert statements["InvokePrivateRemediationExecutorAliasOnly"]["Resource"] == (
        "${RemediationExecutorAliasArn}"
    )
    assert statements["DurableItemOnlyState"]["Resource"] == "${StateTableArn}"
    assert statements["ReadDedicatedJudgeSecretOnly"]["Resource"] == (
        "${JudgeTokenSecretArn}"
    )
    profile = statements["InvokeExactNovaTwoLiteEuInferenceProfile"]
    bedrock_resources = statements["InvokeProfileDestinationModelsOnly"]["Resource"]
    assert profile["Resource"] == "${NovaTwoLiteEuInferenceProfileArn}"
    assert profile["Condition"] == {
        "StringEquals": {"aws:RequestedRegion": "eu-central-1"}
    }
    assert len(bedrock_resources) == 6
    assert all(
        resource.endswith("foundation-model/amazon.nova-2-lite-v1:0")
        for resource in bedrock_resources
    )
    assert statements["InvokeProfileDestinationModelsOnly"]["Condition"] == {
        "StringEquals": {
            "aws:RequestedRegion": "eu-central-1",
            "bedrock:InferenceProfileArn": "${NovaTwoLiteEuInferenceProfileArn}",
        }
    }


def test_wildcard_resources_are_only_for_non_resource_scope_reads_and_xray_delivery() -> None:
    policies = [
        _policy(READ_ONLY_POLICY_PATH),
        _policy(REMEDIATION_POLICY_PATH),
        _policy(ORCHESTRATOR_POLICY_PATH),
    ]
    wildcard_statements = {
        statement["Sid"]
        for policy in policies
        for statement in policy["Statement"]
        if statement["Resource"] == "*"
    }

    assert wildcard_statements == {
        "InspectConfiguredSandboxInstance",
        "FreshConfiguredSandboxScopeRead",
        "ReadConfiguredSandboxEvidence",
        "BoundedXRayDelivery",
    }
    assert all("*" not in action for policy in policies for action in _actions(policy))


def test_no_generalized_write_permission_agentcore_or_account_literal_exists() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in IAM_DIRECTORY.glob("*.json")
    )
    actions = [
        action
        for path in IAM_DIRECTORY.glob("*.json")
        for action in _actions(_policy(path))
    ]

    for forbidden in (
        "ec2:TerminateInstances",
        "ec2:StartInstances",
        "ec2:RebootInstances",
        "ec2:ModifyInstanceAttribute",
        "ssm:SendCommand",
        "dynamodb:DeleteItem",
        "dynamodb:Scan",
        "secretsmanager:PutSecretValue",
    ):
        assert forbidden not in actions
    assert re.search(r"(?<!\d)\d{12}(?!\d)", combined) is None
    assert "agentcore" not in combined.casefold()
