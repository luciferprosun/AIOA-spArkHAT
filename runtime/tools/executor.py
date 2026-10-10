from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .browser_tools import (
    browser_click,
    browser_close,
    browser_current_url,
    browser_get_visible_text,
    browser_open,
    browser_press,
    browser_read_html,
    browser_screenshot,
    browser_start,
    browser_type,
    configure_browser_bridge,
)
from .filesystem_tools import (
    append_file,
    create_file,
    create_folder,
    delete_file,
    move_file,
    read_file,
    resolve_path,
    search_in_project,
    write_file,
)
from .memory import MemoryStore
from .admission import PublicFileReads, ReadDenied
from .project_scanner import scan_project
from .shell_tools import shell_execute
from .validator import classify_shell_command, validate_shell_command


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    """Runtime tool metadata used by the executor registry."""

    name: str
    handler: ToolHandler
    description: str


class ExecutionEngine:
    """Dispatch structured tool actions to shell, filesystem, or browser."""

    def __init__(self, project_dir: Path, memory_store: MemoryStore, *, readable_files=None) -> None:
        self.public_reads = PublicFileReads(project_dir, readable_files)
        self.last_result = None
        self.project_dir = project_dir
        self.memory_store = memory_store
        self.cwd = Path(memory_store.memory.cwd)
        self.command_log_dir = memory_store.paths.command_logs_dir
        configure_browser_bridge(
            user_data_dir=memory_store.paths.state_dir / "browser_profile",
            screenshots_dir=memory_store.paths.screenshots_dir,
            headless=True,
        )
        self.tools = self._build_tool_registry()

    def tool_names(self) -> list[str]:
        return sorted(self.tools)

    def execute(self, action: dict[str, Any], require_approval: bool = True) -> dict[str, Any]:
        """Execute one validated JSON action."""
        name = action["action"]
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError(f"Unhandled action: {name}")

        # A legacy prompt/confirmation flag cannot mint native Core effect authority.
        # Host tools remain unsupported until a reviewed contained target adapter exists.
        if name in {'read_file', 'search_in_project'}:
            try:
                result = self.public_reads.execute(action)
            except ReadDenied as error:
                result = {'success': False, 'cancelled': True, 'error': str(error),
                          'effect_status': 'DENIED', 'message': str(error)}
        elif name == 'respond':
            result = tool.handler(action)
        else:
            result = {'success': False, 'cancelled': True, 'error': 'UNSUPPORTED_EFFECT_ROUTE',
                      'effect_status': 'UNSUPPORTED',
                      'message': 'UNSUPPORTED_EFFECT_ROUTE: native authority and containment required.'}
        self.last_result = result
        # Denied arguments may contain private text; do not persist them in a legacy log.
        self._record_execution(action if result.get('success') else {'action': name}, result)
        return result

    def _build_tool_registry(self) -> dict[str, ToolSpec]:
        return {
            "respond": ToolSpec("respond", self._respond, "Return a final answer."),
            "shell_execute": ToolSpec("shell_execute", self._execute_shell_action, "Run a validated shell command."),
            "write_file": ToolSpec("write_file", lambda action: write_file(action["path"], action["content"], self.cwd), "Write a text file."),
            "append_file": ToolSpec("append_file", lambda action: append_file(action["path"], action["content"], self.cwd), "Append to a text file."),
            "read_file": ToolSpec("read_file", lambda action: read_file(action["path"], self.cwd), "Read a text file."),
            "create_file": ToolSpec("create_file", lambda action: create_file(action["path"], self.cwd, action["content"]), "Create a file."),
            "create_folder": ToolSpec("create_folder", lambda action: create_folder(action["path"], self.cwd), "Create a folder."),
            "move_file": ToolSpec("move_file", lambda action: move_file(action["src"], action["dst"], self.cwd), "Move a file or folder."),
            "delete_file": ToolSpec("delete_file", lambda action: delete_file(action["path"], self.cwd), "Delete a file or empty folder."),
            "search_in_project": ToolSpec("search_in_project", lambda action: search_in_project(action["pattern"], action["path"], self.cwd), "Search text in project files."),
            "change_directory": ToolSpec("change_directory", lambda action: self._change_directory(action["path"]), "Change runtime directory."),
            "browser_start": ToolSpec("browser_start", lambda action: browser_start(), "Start browser session."),
            "browser_open": ToolSpec("browser_open", lambda action: browser_open(action["url"]), "Open a URL."),
            "browser_click": ToolSpec("browser_click", lambda action: browser_click(action["selector"]), "Click an element."),
            "browser_type": ToolSpec("browser_type", lambda action: browser_type(action["selector"], action["text"]), "Type into an element."),
            "browser_press": ToolSpec("browser_press", lambda action: browser_press(action["key"]), "Press a key."),
            "browser_read_html": ToolSpec("browser_read_html", lambda action: browser_read_html(), "Read current page HTML."),
            "browser_get_visible_text": ToolSpec("browser_get_visible_text", lambda action: browser_get_visible_text(), "Read visible page text."),
            "browser_screenshot": ToolSpec("browser_screenshot", lambda action: browser_screenshot(action.get("path") or None), "Save browser screenshot."),
            "browser_close": ToolSpec("browser_close", lambda action: browser_close(), "Close browser session."),
            "browser_current_url": ToolSpec("browser_current_url", lambda action: browser_current_url(), "Read current browser URL."),
            "scan_project": ToolSpec("scan_project", lambda action: scan_project(action["path"], self.cwd), "Scan a repository or project tree."),
        }

    @staticmethod
    def _respond(action: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "message": action["message"],
            "confidence_label": action.get("confidence_label", "unknown"),
            "stop_loop": True,
        }

    def _execute_shell_action(self, action: dict[str, Any]) -> dict[str, Any]:
        command = action["command"]
        allowed, reason = validate_shell_command(command)
        if not allowed:
            return {
                "success": False,
                "command": command,
                "message": f"Command blocked by validator: {reason}",
            }

        permission = classify_shell_command(command)
        if permission.interactive:
            print("[INFO] Interactive command may ask for password or package confirmation.")

        self.memory_store.record_command(command)
        return {
            **shell_execute(command, self.cwd, interactive=permission.interactive),
            "permission_mode": permission.mode,
            "permission_reason": permission.reason,
        }

    def _request_approval(self, action: dict[str, Any]) -> bool:
        print("\nPROPOSED ACTION")
        print(f"Action: {action['action']}")
        if action.get("reason"):
            print(f"Reason: {action['reason']}")
        for field in ("command", "path", "src", "dst", "url", "selector", "key"):
            if field in action and action[field]:
                print(f"{field}: {action[field]}")
        answer = input("Press ENTER to approve, or type n/cancel to reject: ").strip().lower()
        return answer not in {"n", "no", "cancel", "reject", "stop"}

    def _change_directory(self, path_text: str) -> dict:
        target = resolve_path(path_text, self.cwd)
        if not target.exists() or not target.is_dir():
            return {
                "success": False,
                "path": str(target),
                "message": f"Directory does not exist: {target}",
            }
        self.cwd = target
        self.memory_store.update_cwd(target)
        return {
            "success": True,
            "path": str(target),
            "message": f"Current directory changed to {target}",
        }

    def _record_execution(self, action: dict[str, Any], result: dict[str, Any]) -> None:
        payload = {
            "timestamp": dt.datetime.now().isoformat(),
            "authority": {
                "classification": "operational_event",
                "retention": "replay_only",
                "non_authoritative": True,
                "canonical_evidence": False,
            },
            "action": action,
            "result": result,
            "cwd": str(self.cwd),
        }
        filename = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f.json")
        (self.command_log_dir / filename).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.memory_store.record_result(result)
        self.memory_store.append_history("action_result", payload)
        # AOIA Phase 2A containment boundary
        # Runtime operational outputs must NEVER become canonical evidence.
        if action["action"].startswith("browser_"):
            self.memory_store.append_browser_event(payload)
