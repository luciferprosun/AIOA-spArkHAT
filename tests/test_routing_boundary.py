import tempfile
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main


PROMPT_TEMPLATE = """
You are an autonomous AI runtime agent.
Desktop: __DESKTOP_DIR__
Project: __CURRENT_PROJECT__
cwd: __CURRENT_CWD__
Return one JSON object only.
""".strip()


class FakeProvider:
    model_name = "fake/test-model"

    def describe(self) -> str:
        return self.model_name

    def active_fallback_chain(self) -> list[str]:
        return []

    def provider_status(self) -> list[dict]:
        return []

    def generate(self, prompt: str) -> str:
        _ = prompt
        return '{"plan":[{"action":"respond","message":"normal runtime response","reason":"test"}]}'


class RaisingKernel:
    def evaluate(self, user_request: str):
        raise AssertionError(f"RHCSA kernel must not receive external request: {user_request}")


class RecordingKernel:
    def __init__(self) -> None:
        self.called = False

    def evaluate(self, user_request: str):
        self.called = True
        return SimpleNamespace(
            should_respond_locally=True,
            route="local_knowledge",
            depth="shallow",
            pressure=34,
            confidence="medium",
            response="Local RHCSA route preserved.",
            manual_review_required=False,
            manual_review_reasons=(),
            evidence=(),
            reasoning={"query": user_request, "route": "local_knowledge"},
        )


class RecordingExecutor:
    def __init__(self) -> None:
        self.actions: list[dict] = []

    def execute(self, action: dict, require_approval: bool = True):
        _ = require_approval
        self.actions.append(action)
        if action["action"] == "browser_open":
            return {
                "success": True,
                "message": f"Opened {action['url']}",
                "current_url": action["url"],
                "open_tabs": [action["url"]],
            }
        if action["action"] == "browser_get_visible_text":
            return {
                "success": True,
                "message": "Read visible page text.",
                "text": "GitHub page text",
            }
        raise AssertionError(f"Unexpected action: {action}")


class RoutingBoundaryTests(unittest.TestCase):
    def test_model_question_is_not_external_review(self) -> None:
        self.assertIsNone(main.classify_external_review_request("jakim jestes modelem"))

    def test_model_question_uses_normal_runtime_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            runtime = main.AgentRuntime(FakeProvider(), PROMPT_TEMPLATE, project_dir)
            runtime.safeguards = main.EpistemicSafeguards(
                kill_switch=False,
                disable_model=False,
                disable_knowledge=True,
                disable_memory_hats=True,
                reasoning_trace_enabled=False,
                prefer_unknown=True,
            )

            with patch("sys.stdout", new_callable=StringIO) as fake_stdout:
                runtime.handle_user_request("jakim jestes modelem")

            self.assertIn("normal runtime response", fake_stdout.getvalue())

    def test_github_url_does_not_trigger_rhcsa_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            runtime = main.AgentRuntime(FakeProvider(), PROMPT_TEMPLATE, project_dir)
            executor = RecordingExecutor()
            runtime.executor = executor
            runtime.aoia_kernel = RaisingKernel()

            with patch("sys.stdout", new_callable=StringIO) as fake_stdout:
                runtime.handle_user_request("https://github.com/luciferprosun/AOIA-Core")

            transcript = fake_stdout.getvalue()
            self.assertEqual([action["action"] for action in executor.actions], ["browser_open", "browser_get_visible_text"])
            self.assertIn("Opened https://github.com/luciferprosun/AOIA-Core", transcript)
            self.assertIn("Current URL: https://github.com/luciferprosun/AOIA-Core", transcript)
            self.assertIn("GitHub page text", transcript)
            self.assertNotIn("AOIA deterministic epistemic kernel hit", transcript)

    def test_repository_intent_does_not_trigger_rhcsa_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            runtime = main.AgentRuntime(FakeProvider(), PROMPT_TEMPLATE, project_dir)
            runtime.aoia_kernel = RaisingKernel()

            with patch.object(runtime.executor, "execute", wraps=runtime.executor.execute) as execute, \
                    patch.object(runtime.provider_manager, "generate", wraps=runtime.provider_manager.generate) as generate:
                result = runtime.run_text_request("can you check github repository")

            transcript = result["transcript"]
            self.assertFalse(result["ok"])
            self.assertEqual("UNSUPPORTED_EFFECT_ROUTE", result["error"])
            self.assertEqual("UNSUPPORTED", result["effect_status"])
            self.assertIn("UNSUPPORTED_EFFECT_ROUTE", transcript)
            self.assertNotIn("Browser inspection path available", transcript)
            self.assertNotIn("AOIA deterministic epistemic kernel hit", transcript)
            execute.assert_not_called()
            generate.assert_not_called()

    def test_repository_inspection_intent_does_not_trigger_rhcsa_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            runtime = main.AgentRuntime(FakeProvider(), PROMPT_TEMPLATE, project_dir)
            runtime.aoia_kernel = RaisingKernel()

            with patch.object(runtime.executor, "execute", wraps=runtime.executor.execute) as execute, \
                    patch.object(runtime.provider_manager, "generate", wraps=runtime.provider_manager.generate) as generate:
                result = runtime.run_text_request("can you inspect github repository")

            transcript = result["transcript"]
            self.assertFalse(result["ok"])
            self.assertEqual("UNSUPPORTED_EFFECT_ROUTE", result["error"])
            self.assertEqual("UNSUPPORTED", result["effect_status"])
            self.assertIn("UNSUPPORTED_EFFECT_ROUTE", transcript)
            self.assertNotIn("Browser inspection path available", transcript)
            self.assertNotIn("AOIA deterministic epistemic kernel hit", transcript)
            execute.assert_not_called()
            generate.assert_not_called()

    def test_linux_request_still_uses_rhcsa_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            runtime = main.AgentRuntime(FakeProvider(), PROMPT_TEMPLATE, project_dir)
            kernel = RecordingKernel()
            runtime.aoia_kernel = kernel

            with patch("sys.stdout", new_callable=StringIO) as fake_stdout:
                runtime.handle_user_request("how to create folder in linux")

            self.assertTrue(kernel.called)
            self.assertIn("Local RHCSA route preserved.", fake_stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
