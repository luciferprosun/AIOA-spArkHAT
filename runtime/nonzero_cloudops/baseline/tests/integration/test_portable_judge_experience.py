import http.client
import json
from pathlib import Path
from threading import Thread

from aioa_cloudops_agent.agent import create_local_hitl_runtime
from aioa_cloudops_agent.cloudops import (
    MOCK_UNATTACHED_EIP_ID,
    MOCK_UNSAFE_SECURITY_GROUP_ID,
)
from aioa_cloudops_agent.config import LocalHitlSettings
from aioa_cloudops_agent.local_api import (
    LocalApiApplication,
    LocalApiTokenAuthorizer,
    create_local_http_server,
)
from aioa_cloudops_agent.nz import CloudResourceType

TOKEN = "portable-judge-e2e-" + "e" * 32


def _request(
    connection: http.client.HTTPConnection,
    method: str,
    path: str,
    *,
    body: object | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object], dict[str, str]]:
    request_headers = {"Accept": "application/json", **(headers or {})}
    rendered: str | None = None
    if body is not None:
        rendered = json.dumps(body)
        request_headers["Content-Type"] = "application/json"
    connection.request(method, path, body=rendered, headers=request_headers)
    response = connection.getresponse()
    payload = json.loads(response.read())
    return response.status, payload, {name.casefold(): value for name, value in response.getheaders()}


def _decision(challenge: dict[str, object], decision: str) -> dict[str, object]:
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


def _start_server(settings: LocalHitlSettings) -> tuple[object, object, Thread]:
    runtime = create_local_hitl_runtime(settings)
    application = LocalApiApplication(runtime, LocalApiTokenAuthorizer(TOKEN))
    server = create_local_http_server(application, port=0)
    thread = Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        daemon=True,
    )
    thread.start()
    return runtime, server, thread


def _stop_server(server: object, thread: Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_judge_http_experience_survives_stale_tab_duplicate_click_and_restart(
    tmp_path: Path,
) -> None:
    settings = LocalHitlSettings(
        state_path=tmp_path / "truth.json",
        inventory_path=tmp_path / "inventory.json",
    )
    runtime, server, thread = _start_server(settings)
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        session_status, session, session_headers = _request(
            connection,
            "POST",
            "/api/session",
            body={},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        cookie = session_headers["set-cookie"].split(";", 1)[0]
        browser_headers = {
            "Cookie": cookie,
            "X-AIOA-Intent": "judge-console-v1",
        }
        start_status, started, _ = _request(
            connection,
            "POST",
            "/api/runs",
            body={
                "resource_type": CloudResourceType.ELASTIC_IP.value,
                "resource_id": MOCK_UNATTACHED_EIP_ID,
            },
            headers=browser_headers,
        )
        run_id = started["result"]["run_id"]
        first_status, first, _ = _request(
            connection,
            "POST",
            f"/api/runs/{run_id}/approval-request",
            body={},
            headers=browser_headers,
        )
        second_status, second, _ = _request(
            connection,
            "POST",
            f"/api/runs/{run_id}/approval-request",
            body={},
            headers=browser_headers,
        )
        stale_status, stale, _ = _request(
            connection,
            "POST",
            f"/api/runs/{run_id}/decision",
            body=_decision(first["result"], "APPROVED"),
            headers=browser_headers,
        )
        decision_status, decision, _ = _request(
            connection,
            "POST",
            f"/api/runs/{run_id}/decision",
            body=_decision(second["result"], "APPROVED"),
            headers=browser_headers,
        )
        completion_status, completion, _ = _request(
            connection,
            "POST",
            f"/api/runs/{run_id}/resume",
            body={"confirm_execution": True},
            headers=browser_headers,
        )
        replay_status, replay, _ = _request(
            connection,
            "POST",
            f"/api/runs/{run_id}/resume",
            body={"confirm_execution": True},
            headers=browser_headers,
        )
        view_status, view, _ = _request(
            connection,
            "GET",
            f"/api/runs/{run_id}",
            headers={"Cookie": cookie},
        )
    finally:
        connection.close()
        _stop_server(server, thread)

    assert session_status == first_status == second_status == 200
    assert start_status == 201
    assert stale_status == 403
    assert stale["failure_code"] == "LOCAL_APPROVAL_BINDING_MISMATCH"
    assert decision_status == completion_status == replay_status == view_status == 200
    assert decision["result"]["final_state"] == "APPROVED"
    assert completion["result"]["final_state"] == "SUCCESS_WITH_EVIDENCE"
    assert replay["result"]["reconciled"] is True
    assert runtime.executor.mutation_calls == 1
    assert view["result"]["run_sandbox_mutations"] == 1
    assert view["result"]["runtime"]["process_external_network_calls"] == 0
    assert any(
        event["type"] == "POLICY_DENIED"
        for event in view["result"]["audit_events"]
    )
    rendered = json.dumps((session, view), sort_keys=True)
    assert TOKEN not in rendered
    assert "decision_nonce" not in rendered
    assert "actor_session_id" not in rendered

    restarted, server, thread = _start_server(settings)
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        restored_status, restored, _ = _request(
            connection,
            "GET",
            f"/api/runs/{run_id}",
            headers={"Cookie": cookie},
        )
        recovered_status, recovered, _ = _request(
            connection,
            "POST",
            f"/api/runs/{run_id}/resume",
            body={"confirm_execution": True},
            headers=browser_headers,
        )
        denied_start_status, denied_started, _ = _request(
            connection,
            "POST",
            "/api/runs",
            body={
                "resource_type": CloudResourceType.SECURITY_GROUP.value,
                "resource_id": MOCK_UNSAFE_SECURITY_GROUP_ID,
            },
            headers=browser_headers,
        )
        denied_run_id = denied_started["result"]["run_id"]
        denied_challenge_status, denied_challenge, _ = _request(
            connection,
            "POST",
            f"/api/runs/{denied_run_id}/approval-request",
            body={},
            headers=browser_headers,
        )
        denied_decision_status, denied_decision, _ = _request(
            connection,
            "POST",
            f"/api/runs/{denied_run_id}/decision",
            body=_decision(denied_challenge["result"], "DENIED"),
            headers=browser_headers,
        )
        denied_view_status, denied_view, _ = _request(
            connection,
            "GET",
            f"/api/runs/{denied_run_id}",
            headers={"Cookie": cookie},
        )
    finally:
        connection.close()
        _stop_server(server, thread)

    assert restored_status == recovered_status == 200
    assert restored["result"]["run"]["state"] == "SUCCESS_WITH_EVIDENCE"
    assert recovered["result"]["reconciled"] is True
    assert denied_start_status == 201
    assert denied_challenge_status == denied_decision_status == denied_view_status == 200
    assert denied_decision["result"]["final_state"] == "DENIED_BY_HUMAN"
    assert denied_view["result"]["run_sandbox_mutations"] == 0
    assert "execution_receipt" not in denied_view["result"]["checkpoint"]
    assert restarted.executor.mutation_calls == 0
    assert restarted.cloud_provider.network_calls == 0
    assert restarted.model_provider.network_calls == 0
