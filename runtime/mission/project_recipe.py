"""Inert, operator-reviewed Python fixture plans for the existing U06 registry.

No authority, filesystem mutation, dependency acquisition or host execution.
The workspace is a fresh single-writer sandbox fixture, never a host project.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from runtime.mission.project_worker import validate_program


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _hash(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def _validate_seed(project_ref, revision, content):
    _require(
        type(project_ref) is str
        and re.fullmatch(r"fixture:[A-Za-z0-9][A-Za-z0-9_-]{0,47}", project_ref),
        "FIXTURE_PROJECT_REQUIRED",
    )
    _require(
        type(revision) is int and 0 <= revision <= 1000000, "INVALID_PROJECT_REVISION"
    )
    _require(
        (revision == 0 and content is None)
        or (revision > 0 and type(content) is bytes and 0 < len(content) <= 8192),
        "INVALID_PROJECT_PREIMAGE",
    )


@dataclass(frozen=True, slots=True)
class ProjectSeed:
    """Independent trusted fixture snapshot; it is not inferred from plan claims."""

    project_ref: str
    revision: int
    content: bytes | None

    def __post_init__(self):
        _validate_seed(self.project_ref, self.revision, self.content)


@dataclass(frozen=True, slots=True)
class PythonProjectPlan:
    project_ref: str
    path: str
    expected_revision: int
    preimage: bytes | None
    replacement: bytes
    expected_value: int

    def __post_init__(self):
        _validate_seed(self.project_ref, self.expected_revision, self.preimage)
        _require(
            type(self.path) is str and self.path == "src/app.py",
            "FIXED_PROJECT_PATH_REQUIRED",
        )
        _require(
            type(self.replacement) is bytes and 0 < len(self.replacement) <= 8192,
            "INVALID_PROJECT_REPLACEMENT",
        )
        _require(
            type(self.expected_value) is int
            and -1000000 <= self.expected_value <= 1000000,
            "INVALID_PROJECT_EXPECTATION",
        )
        validate_program(self.replacement)

    @property
    def authority(self):
        return "NONE"

    def plan_bytes(self):
        return _json(
            {
                "schema": "aioa.python-project-plan.v1",
                "project_ref": self.project_ref,
                "path": self.path,
                "expected_revision": self.expected_revision,
                "preimage_sha256": _hash(self.preimage),
                "replacement_sha256": _hash(self.replacement),
                "expected_value": self.expected_value,
            }
        )

    @property
    def digest(self):
        return hashlib.sha256(self.plan_bytes()).hexdigest()

    @property
    def target_fingerprint(self):
        return (
            "sha256:"
            + hashlib.sha256(
                _json(
                    {
                        "project_ref": self.project_ref,
                        "path": self.path,
                        "revision": self.expected_revision,
                        "preimage_sha256": _hash(self.preimage),
                    }
                )
            ).hexdigest()
        )

    def result_bytes(self):
        return _json(
            {
                "schema": "aioa.python-project-result.v1",
                "plan_digest": self.digest,
                "project_ref": self.project_ref,
                "path": self.path,
                "revision": self.expected_revision + 1,
                "source_sha256": _hash(self.replacement),
                "build": "PASS",
                "test": "PASS",
                "value": self.expected_value,
            }
        )

    def recipe_spec(self, seed):
        _require(type(seed) is ProjectSeed, "TRUSTED_PROJECT_SEED_REQUIRED")
        worker = Path(__file__).with_name("project_worker.py").read_bytes()
        check = b"import runpy, sys\nns=runpy.run_path('/work/project/src/app.py')\nif type(ns.get('value')) is not int or ns['value'] != int(sys.argv[1]):\n    raise ValueError('PROJECT_TEST_FAILED')\n"
        return {
            "files": {
                "recipe.py": worker,
                "project.json": self.plan_bytes(),
                "seed.json": _json(
                    {
                        "project_ref": seed.project_ref,
                        "revision": seed.revision,
                        "content_sha256": _hash(seed.content),
                    }
                ),
                "before.py": seed.content or b"",
                "after.py": self.replacement,
                "check.py": check,
            },
            "expected": {
                "source.py": self.replacement,
                "project-result.json": self.result_bytes(),
            },
        }


@dataclass(frozen=True, slots=True)
class SensorBridgePlan:
    """Fixed reviewed source, inert until an acknowledged native START."""

    project_ref: str

    def __post_init__(self):
        _validate_seed(self.project_ref, 0, None)

    @property
    def authority(self):
        return "NONE"

    def files(self):
        root = Path(__file__).parent
        return {
            "sensorbridge.py": (root / "sensorbridge_template.py").read_bytes(),
            "test_sensorbridge.py": (root / "sensorbridge_checks.py").read_bytes(),
            "README.md": b"# SensorBridge\n\nDeterministic Python simulator. No hardware or network.\n",
        }

    def manifest(self):
        return {
            name: {"sha256": _hash(data), "bytes": len(data)}
            for name, data in self.files().items()
        }

    def plan_bytes(self):
        return _json(
            {
                "schema": "aioa.sensorbridge-plan.v1",
                "project_ref": self.project_ref,
                "revision": 0,
                "files": self.manifest(),
            }
        )

    @property
    def digest(self):
        return _hash(self.plan_bytes())

    def recipe_spec(self, seed):
        _require(
            type(seed) is ProjectSeed
            and seed.project_ref == self.project_ref
            and seed.revision == 0
            and seed.content is None,
            "WORKSPACE_FRESH_SEED_REQUIRED",
        )
        root = Path(__file__).parent
        expected = {
            **self.files(),
            "test-log.txt": b"SENSORBRIDGE_CHECKS_V1 PASS 5\n",
            "manifest.json": _json(self.manifest()),
            "result.json": _json(
                {
                    "schema": "aioa.sensorbridge-result.v1",
                    "project_ref": self.project_ref,
                    "plan_digest": self.digest,
                    "revision": 1,
                    "tests_passed": 5,
                    "files_sha256": _hash(_json(self.manifest())),
                }
            ),
        }
        return {
            "files": {
                "recipe.py": (root / "workspace_worker.py").read_bytes(),
                "fs_helpers.py": (root / "project_worker.py").read_bytes(),
                "plan.json": self.plan_bytes(),
                **{k: v for k, v in self.files().items() if k.endswith(".py")},
            },
            "expected": expected,
        }


def prepare_sensorbridge_sandbox(root, *, workspace):
    """Explicit offline host prep; copies installed runtime, never installs it.

    Uses the existing production broker, native gate, namespaces, seccomp and
    kernel resource ceilings. Source runtime/recipe digests join exact approval.
    No old private runtime or credential/cache is imported.
    """
    from dataclasses import replace

    from runtime.mission.sandbox_contracts import SandboxRegistry
    from runtime.mission.sandbox_linux import prepare_linux_sandbox

    root = Path(root).absolute()
    _require(not root.exists(), "WORKSPACE_PREPARATION_EXISTS")
    runtime = snapshot_python_runtime(
        root.with_name(root.name + "-runtime"), include_git=True
    )
    plan = SensorBridgePlan("fixture:sensorbridge")
    config = prepare_linux_sandbox(
        root,
        runtime,
        workspace=workspace,
        recipes={
            "recipe:sensorbridge-v1": plan.recipe_spec(
                ProjectSeed(plan.project_ref, 0, None)
            )
        },
    )
    return replace(
        config,
        registry=SandboxRegistry(
            workspace,
            tuple(
                replace(r, timeout_ms=20000, max_output_bytes=16384)
                for r in config.registry.recipes
            ),
        ),
    )


def snapshot_python_runtime(root, *, include_git=False):
    """Trusted system-only runtime capture for the existing sandbox manifest."""
    import os
    import stat
    import subprocess

    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    files = {
        str(p): p
        for p in Path("/usr/lib/python3.12").rglob("*.py")
        if not any(
            part
            in (
                "__pycache__",
                "site-packages",
                "dist-packages",
                "test",
                "tests",
                "idlelib",
                "tkinter",
            )
            for part in p.parts
        )
        and p.is_file()
        and not p.is_symlink()
    }
    files["/usr/bin/python3.12"] = Path("/usr/bin/python3.12")
    if include_git:
        from runtime.mission.git_publish import LOCAL_GIT_SHA256
        from runtime.mission.git_recipe import GIT_BINARY

        _require(
            _hash(Path(GIT_BINARY).read_bytes()) == LOCAL_GIT_SHA256,
            "PINNED_GIT_CHANGED",
        )
        files[GIT_BINARY] = Path(GIT_BINARY)
    for pattern in (
        "_struct.*.so",
        "_datetime.*.so",
        "_decimal.*.so",
        "binascii.*.so",
        "math.*.so",
    ):
        for p in Path("/usr/lib/python3.12/lib-dynload").glob(pattern):
            files[str(p)] = p
    for name in tuple(files):
        if name.endswith(".py"):
            continue
        result = subprocess.run(
            ["/usr/bin/ldd", name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        _require(result.returncode == 0, "WORKSPACE_RUNTIME_DEPENDENCY_UNKNOWN")
        for dep in re.findall(r"(/(?:lib|lib64)/[^\s()]+)", result.stdout):
            files[dep] = Path(dep)
    manifest = {}
    for index, (target, source) in enumerate(sorted(files.items())):
        resolved = source.resolve(strict=True)
        _require(
            str(resolved).startswith(("/usr/lib/", "/usr/bin/"))
            and stat.S_ISREG(resolved.lstat().st_mode),
            "WORKSPACE_RUNTIME_PATH_DENIED",
        )
        data = resolved.read_bytes()
        destination = root / str(index)
        with destination.open("xb") as stream:
            # The ELF interpreter is executed by the kernel too. Preserve its
            # executable role without making any snapshot writable.
            mode = 0o500 if resolved.stat().st_mode & 0o111 else 0o400
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        manifest[target] = {
            "snapshot": str(destination),
            "bytes": len(data),
            "sha256": _hash(data),
        }
    return manifest


def _recipe_value(raw):
    """Bounded canonical JSON values, with no object hooks or executable input."""
    import math

    from runtime.mission.repair_validation import _json_bytes

    _require(type(raw) is bytes and 0 < len(raw) <= 8192, "RECIPE_JSON_BOUND")
    try:
        value = _json_bytes(raw)
    except (ValueError, RecursionError):
        raise ValueError("RECIPE_JSON") from None

    def check(item, depth=0):
        _require(depth <= 8, "RECIPE_JSON_DEPTH")
        if item is None or type(item) is bool:
            return
        if type(item) in (int, float):
            _require(math.isfinite(item) and abs(item) <= 10**12, "RECIPE_NUMBER_BOUND")
        elif type(item) is str:
            _require(len(item.encode()) <= 2048, "RECIPE_STRING_BOUND")
        elif type(item) is list:
            _require(len(item) <= 32, "RECIPE_ARRAY_BOUND")
            for child in item:
                check(child, depth + 1)
        elif type(item) is dict:
            _require(
                len(item) <= 32 and all(type(k) is str and len(k) <= 64 for k in item),
                "RECIPE_OBJECT_BOUND",
            )
            for child in item.values():
                check(child, depth + 1)
        else:
            raise ValueError("RECIPE_JSON_TYPE")

    check(value)
    _require(_json(value) == raw, "RECIPE_CANONICAL_JSON_REQUIRED")
    return value


@dataclass(frozen=True, slots=True)
class PythonFunctionCase:
    """Operator oracle. Expected values are never supplied to candidate code."""

    case_id: str
    module: str
    function: str
    arguments_json: bytes = field(repr=False)
    expected_json: bytes = field(repr=False)

    def __post_init__(self):
        from runtime.mission.contracts import logical_id
        from runtime.nonzero_cloudops.models.redaction import (
            contains_sensitive_material,
        )

        logical_id(self.case_id)
        _require(
            type(self.module) is str
            and re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*", self.module
            )
            and len(self.module) <= 128,
            "RECIPE_MODULE",
        )
        _require(
            type(self.function) is str
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", self.function),
            "RECIPE_FUNCTION",
        )
        args = _recipe_value(self.arguments_json)
        _require(type(args) is list and len(args) <= 16, "RECIPE_ARGUMENTS")
        _recipe_value(self.expected_json)
        _require(
            not contains_sensitive_material(self.arguments_json.decode())
            and not contains_sensitive_material(self.expected_json.decode()),
            "RECIPE_SENSITIVE_VALUE",
        )

    def call_payload(self):
        return {
            "case_id": self.case_id,
            "module": self.module,
            "function": self.function,
            "arguments": _recipe_value(self.arguments_json),
        }


@dataclass(frozen=True, slots=True)
class PythonRepositoryRecipe:
    """Static bounded repository recipe, distinct from model instructions.

    A restricted Python AST/JSON function language is evaluated in the existing
    credentialless Linux sandbox. Arbitrary Python execution is unsupported.
    A trusted host oracle checks returned JSON values; guest assertions,
    counters, exit text and PASS claims confer no authority.
    """

    repository_id: str
    source_base_sha: str
    allowed_paths: tuple[str, ...]
    import_roots: tuple[str, ...]
    stages: tuple = field(repr=False)
    command: tuple[str, ...]

    def __post_init__(self):
        from runtime.mission.contracts import logical_id
        from runtime.mission.patchset import (
            _protected_change,
            normalize_patch_relative_path,
        )
        from runtime.mission.repair import TEST_STAGES
        from runtime.mission.sandbox_contracts import PYTHON_ARGV

        logical_id(self.repository_id)
        _require(
            type(self.source_base_sha) is str
            and re.fullmatch("[a-f0-9]{40}", self.source_base_sha),
            "RECIPE_SOURCE_SHA",
        )
        _require(
            type(self.command) is tuple and self.command == PYTHON_ARGV,
            "RECIPE_FIXED_COMMAND",
        )
        _require(
            type(self.allowed_paths) is tuple
            and 1 <= len(self.allowed_paths) <= 3
            and all(type(p) is str for p in self.allowed_paths),
            "RECIPE_PATHS",
        )
        _require(
            self.allowed_paths == tuple(sorted(set(self.allowed_paths))), "RECIPE_PATHS"
        )
        for path in self.allowed_paths:
            normalize_patch_relative_path(path)
            _protected_change(path)
            _require(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,191}", path) is not None,
                "RECIPE_EXACT_PATHS_ONLY",
            )
        _require(
            type(self.import_roots) is tuple
            and 1 <= len(self.import_roots) <= 4
            and all(type(p) is str for p in self.import_roots),
            "RECIPE_IMPORT_ROOTS",
        )
        for path in self.import_roots:
            if path:
                normalize_patch_relative_path(path)
            _require(
                path == "" or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,127}", path),
                "RECIPE_IMPORT_ROOTS",
            )
        _require(
            type(self.stages) is tuple
            and len(self.stages) == 3
            and all(type(row) is tuple and len(row) == 2 for row in self.stages),
            "RECIPE_STAGES",
        )
        _require(tuple(row[0] for row in self.stages) == TEST_STAGES, "RECIPE_STAGES")
        for _, cases in self.stages:
            _require(
                type(cases) is tuple
                and 1 <= len(cases) <= 16
                and all(type(c) is PythonFunctionCase for c in cases),
                "RECIPE_CASES",
            )
            _require(len({c.case_id for c in cases}) == len(cases), "RECIPE_CASES")
            _require(
                sum(len(c.arguments_json) + len(c.expected_json) for c in cases)
                <= 8192,
                "RECIPE_CASES_BOUND",
            )

    def manifest_bytes(self):
        self.__post_init__()
        return _json(
            {
                "schema": "aioa.python-repository-recipe.v2",
                "repository_id": self.repository_id,
                "source_base_sha": self.source_base_sha,
                "allowed_paths": list(self.allowed_paths),
                "import_roots": list(self.import_roots),
                "command": list(self.command),
                "stages": [
                    {
                        "stage": stage,
                        "cases": [
                            {
                                "case_id": case.case_id,
                                "module": case.module,
                                "function": case.function,
                                "arguments": _recipe_value(case.arguments_json),
                                "expected": _recipe_value(case.expected_json),
                            }
                            for case in cases
                        ],
                    }
                    for stage, cases in self.stages
                ],
            }
        )

    @classmethod
    def from_manifest(cls, raw):
        from runtime.mission.repair_validation import _json_bytes

        _require(type(raw) is bytes and 0 < len(raw) <= 65536, "PYTHON_MANIFEST_BOUND")
        row = _json_bytes(raw)
        _require(
            type(row) is dict
            and set(row)
            == {
                "schema",
                "repository_id",
                "source_base_sha",
                "allowed_paths",
                "import_roots",
                "command",
                "stages",
            }
            and row["schema"] == "aioa.python-repository-recipe.v2",
            "PYTHON_MANIFEST_SCHEMA",
        )
        for name in ("allowed_paths", "import_roots", "command", "stages"):
            _require(
                type(row[name]) is list and len(row[name]) <= 16,
                "PYTHON_MANIFEST_SCHEMA",
            )
        stages = []
        for stage in row["stages"]:
            _require(
                type(stage) is dict
                and set(stage) == {"stage", "cases"}
                and type(stage["cases"]) is list
                and 1 <= len(stage["cases"]) <= 16,
                "PYTHON_MANIFEST_SCHEMA",
            )
            cases = []
            for case in stage["cases"]:
                _require(
                    type(case) is dict
                    and set(case)
                    == {"case_id", "module", "function", "arguments", "expected"},
                    "PYTHON_MANIFEST_SCHEMA",
                )
                cases.append(
                    PythonFunctionCase(
                        case["case_id"],
                        case["module"],
                        case["function"],
                        _json(case["arguments"]),
                        _json(case["expected"]),
                    )
                )
            stages.append((stage["stage"], tuple(cases)))
        return cls(
            row["repository_id"],
            row["source_base_sha"],
            tuple(row["allowed_paths"]),
            tuple(row["import_roots"]),
            tuple(stages),
            tuple(row["command"]),
        )

    @classmethod
    def load_file(cls, path):
        import os

        from runtime.mission.sandbox_linux import read_evidence_file

        path = Path(path)
        _require(
            path.is_absolute() and path.resolve(strict=True) == path,
            "PYTHON_MANIFEST_LOCATOR",
        )
        info = path.lstat()
        _require(
            info.st_uid == os.getuid() and not info.st_mode & 0o077,
            "PYTHON_PRIVATE_MANIFEST_REQUIRED",
        )
        return cls.from_manifest(read_evidence_file(path.parent, path.name, 65536))

    @property
    def digest(self):
        return _hash(
            _json(
                {
                    "schema": "aioa.python-repository-recipe.v2",
                    "repository_id": self.repository_id,
                    "source_base_sha": self.source_base_sha,
                    "allowed_paths": self.allowed_paths,
                    "import_roots": self.import_roots,
                    "command": self.command,
                    "stages": [
                        [
                            stage,
                            [
                                [c.call_payload(), _recipe_value(c.expected_json)]
                                for c in cases
                            ],
                        ]
                        for stage, cases in self.stages
                    ],
                    "worker_sha256": _hash(
                        Path(__file__).with_name("repository_worker.py").read_bytes()
                    ),
                }
            )
        )

    def validate_patch(self, patch):
        from runtime.mission.patchset import PatchSet

        _require(type(patch) is PatchSet, "RECIPE_PATCH_REQUIRED")
        patch.verify_digest()
        _require(
            patch.repository_id == self.repository_id
            and patch.source_base_sha == self.source_base_sha,
            "RECIPE_SOURCE_BINDING",
        )
        _require(
            all(c.path in self.allowed_paths for c in patch.files), "RECIPE_PATH_DENIED"
        )

    def context(self, stage, patch):
        self.validate_patch(patch)
        _require(stage in dict(self.stages), "RECIPE_STAGE")
        return {
            "schema": "aioa.trusted-test-context.v1",
            "stage": stage,
            "profile_digest": self.digest,
            "patchset_sha256": patch.patchset_sha256,
            "test_count": len(dict(self.stages)[stage]),
        }

    def materialization_spec(
        self, base_root, *, source, task, worker_session_id, candidate
    ):
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.mission.patchset import BoundedPatchSetPolicy, _snapshot, _text

        patch, archive = BoundedPatchSetPolicy().preview(
            base_root,
            source=source,
            task=task,
            worker_session_id=worker_session_id,
            candidate=candidate,
        )
        self.validate_patch(patch)
        tree = _snapshot(base_root)
        base = canonical_json_bytes(
            {
                "schema": "aioa.validation-workspace.v1",
                "files": [
                    {"path": p, "mode": f.identity.mode, "text": _text(f)}
                    for p, f in sorted(tree.files.items())
                ],
            }
        )
        changes = [
            {
                "path": c.path,
                "operation": c.operation,
                "before_sha256": None if c.before is None else c.before.sha256,
                "after_sha256": None if c.after is None else c.after.sha256,
                "text": next(v.text for v in candidate.files if v.path == c.path),
            }
            for c in patch.files
        ]
        receipt = {
            "schema": "aioa.python-materialization.v1",
            "profile_digest": self.digest,
            "source_base_sha": self.source_base_sha,
            "patchset_sha256": patch.patchset_sha256,
            "base_tree_sha256": patch.base_tree_sha256,
            "final_tree_sha256": patch.final_tree_sha256,
            "operations": [
                {"path": c.path, "operation": c.operation} for c in patch.files
            ],
        }
        spec = {
            "files": {
                "recipe.py": Path(__file__)
                .with_name("repository_worker.py")
                .read_bytes(),
                "mode.json": _json({"mode": "materialize"}),
                "base.json": base,
                "changes.json": canonical_json_bytes(changes),
                "materialization.json": canonical_json_bytes(receipt),
            },
            "expected": {
                "workspace.json": archive,
                "materialization.json": canonical_json_bytes(receipt),
            },
        }
        return patch, archive, spec

    def observation_spec(self, stage, archive, patch):
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.mission.repair_validation import workspace_tree_digest

        _require(
            workspace_tree_digest(archive) == patch.final_tree_sha256,
            "RECIPE_TREE_BINDING",
        )
        context = self.context(stage, patch)
        return {
            "files": {
                "recipe.py": Path(__file__)
                .with_name("repository_worker.py")
                .read_bytes(),
                "mode.json": _json({"mode": "observe"}),
                "workspace.json": archive,
                "context.json": canonical_json_bytes(context),
                "calls.json": canonical_json_bytes(
                    [c.call_payload() for c in dict(self.stages)[stage]]
                ),
                "imports.json": canonical_json_bytes(list(self.import_roots)),
            },
            "expected": {"calls-complete.txt": b"PYTHON_CALLS_FINISHED\n"},
        }

    def decode_observation(self, stdout, stage, patch):
        from runtime.mission.codex_worker import JsonlFramer

        self.validate_patch(patch)
        _require(
            type(stdout) is str and len(stdout.encode()) <= 16384,
            "RECIPE_OBSERVATION_BOUND",
        )
        parser = JsonlFramer(max_bytes=16384)
        rows = parser.feed(stdout.encode())
        parser.finish()
        _require(len(rows) == 1, "RECIPE_OBSERVATION_COUNT")
        row = rows[0]
        _require(
            set(row)
            == {"schema", "profile_digest", "patchset_sha256", "stage", "results"}
            and row["schema"] == "aioa.python-observation.v2"
            and row["profile_digest"] == self.digest
            and row["patchset_sha256"] == patch.patchset_sha256
            and row["stage"] == stage,
            "RECIPE_OBSERVATION_BINDING",
        )
        cases = dict(self.stages)[stage]
        values = row["results"]
        _require(
            type(values) is list and len(values) == len(cases),
            "RECIPE_OBSERVATION_CASES",
        )
        passed = True
        for case, observed in zip(cases, values, strict=True):
            _require(
                type(observed) is dict and observed.get("case_id") == case.case_id,
                "RECIPE_OBSERVATION_CASES",
            )
            if observed.get("kind") == "returned":
                _require(
                    set(observed) == {"case_id", "kind", "value"},
                    "RECIPE_OBSERVATION_SCHEMA",
                )
                actual = _json(observed["value"])
                _recipe_value(actual)
                passed = passed and actual == case.expected_json
            else:
                _require(
                    set(observed) == {"case_id", "kind", "type"}
                    and observed["kind"] == "raised"
                    and type(observed["type"]) is str
                    and re.fullmatch("[A-Za-z][A-Za-z0-9_]{0,63}", observed["type"]),
                    "RECIPE_OBSERVATION_SCHEMA",
                )
                passed = False
        return ("PASS", 0) if passed else ("FAIL", 1)
