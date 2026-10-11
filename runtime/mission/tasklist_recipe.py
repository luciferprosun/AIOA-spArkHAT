"""Typed immutable task-list template selection for existing Core/U07/U06.

Plans are inert. Explicit preparation pins files using the existing U06 helper.
The trusted host owns the seed and recipe registry;
model text supplies neither source, tests, argv, paths nor execution authority.
"""
from dataclasses import dataclass, field, replace
import hashlib
from pathlib import Path
import re
from types import MappingProxyType

from runtime.mission.project_recipe import ProjectSeed
from runtime.mission.tasklist_worker import TEMPLATE_ID, canonical, validate_request, require

TASKLIST_TIMEOUT_MS = 20000  # existing U06 ceiling; no change to syscall/egress policy


# Reviewed v1 source identities. Changing a template requires a new review/pin.
SOURCE_PINS = MappingProxyType({
    'tasklist_template.py': '2702689296c688d380be5545a191aeb82da729e72f43fc34ee6f97ca25a2b8e7',
    'tasklist_checks.py': '49ff5f44d151c0dca63d2d6f2597121052669169aa0589d82711e97b6a883245',
    'tasklist_worker.py': 'bcc25e4c0ffd50e381030221dd60a9eacd51c0b4fb0548a43ff383834991f197',
})


def sha(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class TaskListRequest:
    template_id: str
    title: str
    labels: tuple[str, ...]

    def __post_init__(self):
        validate_request(self.template_id, self.title, self.labels)

    @classmethod
    def parse(cls, value):
        require(type(value) is dict and len(value) == 3 and set(value) == {'template_id', 'title', 'labels'},
                'TASKLIST_REQUEST_FIELDS_DENIED')
        require(type(value['labels']) is list and len(value['labels']) <= 8, 'TASKLIST_LABEL_LIMIT')
        return cls(value['template_id'], value['title'], tuple(value['labels']))


@dataclass(frozen=True, slots=True)
class TaskListPlan:
    project_ref: str
    request: TaskListRequest
    expected_revision: int = 0
    preimage: None = None
    _sources: tuple[bytes, bytes, bytes] = field(init=False, repr=False)

    def __post_init__(self):
        require(type(self.project_ref) is str and
                re.fullmatch(r'fixture:[A-Za-z0-9][A-Za-z0-9_-]{0,47}', self.project_ref),
                'FIXTURE_PROJECT_REQUIRED')
        require(type(self.request) is TaskListRequest, 'TYPED_TASKLIST_REQUEST_REQUIRED')
        require(type(self.expected_revision) is int and self.expected_revision == 0
                and self.preimage is None, 'TASKLIST_FRESH_PROJECT_REQUIRED')
        sources = tuple(Path(__file__).with_name(name).read_bytes() for name in SOURCE_PINS)
        require(all(sha(data) == pin for data, pin in zip(sources, SOURCE_PINS.values())),
                'TASKLIST_REVIEWED_SOURCE_REQUIRED')
        object.__setattr__(self, '_sources', sources)

    @property
    def authority(self):
        return 'NONE'

    def plan_bytes(self):
        source, checks, worker = self._sources
        return canonical({'schema': 'aioa.tasklist-plan.v1', 'project_ref': self.project_ref,
            'path': 'src/tasklist.py', 'expected_revision': 0, 'preimage_sha256': None,
            'template_id': self.request.template_id, 'source_sha256': sha(source),
            'checks_sha256': sha(checks), 'worker_sha256': sha(worker),
            'title': self.request.title, 'labels': list(self.request.labels)})

    @property
    def digest(self):
        return sha(self.plan_bytes())

    @property
    def target_fingerprint(self):
        return 'sha256:' + sha(canonical({'project_ref': self.project_ref, 'path': 'src/tasklist.py',
                                         'revision': 0, 'preimage_sha256': None}))

    def expected_artifacts(self):
        source, checks, worker = self._sources
        tasks = [{'id': n, 'label': text, 'done': n == 1}
                 for n, text in enumerate(self.request.labels, 1)]
        data = canonical({'schema': 'aioa.tasklist-data.v1', 'title': self.request.title,
                          'next_id': len(tasks) + 1, 'tasks': tasks})
        listing = (self.request.title + '\n' + ''.join(str(t['id']) + (' [x] ' if t['done'] else ' [ ] ')
            + t['label'] + '\n' for t in tasks)).encode('utf-8')
        outcome = canonical({'schema': 'aioa.tasklist-result.v1', 'plan_digest': self.digest,
            'project_ref': self.project_ref, 'path': 'src/tasklist.py', 'revision': 1,
            'source_sha256': sha(source), 'checks_sha256': sha(checks), 'worker_sha256': sha(worker),
            'data_sha256': sha(data), 'list_sha256': sha(listing), 'build': 'PASS', 'test': 'PASS',
            'test_checks': 16, 'completed_ids': [1], 'task_count': len(tasks)})
        artifacts = {'tasklist.py': source, 'tasklist-tests.py': checks, 'plan.json': self.plan_bytes(),
            'tasks.json': data, 'list.txt': listing, 'test-log.txt': b'TASKLIST_CHECKS_V1 PASS 16\n',
            'tasklist-result.json': outcome}
        artifacts['manifest.json'] = canonical({'schema': 'aioa.tasklist-manifest.v1', 'plan_digest': self.digest,
            'files': {name: {'sha256': sha(content), 'bytes': len(content)} for name, content in artifacts.items()}})
        return artifacts

    def result_bytes(self):
        return self.expected_artifacts()['tasklist-result.json']

    def recipe_spec(self, seed):
        require(type(seed) is ProjectSeed, 'TRUSTED_PROJECT_SEED_REQUIRED')
        source, checks, worker = self._sources
        return {'files': {'recipe.py': worker, 'template.py': source, 'checks.py': checks,
            'plan.json': self.plan_bytes(), 'seed.json': canonical({'project_ref': seed.project_ref,
                'revision': seed.revision, 'content_sha256': None if seed.content is None else sha(seed.content)}),
            'before.py': seed.content or b''}, 'expected': self.expected_artifacts()}


def prepare_tasklist_sandbox(root, runtime_manifest, *, workspace, plan, seed):
    """Explicit trusted host setup, not a model-callable execution controller.

    The fixed v1 CLI checks need more than the arithmetic fixture's 5 seconds on
    the supported small host. Only the existing 20-second U06 timeout is selected;
    all other fixed resources, argv, isolation and Core dispatch gates are kept.
"""
    from runtime.mission.sandbox_contracts import SandboxRegistry
    from runtime.mission.sandbox_linux import prepare_linux_sandbox
    require(type(plan) is TaskListPlan and type(seed) is ProjectSeed,
            'TRUSTED_TASKLIST_PREPARATION_REQUIRED')
    require(seed.project_ref == plan.project_ref and seed.revision == 0 and seed.content is None,
            'TASKLIST_PREIMAGE_DENIED')
    config = prepare_linux_sandbox(root, runtime_manifest, workspace=workspace,
                                  recipes={TEMPLATE_ID: plan.recipe_spec(seed)})
    recipe = replace(config.registry.recipes[0], timeout_ms=TASKLIST_TIMEOUT_MS)
    return replace(config, registry=SandboxRegistry(workspace, (recipe,)))
