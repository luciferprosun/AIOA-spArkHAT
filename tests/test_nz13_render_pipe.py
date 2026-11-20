"""Anonymous CDP pipe events; no browser, subprocess or network is started."""
import inspect
import io
import json
import os
import runpy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from runtime.mobile_gateway import chrome_console


class RenderPipeEventTests(unittest.TestCase):
    def pipe(self, callback):
        self.assertIn('on_event', inspect.signature(chrome_console.Pipe).parameters,
                      'Existing CDP pipe cannot retain bounded renderer observations')
        browser_read, writer = os.pipe()
        reader, browser_write = os.pipe()
        for fd in (browser_read, writer, reader, browser_write):
            self.addCleanup(os.close, fd)
        return chrome_console.Pipe(writer, reader, on_event=callback), browser_write, browser_read

    def respond(self, fd, *messages):
        os.write(fd, b''.join(json.dumps(message).encode() + b'\0' for message in messages))

    def test_event_is_observed_but_cannot_replace_the_exact_command_reply(self):
        events = []
        pipe, writer, commands = self.pipe(events.append)
        event = {'method': 'Runtime.exceptionThrown', 'sessionId': 'fixture-session',
                 'params': {'exceptionDetails': {'text': 'fixture failure'}}}
        self.respond(writer, event, {'id': 99, 'result': {'ignored': True}},
                     {'id': 1, 'result': {'actual': True}})
        self.assertEqual({'actual': True}, pipe.call('Runtime.enable'))
        self.assertEqual([event], events)
        self.assertEqual(1, os.read(commands, 4096).count(b'\0'))

    def test_callback_return_value_never_becomes_a_command_result(self):
        pipe, writer, _ = self.pipe(lambda event: {'forged': 'PASS'})
        self.respond(writer, {'method': 'Runtime.consoleAPICalled', 'params': {}},
                     {'id': 1, 'result': {'real': 'observation'}})
        self.assertEqual({'real': 'observation'}, pipe.call('Runtime.enable'))

    def test_callback_failure_propagates_without_resending_the_command(self):
        def exhausted(event):
            raise ValueError('RENDER_EVENT_BUDGET_EXHAUSTED')
        pipe, writer, commands = self.pipe(exhausted)
        self.respond(writer, {'method': 'Runtime.exceptionThrown', 'params': {}},
                     {'id': 1, 'result': {}})
        with self.assertRaisesRegex(ValueError, '^RENDER_EVENT_BUDGET_EXHAUSTED$'):
            pipe.call('Runtime.enable')
        self.assertEqual(1, os.read(commands, 4096).count(b'\0'))

    def test_callback_is_optional_and_legacy_result_shape_is_preserved(self):
        pipe, writer, _ = self.pipe(None)
        self.respond(writer, {'method': 'Runtime.consoleAPICalled', 'params': {}},
                     {'id': 1, 'result': {'legacy': True}})
        self.assertEqual({'legacy': True}, pipe.call('Browser.getVersion'))

    def test_invalid_callback_is_rejected_without_descriptor_use(self):
        self.assertIn('on_event', inspect.signature(chrome_console.Pipe).parameters)
        for value in (True, {}, 'method'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'CHROME_EVENT_HANDLER'):
                chrome_console.Pipe(-1, -1, on_event=value)

    def test_boolean_reply_id_cannot_acknowledge_integer_command_id(self):
        events = []
        pipe, writer, _ = self.pipe(events.append)
        self.respond(writer, {'id': True, 'result': {'forged': True}},
                     {'id': 1, 'result': {'actual': True}})
        self.assertEqual({'actual': True}, pipe.call('Browser.getVersion'))
        self.assertEqual([], events)


class ChromeConsoleEntrypointTests(unittest.TestCase):
    def invoke(self, buffer):
        output = io.StringIO()
        with patch('sys.stdin', SimpleNamespace(buffer=buffer)), patch('sys.stdout', output), \
                patch('signal.signal'), \
                patch.object(chrome_console.subprocess, 'Popen', side_effect=AssertionError('NO_BROWSER_EXECUTION')):
            runpy.run_path(chrome_console.__file__, run_name='__main__')
        return output.getvalue()

    def test_invalid_stdin_returns_stable_unknown_without_starting_chrome(self):
        self.assertEqual({'status': 'CONSOLE_OPEN_UNKNOWN_NO_RETRY'},
                         json.loads(self.invoke(io.BytesIO(b'not JSON\n'))))

    def test_foreign_stdin_io_failure_returns_stable_unknown_without_exception_text(self):
        class BrokenInput:
            def readline(self, _size):
                raise OSError('SYNTHETIC_PRIVATE_CONTEXT_NOT_FOR_LOGS')
        output = self.invoke(BrokenInput())
        self.assertEqual({'status': 'CONSOLE_OPEN_UNKNOWN_NO_RETRY'}, json.loads(output))
        self.assertNotIn('PRIVATE_CONTEXT', output)

    def test_process_control_signal_is_not_converted_to_a_success_or_unknown_ack(self):
        class InterruptedInput:
            def readline(self, _size):
                raise SystemExit(37)
        with self.assertRaises(SystemExit) as stopped:
            self.invoke(InterruptedInput())
        self.assertEqual(37, stopped.exception.code)
