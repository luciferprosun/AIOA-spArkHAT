"""Default Assistant CLI, expert commands and explicit bypass on one runtime."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from main import create_runtime, main
from tui.assistant import operator_request


class AssistantCLITests(unittest.TestCase):
    def test_optional_tui_adapter_uses_same_default_without_textual_dependency(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict('os.environ', {'AOIA_HOME':temporary}):
            runtime = create_runtime(cpl_fixture=True)
            try:
                with patch.object(runtime, 'run_text_request', side_effect=AssertionError('No hidden bypass')):
                    text = operator_request(runtime, '  Explain RAM.\n')
                self.assertTrue(text.startswith('CPL PLAN — NOT A FINAL ANSWER'))
                run_id = runtime.critical_loop.status()['run_ids'][0]
                view = runtime.critical_loop.get(run_id)
                self.assertEqual(view['plan']['prompt'], '  Explain RAM.\n')
                self.assertEqual(view['execution_status'], 'PLANNED')
                self.assertEqual(runtime._owned_cpl_fixture.requests, [])
                with patch.object(runtime, 'run_text_request', return_value={'transcript':'Explicit bypass'}) as bypass:
                    plain = operator_request(runtime, 'Explain RAM.', plain_chat=True)
                bypass.assert_called_once_with('Explain RAM.')
                self.assertTrue(plain.startswith('PLAIN CHAT — NOT CPL REVIEWED'))
                self.assertIn('Local commands', operator_request(runtime, '/help'))
            finally:
                runtime.close()

    def test_actual_default_cli_question_plans_then_restart_does_not_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = {**os.environ, 'AOIA_HOME':temporary, 'PYTHONDONTWRITEBYTECODE':'1'}
            command = [sys.executable, '-m', 'runtime', '--cpl-fixture']
            result = subprocess.run(command, input='Explain Python recursion in simple terms.\nquit\n',
                env=env, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Critical Prompt Loop — DEFAULT', result.stdout)
            self.assertIn('"execution_status": "PLANNED"', result.stdout)
            self.assertIn('"generation_requests": 0', result.stdout)
            self.assertIn('/cpl start RUN_ID PLAN_HASH NONCE', result.stdout)
            status = subprocess.run(command+['--command','/cpl status'], env=env,
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
            self.assertEqual(status.returncode, 0, status.stderr)
            run_id = json.loads(status.stdout)['run_ids'][0]
            recovered = subprocess.run(command+['--command','/cpl status '+run_id], env=env,
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            view = json.loads(recovered.stdout)
            self.assertEqual(view['execution_status'], 'INTERRUPTED')
            self.assertEqual(view['generation_requests'], 0)
            self.assertIsNone(view['final_answer'])

    def test_interactive_plain_flag_is_explicit_bypass_of_review(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict('os.environ', {'AOIA_HOME':temporary}):
            runtime = create_runtime(cpl_fixture=True)
            with patch('main.create_runtime', return_value=runtime), \
                 patch.object(runtime, 'run_text_request', return_value={'transcript':'Explicit bypass stub', 'status':{}}) as bypass, \
                 patch('sys.argv',['aioa-sparkhat','--cpl-fixture','--plain-chat']), \
                 patch('builtins.input',side_effect=['Explain RAM.','quit']), redirect_stdout(io.StringIO()) as output:
                main()
            bypass.assert_called_once_with('Explain RAM.')
            self.assertIn('CPL BYPASS (not reviewed)', output.getvalue())
            self.assertNotIn('"execution_status": "PLANNED"', output.getvalue())


if __name__ == '__main__':
    unittest.main()
