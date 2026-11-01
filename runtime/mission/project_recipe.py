"""Inert, operator-reviewed Python fixture plans for the existing U06 registry.

No authority, filesystem mutation, dependency acquisition or host execution.
The workspace is a fresh single-writer sandbox fixture, never a host project.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from runtime.mission.project_worker import validate_program


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def _validate_seed(project_ref, revision, content):
    _require(type(project_ref) is str and re.fullmatch(r'fixture:[A-Za-z0-9][A-Za-z0-9_-]{0,47}', project_ref),
             'FIXTURE_PROJECT_REQUIRED')
    _require(type(revision) is int and 0 <= revision <= 1000000, 'INVALID_PROJECT_REVISION')
    _require((revision == 0 and content is None) or
             (revision > 0 and type(content) is bytes and 0 < len(content) <= 8192),
             'INVALID_PROJECT_PREIMAGE')


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
        _require(type(self.path) is str and self.path == 'src/app.py', 'FIXED_PROJECT_PATH_REQUIRED')
        _require(type(self.replacement) is bytes and 0 < len(self.replacement) <= 8192,
                 'INVALID_PROJECT_REPLACEMENT')
        _require(type(self.expected_value) is int and -1000000 <= self.expected_value <= 1000000,
                 'INVALID_PROJECT_EXPECTATION')
        validate_program(self.replacement)

    @property
    def authority(self):
        return 'NONE'

    def plan_bytes(self):
        return _json({'schema': 'aioa.python-project-plan.v1', 'project_ref': self.project_ref,
                      'path': self.path, 'expected_revision': self.expected_revision,
                      'preimage_sha256': _hash(self.preimage), 'replacement_sha256': _hash(self.replacement),
                      'expected_value': self.expected_value})

    @property
    def digest(self):
        return hashlib.sha256(self.plan_bytes()).hexdigest()

    @property
    def target_fingerprint(self):
        return 'sha256:' + hashlib.sha256(_json({'project_ref': self.project_ref, 'path': self.path,
                                               'revision': self.expected_revision,
                                               'preimage_sha256': _hash(self.preimage)})).hexdigest()

    def result_bytes(self):
        return _json({'schema': 'aioa.python-project-result.v1', 'plan_digest': self.digest,
                      'project_ref': self.project_ref, 'path': self.path,
                      'revision': self.expected_revision + 1, 'source_sha256': _hash(self.replacement),
                      'build': 'PASS', 'test': 'PASS', 'value': self.expected_value})

    def recipe_spec(self, seed):
        _require(type(seed) is ProjectSeed, 'TRUSTED_PROJECT_SEED_REQUIRED')
        worker = Path(__file__).with_name('project_worker.py').read_bytes()
        check = b"import runpy, sys\nns=runpy.run_path('/work/project/src/app.py')\nif type(ns.get('value')) is not int or ns['value'] != int(sys.argv[1]):\n    raise ValueError('PROJECT_TEST_FAILED')\n"
        return {'files': {'recipe.py': worker, 'project.json': self.plan_bytes(),
                          'seed.json': _json({'project_ref': seed.project_ref, 'revision': seed.revision,
                                              'content_sha256': _hash(seed.content)}),
                          'before.py': seed.content or b'', 'after.py': self.replacement, 'check.py': check},
                'expected': {'source.py': self.replacement, 'project-result.json': self.result_bytes()}}


@dataclass(frozen=True, slots=True)
class SensorBridgePlan:
    """Fixed reviewed source, inert until an acknowledged native START."""
    project_ref: str

    def __post_init__(self):
        _validate_seed(self.project_ref, 0, None)

    @property
    def authority(self): return 'NONE'

    def files(self):
        root = Path(__file__).parent
        return {'sensorbridge.py': (root/'sensorbridge_template.py').read_bytes(),
                'test_sensorbridge.py': (root/'sensorbridge_checks.py').read_bytes(),
                'README.md': b'# SensorBridge\n\nDeterministic Python simulator. No hardware or network.\n'}

    def manifest(self):
        return {name: {'sha256': _hash(data), 'bytes': len(data)} for name, data in self.files().items()}

    def plan_bytes(self):
        return _json({'schema': 'aioa.sensorbridge-plan.v1', 'project_ref': self.project_ref,
                      'revision': 0, 'files': self.manifest()})

    @property
    def digest(self): return _hash(self.plan_bytes())

    def recipe_spec(self, seed):
        _require(type(seed) is ProjectSeed and seed.project_ref == self.project_ref
                 and seed.revision == 0 and seed.content is None, 'WORKSPACE_FRESH_SEED_REQUIRED')
        root = Path(__file__).parent
        expected = {**self.files(), 'test-log.txt': b'SENSORBRIDGE_CHECKS_V1 PASS 5\n',
            'manifest.json': _json(self.manifest()), 'result.json': _json({
                'schema': 'aioa.sensorbridge-result.v1', 'project_ref': self.project_ref,
                'plan_digest': self.digest, 'revision': 1, 'tests_passed': 5,
                'files_sha256': _hash(_json(self.manifest()))})}
        return {'files': {'recipe.py': (root/'workspace_worker.py').read_bytes(),
            'fs_helpers.py': (root/'project_worker.py').read_bytes(),
            'plan.json': self.plan_bytes(), **{k:v for k,v in self.files().items() if k.endswith('.py')}},
            'expected': expected}


def prepare_sensorbridge_sandbox(root, *, workspace):
    """Explicit offline host prep; copies installed runtime, never installs it.

    Uses the existing production broker, native gate, namespaces, seccomp and
    kernel resource ceilings. Source runtime/recipe digests join exact approval.
    No old private runtime or credential/cache is imported.
    """
    from dataclasses import replace
    from runtime.mission.sandbox_linux import prepare_linux_sandbox
    from runtime.mission.sandbox_contracts import SandboxRegistry
    root = Path(root).absolute()
    _require(not root.exists(), 'WORKSPACE_PREPARATION_EXISTS')
    runtime = snapshot_python_runtime(root.with_name(root.name+'-runtime'), include_git=True)
    plan = SensorBridgePlan('fixture:sensorbridge')
    config = prepare_linux_sandbox(root, runtime, workspace=workspace,
        recipes={'recipe:sensorbridge-v1': plan.recipe_spec(ProjectSeed(plan.project_ref, 0, None))})
    return replace(config, registry=SandboxRegistry(workspace, tuple(
        replace(r, timeout_ms=20000, max_output_bytes=16384) for r in config.registry.recipes)))


def snapshot_python_runtime(root, *, include_git=False):
    """Trusted system-only runtime capture for the existing sandbox manifest."""
    import os
    import stat
    import subprocess
    root = Path(root); root.mkdir(mode=0o700, parents=True, exist_ok=False)
    files = {str(p):p for p in Path('/usr/lib/python3.12').rglob('*.py')
             if not any(part in ('__pycache__', 'site-packages', 'dist-packages', 'test', 'tests', 'idlelib', 'tkinter')
                        for part in p.parts) and p.is_file() and not p.is_symlink()}
    files['/usr/bin/python3.12'] = Path('/usr/bin/python3.12')
    if include_git:
        from runtime.mission.git_recipe import GIT_BINARY
        from runtime.mission.git_publish import LOCAL_GIT_SHA256
        _require(_hash(Path(GIT_BINARY).read_bytes()) == LOCAL_GIT_SHA256, 'PINNED_GIT_CHANGED')
        files[GIT_BINARY] = Path(GIT_BINARY)
    for pattern in ('_struct.*.so', '_datetime.*.so', '_decimal.*.so', 'binascii.*.so', 'math.*.so'):
        for p in Path('/usr/lib/python3.12/lib-dynload').glob(pattern): files[str(p)] = p
    for name in tuple(files):
        if name.endswith('.py'): continue
        result = subprocess.run(['/usr/bin/ldd', name], capture_output=True, text=True, timeout=5)
        _require(result.returncode == 0, 'WORKSPACE_RUNTIME_DEPENDENCY_UNKNOWN')
        for dep in re.findall(r'(/(?:lib|lib64)/[^\s()]+)', result.stdout): files[dep] = Path(dep)
    manifest = {}
    for index, (target, source) in enumerate(sorted(files.items())):
        resolved = source.resolve(strict=True)
        _require(str(resolved).startswith(('/usr/lib/', '/usr/bin/'))
                 and stat.S_ISREG(resolved.lstat().st_mode), 'WORKSPACE_RUNTIME_PATH_DENIED')
        data = resolved.read_bytes(); destination = root/str(index)
        with destination.open('xb') as stream:
            # The ELF interpreter is executed by the kernel too. Preserve its
            # executable role without making any snapshot writable.
            mode = 0o500 if resolved.stat().st_mode & 0o111 else 0o400
            stream.write(data); stream.flush(); os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        manifest[target] = {'snapshot': str(destination), 'bytes': len(data), 'sha256': _hash(data)}
    return manifest
