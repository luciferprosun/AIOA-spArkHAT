"""Bounded sandbox values, not authority or a second effect journal.

The operation precedes a human session grant. A dispatch request is constructed
by the trusted Core adapter only after its live START acknowledgement. Its
digest never feeds back into the operation, completion, grant or warrant.
"""
from dataclasses import dataclass, fields
from types import MappingProxyType
import json
import re

from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.mission.warrant import require

PYTHON_ARGV = ('/usr/bin/python3.12', '-I', '-S', '-B', '/inputs/recipe.py')
RESOURCE_CEILINGS = MappingProxyType({
    'timeout_ms': 20000, 'max_output_bytes': 16384, 'memory_bytes': 536870912,
    'cpu_quota_us': 100000, 'cpu_period_us': 100000, 'pids_max': 16,
    'work_bytes': 33554432, 'tmp_bytes': 16777216, 'artifacts_bytes': 8388608,
})
PAYLOAD_FIELDS = frozenset({
    'tool', 'workspace', 'task_id', 'step_id', 'recipe_id', 'argv', 'project_root_ref',
    'sandbox_profile_digest', 'tool_input_digest', 'network_profile', 'env_policy_digest',
    *RESOURCE_CEILINGS,
})


def _identity(value):
    require(type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}', value) is not None,
            'INVALID_SANDBOX_IDENTITY')


def _digest(value, *, prefixed=False):
    pattern = r'sha256:[0-9a-f]{64}' if prefixed else r'[0-9a-f]{64}'
    require(type(value) is str and re.fullmatch(pattern, value) is not None, 'INVALID_SANDBOX_DIGEST')


@dataclass(frozen=True, slots=True)
class SandboxOperation:
    operation_bytes: bytes

    def __post_init__(self):
        require(type(self.operation_bytes) is bytes and 0 < len(self.operation_bytes) <= 4096,
                'INVALID_SANDBOX_OPERATION')
        try:
            operation = json.loads(self.operation_bytes)
        except (ValueError, UnicodeError):
            require(False, 'INVALID_SANDBOX_OPERATION')
        require(canonical_json_bytes(operation) == self.operation_bytes
                and type(operation) is dict and set(operation) == {
                    'operation_class', 'target_fingerprint', 'expected_target_revision', 'payload'}
                and operation['operation_class'] == 'SANDBOX_EXEC', 'INVALID_SANDBOX_OPERATION')
        _digest(operation['target_fingerprint'], prefixed=True)
        _identity(operation['expected_target_revision'])
        payload = operation['payload']
        require(type(payload) is dict and set(payload) == PAYLOAD_FIELDS
                and payload['tool'] == 'run_recipe' and payload['network_profile'] == 'OFF',
                'INVALID_SANDBOX_OPERATION')
        for name in ('workspace', 'task_id', 'step_id', 'recipe_id', 'project_root_ref'):
            _identity(payload[name])
        for name in ('sandbox_profile_digest', 'tool_input_digest', 'env_policy_digest'):
            _digest(payload[name])
        # This deliberately small profile exposes one fixed interpreter recipe.
        # A future executable/argv profile needs a separately reviewed registry.
        require(type(payload['argv']) is list and tuple(payload['argv']) == PYTHON_ARGV,
                'UNAPPROVED_SANDBOX_ARGV')
        for name, ceiling in RESOURCE_CEILINGS.items():
            require(type(payload[name]) is int and 0 < payload[name] <= ceiling,
                    'INVALID_SANDBOX_LIMIT')
        require(payload['cpu_quota_us'] <= payload['cpu_period_us'], 'INVALID_SANDBOX_LIMIT')

    @classmethod
    def parse(cls, value):
        require(type(value) is dict, 'INVALID_SANDBOX_OPERATION')
        return cls(canonical_json_bytes(value))

    def to_dict(self):
        return json.loads(self.operation_bytes)

    @property
    def digest(self):
        return 'sha256:' + canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class SandboxDispatchRequest:
    operation_bytes: bytes
    operation_digest: str
    task_id: str
    step_id: str
    session_id: str
    session_grant_digest: str
    policy_epoch: int
    warrant_digest: str
    ddr_digest: str
    reservation_digest: str
    completion_digest: str
    idempotency_key: str

    def __post_init__(self):
        operation = SandboxOperation(self.operation_bytes)
        payload = operation.to_dict()['payload']
        require(self.operation_digest == operation.digest and self.task_id == payload['task_id']
                and self.step_id == payload['step_id'], 'SANDBOX_REQUEST_BINDING')
        for name in ('task_id', 'step_id', 'session_id', 'idempotency_key'):
            _identity(getattr(self, name))
        for name in ('session_grant_digest', 'reservation_digest', 'completion_digest'):
            _digest(getattr(self, name))
        for name in ('operation_digest', 'warrant_digest', 'ddr_digest'):
            _digest(getattr(self, name), prefixed=True)
        require(type(self.policy_epoch) is int and 0 < self.policy_epoch < 2**63,
                'INVALID_SANDBOX_EPOCH')

    def to_dict(self):
        result = {field.name: getattr(self, field.name) for field in fields(self)
                  if field.name != 'operation_bytes'}
        return {'schema': 'aioa.sandbox-dispatch.v1',
                'operation': json.loads(self.operation_bytes), **result}

    @property
    def digest(self):
        return canonical_sha256({'domain': 'aioa.sandbox-dispatch.v1', 'request': self.to_dict()})


@dataclass(frozen=True, slots=True)
class ToolVariant:
    operation_class: str
    tool: str
    provider_id: str
    mode: str
    reservation_domain: str


SYNTHETIC = ToolVariant('PROJECT_WRITE', 'write_file', 'synthetic', 'SYNTHETIC_ONLY',
                        'synthetic-tool-reservation')
SANDBOX = ToolVariant('SANDBOX_EXEC', 'run_recipe', 'sandbox-exec', 'SANDBOX',
                      'sandbox-tool-reservation')
TOOL_POLICY_VERSIONS = MappingProxyType({1: (SYNTHETIC,), 2: (SYNTHETIC, SANDBOX)})


def tool_variant(revision, operation_class):
    require(type(revision) is int and revision in TOOL_POLICY_VERSIONS, 'UNKNOWN_TOOL_POLICY')
    selected = [v for v in TOOL_POLICY_VERSIONS[revision] if v.operation_class == operation_class]
    require(len(selected) == 1, 'UNKNOWN_TOOL_VARIANT')
    return selected[0]


@dataclass(frozen=True, slots=True)
class SandboxRecipe:
    recipe_id: str
    project_root_ref: str
    sandbox_profile_digest: str
    tool_input_digest: str
    env_policy_digest: str
    timeout_ms: int = 5000
    max_output_bytes: int = 4096
    memory_bytes: int = 536870912
    cpu_quota_us: int = 100000
    cpu_period_us: int = 100000
    pids_max: int = 16
    work_bytes: int = 33554432
    tmp_bytes: int = 16777216
    artifacts_bytes: int = 8388608
    argv: tuple[str, ...] = PYTHON_ARGV

    def __post_init__(self):
        require(type(self.argv) is tuple, 'INVALID_SANDBOX_RECIPE')
        SandboxOperation.parse({'operation_class': 'SANDBOX_EXEC',
            'target_fingerprint': 'sha256:' + '0'*64, 'expected_target_revision': 'recipe-v1',
            'payload': self.payload('workspace', 'task', 'step')})

    def payload(self, workspace, task_id, step_id):
        result = {field.name: getattr(self, field.name) for field in fields(self)}
        result['argv'] = list(self.argv)
        return {**result, 'tool': 'run_recipe', 'workspace': workspace, 'task_id': task_id,
                'step_id': step_id, 'network_profile': 'OFF'}


@dataclass(frozen=True, slots=True)
class SandboxRegistry:
    workspace: str
    recipes: tuple[SandboxRecipe, ...]

    def __post_init__(self):
        _identity(self.workspace)
        require(type(self.recipes) is tuple and 0 < len(self.recipes) <= 32
                and all(type(r) is SandboxRecipe for r in self.recipes)
                and len({r.recipe_id for r in self.recipes}) == len(self.recipes),
                'INVALID_SANDBOX_REGISTRY')

    def payload(self, proposal):
        require(type(proposal) is dict and set(proposal) == {'action', 'recipe_id', 'task_id', 'step_id'}
                and proposal['action'] == 'run_recipe', 'UNSUPPORTED_TOOL')
        selected = [r for r in self.recipes if r.recipe_id == proposal['recipe_id']]
        require(len(selected) == 1, 'UNAPPROVED_SANDBOX_RECIPE')
        return selected[0].payload(self.workspace, proposal['task_id'], proposal['step_id'])

    def validate(self, operation):
        parsed = SandboxOperation.parse(operation)
        payload = parsed.to_dict()['payload']
        expected = self.payload({'action': 'run_recipe', 'recipe_id': payload['recipe_id'],
                                 'task_id': payload['task_id'], 'step_id': payload['step_id']})
        require(payload == expected, 'SANDBOX_REGISTRY_BINDING')
        return parsed
