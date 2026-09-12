import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from aioa_cloudops_agent.agent import create_local_hitl_runtime
from aioa_cloudops_agent.cloudops import (
    MOCK_UNATTACHED_EIP_ID,
    MOCK_UNSAFE_SECURITY_GROUP_ID,
)
from aioa_cloudops_agent.config import LocalHitlSettings
from aioa_cloudops_agent.local_api import (
    LOCAL_API_BODY_MAX_BYTES,
    LOCAL_API_HEADER_MAX_COUNT,
    LOCAL_API_HEADER_VALUE_MAX_LENGTH,
    LOCAL_API_SESSION_COOKIE,
    LocalApiApplication,
    LocalApiTokenAuthorizer,
)
from aioa_cloudops_agent.nz import (
    CloudResourceType,
    WorkflowState,
    generate_event_id,
)

TOKEN = "t" * 48
WRONG_TOKEN = "w" * 48
NONCE = "local-api-decision-nonce-00000001"
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b80")
REQUEST_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b81")
NOW = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)


def _application(tmp_path: Path) -> tuple[LocalApiApplication, object]:
    runtime = create_local_hitl_runtime(
        LocalHitlSettings(
            state_path=tmp_path / "truth.json",
            inventory_path=tmp_path / "inventory.json",
        ),
        clock=lambda: NOW,
        proposal_id_factory=lambda: PROPOSAL_ID,
        request_id_factory=lambda: REQUEST_ID,
        event_id_factory=generate_event_id,
        nonce_factory=lambda: NONCE,
    )
    trace_ids = iter((TRACE_ID, CORRELATION_ID))
    application = LocalApiApplication(
        runtime,
        LocalApiTokenAuthorizer(TOKEN),
        clock=lambda: NOW,
        run_id_factory=lambda: RUN_ID,
        trace_id_factory=lambda: next(trace_ids),
    )
    return application, runtime


def _call(
    application: LocalApiApplication,
    method: str,
    path: str,
    *,
    body: object | str | None = None,
    token: str | None = TOKEN,
    content_type: str | None = "application/json",
    query: str = "",
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], dict[str, str]]:
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if content_type is not None:
        headers["Content-Type"] = content_type
    headers.update(extra_headers or {})
    rendered = body if isinstance(body, str) else json.dumps(body) if body is not None else None
    response = application.handle(
        {
            "method": method,
            "path": path,
            "headers": headers,
            "body": rendered,
            "query": query,
        }
    )
    parsed = json.loads(str(response["body"]))
    return int(response["statusCode"]), parsed, response["headers"]  # type: ignore[return-value]


def _start(
    application: LocalApiApplication,
    resource_type: CloudResourceType = CloudResourceType.ELASTIC_IP,
    resource_id: str = MOCK_UNATTACHED_EIP_ID,
) -> dict[str, object]:
    status, payload, _ = _call(
        application,
        "POST",
        "/api/runs",
        body={"resource_type": resource_type.value, "resource_id": resource_id},
    )
    assert status == 201
    assert payload["ok"] is True
    return payload["result"]  # type: ignore[return-value]


def _challenge(application: LocalApiApplication) -> dict[str, object]:
    status, payload, _ = _call(
        application,
        "POST",
        f"/api/runs/{RUN_ID}/approval-request",
        body={},
    )
    assert status == 200
    return payload["result"]  # type: ignore[return-value]


def _decision_body(challenge: dict[str, object], decision: str) -> dict[str, object]:
    request = challenge["request"]
    assert isinstance(request, dict)
    return {
        "request_id": request["request_id"],
        "run_id": request["run_id"],
        "proposal_id": request["proposal_id"],
        "request_hash": request["request_hash"],
        "proposal_hash": request["proposal_hash"],
        "evidence_hash": request["evidence_hash"],
        "proposal_version": request["proposal_version"],
        "decision": decision,
        "decision_nonce": challenge["decision_nonce"],
    }


def test_full_approved_http_flow_executes_verifies_and_reconciles(
    tmp_path: Path,
) -> None:
    application, runtime = _application(tmp_path)

    started = _start(application)
    assert started["final_state"] == WorkflowState.AWAITING_APPROVAL.value
    challenge = _challenge(application)
    decision_status, decision, _ = _call(
        application,
        "POST",
        f"/api/runs/{RUN_ID}/decision",
        body=_decision_body(challenge, "APPROVED"),
    )
    resume_status, completion, _ = _call(
        application,
        "POST",
        f"/api/runs/{RUN_ID}/resume",
        body={"confirm_execution": True},
    )
    replay_status, replay, _ = _call(
        application,
        "POST",
        f"/api/runs/{RUN_ID}/resume",
        body={"confirm_execution": True},
    )
    status_code, durable, headers = _call(
        application,
        "GET",
        f"/api/runs/{RUN_ID}",
        body=None,
        content_type=None,
    )

    assert decision_status == resume_status == replay_status == status_code == 200
    assert decision["result"]["final_state"] == WorkflowState.APPROVED.value
    assert completion["result"]["final_state"] == WorkflowState.SUCCESS_WITH_EVIDENCE.value
    assert replay["result"]["reconciled"] is True
    assert durable["result"]["run"]["state"] == WorkflowState.SUCCESS_WITH_EVIDENCE.value
    assert NONCE not in json.dumps(durable)
    assert runtime.executor.mutation_calls == 1
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"


def test_denied_http_flow_never_executes(tmp_path: Path) -> None:
    application, runtime = _application(tmp_path)
    _start(
        application,
        CloudResourceType.SECURITY_GROUP,
        MOCK_UNSAFE_SECURITY_GROUP_ID,
    )
    challenge = _challenge(application)

    decision_status, decision, _ = _call(
        application,
        "POST",
        f"/api/runs/{RUN_ID}/decision",
        body=_decision_body(challenge, "DENIED"),
    )
    resume_status, completion, _ = _call(
        application,
        "POST",
        f"/api/runs/{RUN_ID}/resume",
        body={"confirm_execution": True},
    )

    assert decision_status == resume_status == 200
    assert decision["result"]["final_state"] == WorkflowState.DENIED_BY_HUMAN.value
    assert "receipt" not in completion["result"]
    assert runtime.executor.execute_calls == runtime.executor.mutation_calls == 0


def test_auth_is_exact_and_precedes_json_parsing(tmp_path: Path) -> None:
    application, _ = _application(tmp_path)

    missing, missing_body, _ = _call(
        application,
        "POST",
        "/api/runs",
        body="{not-json",
        token=None,
    )
    wrong, wrong_body, _ = _call(
        application,
        "POST",
        "/api/runs",
        body={},
        token=WRONG_TOKEN,
    )
    padded, padded_body, _ = _call(
        application,
        "POST",
        "/api/runs",
        body={},
        token=f"{TOKEN} ",
    )

    assert (missing, wrong, padded) == (401, 401, 401)
    assert missing_body["error"] == wrong_body["error"] == padded_body["error"] == "UNAUTHORIZED"
    assert TOKEN not in json.dumps((missing_body, wrong_body, padded_body))


@pytest.mark.parametrize(
    ("body", "content_type", "expected"),
    [
        ('{"resource_type":"AWS::EC2::EIP","resource_type":"AWS::EC2::EIP"}', "application/json", 400),
        ({"resource_type": "AWS::EC2::EIP", "resource_id": MOCK_UNATTACHED_EIP_ID, "extra": True}, "application/json", 400),
        ({"resource_type": "AWS::EC2::EIP", "resource_id": MOCK_UNATTACHED_EIP_ID}, "text/plain", 415),
    ],
)
def test_start_rejects_ambiguous_or_non_contract_input(
    tmp_path: Path,
    body: object,
    content_type: str,
    expected: int,
) -> None:
    application, _ = _application(tmp_path)

    status, payload, _ = _call(
        application,
        "POST",
        "/api/runs",
        body=body,
        content_type=content_type,
    )

    assert status == expected
    assert payload["ok"] is False


def test_routes_reject_queries_bad_ids_methods_and_oversized_bodies(
    tmp_path: Path,
) -> None:
    application, _ = _application(tmp_path)

    queried, _, _ = _call(
        application,
        "POST",
        "/api/runs",
        body={},
        query="resource_id=attacker-controlled",
    )
    invalid_id, _, _ = _call(
        application,
        "GET",
        "/api/runs/not-a-uuid",
        content_type=None,
    )
    method, _, _ = _call(
        application,
        "DELETE",
        "/api/runs",
        body=None,
        content_type=None,
    )
    oversized, oversized_body, _ = _call(
        application,
        "POST",
        "/api/runs",
        body="x" * (LOCAL_API_BODY_MAX_BYTES + 1),
    )

    assert (queried, invalid_id, method, oversized) == (400, 400, 405, 413)
    assert oversized_body["error"] == "PAYLOAD_TOO_LARGE"


def test_public_console_has_strict_csp_and_no_browser_secret_storage(
    tmp_path: Path,
) -> None:
    application, _ = _application(tmp_path)

    root = application.handle(
        {"method": "GET", "path": "/", "headers": {}, "body": None, "query": ""}
    )
    health = application.handle(
        {"method": "GET", "path": "/health", "headers": {}, "body": None, "query": ""}
    )
    body = str(root["body"])
    headers = root["headers"]

    assert root["statusCode"] == health["statusCode"] == 200
    assert "localStorage" not in body
    assert "sessionStorage" not in body
    assert TOKEN not in body
    assert "Demo sandbox" in body
    assert "Evidence first" in body
    assert "data-scenario" in body
    assert "DENIED_BY_HUMAN" in body
    assert "authorizes_execution: false" in body
    assert "style=" not in body
    assert "sha256-" in headers["content-security-policy"]  # type: ignore[index]
    assert "connect-src 'self'" in headers["content-security-policy"]  # type: ignore[index]
    assert headers["x-frame-options"] == "DENY"  # type: ignore[index]


def test_ready_contract_labels_portable_truth_without_cloud_prerequisites(
    tmp_path: Path,
) -> None:
    application, _ = _application(tmp_path)

    ready = application.handle(
        {"method": "GET", "path": "/ready", "headers": {}, "body": None, "query": ""}
    )
    payload = json.loads(str(ready["body"]))
    runtime = payload["runtime"]

    assert ready["statusCode"] == 200
    assert payload["status"] == "ready"
    assert payload["process_status"] == "READY"
    assert payload["provider_status"] == "READY"
    assert payload["sandbox_status"] == "READY"
    assert runtime["runtime_mode"] == "portable"
    assert runtime["experience_mode"] == "DEMO_SANDBOX"
    assert runtime["model_mode"] == "DETERMINISTIC_MODEL"
    assert runtime["provider"] == "mock"
    assert runtime["agent_framework"] == "strands-agents"
    assert runtime["aws_calls_allowed"] is False
    assert runtime["external_network_allowed"] is False
    assert runtime["real_cloud_mutations_enabled"] is False


def test_ready_fails_closed_when_sandbox_integrity_is_invalid(tmp_path: Path) -> None:
    application, runtime = _application(tmp_path)
    _start(application)
    inventory_path = runtime.cloud_state.path
    inventory_path.write_text("{truncated", encoding="utf-8")
    inventory_path.chmod(0o600)

    ready = application.handle(
        {"method": "GET", "path": "/ready", "headers": {}, "body": None, "query": ""}
    )
    payload = json.loads(str(ready["body"]))

    assert ready["statusCode"] == 503
    assert payload == {
        "error": "DEPENDENCY_UNAVAILABLE",
        "ok": False,
        "retryable": True,
    }


def test_browser_session_exchange_uses_http_only_cookie_and_intent_header(
    tmp_path: Path,
) -> None:
    application, _ = _application(tmp_path)

    session_status, session, session_headers = _call(
        application,
        "POST",
        "/api/session",
        body={},
    )
    cookie = session_headers["set-cookie"]
    cookie_pair = cookie.split(";", 1)[0]
    session_get, session_view, _ = _call(
        application,
        "GET",
        "/api/session",
        token=None,
        content_type=None,
        extra_headers={"Cookie": cookie_pair},
    )
    missing_intent, missing_intent_body, _ = _call(
        application,
        "POST",
        "/api/runs",
        body={
            "resource_type": CloudResourceType.ELASTIC_IP.value,
            "resource_id": MOCK_UNATTACHED_EIP_ID,
        },
        token=None,
        extra_headers={"Cookie": cookie_pair},
    )
    started, started_body, _ = _call(
        application,
        "POST",
        "/api/runs",
        body={
            "resource_type": CloudResourceType.ELASTIC_IP.value,
            "resource_id": MOCK_UNATTACHED_EIP_ID,
        },
        token=None,
        extra_headers={
            "Cookie": cookie_pair,
            "X-AIOA-Intent": "judge-console-v1",
        },
    )
    cleared, _, cleared_headers = _call(
        application,
        "DELETE",
        "/api/session",
        body=None,
        token=None,
        content_type=None,
    )

    assert session_status == session_get == cleared == 200
    assert started == 201
    assert session["result"] == session_view["result"]
    assert session["result"]["storage"] == "http_only_session_cookie"
    assert cookie.startswith(f"{LOCAL_API_SESSION_COOKIE}=")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert TOKEN not in cookie
    assert missing_intent == 401
    assert missing_intent_body["error"] == "UNAUTHORIZED"
    assert started_body["ok"] is True
    assert "Max-Age=0" in cleared_headers["set-cookie"]


def test_run_view_is_sanitized_and_exposes_bounded_audit_evidence(
    tmp_path: Path,
) -> None:
    application, runtime = _application(tmp_path)
    _start(application)
    challenge = _challenge(application)
    _call(
        application,
        "POST",
        f"/api/runs/{RUN_ID}/decision",
        body=_decision_body(challenge, "APPROVED"),
    )
    _call(
        application,
        "POST",
        f"/api/runs/{RUN_ID}/resume",
        body={"confirm_execution": True},
    )

    status, payload, _ = _call(
        application,
        "GET",
        f"/api/runs/{RUN_ID}",
        body=None,
        content_type=None,
    )
    rendered = json.dumps(payload, sort_keys=True)
    view = payload["result"]

    assert status == 200
    assert view["run"]["state"] == WorkflowState.SUCCESS_WITH_EVIDENCE.value
    assert view["run_sandbox_mutations"] == runtime.executor.mutation_calls == 1
    assert view["runtime"]["process_external_network_calls"] == 0
    assert view["runtime"]["process_sandbox_mutations"] == 1
    assert view["evidence_schema_version"] == 2
    assert view["evidence_integrity"] == "VERIFIED"
    assert len(view["evidence_snapshot_sha256"]) == 64
    assert len(view["audit_events"]) >= 8
    assert view["audit_event_count"] == len(view["audit_events"])
    assert view["audit_events_truncated"] is False
    assert view["audit_events"][-1]["type"] == "VERIFICATION_RECORDED"
    assert view["audit_events"][-1]["category"] == "VERIFICATION"
    assert view["audit_events"][-1]["summary"] == "Verification Recorded"
    assert view["checkpoint"]["verification"]["verification_hash"]
    assert "decision_nonce" not in rendered
    assert "actor_session_id" not in rendered
    assert NONCE not in rendered


def test_token_authorizer_rejects_invalid_constructor_values() -> None:
    with pytest.raises(ValueError):
        LocalApiTokenAuthorizer("short")
    with pytest.raises(ValueError):
        LocalApiTokenAuthorizer(f"{'x' * 32} ")


@pytest.mark.parametrize(
    "headers",
    [
        {f"X-Test-{index}": "value" for index in range(LOCAL_API_HEADER_MAX_COUNT + 1)},
        {"X-Oversized": "x" * (LOCAL_API_HEADER_VALUE_MAX_LENGTH + 1)},
        {"X-Non-Text": 123},
    ],
)
def test_header_resource_limits_fail_closed(
    tmp_path: Path,
    headers: dict[str, object],
) -> None:
    application, _ = _application(tmp_path)

    response = application.handle(
        {"method": "GET", "path": "/health", "headers": headers, "body": None}
    )
    payload = json.loads(str(response["body"]))

    assert response["statusCode"] == 400
    assert payload == {"error": "BAD_REQUEST", "ok": False, "retryable": False}


def test_tampered_durable_evidence_returns_redacted_dependency_failure(
    tmp_path: Path,
) -> None:
    application, runtime = _application(tmp_path)
    _start(application)
    path = runtime.repository.path
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["payload"]["runs"][0]["state"] = "EXECUTING"
    path.write_text(json.dumps(raw), encoding="utf-8")

    status, payload, _ = _call(
        application,
        "GET",
        f"/api/runs/{RUN_ID}",
        body=None,
        content_type=None,
    )

    assert status == 503
    assert payload == {
        "error": "DEPENDENCY_UNAVAILABLE",
        "ok": False,
        "retryable": True,
    }
    assert "digest" not in json.dumps(payload).casefold()
