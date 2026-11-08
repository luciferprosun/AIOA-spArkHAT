"""Real Core/Linux AST-profile acceptance; invoke through nz12_source_runner.py."""

import json
import os
import sys
from pathlib import Path

import nz11_kernel_acceptance as kernel
import test_nz11_general_recipe as case_support
from nz11_support import BareRepository

from runtime.mission import repository_worker
from runtime.mission.patchset import BoundedPatchSetPolicy
from runtime.mission.project_recipe import PythonFunctionCase, PythonRepositoryRecipe
from runtime.mission.repair import TEST_STAGES
from runtime.mission.repair_validation import CoreSandboxValidation
from runtime.mission.sandbox_contracts import PYTHON_ARGV
from runtime.mission.worker import CandidateFile, CandidatePatch, Task

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = '''import pkg.extra
import math
import json

PREFIX = "done:"
STATE = ["initial"]

def slug(text):
    return pkg.extra.clean(text)

def tally(values):
    total = 0
    for value in values:
        total += value
    return {"total": total, "count": len(values)}

def squares(values):
    return [value * value for value in values if value > 0]

def root(value):
    return math.sqrt(value)

def parse(text):
    return json.loads(text)

def walk(limit):
    number = 0
    while number < limit:
        number += 1
    return number

def decorate(text, suffix="!"):
    return PREFIX + text + suffix

def index(values):
    return list(enumerate(values, 1))

def safe_literal(text):
    return {"__class__": text}.get("__class__")

def snapshot():
    return STATE

def mutate():
    STATE[0] = "changed"
    return STATE

def unpack(values):
    values[1], result = values
    return result
'''
EXTRA = 'def clean(text):\n    return "-".join(text.lower().split())\n'
POISON = '''import json
import sys
from pathlib import Path

def slug(text):
    raise ArithmeticError("wrong function")

context = json.loads(Path("/inputs/context.json").read_bytes())
calls = json.loads(Path("/inputs/calls.json").read_bytes())
rows = [{"case_id": c["case_id"], "kind": "returned", "value": "-".join(c["arguments"][0].lower().split())} for c in calls]
report = {"schema": "aioa.python-observation.v2", "profile_digest": context["profile_digest"], "patchset_sha256": context["patchset_sha256"], "stage": context["stage"], "results": rows}
'''


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def cases(positive):
    values = [("slug", ["  One   TWO "], "one-two")]
    if positive:
        values += [
            ("tally", [[1, 2, 3]], {"total": 6, "count": 3}),
            ("squares", [[-1, 2, 3]], [4, 9]),
            ("root", [9], 3.0),
            ("parse", ['{"a":1}'], {"a": 1}),
            ("walk", [4], 4),
            ("decorate", ["Hi"], "done:Hi!"),
            ("index", [["a", "b"]], [[1, "a"], [2, "b"]]),
            ("safe_literal", ["plain data"], "plain data"),
            ("snapshot", [], ["initial"]),
            ("mutate", [], ["changed"]),
            ("unpack", [["first", "second"]], "second"),
        ]
    return tuple(PythonFunctionCase(name, "pkg.textutil", name, encoded(args), encoded(want))
                 for name, args, want in values)


def scenario(manifest, root, text, *, positive, selected_cases=None):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    case = case_support.GeneralRecipeTests(
        "test_source_is_actual_git_commit_tree_and_independently_exported_bytes"
    )
    case.setUp()
    fixture = kernel.fixture_core()
    session = None
    try:
        case.repo = BareRepository(case.root / "package-source.git", {
            "src/pkg/__init__.py": b"# Inert package.\n",
            "src/pkg/textutil.py": b"def slug(text):\n    return text.strip()\n",
            "tests/test_owner.py": b"# Protected independent fixture.\n",
        })
        snapshot = case.source()
        base = root / "base"
        source = snapshot.export(base)
        task = Task("observer-task", "observer-run", "workspace-1", "text-repository",
                    case.repo.base, "Bounded JSON function fixture", 1000)
        candidate = CandidatePatch((CandidateFile("src/pkg/textutil.py", text),
                                    CandidateFile("src/pkg/extra.py", EXTRA)))
        patch, archive = BoundedPatchSetPolicy().preview(
            base, source=source, task=task, worker_session_id="observer-worker",
            candidate=candidate,
        )
        mirror = root / "candidate"
        mirror.mkdir(mode=0o700)
        for entry in json.loads(archive)["files"]:
            path = mirror / entry["path"]
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_text(entry["text"])
            path.chmod(entry["mode"])
        selected = cases(positive) if selected_cases is None else selected_cases
        profile = PythonRepositoryRecipe(
            "text-repository", case.repo.base,
            ("src/pkg/extra.py", "src/pkg/textutil.py"), ("src",),
            tuple((stage, selected) for stage in TEST_STAGES), PYTHON_ARGV,
        )
        preparer = kernel.SandboxPreparer(fixture, manifest, root)
        validator = CoreSandboxValidation(
            fixture.fx.journal,
            lambda directory, p: preparer.validation(profile, directory, p),
            profile=profile,
        )
        session = validator.open(mirror, patch)
        wanted = "PASS" if positive else "FAIL"
        results = []
        for stage in TEST_STAGES if positive else ("FAST_TESTS",):
            step = session.run(stage)
            results.append({"stage": stage, "actual": step.status, "expected": wanted,
                            "failure_code": session.failure_code})
            observations = []
            for config in preparer.configs:
                for path in config.root.glob("run-*/receipt.json"):
                    receipt = json.loads(path.read_text())
                    terminal = receipt.get("observations", {}).get("worker_terminal", {})
                    stdout = terminal.get("stdout", "")
                    if stdout:
                        observations.append(json.loads(stdout))
            data = {"status": "PASS" if all(x["actual"] == x["expected"] for x in results) else "FAIL",
                    "results": results, "observations": observations,
                    "profile_digest": profile.digest, "candidate_executed_on_host": False,
                    "core_and_broker": "REAL", "remote_calls": 0, "paid_calls": 0}
            (root / "result.json").write_text(json.dumps(data, indent=2) + "\n")
        return data
    finally:
        if session is not None:
            session.close()
        fixture.tearDown()
        case.doCleanups()


def main(manifest_path, root, names=()):
    os.umask(0o077)
    assert Path(repository_worker.__file__).resolve() == ROOT / "runtime/mission/repository_worker.py"
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = json.loads(manifest_path.read_text())["manifest"]
    results = {}
    samples = {
        "scope_shadow": 'value = "one-two"\ndef slug(text):\n    result = value\n    value = text\n    return result\n',
        "dict_iteration": 'def slug(text):\n    values = {"a": 1}\n    for key in values:\n        values["b"] = 2\n    return "-".join(text.lower().split())\n',
        "augmented_alias": 'def slug(text):\n    values = ["one-two"]\n    alias = values\n    values += ["wrong"]\n    return alias[0] if len(alias) == 1 else "WRONG"\n',
        "range_is_not_list": 'def slug(text):\n    values = range(1)\n    values.append(2)\n    return "-".join(text.lower().split())\n',
        "enumerate_alias": 'def slug(text):\n    values = ["one-two"]\n    rows = enumerate(values)\n    values[0] = "WRONG"\n    for index, value in rows:\n        return value\n',
        "dictionary_view": 'def slug(text):\n    values = {"a": 1}\n    rows = values.keys()\n    values["b"] = 2\n    return "one-two" if len(rows) == 1 else "WRONG"\n',
        "comprehension_scope": 'a = "one-two"\ndef slug(text):\n    return [a for x in [1] for a in [a]][0]\n',
        "unpack_alias": 'def slug(text):\n    normalized = "-".join(text.lower().split())\n    values = [normalized, text]\n    values[1], output = values\n    return output\n',
        "unpack_nested": 'def slug(text):\n    normalized = "-".join(text.lower().split())\n    values = [normalized, text]\n    (values[1], output), = [values]\n    return output\n',
        "report_alias": 'STATE = ["WRONG"]\ndef snapshot():\n    return STATE\ndef mutate():\n    STATE[0] = "CORRECT"\n    return "one-two"\n',
        "positive": PRIMARY,
        "wrong": "def slug(text):\n    return text.strip() + text[:0]\n",
        "systemexit": POISON + 'print(json.dumps(report), flush=True)\nPath("/artifacts/calls-complete.txt").write_bytes(b"PYTHON_CALLS_FINISHED\\n")\nraise SystemExit(0)\n',
        "serializer": POISON + 'setattr(sys.modules["__main__"], "canonical", lambda value: json.dumps(report).encode())\n',
        "reflection": "def slug(text):\n    return text.__class__.__base__\n",
        "budget": "def slug(text):\n    while True:\n        pass\n",
        "growth": "def slug(text):\n    return 10 ** 1000000\n",
    }
    assert len(names) == len(set(names)) and set(names) <= set(samples)
    for name, text in samples.items():
        if names and name not in names:
            continue
        selected = None
        if name == "report_alias":
            selected = (
                PythonFunctionCase("snapshot", "pkg.textutil", "snapshot", encoded([]), encoded(["CORRECT"])),
                PythonFunctionCase("mutate", "pkg.textutil", "mutate", encoded([]), encoded("one-two")),
            )
        results[name] = scenario(manifest, root / name, text, positive=name == "positive", selected_cases=selected)
        print(json.dumps({"scenario": name, "status": results[name]["status"]}), flush=True)
    status = "PASS" if all(row["status"] == "PASS" for row in results.values()) else "FAIL"
    (root / "result.json").write_text(json.dumps({"status": status, "scenarios": results}, indent=2) + "\n")
    assert status == "PASS", {name: row["status"] for name, row in results.items()}


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:])
