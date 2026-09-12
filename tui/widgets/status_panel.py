from __future__ import annotations

from typing import Any

from textual.widgets import Static


class StatusPanel(Static):
    """Read-only operational status panel backed by AgentRuntime.snapshot_status."""

    def render_status(self, status: dict[str, Any]) -> str:
        knowledge = status.get("knowledge_routing", {})
        safeguards = status.get("epistemic_safeguards", {})
        lines = [
            "AIOA spArkHAT Status",
            f"provider/model: {status.get('model', '(unknown)')}",
            f"cwd: {status.get('cwd', '(unknown)')}",
            f"session_log: {status.get('session_log', '(unknown)')}",
            f"retrieval: {'enabled' if knowledge.get('enabled') else 'disabled'}",
            f"memory_mode: evidence/reasoning separated; operational logs replay-only",
            f"approval_mode: operator-supervised dangerous/confirmed actions",
            f"kill_switch: {safeguards.get('kill_switch')}",
            f"model_disabled: {safeguards.get('disable_model')}",
            f"active_hat: {status.get('active_memory_hat', {}).get('active_hat', '(none)')}",
        ]
        return "\n".join(lines)

    def update_status(self, status: dict[str, Any]) -> None:
        self.update(self.render_status(status))
