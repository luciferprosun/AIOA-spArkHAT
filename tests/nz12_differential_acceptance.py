"""Controlled AST/CPython differential corpus through the real Core/Linux broker.

This trusted diagnostic never accepts model/user code and grants no production
execution authority. Its fixed data-only fixtures execute inside the existing
credentialless sandbox, never on the host. Run through nz12_source_runner.py.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import nz11_kernel_acceptance as kernel

from runtime.mission.repair_validation import (
    _collect_sandbox_receipt,
    _pin_prepared_spec,
    _settle_sandbox_receipt,
)
from runtime.providers.exact import CancellationToken

ROOT = Path(__file__).resolve().parents[1]


def corpus():
    cases = []


    def add(name, body, args):
        cases.append({"id": name, "source": body, "args": args})


    for size in range(1, 6):
        values = list(range(1, size + 1))
        add(f"numeric-{size}", "def run(values):\n    total = 0\n    for value in values:\n        total += value * 2\n    return total\n", [values])
        add(f"comprehension-{size}", "def run(values):\n    return [value * value for value in values if value > 1]\n", [values])
        add(f"list-inplace-{size}", "def run(values):\n    alias = values\n    values += [9]\n    return alias\n", [values])
        add(f"while-{size}", "def run(values):\n    index = 0\n    result = []\n    while index < len(values):\n        result.append(values[index])\n        index += 1\n    return result\n", [values])
        add(f"enum-{size}", "def run(values):\n    return list(enumerate(values, 2))\n", [values])
        add(f"zip-{size}", "def run(values):\n    return list(zip(values, reversed(values)))\n", [values])
        add(f"dict-{size}", "def run(values):\n    return {str(value): value * 2 for value in values}\n", [values])
        add(f"slice-{size}", "def run(values):\n    values[1:] = values[:-1]\n    return values\n", [values])

    add("unpack-alias", 'def run(text):\n    normalized = "-".join(text.lower().split())\n    values = [normalized, text]\n    values[1], output = values\n    return output\n', ["  One   TWO "])
    add("unpack-list-target", 'def run(text):\n    normalized = "-".join(text.lower().split())\n    values = [normalized, text]\n    [values[1], output] = values\n    return output\n', ["  One   TWO "])
    add("unpack-nested", 'def run(text):\n    normalized = "-".join(text.lower().split())\n    values = [normalized, text]\n    (values[1], output), = [values]\n    return output\n', ["  One   TWO "])
    add("unpack-iteration", 'def run(text):\n    values = ["first", text]\n    for values[1], output in [values]:\n        return output\n', ["second"])
    add("scope-local", 'result = "global"\ndef run(text):\n    value = result\n    result = text\n    return value\n', ["input"])
    add("scope-comprehension", 'value = "global"\ndef run(text):\n    return [value for other in [1] for value in [value]][0]\n', ["input"])
    add("scope-first-iterable", 'def run(values):\n    return [values for values in values]\n', [[1, 2, 3]])
    add("dict-mutation", 'def run(text):\n    values = {"a": 1}\n    for key in values:\n        values["b"] = 2\n    return text\n', ["input"])
    add("dict-view", 'def run(text):\n    values = {"a": 1}\n    keys = values.keys()\n    values["b"] = 2\n    return list(keys)\n', ["input"])
    add("enum-alias", 'def run(text):\n    values = [text]\n    pairs = enumerate(values)\n    values[0] = "changed"\n    return list(pairs)\n', ["input"])
    add("iterator-consumed-once", 'def run(values):\n    pairs = enumerate(values)\n    first = list(pairs)\n    return [first, list(pairs)]\n', [[1, 2]])
    add("list-iteration-mutation", 'def run(values):\n    result = []\n    for value in values:\n        result.append(value)\n        if len(values) < 4:\n            values.append(9)\n    return result\n', [[1]])
    add("for-else", 'def run(values):\n    result = 0\n    for value in values:\n        if value < 0:\n            break\n        result += value\n    else:\n        result += 100\n    return result\n', [[1, 2, 3]])
    add("break-suppresses-else", 'def run(values):\n    result = 0\n    for value in values:\n        if value < 0:\n            break\n        result += value\n    else:\n        result += 100\n    return result\n', [[1, -2, 3]])
    add("scalar-default-keyword", 'def helper(text, suffix="!"):\n    return text + suffix\ndef run(text):\n    return helper(text, suffix="?")\n', ["input"])
    add("module-state", 'STATE = ["first", "second"]\ndef run(text):\n    STATE.reverse()\n    return STATE\n', ["input"])

    return cases


RECIPE = r'''
import json
import runpy
from pathlib import Path

program_type = runpy.run_path("/inputs/observer.py")["PythonJsonProgram"]
cases = json.loads(Path("/inputs/corpus.json").read_bytes())

def freeze(value):
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))

def native(case):
    # These are controlled, deterministic data-only regression fixtures. No
    # untrusted network/model code is executed by this diagnostic reference.
    namespace = {"__name__": "reference_fixture"}
    try:
        exec(compile(case["source"], "<controlled-reference>", "exec"), namespace)
        return {"kind": "returned", "value": freeze(namespace["run"](*freeze(case["args"])))}
    except Exception as error:
        return {"kind": "raised", "type": type(error).__name__}

def observed(case):
    try:
        call = {"case_id": "case", "module": "sample", "function": "run", "arguments": freeze(case["args"])}
        archive = {"files": [{"path": "src/sample.py", "text": case["source"], "mode": 420}]}
        program = program_type(archive, ["src"], [call])
        return {"kind": "returned", "value": freeze(program.call("sample", "run", call["arguments"]))}
    except Exception as error:
        return {"kind": "raised", "type": type(error).__name__}

mismatches = []
for case in cases:
    expected, actual = native(case), observed(case)
    if expected["kind"] != actual["kind"] or expected["kind"] == "returned" and expected["value"] != actual["value"]:
        mismatches.append({"id": case["id"], "native": expected, "ast": actual})
report = {"cases": len(cases), "mismatches": mismatches}
Path("/artifacts/differential.json").write_bytes(json.dumps(report, sort_keys=True, separators=(",", ":")).encode())
print(json.dumps(report), flush=True)
'''



def main(manifest_path, output):
    os.umask(0o077)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    cases = corpus()
    manifest = json.loads(manifest_path.read_text())["manifest"]
    observer = (ROOT / "runtime/mission/repository_worker.py").read_bytes()
    expected = json.dumps({"cases": len(cases), "mismatches": []}, sort_keys=True, separators=(",", ":")).encode()
    spec = {"files": {"recipe.py": RECIPE.encode(), "observer.py": observer,
                       "corpus.json": json.dumps(cases, sort_keys=True).encode()},
            "expected": {"differential.json": expected}}
    fixture = kernel.fixture_core()
    try:
        preparer = kernel.SandboxPreparer(fixture, manifest, output)
        step, = preparer.steps((("FAST_TESTS", spec),))
        _pin_prepared_spec(fixture.fx.journal, step, spec)
        raw, receipt, _run = _collect_sandbox_receipt(fixture.fx.journal, step, CancellationToken())
        report = json.loads(receipt["observations"]["worker_terminal"]["stdout"])
        result = {"status": "PASS" if not report["mismatches"] else "FAIL", "report": report,
                  "observer_sha256": hashlib.sha256(observer).hexdigest(), "evaluated_on_host": False,
                  "core_and_broker": "REAL", "paid_calls": 0, "remote_calls": 0}
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        assert not report["mismatches"], report
        _settle_sandbox_receipt(fixture.fx.journal, step, raw, receipt)
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
