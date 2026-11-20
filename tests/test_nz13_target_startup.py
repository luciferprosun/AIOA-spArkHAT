"""Real owned-child readiness failures must remain bounded and private."""
import fcntl
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nv09_support

_REAL_POPEN = subprocess.Popen
_PREAMBLE = (
    'import json,os,sys,time\n'
    'config=json.loads(sys.stdin.buffer.readline())\n'
)


class TargetStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.children = []
        self.launches = 0

    def tearDown(self):
        for process in self.children:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        self.temp.cleanup()

    def factory(self, script):
        def spawn(argv, **kwargs):
            self.launches += 1
            self.assertEqual([sys.executable, '-B', '-m', 'runtime.service_guard.target'], argv)
            process = _REAL_POPEN([sys.executable, '-I', '-B', '-c', _PREAMBLE + script], **kwargs)
            # Before config is written, make stderr backpressure deterministic.
            fcntl.fcntl(process.stderr.fileno(), fcntl.F_SETPIPE_SZ, 4096)
            self.children.append(process)
            return process
        return spawn

    def reject(self, script, code):
        with (
            patch.object(nv09_support.subprocess, 'Popen', self.factory(script)),
            self.assertRaises(Exception) as captured,
        ):
            nv09_support.LocalTarget(self.root / 'target', target_id='startup-fixture')
        self.assertIs(type(captured.exception), AssertionError)
        self.assertEqual(code, str(captured.exception))
        self.assertEqual(1, self.launches)
        self.assertEqual(1, len(self.children))
        self.assertIsNotNone(self.children[0].poll(), 'constructor failure leaked its owned child')
        self.assertTrue(self.children[0].stdout.closed)
        self.assertTrue(self.children[0].stderr.closed)
        self.assertFalse((self.root / 'target').exists(), 'invalid READY initialized target state')

    def test_wrong_target_id_is_rejected_before_state_and_child_is_reaped(self):
        self.reject(
            "print(json.dumps({'port':12345,'target_id':'different-target'}),flush=True)\n"
            'time.sleep(30)\n', 'LOCAL_TARGET_READY_INVALID')

    def test_unknown_ready_fields_are_rejected(self):
        self.reject(
            "print(json.dumps({'port':12345,'target_id':config['target_id'],'extra':True}),flush=True)\n"
            'time.sleep(30)\n', 'LOCAL_TARGET_READY_INVALID')

    def test_duplicate_ready_fields_are_rejected(self):
        self.reject(
            "print('{\"port\":12344,\"port\":12345,\"target_id\":\"startup-fixture\"}',flush=True)\n"
            'time.sleep(30)\n', 'LOCAL_TARGET_READY_INVALID')

    def test_boolean_port_is_rejected_and_child_is_reaped(self):
        self.reject(
            "print(json.dumps({'port':True,'target_id':config['target_id']}),flush=True)\n"
            'time.sleep(30)\n', 'LOCAL_TARGET_READY_INVALID')

    def test_invalid_json_is_private_and_child_is_reaped(self):
        self.reject("print('private fixture non-json',flush=True)\ntime.sleep(30)\n",
                    'LOCAL_TARGET_READY_INVALID')

    def test_ready_without_newline_is_not_accepted_at_eof(self):
        self.reject(
            "sys.stdout.write(json.dumps({'port':12345,'target_id':config['target_id']}))\n"
            'sys.stdout.flush()\nos.close(1)\ntime.sleep(30)\n',
            'LOCAL_TARGET_READY_EOF')

    def test_early_exit_does_not_echo_private_stderr(self):
        self.reject("sys.stderr.write('fixture-private-startup-material')\nsys.exit(17)\n",
                    'LOCAL_TARGET_READY_EOF')
        self.assertEqual(17, self.children[0].returncode)

    def test_long_ready_frame_is_rejected_before_json_or_state(self):
        self.reject(
            "print(' '*2048+json.dumps({'port':12345,'target_id':config['target_id']}),flush=True)\n"
            'time.sleep(30)\n', 'LOCAL_TARGET_READY_LIMIT')

    def test_stderr_is_drained_before_ready_without_retry(self):
        script = (
            "sys.stderr.buffer.write(b'x'*24576)\nsys.stderr.buffer.flush()\n"
            "print(json.dumps({'port':12345,'target_id':config['target_id']}),flush=True)\n"
            'time.sleep(30)\n'
        )
        with patch.object(nv09_support.subprocess, 'Popen', self.factory(script)):
            target = nv09_support.LocalTarget(self.root / 'target', target_id='startup-fixture')
        try:
            self.assertEqual(12345, target.port)
            self.assertEqual(1, self.launches)
        finally:
            target.close()
        self.assertIsNotNone(self.children[0].poll())

    def test_stderr_overflow_fails_closed_and_reaps_child(self):
        self.reject("sys.stderr.buffer.write(b'x'*40000)\nsys.stderr.buffer.flush()\ntime.sleep(30)\n",
                    'LOCAL_TARGET_STARTUP_STDERR_LIMIT')

    def test_genuine_readiness_timeout_has_no_relaunch_or_state(self):
        self.reject('time.sleep(30)\n', 'LOCAL_TARGET_READY_TIMEOUT')

    def test_deep_json_is_a_constant_error_and_reaps_child(self):
        self.reject("print('['*1000,flush=True)\ntime.sleep(30)\n",
                    'LOCAL_TARGET_READY_INVALID')

    def test_partial_ready_with_open_stdout_times_out_and_reaps_child(self):
        self.reject("sys.stdout.write('{\"port\":12345')\nsys.stdout.flush()\ntime.sleep(30)\n",
                    'LOCAL_TARGET_READY_TIMEOUT')

    def test_existing_ten_second_budget_is_preserved(self):
        self.assertEqual(10, getattr(nv09_support, '_TARGET_READY_SECONDS', 10))


if __name__ == '__main__':
    unittest.main()
