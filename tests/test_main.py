import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from tools.browser_tools import (
    browser_click,
    browser_close,
    browser_current_url,
    browser_get_visible_text,
    browser_open,
    browser_press,
    browser_screenshot,
    browser_start,
    browser_type,
    PLAYWRIGHT_AVAILABLE,
)
from tools.executor import ExecutionEngine
from tools.memory import MemoryStore
from tools.system_info import detect_desktop_dir
from tools.validator import classify_shell_command, validate_shell_command
from providers.config import DEFAULT_MODEL, ProviderManager
from providers.aureon_provider import AureonProvider
from commands.local_commands import cmd_scemda


class FakeProvider:
    def __init__(self, outputs: list[str | Exception]) -> None:
        self.outputs = outputs
        self.calls = 0
        self.model_name = "fake/test-model"

    def generate(self, prompt: str) -> str:
        _ = prompt
        output = self.outputs[self.calls]
        self.calls += 1
        if isinstance(output, Exception):
            raise output
        return output

    def describe(self) -> str:
        return self.model_name

    def switch_model(self, model_name: str) -> str:
        self.model_name = model_name
        return model_name


class RuntimeArchitectureTests(unittest.TestCase):
    def test_normalize_external_url_unwraps_facebook_redirect(self) -> None:
        raw = (
            "https://l.facebook.com/l.php?u=https%3A%2F%2Fzenodo.org%2Frecords%2F20038802"
            "%3Ffbclid%3Dabc123&h=XYZ"
        )
        normalized = main.normalize_external_url(raw)
        self.assertEqual(normalized, "https://zenodo.org/records/20038802?fbclid=abc123")

    def test_detect_desktop_dir_uses_xdg_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_dir = home / ".config"
            config_dir.mkdir(parents=True)
            desktop_dir = home / "MojPulpit"
            desktop_dir.mkdir()
            (config_dir / "user-dirs.dirs").write_text(
                'XDG_DESKTOP_DIR="$HOME/MojPulpit"\n',
                encoding="utf-8",
            )
            detected = detect_desktop_dir(home)
            self.assertEqual(detected, desktop_dir)

    def test_validate_shell_command_allows_multi_step_redirection(self) -> None:
        allowed, reason = validate_shell_command('echo "hello" > file.txt && cat file.txt')
        self.assertTrue(allowed)
        self.assertEqual(reason, "OK")

    def test_classify_install_command_requires_confirmation(self) -> None:
        decision = classify_shell_command("sudo apt install curl")
        self.assertEqual(decision.mode, "advanced")
        self.assertTrue(decision.requires_confirmation)
        self.assertTrue(decision.interactive)

    def test_legacy_executor_denies_desktop_folder_without_native_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            desktop_dir = Path(tmp) / "Desktop"
            project_dir.mkdir()
            desktop_dir.mkdir()
            memory = MemoryStore(project_dir, project_dir)
            engine = ExecutionEngine(project_dir, memory)
            result = engine.execute(
                {
                    "action": "create_folder",
                    "path": str(desktop_dir / "AI_TEST"),
                    "reason": "Create desktop folder.",
                }
            )
            self.assertFalse(result["success"])
            self.assertFalse((desktop_dir / "AI_TEST").exists())
            self.assertEqual('UNSUPPORTED_EFFECT_ROUTE',result['error'])

    def test_legacy_executor_denies_folder_and_text_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            desktop_dir = Path(tmp) / "Desktop"
            project_dir.mkdir()
            desktop_dir.mkdir()
            target_file = desktop_dir / "AI_TEST" / "note.txt"
            memory = MemoryStore(project_dir, project_dir)
            engine = ExecutionEngine(project_dir, memory)
            engine.execute(
                {
                    "action": "create_folder",
                    "path": str(target_file.parent),
                    "reason": "Create folder.",
                }
            )
            result = engine.execute(
                {
                    "action": "write_file",
                    "path": str(target_file),
                    "content": "hello from agent\n",
                    "reason": "Write file.",
                }
            )
            self.assertFalse(result["success"])
            self.assertEqual('UNSUPPORTED_EFFECT_ROUTE',result['error'])
            self.assertFalse(target_file.exists())

    def test_runtime_cancels_install_when_user_declines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            provider = FakeProvider(
                [
                    json_text(
                        {
                            "action": "shell_execute",
                            "command": "sudo apt install curl",
                            "reason": "Install curl.",
                            "requires_confirmation": True,
                        }
                    )
                ]
            )
            runtime = main.AgentRuntime(provider, PROMPT_TEMPLATE, project_dir)
            with patch("builtins.input", side_effect=AssertionError('prompt cannot grant authority')):
                runtime.handle_user_request("zainstaluj curl")
            self.assertEqual(provider.calls, 1)
            self.assertTrue(runtime.memory_store.memory.recent_outputs)
            self.assertFalse(runtime.memory_store.memory.recent_outputs[-1]["success"])

    def test_runtime_handles_model_503_after_approved_public_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            desktop_dir = Path(tmp) / "Desktop"
            project_dir.mkdir()
            desktop_dir.mkdir()
            provider = FakeProvider(
                [
                    json_text(
                        {
                            "action": "read_file",
                            "path": "public.txt",
                            "reason": "Read exact approved public fixture.",
                        }
                    ),
                    RuntimeError("503 UNAVAILABLE"),
                    RuntimeError("503 UNAVAILABLE"),
                    RuntimeError("503 UNAVAILABLE"),
                ]
            )
            runtime = main.AgentRuntime(provider, PROMPT_TEMPLATE, project_dir)
            from tools.admission import PublicFileReads
            import hashlib
            public=project_dir/'public.txt';public.write_text('public fixture')
            runtime.executor.public_reads=PublicFileReads(project_dir,
                {'public.txt':hashlib.sha256(public.read_bytes()).hexdigest()})
            with patch("sys.stdout", new_callable=StringIO) as fake_stdout:
                runtime.handle_user_request("read approved public input and summarize")
            self.assertFalse((desktop_dir / "xxxxxxxxxxxx").exists())
            self.assertIn("Część operacji została już wykonana poprawnie", fake_stdout.getvalue())

    @unittest.skipUnless(PLAYWRIGHT_AVAILABLE, "Playwright is not installed")
    def test_bootstrap_local_context_opens_url_before_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_local_site(root)
            project_dir = root / "project"
            project_dir.mkdir()
            provider = FakeProvider([])
            runtime = main.AgentRuntime(provider, PROMPT_TEMPLATE, project_dir)
            local_url = (root / "index.html").as_uri()

            with patch("sys.stdout", new_callable=StringIO):
                trace = runtime.bootstrap_local_context(f"przeanalizuj te prace {local_url}")

            self.assertEqual(provider.calls, 0)
            self.assertEqual(len(trace), 1)
            self.assertEqual(trace[0]["action"]["action"], "browser_start")
            self.assertEqual('UNSUPPORTED_EFFECT_ROUTE', trace[0]['result']['error'])
            browser_close()

    def test_slash_status_uses_no_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            provider = FakeProvider([])
            runtime = main.AgentRuntime(provider, PROMPT_TEMPLATE, project_dir)
            result = runtime.command_registry.execute("/status", runtime)
            self.assertTrue(result.handled)
            self.assertIn("Local runtime status", result.message)
            self.assertEqual(provider.calls, 0)

    def test_local_desktop_folder_route_uses_no_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            desktop_dir = Path(tmp) / "Desktop"
            project_dir.mkdir()
            desktop_dir.mkdir()
            provider = FakeProvider([])
            runtime = main.AgentRuntime(provider, PROMPT_TEMPLATE, project_dir)
            runtime.desktop_dir = desktop_dir
            runtime.local_router.desktop_dir = desktop_dir
            with patch("sys.stdout", new_callable=StringIO):
                runtime.handle_user_request("stworz folder AI_TEST na pulpicie")
            self.assertFalse((desktop_dir / "AI_TEST").exists())
            self.assertEqual(provider.calls, 0)

    def test_plain_help_uses_no_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            provider = FakeProvider([])
            runtime = main.AgentRuntime(provider, PROMPT_TEMPLATE, project_dir)
            with patch("sys.stdout", new_callable=StringIO) as fake_stdout:
                runtime.handle_user_request("help")
            self.assertIn("/status", fake_stdout.getvalue())
            self.assertEqual(provider.calls, 0)

    def test_slash_vault_uses_no_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            provider = FakeProvider([])
            runtime = main.AgentRuntime(provider, PROMPT_TEMPLATE, project_dir)
            result = runtime.command_registry.execute("/vault", runtime)
            self.assertTrue(result.handled)
            self.assertIn("Obsidian vault", result.message)
            self.assertEqual(provider.calls, 0)

    def test_scemda_command_reports_when_zip_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            runtime = main.AgentRuntime(FakeProvider([]), PROMPT_TEMPLATE, project_dir)
            with patch("commands.local_commands.SCEMDA_ZIP", Path(tmp) / "missing.zip"):
                result = cmd_scemda("", runtime)
            self.assertTrue(result.handled)
            self.assertIn("SCEMDA zip not found", result.message)

    def test_memory_store_initializes_obsidian_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            memory = MemoryStore(project_dir, project_dir)
            self.assertTrue(memory.vault_dir.exists())
            self.assertTrue((memory.vault_dir / "00_START_HERE.md").exists())
            self.assertTrue((memory.vault_dir / ".obsidian" / "app.json").exists())

    def test_provider_manager_defaults_to_aureon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            manager = ProviderManager(project_dir)
            self.assertEqual(manager.current_model, DEFAULT_MODEL)

    def test_provider_manager_normalizes_model_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            manager = ProviderManager(project_dir)
            self.assertEqual(manager.normalize_model_name("aureon"), "aureon/aureon-queen")
            self.assertEqual(manager.normalize_model_name("gemini"), "gemini/gemini-2.5-flash")
            self.assertEqual(manager.normalize_model_name("grok"), "xai/grok-4.3")
            self.assertEqual(manager.normalize_model_name("xai"), "xai/grok-4.3")
            self.assertEqual(manager.normalize_model_name("openrouter"), "openrouter/free")
            self.assertEqual(
                manager.normalize_model_name("openai:gpt-4o-mini"),
                "openai/gpt-4o-mini",
            )

    def test_model_command_lists_presets_and_current_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            manager = ProviderManager(project_dir)
            runtime = SimpleNamespace(provider_manager=manager)
            result = main.build_command_registry().execute("/model list", runtime)
            self.assertTrue(result.handled)
            self.assertIn("Current model:", result.message)
            self.assertIn("aureon", result.message)
            self.assertIn("gemini", result.message)

    def test_model_command_switches_alias_to_full_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            manager = ProviderManager(project_dir)
            runtime = SimpleNamespace(provider_manager=manager)
            result = main.build_command_registry().execute("/model aureon", runtime)
            self.assertTrue(result.handled)
            self.assertIn("Model switched to: aureon/aureon-queen", result.message)
            self.assertEqual(manager.current_model, "aureon/aureon-queen")
            self.assertEqual(
                json.loads(manager.config_path.read_text(encoding="utf-8"))["model"],
                "aureon/aureon-queen",
            )

    def test_model_command_switches_gemini_without_instantiating_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            manager = ProviderManager(project_dir)
            runtime = SimpleNamespace(provider_manager=manager)
            result = main.build_command_registry().execute("/model gemini", runtime)
            self.assertTrue(result.handled)
            self.assertIn("Model switched to: gemini/gemini-2.5-flash", result.message)
            self.assertIn("google-genai", result.message)
            self.assertEqual(manager.current_model, "gemini/gemini-2.5-flash")
            self.assertEqual(manager.describe(), "gemini/gemini-2.5-flash")

    def test_model_command_switches_grok_without_instantiating_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            manager = ProviderManager(project_dir)
            runtime = SimpleNamespace(provider_manager=manager)
            result = main.build_command_registry().execute("/model grok", runtime)
            self.assertTrue(result.handled)
            self.assertIn("Model switched to: xai/grok-4.3", result.message)
            self.assertIn("XAI_API_KEY", result.message)
            self.assertEqual(manager.current_model, "xai/grok-4.3")
            self.assertEqual(manager.describe(), "xai/grok-4.3")

    def test_aureon_offline_provider_answers_greeting_normally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ = tmp
            with patch.dict(os.environ, {}, clear=True):
                provider = AureonProvider("aureon-queen")
                reply = provider.generate('{"user_request":"hello are you ai ?"}')
            payload = json.loads(reply)
            self.assertEqual(payload["action"], "respond")
            self.assertIn("lokalnym Aureon", payload["message"])

    @unittest.skipUnless(PLAYWRIGHT_AVAILABLE, "Playwright is not installed")
    def test_browser_open_search_screenshot_visible_text_and_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_local_site(root)
            project_dir = root / "project"
            project_dir.mkdir()
            memory = MemoryStore(project_dir, project_dir)
            _ = ExecutionEngine(project_dir, memory)

            browser_start()
            browser_open((root / "index.html").as_uri())
            browser_type("#query", "OpenAI")
            browser_press("Enter")
            current = browser_current_url()
            self.assertIn("#search=OpenAI", current["current_url"])

            text_result = browser_get_visible_text()
            self.assertIn("Search Results for OpenAI", text_result["text"])

            shot = browser_screenshot("local_search.png")
            self.assertTrue(Path(shot["screenshot_path"]).exists())

            browser_open((root / "index.html").as_uri())
            browser_click("#next-link")
            current = browser_current_url()
            self.assertIn("#clicked", current["current_url"])
            text_result = browser_get_visible_text()
            self.assertIn("Click confirmed", text_result["text"])

            browser_open((root / "page2.html").as_uri())
            current = browser_current_url()
            self.assertIn("page2.html", current["current_url"])
            text_result = browser_get_visible_text()
            self.assertIn("Second Page", text_result["text"])
            browser_close()

    def test_shell_execute_denied_even_for_curl_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            memory = MemoryStore(project_dir, project_dir)
            engine = ExecutionEngine(project_dir, memory)
            result = engine.execute(
                {
                    "action": "shell_execute",
                    "command": "curl --version",
                    "reason": "Check curl version.",
                    "requires_confirmation": False,
                }
            )
            self.assertFalse(result["success"])
            self.assertEqual('UNSUPPORTED_EFFECT_ROUTE',result['error'])
            self.assertNotIn('stdout',result)

    @staticmethod
    def _write_local_site(root: Path) -> None:
        (root / "index.html").write_text(
            """
            <html>
              <body>
                <h1>Local Search</h1>
                <form id="search-form">
                  <input id="query" name="q" type="text" />
                  <button id="submit" type="submit">Search</button>
                </form>
                <div id="result"></div>
                <button id="next-link" type="button">Click Next</button>
                <div id="nav-status"></div>
                <script>
                  const form = document.getElementById("search-form");
                  form.addEventListener("submit", function(event) {
                    event.preventDefault();
                    const q = document.getElementById("query").value;
                    document.getElementById("result").textContent = "Search Results for " + q;
                    window.location.hash = "search=" + encodeURIComponent(q);
                  });
                  document.getElementById("next-link").addEventListener("click", function() {
                    document.getElementById("nav-status").textContent = "Click confirmed";
                    window.location.hash = "clicked";
                  });
                </script>
              </body>
            </html>
            """,
            encoding="utf-8",
        )
        (root / "page2.html").write_text(
            """
            <html>
              <body>
                <h1>Second Page</h1>
                <p>Browser navigation succeeded.</p>
              </body>
            </html>
            """,
            encoding="utf-8",
        )


PROMPT_TEMPLATE = """
You are an autonomous AI runtime agent.
Desktop: __DESKTOP_DIR__
Project: __CURRENT_PROJECT__
cwd: __CURRENT_CWD__
Return one JSON object only.
""".strip()


def json_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
