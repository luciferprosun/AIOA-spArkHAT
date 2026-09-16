"""Completion and transport cleanup share one finite CPL wait budget."""
import threading
import unittest
from unittest.mock import Mock, patch

from critical_loop.service import CriticalPromptLoopService, _Run
from providers.exact import ExactCallError


class CPLWaitContractTests(unittest.TestCase):
    def setUp(self):
        # No provider or filesystem is needed to exercise the real wait contract.
        self.run_id = "cpl-" + "a" * 32
        self.run = _Run(None, {"run_id": self.run_id, "execution_status": "COMPLETED"})
        self.service = object.__new__(CriticalPromptLoopService)
        self.service._lock = threading.RLock()
        self.service._runs = {self.run_id: self.run}

    def test_completed_view_requires_both_completion_signals(self):
        for done, cleaned in ((False, False), (True, False), (False, True)):
            with self.subTest(done=done, cleaned=cleaned):
                self.run.done.clear()
                self.run.worker_done.clear()
                if done:
                    self.run.done.set()
                if cleaned:
                    self.run.worker_done.set()
                with self.assertRaisesRegex(ExactCallError, "WAIT_TIMEOUT"):
                    self.service.wait(self.run_id, 0)

    def test_both_signals_return_the_same_completed_run(self):
        self.run.done.set()
        self.run.worker_done.set()
        result = self.service.wait(self.run_id, 0)
        self.assertEqual(result["run_id"], self.run_id)
        self.assertEqual(result["execution_status"], "COMPLETED")

    def test_completion_and_cleanup_share_one_finite_budget(self):
        self.run.done = Mock()
        self.run.worker_done = Mock()
        self.run.done.wait.return_value = True
        self.run.worker_done.wait.return_value = True
        with patch("critical_loop.service.time.monotonic", side_effect=(10, 12)):
            self.service.wait(self.run_id, 5)
        self.run.done.wait.assert_called_once_with(5)
        self.run.worker_done.wait.assert_called_once_with(3)

    def test_exhausted_budget_cannot_restart_cleanup_deadline(self):
        self.run.done = Mock()
        self.run.worker_done = Mock()
        self.run.done.wait.return_value = True
        self.run.worker_done.wait.return_value = False
        with patch("critical_loop.service.time.monotonic", side_effect=(10, 16)):
            with self.assertRaisesRegex(ExactCallError, "WAIT_TIMEOUT"):
                self.service.wait(self.run_id, 5)
        self.run.worker_done.wait.assert_called_once_with(0)

    def test_cleanup_signal_releases_waiter_and_thread_terminates(self):
        entered = threading.Event()
        finished = threading.Event()
        outcomes = []

        class CleanupEvent(threading.Event):
            def wait(self, timeout=None):
                entered.set()
                return super().wait(timeout)

        self.run.done.set()
        self.run.worker_done = CleanupEvent()

        def wait():
            try:
                outcomes.append(self.service.wait(self.run_id, 5))
            except Exception as error:
                outcomes.append(error)
            finally:
                finished.set()

        waiter = threading.Thread(target=wait, daemon=True)
        waiter.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertFalse(finished.is_set())
            self.run.worker_done.set()
            waiter.join(5)
            self.assertFalse(waiter.is_alive())
            self.assertEqual(len(outcomes), 1)
            self.assertIsInstance(outcomes[0], dict)
            self.assertEqual(outcomes[0]["run_id"], self.run_id)
        finally:
            self.run.worker_done.set()
            waiter.join(5)

    def test_missing_completion_fails_with_positive_finite_bound(self):
        outcomes = []

        def wait():
            try:
                outcomes.append(self.service.wait(self.run_id, .02))
            except Exception as error:
                outcomes.append(error)

        waiter = threading.Thread(target=wait, daemon=True)
        waiter.start()
        try:
            waiter.join(5)
            self.assertFalse(waiter.is_alive(), "wait must reject a hung CPL within a finite bound")
            self.assertEqual(len(outcomes), 1)
            self.assertIsInstance(outcomes[0], ExactCallError)
            self.assertEqual(outcomes[0].code, "WAIT_TIMEOUT")
        finally:
            self.run.done.set()
            self.run.worker_done.set()
            waiter.join(5)
