from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

try:
    from tui.app import AOIATerminalApp, build_app
    from tui.widgets.approval_panel import ApprovalPanel
    from tui.widgets.status_bar import RuntimeStatusBar
    from tui.widgets.transcript_panel import TranscriptPanel, sanitize_transcript
except ModuleNotFoundError as exc:
    if exc.name == "textual":
        raise unittest.SkipTest("optional dependency textual is not installed") from exc
    raise


class TUIPhase2Tests(unittest.TestCase):
    def test_transcript_sanitizes_runtime_internal_output(self) -> None:
        rendered = sanitize_transcript(
            "\n".join(
                [
                    "Agent> visible operator response",
                    "SYSTEM PROMPT:",
                    "hidden prompt internals",
                    "",
                    "Result: safe summary",
                ]
            )
        )
        self.assertIn("visible operator response", rendered)
        self.assertIn("[redacted runtime-internal output]", rendered)
        self.assertIn("Result: safe summary", rendered)
        self.assertNotIn("hidden prompt internals", rendered)

    def test_transcript_panel_keeps_bounded_operator_entries(self) -> None:
        panel = TranscriptPanel()
        panel.max_entries = 2
        panel.append_entry("operator", "first")
        panel.append_entry("runtime", "second")
        panel.append_entry("runtime", "third")
        rendered = panel.render_entries()
        self.assertNotIn("first", rendered)
        self.assertIn("second", rendered)
        self.assertIn("third", rendered)

    def test_approval_panel_renders_operator_controls(self) -> None:
        rendered = ApprovalPanel().render_pending(
            {
                "action": "shell_execute",
                "command": "sudo dnf update",
                "reason": "Risky test action.",
            },
            timeout_seconds=120,
        )
        self.assertIn("Approval required", rendered)
        self.assertIn("shell_execute", rendered)
        self.assertIn("sudo dnf update", rendered)
        self.assertIn("Ctrl+A approve", rendered)

    def test_status_bar_contains_runtime_contract_fields(self) -> None:
        rendered = RuntimeStatusBar().render_status_bar(
            {
                "model": "gemini/gemini-2.5-flash",
                "cwd": "/tmp/aoia",
                "session_log": "/tmp/session.jsonl",
                "knowledge_routing": {"enabled": True},
                "epistemic_safeguards": {"disable_model": False},
            }
        )
        self.assertIn("provider=gemini/gemini-2.5-flash", rendered)
        self.assertIn("retrieval=on", rendered)
        self.assertIn("approval=operator", rendered)

    def test_tui_approval_flow_can_approve_without_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "runtime"
            project_dir.mkdir()
            app = build_app(project_dir=project_dir)
            app.call_from_thread = lambda callback, *args: callback(*args)  # type: ignore[method-assign]
            app._show_pending_approval = lambda action: None  # type: ignore[method-assign]
            app._clear_pending_approval = lambda approved: None  # type: ignore[method-assign]

            result: dict[str, bool] = {}

            def request() -> None:
                result["approved"] = app._request_approval_from_tui(
                    {"action": "shell_execute", "command": "sudo whoami"}
                )

            thread = threading.Thread(target=request)
            thread.start()
            self.assertTrue(app._approval_event is not None)
            app.action_approve_pending()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertTrue(result["approved"])

    def test_tui_request_thread_uses_runtime_run_text_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "runtime"
            project_dir.mkdir()
            app = build_app(project_dir=project_dir)

            calls: list[str] = []

            class FakeRuntime:
                def log_session_event(self, kind, payload):
                    calls.append(kind)

                def assistant_request(self, raw, *, mode, plan_options):
                    calls.append(raw)
                    calls.append('assistant:'+mode)
                    calls.append('budget:'+plan_options['run_budget_usd'])
                    return {'mode':'cpl','cpl':{'execution_status':'PLANNED','prompt':raw}}

            app.runtime = FakeRuntime()  # type: ignore[assignment]
            app.call_from_thread = lambda callback, *args: calls.append(args[0])  # type: ignore[method-assign]

            app._run_request_thread("status please")

        self.assertIn("tui_operator_request", calls)
        self.assertIn("status please", calls)
        self.assertIn('assistant:cpl', calls)
        self.assertIn('budget:0', calls)
        self.assertTrue(any('CPL PLAN — NOT A FINAL ANSWER' in value for value in calls))

    def test_start_script_exists_and_uses_runtime_venv(self) -> None:
        script = Path("scripts/start_tui.sh")
        self.assertTrue(script.exists())
        self.assertTrue(script.stat().st_mode & 0o111)
        content = script.read_text(encoding="utf-8")
        self.assertIn('RUNTIME_DIR="$ROOT_DIR/runtime"', content)
        self.assertIn('VENV_DIR="$RUNTIME_DIR/.venv"', content)
        self.assertIn("PYTHONPATH", content)
        self.assertIn("-m tui.app", content)


if __name__ == "__main__":
    unittest.main()
