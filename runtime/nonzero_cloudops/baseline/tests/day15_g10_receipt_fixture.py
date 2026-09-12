from __future__ import annotations

import json
from collections.abc import Mapping

from scripts.day15.g10_aws_preflight import (
    EXPECTED_NOVA_MODEL_REGIONS,
    PASS_OPERATION_SEQUENCE,
    PRIVATE_CHECK_KEYS,
    READ_OPERATION_ALLOWLIST,
    PrivateObservationReceipt,
)

ACCOUNT = "1" * 12
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/AIOANonZeroCloudOpsDay15DeploymentRole"
BUCKET = "private-day15-artifacts"
INSTANCE = "i-" + "a" * 17
OWNER = "private-owner" + "@example.invalid"
OBSERVED_AT = "2026-08-24T12:01:00Z"


def valid_private_contract(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        "bootstrap": {"create_judge_secret": False, "create_packaging_bucket": False},
        "budget_notification": {
            "budget_name": "aioa-day15-budget",
            "owner_binding": OWNER,
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
        "deployment_role_arn": ROLE_ARN,
        "expected_account_id": ACCOUNT,
        "judge_secret": {"creation_policy": "STACK_OWNED", "secret_name": None},
        "nova": {
            "allow_bounded_inference_probe": True,
            "inference_profile_id": "eu.amazon.nova-2-lite-v1:0",
            "region": "eu-central-1",
        },
        "operator_selection_timestamp": "2026-08-24T12:00:00Z",
        "packaging": {
            "artifact_path": "day15/reviewed/aioa-lambda.zip",
            "bucket_name": BUCKET,
        },
        "region": "eu-central-1",
        "sandbox": {
            "expected_state": "running",
            "instance_id": INSTANCE,
            "require_ebs_backed": True,
            "tag_key": "AIOACloudOpsSandbox",
            "tag_value": "true",
        },
        "schema_version": 1,
        "selected_profile": "aioa-day15-deployer",
        "selection_source": "PRIVATE_CONTRACT",
        "stack_name": "aioa-nonzero-cloudops-day15",
    }


def _tls_policy(bucket: str) -> str:
    return json.dumps(
        {
            "Statement": [
                {
                    "Action": "s3:*",
                    "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                    "Effect": "Deny",
                    "Principal": "*",
                    "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
                }
            ],
            "Version": "2012-10-17",
        },
        sort_keys=True,
    )


def valid_private_receipt(
    candidate: Mapping[str, object],
    contract: Mapping[str, object] | None = None,
) -> PrivateObservationReceipt:
    selected = dict(contract or valid_private_contract(candidate))
    account = str(selected["expected_account_id"])
    role = str(selected["deployment_role_arn"])
    packaging = selected["packaging"]
    budget = selected["budget_notification"]
    sandbox = selected["sandbox"]
    nova = selected["nova"]
    assert isinstance(packaging, Mapping)
    assert isinstance(budget, Mapping)
    assert isinstance(sandbox, Mapping)
    assert isinstance(nova, Mapping)
    bucket = str(packaging["bucket_name"])
    stack = str(selected["stack_name"])
    private = {
        "call_ledger": [
            {"operation": operation, "sequence": sequence, "write": False}
            for sequence, operation in enumerate(PASS_OPERATION_SEQUENCE, start=1)
        ],
        "candidate": {
            "descriptor": dict(candidate),
            "sha256": candidate["candidate_digest"],
        },
        "checks": {name: True for name in PRIVATE_CHECK_KEYS},
        "external_prerequisites_pass": True,
        "identifiers": {
            "artifact_bucket": bucket,
            "budget_name": budget["budget_name"],
            "budget_owner": budget["owner_binding"],
            "deployment_profile": selected["selected_profile"],
            "deployment_role_arn": role,
            "expected_account_id": account,
            "judge_secret_arn": (
                f"arn:aws:secretsmanager:eu-central-1:{account}:secret:{stack}-JudgeTokenSecret-*"
            ),
            "nova_inference_profile_id": nova["inference_profile_id"],
            "sandbox_instance_id": sandbox["instance_id"],
        },
        "observations": {
            "artifact_bucket": {
                "encryption": {
                    "ServerSideEncryptionConfiguration": {
                        "Rules": [
                            {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                        ]
                    }
                },
                "lifecycle": {
                    "Rules": [
                        {
                            "Expiration": {"Days": 3},
                            "Filter": {"Prefix": "day15/reviewed/"},
                            "NoncurrentVersionExpiration": {"NoncurrentDays": 3},
                            "Status": "Enabled",
                        }
                    ]
                },
                "location": {"LocationConstraint": "eu-central-1"},
                "ownership": {
                    "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
                },
                "policy": {"Policy": _tls_policy(bucket)},
                "public_access_block": {
                    "PublicAccessBlockConfiguration": {
                        "BlockPublicAcls": True,
                        "BlockPublicPolicy": True,
                        "IgnorePublicAcls": True,
                        "RestrictPublicBuckets": True,
                    }
                },
                "versioning": {"Status": "Enabled"},
            },
            "artifact_path_capability": {
                "actions_exact": True,
                "allowed_for_exact_resource": True,
                "not_truncated": True,
            },
            "budget": {
                "budget": {"configuration_valid": True},
                "notifications": {"thresholds_exact": True},
                "subscribers": [{"owner_present": True}] * 3,
            },
            "caller_identity": {
                "Account": account,
                "Arn": (
                    f"arn:aws:sts::{account}:assumed-role/"
                    "AIOANonZeroCloudOpsDay15DeploymentRole/fixture-session"
                ),
                "UserId": "fixture-user",
            },
            "cloudwatch": {
                "minimum_numeric_datapoints": 6,
                "numeric_datapoints": 6,
                "window_seconds": 3600,
            },
            "nova_profile": {
                "active": True,
                "exact_profile": True,
                "routed_model_count": len(EXPECTED_NOVA_MODEL_REGIONS),
                "routed_models_exact": True,
            },
            "nova_synthetic_converse": {
                "called": True,
                "latency_ms": 1,
                "outcome_class": "SUCCESS",
                "response_persisted": False,
                "response_received": True,
            },
            "sandbox": {
                "ebs_backed": True,
                "explicit_target_match": True,
                "region_match": True,
                "running": True,
                "tag_match": True,
            },
            "secret_capability": {
                "actions_exact": True,
                "allowed_for_exact_resource": True,
                "not_truncated": True,
            },
        },
        "observed_at": OBSERVED_AT,
        "private_contract": selected,
        "read_operation_allowlist": sorted(READ_OPERATION_ALLOWLIST),
        "receipt_nonce": "a" * 32,
        "reasons": [],
        "region": "eu-central-1",
        "schema_version": 1,
        "status": "PASS",
        "write_operations": [],
    }
    return PrivateObservationReceipt(private)
