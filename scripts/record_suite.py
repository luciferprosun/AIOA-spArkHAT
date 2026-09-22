"""Run unittest discovery and write deterministic machine-readable gate results."""

from __future__ import annotations

import json
import os
from pathlib import Path
import resource
import sys
import tempfile
import time
import unittest


ALLOWED_SKIPS = {
    (
        "test_main.RuntimeArchitectureTests.test_bootstrap_local_context_opens_url_before_model",
        "Playwright is not installed",
    ),
    (
        "test_main.RuntimeArchitectureTests.test_browser_open_search_screenshot_visible_text_and_navigation",
        "Playwright is not installed",
    ),
    (
        "unittest.loader.ModuleSkipped.test_tui_phase1",
        "optional dependency textual is not installed",
    ),
    (
        "unittest.loader.ModuleSkipped.test_tui_phase2",
        "optional dependency textual is not installed",
    ),
}


class ResultWriterError(RuntimeError):
    """The requested machine-result target is unsafe or unusable."""


def prepare_result_output(path: Path) -> Path:
    """Create only the parent and reject a filename/directory collision."""
    if not isinstance(path, Path) or not path.is_absolute():
        raise ResultWriterError("RESULT_OUTPUT_PATH_INVALID")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise ResultWriterError("RESULT_OUTPUT_PARENT_INVALID") from None
    if path.is_dir():
        raise ResultWriterError("RESULT_OUTPUT_IS_DIRECTORY")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ResultWriterError("RESULT_OUTPUT_NOT_REGULAR_FILE")
    return path


def atomic_write_json(path: Path, value: object) -> None:
    path = prepare_result_output(path)
    try:
        encoded = (
            json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ResultWriterError("RESULT_JSON_INVALID") from None
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError:
        raise ResultWriterError("RESULT_OUTPUT_WRITE_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    if path.is_symlink() or not path.is_file():
        raise ResultWriterError("RESULT_OUTPUT_NOT_REGULAR_FILE")


def _result_class(output: Path):
    progress = output.with_suffix(".progress.json")

    class Result(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.records = []

        def record(self, test, status, **details):
            self.records.append({"id": test.id(), "status": status, **details})
            atomic_write_json(progress, {
                "tests_run": self.testsRun,
                "last": test.id(),
                "last_status": status,
                "failures": len(self.failures),
                "errors": len(self.errors),
            })

        def addSuccess(self, test):
            super().addSuccess(test)
            self.record(test, "PASS")

        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            self.record(test, "SKIP", reason=reason)

        def addFailure(self, test, error):
            super().addFailure(test, error)
            self.record(test, "FAIL")

        def addError(self, test, error):
            super().addError(test, error)
            self.record(test, "ERROR", exception=type(error[1]).__name__)

        def addExpectedFailure(self, test, error):
            super().addExpectedFailure(test, error)
            self.record(test, "XFAIL")

        def addUnexpectedSuccess(self, test):
            super().addUnexpectedSuccess(test)
            self.record(test, "XPASS")

    return Result


def run_suite(root: Path, output: Path, pattern: str = "test*.py") -> tuple[dict, bool]:
    output = prepare_result_output(output)
    prepare_result_output(output.with_suffix(".progress.json"))
    if not isinstance(root, Path) or not root.is_absolute() or not root.is_dir():
        raise ResultWriterError("RESULT_TEST_ROOT_INVALID")
    sys.path.insert(0, str(root))
    import runtime  # noqa: E402

    started = time.monotonic()
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.discover(str(root / "tests"), pattern=item)
        for item in pattern.split(",")
    )
    collected = suite.countTestCases()
    result = unittest.TextTestRunner(
        verbosity=2, resultclass=_result_class(output)
    ).run(suite)
    unexpected_skips = [
        [test.id(), reason]
        for test, reason in result.skipped
        if (test.id(), reason) not in ALLOWED_SKIPS
    ]
    passed = (
        result.wasSuccessful()
        and result.testsRun == collected
        and not unexpected_skips
        and not result.expectedFailures
        and not result.unexpectedSuccesses
    )
    report = {
        "STATUS": "PASS" if passed else "FAIL",
        "classification": "OBSERVED_NOW",
        "python": sys.version.split()[0],
        "collected": collected,
        "tests_run": result.testsRun,
        "passed": sum(row["status"] == "PASS" for row in result.records),
        "skipped": len(result.skipped),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "unexpected_skips": unexpected_skips,
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "unique_test_ids": len({row["id"] for row in result.records}),
        "seconds": round(time.monotonic() - started, 3),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "runtime_file": runtime.__file__,
        "state_root": os.environ.get("AOIA_HOME"),
        "network": "BWRAP_ISOLATED_NETWORK_NAMESPACE",
        "tests": result.records,
    }
    atomic_write_json(output, report)
    return report, passed


def main(arguments: list[str]) -> int:
    if len(arguments) not in {2, 3}:
        raise SystemExit("usage: record_suite.py ROOT OUTPUT [PATTERN]")
    root = Path(arguments[0]).resolve()
    output = Path(arguments[1])
    if not output.is_absolute():
        output = output.resolve()
    pattern = arguments[2] if len(arguments) == 3 else "test*.py"
    report, passed = run_suite(root, output, pattern)
    print(json.dumps({key: value for key, value in report.items() if key != "tests"}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
