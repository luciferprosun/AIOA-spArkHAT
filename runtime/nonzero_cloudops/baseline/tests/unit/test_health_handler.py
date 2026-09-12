import ast
import inspect
import json
import re

import pytest

from aioa_cloudops_agent.domain import ContractValidationError
from aioa_cloudops_agent.handlers import health


def _invoke_health() -> tuple[dict[str, object], dict[str, object]]:
    response = health.lambda_handler({}, None)
    body = json.loads(response["body"])
    return response, body


def test_health_invocation_returns_expected_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_STAGE", raising=False)

    response, body = _invoke_health()

    assert response["statusCode"] == 200
    assert response["headers"] == {"content-type": "application/json"}
    assert body == {
        "service": "aioa-nonzero-cloudops-agent",
        "stage": "hackathon",
        "status": "ok",
    }


def test_health_body_is_valid_minimal_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_STAGE", raising=False)

    response, _body = _invoke_health()

    assert json.dumps(json.loads(response["body"]), sort_keys=True)


def test_health_body_contains_no_account_or_credential_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_STAGE", raising=False)

    _response, body = _invoke_health()
    serialized = json.dumps(body, sort_keys=True)

    assert re.search(r"(?<!\d)\d{12}(?!\d)", serialized) is None
    assert not {
        "account",
        "account_id",
        "access_key",
        "secret_key",
        "session_token",
        "credentials",
    }.intersection(body)


def test_health_handler_has_no_aws_or_network_client_imports() -> None:
    syntax_tree = ast.parse(inspect.getsource(health))
    imported_roots: set[str] = set()
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots.isdisjoint(
        {"boto3", "botocore", "httpx", "requests", "socket", "subprocess", "urllib"}
    )


def test_stage_is_validated_without_exposing_arbitrary_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_STAGE", "invalid stage")

    with pytest.raises(ContractValidationError, match="stage"):
        health.lambda_handler({}, None)
