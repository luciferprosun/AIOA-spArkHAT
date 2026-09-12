from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from textual.app import App
from textual.widgets import Input, Label

from tui.widgets.approval_panel import ApprovalPanel
from tui.assistant import operator_request
from main import DEBUG_RAW_RESPONSE, PROMPT_FILE, AgentRuntime, ProviderManager, load_prompt_template
from tui.views.dashboard import DashboardView
from tui.widgets.log_panel import LogPanel
from tui.widgets.status_panel import StatusPanel
from tui.widgets.status_bar import RuntimeStatusBar
from tui.widgets.transcript_panel import TranscriptPanel


class AOIATerminalApp(App):
    """Minimal operator TUI around the existing AgentRuntime."""

    CSS = DashboardView.DEFAULT_CSS
    BINDINGS = [
        ("ctrl+r", "refresh_status", "Refresh"),
        ("ctrl+a", "approve_pending", "Approve"),
        ("ctrl+x", "reject_pending", "Reject"),
        ("ctrl+p", "history_previous", "Prev"),
        ("ctrl+n", "history_next", "Next"),
        ("q", "quit", "Quit"),
    ]
    APPROVAL_TIMEOUT_SECONDS = 120

    def __init__(self, project_dir: Path | None = None, *, plain_chat=False, cpl_cost_policy=None, cpl_run_budget='0') -> None:
        super().__init__()
        self.project_dir = project_dir or RUNTIME_DIR
        self.plain_chat = plain_chat
        self.cpl_run_budget = cpl_run_budget
        self.runtime = AgentRuntime(
            provider_manager=ProviderManager(self.project_dir),
            prompt_template=load_prompt_template(PROMPT_FILE),
            project_dir=self.project_dir,
            debug_raw=DEBUG_RAW_RESPONSE,
        )
        self.runtime.executor._request_approval = self._request_approval_from_tui  # type: ignore[method-assign]
        self.runtime.cpl_cost_policy = cpl_cost_policy
        self.command_history: list[str] = []
        self.history_index: int | None = None
        self.request_running = False
        self.pending_approval: dict[str, Any] | None = None
        self._approval_event: threading.Event | None = None
        self._approval_decision = False

    def compose(self):
        yield DashboardView()

    def on_mount(self) -> None:
        self.title = "AIOA spArkHAT Operator Console"
        self.sub_title = 'Plain Chat — explicit CPL BYPASS' if self.plain_chat else 'Critical Prompt Loop — DEFAULT'
        self.refresh_status()
        self.set_interval(2.0, self.refresh_status)
        self.query_one(ApprovalPanel).set_idle()
        self.query_one(TranscriptPanel).update("No transcript yet.")
        self.query_one("#operator-input", Input).focus()

    def action_refresh_status(self) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        status = self.runtime.snapshot_status()
        self.query_one(StatusPanel).update_status(status)
        self.query_one(LogPanel).update_from_status(status)
        self.query_one(RuntimeStatusBar).update_status(status)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value
        event.input.value = ""
        if not raw.strip():
            return
        if event.input.id != "operator-input":
            return
        self._dispatch_operator_input(raw)

    def _dispatch_operator_input(self, raw: str) -> None:
        self._remember_command(raw)
        if raw in {"/quit", "/exit"}:
            self.exit()
            return
        if raw == "/clear":
            self.query_one(TranscriptPanel).clear_entries()
            self._notice("Transcript cleared.")
            return
        if raw == "/status":
            self.refresh_status()
            self.query_one(TranscriptPanel).append_entry("status", self._status_summary())
            return
        if raw.startswith("/model "):
            self._switch_model(raw.split(maxsplit=1)[1])
            return
        if raw == "/model":
            self.query_one(TranscriptPanel).append_entry(
                "system",
                "\n".join(self.runtime.provider_manager.available_models()) or "No configured providers reported.",
            )
            return
        if self.request_running:
            self._notice("Request is already running. Wait for completion before submitting another command.")
            return

        self.query_one(TranscriptPanel).append_entry("operator", raw)
        self.request_running = True
        self._notice('Plain Chat bypass; not CPL reviewed.' if self.plain_chat else 'CPL default: questions preview a plan; approval is a separate command.')
        worker = threading.Thread(target=self._run_request_thread, args=(raw,), daemon=True)
        worker.start()

    def _switch_model(self, model_name: str) -> None:
        try:
            selected = self.runtime.provider_manager.switch_model(model_name)
            notice = self.runtime.provider_manager.model_notice(selected) or "Provider switched."
            self._notice(f"Model switched to: {selected}. {notice}")
            self.query_one(TranscriptPanel).append_entry("system", f"Model switched to: {selected}. {notice}")
        except Exception as error:
            self._notice(f"Provider switch failed: {error}")
            self.query_one(TranscriptPanel).append_entry("error", f"Provider switch failed: {error}")
        self.refresh_status()

    def _run_request_thread(self, raw: str) -> None:
        try:
            self.runtime.log_session_event(
                "tui_operator_request",
                {"length": len(raw), "slash_command": raw.startswith("/")},
            )
            transcript = operator_request(self.runtime, raw, plain_chat=self.plain_chat, run_budget=self.cpl_run_budget)
            self.call_from_thread(self._complete_request, transcript, None)
        except Exception as error:
            self.call_from_thread(self._complete_request, "", error)

    def _complete_request(self, transcript: str, error: Exception | None) -> None:
        self.request_running = False
        if error is not None:
            self.query_one(TranscriptPanel).append_entry("error", str(error))
            self._notice(f"Request failed: {error}")
        else:
            self.query_one(TranscriptPanel).append_entry("runtime", transcript or "(no visible output)")
            self._notice("Request completed.")
        self.refresh_status()

    def _request_approval_from_tui(self, action: dict[str, Any]) -> bool:
        event = threading.Event()
        self._approval_event = event
        self._approval_decision = False
        self.pending_approval = dict(action)
        self.call_from_thread(self._show_pending_approval, dict(action))
        approved = event.wait(self.APPROVAL_TIMEOUT_SECONDS) and self._approval_decision
        self.call_from_thread(self._clear_pending_approval, approved)
        return approved

    def _show_pending_approval(self, action: dict[str, Any]) -> None:
        self.query_one(ApprovalPanel).set_pending(action, self.APPROVAL_TIMEOUT_SECONDS)
        self.query_one(TranscriptPanel).append_entry(
            "approval",
            f"Approval required for {action.get('action', '(unknown)')}. Use Ctrl+A to approve or Ctrl+X to reject.",
        )
        self._notice("Approval required.")

    def _clear_pending_approval(self, approved: bool) -> None:
        action_name = self.pending_approval.get("action", "(unknown)") if self.pending_approval else "(unknown)"
        self.runtime.log_session_event(
            "tui_approval_decision",
            {"action": action_name, "approved": approved},
        )
        self.query_one(ApprovalPanel).set_idle()
        self.query_one(TranscriptPanel).append_entry(
            "approval",
            f"{action_name} {'approved' if approved else 'rejected or timed out'}.",
        )
        self.pending_approval = None
        self._approval_event = None
        self._notice("Approval completed." if approved else "Approval rejected or timed out.")

    def action_approve_pending(self) -> None:
        if not self._approval_event:
            self._notice("No pending approval.")
            return
        self._approval_decision = True
        self._approval_event.set()

    def action_reject_pending(self) -> None:
        if not self._approval_event:
            service = self.runtime._cpl_service
            active = service.status()['active_run_id'] if service is not None else None
            if active:
                service.cancel(active)
                self._notice('CPL cancelled; already-sent provider requests may still be billed.')
                return
            self._notice("No pending approval.")
            return
        self._approval_decision = False
        self._approval_event.set()

    def action_history_previous(self) -> None:
        if not self.command_history:
            return
        if self.history_index is None:
            self.history_index = len(self.command_history) - 1
        else:
            self.history_index = max(0, self.history_index - 1)
        self.query_one("#operator-input", Input).value = self.command_history[self.history_index]

    def action_history_next(self) -> None:
        if not self.command_history or self.history_index is None:
            return
        self.history_index += 1
        input_widget = self.query_one("#operator-input", Input)
        if self.history_index >= len(self.command_history):
            self.history_index = None
            input_widget.value = ""
        else:
            input_widget.value = self.command_history[self.history_index]

    def _remember_command(self, raw: str) -> None:
        if not self.command_history or self.command_history[-1] != raw:
            self.command_history.append(raw)
        self.command_history = self.command_history[-50:]
        self.history_index = None

    def _status_summary(self) -> str:
        status = self.runtime.snapshot_status()
        return self.query_one(RuntimeStatusBar).render_status_bar(status)

    def _notice(self, message: str) -> None:
        self.query_one("#notice", Label).update(message)

    def on_unmount(self) -> None:
        try:
            self.runtime.log_session_event(
                "tui_shutdown",
                {"message": "AOIA terminal UI closed cleanly."},
            )
        except Exception:
            pass
        finally:
            self.runtime.close()


def build_app(project_dir: Path | None = None, *, plain_chat=False, cpl_cost_policy=None, cpl_run_budget='0') -> AOIATerminalApp:
    return AOIATerminalApp(project_dir=project_dir, plain_chat=plain_chat,
        cpl_cost_policy=cpl_cost_policy, cpl_run_budget=cpl_run_budget)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description='AIOA spArkHAT optional operator console; CPL default')
    parser.add_argument('--plain-chat', action='store_true', help='Explicit bypass of CPL for ordinary questions')
    parser.add_argument('--cpl-live-policy', help='Explicit private price/budget policy; no automatic approval')
    parser.add_argument('--cpl-run-budget', default='0', help='Per-question LIVE admission cap in USD')
    args = parser.parse_args()
    from critical_loop.policy import load_cost_policy
    policy = load_cost_policy(args.cpl_live_policy) if args.cpl_live_policy else None
    build_app(plain_chat=args.plain_chat, cpl_cost_policy=policy, cpl_run_budget=args.cpl_run_budget).run()


if __name__ == "__main__":
    main()
