import json
import logging
from types import SimpleNamespace
from uuid import UUID

import pytest

from aioa_cloudops_agent.deployment import JudgeInvestigationRequest
from aioa_cloudops_agent.judge import (
    JudgeFunctionUrlApplication,
    JudgeInvestigationOutcome,
    JudgeOutcomeClass,
    JudgeRequestServices,
)
from aioa_cloudops_agent.judge.logging import StructuredJudgeLogger
from aioa_cloudops_agent.nz import WorkflowState

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
TOKEN = "unit-test-placeholder-token-xxxxxxxxxxxxxxxx"


def _event(
    method: str,
    path: str,
    *,
    body: str | None = None,
    headers: dict[str, object] | None = None,
    query: str = "",
    encoded: bool = False,
) -> dict[str, object]:
    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": query,
        "headers": headers or {},
        "requestContext": {"http": {"method": method}},
        "body": body,
        "isBase64Encoded": encoded,
    }


class Authorizer:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[dict[str, object]] = []

    def authorize(self, headers: object) -> object | None:
        assert isinstance(headers, dict)
        self.calls.append(headers)
        return object() if self.accepted else None


class Quota:
    def __init__(self, reservation: object | None = object()) -> None:
        self.reservation = reservation
        self.calls = 0

    def reserve(self) -> object | None:
        self.calls += 1
        return self.reservation


class Investigation:
    def __init__(self) -> None:
        self.calls: list[JudgeInvestigationRequest] = []

    def investigate(self, request: JudgeInvestigationRequest) -> JudgeInvestigationOutcome:
        self.calls.append(request)
        return JudgeInvestigationOutcome(
            run_id=RUN_ID,
            succeeded=True,
            state=WorkflowState.REMEDIATION_PROPOSED,
            outcome_class=JudgeOutcomeClass.REMEDIATION_PROPOSED,
            proposal_id=PROPOSAL_ID,
            evidence_hash="a" * 64,
        )


class Status:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    def get(self, run_id: UUID) -> object:
        self.calls.append(run_id)
        return {
            "run_id": str(run_id),
            "state": "REMEDIATION_PROPOSED",
            "terminal": True,
            "outcome_class": "proposal_ready_no_execution",
            "next_poll_after_seconds": None,
        }


class Harness:
    def __init__(
        self,
        *,
        authorized: bool = True,
        reservation: object | None = object(),
        ready: bool = True,
    ) -> None:
        self.authorizer = Authorizer(authorized)
        self.investigation_quota = Quota(reservation)
        self.status_quota = Quota(reservation)
        self.investigation = Investigation()
        self.status = Status()
        self.ready = ready
        self.provider_calls = 0
        self.logs: list[str] = []
        self.application = JudgeFunctionUrlApplication(
            self.services,
            logger=StructuredJudgeLogger(self.logs.append),
        )

    def services(self) -> JudgeRequestServices:
        self.provider_calls += 1
        return JudgeRequestServices(
            authorizer=self.authorizer,
            investigation_quota=self.investigation_quota,
            status_quota=self.status_quota,
            investigation=self.investigation,
            status=self.status,
            readiness=lambda: self.ready,
        )


def _json(response: dict[str, object]) -> dict[str, object]:
    body = response["body"]
    assert isinstance(body, str)
    decoded = json.loads(body)
    assert isinstance(decoded, dict)
    return decoded


def test_health_and_root_create_no_clients_and_expose_hardened_same_origin_ui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_STAGE", raising=False)
    harness = Harness()

    health = harness.application.handle(_event("GET", "/health"), object())
    root = harness.application.handle(_event("GET", "/"), object())

    assert health["statusCode"] == root["statusCode"] == 200
    assert harness.provider_calls == 0
    assert _json(health) == {
        "service": "aioa-nonzero-cloudops-agent",
        "stage": "hackathon",
        "status": "ok",
    }
    root_body = root["body"]
    assert isinstance(root_body, str)
    assert "localStorage" not in root_body
    assert "sessionStorage" not in root_body
    assert "Authorization" in root_body
    assert "finally" in root_body
    assert "t.value=''" in root_body
    headers = root["headers"]
    assert isinstance(headers, dict)
    assert "sha256-" in headers["content-security-policy"]
    assert "connect-src 'self'" in headers["content-security-policy"]
    assert "access-control-allow-origin" not in headers
    assert headers["cache-control"] == "no-store"


def test_invalid_health_stage_fails_closed_without_constructing_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_STAGE", "unsafe stage")
    harness = Harness()

    response = harness.application.handle(_event("GET", "/health"), object())

    assert response["statusCode"] == 503
    assert _json(response) == {"error": "NOT_READY", "retryable": False}
    assert harness.provider_calls == 0


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("POST", "/judge/approve"),
        ("POST", "/judge/resume"),
        ("POST", "/judge/mutate"),
        ("DELETE", "/judge/investigate"),
        ("OPTIONS", "/judge/investigate"),
        ("POST", "/unknown"),
    ),
)
def test_unknown_approval_mutation_and_wrong_method_routes_fail_before_services(
    method: str,
    path: str,
) -> None:
    harness = Harness()

    response = harness.application.handle(_event(method, path), object())

    assert response["statusCode"] in {404, 405}
    assert harness.provider_calls == 0
    assert harness.investigation_quota.calls == 0
    assert harness.status_quota.calls == 0
    assert harness.investigation.calls == []


@pytest.mark.parametrize(
    "event",
    (
        _event(
            "POST",
            "/judge/investigate",
            body='{"intent":"investigate_idle_sandbox","max_turns":99}',
            headers={"content-type": "application/json"},
        ),
        _event(
            "POST",
            "/judge/investigate",
            body='{"intent":"investigate_idle_sandbox","intent":"investigate_idle_sandbox"}',
            headers={"content-type": "application/json"},
        ),
        _event(
            "POST",
            "/judge/investigate",
            body="{}",
            headers={"content-type": "text/plain"},
        ),
        _event(
            "POST",
            "/judge/investigate",
            body="{}",
            headers={"content-type": "application/json"},
            query="budget=999",
        ),
        _event(
            "POST",
            "/judge/investigate",
            body="{}",
            headers={"content-type": "application/json"},
            encoded=True,
        ),
    ),
)
def test_invalid_body_content_type_query_and_encoding_fail_before_services(
    event: dict[str, object],
) -> None:
    harness = Harness()

    response = harness.application.handle(event, object())

    assert response["statusCode"] in {400, 415}
    assert harness.provider_calls == 0
    assert harness.investigation_quota.calls == 0
    assert harness.status_quota.calls == 0
    assert harness.investigation.calls == []


def test_oversized_body_fails_before_authorizer_model_or_aws() -> None:
    harness = Harness()
    body = '{"intent":"' + ("x" * 5_000) + '"}'

    response = harness.application.handle(
        _event(
            "POST",
            "/judge/investigate",
            body=body,
            headers={"content-type": "application/json"},
        ),
        object(),
    )

    assert response["statusCode"] == 413
    assert harness.provider_calls == 0


def test_pathologically_nested_json_fails_before_authorizer_model_or_aws() -> None:
    harness = Harness()
    body = "[" * 1_100 + "0" + "]" * 1_100

    response = harness.application.handle(
        _event(
            "POST",
            "/judge/investigate",
            body=body,
            headers={"content-type": "application/json"},
        ),
        object(),
    )

    assert response["statusCode"] == 400
    assert harness.provider_calls == 0


def test_wrong_token_denies_before_quota_agent_and_status() -> None:
    harness = Harness(authorized=False)

    response = harness.application.handle(
        _event(
            "POST",
            "/judge/investigate",
            body='{"intent":"investigate_idle_sandbox"}',
            headers={
                "authorization": f"Bearer {TOKEN}",
                "content-type": "application/json",
            },
        ),
        object(),
    )

    assert response["statusCode"] == 401
    assert harness.provider_calls == 1
    assert len(harness.authorizer.calls) == 1
    assert harness.investigation_quota.calls == 0
    assert harness.status_quota.calls == 0
    assert harness.investigation.calls == []
    assert TOKEN not in str(response)
    assert TOKEN not in "".join(harness.logs)


def test_investigate_is_strict_quota_bound_and_returns_only_sanitized_truth() -> None:
    harness = Harness()

    response = harness.application.handle(
        _event(
            "POST",
            "/judge/investigate",
            body='{"intent":"investigate_idle_sandbox"}',
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
            },
        ),
        SimpleNamespace(aws_request_id="request-safe-001"),
    )

    assert response["statusCode"] == 200
    assert harness.investigation_quota.calls == 1
    assert harness.status_quota.calls == 0
    assert len(harness.investigation.calls) == 1
    body = _json(response)
    assert body["run_id"] == str(RUN_ID)
    assert body["proposal_id"] == str(PROPOSAL_ID)
    assert set(body) == {
        "evidence_hash",
        "outcome_class",
        "proposal_id",
        "retryable",
        "run_id",
        "state",
        "succeeded",
    }
    assert TOKEN not in str(response)
    assert TOKEN not in "".join(harness.logs)
    assert "instance_id" not in str(response)


def test_status_requires_auth_and_global_quota_before_one_bounded_status_read() -> None:
    harness = Harness()

    response = harness.application.handle(
        _event(
            "GET",
            f"/judge/status/{RUN_ID}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ),
        object(),
    )

    assert response["statusCode"] == 200
    assert harness.investigation_quota.calls == 0
    assert harness.status_quota.calls == 1
    assert harness.investigation.calls == []
    assert harness.status.calls == [RUN_ID]
    assert _json(response)["outcome_class"] == "proposal_ready_no_execution"


def test_status_quota_denial_prevents_durable_status_read() -> None:
    harness = Harness(reservation=None)

    response = harness.application.handle(
        _event(
            "GET",
            f"/judge/status/{RUN_ID}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ),
        object(),
    )

    assert response["statusCode"] == 429
    assert harness.investigation_quota.calls == 0
    assert harness.status_quota.calls == 1
    assert harness.status.calls == []


def test_malformed_status_id_fails_before_auth_quota_and_storage() -> None:
    harness = Harness()

    response = harness.application.handle(
        _event("GET", "/judge/status/not-a-uuid"),
        object(),
    )

    assert response["statusCode"] == 400
    assert harness.provider_calls == 0
    assert harness.investigation_quota.calls == 0
    assert harness.status_quota.calls == 0
    assert harness.status.calls == []


def test_readiness_fails_closed_without_identifier_or_exception_detail() -> None:
    harness = Harness(ready=False)

    response = harness.application.handle(_event("GET", "/ready"), object())

    assert response["statusCode"] == 503
    assert _json(response) == {"error": "NOT_READY", "retryable": False}
    assert "exception" not in str(response).casefold()
    assert "resource" not in str(response).casefold()


@pytest.mark.parametrize(
    ("method", "path", "body", "headers"),
    (
        (
            "POST",
            "/judge/investigate",
            '{"intent":"investigate_idle_sandbox"}',
            {
                "authorization": f"Bearer {TOKEN}",
                "content-type": "application/json",
            },
        ),
        (
            "GET",
            f"/judge/status/{RUN_ID}",
            None,
            {"authorization": f"Bearer {TOKEN}"},
        ),
    ),
)
def test_service_composition_failure_is_dependency_unavailable_not_auth_failure(
    method: str,
    path: str,
    body: str | None,
    headers: dict[str, object],
) -> None:
    application = JudgeFunctionUrlApplication(
        lambda: (_ for _ in ()).throw(RuntimeError("private composition detail"))
    )

    response = application.handle(
        _event(method, path, body=body, headers=headers),
        object(),
    )

    assert response["statusCode"] == 503
    assert _json(response) == {
        "error": "DEPENDENCY_UNAVAILABLE",
        "retryable": True,
        **({"run_id": str(RUN_ID)} if method == "GET" else {}),
    }
    assert "private composition detail" not in str(response)


def test_structured_logger_discards_secrets_prompts_and_tool_arguments() -> None:
    records: list[str] = []
    logger = StructuredJudgeLogger(records.append)

    logger.emit(
        "judge_http_result",
        route="investigate",
        http_status=200,
        authorization=f"Bearer {TOKEN}",
        secret=TOKEN,
        raw_prompt="ignore safety",
        tool_arguments={"instance_id": "i-0123456789abcdef0"},
    )

    assert len(records) == 1
    assert TOKEN not in records[0]
    assert "prompt" not in records[0]
    assert "tool" not in records[0]
    assert "instance" not in records[0]


def test_default_judge_logger_emits_parseable_info_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="aioa.judge")

    StructuredJudgeLogger().emit(
        "judge_http_result",
        route="health",
        method="GET",
        http_status=200,
        outcome="success",
    )

    assert len(caplog.records) == 1
    assert json.loads(caplog.records[0].getMessage()) == {
        "event": "judge_http_result",
        "http_status": 200,
        "method": "GET",
        "outcome": "success",
        "route": "health",
    }
