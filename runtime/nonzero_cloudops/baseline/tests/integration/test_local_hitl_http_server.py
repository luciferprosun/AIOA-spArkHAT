import http.client
import json
import stat
from pathlib import Path
from threading import Thread

import pytest

from aioa_cloudops_agent.agent import create_local_hitl_runtime
from aioa_cloudops_agent.cloudops import MOCK_UNATTACHED_EIP_ID
from aioa_cloudops_agent.config import LocalHitlSettings
from aioa_cloudops_agent.local_api import (
    LOCAL_API_MAX_CONCURRENT_REQUESTS,
    LOCAL_API_SOCKET_TIMEOUT_SECONDS,
    LocalApiApplication,
    LocalApiTokenAuthorizer,
    create_local_http_server,
    load_or_create_local_token,
)
from aioa_cloudops_agent.nz import CloudResourceType

TOKEN = "s" * 48


def test_token_file_is_created_once_with_owner_only_permissions(tmp_path: Path) -> None:
    path = tmp_path / "auth" / "operator.token"

    created = load_or_create_local_token(path, token_factory=lambda: TOKEN)
    loaded = load_or_create_local_token(path, token_factory=lambda: "z" * 48)

    assert created == loaded == TOKEN
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text(encoding="utf-8") == f"{TOKEN}\n"


def test_token_file_rejects_permissive_mode_and_symlink(tmp_path: Path) -> None:
    permissive = tmp_path / "permissive.token"
    permissive.write_text(f"{TOKEN}\n", encoding="utf-8")
    permissive.chmod(0o644)
    with pytest.raises(RuntimeError, match="owner-only"):
        load_or_create_local_token(permissive)

    target = tmp_path / "target.token"
    target.write_text(f"{TOKEN}\n", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "linked.token"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="regular file"):
        load_or_create_local_token(link)

    directory = tmp_path / "token-directory"
    directory.mkdir()
    directory_link = tmp_path / "token-directory-link"
    directory_link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(RuntimeError, match="regular file"):
        load_or_create_local_token(directory_link / "operator.token")


def test_real_loopback_server_exposes_health_and_authenticated_start(
    tmp_path: Path,
) -> None:
    runtime = create_local_hitl_runtime(
        LocalHitlSettings(
            state_path=tmp_path / "truth.json",
            inventory_path=tmp_path / "inventory.json",
        )
    )
    application = LocalApiApplication(runtime, LocalApiTokenAuthorizer(TOKEN))
    server = create_local_http_server(application, port=0)
    assert server.max_concurrent_requests == LOCAL_API_MAX_CONCURRENT_REQUESTS
    assert server.request_queue_size == LOCAL_API_MAX_CONCURRENT_REQUESTS
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", "/health")
        health = connection.getresponse()
        health_body = json.loads(health.read())

        request_body = json.dumps(
            {
                "resource_type": CloudResourceType.ELASTIC_IP.value,
                "resource_id": MOCK_UNATTACHED_EIP_ID,
            }
        )
        connection.request(
            "POST",
            "/api/runs",
            body=request_body,
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
            },
        )
        started = connection.getresponse()
        started_body = json.loads(started.read())
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert health.status == 200
    assert health_body == {"mode": "mock", "service": "aioa-local-hitl", "status": "ok"}
    assert started.status == 201
    assert started_body["ok"] is True
    assert runtime.cloud_provider.network_calls == 0
    assert not thread.is_alive()
    assert LOCAL_API_SOCKET_TIMEOUT_SECONDS == 10


def test_server_refuses_non_loopback_bind(tmp_path: Path) -> None:
    runtime = create_local_hitl_runtime(
        LocalHitlSettings(
            state_path=tmp_path / "truth.json",
            inventory_path=tmp_path / "inventory.json",
        )
    )
    application = LocalApiApplication(runtime, LocalApiTokenAuthorizer(TOKEN))

    with pytest.raises(ValueError, match=r"only to 127\.0\.0\.1"):
        create_local_http_server(application, host="0.0.0.0")
