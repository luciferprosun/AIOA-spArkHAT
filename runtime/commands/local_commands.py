from __future__ import annotations

import shlex
import subprocess
import sys
import zipfile
import json
from pathlib import Path

from .base import CommandRegistry, CommandResult
from evidence_review import bundled_scenario, format_review_summary, review_candidate
from runtime_paths import runtime_state_dir
from retrieval.facade import (
    linux_filter_by_topic,
    linux_library_status,
    linux_load_topic,
    linux_low_level_results,
)
from tools.validator import validate_action

SCEMDA_ZIP = Path.home() / ".local" / "share" / "aoia" / "kimi agetn..zip"


def build_command_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register("help", cmd_help)
    registry.register("status", cmd_status)
    registry.register("model", cmd_model)
    registry.register("vault", cmd_vault)
    registry.register("scemda", cmd_scemda)
    registry.register("tools", cmd_tools)
    registry.register("providers", cmd_providers)
    registry.register("setup", cmd_setup)
    registry.register("hat", cmd_hat)
    registry.register("review", cmd_review)
    registry.register("cpl", cmd_cpl)
    registry.register("scan", cmd_scan)
    registry.register("orchestrator", cmd_orchestrator)
    registry.register("worker", cmd_worker)
    registry.register("rhcsa", cmd_rhcsa)
    return registry


def cmd_help(_args: str, runtime) -> CommandResult:
    _ = runtime
    return CommandResult(
        True,
        "\n".join(
            [
                "Local commands:",
                "  /status          show local runtime state",
                "  /model           show active model and presets",
                "  /model NAME      switch model, e.g. grok or gemini/gemini-2.5-flash",
                "  /vault           show Obsidian vault path",
                "  /providers       show cloud provider fallback status",
                "  /setup           show free API setup checklist",
                "  /hat             list/load/show/clear memory hats",
                "  /review          review the bundled dated-evidence example without a model call",
                "  /review corrected  review the bundled corrected example",
                "  /review TEXT     review supplied text against the bundled dated evidence",
                "  /cpl             Critical Prompt Loop help / plan / start / status / verify",
                "  /cpl fixture     explicit local HTTP 1+3+1 test (requires --cpl-fixture)",
                "  /scan PATH       scan a project tree after ENTER approval",
                "  /orchestrator on|off|status",
                "  /worker status|memory|clear",
                "  /rhcsa status|savings|build|search QUERY|tag TAG|exact COMMAND|grep PATTERN|filter TOPIC QUERY|topic TOPIC|commands QUERY|workflows QUERY|examples QUERY",
                "  /scemda ARGS     run the SCEMDA addon from Gary's zip",
                "  /tools           list registered local tools",
                "  /help            show this help",
                "  exit             quit",
            ]
        ),
    )


def cmd_cpl(args: str, runtime) -> CommandResult:
    """CPL never routes model output through an executor or normal chat."""
    action, _, rest = args.strip().partition(' ')
    if action in {'', 'help', '?'}:
        return CommandResult(True, '\n'.join([
            'AIOA spArkHAT Critical Prompt Loop: advisory 1+3+1, not independent consensus.',
            '/cpl fixture — synthetic HTTP run; start runtime with --cpl-fixture',
            '/cpl plan PROMPT — immutable plan and one-use nonce; live disabled without a cost policy',
            '/cpl plan-json JSON — explicit evidence, models, limits and run_budget_usd',
            '/cpl start RUN_ID PLAN_HASH NONCE — execute exactly the server-held plan',
            '/cpl status [RUN_ID] | /cpl cancel RUN_ID | /cpl verify RUN_ID',
            'No tools, automatic knowledge promotion, retries or fallback.']))
    if action == 'fixture' and not rest:
        result = runtime.run_cpl_fixture()
    elif action == 'plan' and rest:
        result = runtime.plan_critical_loop({'prompt': rest})
    elif action == 'plan-json' and rest:
        from providers.exact import ExactCallError, _unique_object
        try:
            if len(rest.encode()) > 24000:
                raise ValueError()
            payload = json.loads(rest, object_pairs_hook=_unique_object)
        except (ValueError, RecursionError):
            raise ExactCallError('INVALID_PLAN_JSON') from None
        result = runtime.plan_critical_loop(payload)
    elif action == 'start':
        fields = shlex.split(rest)
        if len(fields) != 3:
            return CommandResult(True, 'Usage: /cpl start RUN_ID PLAN_HASH NONCE', 1)
        result = runtime.critical_loop.start(*fields)
        result = runtime.critical_loop.wait(result['run_id'])
    elif action == 'status':
        result = runtime.critical_loop.get(rest) if rest else runtime.critical_loop.status()
    elif action == 'cancel' and rest:
        result = runtime.critical_loop.cancel(rest)
    elif action == 'verify' and rest:
        result = runtime.critical_loop.verify(rest)
    else:
        return CommandResult(True, 'Unknown CPL command. Use /cpl help.', 1)
    failed = ((action in {'fixture', 'start'} and result.get('execution_status') != 'COMPLETED')
              or (action == 'verify' and result.get('ok') is not True))
    return CommandResult(True, json.dumps(result, indent=2, ensure_ascii=False), int(failed))


def cmd_status(_args: str, runtime) -> CommandResult:
    memory = runtime.memory_store.memory
    return CommandResult(
        True,
        "\n".join(
            [
                "Local runtime status:",
                f"  cwd: {memory.cwd}",
                f"  desktop: {runtime.desktop_dir}",
                f"  model: {runtime.provider_manager.describe()}",
                f"  fallback_chain: {', '.join(_fallback_chain(runtime)) or '(empty)'}",
                f"  orchestrator: {'on' if getattr(runtime, 'use_orchestrator', False) else 'off'}",
                f"  active_hat: {_active_hat_name(runtime)}",
                f"  browser_active: {memory.browser_active}",
                f"  current_url: {memory.current_browser_page or '(none)'}",
                "  local URL bootstrap: enabled",
                "  dated evidence review: enabled (deterministic, no provider call)",
            ]
        ),
    )


def cmd_model(args: str, runtime) -> CommandResult:
    text = args.strip()
    if not text or text.lower() in {"help", "list", "?"}:
        lines = [
            f"Current model: {runtime.provider_manager.describe()}",
            "Available presets:",
        ]
        lines.extend(f"  {line}" for line in runtime.provider_manager.available_models())
        lines.extend(
            [
                "Examples:",
                "  /model aureon",
                "  /model gemma",
                "  /model openrouter-gemma",
                "  /model openrouter/google/gemma-3-27b-it",
                "  /model gemini",
                "  /model gemini/gemini-2.5-flash",
                "  /model grok",
                "  /model xai/grok-4.3",
                "  /model deepseek/deepseek-chat",
            ]
        )
        return CommandResult(True, "\n".join(lines))

    try:
        model_name = runtime.provider_manager.switch_model(text)
    except Exception as error:
        return CommandResult(True, f"Could not switch model: {error}")
    notice = runtime.provider_manager.model_notice(model_name)
    if notice:
        return CommandResult(True, f"Model switched to: {model_name}\nNote: {notice}")
    return CommandResult(True, f"Model switched to: {model_name}")


def cmd_tools(_args: str, runtime) -> CommandResult:
    tools = runtime.executor.tool_names()
    return CommandResult(True, "Registered tools:\n  " + "\n  ".join(tools))


def cmd_review(args: str, runtime) -> CommandResult:
    """Run the bounded evidence review without invoking a model provider."""

    _ = runtime
    scenario = bundled_scenario()
    text = args.strip()
    if not text or text.lower() in {"bundled", "example", "stale"}:
        candidate = str(scenario["candidate_answer"])
    elif text.lower() == "corrected":
        candidate = str(scenario["corrected_example"])
    else:
        candidate = text
    return CommandResult(True, format_review_summary(review_candidate(candidate)))


def cmd_vault(_args: str, runtime) -> CommandResult:
    return CommandResult(True, f"Obsidian vault: {runtime.memory_store.vault_dir}")


def cmd_providers(_args: str, runtime) -> CommandResult:
    lines = ["Cloud provider fallback status:"]
    for row in runtime.provider_manager.provider_status():
        status = "ready" if row["available"] else "missing key/backend"
        enabled = "enabled" if row["enabled"] else "disabled"
        lines.append(f"  {row['full_name']} [{enabled}, {status}]")
    return CommandResult(True, "\n".join(lines))


def cmd_setup(_args: str, runtime) -> CommandResult:
    lines = [
        "Free API setup checklist:",
        "  Secrets must stay outside the repository and must not be committed or printed.",
        "  Create private secrets directory:",
        "    mkdir -p ~/.config/aoia/secrets",
        "    chmod 700 ~/.config/aoia/secrets",
        "  OpenRouter Gemma: set OPENROUTER_API_KEY in your environment or private ~/.config/aoia/secrets/openrouter.env",
        "  Gemini: set GEMINI_API_KEY in your environment or private ~/.config/aoia/secrets/gemini.env",
        "  Grok/xAI: set XAI_API_KEY in your environment or private ~/.config/aoia/secrets/xai.env. Do not commit API keys.",
        "  DeepSeek: set DEEPSEEK_API_KEY in your environment or private ~/.config/aoia/secrets/deepseek.env",
        "  Example private file format only: XAI_API_KEY=your_key_here",
        "  Removed from this terminal app: Ollama/local Gemma and HuggingFace.",
        "",
        "Current provider status:",
    ]
    for row in runtime.provider_manager.provider_status():
        status = "ready" if row["available"] else "missing"
        lines.append(f"  {row['full_name']}: {status}")
    return CommandResult(True, "\n".join(lines))


def cmd_hat(args: str, runtime) -> CommandResult:
    parts = args.strip().split(maxsplit=2)
    if not parts or parts[0] in {"list", "ls"}:
        active = _active_hat_name(runtime)
        lines = [f"Active memory hat: {active}", "Available memory hats:"]
        for hat in runtime.hat_store.list_hats():
            marker = "*" if hat.name == active else "-"
            lines.append(f"  {marker} {hat.name}: {hat.role}")
        return CommandResult(True, "\n".join(lines))

    command = parts[0]
    if command == "show":
        hat = runtime.hat_store.active_hat()
        if hat is None:
            return CommandResult(True, "No active memory hat.")
        return CommandResult(
            True,
            "\n".join(
                [
                    f"name: {hat.name}",
                    f"role: {hat.role}",
                    f"project_path: {hat.project_path or '(none)'}",
                    "instructions:",
                    hat.instructions,
                ]
            ),
        )

    if command == "clear":
        runtime.hat_store.clear_active()
        return CommandResult(True, "Active memory hat cleared.")

    if command == "load" and len(parts) >= 2:
        try:
            hat = runtime.hat_store.load_hat(parts[1])
        except Exception as error:
            return CommandResult(True, f"Could not load memory hat: {error}")
        return CommandResult(True, f"Loaded memory hat: {hat.name} ({hat.role})")

    if command == "save" and len(parts) >= 3:
        name = parts[1]
        instructions = parts[2]
        hat = runtime.hat_store.save_hat(
            name=name,
            role="custom",
            instructions=instructions,
            project_path=runtime.memory_store.memory.cwd,
        )
        return CommandResult(True, f"Saved memory hat: {hat.name}")

    return CommandResult(
        True,
        "Usage: /hat list | /hat load NAME | /hat show | /hat clear | /hat save NAME INSTRUCTIONS",
    )


def cmd_scan(args: str, runtime) -> CommandResult:
    path = args.strip() or runtime.memory_store.memory.cwd
    action = validate_action(
        {
            "action": "scan_project",
            "path": path,
            "reason": "Operator requested project scan.",
        }
    )
    result = runtime.executor.execute(action)
    if result.get("cancelled"):
        return CommandResult(True, "Project scan cancelled.")
    report = result.get("project_scan", {})
    lines = [
        result.get("message", "Project scan complete."),
        f"Report: {result.get('scan_report_path') or '(not written)'}",
        f"Summary: {report.get('architecture_summary', '(none)')}",
    ]
    entrypoints = report.get("entrypoints", [])
    if entrypoints:
        lines.append("Entrypoints: " + ", ".join(entrypoints[:12]))
    return CommandResult(True, "\n".join(lines))


def cmd_orchestrator(args: str, runtime) -> CommandResult:
    text = args.strip().lower()
    if text in {"on", "enable", "1", "true"}:
        runtime.enable_orchestrator(False)
        return CommandResult(
            True,
            "Orchestrator worker is disabled. Gemma/Ollama/HuggingFace were removed from this terminal app.",
        )
    if text in {"off", "disable", "0", "false"}:
        runtime.enable_orchestrator(False)
        return CommandResult(True, "Gemini -> Gemma orchestrator disabled.")
    return CommandResult(
        True,
        "\n".join(
            [
                f"orchestrator: {'on' if getattr(runtime, 'use_orchestrator', False) else 'off'}",
                "workflow: disabled because Gemma/Ollama/HuggingFace are removed from this terminal build",
            ]
        ),
    )


def cmd_worker(args: str, runtime) -> CommandResult:
    text = args.strip().lower() or "status"
    if text == "clear":
        runtime.worker_memory.clear_worker_memory()
        return CommandResult(True, "Gemma worker memory cleared.")

    state = runtime.worker_memory.summarize_worker_state()
    if text == "memory":
        return CommandResult(True, json_dump(state))
    if text == "status":
        stats = state.get("token_saving_stats", {})
        lines = [
            "Gemma worker status:",
            f"  active_task: {state.get('active_task') or '(none)'}",
            f"  delegated_steps: {stats.get('delegated_steps', 0)}",
            f"  gemini_planner_calls: {stats.get('gemini_planner_calls', 0)}",
            f"  gemma_worker_calls: {stats.get('gemma_worker_calls', 0)}",
            f"  command_patterns: {len(state.get('command_patterns', []))}",
        ]
        return CommandResult(True, "\n".join(lines))
    return CommandResult(True, "Usage: /worker status | /worker memory | /worker clear")


def cmd_rhcsa(args: str, runtime) -> CommandResult:
    parts = args.strip().split(maxsplit=1)
    command = parts[0].lower() if parts else "status"
    query = parts[1] if len(parts) > 1 else ""

    if command == "status":
        status = linux_library_status()
        lines = [
            "RHCSA local library status:",
            f"  path: {status['path']}",
            f"  exists: {status['exists']}",
            f"  files: {status['files']}",
            f"  indexed_topics: {status['indexed_topics']}",
            f"  indexed_command_names: {status['indexed_command_names']}",
            f"  indexed_command_examples: {status['indexed_command_examples']}",
            f"  indexed_workflows: {status.get('indexed_workflows', 0)}",
            f"  indexed_examples: {status.get('indexed_examples', 0)}",
            f"  size_bytes: {status['size_bytes']}",
        ]
        return CommandResult(True, "\n".join(lines))

    if command == "savings":
        report_path = getattr(getattr(runtime, "knowledge_router", None), "report_path", None)
        if report_path is None:
            report_path = runtime_state_dir(runtime.project_dir) / "state" / "token_savings_report.json"
        if not report_path.exists():
            return CommandResult(True, "No token savings report yet.")
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return CommandResult(True, f"Token savings report is invalid: {report_path}")
        return CommandResult(True, json_dump(payload))

    if command == "build":
        answer = input("Press ENTER to build/update the RHCSA library, or type n/cancel to reject: ").strip().lower()
        if answer in {"n", "no", "cancel", "reject", "stop"}:
            return CommandResult(True, "RHCSA library build cancelled.")
        from tools.build_rhcsa_library import build_library

        root = build_library()
        return CommandResult(True, f"RHCSA library built at: {root}")

    if command == "search":
        if not query:
            return CommandResult(True, "Usage: /rhcsa search QUERY")
        results = linux_low_level_results("search", query, limit=8)
        return CommandResult(True, format_rhcsa_results(results))

    if command == "tag":
        if not query:
            return CommandResult(True, "Usage: /rhcsa tag TAG")
        results = linux_low_level_results("tag", query, limit=8)
        return CommandResult(True, format_rhcsa_results(results))

    if command == "exact":
        if not query:
            return CommandResult(True, "Usage: /rhcsa exact COMMAND")
        results = linux_low_level_results("exact", query, limit=8)
        return CommandResult(True, format_rhcsa_results(results))

    if command == "grep":
        if not query:
            return CommandResult(True, "Usage: /rhcsa grep PATTERN")
        results = linux_low_level_results("grep", query, limit=8)
        return CommandResult(True, format_rhcsa_results(results))

    if command == "filter":
        if not query or " " not in query.strip():
            return CommandResult(True, "Usage: /rhcsa filter TOPIC QUERY")
        topic_name, filtered_query = query.strip().split(maxsplit=1)
        results = linux_filter_by_topic(topic_name, filtered_query, limit=8)
        return CommandResult(True, format_rhcsa_results(results))

    if command == "topic":
        if not query:
            return CommandResult(True, "Usage: /rhcsa topic TOPIC")
        return CommandResult(True, linux_load_topic(query) or "RHCSA topic not found.")

    if command == "commands":
        suggestions = linux_low_level_results("commands", query, limit=20)
        if not suggestions:
            return CommandResult(True, "No RHCSA command suggestions found.")
        lines = ["RHCSA command suggestions:"]
        for item in suggestions:
            lines.append(f"  {item['command']} [{item['topic']}]")
        return CommandResult(True, "\n".join(lines))

    if command == "workflows":
        workflows = linux_low_level_results("workflows", query, limit=10)
        if not workflows:
            return CommandResult(True, "No RHCSA workflows found.")
        lines = ["RHCSA workflow results:"]
        for item in workflows:
            lines.append(f"  {item['topic']}: {item.get('summary', '')}")
            lines.append(f"    file: {item.get('source_file', item.get('file_location', ''))}")
        return CommandResult(True, "\n".join(lines))

    if command == "examples":
        examples = linux_low_level_results("examples", query, limit=10)
        if not examples:
            return CommandResult(True, "No RHCSA examples found.")
        lines = ["RHCSA example results:"]
        for item in examples:
            lines.append(f"  {item['topic']}: {item.get('summary', '')}")
            lines.append(f"    file: {item.get('source_file', item.get('file_location', ''))}")
        return CommandResult(True, "\n".join(lines))

    return CommandResult(
        True,
        "Usage: /rhcsa status | /rhcsa savings | /rhcsa build | /rhcsa search QUERY | /rhcsa tag TAG | /rhcsa exact COMMAND | /rhcsa grep PATTERN | /rhcsa filter TOPIC QUERY | /rhcsa topic TOPIC | /rhcsa commands QUERY | /rhcsa workflows QUERY | /rhcsa examples QUERY",
    )


def cmd_scemda(args: str, runtime) -> CommandResult:
    addon_dir = runtime.project_dir / "addons" / "scemda"
    script_path = addon_dir / "scemda_aureon_agent_v2.py"
    extracted = ensure_scemda_addon(addon_dir)

    if not script_path.exists():
        if not SCEMDA_ZIP.exists():
            return CommandResult(
                True,
                f"SCEMDA zip not found at {SCEMDA_ZIP}. Place Gary's zip there first.",
            )
        return CommandResult(True, f"SCEMDA addon prepared at {addon_dir}, but launcher script is missing.")

    if not args.strip():
        return CommandResult(
            True,
            "\n".join(
                [
                    f"SCEMDA addon ready at: {addon_dir}",
                    f"Source zip: {SCEMDA_ZIP}",
                    "Run example:",
                    "  /scemda --start 2026-01-01 --end 2026-05-18 --out ./scemda_run --nulls 2000",
                    f"Extracted files: {len(extracted)}",
                ]
            ),
        )

    answer = input("Press ENTER to run SCEMDA, or type n/cancel to reject: ").strip().lower()
    if answer in {"n", "no", "cancel", "reject", "stop"}:
        return CommandResult(True, "SCEMDA run cancelled.")

    command = [sys.executable, str(script_path), *shlex.split(args)]
    result = subprocess.run(
        command,
        cwd=str(runtime.project_dir),
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(
        [
            f"Exit code: {result.returncode}",
            result.stdout.strip() or "(no stdout)",
            result.stderr.strip() or "(no stderr)",
        ]
    ).strip()
    return CommandResult(True, output)


def _active_hat_name(runtime) -> str:
    hat = runtime.hat_store.active_hat()
    return hat.name if hat else "(none)"


def _fallback_chain(runtime) -> list[str]:
    method = getattr(runtime.provider_manager, "active_fallback_chain", None)
    if callable(method):
        return method()
    return []


def json_dump(payload) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=False)


def format_rhcsa_results(results: list[dict]) -> str:
    if not results:
        return "No RHCSA results found."
    lines = ["RHCSA search results:"]
    for result in results:
        lines.append(f"  {result['topic']} [{result['category']}]")
        lines.append(f"    file: {result['file_location']}")
        if result.get("tags"):
            lines.append(f"    tags: {', '.join(result['tags'][:10])}")
        if result.get("related_commands"):
            lines.append(f"    commands: {', '.join(result['related_commands'][:8])}")
        if result.get("summary"):
            lines.append(f"    summary: {result['summary']}")
        if result.get("preview"):
            lines.append(f"    preview: {result['preview']}")
    return "\n".join(lines)


def ensure_scemda_addon(addon_dir: Path) -> list[str]:
    addon_dir.mkdir(parents=True, exist_ok=True)
    if not SCEMDA_ZIP.exists():
        return []

    extracted: list[str] = []
    wanted = {
        "README_SCEMDA_v2.md",
        "scemda_aureon_agent_v2.py",
        "scemda_comprehensive_validation.py",
        "scemda_full_validation.py",
        "scemda_open_data_fetcher.py",
    }
    with zipfile.ZipFile(SCEMDA_ZIP) as archive:
        for member in archive.namelist():
            if member not in wanted:
                continue
            target = addon_dir / Path(member).name
            with archive.open(member) as source, target.open("wb") as dest:
                dest.write(source.read())
            extracted.append(target.name)
    return extracted
