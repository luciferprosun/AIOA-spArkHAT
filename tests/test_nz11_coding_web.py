"""Existing HTTP service and installed CLI share the admitted coding Core."""

import http.client
import json
import threading
import unittest
from dataclasses import asdict

import test_nz11_controller as support
from webapp import WebRuntimeService, make_server

from runtime.core_admission import Capability
from runtime.main import AgentRuntime
from runtime.mission import coding_tasks


class CodingWebTests(unittest.TestCase):
    def setUp(self):
        self.case = support.ControllerTests(
            "test_two_active_runs_cancel_independently_without_worker_or_core_replay"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.tasks = self.case.service()
        self.fx = self.case.fx
        self.runtime = AgentRuntime(
            None,
            "",
            self.case.case.case.root,
            inspection_only=True,
            coding_tasks=self.tasks,
        )
        self.addCleanup(self.runtime.close)
        self.assertTrue(
            callable(getattr(WebRuntimeService, "coding_request", None)),
            "same-server coding HTTP adapter is missing",
        )
        principals = {
            name: self.fx.p(value)
            for name, value in (
                ("READ", Capability.READ),
                ("MANAGE", Capability.MANAGE),
                ("COMMIT", Capability.COMMIT),
                ("OWNER_APPROVAL", Capability.OWNER_APPROVAL),
            )
        }
        self.service = WebRuntimeService(
            runtime=self.runtime, coding_principals=principals
        )
        self.server = make_server("127.0.0.1", 0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(
        self, method, path, payload=None, *, token=True, intent=None, origin=None
    ):
        conn = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=3
        )
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-AIOA-Session-Token"] = self.service.csrf_token
        if intent:
            headers["X-AIOA-Intent"] = intent
        if origin:
            headers["Origin"] = origin
        conn.request(
            method, path, None if payload is None else json.dumps(payload), headers
        )
        result = conn.getresponse()
        data = result.read()
        code = result.status
        conn.close()
        return code, json.loads(data)

    def test_existing_panel_bootstrap_reports_the_actual_coding_binding(self):
        code, session = self.request("GET", "/api/session")
        self.assertEqual(code, 200)
        self.assertIs(session.get("coding_profile"), True)
        code, status = self.request("GET", "/api/status")
        self.assertEqual(code, 200)
        self.assertIs(status.get("coding_profile"), True)
        self.assertEqual(status["available_models"], [])

    def test_http_admission_status_receipts_and_stop_use_one_existing_core(self):
        task = self.case.case.task
        path = "/api/agent/coding/create_task"
        self.assertEqual(
            self.request(
                "POST", path, {"task": asdict(task)}, intent="coding-create_task-v1"
            )[0],
            200,
        )
        self.assertIs(self.runtime._coding_tasks.journal, self.fx.journal)
        code, view = self.request("GET", "/api/agent/coding/tasks/" + task.task_id)
        self.assertEqual((code, view["state"]), (200, "QUEUED"))
        code, _ = self.request(
            "POST",
            "/api/agent/coding/start",
            {"task_id": task.task_id},
            intent="coding-start-v1",
        )
        self.assertEqual(code, 200)
        self.case.wait_started(task)
        self.assertEqual(
            self.request(
                "POST",
                "/api/agent/coding/stop",
                {"task_id": task.task_id},
                intent="coding-stop-v1",
            )[0],
            200,
        )
        self.assertTrue(self.tasks.wait(task.task_id, 3))
        code, data = self.request("GET", "/api/agent/coding/receipts/" + task.task_id)
        self.assertEqual((code, data["state"]), (200, "CANCELLED"))
        self.assertEqual(
            [r["receipt"]["state"] for r in data["receipts"]],
            ["QUEUED", "RUNNING", "CANCELLED"],
        )

    def test_auth_origin_intent_and_model_authority_are_denied(self):
        path = "/api/agent/coding/create_task"
        payload = {"task": asdict(self.case.case.task)}
        self.assertEqual(
            self.request(
                "POST", path, payload, token=False, intent="coding-create_task-v1"
            )[0],
            403,
        )
        self.assertEqual(
            self.request(
                "POST",
                path,
                payload,
                origin="https://evil.invalid",
                intent="coding-create_task-v1",
            )[0],
            403,
        )
        self.assertEqual(
            self.request("POST", path, payload, intent="coding-start-v1")[0], 403
        )
        payload["approved"] = True
        self.assertEqual(
            self.request("POST", path, payload, intent="coding-create_task-v1")[0], 400
        )
        self.assertFalse(self.case.workers)

    def test_cli_reads_the_full_bounded_core_receipt_chain(self):
        task = self.case.case.task
        self.tasks.request(
            self.fx.p(Capability.MANAGE), "create_task", {"task": asdict(task)}
        )
        for index in range(40):
            self.tasks._transition(
                self.fx.p(),
                task.task_id,
                ("QUEUED", "RUNNING", "VALIDATING"),
                "RUNNING" if index % 2 == 0 else "VALIDATING",
            )
        connection = self.case.case.case.root / "receipt-connection.json"
        connection.write_text(
            json.dumps(
                {"port": self.server.server_port, "csrf_token": self.service.csrf_token}
            )
        )
        connection.chmod(0o600)
        code, expected = self.request(
            "GET", "/api/agent/coding/receipts/" + task.task_id
        )
        self.assertEqual(code, 200)
        self.assertGreater(len(json.dumps(expected).encode()), 16384)
        actual = coding_tasks.coding_http_request(
            connection, "get_receipts", {"task_id": task.task_id}
        )
        self.assertEqual(actual, expected)

    def test_cli_connects_to_existing_server_without_creating_another_runtime(self):
        method = getattr(coding_tasks, "coding_http_request", None)
        self.assertTrue(callable(method), "installed coding CLI transport is missing")
        connection = self.case.case.case.root / "coding-connection.json"
        connection.write_text(
            json.dumps(
                {"port": self.server.server_port, "csrf_token": self.service.csrf_token}
            )
        )
        connection.chmod(0o600)
        task = self.case.case.task
        view = method(connection, "create_task", {"task": asdict(task)})
        self.assertEqual(view["state"], "QUEUED")
        self.assertEqual(
            method(connection, "read_status", {"task_id": task.task_id})["task_digest"],
            task.digest,
        )
        connection.chmod(0o644)
        with self.assertRaises(ValueError):
            method(connection, "read_status", {"task_id": task.task_id})


if __name__ == "__main__":
    unittest.main()
