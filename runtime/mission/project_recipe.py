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
