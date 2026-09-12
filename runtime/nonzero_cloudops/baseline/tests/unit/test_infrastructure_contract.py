import json
import re
from pathlib import Path
from typing import Any

import yaml

TEMPLATE_PATH = Path(__file__).parents[2] / "infra" / "sam" / "template.yaml"


def _template() -> dict[str, Any]:
    return yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _resources() -> dict[str, Any]:
    return _template()["Resources"]


def _role_statements(role_name: str) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    for policy in _resources()[role_name]["Properties"]["Policies"]:
        statements.extend(policy["PolicyDocument"]["Statement"])
    return statements


def _actions(statements: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for statement in statements:
        value = statement["Action"]
        result.update([value] if isinstance(value, str) else value)
    return result


def test_template_is_one_function_url_topology_with_no_parallel_api() -> None:
    template = _template()
    resources = template["Resources"]

    assert template["AWSTemplateFormatVersion"] == "2010-09-09"
    assert template["Transform"] == "AWS::Serverless-2016-10-31"
    assert sum(resource["Type"] == "AWS::Lambda::Url" for resource in resources.values()) == 1
    assert not any(
        resource["Type"] in {"AWS::Serverless::HttpApi", "AWS::ApiGatewayV2::Api"}
        for resource in resources.values()
    )
    assert {
        name
        for name, resource in resources.items()
        if resource["Type"] == "AWS::Serverless::Function"
    } == {"OrchestratorFunction", "RemediationExecutorFunction"}


def test_functions_use_one_reviewed_python_artifact_and_reserved_concurrency_one() -> None:
    resources = _resources()
    handlers = {
        "OrchestratorFunction": "aioa_cloudops_agent.judge.lambda_handler.lambda_handler",
        "RemediationExecutorFunction": (
            "aioa_cloudops_agent.remediation.lambda_handler.lambda_handler"
        ),
    }
    for name, handler in handlers.items():
        properties = resources[name]["Properties"]
        assert properties["CodeUri"] == "../../dist/day15/aioa-lambda.zip"
        assert properties["Handler"] == handler
        assert properties["Runtime"] == "python3.12"
        assert properties["Architectures"] == ["x86_64"]
        assert properties["ReservedConcurrentExecutions"] == 1
        assert properties["Tracing"] == "Active"
        assert "ProvisionedConcurrencyConfig" not in properties


def test_state_table_is_retained_recoverable_encrypted_and_deletion_protected() -> None:
    table = _resources()["StateTable"]
    properties = table["Properties"]

    assert table["DeletionPolicy"] == "Retain"
    assert table["UpdateReplacePolicy"] == "Retain"
    assert properties["BillingMode"] == "PAY_PER_REQUEST"
    assert properties["DeletionProtectionEnabled"] is True
    assert properties["PointInTimeRecoverySpecification"] == {
        "PointInTimeRecoveryEnabled": True
    }
    assert properties["SSESpecification"] == {"SSEEnabled": True}
    assert properties["AttributeDefinitions"] == [
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
    ]
    assert properties["KeySchema"] == [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ]


def test_secret_rotation_is_bound_to_the_same_bounded_runtime_expiry() -> None:
    template = _template()
    secret = template["Resources"]["JudgeTokenSecret"]["Properties"][
        "GenerateSecretString"
    ]
    orchestrator = template["Resources"]["OrchestratorFunction"]["Properties"][
        "Environment"
    ]["Variables"]

    assert secret["SecretStringTemplate"] == {
        "Fn::Sub": '{"not_after":"${JudgeTokenNotAfter}"}'
    }
    assert secret["GenerateStringKey"] == "token"
    assert secret["PasswordLength"] == 64
    assert orchestrator["JUDGE_TOKEN_NOT_AFTER"] == {"Ref": "JudgeTokenNotAfter"}
    assert "JudgeTokenSecret" not in template["Outputs"]


def test_region_is_explicit_and_public_ingress_preserves_all_mutation_vetoes() -> None:
    template = _template()
    parameters = template["Parameters"]
    rule = template["Rules"]["PublicIngressKeepsMutationDisabled"]

    assert parameters["DeploymentRegion"]["AllowedValues"] == ["eu-central-1"]
    assert "Default" not in parameters["DeploymentRegion"]
    assert parameters["PublicIngressEnabled"]["Default"] == "false"
    assert parameters["AwsMutationsEnabled"]["Default"] == "false"
    assert parameters["AllowLiveSandboxStop"]["Default"] == "false"
    assert parameters["EmergencyExecutionDisabled"]["Default"] == "true"
    assert parameters["AwsMutationsEnabled"]["AllowedValues"] == ["false"]
    assert parameters["AllowLiveSandboxStop"]["AllowedValues"] == ["false"]
    assert parameters["EmergencyExecutionDisabled"]["AllowedValues"] == ["true"]
    region_rule = template["Rules"]["DeploymentRegionIsFrozen"]
    assert "AWS::Region" in json.dumps(region_rule)
    serialized = json.dumps(rule, sort_keys=True)
    for name in (
        "AwsMutationsEnabled",
        "AllowLiveSandboxStop",
        "EmergencyExecutionDisabled",
    ):
        assert name in serialized


def test_private_executor_has_fresh_read_plus_separate_exact_scoped_stop() -> None:
    statements = _role_statements("RemediationExecutorRole")
    assert _actions(statements) == {
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "ec2:DescribeInstances",
        "ec2:StopInstances",
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
    }
    describe = next(s for s in statements if s["Action"] == ["ec2:DescribeInstances"])
    stop = next(s for s in statements if s["Action"] == ["ec2:StopInstances"])
    assert describe["Resource"] == "*"
    assert describe["Condition"] == {
        "StringEquals": {"aws:RequestedRegion": "eu-central-1"}
    }
    assert stop["Resource"] == {
        "Fn::Sub": (
            "arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:"
            "instance/${SandboxInstanceId}"
        )
    }
    assert stop["Condition"]["StringEquals"] == {
        "aws:RequestedRegion": "eu-central-1",
        "aws:ResourceTag/AIOACloudOpsSandbox": "true",
    }


def test_orchestrator_iam_has_exact_bedrock_profile_models_and_no_ec2_write() -> None:
    statements = _role_statements("OrchestratorRole")
    actions = _actions(statements)
    expected_models = {
        {
            "Fn::Sub": (
                f"arn:${{AWS::Partition}}:bedrock:{region}::foundation-model/"
                "amazon.nova-2-lite-v1:0"
            )
        }["Fn::Sub"]
        for region in (
            "eu-central-1",
            "eu-north-1",
            "eu-south-1",
            "eu-south-2",
            "eu-west-1",
            "eu-west-3",
        )
    }
    profile = next(
        statement
        for statement in statements
        if statement.get("Sid") == "InvokeExactEuInferenceProfile"
    )
    models = next(
        statement
        for statement in statements
        if statement.get("Sid") == "InvokeProfileDestinationModelsOnly"
    )
    model_resources = {entry["Fn::Sub"] for entry in models["Resource"]}
    profile_arn = (
        "arn:${AWS::Partition}:bedrock:${AWS::Region}:${AWS::AccountId}:"
        "inference-profile/eu.amazon.nova-2-lite-v1:0"
    )

    assert "bedrock:InvokeModel" not in actions
    assert not any(action.startswith("ec2:") and action != "ec2:DescribeInstances" for action in actions)
    assert profile["Resource"] == {"Fn::Sub": profile_arn}
    assert profile["Condition"] == {
        "StringEquals": {"aws:RequestedRegion": "eu-central-1"}
    }
    assert model_resources == expected_models
    assert models["Condition"] == {
        "StringEquals": {
            "aws:RequestedRegion": "eu-central-1",
            "bedrock:InferenceProfileArn": {"Fn::Sub": profile_arn},
        }
    }
    assert "lambda:InvokeFunction" in actions
    invoke = next(s for s in statements if s["Action"] == ["lambda:InvokeFunction"])
    assert invoke["Resource"] == {"Ref": "RemediationExecutorAlias"}


def test_function_url_targets_live_alias_and_has_exact_two_conditioned_permissions() -> None:
    resources = _resources()
    function_url = resources["OrchestratorFunctionUrl"]

    assert function_url["Properties"] == {
        "AuthType": "NONE",
        "InvokeMode": "BUFFERED",
        "TargetFunctionArn": {"Ref": "OrchestratorFunction"},
        "Qualifier": "live",
    }
    permission_names = {
        name
        for name, resource in resources.items()
        if resource["Type"] == "AWS::Lambda::Permission"
    }
    assert permission_names == {
        "PublicFunctionUrlInvokePermission",
        "PublicFunctionInvokeViaUrlPermission",
    }
    first = resources["PublicFunctionUrlInvokePermission"]
    second = resources["PublicFunctionInvokeViaUrlPermission"]
    assert first["Condition"] == second["Condition"] == "PublicIngressEnabledCondition"
    assert first["Properties"] == {
        "FunctionName": {"Ref": "OrchestratorAlias"},
        "Action": "lambda:InvokeFunctionUrl",
        "Principal": "*",
        "FunctionUrlAuthType": "NONE",
    }
    assert second["Properties"] == {
        "FunctionName": {"Ref": "OrchestratorAlias"},
        "Action": "lambda:InvokeFunction",
        "Principal": "*",
        "InvokedViaFunctionUrl": True,
    }


def test_immutable_versions_and_live_aliases_are_retained_for_rollback() -> None:
    template = _template()
    resources = _resources()
    pairs = (
        ("OrchestratorFunction", "OrchestratorVersion", "OrchestratorAlias"),
        (
            "RemediationExecutorFunction",
            "RemediationExecutorVersion",
            "RemediationExecutorAlias",
        ),
    )
    for function, version_name, alias_name in pairs:
        version = resources[version_name]
        alias = resources[alias_name]
        assert version["DeletionPolicy"] == "Retain"
        assert version["UpdateReplacePolicy"] == "Retain"
        assert version["Properties"]["FunctionName"] == {"Ref": function}
        assert version["Properties"]["CodeSha256"] == {
            "Ref": "LambdaArtifactSha256Base64"
        }
        assert alias["Properties"] == {
            "Name": "live",
            "FunctionName": {"Ref": function},
            "FunctionVersion": {"Fn::GetAtt": [version_name, "Version"]},
        }
        description = json.dumps(version["Properties"]["Description"])
        assert "LambdaConfigurationSha256" in description
        if version_name == "OrchestratorVersion":
            assert "JudgeTokenNotAfter" in description

    assert template["Parameters"]["LambdaConfigurationSha256"]["AllowedPattern"] == (
        "^[0-9a-f]{64}$"
    )
    assert "$LATEST" not in json.dumps(
        {name: resources[name] for _, _, name in pairs},
        sort_keys=True,
    )


def test_canonical_target_telemetry_redaction_and_three_day_logs_are_frozen() -> None:
    resources = _resources()
    orchestrator = resources["OrchestratorFunction"]["Properties"]["Environment"][
        "Variables"
    ]
    executor = resources["RemediationExecutorFunction"]["Properties"]["Environment"][
        "Variables"
    ]
    canonical = {
        "SANDBOX_INSTANCE_ID": {"Ref": "SandboxInstanceId"},
        "SANDBOX_REGION": "eu-central-1",
        "SANDBOX_TAG_KEY": "AIOACloudOpsSandbox",
        "SANDBOX_TAG_VALUE": "true",
    }

    assert {name: orchestrator[name] for name in canonical} == canonical
    assert {name: executor[name] for name in canonical} == canonical
    assert "SANDBOX_REQUIRED_TAG_KEY" not in json.dumps(resources)
    assert orchestrator["OTEL_TRACES_SAMPLER"] == "parentbased_traceidratio"
    assert orchestrator["OTEL_TRACES_SAMPLER_ARG"] == "0.05"
    assert orchestrator["OTEL_SEMCONV_STABILITY_OPT_IN"].endswith(
        "gen_ai_unredacted_attributes="
    )
    assert {
        resources[name]["Properties"]["RetentionInDays"]
        for name in ("OrchestratorFunctionLogGroup", "RemediationExecutorLogGroup")
    } == {3}


def test_template_contains_no_forbidden_services_wildcard_actions_or_account_literal() -> None:
    template = _template()
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    serialized = json.dumps(template, sort_keys=True).casefold()
    forbidden_types = {
        "AWS::RDS::DBInstance",
        "AWS::EC2::NatGateway",
        "AWS::ECS::Service",
        "AWS::EKS::Cluster",
        "AWS::OpenSearchService::Domain",
        "AWS::ElastiCache::CacheCluster",
        "AWS::StepFunctions::StateMachine",
        "AWS::SQS::Queue",
    }

    assert not any(resource["Type"] in forbidden_types for resource in template["Resources"].values())
    assert not any("*" in action for action in _actions(_role_statements("OrchestratorRole")))
    assert not any("*" in action for action in _actions(_role_statements("RemediationExecutorRole")))
    assert "agentcore" not in serialized
    assert re.search(r"(?<!\d)\d{12}(?!\d)", text) is None
